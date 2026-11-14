"""Sensors: one per Liftosaur dashboard value, graph series, calendar and muscle map."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LiftosaurConfigEntry, LiftosaurCoordinator, SensorSpec

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LiftosaurConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        new: list[LiftosaurSensor] = []
        for dash in (coordinator.data or {}).values():
            for key in dash.sensors:
                if (dash.id, key) not in known:
                    known.add((dash.id, key))
                    new.append(LiftosaurSensor(coordinator, dash.id, key))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class LiftosaurSensor(CoordinatorEntity[LiftosaurCoordinator], SensorEntity):
    """A number from a Liftosaur dashboard."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LiftosaurCoordinator, dashboard_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._dashboard_id = dashboard_id
        self._key = key
        spec = self._spec
        assert spec is not None
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{spec.unique_id_suffix}"
        self._attr_name = spec.name
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_icon = spec.icon or "mdi:dumbbell"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_{dashboard_id}")},
            name=f"Liftosaur {spec.dashboard_name}",
            manufacturer="Liftosaur",
            model="Dashboard",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.liftosaur.com/app",
        )

    @property
    def _spec(self) -> SensorSpec | None:
        dash = (self.coordinator.data or {}).get(self._dashboard_id)
        return dash.sensors.get(self._key) if dash else None

    @property
    def available(self) -> bool:
        return super().available and self._spec is not None

    @property
    def native_value(self) -> float | None:
        spec = self._spec
        return spec.value if spec else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        spec = self._spec
        if spec is None:
            return None
        return {k: v for k, v in spec.attributes.items() if v is not None}

    @callback
    def _handle_coordinator_update(self) -> None:
        spec = self._spec
        if spec is not None and spec.unit != self._attr_native_unit_of_measurement:
            # Units only change if the user rewrites the dashboard; follow them.
            self._attr_native_unit_of_measurement = spec.unit
        super()._handle_coordinator_update()
