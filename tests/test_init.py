"""Setup, sensors, backfill and config flow against the fake API."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant import config_entries
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.liftosaur.const import CONF_BACKFILL_WEEKS, DOMAIN

KEY = "lftsk_test"


async def _setup(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: KEY}, options=options or {}, unique_id="u")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_sensors_created(recorder_mock, hass: HomeAssistant, fake_api) -> None:
    entry = await _setup(hass, {CONF_BACKFILL_WEEKS: 0})
    assert entry.state is ConfigEntryState.LOADED

    ent = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent, entry.entry_id)
    names = sorted(e.original_name for e in entities)
    assert "Total / BW" in names
    assert "My graph · Squat / BW" in names
    assert "Week streak" in names
    assert "Muscle sets per week" in names and "Muscle sets per week (selected)" in names
    # 4 values + 2+2+1 graph series + 1 value + 2 calendar + 2 muscles
    assert len(entities) == 14

    device = dr.async_get(hass).async_get_device({(DOMAIN, f"{entry.entry_id}_abc")})
    assert device.name == "Liftosaur Strength"

    state = hass.states.get("sensor.liftosaur_strength_total_bw")
    assert state.state == "100.0"
    assert state.attributes["change"] == 4.0
    assert state.attributes["compared_to"] == "4w"
    assert state.attributes["unit_of_measurement"] == "lb"
    assert state.attributes["state_class"] == "measurement"

    graph = hass.states.get("sensor.liftosaur_strength_my_graph_squat_bw")
    assert graph.state == "100.0"
    assert graph.attributes["change_1w"] == 1.0
    assert graph.attributes["last_point_date"] == "2026-11-01"

    streak = hass.states.get("sensor.liftosaur_strength_week_streak")
    assert streak.state == "12.0"
    muscles = hass.states.get("sensor.liftosaur_strength_muscle_sets_per_week")
    assert muscles.state == "14.5" and muscles.attributes["chest"] == 10.0


async def test_backfill_imports_statistics(recorder_mock, hass: HomeAssistant, fake_api) -> None:
    await _setup(hass, {CONF_BACKFILL_WEEKS: 8})
    await async_wait_recording_done(hass)

    sid = "sensor.liftosaur_strength_total_bw"
    stats = await recorder_mock.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utcnow() - timedelta(weeks=10),
        None,
        {sid},
        "hour",
        None,
        {"mean"},
    )
    rows = stats[sid]
    # 13 daily + 7 weekly (2w..8w)
    assert len(rows) == 20
    # 8 weeks ago the fake series was 100 - 8
    assert rows[0]["mean"] == 92.0
    assert rows[-1]["mean"] == round(100 - 1 / 7, 2)

    # Metadata agrees with what the sensor recorder derives for "lb".
    from homeassistant.components.recorder.statistics import get_metadata

    meta = await recorder_mock.async_add_executor_job(lambda: get_metadata(hass, statistic_ids={sid}))
    assert meta[sid][1]["unit_class"] == "mass"

    # Second run is a no-op: same definitions.
    calls = len(fake_api.preview_calls)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    from custom_components.liftosaur.backfill import async_backfill

    assert await async_backfill(hass, entry) == 0
    assert len(fake_api.preview_calls) == calls

    # The service forces it.
    resp = await hass.services.async_call(DOMAIN, "backfill", {}, blocking=True, return_response=True)
    assert resp["sensors_backfilled"] == 10  # every value/series sensor


async def test_auth_failure_starts_reauth(recorder_mock, hass: HomeAssistant, fake_api) -> None:
    fake_api.status = 401
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: KEY}, unique_id="u")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_config_flow(recorder_mock, hass: HomeAssistant, fake_api) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    fake_api.status = 403
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: KEY})
    assert result["errors"] == {"base": "no_subscription"}

    fake_api.status = 200
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: " " + KEY + " "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: KEY}


async def test_options_flow(recorder_mock, hass: HomeAssistant, fake_api) -> None:
    entry = await _setup(hass, {CONF_BACKFILL_WEEKS: 0})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"dashboards": ["abc"], "scan_interval": 15, "backfill_weeks": 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.options["scan_interval"] == 15
    assert entry.runtime_data.update_interval == timedelta(minutes=15)


async def test_empty_series_falls_back_to_raw(recorder_mock, hass: HomeAssistant, aioclient_mock) -> None:
    from .conftest import FakeLiftosaur

    api = FakeLiftosaur(text="graph {\n  name: W / source: stats(Nothing) / group: avg(1w)\n}\n")
    api.register(aioclient_mock)
    entry = await _setup(hass, {CONF_BACKFILL_WEEKS: 0})
    spec = next(iter(entry.runtime_data.data["abc"].sensors.values()))
    # Both forms are empty in the fake, so the raw form is chosen.
    assert spec.history_line == "value / source: stats(Nothing)"
    assert spec.value is None


WINDOW = {
    CONF_BACKFILL_WEEKS: 0,
    "workout_window": True,
    "workout_start": "04:00:00",
    "workout_end": "05:00:00",
    "workout_interval": 1,
}


def _local(h: int, m: int) -> datetime:
    return datetime(2026, 11, 14, h, m, tzinfo=dt_util.get_default_time_zone())


async def test_workout_window_polls_quickly_and_cheaply(
    recorder_mock, hass: HomeAssistant, fake_api, freezer
) -> None:
    freezer.move_to(_local(4, 10))
    entry = await _setup(hass, WINDOW)
    coordinator = entry.runtime_data
    assert coordinator.update_interval == timedelta(minutes=1)
    assert coordinator.full_refreshes == 1
    previews = len(fake_api.preview_calls)

    # Nothing new logged: one history request, no dashboard re-evaluation.
    freezer.tick(timedelta(minutes=1))
    await coordinator.async_refresh()
    assert coordinator.full_refreshes == 1
    assert len(fake_api.preview_calls) == previews
    assert fake_api.history_calls == 2

    # A workout is logged: the next poll re-evaluates the dashboards.
    fake_api.history.append({"id": 2, "text": "2026-11-14T09:05:00Z / exercises: { Bench / 3x5 225lb }"})
    freezer.tick(timedelta(minutes=1))
    await coordinator.async_refresh()
    assert coordinator.full_refreshes == 2
    assert len(fake_api.preview_calls) > previews

    # Edits to a logged workout count too.
    fake_api.history[-1] = {**fake_api.history[-1], "text": "edited"}
    freezer.tick(timedelta(minutes=1))
    await coordinator.async_refresh()
    assert coordinator.full_refreshes == 3

    # Even with nothing new, a full refresh still happens every regular interval.
    freezer.tick(timedelta(minutes=31))
    await coordinator.async_refresh()
    assert coordinator.full_refreshes == 4


async def test_workout_window_closed(recorder_mock, hass: HomeAssistant, fake_api, freezer) -> None:
    freezer.move_to(_local(3, 50))
    entry = await _setup(hass, WINDOW)
    coordinator = entry.runtime_data
    # Wakes up when the window opens, not 30 minutes later.
    assert coordinator.update_interval == timedelta(minutes=10)
    # Outside the window the change check is skipped entirely.
    assert fake_api.history_calls == 0
    freezer.move_to(_local(12, 0))
    await coordinator.async_refresh()
    assert coordinator.full_refreshes == 2
    assert coordinator.update_interval == timedelta(minutes=30)
    assert fake_api.history_calls == 0

    # The first poll in the window refreshes fully, even with no new workouts.
    freezer.move_to(_local(4, 0))
    await coordinator.async_refresh()
    assert coordinator.full_refreshes == 3
    assert coordinator.update_interval == timedelta(minutes=1)


async def test_options_flow_workout_window(recorder_mock, hass: HomeAssistant, fake_api, freezer) -> None:
    freezer.move_to(_local(12, 0))
    entry = await _setup(hass, {CONF_BACKFILL_WEEKS: 0})
    base = {"dashboards": [], "scan_interval": 60, "backfill_weeks": 0}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**base, "workout_window": True, "workout_start": "04:00:00", "workout_end": "04:00:00", "workout_interval": 1},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"workout_end": "window_empty"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**base, "workout_window": True, "workout_start": "04:00:00", "workout_end": "05:00:00", "workout_interval": 1},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    assert coordinator.workout_window is not None
    assert coordinator.normal_interval == timedelta(minutes=60)
    assert coordinator.update_interval == timedelta(minutes=60)
