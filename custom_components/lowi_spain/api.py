"""
API client for the (unofficial) Lowi customer API.

CONFIRMED (from a real browser capture, see CONTRIBUTING.md):
- The account/lines endpoint is a real, flat REST API at
  `https://www.lowi.es/api/2.0/me/subscriptions` (`GET`, no `Authorization`
  header - auth is via Django session cookies, not a bearer token).
- Login is NOT simple email/password: it's a Keycloak SSO flow at
  `login.lowi.es`, using the account's NIF/DNI as the username, and requires
  an SMS one-time code as a second factor.

UNVERIFIED / best-effort (flagged inline below, see CONTRIBUTING.md):
- The exact entry URL used to *start* the Keycloak flow.
- The field name Keycloak expects for the submitted SMS code.
- That exactly one phone-selection step always precedes the OTP step.
- Whether a session persisted across a Home Assistant restart survives
  Incapsula's `reese84` device-fingerprint check when reused from a
  different connection than the one that obtained it.

This module is the only place in the integration that talks HTTP to Lowi;
everything else works against the normalized `LowiSubscriptionSummary`
dataclass, so fixing any of the above should stay a contained change here.
"""

from __future__ import annotations

import asyncio
import re
import socket
from dataclasses import dataclass
from html import unescape as html_unescape
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import aiohttp
from yarl import URL

if TYPE_CHECKING:
    from collections.abc import Mapping

PORTAL_BASE_URL = "https://www.lowi.es/milowi"
API_BASE_URL = "https://www.lowi.es/api/2.0/"

# UNVERIFIED: inferred from the redirect_uri seen in a captured Keycloak
# session cookie, not from a captured *initial* request. If the Keycloak
# dance fails at the very first step, this is the first thing to check.
_LOGIN_ENTRY_URL = f"{PORTAL_BASE_URL}/oauth/"

# A realistic browser-like identity, to avoid trivially looking like a bot to
# Lowi's WAF. Should be replaced with the exact header set from a browser
# capture if requests are being challenged.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# Signatures of an Incapsula bot-detection challenge page, seen instead of
# the expected response. May need updating if Incapsula changes its
# challenge markup.
_WAF_BODY_MARKERS = (
    "Incapsula incident ID",
    "_Incapsula_Resource",
)
_WAF_HEADER_MARKERS = ("x-iinfo",)

# UNVERIFIED: standard Keycloak template class names for an error message on
# the login/OTP form. Real error copy wasn't captured.
_LOGIN_ERROR_MARKERS = ("kc-feedback-text", "alert-error")

_FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_INPUT_TAG_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


class LowiApiError(Exception):
    """Base exception for the Lowi API client."""


class LowiApiCommunicationError(LowiApiError):
    """Raised on network/timeout/transport failures talking to Lowi."""


class LowiApiAuthenticationError(LowiApiError):
    """
    Raised when Lowi rejects the credentials/OTP, or the session has expired.

    A cookie-session failure can't be silently retried the way a stale
    bearer token could: recovering requires a human to receive and enter a
    new SMS code, so this always surfaces to the user via Home Assistant's
    reauth flow rather than being retried automatically.
    """


class LowiApiWafChallengeError(LowiApiError):
    """
    Raised when Lowi's WAF returns a bot-detection challenge instead of data.

    Deliberately distinct from LowiApiAuthenticationError: a WAF challenge
    means "try again later", not "your credentials are wrong". Conflating
    the two would force needless reauth prompts and increase request
    volume, worsening WAF suspicion.
    """


@dataclass
class LowiSubscriptionSummary:
    """
    Normalized info for a single Lowi mobile line.

    cost_current_month/remaining_data_mb/total_data_mb/
    shared_data_received_mb are placeholders (None) until the live
    usage/consumption endpoint is captured (see CONTRIBUTING.md) - only the
    *contracted* allowance fields are populated today, from
    /me/subscriptions.
    """

    msisdn: str
    account_id: str
    tariff_data_included_mb: float | None = None
    bonus_data_mb: float | None = None
    cost_current_month: float | None = None
    accumulated_data_mb: float | None = None
    shared_data_received_mb: float | None = None
    remaining_data_mb: float | None = None
    total_data_mb: float | None = None


