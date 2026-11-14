"""When to poll: the regular interval, plus an optional daily workout window
during which Liftosaur is checked far more often."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from .const import (
    CONF_WORKOUT_END,
    CONF_WORKOUT_INTERVAL,
    CONF_WORKOUT_START,
    CONF_WORKOUT_WINDOW,
    DEFAULT_WORKOUT_END,
    DEFAULT_WORKOUT_INTERVAL,
    DEFAULT_WORKOUT_START,
)

# Never schedule the next poll sooner than this, so a window that starts in a
# few milliseconds cannot cause a burst of back-to-back polls.
MIN_WAIT = timedelta(seconds=5)


def _parse_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


@dataclass(frozen=True)
class WorkoutWindow:
    """A daily time range (local time) that may span midnight."""

    start: time
    end: time
    interval: timedelta

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> WorkoutWindow | None:
        """The configured window, or None when it is off or empty."""
        if not options.get(CONF_WORKOUT_WINDOW):
            return None
        start = _parse_time(options.get(CONF_WORKOUT_START, DEFAULT_WORKOUT_START))
        end = _parse_time(options.get(CONF_WORKOUT_END, DEFAULT_WORKOUT_END))
        if start == end:
            return None
        minutes = options.get(CONF_WORKOUT_INTERVAL, DEFAULT_WORKOUT_INTERVAL)
        return cls(start, end, timedelta(minutes=max(1, int(minutes))))

    def contains(self, now: datetime) -> bool:
        t = now.time().replace(tzinfo=None)
        if self.start < self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end

    def until_start(self, now: datetime) -> timedelta:
        """Real time from `now` to the next start of the window."""
        candidate = datetime.combine(now.date(), self.start, tzinfo=now.tzinfo)
        if candidate <= now:
            candidate = datetime.combine(now.date() + timedelta(days=1), self.start, tzinfo=now.tzinfo)
        # Subtract in UTC so a DST change in between is counted correctly.
        return candidate.astimezone(UTC) - now.astimezone(UTC)


def next_interval(now: datetime, normal: timedelta, window: WorkoutWindow | None) -> timedelta:
    """How long to wait before the next poll.

    Inside the window: the window's interval. Outside: the regular interval,
    cut short so the first poll of the window lands right when it opens.
    """
    if window is None:
        return normal
    if window.contains(now):
        return window.interval
    return max(min(normal, window.until_start(now)), MIN_WAIT)
