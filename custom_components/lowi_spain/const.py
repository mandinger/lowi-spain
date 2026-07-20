"""Constants for lowi."""

from datetime import timedelta
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "lowi_spain"
ATTRIBUTION = "Data provided by lowi.es"

# No standard homeassistant.const key exists for a persisted session-cookie
# jar; stored in config entry data alongside CONF_USERNAME/CONF_PASSWORD so a
# restart doesn't require redoing the SMS one-time-code login every time.
CONF_COOKIES = "cookies"

# The long-lived Keycloak SSO cookies (login.lowi.es), kept separate from the
# short-lived Django sessionid (CONF_COOKIES, www.lowi.es): they scope to a
# different host, and aiohttp's cookie jar needs cookies re-imported per-host
# to land in the right domain. These are what make a silent prompt=none
# session refresh possible without redoing the SMS one-time-code login - see
# LowiApiClient._async_silent_reauth() in api.py.
CONF_SSO_COOKIES = "sso_cookies"

# Deliberately conservative and not user-configurable in v1: usage counters on
# the carrier side don't update more than a few times a day, and every poll is
# a real request against a WAF-protected consumer login. Polling more often
# buys nothing and increases the chance of the account/IP being flagged.
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)
