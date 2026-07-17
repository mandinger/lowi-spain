"""
Shared test fixtures/constants for lowi tests.

The subscriptions/consumptions/billings response shapes below mirror real
captured payloads (see docs/lowi-auth-and-api.md), with fake msisdns and
subscription ids substituted for the real account's. The Keycloak
login-flow HTML fixtures are best-effort reconstructions of a real captured
multi-step login - the exact page structure/field names are confirmed for
the submitted values (see docs/lowi-auth-and-api.md §4, §7) but the phone
option *label* markup is still a guess (also see CONTRIBUTING.md).
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
# a non-empty msisdn and are kept by api.py's parsing. This endpoint gives
# the *contracted* line list; live usage comes from MOCK_CONSUMPTIONS_RESPONSE
# below and is merged in by subscription_id.
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
                        "contract_name": "Tarifa 150GB + Llamadas Ilimitadas",
                        "charging_amount": 19.95,
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
                        "contract_name": "Tarifa 5GB",
                        "charging_amount": 5.0,
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

# Real, confirmed shape (docs/lowi-auth-and-api.md §6.1): account-wide
# `summary` plus a `subscriptions` list keyed by `subscription_id`. Note the
# primary line's `extra` here (250GB) intentionally differs from its
# BOND_DATA addon above (50GB) so tests can prove consumptions data wins.
MOCK_CONSUMPTIONS_RESPONSE = {
    "object": "user_consumption",
    "summary": {
        "total_price": {"amount": "27.79", "currency": "€"},
        "billing_period_start": 1782856800,
        "billing_period_end": 1785535199,
        "is_prorated": False,
        "next_month_price": None,
    },
    "subscriptions": [
        {
            "subscription_id": ACCOUNT_ID_PRIMARY,
            "status_detail": None,
            "provider_status": None,
            "consumptions": {
                "data_consumption": {
                    "is_unlimited": False,
                    "resume": {
                        "quantity": {"value": "400.0", "unit": "GB"},
                        "available": {"value": "398.9", "unit": "GB"},
                    },
                    "included": {
                        "quantity": {"value": "150.0", "unit": "GB"},
                        "available": {"value": "150.0", "unit": "GB"},
                    },
                    "extra": {
                        "quantity": {"value": "250.0", "unit": "GB"},
                        "available": {"value": "248.9", "unit": "GB"},
                        "sections": [
                            {
                                "name": "Acumulados del mes anterior",
                                "quantity": {"value": "198.9", "unit": "GB"},
                            },
                        ],
                    },
                },
                "voice_consumption": {"is_unlimited": True},
                "extra_consumption": None,
            },
            "extra_info": None,
            "roaming": {"zones": ["1"], "bonds": None},
        },
        {
            "subscription_id": ACCOUNT_ID_SECONDARY,
            "status_detail": None,
            "provider_status": None,
            "consumptions": {
                "data_consumption": {
                    "is_unlimited": False,
                    "resume": {
                        "quantity": {"value": "5.0", "unit": "GB"},
                        "available": {"value": "2.5", "unit": "GB"},
                    },
                    "included": {
                        "quantity": {"value": "5.0", "unit": "GB"},
                        "available": {"value": "2.5", "unit": "GB"},
                    },
                    "extra": None,
                },
                "voice_consumption": {"is_unlimited": True},
                "extra_consumption": None,
            },
            "extra_info": None,
            "roaming": None,
        },
        {
            "subscription_id": INTERNET_ACCOUNT_ID,
            "status_detail": None,
            "provider_status": None,
            "consumptions": {"extra_consumption": None},
            "extra_info": None,
            "roaming": None,
        },
    ],
}

# Real, confirmed shape (docs/lowi-auth-and-api.md §6.1): newest first.
MOCK_BILLINGS_RESPONSE = [
    {
        "id": 264172547,
        "date": 1780264800,
        "price": 28.36,
        "type": "INVOICE",
        "status": "PAID",
        "billing_date": None,
    },
    {
        "id": 264172000,
        "date": 1777672800,
        "price": 27.10,
        "type": "INVOICE",
        "status": "PAID",
        "billing_date": None,
    },
]

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
{options}
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
    """Render a single-option phone-selection form (radio input)."""
    option = f'<input type="radio" name="selectedPhone" value="{phone_id}"/>'
    return _PHONE_SELECT_HTML.format(action=action, options=option)


def multi_phone_select_html(action: str, options: list[tuple[str, str]]) -> str:
    """Render a multi-option phone-selection form with labelled radio inputs."""
    rendered = "".join(
        f'<input type="radio" name="selectedPhone" id="phone-{value}" value="{value}"/>'
        f'<label for="phone-{value}">{label}</label>'
        for value, label in options
    )
    return _PHONE_SELECT_HTML.format(action=action, options=rendered)


def otp_form_html(action: str) -> str:
    """Render the (best-effort) SMS one-time-code entry form."""
    return _OTP_FORM_HTML.format(action=action)


WAF_CHALLENGE_BODY = (
    "<html><body>Request unsuccessful. Incapsula incident ID: "
    "123456789-987654321</body></html>"
)
