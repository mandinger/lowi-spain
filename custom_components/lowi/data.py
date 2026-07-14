"""Custom types for lowi."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration

    from .api import LowiApiClient
    from .coordinator import LowiDataUpdateCoordinator


type LowiConfigEntry = ConfigEntry[LowiData]


@dataclass
class LowiData:
    """Runtime data for the Lowi integration."""

    client: LowiApiClient
    coordinator: LowiDataUpdateCoordinator
    integration: Integration
