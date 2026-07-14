"""
Shared test fixtures/constants for lowi tests.

These mock payloads are shaped after the old, dead lowi-api npm package (see
CONTRIBUTING.md) since that's the only reference we have for what Lowi's API
used to look like. They are placeholders: once a real browser capture of the
live lowi.es API is available, replace these with real (redacted) payloads.
"""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

MOCK_CONFIG = {
    CONF_EMAIL: "test@example.com",
    CONF_PASSWORD: "test-password",
}

MSISDN_SINGLE = "600111222"
ACCOUNT_ID_SINGLE = "1111"

MSISDN_SECOND = "600333444"
ACCOUNT_ID_SECOND = "2222"

MOCK_LOGIN_RESPONSE = {
    "result": {"resultCode": 0},
    "data": {
        "auth_token": "mock-token",
        "user": {
            "name": "Test",
            "first_last_name": "User",
            "accounts": [
                {
                    "id": ACCOUNT_ID_SINGLE,
                    "subscriptions": [{"msisdn": MSISDN_SINGLE}],
                },
            ],
        },
    },
}

MOCK_LOGIN_RESPONSE_MULTI = {
    "result": {"resultCode": 0},
    "data": {
        "auth_token": "mock-token",
        "user": {
            "name": "Test",
            "first_last_name": "User",
            "accounts": [
                {
                    "id": ACCOUNT_ID_SINGLE,
                    "subscriptions": [{"msisdn": MSISDN_SINGLE}],
                },
                {
                    "id": ACCOUNT_ID_SECOND,
                    "subscriptions": [{"msisdn": MSISDN_SECOND}],
                },
            ],
        },
    },
}

MOCK_LOGIN_FAILURE_RESPONSE = {
    "result": {"resultCode": 1, "resultDescription": "Invalid credentials"},
}

# acumulative_data below is in bytes (209715200 == 200 MiB), unlike its
# MB-valued siblings - this mirrors the historical unit mixup api.py guards
# against (see api.py's _bytes_to_mb).
MOCK_SUMMARY_RESPONSE = {
    "result": {"resultCode": 0},
    "data": {
        "cost_current_month": 12.34,
        "current_tariff_data_included": 5000,
        "bonds_data": 1000,
        "acumulative_data": 209715200,
        "shared_data_received": 0,
        "graph_remaining_data": 4200,
        "graph_total_data": 6000,
    },
}

MOCK_SUMMARY_FAILURE_RESPONSE = {
    "result": {"resultCode": 1, "resultDescription": "Unknown subscription"},
}

WAF_CHALLENGE_BODY = (
    "<html><body>Request unsuccessful. Incapsula incident ID: "
    "123456789-987654321</body></html>"
)
