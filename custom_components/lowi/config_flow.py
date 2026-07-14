"""Adds config flow for Lowi."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    LowiApiAuthenticationError,
    LowiApiClient,
    LowiApiCommunicationError,
    LowiApiError,
    LowiApiWafChallengeError,
)
from .const import DOMAIN, LOGGER

_PASSWORD_SCHEMA = {
    vol.Required(CONF_PASSWORD): selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
    ),
}


class LowiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Lowi."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._test_credentials(
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                )
            except LowiApiAuthenticationError as exception:
                LOGGER.warning(exception)
                errors["base"] = "invalid_auth"
            except LowiApiWafChallengeError as exception:
                LOGGER.warning(exception)
                errors["base"] = "waf_challenge"
            except LowiApiCommunicationError as exception:
                LOGGER.error(exception)
                errors["base"] = "cannot_connect"
            except LowiApiError as exception:
                LOGGER.exception(exception)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL,
                        ),
                    ),
                    **_PASSWORD_SCHEMA,
                },
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],  # noqa: ARG002 Unused function argument
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth when Lowi rejects previously-valid credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm reauth with a fresh password."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await self._test_credentials(
                    email=reauth_entry.data[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                )
            except LowiApiAuthenticationError as exception:
                LOGGER.warning(exception)
                errors["base"] = "invalid_auth"
            except LowiApiWafChallengeError as exception:
                LOGGER.warning(exception)
                errors["base"] = "waf_challenge"
            except LowiApiCommunicationError as exception:
                LOGGER.error(exception)
                errors["base"] = "cannot_connect"
            except LowiApiError as exception:
                LOGGER.exception(exception)
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(_PASSWORD_SCHEMA),
            errors=errors,
            description_placeholders={"email": reauth_entry.data[CONF_EMAIL]},
        )

    async def _test_credentials(self, email: str, password: str) -> None:
        """Validate credentials against the Lowi API."""
        client = LowiApiClient(
            email=email,
            password=password,
            session=async_create_clientsession(self.hass),
        )
        await client.async_login()
