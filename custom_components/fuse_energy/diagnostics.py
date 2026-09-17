"""Diagnostics for Fuse Energy.

Fuse's API is undocumented and changes without notice, so the most useful
thing a diagnostics dump can do is show what the account actually returned.
Tokens and the phone number are withheld -- they are enough to take over the
account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from . import FuseConfigEntry
from .api import FuseApiError
from .const import FUSE_TIMEZONE, statistic_id_cost, statistic_id_energy

_LOCAL_TZ = ZoneInfo(FUSE_TIMEZONE)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FuseConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    premises_id = coordinator.premises_id
    today = datetime.now(UTC).astimezone(_LOCAL_TZ).date()

    supplies: dict[str, Any] = {}
    if coordinator.data is not None:
        for supply_type, snapshot in coordinator.data.supplies.items():
            supplies[supply_type] = {
                "last_hour_start": (
                    snapshot.last_hour_start.isoformat()
                    if snapshot.last_hour_start
                    else None
                ),
                "last_hour_kwh": snapshot.last_hour_kwh,
                "last_hour_cost": snapshot.last_hour_cost,
                "current_hour_start": (
                    snapshot.current_hour_start.isoformat()
                    if snapshot.current_hour_start
                    else None
                ),
                "current_hour_kwh": snapshot.current_hour_kwh,
                "current_hour_cost": snapshot.current_hour_cost,
                "today_kwh": snapshot.today_kwh,
                "today_cost": snapshot.today_cost,
                "statistic_ids": [
                    statistic_id_energy(premises_id, supply_type),
                    statistic_id_cost(premises_id, supply_type),
                ],
            }

    # A live sample of today's bars, which is what to look at first when the
    # parser stops recognising a payload.
    try:
        bars = await coordinator.client.async_fetch_day(premises_id, today)
        sample: Any = [
            {
                "supply_type": bar.supply_type,
                "start": bar.start.isoformat(),
                "kwh": str(bar.kwh),
                "cost_gbp": str(bar.cost_gbp),
                "is_realised": bar.is_realised,
            }
            for bar in bars[:6]
        ]
    except FuseApiError as err:
        sample = {"error": str(err)}

    return {
        "premises_id": premises_id,
        "last_update_success": coordinator.last_update_success,
        "supplies": supplies,
        "todays_bars_sample": sample,
    }
