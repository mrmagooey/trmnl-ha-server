# History Graph Gap-Dashing Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `history_graph` component so that a data gap (entity reported `unavailable`/`unknown`) stays rendered as a dashed hold-line across its full span even after a new real reading arrives, instead of silently becoming a solid line interpolated between the pre-gap and post-gap values.

**Architecture:** `_process_history_to_points` (hass_client.py) stops discarding HA's `unavailable`/`unknown` states; it now emits an explicit `(timestamp, None)` gap marker for them instead of dropping the timestamp entirely. `_draw_graph_component` (components.py) gains a new pure helper, `_build_draw_segments`, that walks the (possibly gap-containing) point list once and classifies each consecutive span as solid (both endpoints real) or dashed-flat (holding the last known value across a gap — including the existing live-tail-to-"now" case, which becomes just another instance of the same rule instead of a separate hardcoded block).

**Tech Stack:** Python 3.12, Pillow (manual dashed-line drawing via the existing `_draw_dashed_line` helper), stdlib `datetime`, `unittest`.

**Baseline:** `250 passed, 2 failed` on `main` today. The 2 failures (`TestGoldenImages::test_entity_attribute_dashboard`, `TestGoldenImages::test_history_graph_bipolar`) are **pre-existing and unrelated** to this work — their golden PNGs are stale/mismatched already on `main`. Do not attempt to fix them as part of this plan; just confirm the failing set doesn't grow.

**Test command (everywhere below):**
```
uv run pytest -q
```

## Global Constraints

