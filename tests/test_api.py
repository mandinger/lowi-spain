"""Tests for the Lowi API client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from custom_components.lowi.api import (
    API_BASE_URL,
    LowiApiAuthenticationError,
    LowiApiClient,
    LowiApiCommunicationError,
    LowiApiWafChallengeError,
    LowiSubscriptionSummary,
    LowiUser,
    _bytes_to_mb,
)

from .const import (
    ACCOUNT_ID_SINGLE,
    MOCK_LOGIN_FAILURE_RESPONSE,
    MOCK_LOGIN_RESPONSE,
    MOCK_LOGIN_RESPONSE_MULTI,
    MOCK_SUMMARY_RESPONSE,
    MSISDN_SECOND,
    MSISDN_SINGLE,
    WAF_CHALLENGE_BODY,
)

if TYPE_CHECKING:
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


def _client_from_mocker(
    aioclient_mock: AiohttpClientMocker,
) -> tuple[LowiApiClient, aiohttp.ClientSession]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    client = LowiApiClient("test@example.com", "test-password", session)
    return client, session


def test_bytes_to_mb() -> None:
    """None passes through unchanged; byte values convert to MB."""
    assert _bytes_to_mb(None) is None
    assert _bytes_to_mb(209715200) == pytest.approx(200.0)


async def test_login_success(aioclient_mock: AiohttpClientMocker) -> None:
    """A successful login stores the token and returns the parsed user."""
    aioclient_mock.post(f"{API_BASE_URL}login", json=MOCK_LOGIN_RESPONSE)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        user = await client.async_login()
    finally:
        await session.close()

    assert user.name == "Test"
    assert len(user.subscriptions) == 1
    assert user.subscriptions[0].msisdn == MSISDN_SINGLE
    assert user.subscriptions[0].account_id == ACCOUNT_ID_SINGLE
    assert client._token == "mock-token"


async def test_login_invalid_credentials(aioclient_mock: AiohttpClientMocker) -> None:
    """A resultCode != 0 on login is surfaced as an authentication error."""
    aioclient_mock.post(f"{API_BASE_URL}login", json=MOCK_LOGIN_FAILURE_RESPONSE)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        with pytest.raises(LowiApiAuthenticationError):
            await client.async_login()
    finally:
        await session.close()


async def test_login_http_401(aioclient_mock: AiohttpClientMocker) -> None:
    """An HTTP 401 on login is surfaced as an authentication error."""
    aioclient_mock.post(f"{API_BASE_URL}login", status=401, json={})
    client, session = _client_from_mocker(aioclient_mock)
    try:
        with pytest.raises(LowiApiAuthenticationError):
            await client.async_login()
    finally:
        await session.close()


async def test_get_subscription_summary(aioclient_mock: AiohttpClientMocker) -> None:
    """A summary response is normalized, including bytes -> MB conversion."""
    aioclient_mock.post(f"{API_BASE_URL}login", json=MOCK_LOGIN_RESPONSE)
    aioclient_mock.get(f"{API_BASE_URL}home_summary", json=MOCK_SUMMARY_RESPONSE)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        await client.async_login()
        summary = await client.async_get_subscription_summary(ACCOUNT_ID_SINGLE)
    finally:
        await session.close()

    assert summary.msisdn == MSISDN_SINGLE
    assert summary.cost_current_month == 12.34
    assert summary.tariff_data_included_mb == 5000
    assert summary.bonus_data_mb == 1000
    assert summary.accumulated_data_mb == pytest.approx(200.0)
    assert summary.remaining_data_mb == 4200
    assert summary.total_data_mb == 6000


async def test_get_all_summaries_multi_subscription(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """All subscriptions on the account are fetched and keyed correctly."""
    aioclient_mock.post(f"{API_BASE_URL}login", json=MOCK_LOGIN_RESPONSE_MULTI)
    aioclient_mock.get(f"{API_BASE_URL}home_summary", json=MOCK_SUMMARY_RESPONSE)
    client, session = _client_from_mocker(aioclient_mock)
    try:
        summaries = await client.async_get_all_summaries()
    finally:
        await session.close()

    assert {summary.msisdn for summary in summaries} == {
        MSISDN_SINGLE,
        MSISDN_SECOND,
    }


async def test_waf_challenge_detected(aioclient_mock: AiohttpClientMocker) -> None:
    """An Incapsula challenge page is surfaced as a distinct WAF error."""
    aioclient_mock.post(
        f"{API_BASE_URL}login",
        text=WAF_CHALLENGE_BODY,
        headers={"X-Iinfo": "1-2-3", "Content-Type": "text/html"},
    )
    client, session = _client_from_mocker(aioclient_mock)
    try:
        with pytest.raises(LowiApiWafChallengeError):
            await client.async_login()
    finally:
        await session.close()


async def test_communication_error_on_transport_failure() -> None:
    """A transport-level failure is surfaced as a communication error."""
    session = aiohttp.ClientSession()
    client = LowiApiClient("test@example.com", "test-password", session)
    try:
        with (
            patch.object(
                session,
                "request",
                side_effect=aiohttp.ClientConnectionError("boom"),
            ),
            pytest.raises(LowiApiCommunicationError),
        ):
            await client.async_login()
    finally:
        await session.close()


async def test_retry_once_on_expired_token(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A 401 on an authenticated call triggers exactly one re-login retry."""
    client, session = _client_from_mocker(aioclient_mock)
    client._token = "stale-token"
    client._subscriptions = [
        LowiSubscriptionSummary(msisdn=MSISDN_SINGLE, account_id=ACCOUNT_ID_SINGLE),
    ]

    login_mock = AsyncMock(
        return_value=LowiUser(name="Test", first_last_name="User", subscriptions=[]),
    )
    request_mock = AsyncMock(
        side_effect=[
            LowiApiAuthenticationError("expired"),
            {"result": {"resultCode": 0}, "data": MOCK_SUMMARY_RESPONSE["data"]},
        ],
    )

    try:
        with (
            patch.object(client, "_async_request", request_mock),
            patch.object(client, "async_login", login_mock),
        ):
            summary = await client.async_get_subscription_summary(ACCOUNT_ID_SINGLE)
    finally:
        await session.close()

    login_mock.assert_awaited_once()
    assert request_mock.await_count == 2
    assert summary.msisdn == MSISDN_SINGLE
