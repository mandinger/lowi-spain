"""Tests for the Lowi sensor platform."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from homeassistant.const import CONF_USERNAME
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi_spain.api import (
    LowiAccountData,
    LowiAccountSummary,
    LowiSubscriptionSummary,
)
from custom_components.lowi_spain.const import DOMAIN
from custom_components.lowi_spain.sensor import (
    ACCOUNT_ENTITY_DESCRIPTIONS,
    ENTITY_DESCRIPTIONS,
)

from .const import (
    ACCOUNT_ID_PRIMARY,
    ACCOUNT_ID_SECONDARY,
    MOCK_CONFIG,
    MSISDN_PRIMARY,
    MSISDN_SECONDARY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_GET_ACCOUNT_DATA_TARGET = (
    "custom_components.lowi_spain.api.LowiApiClient.async_get_account_data"
)


def _account_data(lines: dict[str, LowiSubscriptionSummary]) -> LowiAccountData:
    """Build account data with a fixed account-level summary for these tests."""
    return LowiAccountData(
        account=LowiAccountSummary(
            current_month_cost=27.79,
            billing_period_end=1785535199,
            last_invoice_amount=28.36,
            last_invoice_status="PAID",
            last_invoice_date=1780264800,
        ),
        lines=lines,
    )


async def _setup_entry(
    hass: HomeAssistant,
    account_data: LowiAccountData,
) -> MockConfigEntry:
    """Set up the integration with mocked account data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_USERNAME],
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)

    with patch(_GET_ACCOUNT_DATA_TARGET, return_value=account_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_sensor_entities_created_per_subscription_and_account(
    hass: HomeAssistant,
) -> None:
    """One device+sensors per msisdn, plus one account device+sensors, are created."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
        ),
        MSISDN_SECONDARY: LowiSubscriptionSummary(
            msisdn=MSISDN_SECONDARY,
            subscription_id=ACCOUNT_ID_SECONDARY,
        ),
    }
    entry = await _setup_entry(hass, _account_data(lines))

    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    expected_count = len(lines) * len(ENTITY_DESCRIPTIONS) + len(
        ACCOUNT_ENTITY_DESCRIPTIONS
    )
    assert len(entities) == expected_count

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    # One device per line, plus one account-wide device.
    assert len(devices) == len(lines) + 1


async def test_per_line_sensor_state_reflects_summary(hass: HomeAssistant) -> None:
    """A per-line sensor's state matches the derived value from the summary."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
            data_total_mb=409600.0,
            data_remaining_mb=408473.6,
            data_used_mb=1126.4,
        ),
    }
    await _setup_entry(hass, _account_data(lines))

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_data_used",
    )
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 1126.4


async def test_data_used_pct_sensor_is_computed(hass: HomeAssistant) -> None:
    """data_used_pct is derived from data_used_mb / data_total_mb."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
            data_total_mb=1000.0,
            data_used_mb=250.0,
        ),
    }
    await _setup_entry(hass, _account_data(lines))

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_data_used_pct",
    )
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 25.0


async def test_bonus_data_sensor_exposes_attributes(hass: HomeAssistant) -> None:
    """Plan/price/sections context is surfaced as attributes, not separate sensors."""
    sections = [
        {
            "name": "Acumulados del mes anterior",
            "quantity": {"value": "198.9", "unit": "GB"},
        },
    ]
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
            bonus_data_mb=256000.0,
            plan_name="Tarifa 150GB",
            price=19.95,
            extra_sections=sections,
        ),
    }
    await _setup_entry(hass, _account_data(lines))

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{MSISDN_PRIMARY}_bonus_data",
    )
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["sections"] == sections
    assert state.attributes["plan_name"] == "Tarifa 150GB"
    assert state.attributes["price"] == 19.95


async def test_account_sensor_states(hass: HomeAssistant) -> None:
    """Account-level sensors read the merged billing/consumption summary."""
    lines = {
        MSISDN_PRIMARY: LowiSubscriptionSummary(
            msisdn=MSISDN_PRIMARY,
            subscription_id=ACCOUNT_ID_PRIMARY,
        ),
    }
    entry = await _setup_entry(hass, _account_data(lines))

    entity_registry = er.async_get(hass)

    cost_entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_current_month_cost",
    )
    cost_state = hass.states.get(cost_entity_id)
    assert cost_state is not None
    assert float(cost_state.state) == 27.79

    status_entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_last_invoice_status",
    )
    status_state = hass.states.get(status_entity_id)
    assert status_state is not None
    assert status_state.state == "PAID"

    billing_end_entity_id = entity_registry.async_get_entity_id(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_billing_period_end",
    )
    billing_end_state = hass.states.get(billing_end_entity_id)
    assert billing_end_state is not None
    assert billing_end_state.state not in ("unknown", "unavailable")
