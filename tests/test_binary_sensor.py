"""Tests for the Lowi binary sensor platform."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.const import CONF_USERNAME
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi_spain.api import (
    LowiAccountData,
    LowiAccountSummary,
    LowiSubscriptionSummary,
)
from custom_components.lowi_spain.const import DOMAIN

from .const import ACCOUNT_ID_PRIMARY, MOCK_CONFIG, MSISDN_PRIMARY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_GET_ACCOUNT_DATA_TARGET = (
    "custom_components.lowi_spain.api.LowiApiClient.async_get_account_data"
)


async def _setup_entry(
    hass: HomeAssistant,
    lines: dict[str, LowiSubscriptionSummary],
) -> MockConfigEntry:
    """Set up the integration with mocked account data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_USERNAME],
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)

    account_data = LowiAccountData(account=LowiAccountSummary(), lines=lines)
    with patch(_GET_ACCOUNT_DATA_TARGET, return_value=account_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_voice_unlimited_on(hass: HomeAssistant) -> None:
    """The binary sensor reads True when the line has unlimited calls."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
            voice_unlimited=True,
        ),
    }
    await _setup_entry(hass, lines)

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_voice_unlimited",
    )
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"


async def test_voice_unlimited_off(hass: HomeAssistant) -> None:
    """The binary sensor reads False when the line's calls are metered."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
            voice_unlimited=False,
        ),
    }
    await _setup_entry(hass, lines)

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_voice_unlimited",
    )
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"


async def test_voice_unlimited_unknown_when_not_reported(hass: HomeAssistant) -> None:
    """The binary sensor is unknown when Lowi didn't report voice_consumption."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
            voice_unlimited=None,
        ),
    }
    await _setup_entry(hass, lines)

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_voice_unlimited",
    )
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "unknown"
