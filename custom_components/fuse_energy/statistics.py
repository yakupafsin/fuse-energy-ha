"""Write Fuse's hourly bars into Home Assistant's long-term statistics.

We use the *external* statistics API rather than ordinary sensor history.
That matters for two reasons:

* Fuse publishes hours late, and often revises them afterwards. A sensor can
  only ever record "now", so backdated data has nowhere to go. External
  statistics can be written at any point in the past and overwritten later.
* It keeps the Energy dashboard reading true historical values instead of a
  reconstruction of whenever Home Assistant happened to be polling.

Statistics rows carry a running ``sum`` and the Energy dashboard renders each
hour as the difference between consecutive sums. A row written with a sum
that does not follow from its predecessor shows up as a spurious spike or a
negative bar, so the rule this module follows is: **rewrite a contiguous
range in one pass, anchored to the cumulative sum immediately before it.**
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from decimal import Decimal
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .api import Bar
from .const import DOMAIN, statistic_id_cost, statistic_id_energy

_LOGGER = logging.getLogger(__name__)

# How far back to hunt for the cumulative sum preceding a rewrite. The
# coordinator re-fetches only a day or two in steady state, so the anchor is
# normally the row immediately before. A window this wide simply means an
# outage has to last over a month before the baseline is lost.
_ANCHOR_LOOKBACK = timedelta(days=35)

# Currency is per-account rather than per-reading; Fuse is UK-only. Money has
# no unit converter, so its unit_class is None; energy converts via "energy".
_CURRENCY = "GBP"
_UNIT_CLASS_ENERGY = "energy"

_SUPPLY_LABELS: dict[str, str] = {
    "ELEC_IMPORT": "electricity import",
    "ELEC_EXPORT": "electricity export",
    "GAS": "gas",
}


def _describe(supply_type: str) -> str:
    """Human-readable name for a supply type, for the statistics UI."""
    return _SUPPLY_LABELS.get(supply_type, supply_type.replace("_", " ").lower())


async def async_import_bars(
    hass: HomeAssistant,
    premises_id: str,
    bars: Iterable[Bar],
) -> None:
    """Import settled bars, one statistics series per supply and measure.

    Forecast bars are dropped rather than written as zeroes: Fuse promotes
    them to REALISED once the meter reports, and a later poll picks them up.
    """
    settled = [bar for bar in bars if bar.is_realised]
    if not settled:
        return

    by_supply: dict[str, list[Bar]] = {}
    for bar in settled:
        by_supply.setdefault(bar.supply_type, []).append(bar)

    for supply_type, supply_bars in by_supply.items():
        label = _describe(supply_type)
        await _async_write_series(
            hass,
            statistic_id=statistic_id_energy(premises_id, supply_type),
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            unit_class=_UNIT_CLASS_ENERGY,
            name=f"Fuse {label}",
            bars=supply_bars,
            value_of=lambda bar: bar.kwh,
        )
        await _async_write_series(
            hass,
            statistic_id=statistic_id_cost(premises_id, supply_type),
            unit=_CURRENCY,
            unit_class=None,
            name=f"Fuse {label} cost",
            bars=supply_bars,
            value_of=lambda bar: bar.cost_gbp,
        )


async def _async_write_series(
    hass: HomeAssistant,
    *,
    statistic_id: str,
    unit: str,
    unit_class: str | None,
    name: str,
    bars: list[Bar],
    value_of: Callable[[Bar], Decimal],
) -> None:
    """Rebuild one statistics series across the span the bars cover.

    Every bar handed in is written, whether or not it is already on record.
    ``async_add_external_statistics`` upserts on (statistic_id, start), so
    re-writing an hour replaces it -- which is exactly what we want when Fuse
    revises a value after the fact.
    """
    if not bars:
        return

    ordered = sorted(bars, key=lambda bar: bar.start)

    # De-duplicate defensively. Two rows sharing a start would each contribute
    # to the running sum, permanently inflating every later hour in the series.
    deduped: list[Bar] = []
    for bar in ordered:
        if deduped and deduped[-1].start == bar.start:
            deduped[-1] = bar  # keep the later reading for this hour
            continue
        deduped.append(bar)

    running = await _async_sum_before(hass, statistic_id, deduped[0].start)

    rows: list[StatisticData] = []
    for bar in deduped:
        value = float(value_of(bar))
        running += value
        rows.append(StatisticData(start=bar.start, state=value, sum=running))

    metadata: StatisticMetaData = {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_class": unit_class,
        "unit_of_measurement": unit,
    }
    async_add_external_statistics(hass, metadata, rows)
    _LOGGER.debug("Wrote %d rows to %s", len(rows), statistic_id)


async def _async_sum_before(
    hass: HomeAssistant, statistic_id: str, boundary: datetime
) -> float:
    """Cumulative sum of the last row starting strictly before ``boundary``.

    Returns 0.0 when the series has no earlier data, which is the correct
    baseline for a first import.
    """
    recorder = get_instance(hass)

    latest = await recorder.async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    rows = latest.get(statistic_id) or []
    if not rows:
        return 0.0

    # Fast path: the newest row on record already predates the rewrite, so
    # nothing sits between it and our boundary.
    if float(rows[0]["start"]) < boundary.timestamp():
        return float(rows[0]["sum"] or 0.0)

    # Otherwise the series extends into (or past) the range we are rewriting,
    # and we need the last row before the boundary specifically.
    window = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        boundary - _ANCHOR_LOOKBACK,
        boundary,
        {statistic_id},
        "hour",
        None,
        {"sum"},
    )
    preceding = window.get(statistic_id) or []
    if not preceding:
        _LOGGER.debug(
            "No anchor row within %s before %s for %s; restarting the sum at zero",
            _ANCHOR_LOOKBACK,
            boundary,
            statistic_id,
        )
        return 0.0
    return float(preceding[-1].get("sum") or 0.0)
