"""Sensor platform for lowi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation

from .entity import LowiEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import LowiSubscriptionSummary
    from .coordinator import LowiDataUpdateCoordinator
    from .data import LowiConfigEntry


@dataclass(frozen=True, kw_only=True)
class LowiSensorEntityDescription(SensorEntityDescription):
    """Describes a Lowi sensor and how to read its value from a summary."""

    value_fn: Callable[[LowiSubscriptionSummary], float | None]


ENTITY_DESCRIPTIONS: tuple[LowiSensorEntityDescription, ...] = (
    LowiSensorEntityDescription(
        key="remaining_data",
        translation_key="remaining_data",
        icon="mdi:database-arrow-down",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.remaining_data_mb,
    ),
    LowiSensorEntityDescription(
        key="total_data",
        translation_key="total_data",
        icon="mdi:database",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.total_data_mb,
    ),
    LowiSensorEntityDescription(
        key="tariff_data_included",
        translation_key="tariff_data_included",
        icon="mdi:database-check",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.tariff_data_included_mb,
    ),
    LowiSensorEntityDescription(
        key="bonus_data",
        translation_key="bonus_data",
        icon="mdi:database-plus",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.bonus_data_mb,
    ),
    LowiSensorEntityDescription(
        key="accumulated_data",
        translation_key="accumulated_data",
        icon="mdi:database-clock",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.accumulated_data_mb,
    ),
    LowiSensorEntityDescription(
        key="shared_data_received",
        translation_key="shared_data_received",
        icon="mdi:database-import",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.shared_data_received_mb,
    ),
    LowiSensorEntityDescription(
        key="cost_current_month",
        translation_key="cost_current_month",
        icon="mdi:currency-eur",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda summary: summary.cost_current_month,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument
    entry: LowiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform: one entity per msisdn per descriptor."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        LowiSensor(
            coordinator=coordinator,
            msisdn=msisdn,
            entity_description=entity_description,
        )
        for msisdn in coordinator.data
        for entity_description in ENTITY_DESCRIPTIONS
    )


class LowiSensor(LowiEntity, SensorEntity):
    """Sensor exposing a single usage/cost figure for one Lowi phone line."""

    entity_description: LowiSensorEntityDescription

    def __init__(
        self,
        coordinator: LowiDataUpdateCoordinator,
        msisdn: str,
        entity_description: LowiSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, msisdn)
        self.entity_description = entity_description
        self._attr_unique_id = f"{msisdn}_{entity_description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value for this sensor."""
        summary = self.coordinator.data.get(self.msisdn)
        if summary is None:
            return None
        return self.entity_description.value_fn(summary)
