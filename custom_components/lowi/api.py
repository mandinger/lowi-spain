"""
API client for the (unofficial) Lowi customer API.

The endpoint paths, auth scheme, and field names in this module are
placeholders derived from an old, now-dead reverse-engineered mobile API
(`mobile.lowi.es`, confirmed NXDOMAIN - see CONTRIBUTING.md). They are
expected to be replaced once a real capture of the live lowi.es customer
portal is available. This module is the only place in the integration that
should need to change when that happens: everything else talks to the
normalized dataclasses defined here, not to Lowi's raw JSON.
"""

from __future__ import annotations

import asyncio
import base64
import socket
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Mapping

# PLACEHOLDER: this host no longer resolves. Replace with the real lowi.es
# customer-portal API once a browser capture is available (CONTRIBUTING.md).
API_BASE_URL = "https://mobile.lowi.es/api/1.0/"

# A realistic browser-like identity, to avoid trivially looking like a bot to
# Lowi's WAF. Once we have a real capture, these should be replaced with the
# exact header set copied from it rather than hand-guessed.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# Signatures of an Incapsula bot-detection challenge page, seen instead of
# the expected JSON body. May need updating if Incapsula changes its
# challenge markup.
_WAF_BODY_MARKERS = (
    "Incapsula incident ID",
    "_Incapsula_Resource",
)
_WAF_HEADER_MARKERS = ("x-iinfo",)


class LowiApiError(Exception):
    """Base exception for the Lowi API client."""


class LowiApiCommunicationError(LowiApiError):
    """Raised on network/timeout/transport failures talking to Lowi."""


class LowiApiAuthenticationError(LowiApiError):
    """Raised when Lowi rejects the supplied credentials."""


class LowiApiWafChallengeError(LowiApiError):
    """
    Raised when Lowi's WAF returns a bot-detection challenge instead of data.

    Deliberately distinct from LowiApiAuthenticationError: a WAF challenge
    means "try again later", not "your password is wrong". Conflating the
    two would make the config flow/coordinator force reauth loops that
    themselves increase request volume and worsen WAF suspicion.
    """


@dataclass
class LowiSubscriptionSummary:
    """
    Normalized usage summary for a single Lowi phone line.

    Units are spelled out in the field names on purpose: the legacy API this
    was modeled on mixed MB and bytes across sibling fields, which is an easy
    trap to reintroduce silently.
    """

    msisdn: str
    account_id: str
    cost_current_month: float | None = None
    tariff_data_included_mb: float | None = None
    bonus_data_mb: float | None = None
    accumulated_data_mb: float | None = None
    shared_data_received_mb: float | None = None
    remaining_data_mb: float | None = None
    total_data_mb: float | None = None


@dataclass
class LowiUser:
    """Normalized logged-in user, with the subscriptions to fetch usage for."""

    name: str
    first_last_name: str
    subscriptions: list[LowiSubscriptionSummary] = field(default_factory=list)


def _bytes_to_mb(value: float | None) -> float | None:
    """Convert a byte value to MB, passing through None unchanged."""
    if value is None:
        return None
    return value / (1024 * 1024)


