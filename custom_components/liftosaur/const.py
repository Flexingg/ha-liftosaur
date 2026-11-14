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
CONF_WORKOUT_WINDOW = "workout_window"
CONF_WORKOUT_START = "workout_start"
CONF_WORKOUT_END = "workout_end"
CONF_WORKOUT_INTERVAL = "workout_interval"

DEFAULT_SCAN_MINUTES = 30
MIN_SCAN_MINUTES = 5
DEFAULT_WORKOUT_START = "04:00:00"
DEFAULT_WORKOUT_END = "05:00:00"
DEFAULT_WORKOUT_INTERVAL = 1
MAX_WORKOUT_INTERVAL = 60
# In the workout window, only workouts logged in the last few days are checked
# for changes; the full dashboards are re-evaluated only when they change.
CHANGE_CHECK_DAYS = 3
DEFAULT_BACKFILL_WEEKS = 52
MAX_BACKFILL_WEEKS = 520  # Liftograph caps compare: at 10y

DEFAULT_SCAN_INTERVAL = timedelta(minutes=DEFAULT_SCAN_MINUTES)

SERVICE_BACKFILL = "backfill"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
