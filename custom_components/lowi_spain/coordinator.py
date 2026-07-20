"""DataUpdateCoordinator for lowi."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LowiApiAuthenticationError, LowiApiError, LowiApiWafChallengeError
from .const import CONF_COOKIES, CONF_SSO_COOKIES

if TYPE_CHECKING:
    from .api import LowiAccountData
    from .data import LowiConfigEntry


class LowiDataUpdateCoordinator(DataUpdateCoordinator["LowiAccountData"]):
    """Coordinator that polls Lowi for usage data across all phone lines."""

    config_entry: LowiConfigEntry

    async def _async_update_data(self) -> LowiAccountData:
        """Fetch the latest account summary and per-line usage."""
        try:
            data = await self.config_entry.runtime_data.client.async_get_account_data()
        except LowiApiAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except LowiApiWafChallengeError as exception:
            # Not an auth failure: don't force reauth, just retry next
            # interval. See api.py's LowiApiWafChallengeError docstring.
            raise UpdateFailed(exception) from exception
        except LowiApiError as exception:
            raise UpdateFailed(exception) from exception

        self._async_persist_cookies_if_changed()
        return data

    def _async_persist_cookies_if_changed(self) -> None:
        """
        Save rotated cookies to the config entry, if a silent refresh rotated them.

        async_get_account_data() may have silently minted a fresh `sessionid`
        (and possibly rotated Keycloak SSO cookies) via _async_silent_reauth()
        when the previous session had expired. That happens entirely inside
        the live aiohttp session, so without this it would only last until
        the next Home Assistant restart, at which point the stale persisted
        cookies would need a silent refresh all over again anyway - fine, but
        pointless churn. Comparing before writing avoids updating the config
        entry on every single poll when nothing actually rotated.
        """
        entry = self.config_entry
        client = entry.runtime_data.client
        cookies = client.export_cookies()
        sso_cookies = client.export_sso_cookies()
        if cookies == entry.data.get(CONF_COOKIES) and sso_cookies == entry.data.get(
            CONF_SSO_COOKIES,
        ):
            return

        self.hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_COOKIES: cookies, CONF_SSO_COOKIES: sso_cookies},
        )