def _unit_to_mb(quantity: float | None, unit: str | None) -> float | None:
    """Convert a GB/MB quantity to MB. Unknown units are left as None."""
    if quantity is None:
        return None
    match (unit or "MB").upper():
        case "GB":
            return quantity * 1024
        case "MB":
            return quantity
        case _:
            return None


def _is_waf_challenge(response: aiohttp.ClientResponse, body_text: str) -> bool:
    """Detect an Incapsula bot-challenge page returned instead of JSON."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type and any(
        marker in response.headers for marker in _WAF_HEADER_MARKERS
    ):
        return True
    return any(marker in body_text for marker in _WAF_BODY_MARKERS)


def _looks_like_login_failure(html: str) -> bool:
    """Heuristic: does this Keycloak page show a login/OTP error message."""
    return any(marker in html for marker in _LOGIN_ERROR_MARKERS)


def _extract_form_action(html: str, base_url: str) -> str:
    """Extract and resolve a login form's action URL from a Keycloak page."""
    for tag in _FORM_TAG_RE.findall(html):
        attrs = dict(_ATTR_RE.findall(tag))
        if "action" in attrs:
            return urljoin(base_url, html_unescape(attrs["action"]))
    msg = "Could not find a login form in Lowi's response"
    raise LowiApiError(msg)


def _extract_input_value(html: str, field_name: str) -> str | None:
    """Extract a named <input>'s value attribute from a Keycloak page."""
    for tag in _INPUT_TAG_RE.findall(html):
        attrs = dict(_ATTR_RE.findall(tag))
        if attrs.get("name") == field_name:
            return attrs.get("value")
    return None


def _parse_subscriptions_response(
    raw: Mapping[str, Any],
) -> list[LowiSubscriptionSummary]:
    """
    Parse the real /me/subscriptions response into mobile-line summaries.

    Only MOBILE-type subscriptions are kept: INTERNET/TV lines share the
    same response but have no msisdn and aren't Lowi mobile lines.
    """
    summaries = []
    for package in raw.get("data", []):
        for subscription in package.get("subscriptions", []):
            if subscription.get("type") != "MOBILE":
                continue
            msisdn = subscription.get("msisdn")
            if not msisdn:
                continue

            tariff_data_included_mb = None
            for item in subscription.get("product", {}).get("product_items", []):
                if item.get("type") == "DATA":
                    tariff_data_included_mb = _unit_to_mb(
                        item.get("quantity"),
                        item.get("unit"),
                    )
                    break

            bonus_data_mb = None
            for addon in subscription.get("addons", []):
                if addon.get("type") == "BOND_DATA":
                    bonus_data_mb = _unit_to_mb(
                        addon.get("current_limit"),
                        addon.get("unit", "MB"),
                    )
                    break

            summaries.append(
                LowiSubscriptionSummary(
                    msisdn=msisdn,
                    account_id=str(subscription["id"]),
                    tariff_data_included_mb=tariff_data_included_mb,
                    bonus_data_mb=bonus_data_mb,
                ),
            )
    return summaries


