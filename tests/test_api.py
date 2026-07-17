"""Tests for the Lowi API client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import patch

import aiohttp
import pytest
from yarl import URL

from custom_components.lowi_spain.api import (
    API_BASE_URL,
    MILOWI_API_BASE_URL,
    PORTAL_BASE_URL,
    LowiApiAuthenticationError,
    LowiApiClient,
    LowiApiCommunicationError,
    LowiApiError,
    LowiApiWafChallengeError,
    PhoneOption,
    _extract_phone_options,
)

from .const import (
    ACCOUNT_ID_PRIMARY,
    INTERNET_ACCOUNT_ID,
    LOGIN_ERROR_HTML,
    MOCK_BILLINGS_RESPONSE,
    MOCK_CONSUMPTIONS_RESPONSE,
    MOCK_SUBSCRIPTIONS_RESPONSE,
    MSISDN_PRIMARY,
    MSISDN_SECONDARY,
    WAF_CHALLENGE_BODY,
    login_page_html,
    multi_phone_select_html,
    otp_form_html,
    phone_select_html,
)

if TYPE_CHECKING:
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

_ENTRY_URL = f"{PORTAL_BASE_URL}/login/"
_LOGIN_ACTION_URL = f"{PORTAL_BASE_URL}/login-step"
_PHONE_ACTION_URL = f"{PORTAL_BASE_URL}/phone-step"
_OTP_ACTION_URL = f"{PORTAL_BASE_URL}/otp-step"


def _client_from_mocker(
    aioclient_mock: AiohttpClientMocker,
) -> tuple[LowiApiClient, aiohttp.ClientSession]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    client = LowiApiClient("12345678A", "test-password", session)
    return client, session


def test_extract_phone_options_from_select() -> None:
    """Phone options (value + visible label) are found in a <select> dropdown."""
    html = (
        '<form><select name="selectedPhone">'
        '<option value="">Choose...</option>'
        '<option value="7192706">***379</option>'
        '<option value="7192704">***579</option>'
        "</select></form>"
    )
    assert _extract_phone_options(html) == [
        PhoneOption(value="7192706", label="***379"),
        PhoneOption(value="7192704", label="***579"),
    ]


def test_extract_phone_options_from_labelled_radio_inputs() -> None:
    """Phone options are found when rendered as radio <input>s with <label>s."""
    html = (
        "<form>"
        '<input type="radio" id="phone-7192706" name="selectedPhone" value="7192706"/>'
        '<label for="phone-7192706">***379</label>'
        '<input type="radio" id="phone-7192704" name="selectedPhone" value="7192704"/>'
        '<label for="phone-7192704">***579</label>'
        "</form>"
    )
    assert _extract_phone_options(html) == [
        PhoneOption(value="7192706", label="***379"),
        PhoneOption(value="7192704", label="***579"),
    ]


def test_extract_phone_options_from_unlabelled_radio_input() -> None:
    """An unlabelled radio <input> still yields a usable option (value as label)."""
    html = '<form><input type="radio" name="selectedPhone" value="7192706"/></form>'
    assert _extract_phone_options(html) == [
        PhoneOption(value="7192706", label="7192706"),
    ]


def test_extract_phone_options_absent() -> None:
    """No phone field present yields an empty list (surfaced as an error upstream)."""
    assert _extract_phone_options("<form><input name='code'/></form>") == []


def _register_happy_path_login(
    aioclient_mock: AiohttpClientMocker,
    *,
    phone_id: str = ACCOUNT_ID_PRIMARY,
) -> None:
    aioclient_mock.get(_ENTRY_URL, text=login_page_html(_LOGIN_ACTION_URL))
    aioclient_mock.post(
        _LOGIN_ACTION_URL,
        text=phone_select_html(_PHONE_ACTION_URL, phone_id),
    )
    aioclient_mock.post(_PHONE_ACTION_URL, text=otp_form_html(_OTP_ACTION_URL))


async def test_start_login_returns_single_phone_option(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A single offered phone number is returned for the caller to select."""
    _register_happy_path_login(aioclient_mock)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        options = await client.async_start_login()
    finally:
        await session.close()

    assert options == [PhoneOption(value=ACCOUNT_ID_PRIMARY, label=ACCOUNT_ID_PRIMARY)]
    assert client._phone_action_url == _PHONE_ACTION_URL


