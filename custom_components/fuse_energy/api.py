"""Client for the Fuse Energy mobile API.

Every call carries ``Authorization: Bearer <access_token>`` plus the
``Device-Id`` that the session was established with. Access tokens are
short-lived, so :class:`FuseClient` refreshes transparently on a 401 and
replays the request once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .auth import FuseAuthError, FuseAuthTransient, Tokens, async_refresh_tokens
from .const import API_BASE_URL, FUSE_TIMEZONE

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_LOCAL_TZ = ZoneInfo(FUSE_TIMEZONE)

# Fields Fuse has been seen to use for an explicit bar start time. If one of
# these is present we trust it over reconstructing the time from the local
# calendar index, because an explicit instant is unambiguous across a DST
# transition and a calendar hour is not.
_TIMESTAMP_FIELDS: tuple[str, ...] = (
    "start",
    "start_at",
    "starts_at",
    "start_time",
    "timestamp",
    "datetime",
)


class FuseApiError(Exception):
    """Transport, server, or parse failure. Callers map this to UpdateFailed."""


class FuseApiAuthError(FuseApiError):
    """The session is dead and re-authentication is required. Callers map
    this to ConfigEntryAuthFailed so Home Assistant prompts for a new code."""


@dataclass(frozen=True, slots=True)
class Premises:
    """A property on the Fuse account."""

    id: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Bar:
    """One hour of metered volume and cost for a single supply.

    ``start`` is an absolute UTC instant, already resolved from Fuse's
    UK-local calendar indexing, so downstream code never has to think about
    British Summer Time again.
    """

    supply_type: str
    start: datetime
    kwh: Decimal
    cost_gbp: Decimal
    is_realised: bool

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=1)


class FuseClient:
    """Authenticated client with refresh-on-401 and token persistence."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        device_id: str,
        tokens: Tokens,
        on_tokens_rotated: Callable[[Tokens], Awaitable[None]],
    ) -> None:
        self._session = session
        self._device_id = device_id
        self._tokens = tokens
        self._on_tokens_rotated = on_tokens_rotated
        self._refresh_lock = asyncio.Lock()

    @property
    def tokens(self) -> Tokens:
        return self._tokens

    async def _async_get(self, path: str, **kwargs: Any) -> Any:
        """GET an authenticated endpoint, refreshing once if the token expired."""
        for is_retry in (False, True):
            token_used = self._tokens.access_token
            try:
                async with self._session.get(
                    f"{API_BASE_URL}{path}",
                    headers={
                        "Authorization": f"Bearer {token_used}",
                        "Device-Id": self._device_id,
                        "Accept": "application/json",
                    },
                    timeout=_TIMEOUT,
                    **kwargs,
                ) as response:
                    if response.status == 401:
                        if is_retry:
                            raise FuseApiAuthError(
                                f"{path} still returned 401 after refreshing the token"
                            )
                        await self._async_refresh(token_used)
                        continue
                    if response.status >= 500:
                        raise FuseApiError(f"Fuse returned {response.status} from {path}")
                    if response.status >= 300:
                        detail = (await response.text())[:200]
                        raise FuseApiError(
                            f"Fuse returned {response.status} from {path}: {detail}"
                        )
                    return await response.json(content_type=None)
            except aiohttp.ClientError as err:
                raise FuseApiError(f"network error calling {path}: {err}") from err

        raise FuseApiError(f"exhausted retries calling {path}")  # pragma: no cover

    async def _async_refresh(self, token_used: str) -> None:
        """Rotate the token pair, once, even if several polls raced into a 401.

        The guard compares against the token the caller actually sent: if it
        no longer matches, somebody else refreshed while we waited on the
        lock and our job is already done.
        """
        async with self._refresh_lock:
            if self._tokens.access_token != token_used:
                return
            try:
                rotated = await async_refresh_tokens(
                    self._session, device_id=self._device_id, tokens=self._tokens
                )
            except FuseAuthError as err:
                raise FuseApiAuthError(str(err)) from err
            except FuseAuthTransient as err:
                raise FuseApiError(str(err)) from err
            # Persist before swapping in memory: a crash between the two must
            # not leave the config entry holding a refresh token Fuse has
            # already invalidated, which would need a full re-authentication.
            await self._on_tokens_rotated(rotated)
            self._tokens = rotated

    async def async_list_premises(self) -> list[Premises]:
        """List the properties on the account."""
        payload = await self._async_get("/api/v2/customer/premises")
        if not isinstance(payload, list):
            raise FuseApiError(
                f"expected a list of premises, got {type(payload).__name__}"
            )

        premises: list[Premises] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            inner = entry.get("premises") or {}
            if premises_id := inner.get("id"):
                premises.append(
                    Premises(
                        id=str(premises_id),
                        name=inner.get("address_line_1") or inner.get("name"),
                    )
                )

        if not premises:
            raise FuseApiError("the Fuse account has no premises attached")
        return premises

    async def async_fetch_day(self, premises_id: str, day: date) -> list[Bar]:
        """Fetch every supply's hourly bars for one UK-local calendar day."""
        payload = await self._async_get(
            f"/api/v1/premises/{premises_id}/chart",
            params={"year": day.year, "month": day.month, "day": day.day},
        )
        if not isinstance(payload, dict):
            raise FuseApiError(f"expected a chart object, got {type(payload).__name__}")
        return _parse_chart(payload, day)


