"""Binary sensor platform for lowi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .entity import LowiEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .api import LowiSubscriptionSummary
    from .coordinator import LowiDataUpdateCoordinator
    from .data import LowiConfigEntry


@dataclass(frozen=True, kw_only=True)
class LowiBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a per-line Lowi binary sensor and how to read its value."""

    value_fn: Callable[[LowiSubscriptionSummary], bool | None]


ENTITY_DESCRIPTIONS: tuple[LowiBinarySensorEntityDescription, ...] = (
    LowiBinarySensorEntityDescription(
        key="voice_unlimited",
        translation_key="voice_unlimited",
        icon="mdi:phone-in-talk",
        value_fn=lambda summary: summary.voice_unlimited,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument
    entry: LowiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform: one entity per msisdn per descriptor."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        LowiBinarySensor(
            coordinator=coordinator,
            msisdn=msisdn,
            entity_description=entity_description,
        )
        for msisdn in coordinator.data.lines
        for entity_description in ENTITY_DESCRIPTIONS
    )


class LowiBinarySensor(LowiEntity, BinarySensorEntity):
    """Binary sensor exposing a single boolean figure for one Lowi phone line."""

    entity_description: LowiBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: LowiDataUpdateCoordinator,
        msisdn: str,
        entity_description: LowiBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, msisdn)
        self.entity_description = entity_description
        self._attr_unique_id = f"{msisdn}_{entity_description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return whether this line has unlimited voice calls."""
        summary = self.coordinator.data.lines.get(self.msisdn)
        if summary is None:
            return None
        return self.entity_description.value_fn(summary)
