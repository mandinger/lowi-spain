"""Adds config flow for Lowi (NIF/password + SMS one-time code)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    LowiApiAuthenticationError,
    LowiApiClient,
    LowiApiCommunicationError,
    LowiApiError,
    LowiApiWafChallengeError,
)
from .const import CONF_COOKIES, DOMAIN, LOGGER

_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT),
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
        ),
    },
)
_OTP_SCHEMA = vol.Schema(
    {
        vol.Required("code"): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT),
        ),
    },
)
_PASSWORD_ONLY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
        ),
    },
)


class LowiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Lowi: NIF/password, then an SMS one-time code."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._client: LowiApiClient | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._is_reauth = False

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect the account's username (NIF/DNI) and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            errors = await self._async_start_login()
            if not errors:
                return await self.async_step_otp()

        return self.async_show_form(
            step_id="user",
            data_schema=_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_otp(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect the SMS one-time code and finish the login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_submit_otp(user_input["code"])
            if not errors:
                return await self._async_finish()

        return self.async_show_form(
            step_id="otp",
            data_schema=_OTP_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth: Lowi rejected the stored session/credentials."""
        self._is_reauth = True
        self._username = entry_data[CONF_USERNAME]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauth with a (possibly updated) password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            errors = await self._async_start_login()
            if not errors:
                return await self.async_step_otp()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_PASSWORD_ONLY_SCHEMA,
            errors=errors,
            description_placeholders={"username": self._username or ""},
        )

    async def _async_start_login(self) -> dict[str, str]:
        """Instantiate the API client and start the Keycloak login dance."""
        self._client = LowiApiClient(
            username=self._username,
            password=self._password,
            session=async_create_clientsession(self.hass),
        )
        try:
            await self._client.async_start_login()
        except LowiApiAuthenticationError as exception:
            LOGGER.warning(exception)
            return {"base": "invalid_auth"}
        except LowiApiWafChallengeError as exception:
            LOGGER.warning(exception)
            return {"base": "waf_challenge"}
        except LowiApiCommunicationError as exception:
            LOGGER.error(exception)
            return {"base": "cannot_connect"}
        except LowiApiError as exception:
            LOGGER.exception(exception)
            return {"base": "unknown"}
        return {}

    async def _async_submit_otp(self, code: str) -> dict[str, str]:
        """Submit the SMS code on the client started by _async_start_login."""
        try:
            await self._client.async_submit_otp(code)
        except LowiApiAuthenticationError as exception:
            LOGGER.warning(exception)
            return {"base": "invalid_otp"}
        except LowiApiWafChallengeError as exception:
            LOGGER.warning(exception)
            return {"base": "waf_challenge"}
        except LowiApiCommunicationError as exception:
            LOGGER.error(exception)
            return {"base": "cannot_connect"}
        except LowiApiError as exception:
            LOGGER.exception(exception)
            return {"base": "unknown"}
        return {}

    async def _async_finish(self) -> config_entries.ConfigFlowResult:
        """Create or update the config entry with credentials and cookies."""
        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_COOKIES: self._client.export_cookies(),
        }

        if self._is_reauth:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data=data,
            )

        await self.async_set_unique_id(self._username)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._username, data=data)
