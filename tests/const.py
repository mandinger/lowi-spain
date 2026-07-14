"""
Shared test fixtures/constants for lowi tests.

The subscriptions response shape below mirrors a real captured payload from
`GET /api/2.0/me/subscriptions` (see CONTRIBUTING.md), with fake msisdns and
subscription ids substituted for the real account's. The Keycloak login-flow
HTML fixtures are best-effort reconstructions of a real captured multi-step
login (also see CONTRIBUTING.md) - the exact page structure/field names are
still unverified against a live re-test.
"""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

MOCK_CONFIG = {
    CONF_USERNAME: "12345678A",
    CONF_PASSWORD: "test-password",
}

MSISDN_PRIMARY = "600111222"
ACCOUNT_ID_PRIMARY = "7192706"
MSISDN_SECONDARY = "600333444"
ACCOUNT_ID_SECONDARY = "7192704"
INTERNET_ACCOUNT_ID = "9220989"

# Real, confirmed shape: a flat `{"data": [...]}` list of packages, each with
# one or more `subscriptions` (INTERNET/MOBILE/TV). Only MOBILE entries have
# a non-empty msisdn and are kept by api.py's parsing.
MOCK_SUBSCRIPTIONS_RESPONSE = {
    "data": [
        {
            "package_id": 706,
            "name": "150GB/Unlimited + Fibra 600Mbps",
            "subscriptions": [
                {
                    "status": "ACTIVE",
                    "type": "INTERNET",
                    "msisdn": "",
                    "id": INTERNET_ACCOUNT_ID,
                    "addons": [],
                    "product": {
                        "product_items": [
                            {
                                "name": "Fibra 600 MB",
                                "type": "BROADBAND",
                                "quantity": 600,
                                "unit": "MB",
                            },
                        ],
                    },
                },
                {
                    "status": "ACTIVE",
                    "type": "MOBILE",
                    "msisdn": MSISDN_PRIMARY,
                    "id": ACCOUNT_ID_PRIMARY,
                    "addons": [
                        {
                            "type": "BOND_DATA",
                            "unit": "MB",
                            "current_limit": 51200.0,
                            "initial_limit": 51200.0,
                        },
                    ],
                    "product": {
                        "product_items": [
                            {
                                "name": "Movil 150 GB",
                                "type": "DATA",
                                "quantity": 150,
                                "unit": "GB",
                            },
                            {
                                "name": "Llamadas Ilimitadas",
                                "type": "VOICE",
                                "quantity": 3600000,
                                "unit": "SECONDS",
                            },
                        ],
                    },
                },
            ],
        },
        {
            "package_id": 214,
            "name": "5GB/Unlimited - Linea Adicional",
            "subscriptions": [
                {
                    "status": "ACTIVE",
                    "type": "MOBILE",
                    "msisdn": MSISDN_SECONDARY,
                    "id": ACCOUNT_ID_SECONDARY,
                    "addons": [],
                    "product": {
                        "product_items": [
                            {
                                "name": "Movil 5 GB",
                                "type": "DATA",
                                "quantity": 5,
                                "unit": "GB",
                            },
                        ],
                    },
                },
            ],
        },
    ],
}

_LOGIN_PAGE_HTML = """
<html><body>
<form id="kc-form-login" action="{action}" method="post">
<input type="text" name="username"/>
<input type="password" name="password"/>
</form>
</body></html>
"""

_PHONE_SELECT_HTML = """
<html><body>
<form action="{action}" method="post">
<input type="radio" name="selectedPhone" value="{phone_id}"/>
<button type="submit" name="next" value="Enviar codigo">Enviar</button>
</form>
</body></html>
"""

_OTP_FORM_HTML = """
<html><body>
<form action="{action}" method="post">
<input type="text" name="code"/>
</form>
</body></html>
"""

LOGIN_ERROR_HTML = (
    '<html><body><span class="kc-feedback-text">'
    "Invalid credentials</span></body></html>"
)


def login_page_html(action: str) -> str:
    """Render the (best-effort) initial Keycloak login form."""
    return _LOGIN_PAGE_HTML.format(action=action)


def phone_select_html(action: str, phone_id: str) -> str:
    """Render the (best-effort) phone-selection form for the SMS code."""
    return _PHONE_SELECT_HTML.format(action=action, phone_id=phone_id)


def otp_form_html(action: str) -> str:
    """Render the (best-effort) SMS one-time-code entry form."""
    return _OTP_FORM_HTML.format(action=action)


WAF_CHALLENGE_BODY = (
    "<html><body>Request unsuccessful. Incapsula incident ID: "
    "123456789-987654321</body></html>"
)
