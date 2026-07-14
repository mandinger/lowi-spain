"""Tests for the Lowi API client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import patch

import aiohttp
import pytest
from yarl import URL

from custom_components.lowi.api import (
    API_BASE_URL,
    PORTAL_BASE_URL,
    LowiApiAuthenticationError,
    LowiApiClient,
    LowiApiCommunicationError,
    LowiApiWafChallengeError,
)

from .const import (
    ACCOUNT_ID_PRIMARY,
    INTERNET_ACCOUNT_ID,
    LOGIN_ERROR_HTML,
    MOCK_SUBSCRIPTIONS_RESPONSE,
    MSISDN_PRIMARY,
    MSISDN_SECONDARY,
    WAF_CHALLENGE_BODY,
    login_page_html,
    otp_form_html,
    phone_select_html,
)

if TYPE_CHECKING:
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )

_ENTRY_URL = f"{PORTAL_BASE_URL}/oauth/"
_LOGIN_ACTION_URL = f"{PORTAL_BASE_URL}/login-step"
_PHONE_ACTION_URL = f"{PORTAL_BASE_URL}/phone-step"
_OTP_ACTION_URL = f"{PORTAL_BASE_URL}/otp-step"


def _client_from_mocker(
    aioclient_mock: AiohttpClientMocker,
) -> tuple[LowiApiClient, aiohttp.ClientSession]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    client = LowiApiClient("12345678A", "test-password", session)
    return client, session


def _register_happy_path_login(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(_ENTRY_URL, text=login_page_html(_LOGIN_ACTION_URL))
    aioclient_mock.post(
        _LOGIN_ACTION_URL,
        text=phone_select_html(_PHONE_ACTION_URL, ACCOUNT_ID_PRIMARY),
    )
    aioclient_mock.post(_PHONE_ACTION_URL, text=otp_form_html(_OTP_ACTION_URL))


async def test_start_login_success(aioclient_mock: AiohttpClientMocker) -> None:
    """A successful credentials step reaches the OTP form and stores its action."""
    _register_happy_path_login(aioclient_mock)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        await client.async_start_login()
    finally:
        await session.close()

    assert client._otp_action_url == _OTP_ACTION_URL


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


async def test_submit_otp_success_returns_parsed_summaries(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A correct OTP completes login and returns parsed mobile-line summaries."""
    _register_happy_path_login(aioclient_mock)
    aioclient_mock.post(_OTP_ACTION_URL, text="<html>ok</html>")
    aioclient_mock.get(
        f"{API_BASE_URL}me/subscriptions",
        json=MOCK_SUBSCRIPTIONS_RESPONSE,
    )

    client, session = _client_from_mocker(aioclient_mock)
    try:
        await client.async_start_login()
        summaries = await client.async_submit_otp("654321")
    finally:
        await session.close()

    msisdns = {summary.msisdn for summary in summaries}
    assert msisdns == {MSISDN_PRIMARY, MSISDN_SECONDARY}
    assert all(summary.account_id != INTERNET_ACCOUNT_ID for summary in summaries)


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
        with pytest.raises(LowiApiAuthenticationError):
            await client.async_submit_otp("000000")
    finally:
        await session.close()


async def test_get_all_summaries_parsing(aioclient_mock: AiohttpClientMocker) -> None:
    """Contracted tariff/bonus figures are parsed with GB->MB conversion."""
    aioclient_mock.get(
        f"{API_BASE_URL}me/subscriptions",
        json=MOCK_SUBSCRIPTIONS_RESPONSE,
    )
    client, session = _client_from_mocker(aioclient_mock)
    try:
        summaries = await client.async_get_all_summaries()
    finally:
        await session.close()

    primary = next(s for s in summaries if s.msisdn == MSISDN_PRIMARY)
    assert primary.tariff_data_included_mb == 150 * 1024
    assert primary.bonus_data_mb == 51200.0

    secondary = next(s for s in summaries if s.msisdn == MSISDN_SECONDARY)
    assert secondary.tariff_data_included_mb == 5 * 1024
    assert secondary.bonus_data_mb is None


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
            await client.async_get_all_summaries()
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
            await client.async_get_all_summaries()
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
            await client.async_get_all_summaries()
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
