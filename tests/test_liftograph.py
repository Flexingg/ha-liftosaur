"""Parser tests (no Home Assistant needed)."""

from custom_components.liftosaur import liftograph as L

from .conftest import DASHBOARD_TEXT


def test_parse_matches_server_widget_order():
    kinds = [w.kind for w in L.parse(DASHBOARD_TEXT)]
    assert kinds == [
        "value", "value", "value", "value",
        "graph", "graph",
        "calendar", "muscles", "muscles",
        "graph", "value",
    ]


def test_quoted_names_scripts_and_continuations():
    ws = L.parse(DASHBOARD_TEXT)
    assert ws[3].own_series.name == "Total / BW"
    assert "state.dl" in ws[3].script
    assert ws[2].script.strip() == "point(bodyweight * (1 - value / 100))"
    assert [s.name for s in ws[5].series] == ["Squat / BW", "Bench / BW"]
    assert ws[9].series[0].get("source") == 'exercise(Squat, program: "5/3/1 BBB - Squat/Bench/Deadlift/OHP")'
    assert ws[10].own_series.name == "Long"
    assert dict(ws[10].parts)["y"] == "e1rm"


def test_value_line_drops_display_keys_and_keeps_script():
    s = L.parse(DASHBOARD_TEXT)[4].series[0]
    line = L.value_line(s, "4w")
    assert line.startswith("value / source: exercise / group: last(1w) / compare: 4w {~")
    assert "color" not in line and line.endswith("~}")
    # Round-trips through the parser.
    again = L.parse(line)[0]
    assert again.kind == "value" and dict(again.parts)["compare"] == "4w"


def test_trailing_and_raw_series():
    s = L.Series([("name", "W"), ("source", "stats(weight)"), ("group", "avg(1w)")])
    assert L.trailing_series(s).parts == [("name", "W"), ("source", "stats(weight)"), ("smooth", "avg(1w)")]
    s2 = L.Series([("source", "exercise"), ("group", "last(1w)")])
    assert L.trailing_series(s2).parts == [("source", "exercise")]
    s3 = L.Series([("source", "stats(weight)"), ("smooth", "avg(7d)")])
    assert L.raw_series(s3).parts == [("source", "stats(weight)")]
    s4 = L.Series([("source", "exercise(Squat)"), ("smooth", "avg(5)")])
    assert L.raw_series(s4).parts == s4.parts


def test_offsets_and_chunks():
    offs = L.backfill_offsets(52)
    assert offs[0] == ("1d", 1) and offs[12] == ("13d", 13) and offs[13] == ("2w", 14)
    assert offs[-1] == ("52w", 364) and len(offs) == 13 + 51
    chunks = L.chunk_lines(["x" * 1000] * 120, max_bytes=48_000)
    assert sum(len(c) for c in chunks) == 120
    assert all(sum(len(line) + 2 for line in c) <= 48_000 for c in chunks)


def test_caption_cleaning():
    from custom_components.liftosaur.coordinator import clean_caption

    assert clean_caption("**AMRAP reps beyond the target** — the + set.") == "AMRAP reps beyond the target"
    assert clean_caption("## Weekly sets\nmore") == "Weekly sets"
    assert clean_caption("**Training max per cycle** (top-set)") == "Training max per cycle"
    assert clean_caption(None) is None
