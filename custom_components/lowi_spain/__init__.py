"""
Custom integration to integrate Lowi with Home Assistant.

For more details about this integration, please refer to
https://github.com/mandinger/lowi-spain
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import LowiApiClient
from .const import CONF_COOKIES, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER
from .coordinator import LowiDataUpdateCoordinator
from .data import LowiData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import LowiConfigEntry

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: LowiConfigEntry) -> bool:
    """Set up this integration using UI."""
    coordinator = LowiDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )
    client = LowiApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    # Restores the session established during the config flow's NIF+password+
    # SMS-code login, so a restart doesn't force the user through that dance
    # again unless the session has actually expired (see api.py).
    client.import_cookies(entry.data.get(CONF_COOKIES, {}))

    entry.runtime_data = LowiData(
        client=client,
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LowiConfigEntry) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: LowiConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
