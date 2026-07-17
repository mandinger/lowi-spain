"""LowiEntity class."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import LowiDataUpdateCoordinator


class LowiEntity(CoordinatorEntity[LowiDataUpdateCoordinator]):
    """Base entity for a single Lowi phone line (msisdn)."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: LowiDataUpdateCoordinator, msisdn: str) -> None:
        """Initialize the entity for a given phone line."""
        super().__init__(coordinator)
        self.msisdn = msisdn
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, msisdn)},
            name=f"Lowi {msisdn}",
            manufacturer="Lowi",
            model="Mobile line",
        )
