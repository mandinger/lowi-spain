"""
API client for the (unofficial) Lowi customer portal.

Auth flow, endpoints, and JSON schemas below are CONFIRMED from a real login
HAR plus authenticated endpoint captures - see docs/lowi-auth-and-api.md for
the full research writeup this module is built against:

- Login starts at `GET {PORTAL_BASE_URL}/login/`, which redirects into a
  Keycloak (realm `milowi`, client `web-client`) authorization-code+PKCE
  flow. The account's NIF/DNI is the username. `web-client` is a
  confidential client, so the integration can't do its own token exchange -
  it rides the Django-issued `sessionid` cookie set after Keycloak redirects
  back to the callback (see docs/lowi-auth-and-api.md §1, §5).
- MFA is always an SMS one-time code, but multi-line accounts must first
  pick which number receives it (`selectedPhone=<msisdn>`).
- Line/tariff data comes from `GET {API_BASE_URL}me/subscriptions`; live
  usage and account-wide billing come from
  `GET {MILOWI_API_BASE_URL}me/consumptions` and `.../me/billings`.

Still best-effort/unverified (flagged inline below):
- The *display label* for each offered phone option - only the submitted
  `selectedPhone` value is confirmed by a capture, not the surrounding
  label markup - see CONTRIBUTING.md.

This module is the only place in the integration that talks HTTP to Lowi;
everything else works against the normalized LowiAccountData /
LowiSubscriptionSummary dataclasses, so fixing any of the above should stay
a contained change here.
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

from .const import LOGGER

if TYPE_CHECKING:
    from collections.abc import Mapping

PORTAL_BASE_URL = "https://www.lowi.es/milowi"
API_BASE_URL = "https://www.lowi.es/api/2.0/"
MILOWI_API_BASE_URL = "https://www.lowi.es/api/milowi/v1/"
KEYCLOAK_BASE_URL = "https://login.lowi.es"

# UNVERIFIED (the refresh-flow HAR's Set-Cookie headers were scrubbed before
# capture, so this isn't confirmed byte-for-byte): Keycloak's documented
# default is to scope its own auth cookies (KEYCLOAK_IDENTITY,
# KEYCLOAK_SESSION, AUTH_SESSION_ID, KC_RESTART, ...) to this realm path
# rather than the bare host, so a single Keycloak instance hosting multiple
# realms doesn't leak cookies across them. export_sso_cookies()/
# import_sso_cookies() below filter/scope against this path - not just
# KEYCLOAK_BASE_URL - since a too-narrow filter would silently exclude them.
_KEYCLOAK_REALM_URL = f"{KEYCLOAK_BASE_URL}/realms/milowi/"

# Confirmed by docs/lowi-auth-and-api.md §4 Step 1: this is Django's login
# entry point, which 302-redirects into the Keycloak authorize URL. Also
# reused as-is for the silent-refresh dance in _async_silent_reauth() below -
# a captured "already logged in" browser reload confirms Django's own
# redirect (not a hand-built prompt=none Keycloak call) is what lets a
# returning session skip the login form.
_LOGIN_ENTRY_URL = f"{PORTAL_BASE_URL}/login/"

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

# Signature of an actual Incapsula block/incident page. Deliberately narrow:
# `X-Iinfo` and injected anti-bot script tags (e.g. `_Incapsula_Resource`)
# appear on *all* traffic through Incapsula's proxy, blocked or not - using
# either as a signal caused false positives on every normal HTML response
# (confirmed both via a plain curl to lowi.es and via a real user report).
# Only this human-readable incident-page text is specific to an actual block.
_WAF_BODY_MARKERS = ("Incapsula incident ID",)

# UNVERIFIED: standard Keycloak template class names for an error message on
# the login/OTP form. Real error copy wasn't captured.
_LOGIN_ERROR_MARKERS = ("kc-feedback-text", "alert-error")

# Confirmed field name for the phone-line choice: docs/lowi-auth-and-api.md
# §4 Step 3 captured `selectedPhone=<MSISDN>&next=Enviar+código` verbatim.
_PHONE_FIELD_NAME = "selectedPhone"

_FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_INPUT_TAG_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_SELECT_RE = re.compile(
    r'<select\b[^>]*\bname\s*=\s*"([^"]*)"[^>]*>(.*?)</select>',
    re.IGNORECASE | re.DOTALL,
)
_OPTION_FULL_RE = re.compile(
    r"<option\b([^>]*)>(.*?)</option>",
    re.IGNORECASE | re.DOTALL,
)
_LABEL_RE = re.compile(
    r'<label\b[^>]*\bfor\s*=\s*"([^"]*)"[^>]*>(.*?)</label>',
    re.IGNORECASE | re.DOTALL,
)
_BUTTON_RE = re.compile(r"<button\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


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
class PhoneOption:
    """A phone number Keycloak offered to receive the SMS one-time code."""

    value: str
    label: str


@dataclass
class LowiSubscriptionSummary:
    """Normalized info for a single Lowi mobile line."""

    msisdn: str
    subscription_id: str
    plan_name: str | None = None
    price: float | None = None
    data_included_mb: float | None = None
    bonus_data_mb: float | None = None
    data_total_mb: float | None = None
    data_remaining_mb: float | None = None
    data_used_mb: float | None = None
    data_unlimited: bool = False
    voice_unlimited: bool | None = None
    roaming_zones: list[str] | None = None
    extra_sections: list[dict[str, Any]] | None = None


@dataclass
class LowiAccountSummary:
    """Account-wide figures that aren't tied to a single phone line."""

    current_month_cost: float | None = None
    billing_period_end: int | None = None
    last_invoice_amount: float | None = None
    last_invoice_status: str | None = None
    last_invoice_date: int | None = None


