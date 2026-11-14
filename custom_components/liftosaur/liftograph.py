"""A small Liftograph reader.

Liftograph is the text format of Liftosaur dashboards. Liftosaur evaluates
it on the server (POST /dashboard-preview), so this module never computes
anything. It only does two things:

* split a dashboard into its widgets, in the same order the server reports
  them, so each result can be matched to the text that produced it;
* turn any series (a ``value`` widget, or one line of a ``graph``) into a
  ``value`` widget with ``compare: <duration>``. The server then answers with
  today's value and its change over that duration, which gives the exact
  value the series had back then. That is how history is backfilled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("graph", "value", "muscles", "calendar")

# Keys that only change how a series is drawn, or that a backfill line sets
# itself. They are dropped when a series is turned into a value widget.
_DISPLAY_KEYS = {"mark", "axis", "color", "compare", "trend", "range", "name"}


@dataclass
class Series:
    """One series: the key/value parts and an optional script body."""

    parts: list[tuple[str, str]]
    script: str | None = None

    def get(self, key: str) -> str | None:
        for k, v in self.parts:
            if k == key:
                return v
        return None

    @property
    def name(self) -> str | None:
        name = self.get("name")
        return unquote(name) if name is not None else None


@dataclass
class Widget:
    """One widget, in document order."""

    kind: str
    parts: list[tuple[str, str]]
    script: str | None = None
    series: list[Series] = field(default_factory=list)

    @property
    def own_series(self) -> Series | None:
        """The series of a value widget, which lives on the widget line."""
        if self.kind != "value":
            return None
        return Series(self.parts, self.script)


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value


def _split_top(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside double quotes and parentheses."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def _find_outside_quotes(text: str, token: str) -> int:
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
        elif text.startswith(token, i):
            return i
        i += 1
    return -1


def _parse_parts(head: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    for chunk in _split_top(head, "/"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition(":")
        if not sep:
            continue
        parts.append((key.strip(), value.strip()))
    return parts


def _kind_of(line: str) -> str | None:
    for kind in KINDS:
        if line == kind or line.startswith((kind + " ", kind + "/", kind + "{")):
            return kind
    return None


def _logical_lines(text: str) -> list[str]:
    """Join lines ending with a backslash; keep scripts on as many lines as
    they take, as one logical line."""
    raw = text.replace("\r\n", "\n").split("\n")
    joined: list[str] = []
    buf = ""
    for line in raw:
        if line.rstrip().endswith("\\") and not line.lstrip().startswith("//"):
            buf += line.rstrip()[:-1] + " "
            continue
        joined.append(buf + line)
        buf = ""
    if buf:
        joined.append(buf)

    out: list[str] = []
    i = 0
    while i < len(joined):
        line = joined[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            out.append(stripped)
            i += 1
            continue
        start = _find_outside_quotes(line, "{~")
        if start >= 0 and "~}" not in line[start + 2 :]:
            block = [line]
            i += 1
            while i < len(joined):
                block.append(joined[i])
                if "~}" in joined[i]:
                    break
                i += 1
            out.append("\n".join(block).strip())
            i += 1
            continue
        out.append(stripped)
        i += 1
    return out


def _split_script(line: str) -> tuple[str, str | None, bool]:
    """Return (head, script, opens_block)."""
    start = _find_outside_quotes(line, "{~")
    if start >= 0:
        end = line.rfind("~}")
        script = line[start + 2 : end] if end > start else line[start + 2 :]
        return line[:start], script.strip("\n"), False
    stripped = line.rstrip()
    if stripped.endswith("{"):
        return stripped[:-1], None, True
    return stripped, None, False


def parse(text: str) -> list[Widget]:
    """Return the widgets of a dashboard in document order."""
    widgets: list[Widget] = []
    graph: Widget | None = None
    for line in _logical_lines(text):
        if not line or line.startswith("//"):
            continue
        if graph is not None:
            if line == "}":
                widgets.append(graph)
                graph = None
                continue
            head, script, _ = _split_script(line)
            graph.series.append(Series(_parse_parts(head), script))
            continue
        if line == "}" or line.startswith("row"):
            continue
        kind = _kind_of(line)
        if kind is None:
            continue
        head, script, opens = _split_script(line)
        widget = Widget(kind, _parse_parts(head[len(kind) :]), script)
        if kind == "graph" and opens:
            graph = widget
        else:
            widgets.append(widget)
    if graph is not None:
        widgets.append(graph)
    return widgets


def value_line(series: Series, compare: str | None = None, name: str | None = None) -> str:
    """Write a series as a ``value`` widget line (with its script, if any)."""
    parts = [(k, v) for k, v in series.parts if k not in _DISPLAY_KEYS]
    head = ["value"]
    if name is not None:
        head.append(f"name: {name}")
    head.extend(f"{k}: {v}" for k, v in parts)
    if compare:
        head.append(f"compare: {compare}")
    line = " / ".join(head)
    if series.script is not None:
        line += " {~\n" + series.script.strip("\n") + "\n~}"
    return line


_SMOOTH_AGGS = {"avg", "sum", "count", "max", "min"}


def _is_duration_window(value: str) -> bool:
    inner = value[value.find("(") + 1 : value.rfind(")")].strip()
    return bool(inner) and inner[-1] in "dwmy" and inner[:-1].isdigit()


def trailing_series(series: Series) -> Series:
    """Swap a calendar ``group`` bucket for the same trailing ``smooth`` window.

    A value widget reports a grouped series as the current bucket, which is
    empty early in a new week. A trailing window keeps the same meaning
    (e.g. "sets in the last week") and has a value on every day, so it can be
    asked "what were you N days ago". ``group: last(...)`` has no smooth
    equivalent and is simply dropped.
    """
    group = series.get("group")
    if group is None:
        return series
    parts = [(k, v) for k, v in series.parts if k != "group"]
    agg = group.split("(", 1)[0].strip()
    if series.get("smooth") is None and agg in _SMOOTH_AGGS and _is_duration_window(group):
        parts.append(("smooth", group))
    return Series(parts, series.script)


def raw_series(series: Series) -> Series:
    """The series without time-window shaping: the fallback when a windowed
    series has no data today (say, a weekly bodyweight average with no
    weigh-in this week). Point-count smoothing such as ``avg(5)`` is kept."""
    parts = [
        (k, v)
        for k, v in series.parts
        if k != "group" and not (k == "smooth" and _is_duration_window(v))
    ]
    return Series(parts, series.script)


def backfill_offsets(weeks: int) -> list[tuple[str, int]]:
    """Durations to ask for, as (liftograph duration, days ago).

    Daily for the last two weeks, then weekly.
    """
    offsets = [(f"{d}d", d) for d in range(1, 14)]
    offsets.extend((f"{w}w", w * 7) for w in range(2, max(2, weeks) + 1))
    return offsets


def chunk_lines(lines: list[str], max_bytes: int = 48_000, max_lines: int = 250) -> list[list[str]]:
    """Group widget lines into documents under the 64 KB dashboard limit."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        n = len(line.encode()) + 2
        if cur and (size + n > max_bytes or len(cur) >= max_lines):
            chunks.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += n
    if cur:
        chunks.append(cur)
    return chunks