- Do not touch the 2 pre-existing failing golden tests (`test_entity_attribute_dashboard`, `test_history_graph_bipolar`) — out of scope.
- `.gitignore` has a blanket `*.png` rule. Any new golden reference PNG must be force-added (`git add -f`) or it will silently regenerate itself on every CI run and never actually guard against regressions (this already happened to several pre-existing golden images in this repo — don't repeat it).
- Only Home Assistant's two real sentinel states, `unavailable` and `unknown`, count as a data gap. Any other non-numeric state is genuinely malformed data and must keep being silently dropped, exactly as today (see `test_invalid_state_value` in `tests/test_hass_client.py`, which must keep passing unmodified).
- Gap detection must never be based on elapsed time between samples — HA's history API only logs actual state *changes*, so a sensor that legitimately holds one value for hours produces a normal large time gap that must still render solid.
- A gap before the very first real reading has no known value to hold forward, so it produces no drawn segment (nothing renders for that span) — do not invent a value.

---

## File Structure

- `src/trmnl_server/hass_client.py` — `_process_history_to_points` emits `(timestamp, None)` gap markers instead of dropping `unavailable`/`unknown` states.
- `src/trmnl_server/components.py` — new pure helper `_build_draw_segments`; `_draw_graph_component` updated to consume `float | None` values, compute min/max/last-value from real readings only, and replace its single solid-polyline draw + hardcoded trailing-tail block with a loop over `_build_draw_segments`.
- `tests/test_hass_client.py` — new tests for gap-marker emission on `TestProcessHistoryToPoints`.
- `tests/test_components.py` — new `TestBuildDrawSegments` class; new regression tests on `TestDrawGraphComponent`.
- `tests/test_golden.py` — new golden-image regression test + committed reference PNG.
- `tests/test_api.py` — new end-to-end test through the real HTTP handler (`_handle_static_png`).

---

## Task 1: Gap markers in `_process_history_to_points`

**Files:**
- Modify: `src/trmnl_server/hass_client.py:282-305`
- Test: `tests/test_hass_client.py` (extend `TestProcessHistoryToPoints`, class starts at line 45)

**Interfaces:**
- Produces: `_process_history_to_points(history: list[list[HistoryPoint]] | None) -> list[tuple[datetime, float | None]]` — a `None` value at a given timestamp means the entity was `unavailable`/`unknown` at that time. Sorted by timestamp. Non-gap, non-numeric states are still dropped entirely (no entry at all), unchanged from today.

- [ ] **Step 1: Write the failing tests**

In `tests/test_hass_client.py`, add these three methods to `TestProcessHistoryToPoints` (after `test_sorts_by_timestamp`, i.e. after line 93):

```python
    def test_unavailable_state_becomes_gap_marker(self):
        """An 'unavailable' state produces a (timestamp, None) gap marker instead of being dropped."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'unavailable', 'last_changed': '2025-01-15T11:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-01-15T12:00:00+00:00'},
        ]]

        result = _process_history_to_points(history)

        self.assertEqual(len(result), 3)
        self.assertIsNone(result[1][1])
        self.assertEqual(result[1][0], datetime.fromisoformat('2025-01-15T11:00:00+00:00'))

    def test_unknown_state_becomes_gap_marker(self):
        """An 'unknown' state produces a (timestamp, None) gap marker instead of being dropped."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'unknown', 'last_changed': '2025-01-15T11:00:00+00:00'},
        ]]

        result = _process_history_to_points(history)

        self.assertEqual(len(result), 2)
        self.assertIsNone(result[1][1])

    def test_genuinely_invalid_state_still_dropped(self):
        """A state that is neither numeric nor a known HA gap sentinel is still dropped entirely."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'garbled-nonsense', 'last_changed': '2025-01-15T11:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-01-15T12:00:00+00:00'},
        ]]

        result = _process_history_to_points(history)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][1], 21.5)
        self.assertEqual(result[1][1], 22.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hass_client.py::TestProcessHistoryToPoints -v`
Expected: `test_unavailable_state_becomes_gap_marker` and `test_unknown_state_becomes_gap_marker` FAIL (both currently-non-numeric states are silently dropped today, so `len(result)` is 2, not 3/2-with-a-None). `test_genuinely_invalid_state_still_dropped` and all pre-existing tests PASS already (no behavior change needed for them).

- [ ] **Step 3: Implement the gap-marker logic**

In `src/trmnl_server/hass_client.py`, replace lines 282-305:

```python
def _process_history_to_points(
    history: list[list[HistoryPoint]] | None,
) -> list[tuple[datetime, float]]:
    """Processes raw history data into a list of (timestamp, value) tuples.
    
    Args:
        history: Raw history data from Home Assistant
        
    Returns:
        List of (datetime, float) tuples sorted by timestamp
    """
    data_points: list[tuple[datetime, float]] = []
    if not history or not history[0]:
        return data_points

    for state in history[0]:
        try:
            value: float = float(state['state'])
            timestamp: datetime = datetime.fromisoformat(state['last_changed'])
            data_points.append((timestamp, value))
        except (ValueError, TypeError):
            continue
    data_points.sort()
    return data_points
```

with:

```python
_HA_GAP_STATES: frozenset[str] = frozenset({'unavailable', 'unknown'})


def _process_history_to_points(
    history: list[list[HistoryPoint]] | None,
) -> list[tuple[datetime, float | None]]:
    """Processes raw history data into a list of (timestamp, value) tuples.

    A value of None marks a point where Home Assistant reported the entity
    as 'unavailable' or 'unknown' — a genuine data gap — as opposed to a
    state that simply failed to parse as a number, which is dropped as
    before.

    Args:
        history: Raw history data from Home Assistant

    Returns:
        List of (datetime, value) tuples sorted by timestamp; value is
        None where the entity was reported unavailable/unknown at that time.
    """
    data_points: list[tuple[datetime, float | None]] = []
    if not history or not history[0]:
        return data_points

    for state in history[0]:
        try:
            timestamp: datetime = datetime.fromisoformat(state['last_changed'])
            if state['state'] in _HA_GAP_STATES:
                data_points.append((timestamp, None))
                continue
            value: float = float(state['state'])
            data_points.append((timestamp, value))
        except (ValueError, TypeError):
            continue
    data_points.sort(key=lambda point: point[0])
    return data_points
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hass_client.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/hass_client.py tests/test_hass_client.py
git commit -m "feat: preserve HA unavailable/unknown states as history gap markers"
```

---

## Task 2: `_build_draw_segments` pure helper

**Files:**
- Modify: `src/trmnl_server/components.py` (add module-level function immediately after `_draw_dashed_line`, which ends at line 154, before `_draw_graph_component` at line 157)
- Test: `tests/test_components.py` (new `TestBuildDrawSegments` class, placed after `TestDrawGraphComponent` — i.e. after line 348 — and before `class TestDrawEntityComponent`)

**Interfaces:**
- Consumes: nothing from other tasks (pure function, no dependency on Task 1's changes at the type level — it already accepts `float | None`).
- Produces: `_build_draw_segments(data_points: list[tuple[datetime, float | None]], window_end: datetime) -> list[tuple[datetime, float, datetime, float, bool]]`. Each returned tuple is `(t0, v0, t1, v1, dashed)`. Dashed segments always have `v0 == v1` (a flat hold at the last known real value). This is what Task 3 wires into `_draw_graph_component`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_components.py`, add `_build_draw_segments` to the existing import block from `trmnl_server.components` (the list starting at line 9):

```python
    _build_draw_segments,
```

Then add this class after `TestDrawGraphComponent` (after line 348, before `class TestDrawEntityComponent`):

```python
class TestBuildDrawSegments(unittest.TestCase):
    """Tests for the pure _build_draw_segments helper."""

    def test_all_real_points_produce_one_solid_segment_per_pair(self):
        from datetime import datetime
        t0, t1, t2 = datetime(2025, 1, 15, 9, 0), datetime(2025, 1, 15, 10, 0), datetime(2025, 1, 15, 11, 0)
        data_points = [(t0, 20.0), (t1, 21.0), (t2, 22.0)]

        segments = _build_draw_segments(data_points, window_end=t2)

        self.assertEqual(segments, [
            (t0, 20.0, t1, 21.0, False),
            (t1, 21.0, t2, 22.0, False),
        ])

    def test_gap_between_two_real_points_is_dashed_and_flat(self):
        """Regression case for the reported bug: a gap that has since been
        closed by a new reading must stay dashed and flat at the pre-gap
        value, not become a solid line interpolated to the new value."""
        from datetime import datetime
        t0, gap_t, t1 = datetime(2025, 1, 15, 9, 0), datetime(2025, 1, 15, 10, 0), datetime(2025, 1, 15, 13, 0)
        data_points = [(t0, 20.0), (gap_t, None), (t1, 30.0)]

        segments = _build_draw_segments(data_points, window_end=t1)

        self.assertEqual(segments, [(t0, 20.0, t1, 20.0, True)])

    def test_trailing_gap_holds_last_value_to_window_end(self):
        from datetime import datetime
        t0 = datetime(2025, 1, 15, 9, 0)
        window_end = datetime(2025, 1, 15, 16, 0)
        data_points = [(t0, 20.0)]

        segments = _build_draw_segments(data_points, window_end)

        self.assertEqual(segments, [(t0, 20.0, window_end, 20.0, True)])

    def test_no_trailing_segment_when_last_point_is_at_window_end(self):
        from datetime import datetime
        t0 = datetime(2025, 1, 15, 9, 0)
        data_points = [(t0, 20.0)]

        segments = _build_draw_segments(data_points, window_end=t0)

        self.assertEqual(segments, [])

    def test_leading_gap_before_first_real_point_produces_no_segment(self):
        """Nothing can be held forward before we have a first real reading."""
        from datetime import datetime
        gap_t = datetime(2025, 1, 15, 8, 0)
        t0 = datetime(2025, 1, 15, 9, 0)
        data_points = [(gap_t, None), (t0, 20.0)]

        segments = _build_draw_segments(data_points, window_end=t0)

        self.assertEqual(segments, [])

    def test_empty_input_produces_no_segments(self):
        from datetime import datetime
        self.assertEqual(_build_draw_segments([], window_end=datetime(2025, 1, 15, 9, 0)), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_components.py::TestBuildDrawSegments -v`
Expected: FAIL — `ImportError: cannot import name '_build_draw_segments'`.

- [ ] **Step 3: Implement the helper**

In `src/trmnl_server/components.py`, insert this function after `_draw_dashed_line` ends (after line 154) and before `def _draw_graph_component(` (line 157), preserving the existing two-blank-line spacing between top-level functions:

```python
def _build_draw_segments(
    data_points: list[tuple[datetime, float | None]],
    window_end: datetime,
) -> list[tuple[datetime, float, datetime, float, bool]]:
    """Splits history points into contiguous solid/dashed line segments.

    Consecutive real readings are joined with a solid segment. Any gap
    between two real readings — a None marker from an 'unavailable'/'unknown'
    state, or simply no reading yet between the last real one and
    `window_end` — is rendered as a dashed segment holding the last known
    value flat, rather than interpolating a value that was never observed.
    A gap before the very first real reading has nothing to hold forward
    from, so it produces no segment.

    Args:
        data_points: (timestamp, value) tuples sorted by timestamp; value
            is None to mark a known data gap.
        window_end: Right edge of the plotted time window ("now").

    Returns:
        (t0, v0, t1, v1, dashed) segments in chronological order. Dashed
        segments always have v0 == v1 (a flat hold).
    """
    segments: list[tuple[datetime, float, datetime, float, bool]] = []
    last_real: tuple[datetime, float] | None = None
    gap_pending: bool = False

    for t, v in data_points:
        if v is None:
            gap_pending = True
            continue
        if last_real is not None:
            t0, v0 = last_real
            if gap_pending:
                segments.append((t0, v0, t, v0, True))
            else:
                segments.append((t0, v0, t, v, False))
        last_real = (t, v)
        gap_pending = False

    if last_real is not None and window_end > last_real[0]:
        t0, v0 = last_real
        segments.append((t0, v0, window_end, v0, True))

    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_components.py::TestBuildDrawSegments -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: add pure _build_draw_segments helper for gap-aware line drawing"
```

---

## Task 3: Wire the helper into `_draw_graph_component`

**Files:**
- Modify: `src/trmnl_server/components.py:157-390` (`_draw_graph_component`)
- Test: `tests/test_components.py` (extend `TestDrawGraphComponent`)

**Interfaces:**
- Consumes: `_build_draw_segments` from Task 2 (exact signature above); gap-marker data shape `list[tuple[datetime, float | None]]` from Task 1.
- Produces: `_draw_graph_component(..., data_points: list[tuple[datetime, float | None]], ...)` — same external call signature otherwise (all other params unchanged), used by `_render_component` in this same file (no caller changes needed, since Python doesn't enforce the type hint at runtime and the caller already just forwards whatever `_process_history_to_points` returns).

- [ ] **Step 1: Write the failing tests**

In `tests/test_components.py`, add these methods to `TestDrawGraphComponent` (after `test_zero_baseline_flat_at_zero`, i.e. at the end of that class, before line 349):

```python
    def test_internal_gap_renders_dashed_not_interpolated(self):
        """Regression test for the reported bug: a gap that has been closed
        by a new reading must stay dashed across the gap span, not render as
        a smooth solid line interpolated between the pre-gap and post-gap
        values."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), None),
            (datetime(2025, 1, 15, 13, 0), 30.0),
        ]
        img = _draw_graph_component(
            "Gappy", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 13, 0),
        )
        # A naive full-interpolation render (no gap marker at all) is what the
        # bug used to produce once the gap closed; the fixed render must differ.
        naive_interpolated = _draw_graph_component(
            "Gappy", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 13, 0), 30.0),
            ], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 13, 0),
        )
        self.assertIsNotNone(
            ImageChops.difference(img, naive_interpolated).getbbox(),
            "gap rendering must differ from a naive solid interpolation",
        )

        # The gap segment is drawn flat and dashed — a horizontal scan across
        # its time span must show both painted and unpainted (gap) pixels.
        w, h = img.size  # (400, 300)
        band = []
        for x in range(int(w * 0.25), int(w * 0.75)):
            for y in range(h):
                band.append(img.getpixel((x, y)))
        has_black = any(sum(p) < 240 for p in band)
        has_white = any(sum(p) > 600 for p in band)
        self.assertTrue(has_black, "expected painted dash pixels across the gap region")
        self.assertTrue(has_white, "expected gap (unpainted) pixels across the gap region")

    def test_last_value_label_uses_most_recent_real_reading(self):
        """If the series ends on a gap marker (entity currently unavailable),
        the displayed last-value text must use the last REAL reading and
        must not crash."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), None),
        ]
        img = _draw_graph_component(
            "Stale", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_all_gap_data_shows_no_numeric_data_message(self):
        """A series that is entirely gap markers renders the no-data message
        instead of crashing on min()/max() of an empty sequence."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), None),
            (datetime(2025, 1, 15, 10, 0), None),
        ]
        img = _draw_graph_component(
            "AllGaps", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_components.py::TestDrawGraphComponent -v`
Expected: `test_internal_gap_renders_dashed_not_interpolated` FAILS (currently renders a solid interpolated line, identical to the naive version). `test_last_value_label_uses_most_recent_real_reading` and `test_all_gap_data_shows_no_numeric_data_message` FAIL or ERROR today because `_draw_graph_component` doesn't accept `None` values at all yet (`zip`/`min`/`max`/`f"{last_value:.1f}"` will raise on a `None`).

- [ ] **Step 3: Implement the wiring**

In `src/trmnl_server/components.py`, apply these four edits inside `_draw_graph_component` (lines given are current, pre-edit line numbers — locate each by its surrounding code, not by number, since earlier edits shift later ones):

**3a. Signature (line 157-159):** replace
```python
def _draw_graph_component(
    friendly_name: str,
    data_points: list[tuple[datetime, float]],
```
with
```python
def _draw_graph_component(
    friendly_name: str,
    data_points: list[tuple[datetime, float | None]],
```

**3b. No-data guard (lines 223-235):** replace
```python
    # Handle no data case
    if not data_points:
        msg: str = f"No numeric data for {friendly_name}"
```
with
```python
    # Handle no data case (including a series that is entirely gap markers)
    has_real_reading: bool = any(v is not None for _, v in data_points)
    if not data_points or not has_real_reading:
        msg: str = f"No numeric data for {friendly_name}"
```
(the rest of that block, lines 226-235, is unchanged)

**3c. Process-data + last-value setup (lines 242-249):** replace
```python
    # Process data
    times: tuple[datetime, ...]
    values: tuple[float, ...]
    times, values = zip(*data_points)
    min_time: datetime = window_start
    max_time: datetime = window_end
    min_val: float = min(values)
    max_val: float = max(values)
```
with
```python
    # Process data — min/max and the "last value" label are driven by real
    # (non-gap) readings only; gap markers only affect line drawing below.
    real_values: list[float] = [v for _, v in data_points if v is not None]
    min_time: datetime = window_start
    max_time: datetime = window_end
    min_val: float = min(real_values)
    max_val: float = max(real_values)
    last_real_time: datetime
    last_value: float
    last_real_time, last_value = next(
        (t, v) for t, v in reversed(data_points) if v is not None
    )
```

**3d. Display-last-value + draw-line + trailing-tail (lines 361-388):** replace
```python
    # Display last value
    last_value: float = values[-1]
    last_value_text: str = f"{last_value:.1f}"
    _last_x, last_y = to_coords(times[-1], last_value)
    text_bbox = d.textbbox((0, 0), last_value_text, font=font_value)
    text_height = text_bbox[3] - text_bbox[1]
    text_x: float = large_width - margin_right + (5 * scale)
    text_y: float = last_y - (text_height / 2)
    d.text((text_x, text_y), last_value_text, font=font_value, fill='black')

    # Draw data line
    points_coords: list[tuple[float, float]] = [to_coords(t, v) for t, v in data_points]
    if len(points_coords) > 1:
        d.line(points_coords, fill='black', width=4 * scale)

    # Hold the last received value forward to the right edge (now) as a dotted line.
    last_point_x, last_point_y = to_coords(times[-1], last_value)
    right_edge_x, _ = to_coords(max_time, last_value)
    if right_edge_x > last_point_x:
        _draw_dashed_line(
            d,
            (last_point_x, last_point_y),
            (right_edge_x, last_point_y),
            fill='black',
            width=4 * scale,
            dash_on=12 * scale,
            dash_off=8 * scale,
        )
```
with
```python
    # Display last value (the most recent REAL reading, computed above)
    last_value_text: str = f"{last_value:.1f}"
    _last_x, last_y = to_coords(last_real_time, last_value)
    text_bbox = d.textbbox((0, 0), last_value_text, font=font_value)
    text_height = text_bbox[3] - text_bbox[1]
    text_x: float = large_width - margin_right + (5 * scale)
    text_y: float = last_y - (text_height / 2)
    d.text((text_x, text_y), last_value_text, font=font_value, fill='black')

    # Draw data line: solid between consecutive real readings, dashed
    # (holding the last known value flat) across any gap — including the
    # live tail from the last reading forward to window_end ("now").
    for seg_t0, seg_v0, seg_t1, seg_v1, dashed in _build_draw_segments(data_points, max_time):
        p0 = to_coords(seg_t0, seg_v0)
        p1 = to_coords(seg_t1, seg_v1)
        if dashed:
            _draw_dashed_line(
                d, p0, p1,
                fill='black',
                width=4 * scale,
                dash_on=12 * scale,
                dash_off=8 * scale,
            )
        else:
            d.line([p0, p1], fill='black', width=4 * scale)
```

Also update the `data_points` docstring line (currently `data_points: List of (timestamp, value) tuples`, around line 172) to:
```
        data_points: List of (timestamp, value) tuples; value is None to
            mark a known data gap (the entity was reported unavailable or
            unknown at that time).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_components.py -v`
Expected: all PASS, including every pre-existing `TestDrawGraphComponent` test (`test_dotted_tail_drawn_when_last_point_before_window_end`, `test_no_tail_when_data_reaches_window_end`, `test_fully_stale_only_boundary_point`, the `zero_baseline` tests, etc.) — none of their expected behavior changes, only how it's computed internally.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: `250 passed, 2 failed` (only the two pre-existing, unrelated golden failures from the Baseline section — no new failures, and no fewer passes than before).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "fix: keep gap segments dashed across the whole outage span

A gap in the history data now renders as a dashed flat hold from the
last real reading to wherever real data resumes (or to now if it
hasn't yet), instead of the previous behavior where a newly-arrived
reading silently turned the whole gap into a solid interpolated line."
```

---

## Task 4: Integration-level golden image regression test

**Files:**
- Modify: `tests/test_golden.py` (extend `TestGoldenImages`)
- Create (committed reference image): `tests/golden/history_graph_gap_then_recovery.png`

**Interfaces:**
- Consumes: `render_dashboard_image` (unchanged signature) exercising the full pipeline: `_fetch_history` (mocked) → `_process_history_to_points` (Task 1) → `_draw_graph_component` (Task 3).

- [ ] **Step 1: Write the test**

In `tests/test_golden.py`, add this method to `TestGoldenImages`, after `test_history_graph_stale_tail` (after line 125):

```python
    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_gap_then_recovery(self, mock_fetch_history):
        """A gap ('unavailable') between two real readings must render as a
        dashed hold across the whole outage, not a smooth solid
        interpolation between the values on either side of it — this is the
        exact regression this plan fixes, pinned pixel-for-pixel."""
        mock_fetch_history.return_value = [[
            {'state': '18.0', 'last_changed': '2024-01-15T08:00:00+00:00'},
            {'state': 'unavailable', 'last_changed': '2024-01-15T09:00:00+00:00'},
            {'state': '25.0', 'last_changed': '2024-01-15T14:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'gap_recovery',
            'title': 'Gap Recovery',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Temperature',
                 'type': 'history_graph', 'hours': 24},
            ],
        }
        fixed_now = datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_gap_then_recovery')
```

- [ ] **Step 2: Generate and commit the golden reference**

Run: `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py::TestGoldenImages::test_history_graph_gap_then_recovery -q`
Expected: `1 passed` (the assert_golden helper creates the reference file since it doesn't exist yet).

Then **force-add** the new PNG — remember, `.gitignore` blanket-ignores `*.png`, so a plain `git add` silently does nothing and this test would regenerate its own "reference" forever without ever catching a regression:
```bash
git add -f tests/golden/history_graph_gap_then_recovery.png
```

- [ ] **Step 3: Verify the test now compares against the committed reference, not regenerates it**

Run: `uv run pytest tests/test_golden.py::TestGoldenImages::test_history_graph_gap_then_recovery -v`
Expected: `1 passed` (this second run performs a real pixel comparison, since the file now exists).

As a sanity check that the golden file is actually meaningful (not accidentally comparing something to itself trivially), temporarily revert `_build_draw_segments` in `src/trmnl_server/components.py` to the old single-`d.line(points_coords, ...)` behavior in a scratch copy or via `git stash`, rerun this one test, confirm it FAILS with an `AssertionError: Rendered image differs...`, then restore the real implementation (`git stash pop` if used) before continuing.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: `251 passed, 2 failed` (one more pass than Task 3's checkpoint; same 2 pre-existing unrelated failures).

- [ ] **Step 5: Commit**

```bash
git add tests/test_golden.py
git add -f tests/golden/history_graph_gap_then_recovery.png
git commit -m "test: pin golden image for history graph gap-then-recovery rendering"
```

---

## Task 5: End-to-end test through the real HTTP handler

**Files:**
- Modify: `tests/test_api.py` (extend `TestAPISimple`)

**Interfaces:**
- Consumes: `APICalls._handle_static_png` (unchanged signature/behavior contract — just exercising it with a `history_graph` component config that includes a gap, mocking `trmnl_server.api.read_config` and `trmnl_server.hass_client._fetch_history` exactly like existing tests in this file already do).

- [ ] **Step 1: Write the test**

In `tests/test_api.py`, add this method to `TestAPISimple` (anywhere in the class; e.g. after `test_static_png_unknown_device_returns_false`, after line 195):

```python
    @mock.patch('trmnl_server.hass_client._fetch_history')
    @mock.patch('trmnl_server.api.read_config')
    def test_static_png_history_graph_gap_recovery_renders_end_to_end(
        self, mock_read_config, mock_fetch_history,
    ):
        """End-to-end: GET a dashboard PNG for a history_graph whose entity
        went 'unavailable' and recovered. The served image must reflect the
        gap (differ from a control render with no gap), proving the fix is
        wired through the full request path — config lookup, HA history
        fetch, rendering, and e-ink conversion — not just the drawing
        function in isolation."""
        from datetime import datetime, timedelta, timezone
        from PIL import Image, ImageChops

        mock_read_config.return_value = {
            'devices': [],
            'dashboards': [{
                'name': 'gap_dashboard',
                'components': [
                    {'entity_name': 'sensor.temperature', 'friendly_name': 'Temperature',
                     'type': 'history_graph', 'hours': 24},
                ],
            }],
        }
        now = datetime.now(timezone.utc)
        mock_fetch_history.return_value = [[
            {'state': '18.0', 'last_changed': (now - timedelta(hours=20)).isoformat()},
            {'state': 'unavailable', 'last_changed': (now - timedelta(hours=19)).isoformat()},
            {'state': '25.0', 'last_changed': (now - timedelta(hours=10)).isoformat()},
        ]]
        handler = self.create_handler('/static/gap_dashboard.png')

        result = handler._handle_static_png()

        self.assertTrue(result)
        handler.wfile.seek(0)
        gap_img = Image.open(handler.wfile)
        gap_img.load()
        self.assertEqual(gap_img.size, (800, 480))
        self.assertEqual(gap_img.mode, '1')  # eink_display converts to 1-bit b/w

        # Control: same two real readings, no gap in between.
        mock_fetch_history.return_value = [[
            {'state': '18.0', 'last_changed': (now - timedelta(hours=20)).isoformat()},
            {'state': '25.0', 'last_changed': (now - timedelta(hours=10)).isoformat()},
        ]]
        control_handler = self.create_handler('/static/gap_dashboard.png')
        control_handler._handle_static_png()
        control_handler.wfile.seek(0)
        control_img = Image.open(control_handler.wfile)
        control_img.load()

        self.assertIsNotNone(
            ImageChops.difference(gap_img, control_img).getbbox(),
            "the served image must reflect the gap end-to-end, not render "
            "identically to a no-gap control",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api.py::TestAPISimple::test_static_png_history_graph_gap_recovery_renders_end_to_end -v`
Expected: PASSES already if Tasks 1-3 are done first (this task only adds coverage at a new layer; it doesn't require new production code). If you are executing this plan out of order for some reason and Tasks 1-3 are not yet applied, this FAILS because the gap has no effect on the served image yet.

- [ ] **Step 3: (No production code change needed — Tasks 1-3 already cover it)**

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: `252 passed, 2 failed` (same 2 pre-existing unrelated failures; every other test, including all new ones from Tasks 1-5, passes).

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py
git commit -m "test: add end-to-end coverage for history graph gap rendering via the HTTP handler"
```

---

## Final Verification

- [ ] Run the full suite one more time: `uv run pytest -q`. Confirm exactly the same 2 pre-existing failures as the Baseline and nothing else.
- [ ] Confirm `git status` shows the new golden PNG as tracked (`git ls-files tests/golden/history_graph_gap_then_recovery.png` should print the path).
- [ ] Read back through `_draw_graph_component` once fully assembled and confirm there is no longer any reference to the old `times`/`values`/`points_coords` variable names (they were fully replaced by `real_values` / `last_real_time` / `_build_draw_segments`).
