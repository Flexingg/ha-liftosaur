"""The workout window: when it is open and how long to wait between polls."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from custom_components.liftosaur.schedule import WorkoutWindow, next_interval

NY = ZoneInfo("America/New_York")
THIRTY = timedelta(minutes=30)


def _at(h: int, m: int, day: int = 14, month: int = 11) -> datetime:
    return datetime(2026, month, day, h, m, tzinfo=NY)


def _window(start: str = "04:00:00", end: str = "05:00:00", every: int = 1) -> WorkoutWindow:
    window = WorkoutWindow.from_options(
        {"workout_window": True, "workout_start": start, "workout_end": end, "workout_interval": every}
    )
    assert window is not None
    return window


def test_from_options() -> None:
    assert WorkoutWindow.from_options({}) is None
    assert WorkoutWindow.from_options({"workout_window": False, "workout_start": "04:00:00"}) is None
    # Start == end is empty, not all day.
    assert WorkoutWindow.from_options({"workout_window": True, "workout_start": "04:00", "workout_end": "04:00"}) is None
    # Defaults: 4–5 am, every minute.
    window = WorkoutWindow.from_options({"workout_window": True})
    assert window == WorkoutWindow(time(4), time(5), timedelta(minutes=1))


def test_contains() -> None:
    window = _window()
    assert not window.contains(_at(3, 59))
    assert window.contains(_at(4, 0))
    assert window.contains(_at(4, 59))
    assert not window.contains(_at(5, 0))


def test_contains_across_midnight() -> None:
    window = _window("23:00:00", "01:00:00")
    assert window.contains(_at(23, 30))
    assert window.contains(_at(0, 30))
    assert not window.contains(_at(1, 0))
    assert not window.contains(_at(22, 59))


def test_next_interval() -> None:
    window = _window(every=2)
    # No window: the regular interval.
    assert next_interval(_at(4, 10), THIRTY, None) == THIRTY
    # In the window: the quick interval.
    assert next_interval(_at(4, 10), THIRTY, window) == timedelta(minutes=2)
    # Shortly before it opens: wake up right when it opens.
    assert next_interval(_at(3, 50), THIRTY, window) == timedelta(minutes=10)
    # Long before (or after) it: the regular interval.
    assert next_interval(_at(12, 0), THIRTY, window) == THIRTY
    assert next_interval(_at(5, 0), THIRTY, window) == THIRTY
    # Never a burst of polls right before it opens.
    assert next_interval(_at(3, 59) + timedelta(seconds=59, microseconds=999000), THIRTY, window) == timedelta(seconds=5)


def test_until_start_across_dst() -> None:
    # Clocks go back at 2 am on 2026-11-01: 1 am to 4 am that night is 4 real hours.
    window = _window()
    assert window.until_start(_at(1, 0, day=1)) == timedelta(hours=4)
    # From the evening before, the next 4 am is the following day.
    assert window.until_start(_at(23, 0, day=31, month=10)) == timedelta(hours=6)
