"""Adds config flow for Lowi (NIF/password + phone selection + SMS one-time code)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from .api import PhoneOption

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
    """Config flow for Lowi: NIF/password, phone selection, then an SMS code."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._client: LowiApiClient | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._phone_options: list[PhoneOption] = []
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
                return await self._async_step_after_login()

        return self.async_show_form(
            step_id="user",
            data_schema=_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    async def async_step_phone(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect which phone number should receive the SMS code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_select_phone(user_input["phone"])
            if not errors:
                return await self.async_step_otp()

        schema = vol.Schema(
            {
                vol.Required("phone"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=option.value,
                                label=option.label,
                            )
                            for option in self._phone_options
                        ],
                    ),
                ),
            },
        )
        return self.async_show_form(
            step_id="phone",
            data_schema=schema,
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
                return await self._async_step_after_login()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_PASSWORD_ONLY_SCHEMA,
            errors=errors,
            description_placeholders={"username": self._username or ""},
        )

    async def _async_step_after_login(self) -> config_entries.ConfigFlowResult:
        """Route to the phone-selection step, or straight to OTP if only one number."""
        if self._phone_options:
            return await self.async_step_phone()
        return await self.async_step_otp()

    async def _async_start_login(self) -> dict[str, str]:
        """
        Instantiate the API client and start the Keycloak login dance.

        A single offered phone number is auto-selected (the common
        single-line case); with more than one, _async_step_after_login()
        shows the phone step instead.
        """
        self._client = LowiApiClient(
            username=self._username,
            password=self._password,
            session=async_create_clientsession(self.hass),
        )
        self._phone_options = []
        phone_options, errors = await self._async_run(
            self._client.async_start_login(),
            auth_error_key="invalid_auth",
        )
        if errors:
            return errors

        if len(phone_options) == 1:
            return await self._async_select_phone(phone_options[0].value)

        self._phone_options = phone_options
        return {}

    async def _async_select_phone(self, phone_id: str) -> dict[str, str]:
        """Submit the chosen phone number on the client from _async_start_login."""
        _, errors = await self._async_run(
            self._client.async_select_phone(phone_id),
            auth_error_key="invalid_auth",
        )
        return errors

    async def _async_submit_otp(self, code: str) -> dict[str, str]:
        """Submit the SMS code on the client started by _async_start_login."""
        _, errors = await self._async_run(
            self._client.async_submit_otp(code),
            auth_error_key="invalid_otp",
        )
        return errors

    async def _async_run(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        auth_error_key: str,
    ) -> tuple[Any, dict[str, str]]:
        """Await a client call, mapping Lowi exceptions to a config-flow error dict."""
        try:
            result = await coro
        except LowiApiAuthenticationError as exception:
            LOGGER.warning(exception)
            return None, {"base": auth_error_key}
        except LowiApiWafChallengeError as exception:
            LOGGER.warning(exception)
            return None, {"base": "waf_challenge"}
        except LowiApiCommunicationError as exception:
            LOGGER.error(exception)
            return None, {"base": "cannot_connect"}
        except LowiApiError as exception:
            LOGGER.exception(exception)
            return None, {"base": "unknown"}
        return result, {}

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
