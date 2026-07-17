"""Tests for the lowi integration's setup/unload lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi_spain.api import (
    LowiAccountData,
    LowiAccountSummary,
    LowiApiCommunicationError,
    LowiSubscriptionSummary,
)
from custom_components.lowi_spain.const import DOMAIN

from .const import ACCOUNT_ID_PRIMARY, MOCK_CONFIG, MSISDN_PRIMARY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_GET_ACCOUNT_DATA_TARGET = (
    "custom_components.lowi_spain.api.LowiApiClient.async_get_account_data"
)


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_USERNAME],
        data=MOCK_CONFIG,
    )


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """The entry loads successfully, populates runtime_data, and unloads cleanly."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        _GET_ACCOUNT_DATA_TARGET,
        return_value=LowiAccountData(
            account=LowiAccountSummary(),
            lines={
                MSISDN_PRIMARY: LowiSubscriptionSummary(
                    msisdn=MSISDN_PRIMARY,
                    subscription_id=ACCOUNT_ID_PRIMARY,
                ),
            },
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data is not None
        assert MSISDN_PRIMARY in entry.runtime_data.coordinator.data.lines

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_entry_retries_on_communication_error(hass: HomeAssistant) -> None:
    """A communication failure during first refresh leaves the entry unready."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        _GET_ACCOUNT_DATA_TARGET,
        side_effect=LowiApiCommunicationError("down"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
