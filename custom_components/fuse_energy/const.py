"""Constants and identifier helpers for the Fuse Energy integration.

Fuse is a UK supplier with no public API. Everything here targets the
private mobile API at api.fuseenergy.com, learned by observation, so treat
any constant in this file as "correct until Fuse changes it".
"""

from __future__ import annotations

import re
from datetime import timedelta

DOMAIN: str = "fuse_energy"

# Fuse publishes consumption with a lag of up to an hour, so polling faster
# than this buys nothing but rate-limit risk.
DEFAULT_SCAN_INTERVAL: timedelta = timedelta(minutes=15)

# Fuse indexes its chart bars by UK local calendar hour, not UTC.
FUSE_TIMEZONE: str = "Europe/London"

# --- Config entry keys ---
CONF_PHONE_NUMBER: str = "phone_number"
CONF_DEVICE_ID: str = "device_id"
CONF_ACCESS_TOKEN: str = "access_token"
CONF_REFRESH_TOKEN: str = "refresh_token"
CONF_PREMISES_ID: str = "premises_id"

# --- Endpoints ---
API_BASE_URL: str = "https://api.fuseenergy.com"
WEB_BASE_URL: str = "https://www.fuseenergy.com"

# Sent as x-fuse-app-version on the web SMS-dispatch call. The endpoint
# rejects requests that look too old; bump this if OTP delivery starts
# failing with a version complaint.
WEB_APP_VERSION: str = "5.314"

# How far back to reach on the very first poll of a new config entry.
INITIAL_BACKFILL_DAYS: int = 30

# Fuse keeps revising an hour's value for a while after the hour closes, as
# the meter's readings trickle in. Every poll therefore rewrites this many
# hours of history rather than trusting what we wrote last time.
REWRITE_HOURS: int = 24


def slugify_id(value: str) -> str:
    """Reduce an arbitrary Fuse identifier to the [a-z0-9_]+ charset that
    Home Assistant requires in a statistic_id object_id. Fuse's premises
    ids are UUIDs, whose hyphens are not allowed."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def statistic_id_energy(premises_id: str, supply_type: str) -> str:
    """External-statistics id for a supply's metered volume (kWh)."""
    return f"{DOMAIN}:{slugify_id(supply_type)}_energy_{slugify_id(premises_id)}"


def statistic_id_cost(premises_id: str, supply_type: str) -> str:
    """External-statistics id for a supply's cost (GBP)."""
    return f"{DOMAIN}:{slugify_id(supply_type)}_cost_{slugify_id(premises_id)}"
