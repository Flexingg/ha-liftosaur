# Liftosaur for Home Assistant

[![hacs](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/Flexingg/ha-liftosaur/actions/workflows/validate.yml/badge.svg)](https://github.com/Flexingg/ha-liftosaur/actions/workflows/validate.yml)

Your [Liftosaur](https://www.liftosaur.com) dashboards (the **Graphs** tab) as Home Assistant sensors, with their history backfilled into long-term statistics so charts show your past year from day one.

Liftosaur evaluates every number itself. This integration never re-implements an e1RM formula or a Liftograph script, so what you see in Home Assistant matches the app exactly, including custom scripts.

## What you get

For every dashboard, a device named **Liftosaur &lt;dashboard&gt;** with:

| Dashboard widget | Sensor | State | Attributes |
|---|---|---|---|
| `value` | the widget's name | today's value | `change`, `compared_to` |
| each `graph` series | `<graph caption> · <series>` | the series today | `change_1w`, `first_*`, `last_point_*`, `point_count` |
| `calendar` | Calendar workouts, Week streak | workouts in range, streak in weeks | `from`, `to` |
| `muscles` | Muscle sets per week | total sets per week | sets per muscle group |

Add, rename or edit a dashboard in the app and the sensors follow on the next refresh. No YAML to keep in sync.

## History backfill

When a sensor first appears, the integration asks Liftosaur what that series was 1–13 days ago and then every week back (52 weeks by default, up to 520). It uses Liftosaur's own `compare:` feature: today's value minus the change over N weeks is the value N weeks ago, as Liftosaur computes it. The results go into the sensor's own long-term statistics, so the regular **Statistics graph** card, or ApexCharts with `statistics:`, shows them next to the live data.

Two details:

- A graph series grouped by calendar bucket (`group: max(1w)`) is tracked as the equivalent trailing window (`smooth: max(1w)`), which has a value on every day of the week.
- If a windowed series has no data today (say, a weekly bodyweight average and no weigh-in this week), the sensor falls back to the unwindowed series.

Run **Liftosaur: Backfill history** (`liftosaur.backfill`) to redo it after big edits. Already-backfilled sensors are skipped on restart.

## Requirements

- Liftosaur **Premium** (needed for the API).
- An API key: in the app, **Settings → API Keys → Create API Key**. It starts with `lftsk_`.
- Home Assistant 2025.11 or newer, with the recorder enabled (it is by default).

## Install

### HACS

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Flexingg/ha-liftosaur`, category **Integration**.
2. Install **Liftosaur**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Liftosaur**, and paste your API key.

### Manual

Copy `custom_components/liftosaur` into your `config/custom_components/`, restart, then add the integration.

## Options

**Settings → Devices & services → Liftosaur → Configure**

- **Dashboards**: which dashboards to import. Empty means all, including new ones.
- **Refresh every**: default 30 minutes. Each refresh costs about two API calls per dashboard, plus one.
- **History to backfill**: weeks, default 52. 0 turns backfill off.
- **Workout window**: off by default. Turn it on and set when you usually train (say 4:00–5:00) and how often to check during it (default every minute). Inside the window each check is a single small request for recently logged workouts; your dashboards are only re-evaluated when a workout was added or changed, or once per regular interval. Sensors then update about a minute after you finish a workout, quickly enough for automations such as a PR alert to fire while you're still in the gym. Outside the window the regular interval applies, and the first check of the window lands right when it opens. The window can cross midnight.

### Example: celebrate a PR as it happens

With the workout window on, a state trigger on a series such as `sensor.liftosaur_5_3_1_main_lifts_best_e1rm_per_week_squat` fires within a minute of finishing the workout. Compare it to the best you've stored in an `input_number`, update that, then flash a light or announce it on a speaker.

## Charts

[`examples/apexcharts-strength.yaml`](examples/apexcharts-strength.yaml) has an ApexCharts card with a year of weekly e1RM. The built-in card works too:

```yaml
type: statistics-graph
entities:
  - sensor.liftosaur_strength_vs_bodyweight_total_bw
period: week
days_to_show: 365
stat_types: [mean]
chart_type: line
```

## Privacy

The API key is stored in Home Assistant's config entry and is only sent to `www.liftosaur.com`. Diagnostics downloads redact it.

## Not affiliated

A community integration, not made by or affiliated with Liftosaur.
