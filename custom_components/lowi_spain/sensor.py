"""Sensor platform for lowi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.util import dt as dt_util

from .entity import LowiAccountEntity, LowiEntity

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import LowiAccountSummary, LowiSubscriptionSummary
    from .coordinator import LowiDataUpdateCoordinator
    from .data import LowiConfigEntry


def _data_used_pct(summary: LowiSubscriptionSummary) -> float | None:
    """Percentage of the total data allowance already used, if both are known."""
    if not summary.data_total_mb or summary.data_used_mb is None:
        return None
    return round(100 * summary.data_used_mb / summary.data_total_mb, 1)


@dataclass(frozen=True, kw_only=True)
class LowiSensorEntityDescription(SensorEntityDescription):
    """Describes a per-line Lowi sensor and how to read its value from a summary."""

    value_fn: Callable[[LowiSubscriptionSummary], float | None]


ENTITY_DESCRIPTIONS: tuple[LowiSensorEntityDescription, ...] = (
    LowiSensorEntityDescription(
        key="data_remaining",
        translation_key="data_remaining",
        icon="mdi:database-arrow-down",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.data_remaining_mb,
    ),
    LowiSensorEntityDescription(
        key="data_used",
        translation_key="data_used",
        icon="mdi:database-minus",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.data_used_mb,
    ),
    LowiSensorEntityDescription(
        key="data_total",
        translation_key="data_total",
        icon="mdi:database",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.data_total_mb,
    ),
    LowiSensorEntityDescription(
        key="data_used_pct",
        translation_key="data_used_pct",
        icon="mdi:database-percent",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=_data_used_pct,
    ),
    LowiSensorEntityDescription(
        key="data_included",
        translation_key="data_included",
        icon="mdi:database-check",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        suggested_display_precision=0,
        value_fn=lambda summary: summary.data_included_mb,
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
)


@dataclass(frozen=True, kw_only=True)
class LowiAccountSensorEntityDescription(SensorEntityDescription):
    """Describes an account-wide Lowi sensor and how to read its value."""

    value_fn: Callable[[LowiAccountSummary], float | str | datetime | None]


def _as_utc_datetime(epoch_seconds: int | None) -> datetime | None:
    """Convert an epoch-seconds field to an aware datetime for TIMESTAMP sensors."""
    if epoch_seconds is None:
        return None
    return dt_util.utc_from_timestamp(epoch_seconds)


ACCOUNT_ENTITY_DESCRIPTIONS: tuple[LowiAccountSensorEntityDescription, ...] = (
    LowiAccountSensorEntityDescription(
        key="current_month_cost",
        translation_key="current_month_cost",
        icon="mdi:currency-eur",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda account: account.current_month_cost,
    ),
    LowiAccountSensorEntityDescription(
        key="billing_period_end",
        translation_key="billing_period_end",
        icon="mdi:calendar-end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda account: _as_utc_datetime(account.billing_period_end),
    ),
    LowiAccountSensorEntityDescription(
        key="last_invoice_amount",
        translation_key="last_invoice_amount",
        icon="mdi:receipt",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda account: account.last_invoice_amount,
    ),
    LowiAccountSensorEntityDescription(
        key="last_invoice_status",
        translation_key="last_invoice_status",
        icon="mdi:receipt-text-check",
        value_fn=lambda account: account.last_invoice_status,
    ),
    LowiAccountSensorEntityDescription(
        key="last_invoice_date",
        translation_key="last_invoice_date",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda account: _as_utc_datetime(account.last_invoice_date),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument
    entry: LowiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform: per-line entities plus account-wide entities."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        LowiSensor(
            coordinator=coordinator,
            msisdn=msisdn,
            entity_description=entity_description,
        )
        for msisdn in coordinator.data.lines
        for entity_description in ENTITY_DESCRIPTIONS
    ]
    entities.extend(
        LowiAccountSensor(
            coordinator=coordinator, entity_description=entity_description
        )
        for entity_description in ACCOUNT_ENTITY_DESCRIPTIONS
    )
    async_add_entities(entities)


class LowiSensor(LowiEntity, SensorEntity):
    """Sensor exposing a single usage figure for one Lowi phone line."""

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
        summary = self.coordinator.data.lines.get(self.msisdn)
        if summary is None:
            return None
        return self.entity_description.value_fn(summary)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose plan/roaming context, and the extra-data breakdown on that sensor."""
        summary = self.coordinator.data.lines.get(self.msisdn)
        if summary is None:
            return None

        attributes: dict[str, Any] = {"data_unlimited": summary.data_unlimited}
        if summary.plan_name is not None:
            attributes["plan_name"] = summary.plan_name
        if summary.price is not None:
            attributes["price"] = summary.price
        if summary.roaming_zones is not None:
            attributes["roaming_zones"] = summary.roaming_zones
        if (
            self.entity_description.key == "bonus_data"
            and summary.extra_sections is not None
        ):
            attributes["sections"] = summary.extra_sections
        return attributes


class LowiAccountSensor(LowiAccountEntity, SensorEntity):
    """Sensor exposing a single account-wide figure (cost, billing, invoices)."""

    entity_description: LowiAccountSensorEntityDescription

    def __init__(
        self,
        coordinator: LowiDataUpdateCoordinator,
        entity_description: LowiAccountSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{entity_description.key}"

    @property
    def native_value(self) -> float | str | datetime | None:
        """Return the current value for this sensor."""
        return self.entity_description.value_fn(self.coordinator.data.account)
