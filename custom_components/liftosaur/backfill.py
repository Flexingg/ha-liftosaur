"""Backfill long-term statistics from Liftosaur's own evaluation of each series.

For every sensor with a history line, Liftosaur is asked for
``value / <series> / compare: <N>`` at daily and then weekly offsets. Today's
value minus the reported change is the exact value the series had N ago, as
Liftosaur computes it. Those values are imported into the sensor's own
long-term statistics, so a statistics or ApexCharts card shows the past year
from the day the integration is installed.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import liftograph
from .api import LiftosaurDashboardError
from .const import CONF_BACKFILL_WEEKS, DEFAULT_BACKFILL_WEEKS, DOMAIN, LOGGER
from .coordinator import LiftosaurConfigEntry, SensorSpec

try:  # HA 2025.11+
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN = {"mean_type": StatisticMeanType.ARITHMETIC}
except ImportError:  # pragma: no cover - older cores
    _MEAN = {"has_mean": True}

STORE_VERSION = 1


def _signature(spec: SensorSpec, weeks: int) -> str:
    raw = f"{spec.history_line}|{spec.unit}|{weeks}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _parse_series(line: str) -> liftograph.Series:
    widget = liftograph.parse(line)[0]
    series = widget.own_series
    assert series is not None
    return series


async def async_backfill(
    hass: HomeAssistant, entry: LiftosaurConfigEntry, force: bool = False
) -> int:
    """Backfill every sensor that has not been backfilled for its current
    definition. Returns how many sensors were written."""
    async with entry.runtime_data.backfill_lock:
        return await _backfill(hass, entry, force)


async def _backfill(hass: HomeAssistant, entry: LiftosaurConfigEntry, force: bool) -> int:
    coordinator = entry.runtime_data
    weeks = int(entry.options.get(CONF_BACKFILL_WEEKS, DEFAULT_BACKFILL_WEEKS))
    if weeks <= 0 or not coordinator.data:
        return 0

    store: Store[dict[str, str]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.backfill")
    done: dict[str, str] = await store.async_load() or {}
    registry = er.async_get(hass)

    todo: list[tuple[str, SensorSpec, str]] = []
    for dash in coordinator.data.values():
        for spec in dash.sensors.values():
            if not spec.history_line:
                continue
            unique_id = f"{entry.entry_id}_{spec.unique_id_suffix}"
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                continue
            sig = _signature(spec, weeks)
            if not force and done.get(unique_id) == sig:
                continue
            todo.append((entity_id, spec, sig))
    if not todo:
        return 0

    offsets = liftograph.backfill_offsets(weeks)
    lines: list[str] = []
    index: list[tuple[int, int]] = []  # (todo index, days ago) per line
    for ti, (_, spec, _) in enumerate(todo):
        series = _parse_series(spec.history_line or "")
        for duration, days in offsets:
            lines.append(liftograph.value_line(series, duration))
            index.append((ti, days))

    answers: list[dict[str, Any]] = []
    for chunk in liftograph.chunk_lines(lines):
        try:
            res = await coordinator.api.preview("\n".join(chunk))
            got = res.get("widgets", [])
        except LiftosaurDashboardError as err:
            LOGGER.warning("Backfill request rejected: %s", err)
            got = []
        got = list(got) + [{}] * (len(chunk) - len(got))
        answers.extend(got[: len(chunk)])

    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    points: dict[int, dict[Any, float]] = {}
    for (ti, days), ans in zip(index, answers, strict=False):
        value, delta = ans.get("value"), ans.get("delta")
        if not isinstance(value, (int, float)) or not isinstance(delta, (int, float)):
            continue
        start = now - timedelta(days=days)
        points.setdefault(ti, {})[start] = round(float(value) - float(delta), 2)

    written = 0
    for ti, (entity_id, spec, sig) in enumerate(todo):
        series_points = points.get(ti)
        unique_id = f"{entry.entry_id}_{spec.unique_id_suffix}"
        done[unique_id] = sig
        if not series_points:
            continue
        stats: list[StatisticData] = [
            StatisticData(start=start, mean=v, min=v, max=v, state=v)
            for start, v in sorted(series_points.items())
        ]
        metadata: StatisticMetaData = {
            **_MEAN,
            "has_sum": False,
            "name": None,
            "source": "recorder",
            "statistic_id": entity_id,
            "unit_class": None,
            "unit_of_measurement": spec.unit,
        }  # type: ignore[typeddict-item]
        async_import_statistics(hass, metadata, stats)
        written += 1

    await store.async_save(done)
    # Let the recorder finish so callers (and tests) see the data.
    await get_instance(hass).async_block_till_done()
    LOGGER.info("Backfilled %s Liftosaur sensors (%s weeks)", written, weeks)
    return written


async def async_clear_store(hass: HomeAssistant, entry_id: str) -> None:
    await Store(hass, STORE_VERSION, f"{DOMAIN}.{entry_id}.backfill").async_remove()
