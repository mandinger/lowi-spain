"""Tests for the Lowi data update coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi_spain.api import (
    LowiAccountData,
    LowiAccountSummary,
    LowiApiAuthenticationError,
    LowiApiCommunicationError,
    LowiApiWafChallengeError,
    LowiSubscriptionSummary,
)
from custom_components.lowi_spain.const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER
from custom_components.lowi_spain.coordinator import LowiDataUpdateCoordinator
from custom_components.lowi_spain.data import LowiData

from .const import ACCOUNT_ID_PRIMARY, MOCK_CONFIG, MSISDN_PRIMARY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def _make_coordinator(
    hass: HomeAssistant,
    client: AsyncMock,
) -> LowiDataUpdateCoordinator:
    """Build a coordinator wired to a mocked API client, without a full setup."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    entry.add_to_hass(hass)
    coordinator = LowiDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=DEFAULT_SCAN_INTERVAL,
        config_entry=entry,
    )
    entry.runtime_data = LowiData(
        client=client, coordinator=coordinator, integration=None
    )
    return coordinator


def _reauth_flows_for_entry(hass: HomeAssistant) -> list[dict]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"].get("source") == "reauth"
    ]


async def test_successful_update(hass: HomeAssistant) -> None:
    """A successful fetch stores the account data returned by the client."""
    client = AsyncMock()
    account_data = LowiAccountData(
        account=LowiAccountSummary(current_month_cost=12.34),
        lines={
            MSISDN_PRIMARY: LowiSubscriptionSummary(
                msisdn=MSISDN_PRIMARY,
                subscription_id=ACCOUNT_ID_PRIMARY,
            ),
        },
    )
    client.async_get_account_data.return_value = account_data
    coordinator = await _make_coordinator(hass, client)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data is account_data
    assert MSISDN_PRIMARY in coordinator.data.lines
    assert coordinator.data.account.current_month_cost == 12.34


async def test_auth_failure_triggers_reauth(hass: HomeAssistant) -> None:
    """An authentication error triggers Home Assistant's reauth flow."""
    client = AsyncMock()
    client.async_get_account_data.side_effect = LowiApiAuthenticationError("bad creds")
    coordinator = await _make_coordinator(hass, client)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert _reauth_flows_for_entry(hass)


async def test_waf_challenge_does_not_trigger_reauth(hass: HomeAssistant) -> None:
    """
    A WAF challenge fails the update but must NOT force a reauth loop.

    This is the most important Lowi-specific regression test: conflating a
    WAF challenge with a credentials failure would make users needlessly
    re-enter correct passwords and increase request volume, worsening WAF
    suspicion (see api.py's LowiApiWafChallengeError docstring).
    """
    client = AsyncMock()
    client.async_get_account_data.side_effect = LowiApiWafChallengeError("blocked")
    coordinator = await _make_coordinator(hass, client)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert not _reauth_flows_for_entry(hass)


async def test_communication_error_does_not_trigger_reauth(hass: HomeAssistant) -> None:
    """A transport failure fails the update but must NOT force a reauth loop."""
    client = AsyncMock()
    client.async_get_account_data.side_effect = LowiApiCommunicationError("down")
    coordinator = await _make_coordinator(hass, client)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert not _reauth_flows_for_entry(hass)
