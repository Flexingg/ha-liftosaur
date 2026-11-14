"""Fetch Liftosaur dashboards and turn their widgets into sensor specs."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from . import liftograph
from .api import (
    LiftosaurApi,
    LiftosaurAuthError,
    LiftosaurDashboardError,
    LiftosaurError,
)
from .const import (
    CONF_DASHBOARDS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    LOGGER,
)


@dataclass
class SensorSpec:
    """Everything a sensor needs, rebuilt on every refresh."""

    key: str
    dashboard_id: str
    dashboard_name: str
    name: str
    kind: str  # value | series | calendar_total | calendar_streak | muscles
    value: float | None
    unit: str | None = None
    icon: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    # The series (as Liftograph) that reproduces this value, for backfill.
    history_line: str | None = None

    @property
    def unique_id_suffix(self) -> str:
        return f"{self.dashboard_id}_{self.key}"


@dataclass
class DashboardData:
    id: str
    name: str
    text: str
    errors: list[dict[str, Any]]
    sensors: dict[str, SensorSpec]


type LiftosaurConfigEntry = ConfigEntry["LiftosaurCoordinator"]

_MD = re.compile(r"[*_`#>]+")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def clean_caption(caption: str | None, limit: int = 40) -> str | None:
    """First line of a Markdown caption, as a short plain label."""
    if not caption:
        return None
    line = caption.strip().split("\n")[0]
    line = _MD.sub("", _LINK.sub(r"\1", line)).strip()
    for sep in (" — ", " – ", " - ", " ("):
        if sep in line:
            line = line.split(sep, 1)[0].strip()
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line or None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


class LiftosaurCoordinator(DataUpdateCoordinator[dict[str, DashboardData]]):
    """Polls every selected dashboard."""

    config_entry: LiftosaurConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LiftosaurConfigEntry, api: LiftosaurApi) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_MINUTES)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.api = api
        self.backfill_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, DashboardData]:
        try:
            listed = await self.api.list_dashboards()
            selected = self.config_entry.options.get(CONF_DASHBOARDS) or []
            if selected:
                listed = [d for d in listed if d.get("id") in selected]
            results = await asyncio.gather(*(self._load(d) for d in listed))
        except LiftosaurAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LiftosaurError as err:
            raise UpdateFailed(str(err)) from err
        return {d.id: d for d in results}

    async def _load(self, summary: dict[str, Any]) -> DashboardData:
        dash = await self.api.get_dashboard(summary["id"])
        text = dash.get("text", "")
        name = dash.get("name") or summary.get("name") or summary["id"]
        try:
            preview = await self.api.preview(text)
        except LiftosaurDashboardError as err:
            LOGGER.warning("Dashboard %s does not compile: %s", name, err)
            return DashboardData(summary["id"], name, text, err.details, {})

        widgets = liftograph.parse(text)
        results = preview.get("widgets", [])
        if len(widgets) != len(results):
            LOGGER.debug(
                "Dashboard %s: parsed %s widgets, server reported %s",
                name,
                len(widgets),
                len(results),
            )

        # Every series (value widgets and time graphs) is re-asked as a value
        # widget with `compare: 1w`, in both its trailing-window form and its
        # raw form. The answers give the sensor state, its weekly change, and
        # which form to use for history.
        probes: list[tuple[int, int | None, liftograph.Series]] = []
        for wi, (widget, result) in enumerate(zip(widgets, results, strict=False)):
            if widget.kind == "value" and result.get("kind") == "value":
                probes.append((wi, None, widget.own_series))
            elif widget.kind == "graph" and result.get("xMode", "time") == "time":
                for si, series in enumerate(widget.series):
                    probes.append((wi, si, series))

        lines: list[str] = []
        for _, _, series in probes:
            lines.append(liftograph.value_line(liftograph.trailing_series(series), "1w"))
            lines.append(liftograph.value_line(liftograph.raw_series(series), "1w"))
        answers: list[dict[str, Any]] = []
        for chunk in liftograph.chunk_lines(lines):
            try:
                res = await self.api.preview("\n".join(chunk))
                answers.extend(res.get("widgets", []))
            except LiftosaurDashboardError as err:
                LOGGER.debug("Probe for %s failed: %s", name, err)
                answers.extend({} for _ in chunk)

        sensors: dict[str, SensorSpec] = {}

        def add(spec: SensorSpec) -> None:
            base = spec.key
            n = 2
            while spec.key in sensors:
                spec.key = f"{base}_{n}"
                n += 1
            sensors[spec.key] = spec

        probe_by_pos: dict[tuple[int, int | None], tuple[liftograph.Series, dict, dict]] = {}
        for i, (wi, si, series) in enumerate(probes):
            trailing = answers[2 * i] if 2 * i < len(answers) else {}
            raw = answers[2 * i + 1] if 2 * i + 1 < len(answers) else {}
            probe_by_pos[(wi, si)] = (series, trailing, raw)

        def pick(series: liftograph.Series, trailing: dict, raw: dict) -> tuple[dict, str]:
            if not trailing.get("isEmpty", True) and _num(trailing.get("value")) is not None:
                return trailing, liftograph.value_line(liftograph.trailing_series(series))
            return raw, liftograph.value_line(liftograph.raw_series(series))

        for wi, (widget, result) in enumerate(zip(widgets, results, strict=False)):
            kind = result.get("kind")
            caption = clean_caption(result.get("caption"))
            if kind == "value" and widget.kind == "value":
                series = widget.own_series
                label = series.name or result.get("name") or "Value"
                _, history = pick(*probe_by_pos[(wi, None)])
                attrs = {"dashboard": name}
                if "delta" in result:
                    attrs["change"] = _num(result.get("delta"))
                    attrs["compared_to"] = series.get("compare")
                add(
                    SensorSpec(
                        key=slugify(label) or f"value_{wi}",
                        dashboard_id=summary["id"],
                        dashboard_name=name,
                        name=label,
                        kind="value",
                        value=_num(result.get("value")),
                        unit=result.get("unit"),
                        attributes=attrs,
                        history_line=history,
                    )
                )
            elif kind == "graph" and widget.kind == "graph":
                if result.get("xMode", "time") != "time":
                    continue
                for si, (series, sres) in enumerate(zip(widget.series, result.get("series", []), strict=False)):
                    probe, history = pick(*probe_by_pos[(wi, si)])
                    label = series.name or sres.get("name") or f"Series {si + 1}"
                    full = f"{caption} · {label}" if caption else label
                    attrs = {
                        "dashboard": name,
                        "graph": caption,
                        "point_count": sres.get("pointCount"),
                    }
                    if (first := sres.get("first")) is not None:
                        attrs["first_date"] = first.get("x")
                        attrs["first_value"] = _num(first.get("y"))
                    if (last := sres.get("last")) is not None:
                        attrs["last_point_date"] = last.get("x")
                        attrs["last_point_value"] = _num(last.get("y"))
                    if "delta" in probe:
                        attrs["change_1w"] = _num(probe.get("delta"))
                    add(
                        SensorSpec(
                            key=slugify(full) or f"graph_{wi}_{si}",
                            dashboard_id=summary["id"],
                            dashboard_name=name,
                            name=full,
                            kind="series",
                            value=_num(probe.get("value")),
                            unit=probe.get("unit") or sres.get("unit"),
                            icon="mdi:chart-line",
                            attributes=attrs,
                            history_line=history,
                        )
                    )
            elif kind == "calendar":
                window = result.get("window") or {}
                attrs = {"dashboard": name, "from": window.get("from"), "to": window.get("to")}
                add(
                    SensorSpec(
                        key="calendar_workouts",
                        dashboard_id=summary["id"],
                        dashboard_name=name,
                        name="Calendar workouts",
                        kind="calendar_total",
                        value=_num(result.get("total")),
                        unit="workouts",
                        icon="mdi:calendar-check",
                        attributes=attrs,
                    )
                )
                add(
                    SensorSpec(
                        key="week_streak",
                        dashboard_id=summary["id"],
                        dashboard_name=name,
                        name="Week streak",
                        kind="calendar_streak",
                        value=_num(result.get("streakWeeks")),
                        unit="weeks",
                        icon="mdi:fire",
                        attributes={"dashboard": name},
                    )
                )
            elif kind == "muscles":
                window = result.get("window") or {}
                groups = result.get("groups") or []
                attrs = {
                    "dashboard": name,
                    "from": window.get("from"),
                    "to": window.get("to"),
                    "truncated": result.get("truncated", False),
                }
                for g in groups:
                    attrs[g.get("key") or slugify(g.get("name", ""))] = _num(g.get("sets"))
                total = sum(_num(g.get("sets")) or 0 for g in groups)
                add(
                    SensorSpec(
                        key="muscle_sets",
                        dashboard_id=summary["id"],
                        dashboard_name=name,
                        name="Muscle sets per week",
                        kind="muscles",
                        value=round(total, 2) if groups else None,
                        unit=result.get("unit") or "sets/week",
                        icon="mdi:arm-flex",
                        attributes=attrs,
                    )
                )
            elif kind == "error":
                LOGGER.debug("Widget %s on %s: %s", wi, name, result.get("message"))

        return DashboardData(summary["id"], name, text, preview.get("errors", []), sensors)
