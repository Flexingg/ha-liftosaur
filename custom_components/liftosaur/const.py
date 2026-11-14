"""Constants for the Liftosaur integration."""

from __future__ import annotations

import logging
from datetime import timedelta

DOMAIN = "liftosaur"
LOGGER = logging.getLogger(__package__)

API_BASE = "https://www.liftosaur.com/api/v1"

CONF_DASHBOARDS = "dashboards"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_BACKFILL_WEEKS = "backfill_weeks"

DEFAULT_SCAN_MINUTES = 30
MIN_SCAN_MINUTES = 5
DEFAULT_BACKFILL_WEEKS = 52
MAX_BACKFILL_WEEKS = 520  # Liftograph caps compare: at 10y

DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_MINUTES)

SERVICE_BACKFILL = "backfill"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