def _is_waf_challenge(response: aiohttp.ClientResponse, body_text: str) -> bool:
    """Detect an Incapsula bot-challenge page returned instead of JSON."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type and any(
        marker in response.headers for marker in _WAF_HEADER_MARKERS
    ):
        return True
    return any(marker in body_text for marker in _WAF_BODY_MARKERS)


class LowiApiClient:
    """Client for the (currently placeholder) Lowi API."""

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the client."""
        self._email = email
        self._password = password
        self._session = session
        self._token: str | None = None
        self._subscriptions: list[LowiSubscriptionSummary] = []

    async def async_login(self) -> LowiUser:
        """Log in and return the account's user/subscription info."""
        auth = base64.b64encode(f"{self._email}:{self._password}".encode()).decode()
        payload = await self._async_request(
            "POST",
            "login",
            headers={"Authorization": f"Basic {auth}"},
            authenticated=False,
        )
        if payload.get("result", {}).get("resultCode") != 0:
            msg = "Invalid credentials"
            raise LowiApiAuthenticationError(msg)

        data = payload["data"]
        self._token = data["auth_token"]
        user = self._parse_user(data["user"])
        self._subscriptions = user.subscriptions
        return user

    async def async_get_all_summaries(self) -> list[LowiSubscriptionSummary]:
        """Fetch usage summaries for every subscription on the account."""
        user = await self.async_login()
        return [
            await self.async_get_subscription_summary(subscription.account_id)
            for subscription in user.subscriptions
        ]

    async def async_get_subscription_summary(
        self,
        account_id: str,
        *,
        _retried: bool = False,
    ) -> LowiSubscriptionSummary:
        """Fetch the usage summary for a single subscription."""
        if self._token is None:
            await self.async_login()

        try:
            payload = await self._async_request(
                "GET",
                "home_summary",
                params={"subscription": account_id, "account": account_id},
            )
        except LowiApiAuthenticationError:
            if _retried:
                raise
            # The session token may have simply expired - retry once after a
            # fresh login rather than surfacing a spurious auth failure.
            self._token = None
            return await self.async_get_subscription_summary(
                account_id,
                _retried=True,
            )

        if payload.get("result", {}).get("resultCode") != 0:
            msg = f"Failed to fetch summary for subscription {account_id}"
            raise LowiApiError(msg)

        return self._parse_summary(account_id, payload["data"])

    def _parse_user(self, raw: Mapping[str, Any]) -> LowiUser:
        """Build a LowiUser from the login response's user object."""
        subscriptions = [
            LowiSubscriptionSummary(
                msisdn=subscription["msisdn"],
                account_id=str(account["id"]),
            )
            for account in raw.get("accounts", [])
            for subscription in account.get("subscriptions", [])
        ]
        return LowiUser(
            name=raw["name"],
            first_last_name=raw.get("first_last_name", ""),
            subscriptions=subscriptions,
        )

    def _parse_summary(
        self,
        account_id: str,
        raw: Mapping[str, Any],
    ) -> LowiSubscriptionSummary:
        """Build a normalized LowiSubscriptionSummary from a home_summary response."""
        msisdn = next(
            (
                subscription.msisdn
                for subscription in self._subscriptions
                if subscription.account_id == account_id
            ),
            account_id,
        )
        return LowiSubscriptionSummary(
            msisdn=msisdn,
            account_id=account_id,
            cost_current_month=raw.get("cost_current_month"),
            tariff_data_included_mb=raw.get("current_tariff_data_included"),
            bonus_data_mb=raw.get("bonds_data"),
            accumulated_data_mb=_bytes_to_mb(raw.get("acumulative_data")),
            shared_data_received_mb=raw.get("shared_data_received"),
            remaining_data_mb=raw.get("graph_remaining_data"),
            total_data_mb=raw.get("graph_total_data"),
        )

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """
        Make a request against the Lowi API.

        Centralizes header defaults, WAF-challenge detection, and mapping of
        transport/HTTP failures onto our exception hierarchy.
        """
        request_headers: dict[str, str] = {**DEFAULT_HEADERS, **(headers or {})}
        if authenticated:
            if self._token is None:
                msg = "Not logged in"
                raise LowiApiAuthenticationError(msg)
            request_headers["Authorization"] = f"Token {self._token}"

        try:
            async with asyncio.timeout(10):
                response = await self._session.request(
                    method,
                    f"{API_BASE_URL}{path}",
                    params=params,
                    headers=request_headers,
                )
                body_text = await response.text()
        except TimeoutError as exception:
            msg = f"Timeout communicating with Lowi - {exception}"
            raise LowiApiCommunicationError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error communicating with Lowi - {exception}"
            raise LowiApiCommunicationError(msg) from exception

        if _is_waf_challenge(response, body_text):
            msg = "Lowi's anti-bot protection is blocking this request"
            raise LowiApiWafChallengeError(msg)

        if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            msg = "Invalid credentials"
            raise LowiApiAuthenticationError(msg)

        if response.status >= HTTPStatus.BAD_REQUEST:
            msg = f"Lowi returned HTTP {response.status}"
            raise LowiApiCommunicationError(msg)

        try:
            return await response.json(content_type=None)
        except ValueError as exception:
            msg = f"Unexpected response from Lowi - {exception}"
            raise LowiApiCommunicationError(msg) from exception
