"""DataUpdateCoordinator for lowi."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LowiApiAuthenticationError, LowiApiError, LowiApiWafChallengeError

if TYPE_CHECKING:
    from .api import LowiAccountData
    from .data import LowiConfigEntry


class LowiDataUpdateCoordinator(DataUpdateCoordinator["LowiAccountData"]):
    """Coordinator that polls Lowi for usage data across all phone lines."""

    config_entry: LowiConfigEntry

    async def _async_update_data(self) -> LowiAccountData:
        """Fetch the latest account summary and per-line usage."""
        try:
            return await self.config_entry.runtime_data.client.async_get_account_data()
        except LowiApiAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except LowiApiWafChallengeError as exception:
            # Not an auth failure: don't force reauth, just retry next
            # interval. See api.py's LowiApiWafChallengeError docstring.
            raise UpdateFailed(exception) from exception
        except LowiApiError as exception:
            raise UpdateFailed(exception) from exception
