"""Constants for lowi."""

from datetime import timedelta
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "lowi"
ATTRIBUTION = "Data provided by lowi.es"

# No standard homeassistant.const key exists for a persisted session-cookie
# jar; stored in config entry data alongside CONF_USERNAME/CONF_PASSWORD so a
# restart doesn't require redoing the SMS one-time-code login every time.
CONF_COOKIES = "cookies"

# Deliberately conservative and not user-configurable in v1: usage counters on
# the carrier side don't update more than a few times a day, and every poll is
# a real request against a WAF-protected consumer login. Polling more often
# buys nothing and increases the chance of the account/IP being flagged.
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)
