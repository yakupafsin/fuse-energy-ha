"""Phone-OTP authentication against the Fuse Energy mobile API.

Fuse has no username/password and no OAuth; the mobile app signs in with a
phone number and a six-digit SMS code, and may then ask identity questions
(date of birth, postcode) before it hands over tokens.

The flow is three-legged and the middle leg is conditional:

    INITIAL ---> PHONE_OTP ---> AUTHORIZED
                     |
                     +--------> ADDITIONAL_INFO ---> AUTHORIZED

Every leg is a POST to the same /api/v3/auth endpoint, distinguished by a
``challenge_type`` field, and carries an ``auth_flow_token`` forward as a
bearer credential. :class:`FuseAuthFlow` holds that token so callers only
have to think about the steps.

One wrinkle worth knowing: the INITIAL call does *not* send the SMS. It only
mints the flow token. A second, unauthenticated call to the *website's* tRPC
endpoint is what actually dispatches the message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import API_BASE_URL, WEB_APP_VERSION, WEB_BASE_URL

_TIMEOUT = aiohttp.ClientTimeout(total=20)


class FuseAuthError(Exception):
    """Authentication failed in a way that needs the user to do something:
    a wrong code, an expired flow, a revoked refresh token."""

    def __init__(self, message: str, *, code: str = "unknown") -> None:
        super().__init__(message)
        self.code = code


class FuseAuthTransient(Exception):
    """A server-side or network failure. Retrying later is reasonable."""


@dataclass(frozen=True, slots=True)
class Tokens:
    """An access/refresh pair. Both rotate together on every refresh."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class IdentityQuestion:
    """One question from an ADDITIONAL_INFO challenge."""

    key: str
    title: str
    kind: str  # "DATE" or "TEXT"; treat anything unrecognised as TEXT.


@dataclass(frozen=True, slots=True)
class Authorized:
    """Terminal success state."""

    tokens: Tokens


@dataclass(frozen=True, slots=True)
class NeedsIdentity:
    """Fuse wants identity answers before it will issue tokens."""

    title: str
    subtitle: str
    questions: list[IdentityQuestion]


ChallengeResult = Authorized | NeedsIdentity


async def _post_auth(
    session: aiohttp.ClientSession,
    body: dict[str, Any],
    *,
    device_id: str,
    bearer: str | None = None,
) -> dict[str, Any]:
    """POST one leg of the /api/v3/auth state machine.

    Fuse reports business failures (bad code, expired flow) as 4xx with a
    ``status_string`` naming the reason, which we surface as
    :attr:`FuseAuthError.code` so the config flow can show a specific message.
    """
    headers = {"Content-Type": "application/json", "Device-Id": device_id}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    try:
        async with session.post(
            f"{API_BASE_URL}/api/v3/auth",
            json=body,
            headers=headers,
            timeout=_TIMEOUT,
        ) as response:
            if response.status >= 500:
                raise FuseAuthTransient(f"Fuse returned {response.status} from /api/v3/auth")
            payload = await _json_or_empty(response)
            if response.status < 300:
                return payload
            raise FuseAuthError(
                f"/api/v3/auth rejected the request with HTTP {response.status}",
                code=str(payload.get("status_string") or "unknown"),
            )
    except aiohttp.ClientError as err:
        raise FuseAuthTransient(f"network error talking to Fuse: {err}") from err


async def _json_or_empty(response: aiohttp.ClientResponse) -> dict[str, Any]:
    """Fuse occasionally answers an error with an empty or non-JSON body.
    Returning {} keeps the error path from turning into a parse traceback
    that hides the real status code."""
    try:
        parsed = await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _interpret(payload: dict[str, Any]) -> ChallengeResult:
    """Turn a challenge response into either tokens or a question set."""
    challenge = payload.get("challenge_type")
    data = payload.get("data") or {}

    if challenge == "AUTHORIZED":
        try:
            return Authorized(
                tokens=Tokens(
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                )
            )
        except KeyError as err:
            raise FuseAuthError(
                "Fuse said AUTHORIZED but omitted a token", code="bad_response"
            ) from err

    if challenge == "ADDITIONAL_INFO":
        return NeedsIdentity(
            title=data.get("title", ""),
            subtitle=data.get("subtitle", ""),
            questions=[
                IdentityQuestion(
                    key=question["key"],
                    title=question.get("title") or question["key"],
                    kind=question.get("type", "TEXT"),
                )
                for question in (data.get("questions") or [])
                if question.get("key")
            ],
        )

    raise FuseAuthError(
        f"Fuse asked for a challenge we do not implement: {challenge!r}",
        code="unsupported_challenge",
    )