def _parse_chart(payload: dict[str, Any], day: date) -> list[Bar]:
    """Extract bars for ``day`` from a chart response.

    Fuse groups bars under ``supplies``, each tagged with a ``supply_type``
    such as ELEC_IMPORT, ELEC_EXPORT or GAS. We deliberately do not filter on
    that tag: whatever supplies the account has, we surface. The response can
    also carry padding bars from adjacent days, so each one is checked against
    the day we asked for.
    """
    bars: list[Bar] = []

    for supply in payload.get("supplies") or ():
        if not isinstance(supply, dict):
            continue
        supply_type = supply.get("supply_type")
        if not supply_type:
            continue

        # Fuse can repeat a local hour on the October clock-back. Counting
        # how many times each calendar hour has been seen lets the second
        # occurrence resolve to the post-transition (GMT) instant instead of
        # silently colliding with the first.
        seen_hours: dict[int, int] = {}
        raw_bars = supply.get("bars") or ()

        for entry in raw_bars:
            if not isinstance(entry, dict):
                continue
            bar = entry.get("bar") or {}
            index = bar.get("index") or {}

            if (index.get("year"), index.get("month"), index.get("day")) != (
                day.year,
                day.month,
                day.day,
            ):
                continue

            kwh = _as_decimal(bar.get("kWh", bar.get("kwh")))
            cost = _as_decimal((bar.get("money") or {}).get("amount"))
            if kwh is None or cost is None:
                continue

            hour = _as_int(index.get("hour"))
            if hour is None:
                continue

            occurrence = seen_hours.get(hour, 0)
            seen_hours[hour] = occurrence + 1

            start = _resolve_start(bar, day, hour, occurrence)
            if start is None:
                continue

            bars.append(
                Bar(
                    supply_type=str(supply_type),
                    start=start,
                    kwh=kwh,
                    cost_gbp=cost,
                    is_realised=bar.get("type") == "REALISED",
                )
            )

    bars.sort(key=lambda item: (item.supply_type, item.start))
    return bars


def _resolve_start(
    bar: dict[str, Any], day: date, hour: int, occurrence: int
) -> datetime | None:
    """Work out the absolute UTC instant a bar starts at.

    Prefers an explicit timestamp from the payload. Failing that, rebuilds
    the instant from the UK-local calendar hour, using ``occurrence`` to pick
    the right side of an autumn DST transition (fold=0 is still BST, fold=1
    is GMT). On every other day of the year fold is irrelevant and this is
    just a plain local-to-UTC conversion.
    """
    for field in _TIMESTAMP_FIELDS:
        if (raw := bar.get(field)) and isinstance(raw, str):
            if (parsed := _parse_iso(raw)) is not None:
                return parsed.astimezone(UTC)

    try:
        local = datetime(
            day.year, day.month, day.day, hour, tzinfo=_LOCAL_TZ, fold=min(occurrence, 1)
        )
    except ValueError:
        _LOGGER.debug("Discarding bar with an impossible hour: %s", hour)
        return None
    return local.astimezone(UTC)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 string, tolerating a trailing Z and assuming UK
    local time when no offset is given."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_LOCAL_TZ)


def _as_decimal(value: Any) -> Decimal | None:
    """Convert to Decimal via str so float inputs do not smuggle in binary
    rounding error before the value reaches the statistics table."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
