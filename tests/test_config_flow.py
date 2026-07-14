"""Tests for the Lowi config flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi.api import (
    LowiApiAuthenticationError,
    LowiApiCommunicationError,
    LowiApiWafChallengeError,
    LowiUser,
)
from custom_components.lowi.const import DOMAIN

from .const import MOCK_CONFIG

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGIN_PATCH_TARGET = "custom_components.lowi.config_flow.LowiApiClient.async_login"
_MOCK_USER = LowiUser(name="Test", first_last_name="User", subscriptions=[])


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A successful login creates a config entry keyed by the account email."""
    with patch(_LOGIN_PATCH_TARGET, return_value=_MOCK_USER):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_CONFIG[CONF_EMAIL]
    assert result["data"] == MOCK_CONFIG


@pytest.mark.parametrize(
    ("exception", "error_key"),
    [
        (LowiApiAuthenticationError("bad creds"), "invalid_auth"),
        (LowiApiCommunicationError("down"), "cannot_connect"),
        (LowiApiWafChallengeError("blocked"), "waf_challenge"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    exception: Exception,
    error_key: str,
) -> None:
    """Each failure mode from the API client maps to its own error string."""
    with patch(_LOGIN_PATCH_TARGET, side_effect=exception):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error_key}


async def test_user_flow_duplicate_aborts(hass: HomeAssistant) -> None:
    """A second entry for an already-configured email aborts."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_EMAIL].lower(),
        data=MOCK_CONFIG,
    ).add_to_hass(hass)

    with patch(_LOGIN_PATCH_TARGET, return_value=_MOCK_USER):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(hass: HomeAssistant) -> None:
    """Reauth with a new password updates and reloads the existing entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_EMAIL].lower(),
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)

    with patch(_LOGIN_PATCH_TARGET, return_value=_MOCK_USER):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"


async def test_reauth_flow_invalid_auth(hass: HomeAssistant) -> None:
    """A reauth attempt with a still-wrong password stays on the form."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_EMAIL].lower(),
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)

    with patch(
        _LOGIN_PATCH_TARGET,
        side_effect=LowiApiAuthenticationError("bad creds"),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "still-wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