async def test_start_login_sends_remember_me(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The credentials POST asks Keycloak for a long-lived SSO session."""
    _register_happy_path_login(aioclient_mock)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        await client.async_start_login()
    finally:
        await session.close()

    credentials_call = next(
        call for call in aioclient_mock.mock_calls if call[1] == URL(_LOGIN_ACTION_URL)
    )
    assert credentials_call[2]["rememberMe"] == "on"


async def test_start_login_returns_multiple_phone_options(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A multi-line account's offered phone numbers are all returned."""
    aioclient_mock.get(_ENTRY_URL, text=login_page_html(_LOGIN_ACTION_URL))
    aioclient_mock.post(
        _LOGIN_ACTION_URL,
        text=multi_phone_select_html(
            _PHONE_ACTION_URL,
            [(MSISDN_PRIMARY, "***222"), (MSISDN_SECONDARY, "***444")],
        ),
    )
    client, session = _client_from_mocker(aioclient_mock)
    try:
        options = await client.async_start_login()
    finally:
        await session.close()

    assert options == [
        PhoneOption(value=MSISDN_PRIMARY, label="***222"),
        PhoneOption(value=MSISDN_SECONDARY, label="***444"),
    ]


async def test_start_login_invalid_credentials(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Wrong credentials on the first Keycloak step raise an auth error."""
    aioclient_mock.get(_ENTRY_URL, text=login_page_html(_LOGIN_ACTION_URL))
    aioclient_mock.post(_LOGIN_ACTION_URL, text=LOGIN_ERROR_HTML)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        with pytest.raises(LowiApiAuthenticationError):
            await client.async_start_login()
    finally:
        await session.close()


async def test_select_phone_before_start_login_raises() -> None:
    """Calling async_select_phone() before async_start_login() is a bug."""
    session = aiohttp.ClientSession()
    try:
        client = LowiApiClient("12345678A", "test-password", session)
        with pytest.raises(LowiApiError):
            await client.async_select_phone(ACCOUNT_ID_PRIMARY)
    finally:
        await session.close()


async def test_submit_otp_success_returns_account_data(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A correct OTP completes login and returns the merged account data."""
    _register_happy_path_login(aioclient_mock)
    aioclient_mock.post(_OTP_ACTION_URL, text="<html>ok</html>")
    aioclient_mock.get(
        f"{API_BASE_URL}me/subscriptions",
        json=MOCK_SUBSCRIPTIONS_RESPONSE,
    )
    aioclient_mock.get(
        f"{MILOWI_API_BASE_URL}me/consumptions",
        json=MOCK_CONSUMPTIONS_RESPONSE,
    )
    aioclient_mock.get(
        f"{MILOWI_API_BASE_URL}me/billings",
        json=MOCK_BILLINGS_RESPONSE,
    )

    client, session = _client_from_mocker(aioclient_mock)
    try:
        await client.async_start_login()
        await client.async_select_phone(ACCOUNT_ID_PRIMARY)
        data = await client.async_submit_otp("654321")
    finally:
        await session.close()

    assert set(data.lines) == {MSISDN_PRIMARY, MSISDN_SECONDARY}
    assert data.account.current_month_cost == 27.79


async def test_submit_otp_invalid_code(aioclient_mock: AiohttpClientMocker) -> None:
    """An incorrect SMS code raises an auth error."""
    _register_happy_path_login(aioclient_mock)
    aioclient_mock.post(
        _OTP_ACTION_URL,
        text='<html><body><span class="kc-feedback-text">Bad code</span></body></html>',
    )

    client, session = _client_from_mocker(aioclient_mock)
    try:
        await client.async_start_login()
        await client.async_select_phone(ACCOUNT_ID_PRIMARY)
        with pytest.raises(LowiApiAuthenticationError):
            await client.async_submit_otp("000000")
    finally:
        await session.close()


async def test_get_account_data_merges_usage_and_billing(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Live usage overrides contracted figures and is merged in by subscription_id."""
    aioclient_mock.get(
        f"{API_BASE_URL}me/subscriptions",
        json=MOCK_SUBSCRIPTIONS_RESPONSE,
    )
    aioclient_mock.get(
        f"{MILOWI_API_BASE_URL}me/consumptions",
        json=MOCK_CONSUMPTIONS_RESPONSE,
    )
    aioclient_mock.get(
        f"{MILOWI_API_BASE_URL}me/billings",
        json=MOCK_BILLINGS_RESPONSE,
    )
    client, session = _client_from_mocker(aioclient_mock)
    try:
        data = await client.async_get_account_data()
    finally:
        await session.close()

    primary = data.lines[MSISDN_PRIMARY]
    assert primary.subscription_id == ACCOUNT_ID_PRIMARY
    assert primary.data_total_mb == pytest.approx(400 * 1024)
    assert primary.data_remaining_mb == pytest.approx(398.9 * 1024)
    assert primary.data_used_mb == pytest.approx(1.1 * 1024)
    assert primary.data_included_mb == pytest.approx(150 * 1024)
    # consumptions' `extra` (250GB) overrides the subscriptions' BOND_DATA addon (50GB).
    assert primary.bonus_data_mb == pytest.approx(250 * 1024)
    assert primary.data_unlimited is False
    assert primary.voice_unlimited is True
    assert primary.roaming_zones == ["1"]
    assert primary.extra_sections == [
        {
            "name": "Acumulados del mes anterior",
            "quantity": {"value": "198.9", "unit": "GB"},
        },
    ]

    secondary = data.lines[MSISDN_SECONDARY]
    assert secondary.bonus_data_mb is None  # no addon, and consumptions' extra is None

    assert INTERNET_ACCOUNT_ID not in {
        line.subscription_id for line in data.lines.values()
    }

    assert data.account.current_month_cost == 27.79
    assert data.account.billing_period_end == 1785535199
    assert data.account.last_invoice_amount == 28.36
    assert data.account.last_invoice_status == "PAID"
    assert data.account.last_invoice_date == 1780264800


async def test_waf_challenge_detected_on_api_call(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An Incapsula challenge page on the API is surfaced as a distinct error."""
    aioclient_mock.get(
        f"{API_BASE_URL}me/subscriptions",
        text=WAF_CHALLENGE_BODY,
        headers={"X-Iinfo": "1-2-3", "Content-Type": "text/html"},
    )
    client, session = _client_from_mocker(aioclient_mock)
    try:
        with pytest.raises(LowiApiWafChallengeError):
            await client.async_get_account_data()
    finally:
        await session.close()


async def test_expired_session_surfaces_as_auth_error(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A non-JSON response (redirected to the login page) means auth failed."""
    aioclient_mock.get(
        f"{API_BASE_URL}me/subscriptions",
        text="<html>please log in</html>",
        headers={"Content-Type": "text/html"},
    )
    client, session = _client_from_mocker(aioclient_mock)
    try:
        with pytest.raises(LowiApiAuthenticationError):
            await client.async_get_account_data()
    finally:
        await session.close()


async def test_communication_error_on_transport_failure() -> None:
    """A transport-level failure is surfaced as a communication error."""
    session = aiohttp.ClientSession()
    client = LowiApiClient("12345678A", "test-password", session)
    try:
        with (
            patch.object(
                session,
                "request",
                side_effect=aiohttp.ClientConnectionError("boom"),
            ),
            pytest.raises(LowiApiCommunicationError),
        ):
            await client.async_get_account_data()
    finally:
        await session.close()


async def test_export_import_cookies_roundtrip() -> None:
    """Cookies exported from one client can restore a session on another."""
    session = aiohttp.ClientSession()
    try:
        client = LowiApiClient("12345678A", "test-password", session)
        session.cookie_jar.update_cookies(
            {"sessionid": "abc123"},
            response_url=URL(PORTAL_BASE_URL),
        )

        cookies = client.export_cookies()
        assert cookies.get("sessionid") == "abc123"

        fresh_session = aiohttp.ClientSession()
        try:
            fresh_client = LowiApiClient("12345678A", "test-password", fresh_session)
            fresh_client.import_cookies(cookies)
            assert fresh_client.export_cookies().get("sessionid") == "abc123"
        finally:
            await fresh_session.close()
    finally:
        await session.close()
