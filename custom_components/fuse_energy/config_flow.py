"""Config flow for Fuse Energy.

Mirrors the app's sign-in: phone number, SMS code, and -- only when Fuse asks
-- a couple of identity questions. The set of questions is server-defined, so
that step builds its form at runtime from whatever Fuse sent back.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import FuseApiError, FuseClient
from .auth import (
    Authorized,
    FuseAuthError,
    FuseAuthFlow,
    FuseAuthTransient,
    FuseSmsNotSent,
    IdentityQuestion,
    NeedsIdentity,
    Tokens,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_PHONE_NUMBER,
    CONF_PREMISES_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Reasons Fuse gives for refusing to send the code that we can turn into
# specific advice. Anything not listed falls through to the generic message and
# is logged at warning level, so a code we have never seen stays visible rather
# than being flattened into "try again" -- which is how the silent failure
# behind issue #6 went unnoticed in the first place.
_SMS_REFUSALS: dict[str, str] = {
    "incorrect_phone_number": "invalid_phone",
    "issue_otp_premature_retry": "sms_too_soon",
}

# Fuse expects E.164. Nudging the user here avoids a round-trip through a
# server-side validation error that only says "422".
_PHONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE_NUMBER): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEL)
        )
    }
)

_CODE_SCHEMA = vol.Schema({vol.Required("code"): str})


class FuseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle sign-in and re-authentication."""

    VERSION = 1

    def __init__(self) -> None:
        self._auth: FuseAuthFlow | None = None
        self._device_id: str = ""
        self._phone_number: str = ""
        self._questions: list[IdentityQuestion] = []
        self._identity_prompt: str = ""
        self._tokens: Tokens | None = None
        self._reauth_premises_id: str | None = None
        self._premises_choices: list[Any] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the phone number and ask Fuse to text a code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._phone_number = user_input[CONF_PHONE_NUMBER].strip()
            # A stable per-entry device id: Fuse ties sessions to it, and
            # reusing one across installs would invalidate the other's tokens.
            self._device_id = self._device_id or str(uuid.uuid4())
            self._auth = FuseAuthFlow(
                async_get_clientsession(self.hass), device_id=self._device_id
            )
            try:
                await self._auth.async_request_code(self._phone_number)
            except FuseAuthTransient as err:
                _LOGGER.debug("Transient failure requesting a code: %s", err)
                errors["base"] = "cannot_connect"
            # Which leg failed decides what is true to tell the user, and only
            # auth.py knows that -- the two legs report errors in different
            # vocabularies. Reaching FuseSmsNotSent means the number was good
            # enough to start a flow, so blaming the number would be wrong;
            # a failure from the first leg is almost always the number itself.
            except FuseSmsNotSent as err:
                if explained := _SMS_REFUSALS.get(err.code or ""):
                    _LOGGER.debug("Fuse declined to send the SMS: %s", err)
                    errors["base"] = explained
                else:
                    _LOGGER.warning("Fuse did not send the verification SMS: %s", err)
                    errors["base"] = "sms_not_sent"
            except FuseAuthError as err:
                _LOGGER.debug("Fuse would not start the sign-in: %s", err)
                errors["base"] = (
                    "cannot_connect" if err.code == "bad_response" else "invalid_phone"
                )
            else:
                return await self.async_step_code()

        return self.async_show_form(
            step_id="user", data_schema=_PHONE_SCHEMA, errors=errors
        )

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Submit the six-digit code from the SMS."""
        errors: dict[str, str] = {}
        assert self._auth is not None

        if user_input is not None:
            try:
                result = await self._auth.async_submit_code(user_input["code"].strip())
            except FuseAuthTransient:
                errors["base"] = "cannot_connect"
            except FuseAuthError as err:
                _LOGGER.debug("Code rejected: %s", err)
                errors["base"] = "invalid_code"
            else:
                return await self._async_handle_challenge(result)

        return self.async_show_form(
            step_id="code",
            data_schema=_CODE_SCHEMA,
            errors=errors,
            description_placeholders={"phone_number": self._phone_number},
        )

    async def async_step_identity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Answer the identity questions Fuse asked for."""
        errors: dict[str, str] = {}
        assert self._auth is not None

        if user_input is not None:
            answers = {
                question.key: str(user_input[question.key]).strip()
                for question in self._questions
                if user_input.get(question.key) is not None
            }
            try:
                result = await self._auth.async_submit_identity(answers)
            except FuseAuthTransient:
                errors["base"] = "cannot_connect"
            except FuseAuthError as err:
                _LOGGER.debug("Identity answers rejected: %s", err)
                errors["base"] = "invalid_identity"
            else:
                return await self._async_handle_challenge(result)

        return self.async_show_form(
            step_id="identity",
            data_schema=self._identity_schema(),
            errors=errors,
            description_placeholders={"prompt": self._identity_prompt},
        )

    def _identity_schema(self) -> vol.Schema:
        """Build the form Fuse asked for. DATE questions get a date picker so
        the value arrives in the YYYY-MM-DD shape the API demands."""
        fields: dict[Any, Any] = {}
        for question in self._questions:
            key = vol.Required(question.key)
            if question.kind == "DATE":
                fields[key] = selector.DateSelector()
            else:
                fields[key] = selector.TextSelector()
        return vol.Schema(fields)

    async def _async_handle_challenge(self, result: Any) -> ConfigFlowResult:
        """Route the outcome of a challenge to the next step."""
        if isinstance(result, NeedsIdentity):
            self._questions = result.questions
            self._identity_prompt = " ".join(
                part for part in (result.title, result.subtitle) if part
            )
            if not self._questions:
                return self.async_abort(reason="unsupported_challenge")
            return await self.async_step_identity()

        if isinstance(result, Authorized):
            self._tokens = result.tokens
            return await self._async_finish()

        return self.async_abort(reason="unsupported_challenge")

    async def _async_finish(self) -> ConfigFlowResult:
        """Look up the account's premises and create (or update) the entry."""
        assert self._tokens is not None

        async def _discard(_: Tokens) -> None:
            """Tokens may rotate during discovery; nothing to persist yet."""

        client = FuseClient(
            async_get_clientsession(self.hass),
            device_id=self._device_id,
            tokens=self._tokens,
            on_tokens_rotated=_discard,
        )
        try:
            premises = await client.async_list_premises()
        except FuseApiError as err:
            _LOGGER.debug("Could not list premises: %s", err)
            return self.async_abort(reason="no_premises")

        # Re-authentication must land on the same premises it started with,
        # otherwise the entry would silently point at a different property.
        if self._reauth_premises_id is not None:
            if all(item.id != self._reauth_premises_id for item in premises):
                return self.async_abort(reason="wrong_account")
            return await self._async_commit(self._reauth_premises_id)

        if len(premises) == 1:
            return await self._async_commit(premises[0].id, premises[0].name)

        self._premises_choices = premises
        return await self.async_step_premises()

    async def async_step_premises(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a property when the account has more than one."""
        if user_input is not None:
            chosen = user_input[CONF_PREMISES_ID]
            name = next(
                (item.name for item in self._premises_choices if item.id == chosen),
                None,
            )
            return await self._async_commit(chosen, name)

        options = [
            selector.SelectOptionDict(value=item.id, label=item.name or item.id)
            for item in self._premises_choices
        ]
        return self.async_show_form(
            step_id="premises",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PREMISES_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def _async_commit(
        self, premises_id: str, name: str | None = None
    ) -> ConfigFlowResult:
        """Persist the session. One config entry per premises."""
        assert self._tokens is not None

        await self.async_set_unique_id(premises_id)
        data = {
            CONF_PHONE_NUMBER: self._phone_number,
            CONF_DEVICE_ID: self._device_id,
            CONF_ACCESS_TOKEN: self._tokens.access_token,
            CONF_REFRESH_TOKEN: self._tokens.refresh_token,
            CONF_PREMISES_ID: premises_id,
        }

        if self._reauth_premises_id is not None:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=data
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=name or "Fuse Energy", data=data)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Fuse invalidated the session; sign in again."""
        self._reauth_premises_id = entry_data.get(CONF_PREMISES_ID)
        self._phone_number = entry_data.get(CONF_PHONE_NUMBER, "")
        # Keep the original device id: Fuse treats a new one as a new device,
        # which can trigger extra identity checks on every re-auth.
        self._device_id = entry_data.get(CONF_DEVICE_ID, "") or str(uuid.uuid4())
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm before we make Fuse send another SMS."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
                description_placeholders={"phone_number": self._phone_number},
            )
        return await self.async_step_user({CONF_PHONE_NUMBER: self._phone_number})
