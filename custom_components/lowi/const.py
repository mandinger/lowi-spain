"""Constants for lowi."""

from datetime import timedelta
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "lowi"
ATTRIBUTION = "Data provided by lowi.es"

# Deliberately conservative and not user-configurable in v1: usage counters on
# the carrier side don't update more than a few times a day, and every poll is
# a real request against a WAF-protected consumer login. Polling more often
# buys nothing and increases the chance of the account/IP being flagged.
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)
