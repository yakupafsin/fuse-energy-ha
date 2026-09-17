"""Sensors for Fuse Energy.

The Energy dashboard is fed by long-term statistics, not by these entities --
see ``statistics.py``. What lives here is the at-a-glance layer: what the
last settled hour cost, how the day is adding up, and -- from the hour Fuse
is still metering -- roughly what the Fuse app is showing right now, in a form
you can put on a card or trigger an automation from.

None of these carry a ``state_class``, so none of them reach long-term
statistics. That is deliberate: the current-hour figures climb during the hour
and Fuse revises them afterwards, so recording them would fight the settled
values ``statistics.py`` writes for the very same hour.

Entities are created per supply discovered on the account, so a property with
gas and solar export gets a full set for each without any configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FuseConfigEntry
from .const import DOMAIN, FUSE_TIMEZONE
from .coordinator import FuseCoordinator, SupplySnapshot

_LOCAL_TZ = ZoneInfo(FUSE_TIMEZONE)
_CURRENCY = "GBP"

_SUPPLY_LABELS: dict[str, str] = {
    "ELEC_IMPORT": "Electricity",
    "ELEC_EXPORT": "Electricity export",
    "GAS": "Gas",
}


def _label(supply_type: str) -> str:
    """Readable supply name, falling back to a tidied version of whatever
    Fuse sent so an unfamiliar supply type still reads sensibly."""
    return _SUPPLY_LABELS.get(supply_type, supply_type.replace("_", " ").capitalize())


@dataclass(frozen=True, kw_only=True)
class FuseSensorDescription(SensorEntityDescription):
    """A sensor description plus how to read its value off a snapshot."""

    value_fn: Callable[[SupplySnapshot], float | None]
    # The snapshot field naming the hour this reading covers, published as an
    # attribute under that same name. None for readings that span no single
    # hour, so a daily total does not advertise an hour that does not bound it.
    period_attr: str | None = "last_hour_start"
    # Daily totals restart at local midnight. Home Assistant needs to be told
    # so it treats the drop as a reset rather than a meter running backwards.
    resets_daily: bool = False


SENSORS: tuple[FuseSensorDescription, ...] = (
    FuseSensorDescription(
        key="last_hour_energy",
        name="last hour",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        icon="mdi:flash",
        value_fn=lambda snapshot: snapshot.last_hour_kwh,
    ),
    FuseSensorDescription(
        key="last_hour_cost",
        name="last hour cost",
        native_unit_of_measurement=_CURRENCY,
        suggested_display_precision=2,
        icon="mdi:currency-gbp",
        value_fn=lambda snapshot: snapshot.last_hour_cost,
    ),
    FuseSensorDescription(
        key="current_hour_energy",
        name="current hour",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        icon="mdi:flash-outline",
        value_fn=lambda snapshot: snapshot.current_hour_kwh,
        period_attr="current_hour_start",
    ),
    FuseSensorDescription(
        key="current_hour_cost",
        name="current hour cost",
        native_unit_of_measurement=_CURRENCY,
        suggested_display_precision=2,
        icon="mdi:currency-gbp",
        value_fn=lambda snapshot: snapshot.current_hour_cost,
        period_attr="current_hour_start",
    ),
    # "Today so far": these count the hour Fuse is still metering, so they
    # track the Fuse app rather than trailing it. They are display entities --
    # the Energy dashboard reads the external statistics in statistics.py,
    # which are written from settled hours only.
    FuseSensorDescription(
        key="today_energy",
        name="today",
        period_attr=None,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        resets_daily=True,
        value_fn=lambda snapshot: snapshot.today_kwh,
    ),
    FuseSensorDescription(
        key="today_cost",
        name="today cost",
        period_attr=None,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=_CURRENCY,
        suggested_display_precision=2,
        resets_daily=True,
        value_fn=lambda snapshot: snapshot.today_cost,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FuseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for each supply, now and as any new one appears."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_supplies() -> None:
        """Fuse can start reporting a supply mid-life -- a newly commissioned
        export meter, say. Watching the coordinator means those appear without
        the user having to reload the integration."""
        if coordinator.data is None:
            return
        fresh = set(coordinator.data.supplies) - known
        if not fresh:
            return
        known.update(fresh)
        async_add_entities(
            FuseSensor(coordinator, supply_type, description)
            for supply_type in sorted(fresh)
            for description in SENSORS
        )

    _add_new_supplies()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_supplies))


class FuseSensor(CoordinatorEntity[FuseCoordinator], SensorEntity):
    """One measure of one supply."""

    _attr_has_entity_name = True
    entity_description: FuseSensorDescription

    def __init__(
        self,
        coordinator: FuseCoordinator,
        supply_type: str,
        description: FuseSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._supply_type = supply_type
        self._attr_unique_id = (
            f"{coordinator.premises_id}_{supply_type}_{description.key}".lower()
        )
        self._attr_name = f"{_label(supply_type)} {description.name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.premises_id)},
            manufacturer="Fuse Energy",
            name="Fuse Energy",
            entry_type=None,
        )

    @property
    def _snapshot(self) -> SupplySnapshot | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.supplies.get(self._supply_type)

    @property
    def available(self) -> bool:
        """Available once Fuse has published a value for this reading.

        Judged per reading rather than per supply, so the current-hour
        entities drop out while Fuse still calls the hour FORECASTED instead
        of reporting a zero that reads as "you used nothing".
        """
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        if (snapshot := self._snapshot) is None:
            return None
        return self.entity_description.value_fn(snapshot)

    @property
    def last_reset(self) -> datetime | None:
        """Local midnight, for the daily totals."""
        if not self.entity_description.resets_daily:
            return None
        today = datetime.now(_LOCAL_TZ).date()
        return datetime.combine(today, time.min, tzinfo=_LOCAL_TZ)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose which hour the reading belongs to.

        Fuse runs an hour or more behind, so without this it is impossible to
        tell a genuinely idle hour from a reading that has simply not caught up.
        The daily totals span no single hour and so carry no such attribute.
        """
        if (snapshot := self._snapshot) is None:
            return None
        if (attr := self.entity_description.period_attr) is None:
            return {"supply_type": self._supply_type}
        start: datetime | None = getattr(snapshot, attr)
        if start is None:
            return None
        return {
            attr: start.astimezone(_LOCAL_TZ).isoformat(),
            "supply_type": self._supply_type,
        }
