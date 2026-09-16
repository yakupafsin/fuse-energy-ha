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
    # The hour currently in progress. Fuse publishes it as REALISED with a
    # value that climbs as the meter reports, so it is kept out of statistics
    # -- but it IS counted in the daily totals below, which is what keeps them
    # level with the Fuse app instead of trailing it by up to an hour.
    current_hour_start: datetime | None = None
    current_hour_kwh: float | None = None
    current_hour_cost: float | None = None


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
        elapsed = _settled(bars, now)

        # That same unsettled bar is still worth showing: it is most of why the
        # Fuse app looks ahead of Home Assistant. It reaches the sensors only.
        in_progress = _in_progress(bars, now)

        if elapsed:
            # One call for the whole range: the writer chains each series'
            # running sum, and splitting the range would restart that chain
            # partway through and corrupt the totals.
            await async_import_bars(self.hass, self.premises_id, elapsed)
        else:
            _LOGGER.debug("No fully elapsed bars available yet for %s", self.premises_id)

        return FuseData(
            premises_id=self.premises_id,
            supplies=_summarise(elapsed, in_progress, today),
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


def _settled(bars: list[Bar], now: datetime) -> list[Bar]:
    """Bars whose hour has fully elapsed.

    The one gate between Fuse's still-climbing current hour and long-term
    statistics, so it is a named function with its own tests rather than a
    comprehension buried in the poll.
    """
    return [bar for bar in bars if bar.end <= now]


def _in_progress(bars: list[Bar], now: datetime) -> list[Bar]:
    """Bars covering ``now`` -- the hour Fuse is still metering, at most one
    per supply."""
    return [bar for bar in bars if bar.start <= now < bar.end]


def _summarise(
    settled: list[Bar], in_progress: list[Bar], today: date
) -> dict[str, SupplySnapshot]:
    """Reduce bars to per-supply sensor values.

    ``settled`` drives the last-hour figures. ``in_progress`` supplies the
    current-hour fields and is also counted into the daily totals, so "today"
    means today so far -- the same thing the Fuse app shows -- rather than
    today up to the last hour that closed.

    Long-term statistics are unaffected: they are written from ``settled``
    alone, in :func:`_async_poll`, and never see the unfinished hour.
    """
    snapshots: dict[str, SupplySnapshot] = {}

    by_supply: dict[str, list[Bar]] = {}
    for bar in settled:
        if bar.is_realised:
            by_supply.setdefault(bar.supply_type, []).append(bar)

    # Fuse marks an hour it has no readings for yet as FORECASTED, so an
    # unrealised bar is a prediction rather than a partial measurement and is
    # dropped. A supply whose first bar of the day is the one in progress has
    # nothing in ``settled``, so seed an entry for it here too.
    current: dict[str, Bar] = {}
    for bar in in_progress:
        if bar.is_realised:
            current[bar.supply_type] = bar
            by_supply.setdefault(bar.supply_type, [])

    for supply_type, supply_bars in by_supply.items():
        supply_bars.sort(key=lambda item: item.start)
        latest = supply_bars[-1] if supply_bars else None
        todays = [
            bar
            for bar in supply_bars
            if bar.start.astimezone(_LOCAL_TZ).date() == today
        ]
        live = current.get(supply_type)
        # A completed hour is never smaller than the partial reading it
        # replaces, so when the hour closes its settled bar simply lands in
        # ``todays`` in place of this one and the running total does not jump
        # backwards. ``_settled`` and ``_in_progress`` are disjoint, so the
        # hour cannot be counted twice on the way through.
        if live is not None and live.start.astimezone(_LOCAL_TZ).date() == today:
            todays = [*todays, live]

        snapshots[supply_type] = SupplySnapshot(
            supply_type=supply_type,
            last_hour_start=latest.start if latest else None,
            last_hour_kwh=float(latest.kwh) if latest else None,
            last_hour_cost=float(latest.cost_gbp) if latest else None,
            today_kwh=float(sum(bar.kwh for bar in todays)),
            today_cost=float(sum(bar.cost_gbp for bar in todays)),
            current_hour_start=live.start if live else None,
            current_hour_kwh=float(live.kwh) if live else None,
            current_hour_cost=float(live.cost_gbp) if live else None,
        )

    return snapshots