class LowiApiClient:
    """Client for the Lowi customer API and its Keycloak-based login."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the client. `username` is the account's NIF/DNI."""
        self._username = username
        self._password = password
        self._session = session
        self._otp_action_url: str | None = None

    def export_cookies(self) -> dict[str, str]:
        """Export session cookies for persistence across Home Assistant restarts."""
        jar = self._session.cookie_jar
        return {
            name: morsel.value
            for name, morsel in jar.filter_cookies(URL(PORTAL_BASE_URL)).items()
        }

    def import_cookies(self, cookies: Mapping[str, str]) -> None:
        """Restore previously-exported cookies into this client's session."""
        if cookies:
            self._session.cookie_jar.update_cookies(
                cookies,
                response_url=URL(PORTAL_BASE_URL),
            )

    async def async_start_login(self) -> None:
        """
        Submit credentials and trigger an SMS one-time code.

        Call async_submit_otp() next with the code received by SMS.
        """
        html, url = await self._get_html(_LOGIN_ENTRY_URL, params={"next": "/milowi/"})
        action_url = _extract_form_action(html, url)

        html, url = await self._post_html(
            action_url,
            {
                "username": self._username,
                "password": self._password,
                "credentialId": "",
            },
        )
        if _looks_like_login_failure(html):
            msg = "Invalid username or password"
            raise LowiApiAuthenticationError(msg)

        # Best-effort: auto-pick the first offered phone. Accounts with a
        # single registered line have only one choice; this would need to
        # become a real config-flow choice for accounts offering more than
        # one number to send the code to.
        phone_id = _extract_input_value(html, "selectedPhone")
        if phone_id is None:
            msg = "Could not find a phone number to send the verification code to"
            raise LowiApiError(msg)
        action_url = _extract_form_action(html, url)

        html, url = await self._post_html(
            action_url,
            {"selectedPhone": phone_id, "next": "Enviar código"},
        )
        if _looks_like_login_failure(html):
            msg = "Lowi rejected the phone selection step"
            raise LowiApiAuthenticationError(msg)
        self._otp_action_url = _extract_form_action(html, url)

    async def async_submit_otp(self, code: str) -> list[LowiSubscriptionSummary]:
        """Submit the SMS one-time code, completing the login."""
        if self._otp_action_url is None:
            msg = "async_start_login() must be awaited before async_submit_otp()"
            raise LowiApiError(msg)

        html, _url = await self._post_html(self._otp_action_url, {"code": code})
        if _looks_like_login_failure(html):
            msg = "Invalid verification code"
            raise LowiApiAuthenticationError(msg)
        self._otp_action_url = None

        return await self.async_get_all_summaries()

    async def async_get_all_summaries(self) -> list[LowiSubscriptionSummary]:
        """Fetch the account's mobile lines and their contracted allowances."""
        payload = await self._async_api_request("GET", "me/subscriptions")
        return _parse_subscriptions_response(payload)

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Perform the underlying HTTP request, mapping transport failures."""
        try:
            async with asyncio.timeout(10):
                return await self._session.request(method, url, **kwargs)
        except TimeoutError as exception:
            msg = f"Timeout communicating with Lowi - {exception}"
            raise LowiApiCommunicationError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error communicating with Lowi - {exception}"
            raise LowiApiCommunicationError(msg) from exception

    async def _get_html(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> tuple[str, str]:
        """GET a page expected to contain a Keycloak login form."""
        response = await self._request(
            "GET",
            url,
            params=params,
            headers=DEFAULT_HEADERS,
        )
        html = await response.text()
        if _is_waf_challenge(response, html):
            msg = "Lowi's anti-bot protection is blocking this request"
            raise LowiApiWafChallengeError(msg)
        return html, str(response.url)

    async def _post_html(
        self,
        url: str,
        data: Mapping[str, str],
    ) -> tuple[str, str]:
        """POST a Keycloak login-action form."""
        response = await self._request(
            "POST",
            url,
            data=data,
            headers={
                **DEFAULT_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        html = await response.text()
        if _is_waf_challenge(response, html):
            msg = "Lowi's anti-bot protection is blocking this request"
            raise LowiApiWafChallengeError(msg)
        return html, str(response.url)

    async def _async_api_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make a request against the JSON customer API."""
        response = await self._request(
            method,
            f"{API_BASE_URL}{path}",
            headers=DEFAULT_HEADERS,
            **kwargs,
        )
        body_text = await response.text()

        if _is_waf_challenge(response, body_text):
            msg = "Lowi's anti-bot protection is blocking this request"
            raise LowiApiWafChallengeError(msg)

        if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            msg = "Not authenticated with Lowi"
            raise LowiApiAuthenticationError(msg)

        if "application/json" not in response.headers.get("Content-Type", ""):
            # A cookie-session failure doesn't 401 here; Lowi just serves the
            # HTML login page instead of JSON. Treat that as an auth failure
            # rather than a generic communication error.
            msg = "Not authenticated with Lowi (received a non-JSON response)"
            raise LowiApiAuthenticationError(msg)

        if response.status >= HTTPStatus.BAD_REQUEST:
            msg = f"Lowi returned HTTP {response.status}"
            raise LowiApiCommunicationError(msg)

        try:
            return await response.json(content_type=None)
        except ValueError as exception:
            msg = f"Unexpected response from Lowi - {exception}"
            raise LowiApiCommunicationError(msg) from exception
