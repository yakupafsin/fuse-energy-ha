"""Polling coordinator for Fuse Energy.

Each tick does three things: work out how far back history needs repairing,
pull that range of hourly bars, and hand them to the statistics writer in a
single contiguous batch. It also derives a small live snapshot for the
sensor platform, since statistics alone give the Energy dashboard what it
needs but leave nothing to put on a card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
import logging
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Bar, FuseApiAuthError, FuseApiError, FuseClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUSE_TIMEZONE,
    INITIAL_BACKFILL_DAYS,
    statistic_id_energy,
)
from .statistics import async_import_bars

_LOGGER = logging.getLogger(__name__)
_LOCAL_TZ = ZoneInfo(FUSE_TIMEZONE)

# Always re-pull at least this much, so the statistics writer can correct
# hours Fuse has revised since the last poll.
_MINIMUM_REFETCH = timedelta(days=2)


@dataclass(frozen=True, slots=True)
class SupplySnapshot:
    """Live view of one supply, for the sensor platform."""

    supply_type: str
    last_hour_start: datetime | None = None
    last_hour_kwh: float | None = None
    last_hour_cost: float | None = None
    today_kwh: float = 0.0
    today_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class FuseData:
    """Everything one poll produced."""

    premises_id: str
    supplies: dict[str, SupplySnapshot] = field(default_factory=dict)


class FuseCoordinator(DataUpdateCoordinator[FuseData]):
    """Fetches Fuse bars and keeps long-term statistics in step."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: FuseClient,
        *,
        premises_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.premises_id = premises_id

    async def _async_update_data(self) -> FuseData:
        try:
            return await self._async_poll()
        except FuseApiAuthError as err:
            # Surfaces a "re-authenticate" prompt in the UI rather than
            # retrying a session Fuse has already invalidated.
            raise ConfigEntryAuthFailed(str(err)) from err
        except FuseApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_poll(self) -> FuseData:
        now = datetime.now(UTC)
        today = now.astimezone(_LOCAL_TZ).date()

        # Today first: it tells us which supplies this premises actually has,
        # which in turn tells us which statistics series to consult when
        # deciding how far back to reach.
        todays_bars = await self.client.async_fetch_day(self.premises_id, today)
        supply_types = {bar.supply_type for bar in todays_bars}

        start = await self._async_resume_from(supply_types, today)

        bars = list(todays_bars)
        day = start
        while day < today:
            bars.extend(await self.client.async_fetch_day(self.premises_id, day))
            day += timedelta(days=1)

        # Fuse reports the hour in progress as though it were settled, with a
        # value that keeps climbing. Writing it would put a misleadingly small
        # bar on the dashboard, so only fully elapsed hours are imported.
        elapsed = [bar for bar in bars if bar.end <= now]

        if elapsed:
            # One call for the whole range: the writer chains each series'
            # running sum, and splitting the range would restart that chain
            # partway through and corrupt the totals.
            await async_import_bars(self.hass, self.premises_id, elapsed)
        else:
            _LOGGER.debug("No fully elapsed bars available yet for %s", self.premises_id)

        return FuseData(
            premises_id=self.premises_id,
            supplies=_summarise(elapsed, today),
        )

    async def _async_resume_from(self, supply_types: set[str], today: date) -> date:
        """Earliest day worth re-fetching.

        A supply with no statistics at all is new and gets the full backfill.
        Otherwise we resume from the oldest "last imported" across supplies,
        never trusting less than the minimum refetch window.
        """
        if not supply_types:
            return today - timedelta(days=INITIAL_BACKFILL_DAYS)

        newest_per_supply: list[date] = []
        for supply_type in supply_types:
            imported = await self._async_last_imported(supply_type)
            if imported is None:
                return today - timedelta(days=INITIAL_BACKFILL_DAYS)
            newest_per_supply.append(imported)

        return min(min(newest_per_supply), today - _MINIMUM_REFETCH)

    async def _async_last_imported(self, supply_type: str) -> date | None:
        """Local date of the most recent hour already in statistics."""
        statistic_id = statistic_id_energy(self.premises_id, supply_type)
        result = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, set()
        )
        rows = result.get(statistic_id) or []
        if not rows:
            return None
        start = datetime.fromtimestamp(float(rows[0]["start"]), tz=UTC)
        return start.astimezone(_LOCAL_TZ).date()


def _summarise(bars: list[Bar], today: date) -> dict[str, SupplySnapshot]:
    """Reduce settled bars to per-supply sensor values."""
    snapshots: dict[str, SupplySnapshot] = {}

    by_supply: dict[str, list[Bar]] = {}
    for bar in bars:
        if bar.is_realised:
            by_supply.setdefault(bar.supply_type, []).append(bar)

    for supply_type, supply_bars in by_supply.items():
        supply_bars.sort(key=lambda item: item.start)
        latest = supply_bars[-1]
        todays = [
            bar
            for bar in supply_bars
            if bar.start.astimezone(_LOCAL_TZ).date() == today
        ]
        snapshots[supply_type] = SupplySnapshot(
            supply_type=supply_type,
            last_hour_start=latest.start,
            last_hour_kwh=float(latest.kwh),
            last_hour_cost=float(latest.cost_gbp),
            today_kwh=float(sum(bar.kwh for bar in todays)),
            today_cost=float(sum(bar.cost_gbp for bar in todays)),
        )

    return snapshots
