"""Tests for the Lowi sensor platform."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.const import CONF_USERNAME
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi.api import LowiSubscriptionSummary
from custom_components.lowi.const import DOMAIN
from custom_components.lowi.sensor import ENTITY_DESCRIPTIONS

from .const import (
    ACCOUNT_ID_PRIMARY,
    ACCOUNT_ID_SECONDARY,
    MOCK_CONFIG,
    MSISDN_PRIMARY,
    MSISDN_SECONDARY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_GET_ALL_SUMMARIES_TARGET = (
    "custom_components.lowi.api.LowiApiClient.async_get_all_summaries"
)


async def _setup_entry(
    hass: HomeAssistant,
    summaries: list[LowiSubscriptionSummary],
) -> MockConfigEntry:
    """Set up the integration with a mocked list of subscription summaries."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_USERNAME],
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)

    with patch(_GET_ALL_SUMMARIES_TARGET, return_value=summaries):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_sensor_entities_created_per_subscription(hass: HomeAssistant) -> None:
    """One device and one sensor per descriptor is created for each msisdn."""
    summaries = [
        LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            account_id=ACCOUNT_ID_PRIMARY,
            cost_current_month=12.34,
        ),
        LowiSubscriptionSummary(
            msisdn=MSISDN_SECONDARY,
            account_id=ACCOUNT_ID_SECONDARY,
            cost_current_month=5.0,
        ),
    ]
    entry = await _setup_entry(hass, summaries)

    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert len(entities) == len(summaries) * len(ENTITY_DESCRIPTIONS)

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == len(summaries)

    device_msisdns = {next(iter(device.identifiers))[1] for device in devices}
    assert device_msisdns == {MSISDN_PRIMARY, MSISDN_SECONDARY}


async def test_sensor_state_reflects_summary(hass: HomeAssistant) -> None:
    """A sensor's state matches the value from the parsed summary."""
    summaries = [
        LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            account_id=ACCOUNT_ID_PRIMARY,
            cost_current_month=12.34,
        ),
    ]
    await _setup_entry(hass, summaries)

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_cost_current_month",
    )
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 12.34