class FuseAuthFlow:
    """Carries the short-lived ``auth_flow_token`` across the sign-in legs.

    Create one per sign-in attempt. It is not reusable once authorized, and
    the token it holds expires within minutes.
    """

    def __init__(self, session: aiohttp.ClientSession, *, device_id: str) -> None:
        self._session = session
        self._device_id = device_id
        self._flow_token: str | None = None

    async def async_request_code(self, phone_number: str) -> None:
        """Start the flow and get an SMS on its way.

        Two calls, because Fuse splits them: the mobile endpoint mints the
        flow token but stays silent, and the website endpoint is what tells
        the SMS gateway to send anything.
        """
        payload = await _post_auth(
            self._session,
            {
                "challenge_type": "INITIAL",
                "data": {
                    "method": "PHONE",
                    "data": {
                        "phone_number": phone_number,
                        "prelude_dispatch_id": None,
                    },
                },
            },
            device_id=self._device_id,
        )

        flow_token = payload.get("auth_flow_token")
        if not flow_token:
            raise FuseAuthError(
                "Fuse started the sign-in but issued no auth_flow_token",
                code="bad_response",
            )
        self._flow_token = flow_token

        await self._async_dispatch_sms(phone_number)

    async def _async_dispatch_sms(self, phone_number: str) -> None:
        """Ask www.fuseenergy.com to actually send the code.

        This one is unauthenticated but version-gated: it inspects
        x-fuse-app-version and refuses clients it considers stale.
        """
        try:
            async with self._session.post(
                f"{WEB_BASE_URL}/api/trpc/phoneSignIn",
                json={"phone": phone_number},
                headers={
                    "Content-Type": "application/json",
                    "x-fuse-app-version": WEB_APP_VERSION,
                },
                timeout=_TIMEOUT,
            ) as response:
                if response.status < 300:
                    return
                if response.status >= 500:
                    raise FuseAuthTransient(
                        f"Fuse's website returned {response.status} dispatching the SMS"
                    )
                payload = await _json_or_empty(response)
                code = (payload.get("error") or {}).get("code") or "sms_dispatch_failed"
                raise FuseAuthError(
                    "Fuse declined to send the verification SMS", code=str(code)
                )
        except aiohttp.ClientError as err:
            raise FuseAuthTransient(f"network error dispatching the SMS: {err}") from err

    async def async_submit_code(self, code: str) -> ChallengeResult:
        """Answer the SMS challenge with the six-digit code."""
        return await self._async_advance(
            {"challenge_type": "PHONE_OTP", "data": {"code": code}}
        )

    async def async_submit_identity(self, answers: dict[str, str]) -> ChallengeResult:
        """Answer an ADDITIONAL_INFO challenge.

        ``answers`` is keyed by :attr:`IdentityQuestion.key`; anything Fuse
        typed as DATE must be formatted YYYY-MM-DD.
        """
        return await self._async_advance(
            {"challenge_type": "ADDITIONAL_INFO", "data": {"responses": answers}}
        )

    async def _async_advance(self, body: dict[str, Any]) -> ChallengeResult:
        if not self._flow_token:
            raise FuseAuthError(
                "sign-in step attempted before the flow was started",
                code="flow_not_started",
            )
        payload = await _post_auth(
            self._session,
            body,
            device_id=self._device_id,
            bearer=self._flow_token,
        )
        # Fuse reissues the flow token between legs; keep the newest one so a
        # follow-up ADDITIONAL_INFO step authenticates with the right credential.
        if refreshed := payload.get("auth_flow_token"):
            self._flow_token = refreshed
        return _interpret(payload)


async def async_refresh_tokens(
    session: aiohttp.ClientSession,
    *,
    device_id: str,
    tokens: Tokens,
) -> Tokens:
    """Exchange an expiring token pair for a fresh one.

    Fuse wants *both* halves: the outgoing access token in the Authorization
    header and the refresh token in the body. Sending only the refresh token
    is rejected. Both values rotate, so the result must be persisted before
    the old pair is discarded.
    """
    try:
        async with session.post(
            f"{API_BASE_URL}/api/v1/auth/refresh",
            json={
                "refresh_token": tokens.refresh_token,
                "original_request_path": None,
            },
            headers={
                "Content-Type": "application/json",
                "Device-Id": device_id,
                "Authorization": f"Bearer {tokens.access_token}",
            },
            timeout=_TIMEOUT,
        ) as response:
            if response.status >= 500:
                raise FuseAuthTransient(
                    f"Fuse returned {response.status} refreshing the token"
                )
            payload = await _json_or_empty(response)
            if response.status >= 300:
                raise FuseAuthError(
                    f"Fuse refused to refresh the session (HTTP {response.status})",
                    code=str(payload.get("status_string") or "refresh_failed"),
                )
            try:
                return Tokens(
                    access_token=payload["access_token"],
                    refresh_token=payload["refresh_token"],
                )
            except KeyError as err:
                raise FuseAuthError(
                    "Fuse's refresh response was missing a token", code="bad_response"
                ) from err
    except aiohttp.ClientError as err:
        raise FuseAuthTransient(f"network error refreshing the token: {err}") from err
