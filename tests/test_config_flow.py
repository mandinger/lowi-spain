"""Tests for the Lowi config flow (NIF/password + phone selection + SMS code)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lowi_spain.api import (
    LowiApiAuthenticationError,
    LowiApiCommunicationError,
    LowiApiWafChallengeError,
    PhoneOption,
)
from custom_components.lowi_spain.const import CONF_COOKIES, DOMAIN

from .const import MOCK_CONFIG, MSISDN_PRIMARY, MSISDN_SECONDARY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_START_LOGIN_TARGET = (
    "custom_components.lowi_spain.config_flow.LowiApiClient.async_start_login"
)
_SELECT_PHONE_TARGET = (
    "custom_components.lowi_spain.config_flow.LowiApiClient.async_select_phone"
)
_SUBMIT_OTP_TARGET = (
    "custom_components.lowi_spain.config_flow.LowiApiClient.async_submit_otp"
)

_SINGLE_PHONE_OPTION = [PhoneOption(value="7192706", label="7192706")]
_MULTI_PHONE_OPTIONS = [
    PhoneOption(value=MSISDN_PRIMARY, label="***222"),
    PhoneOption(value=MSISDN_SECONDARY, label="***444"),
]


async def _advance_to_otp_step(hass: HomeAssistant) -> dict:
    """Credentials -> single phone auto-selected -> lands on the otp step."""
    with (
        patch(_START_LOGIN_TARGET, return_value=_SINGLE_PHONE_OPTION),
        patch(_SELECT_PHONE_TARGET, return_value=None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )


async def test_full_user_flow_success_single_phone(hass: HomeAssistant) -> None:
    """A single offered phone is auto-selected; credentials + OTP create an entry."""
    result = await _advance_to_otp_step(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "otp"

    with patch(_SUBMIT_OTP_TARGET, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "654321"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_CONFIG[CONF_USERNAME]
    assert result["data"][CONF_USERNAME] == MOCK_CONFIG[CONF_USERNAME]
    assert result["data"][CONF_PASSWORD] == MOCK_CONFIG[CONF_PASSWORD]
    assert CONF_COOKIES in result["data"]


async def test_full_user_flow_success_multi_phone(hass: HomeAssistant) -> None:
    """Multiple phone options show a selection step before the OTP step."""
    with patch(_START_LOGIN_TARGET, return_value=_MULTI_PHONE_OPTIONS):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phone"

    with patch(_SELECT_PHONE_TARGET, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"phone": MSISDN_SECONDARY},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "otp"

    with patch(_SUBMIT_OTP_TARGET, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "654321"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("exception", "error_key"),
    [
        (LowiApiAuthenticationError("bad creds"), "invalid_auth"),
        (LowiApiCommunicationError("down"), "cannot_connect"),
        (LowiApiWafChallengeError("blocked"), "waf_challenge"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_step_errors(
    hass: HomeAssistant,
    exception: Exception,
    error_key: str,
) -> None:
    """Each failure mode from the credentials step maps to its own error string."""
    with patch(_START_LOGIN_TARGET, side_effect=exception):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error_key}


@pytest.mark.parametrize(
    ("exception", "error_key"),
    [
        (LowiApiAuthenticationError("bad creds"), "invalid_auth"),
        (LowiApiCommunicationError("down"), "cannot_connect"),
        (LowiApiWafChallengeError("blocked"), "waf_challenge"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_phone_step_errors(
    hass: HomeAssistant,
    exception: Exception,
    error_key: str,
) -> None:
    """Each failure mode from the phone-selection step maps to its own error string."""
    with patch(_START_LOGIN_TARGET, return_value=_MULTI_PHONE_OPTIONS):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            MOCK_CONFIG,
        )

    with patch(_SELECT_PHONE_TARGET, side_effect=exception):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"phone": MSISDN_SECONDARY},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phone"
    assert result["errors"] == {"base": error_key}


@pytest.mark.parametrize(
    ("exception", "error_key"),
    [
        (LowiApiAuthenticationError("bad code"), "invalid_otp"),
        (LowiApiCommunicationError("down"), "cannot_connect"),
        (LowiApiWafChallengeError("blocked"), "waf_challenge"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_otp_step_errors(
    hass: HomeAssistant,
    exception: Exception,
    error_key: str,
) -> None:
    """Each failure mode from the OTP step maps to its own error string."""
    result = await _advance_to_otp_step(hass)

    with patch(_SUBMIT_OTP_TARGET, side_effect=exception):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "000000"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "otp"
    assert result["errors"] == {"base": error_key}


async def test_user_flow_duplicate_aborts(hass: HomeAssistant) -> None:
    """A second entry for an already-configured username aborts."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_USERNAME],
        data=MOCK_CONFIG,
    ).add_to_hass(hass)

    result = await _advance_to_otp_step(hass)
    with patch(_SUBMIT_OTP_TARGET, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "654321"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(hass: HomeAssistant) -> None:
    """Reauth walks credentials, phone auto-select, and OTP, updating the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_CONFIG[CONF_USERNAME],
        data=MOCK_CONFIG,
    )
    entry.add_to_hass(hass)

    with (
        patch(_START_LOGIN_TARGET, return_value=_SINGLE_PHONE_OPTION),
        patch(_SELECT_PHONE_TARGET, return_value=None),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-password"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "otp"

    with patch(_SUBMIT_OTP_TARGET, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "654321"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
