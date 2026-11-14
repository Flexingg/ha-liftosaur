"""Fixtures: a fake Liftosaur API that evaluates nothing but answers in the
real response shapes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.liftosaur import liftograph
from custom_components.liftosaur.const import API_BASE

FIXTURES = Path(__file__).parent / "fixtures"
DASHBOARD_TEXT = (FIXTURES / "strength_vs_bw.liftograph").read_text()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    yield


def _days(duration: str | None) -> int:
    if not duration:
        return 0
    n, unit = int(duration[:-1]), duration[-1]
    return n * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]


def fake_preview(text: str) -> dict:
    """Value widgets: value 100, and a change of 1 per week of `compare`,
    so N weeks ago the series was 100 - N. Series named "empty" have no data."""
    widgets = []
    row = 0
    for w in liftograph.parse(text):
        row += 1
        if w.kind == "value":
            src = dict(w.parts).get("source", "")
            if "Nothing" in src:
                widgets.append({"row": row, "kind": "value", "isEmpty": True})
                continue
            res = {"row": row, "kind": "value", "name": "x", "value": 100, "unit": "lb", "isEmpty": False}
            cmp = dict(w.parts).get("compare")
            if cmp:
                days = _days(cmp)
                if days <= 400:
                    res["delta"] = round(days / 7, 4)
            widgets.append(res)
        elif w.kind == "graph":
            widgets.append(
                {
                    "row": row,
                    "kind": "graph",
                    "caption": "**My graph** — note",
                    "xMode": "time",
                    "series": [
                        {
                            "name": s.name,
                            "status": "ready",
                            "pointCount": 3,
                            "unit": "lb",
                            "first": {"x": "2026-01-01", "y": 1},
                            "last": {"x": "2026-11-01", "y": 2},
                        }
                        for s in w.series
                    ],
                }
            )
        elif w.kind == "calendar":
            widgets.append({"row": row, "kind": "calendar", "window": {"from": "a", "to": "b"}, "total": 37, "streakWeeks": 12})
        elif w.kind == "muscles":
            widgets.append(
                {
                    "row": row,
                    "kind": "muscles",
                    "unit": "sets/week",
                    "groups": [{"key": "chest", "name": "Chest", "sets": 10}, {"key": "lats", "name": "Lats", "sets": 4.5}],
                }
            )
    return {"data": {"evaluatedAt": "2026-11-14T00:00:00Z", "errors": [], "widgets": widgets}}


class FakeLiftosaur:
    def __init__(self, text: str = DASHBOARD_TEXT, status: int = 200) -> None:
        self.text = text
        self.status = status
        self.preview_calls: list[str] = []
        self.history: list[dict] = [{"id": 1, "text": "2026-11-13T10:00:00Z / exercises: { Squat / 3x5 300lb }"}]
        self.history_calls = 0

    def register(self, aioclient_mock) -> None:
        aioclient_mock.clear_requests()
        aioclient_mock.get(f"{API_BASE}/dashboards", side_effect=self._list)
        aioclient_mock.get(re.compile(rf"{re.escape(API_BASE)}/dashboards/.+"), side_effect=self._get)
        aioclient_mock.post(f"{API_BASE}/dashboard-preview", side_effect=self._preview)
        aioclient_mock.get(re.compile(rf"{re.escape(API_BASE)}/history.*"), side_effect=self._history)

    def _resp(self, method, url, body):
        return AiohttpClientMockResponse(method, url, status=self.status, json=body)

    async def _list(self, method, url, data):
        if self.status != 200:
            return self._resp(method, url, {"error": {"code": "x", "message": "no"}})
        return self._resp(method, url, {"data": {"dashboards": [{"id": "abc", "name": "Strength", "isCurrent": True}]}})

    async def _get(self, method, url, data):
        return self._resp(method, url, {"data": {"id": "abc", "name": "Strength", "text": self.text, "isCurrent": True}})

    async def _history(self, method, url, data):
        self.history_calls += 1
        return self._resp(method, url, {"data": {"records": list(self.history)}})

    async def _preview(self, method, url, data):
        text = (data if isinstance(data, dict) else json.loads(data))["text"]
        self.preview_calls.append(text)
        return self._resp(method, url, fake_preview(text))


@pytest.fixture
def fake_api(aioclient_mock):
    api = FakeLiftosaur()
    api.register(aioclient_mock)
    return api