@dataclass
class LowiAccountData:
    """Everything the coordinator needs for one poll: account + all lines."""

    account: LowiAccountSummary
    lines: dict[str, LowiSubscriptionSummary]


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


def _to_float(value: str | float | None) -> float | None:
    """Parse a numeric field from Lowi's JSON (often a string), tolerating None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantity_mb(container: Mapping[str, Any] | None, field: str) -> float | None:
    """Read `container[field]` (a {"value": .., "unit": ..} pair) as MB."""
    if not container:
        return None
    quantity = container.get(field)
    if not quantity:
        return None
    return _unit_to_mb(_to_float(quantity.get("value")), quantity.get("unit"))


def _is_waf_challenge(body_text: str) -> bool:
    """Detect an Incapsula bot-challenge/incident page in the response body."""
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


def _clean_text(html_fragment: str) -> str:
    """Strip tags and collapse whitespace from an HTML fragment."""
    text = _TAG_STRIP_RE.sub(" ", html_fragment)
    return " ".join(html_unescape(text).split())


def _extract_phone_options(html: str) -> list[PhoneOption]:
    """
    Extract the offered phone-line options from a Keycloak phone-select page.

    Handles the field being rendered as a <select> or as radio/hidden
    <input>s, in that order. The display label is a best-effort guess -
    only the submitted `value` (`selectedPhone=<MSISDN>`) is confirmed by a
    real capture, not the surrounding label markup. A <label for="..."> tag
    matching an input's `id` is used when present; otherwise the label falls
    back to the raw value, so an option is always usable even if unlabeled.
    """
    for name, body in _SELECT_RE.findall(html):
        if name != _PHONE_FIELD_NAME:
            continue
        options = []
        for attrs_str, inner in _OPTION_FULL_RE.findall(body):
            value = dict(_ATTR_RE.findall(attrs_str)).get("value")
            if not value:
                continue
            options.append(PhoneOption(value=value, label=_clean_text(inner) or value))
        return options

    labels_by_id = {
        target_id: _clean_text(inner) for target_id, inner in _LABEL_RE.findall(html)
    }
    options = []
    for tag in _INPUT_TAG_RE.findall(html):
        attrs = dict(_ATTR_RE.findall(tag))
        if attrs.get("name") != _PHONE_FIELD_NAME or not attrs.get("value"):
            continue
        value = attrs["value"]
        options.append(
            PhoneOption(
                value=value, label=labels_by_id.get(attrs.get("id", "")) or value
            ),
        )
    return options


def _describe_form_fields(html: str) -> str:
    """
    Summarize a page's form fields for debug logging.

    Emits field *names* and control types only - never their values - so the
    injected CSRF/session tokens and any prefilled data are not logged.
    """
    inputs = [
        dict(_ATTR_RE.findall(tag)).get("name", "?")
        for tag in _INPUT_TAG_RE.findall(html)
    ]
    selects = [name for name, _ in _SELECT_RE.findall(html)]
    buttons = [
        dict(_ATTR_RE.findall(tag)).get("name", "?") for tag in _BUTTON_RE.findall(html)
    ]
    return f"inputs={inputs} selects={selects} buttons={buttons}"


def _parse_subscriptions_response(
    raw: Mapping[str, Any],
) -> dict[str, LowiSubscriptionSummary]:
    """
    Parse the /me/subscriptions response into mobile-line summaries.

    Keyed by subscription_id (as a string) so live usage from
    /me/consumptions can be merged in by the same key. Only MOBILE-type
    subscriptions are kept: INTERNET/TV lines share the same response but
    have no msisdn and aren't Lowi mobile lines.
    """
    summaries: dict[str, LowiSubscriptionSummary] = {}
    for package in raw.get("data", []):
        for subscription in package.get("subscriptions", []):
            if subscription.get("type") != "MOBILE":
                continue
            msisdn = subscription.get("msisdn")
            if not msisdn:
                continue

            product = subscription.get("product", {})
            data_included_mb = None
            for item in product.get("product_items", []):
                if item.get("type") == "DATA":
                    data_included_mb = _unit_to_mb(
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

            subscription_id = str(subscription["id"])
            summaries[subscription_id] = LowiSubscriptionSummary(
                msisdn=msisdn,
                subscription_id=subscription_id,
                plan_name=product.get("contract_name") or package.get("name"),
                price=_to_float(product.get("charging_amount")),
                data_included_mb=data_included_mb,
                bonus_data_mb=bonus_data_mb,
            )
    return summaries


def _apply_consumption(
    line: LowiSubscriptionSummary,
    consumption: Mapping[str, Any],
) -> None:
    """Fill live usage fields onto a line summary from its consumptions entry."""
    consumptions = consumption.get("consumptions") or {}

    data = consumptions.get("data_consumption")
    if data:
        line.data_unlimited = bool(data.get("is_unlimited"))
        line.data_total_mb = _quantity_mb(data.get("resume"), "quantity")
        line.data_remaining_mb = _quantity_mb(data.get("resume"), "available")
        if line.data_total_mb is not None and line.data_remaining_mb is not None:
            line.data_used_mb = line.data_total_mb - line.data_remaining_mb

        included_mb = _quantity_mb(data.get("included"), "quantity")
        if included_mb is not None:
            line.data_included_mb = included_mb

        extra = data.get("extra")
        extra_mb = _quantity_mb(extra, "quantity")
        if extra_mb is not None:
            line.bonus_data_mb = extra_mb
        if extra:
            line.extra_sections = extra.get("sections") or None

    voice = consumptions.get("voice_consumption")
    if voice:
        line.voice_unlimited = voice.get("is_unlimited")

    roaming = consumption.get("roaming")
    if roaming:
        line.roaming_zones = roaming.get("zones") or None


def _parse_consumptions_response(
    raw: Mapping[str, Any],
) -> tuple[LowiAccountSummary, dict[str, Mapping[str, Any]]]:
    """Split /me/consumptions into the account-wide summary + per-line raw entries."""
    summary_raw = raw.get("summary") or {}
    account = LowiAccountSummary(
        current_month_cost=_to_float(
            (summary_raw.get("total_price") or {}).get("amount"),
        ),
        billing_period_end=summary_raw.get("billing_period_end"),
    )
    by_subscription_id = {
        str(entry["subscription_id"]): entry
        for entry in raw.get("subscriptions", [])
        if entry.get("subscription_id") is not None
    }
    return account, by_subscription_id


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
        self._phone_action_url: str | None = None
        self._otp_action_url: str | None = None

    def export_cookies(self) -> dict[str, str]:
        """Export portal (www.lowi.es) session cookies, e.g. `sessionid`."""
        jar = self._session.cookie_jar
        return {
            name: morsel.value
            for name, morsel in jar.filter_cookies(URL(PORTAL_BASE_URL)).items()
        }

    def import_cookies(self, cookies: Mapping[str, str]) -> None:
        """Restore previously-exported portal cookies into this client's session."""
        if cookies:
            self._session.cookie_jar.update_cookies(
                cookies,
                response_url=URL(PORTAL_BASE_URL),
            )

    def export_sso_cookies(self) -> dict[str, str]:
        """
        Export Keycloak SSO cookies (login.lowi.es), e.g. `KEYCLOAK_IDENTITY`.

        Kept separate from export_cookies(): these live on a different host
        than the portal `sessionid`, and aiohttp's cookie jar scopes an
        imported batch to a single host, so the two sets must be persisted
        and restored independently. This is what a silent
        _async_silent_reauth() rides to mint a fresh `sessionid` without
        redoing the SMS one-time-code login.

        Filtered against _KEYCLOAK_REALM_URL, not just the bare host: Keycloak
        scopes these cookies to `Path=/realms/milowi/`, and cookie-path
        matching means filtering against the host root silently excludes
        them (they'd still be sent on the real authorize request - which
        uses the realm path - so this only breaks *exporting* them, e.g. for
        persistence across a restart).
        """
        jar = self._session.cookie_jar
        return {
            name: morsel.value
            for name, morsel in jar.filter_cookies(URL(_KEYCLOAK_REALM_URL)).items()
        }

    def import_sso_cookies(self, cookies: Mapping[str, str]) -> None:
        """Restore previously-exported Keycloak SSO cookies into this session."""
        if cookies:
            self._session.cookie_jar.update_cookies(
                cookies,
                response_url=URL(_KEYCLOAK_REALM_URL),
            )

    async def async_start_login(self) -> list[PhoneOption]:
        """
        Submit credentials and return the phone numbers offered for the SMS code.

        Call async_select_phone() next with the chosen option's value.
        """
        html, url = await self._get_html(_LOGIN_ENTRY_URL)
        action_url = _extract_form_action(html, url)

        html, url = await self._post_html(
            action_url,
            {
                "username": self._username,
                "password": self._password,
                # Confirmed by docs/lowi-auth-and-api.md §5: needed for a
                # long-lived Keycloak SSO session across HA restarts.
                "rememberMe": "on",
                "credentialId": "",
            },
        )
        if _looks_like_login_failure(html):
            msg = "Invalid username or password"
            raise LowiApiAuthenticationError(msg)

        # The field structure (names/types only, no token values) of the page
        # returned after credentials, so the real markup can be diagnosed.
        landed_path = str(URL(url).with_query(None))
        fields = _describe_form_fields(html)
        LOGGER.debug("Lowi post-credentials page at %s: %s", landed_path, fields)

        phone_options = _extract_phone_options(html)
        if not phone_options:
            # Field names (no values) are embedded in the message so this is
            # diagnosable straight from the surfaced error, without needing
            # debug logging enabled. See CONTRIBUTING.md.
            msg = (
                "Could not find a phone number to send the verification code "
                f"to. Landed on {landed_path} with {fields}. The login page "
                "structure may differ from what was captured."
            )
            raise LowiApiError(msg)

        self._phone_action_url = _extract_form_action(html, url)
        return phone_options

    async def async_select_phone(self, phone_id: str) -> None:
        """Choose which phone receives the SMS code; Keycloak sends it immediately."""
        if self._phone_action_url is None:
            msg = "async_start_login() must be awaited before async_select_phone()"
            raise LowiApiError(msg)

        html, url = await self._post_html(
            self._phone_action_url,
            {"selectedPhone": phone_id, "next": "Enviar código"},
        )
        if _looks_like_login_failure(html):
            msg = "Lowi rejected the phone selection step"
            raise LowiApiAuthenticationError(msg)
        self._phone_action_url = None
        self._otp_action_url = _extract_form_action(html, url)

    async def async_submit_otp(self, code: str) -> LowiAccountData:
        """Submit the SMS one-time code, completing the login."""
        if self._otp_action_url is None:
            msg = "async_select_phone() must be awaited before async_submit_otp()"
            raise LowiApiError(msg)

        html, _url = await self._post_html(self._otp_action_url, {"code": code})
        if _looks_like_login_failure(html):
            msg = "Invalid verification code"
            raise LowiApiAuthenticationError(msg)
        self._otp_action_url = None

        return await self.async_get_account_data()

    async def async_get_account_data(self) -> LowiAccountData:
        """
        Fetch every mobile line's live usage plus account-wide billing info.

        On an expired portal session, transparently attempts a silent
        Keycloak SSO refresh (see _async_silent_reauth()) and retries once
        before giving up. If the Keycloak SSO session (rememberMe'd at
        login) is still alive, this recovers with no user interaction; a
        second failure means that SSO session has genuinely expired, and
        propagates as a normal LowiApiAuthenticationError so the caller
        falls back to Home Assistant's interactive reauth.
        """
        try:
            return await self._async_fetch_account_data()
        except LowiApiAuthenticationError:
            LOGGER.debug(
                "Lowi session expired; attempting a silent Keycloak SSO refresh",
            )
            await self._async_silent_reauth()
            return await self._async_fetch_account_data()

    async def _async_silent_reauth(self) -> None:
        """
        Try to mint a fresh portal session without user interaction.

        Replays the exact same `GET /milowi/login/` entry point
        async_start_login() uses, reusing whatever cookies are already in
        this client's session - Django's own `sessionid` (if not fully
        expired yet) and/or the Keycloak SSO cookies (KEYCLOAK_IDENTITY/
        KEYCLOAK_SESSION), either from the interactive login earlier this
        run or restored via import_sso_cookies().

        Confirmed by a captured "already logged in" browser reload (not a
        manual re-login): this is what a real browser does, and it is NOT a
        hand-built `prompt=none` Keycloak call (an earlier, untested version
        of this method built one, and it doesn't match what Django/Keycloak
        actually do - see docs/lowi-auth-and-api.md §5). Django's `/login/`
        view recognizes the returning browser and redirects straight into
        Keycloak with an identifying `userId` hint; Keycloak recognizes its
        own SSO cookies and redirects back with a fresh `code` and no login/
        OTP form, which Django exchanges for a new `sessionid` in this same
        session. If the SSO session has actually expired, this instead lands
        on the normal Keycloak login form, same as a fresh login would.

        Deliberately best-effort: whether this actually worked is left for
        the caller to discover by retrying the real request, rather than
        parsed here - that keeps this immune to Keycloak markup changes and
        reuses the same-tested auth-failure detection in
        _async_api_request().
        """
        await self._get_html(_LOGIN_ENTRY_URL)

    async def _async_fetch_account_data(self) -> LowiAccountData:
        """Perform the actual data calls for async_get_account_data()."""
        subscriptions_raw = await self._async_api_request(
            "GET",
            "me/subscriptions",
            base_url=API_BASE_URL,
        )
        lines = _parse_subscriptions_response(subscriptions_raw)

        consumptions_raw = await self._async_api_request(
            "GET",
            "me/consumptions",
            base_url=MILOWI_API_BASE_URL,
        )
        account, consumptions_by_id = _parse_consumptions_response(consumptions_raw)
        for subscription_id, line in lines.items():
            consumption = consumptions_by_id.get(subscription_id)
            if consumption is not None:
                _apply_consumption(line, consumption)

        billings_raw = await self._async_api_request(
            "GET",
            "me/billings",
            base_url=MILOWI_API_BASE_URL,
        )
        if billings_raw:
            latest = billings_raw[0]
            account.last_invoice_amount = _to_float(latest.get("price"))
            account.last_invoice_status = latest.get("status")
            account.last_invoice_date = latest.get("date")

        return LowiAccountData(
            account=account,
            lines={line.msisdn: line for line in lines.values()},
        )

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
        if _is_waf_challenge(html):
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
        if _is_waf_challenge(html):
            msg = "Lowi's anti-bot protection is blocking this request"
            raise LowiApiWafChallengeError(msg)
        return html, str(response.url)

    async def _async_api_request(
        self,
        method: str,
        path: str,
        *,
        base_url: str = API_BASE_URL,
        **kwargs: Any,
    ) -> Any:
        """Make a request against one of Lowi's JSON customer APIs."""
        response = await self._request(
            method,
            f"{base_url}{path}",
            headers=DEFAULT_HEADERS,
            **kwargs,
        )
        body_text = await response.text()

        if _is_waf_challenge(body_text):
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
