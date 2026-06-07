# History Graph Fixed-Window + Dotted Tail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `history_graph` components render a fixed rolling time window ending at "now", and hold the last received value forward as a horizontal dotted line when an entity has stopped reporting.

**Architecture:** A new per-component `hours` config (default 24) sets the window width. `render_dashboard_image` captures one injectable `now`, computes `[now − hours, now]` per graph, fetches exactly that window from Home Assistant, and carries the bounds in `RenderData`. `_draw_graph_component` draws the x-axis from those bounds (not the data) and appends a dashed "hold last value" tail from the last real point to the right edge.

**Tech Stack:** Python 3.12, Pillow (manual dashed-line drawing), stdlib `datetime`/`urllib`, pytest.

**Branch:** `graph-fixed-window-dotted-tail` (work happens in an isolated worktree on this branch).

**Spec:** `docs/superpowers/specs/2026-06-07-history-graph-dotted-window-design.md`

**Baseline:** `118 passed`. **Test command (everywhere below):**
```
uv run --with pytest --with pyyaml pytest -q
```

---

## File Structure

- `src/trmnl_server/models.py` — add `hours` to `ComponentConfig`; add `window_start`/`window_end` (NotRequired) to `RenderData`.
- `src/trmnl_server/hass_client.py` — `_fetch_history` gains windowed `start`/`end`.
- `src/trmnl_server/components.py` — new `_draw_dashed_line` helper; `render_dashboard_image` gains injectable `now`, computes window, windowed fetch, stores bounds; `_render_component` passes bounds; `_draw_graph_component` fixed-window + dotted tail.
- `tests/test_components.py`, `tests/test_hass_client.py`, `tests/test_server.py`, `tests/test_golden.py` — updated/added tests.
- `examples/config.yaml`, `README.md`, `AGENTS.md` — document `hours`.

---

## Task 1: Dashed-line helper

**Files:**
- Modify: `src/trmnl_server/components.py` (add module-level `_draw_dashed_line`)
- Test: `tests/test_components.py` (new `TestDrawDashedLine`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_components.py`. First add `_draw_dashed_line` to the existing import block (the `from trmnl_server.components import (...)` list):

```python
    _draw_dashed_line,
```

Then add this test class at the end of the file (before the `if __name__` guard if present, otherwise at end):

```python
class TestDrawDashedLine(unittest.TestCase):
    """Tests for the _draw_dashed_line helper."""

    def test_horizontal_dash_has_gaps(self):
        """A dashed line leaves white gaps, unlike a solid line."""
        from PIL import ImageDraw
        img = Image.new('RGB', (100, 10), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 5), (99, 5), fill='black', width=1, dash_on=6, dash_off=6)
        row = [img.getpixel((x, 5)) for x in range(100)]
        black = sum(1 for p in row if p == (0, 0, 0))
        white = sum(1 for p in row if p == (255, 255, 255))
        self.assertGreater(black, 0, "expected some painted (black) pixels")
        self.assertGreater(white, 0, "expected some gap (white) pixels")

    def test_zero_length_is_noop(self):
        """Start == end draws nothing and does not raise."""
        from PIL import ImageDraw
        img = Image.new('RGB', (10, 10), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (5, 5), (5, 5), fill='black', width=1, dash_on=4, dash_off=4)
        self.assertEqual(img.getpixel((5, 5)), (255, 255, 255))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestDrawDashedLine -q`
Expected: FAIL — `ImportError: cannot import name '_draw_dashed_line'`.

- [ ] **Step 3: Implement the helper**

In `src/trmnl_server/components.py`, add this function at module level, immediately above `def _draw_graph_component(`:

```python
def _draw_dashed_line(
    draw: "ImageDraw.ImageDraw",
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    fill: str,
    width: int,
    dash_on: int,
    dash_off: int,
) -> None:
    """Draw a dashed straight line between two points.

    PIL has no native dashed line, so we step along the segment drawing
    `dash_on`-long marks separated by `dash_off`-long gaps.
    """
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return
    ux = dx / length
    uy = dy / length
    pos = 0.0
    period = dash_on + dash_off
    while pos < length:
        seg = min(float(dash_on), length - pos)
        sx = x0 + ux * pos
        sy = y0 + uy * pos
        ex = x0 + ux * (pos + seg)
        ey = y0 + uy * (pos + seg)
        draw.line([(sx, sy), (ex, ey)], fill=fill, width=width)
        pos += period
```

Note: `ImageDraw` is already imported in this module (`from PIL import Image, ImageDraw, ImageFont`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestDrawDashedLine -q`
Expected: 2 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `120 passed` (118 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Add dashed-line drawing helper for graph components

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Plumbing — config, windowed fetch, injectable now, carry window

This task wires the data path (config → windowed fetch → window stored in RenderData) without yet changing how the graph is drawn. The graph still renders via the existing data-derived axis, so the suite stays green.

**Files:**
- Modify: `src/trmnl_server/models.py`
- Modify: `src/trmnl_server/hass_client.py`
- Modify: `src/trmnl_server/components.py` (`render_dashboard_image` only)
- Test: `tests/test_hass_client.py`, `tests/test_server.py`, `tests/test_golden.py`

- [ ] **Step 1: Write the failing test for the windowed fetch URL**

In `tests/test_hass_client.py`, update the imports at the top to:

```python
"""Tests for hass_client module."""

import logging
import unittest
from datetime import datetime, timezone
from unittest import mock

from trmnl_server.hass_client import (
    _cast_to_numbers,
    _fetch_history,
    _process_history_to_points,
)

mock_logger = mock.Mock(spec=logging.Logger)
```

Add this test class at the end of the file (before the `if __name__ == '__main__':` guard):

```python
class TestFetchHistoryWindow(unittest.TestCase):
    """Tests that _fetch_history requests the exact time window."""

    @mock.patch('trmnl_server.hass_client.urlopen')
    def test_builds_windowed_url(self, mock_urlopen):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = b'[[]]'
        mock_urlopen.return_value = cm
        start = datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc)
        with mock.patch('trmnl_server.hass_client.HASS_URL', 'http://hass'), \
             mock.patch('trmnl_server.hass_client.HASS_TOKEN', 'token'):
            _fetch_history('sensor.x', mock_logger, start=start, end=end)
        url = mock_urlopen.call_args[0][0].full_url
        self.assertIn('/api/history/period/2024-01-15T08:00:00Z', url)
        self.assertIn('filter_entity_id=sensor.x', url)
        self.assertIn('end_time=2024-01-15T16:00:00Z', url)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --with pytest --with pyyaml pytest tests/test_hass_client.py::TestFetchHistoryWindow -q`
Expected: FAIL — `TypeError: _fetch_history() got an unexpected keyword argument 'start'`.

- [ ] **Step 3: Make `_fetch_history` windowed**

In `src/trmnl_server/hass_client.py`, replace the `_fetch_history` signature and URL construction. Change the signature from:

```python
def _fetch_history(
    entity_name: str,
    logger: "Logger",
) -> list[list[HistoryPoint]] | None:
```

to:

```python
def _fetch_history(
    entity_name: str,
    logger: "Logger",
    *,
    start: datetime,
    end: datetime,
) -> list[list[HistoryPoint]] | None:
```

And replace the URL line:

```python
    url: str = f"{HASS_URL}/api/history/period?filter_entity_id={entity_name}"
```

with:

```python
    start_iso: str = start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end_iso: str = end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    url: str = (
        f"{HASS_URL}/api/history/period/{start_iso}"
        f"?filter_entity_id={entity_name}&end_time={end_iso}"
    )
```

(`datetime` and `timezone` are already imported in `hass_client.py`.)

- [ ] **Step 4: Run the fetch test to verify it passes**

Run: `uv run --with pytest --with pyyaml pytest tests/test_hass_client.py::TestFetchHistoryWindow -q`
Expected: 1 passed.

- [ ] **Step 5: Add `hours` to ComponentConfig and window fields to RenderData**

In `src/trmnl_server/models.py`:

Add `hours` to `ComponentConfig` (it is `total=False`, so the key is optional). The class currently ends with `large_display: bool`; add below it:

```python
    hours: int
```

For `RenderData`, add optional window bounds. First ensure `NotRequired` and `datetime` are importable. At the top of `models.py`, the typing import currently includes `Required`; change it to also import `NotRequired`, and add a `datetime` import. Concretely ensure these imports exist:

```python
from datetime import datetime
from typing import NotRequired, Required
```

(Keep any other names already imported from `typing` — just add `NotRequired` alongside them. If `from datetime import datetime` is not already present, add it.)

Then in `RenderData` (currently `type`, `friendly_name`, `data`, `large_display`), add:

```python
    window_start: NotRequired[datetime]
    window_end: NotRequired[datetime]
```

- [ ] **Step 6: Add injectable `now`, compute window, windowed fetch, store bounds**

In `src/trmnl_server/components.py`, update `render_dashboard_image`.

(a) Signature — change from:

```python
def render_dashboard_image(
    dashboard: DashboardConfig,
    logger: "Logger",
    device_id: str | None = None,
    device_rotate: int | None = None,
) -> BytesIO:
```

to:

```python
def render_dashboard_image(
    dashboard: DashboardConfig,
    logger: "Logger",
    device_id: str | None = None,
    device_rotate: int | None = None,
    *,
    now: datetime | None = None,
) -> BytesIO:
```

(b) At the start of the component-building section, just before `component_render_data: list[RenderData] = []`, capture the render time:

```python
    render_now: datetime = now if now is not None else datetime.now().astimezone()
```

(c) First, initialize a per-iteration `graph_window` variable. The loop body currently begins with a line `data: object = None` (just inside `for component in components:`). Immediately after that `data: object = None` line, add:

```python
        graph_window: tuple[datetime, datetime] | None = None
```

This guarantees `graph_window` is defined (`None`) for every component, including non-graph ones.

Then replace the `history_graph` branch in the component loop. Current:

```python
        if component_type == 'history_graph':
            entity_name = component.get('entity_name', '')
            history = _fetch_history(entity_name, logger)
            data = _process_history_to_points(history)
```

with (note: this branch only assigns `graph_window`, it does NOT re-declare it):

```python
        if component_type == 'history_graph':
            entity_name = component.get('entity_name', '')
            hours = component.get('hours', 24)
            if isinstance(hours, bool) or not isinstance(hours, int) or hours <= 0:
                logger.warning(
                    "Invalid 'hours' (%r) for %s; defaulting to 24.",
                    hours, component.get('friendly_name'),
                )
                hours = 24
            window_start: datetime = render_now - timedelta(hours=hours)
            window_end: datetime = render_now
            graph_window = (window_start, window_end)
            history = _fetch_history(entity_name, logger, start=window_start, end=window_end)
            data = _process_history_to_points(history)
```

(d) Where the `RenderData` dict is appended (currently `component_render_data.append({... 'large_display': ...})`), capture it into a variable and attach the window for graphs. Replace:

```python
        component_render_data.append({
            'type': component_type or 'unknown',
            'friendly_name': component.get('friendly_name', ''),
            'data': data,
            'large_display': component.get('large_display', False),
        })
```

with:

```python
        render_entry: RenderData = {
            'type': component_type or 'unknown',
            'friendly_name': component.get('friendly_name', ''),
            'data': data,
            'large_display': component.get('large_display', False),
        }
        if graph_window is not None:
            render_entry['window_start'] = graph_window[0]
            render_entry['window_end'] = graph_window[1]
        component_render_data.append(render_entry)
```

(`datetime` and `timedelta` are already imported in `components.py`.)

- [ ] **Step 7: Update test_server.py fetch assertions for the new signature**

In `tests/test_server.py`, the test `test_render_dashboard_image` asserts the old call shape at lines ~61-62:

```python
        mock_fetch_history.assert_any_call(components[0]['entity_name'], mock_logger)
        mock_fetch_history.assert_any_call(components[1]['entity_name'], mock_logger)
```

Replace both with window-tolerant assertions:

```python
        mock_fetch_history.assert_any_call(
            components[0]['entity_name'], mock_logger, start=mock.ANY, end=mock.ANY
        )
        mock_fetch_history.assert_any_call(
            components[1]['entity_name'], mock_logger, start=mock.ANY, end=mock.ANY
        )
```

(`mock` is already imported in `tests/test_server.py`.)

- [ ] **Step 8: Pin the graph golden test to a fixed `now`**

In `tests/test_golden.py`, `test_history_graph_dashboard` renders via `render_dashboard_image` without a `now`, which would otherwise use real wall-clock time and push the 2024 mock data out of the window. Pass an explicit `now` (1 hour after the last data point) and import `timezone` if not already imported (it is). Change:

```python
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)

        assert_golden(img_io, 'history_graph_dashboard')
```

to:

```python
        fixed_now = datetime(2024, 1, 15, 17, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)

        assert_golden(img_io, 'history_graph_dashboard')
```

- [ ] **Step 9: Run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `121 passed` (120 + 1 new fetch test). If `test_history_graph_dashboard` reports a golden mismatch (because a stale golden from before this change exists in `tests/golden/`), regenerate goldens once and re-run:
```
UPDATE_GOLDEN=1 uv run --with pytest --with pyyaml pytest tests/test_golden.py -q
uv run --with pytest --with pyyaml pytest -q
```
Expected after regen: `121 passed`. (Golden PNGs are gitignored, so nothing to commit from regeneration.)

- [ ] **Step 10: Commit**

```bash
git add src/trmnl_server/models.py src/trmnl_server/hass_client.py src/trmnl_server/components.py tests/test_hass_client.py tests/test_server.py tests/test_golden.py
git commit -m "feat: Fetch exact time window for history graphs and carry bounds

Add per-component hours (default 24), an injectable render 'now', a
windowed _fetch_history, and window bounds on RenderData. Drawing still
uses the data-derived axis; the next change consumes the bounds.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Fixed-window axis + dotted hold tail in the graph drawing

**Files:**
- Modify: `src/trmnl_server/components.py` (`_draw_graph_component`, `_render_component`)
- Test: `tests/test_components.py`

- [ ] **Step 1: Update existing graph unit tests for the new signature, and add new behavior tests**

In `tests/test_components.py`, the four tests in `TestDrawGraphComponent` call `_draw_graph_component` with no window. Update each call to pass keyword-only `window_start`/`window_end`, and add new tests. Replace the entire `TestDrawGraphComponent` class with:

```python
class TestDrawGraphComponent(unittest.TestCase):
    """Tests for _draw_graph_component function."""

    def test_draw_graph_no_data(self):
        """Test drawing graph with no data points."""
        from datetime import datetime
        img = _draw_graph_component(
            "Test Sensor", [], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_single_value(self):
        """Test drawing graph with single value (edge case for min/max)."""
        from datetime import datetime
        data_points = [(datetime(2025, 1, 15, 10, 0), 25.0)]
        img = _draw_graph_component(
            "Test Sensor", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_same_time(self):
        """Test drawing graph with same timestamp (edge case for time delta)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
            (datetime(2025, 1, 15, 10, 0), 26.0),
        ]
        img = _draw_graph_component(
            "Test Sensor", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_long_title(self):
        """Test drawing graph with very long title."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
            (datetime(2025, 1, 15, 11, 0), 26.0),
        ]
        img = _draw_graph_component(
            "A" * 100, data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)

    def test_dotted_tail_drawn_when_last_point_before_window_end(self):
        """A stale entity gets a dashed hold line in the right portion of the plot."""
        from datetime import datetime
        # Last reading at 10:00, window ends at 16:00 -> long flat tail on the right.
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), 20.0),
        ]
        img = _draw_graph_component(
            "Stale", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        # Compare against the same data with the last point AT window_end (no gap to hold).
        img_no_gap = _draw_graph_component(
            "Stale", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 20.0),
            ], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        from PIL import ImageChops
        self.assertIsNotNone(
            ImageChops.difference(img, img_no_gap).getbbox(),
            "expected the dotted hold tail to change the image",
        )

    def test_fully_stale_only_boundary_point(self):
        """A single point well before window_end still renders (flat dotted hold)."""
        from datetime import datetime
        data_points = [(datetime(2025, 1, 15, 8, 0), 42.0)]
        img = _draw_graph_component(
            "Dead", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
```

- [ ] **Step 2: Run these tests to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestDrawGraphComponent -q`
Expected: FAIL — `TypeError: _draw_graph_component() got an unexpected keyword argument 'window_start'`.

- [ ] **Step 3: Change `_draw_graph_component` to use the fixed window and draw the tail**

In `src/trmnl_server/components.py`, update the signature from:

```python
def _draw_graph_component(
    friendly_name: str,
    data_points: list[tuple[datetime, float]],
    width: int,
    height: int,
    logger: "Logger",
) -> Image.Image:
```

to:

```python
def _draw_graph_component(
    friendly_name: str,
    data_points: list[tuple[datetime, float]],
    width: int,
    height: int,
    logger: "Logger",
    *,
    window_start: datetime,
    window_end: datetime,
) -> Image.Image:
```

Replace the time-bounds block. Currently:

```python
    times, values = zip(*data_points)
    min_time: datetime = min(times)
    max_time: datetime = max(times)
    min_val: float = min(values)
    max_val: float = max(values)
```

with (use the fixed window for time, keep values for the y-range):

```python
    times, values = zip(*data_points)
    min_time: datetime = window_start
    max_time: datetime = window_end
    min_val: float = min(values)
    max_val: float = max(values)
```

Update `to_coords` to clamp x into the plot area (the HA boundary point can predate `window_start`). Replace:

```python
    def to_coords(t: datetime, v: float) -> tuple[float, float]:
        x: float = margin + ((t - min_time) / time_delta) * graph_width
        y: float = (large_height - margin) - ((v - min_val) / (max_val - min_val)) * graph_height
        return x, y
```

with:

```python
    def to_coords(t: datetime, v: float) -> tuple[float, float]:
        x: float = margin + ((t - min_time) / time_delta) * graph_width
        x = max(float(margin), min(x, float(margin + graph_width)))
        y: float = (large_height - margin) - ((v - min_val) / (max_val - min_val)) * graph_height
        return x, y
```

Finally, add the dotted hold tail. The function currently ends with:

```python
    # Draw data line
    points_coords: list[tuple[float, float]] = [to_coords(t, v) for t, v in data_points]
    if len(points_coords) > 1:
        d.line(points_coords, fill='black', width=4 * scale)

    return img.resize((width, height), Image.LANCZOS)
```

Replace that block with:

```python
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

    return img.resize((width, height), Image.LANCZOS)
```

(`last_value` is already defined earlier in the function as `values[-1]`.)

- [ ] **Step 4: Update `_render_component` to pass the window through**

In `src/trmnl_server/components.py`, the `_render_component` inner function dispatches history graphs. Replace its `history_graph` branch:

```python
        elif component_type == 'history_graph':
            return _draw_graph_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
```

with:

```python
        elif component_type == 'history_graph':
            window_end_val = render_data.get('window_end')
            window_start_val = render_data.get('window_start')
            if window_start_val is None or window_end_val is None:
                window_end_val = datetime.now().astimezone()
                window_start_val = window_end_val - timedelta(hours=24)
            return _draw_graph_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                window_start=window_start_val,
                window_end=window_end_val,
            )
```

- [ ] **Step 5: Run the graph unit tests, then the full suite**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestDrawGraphComponent -q`
Expected: 6 passed.

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `123 passed` (121 + 2 net new graph tests). If a golden mismatch appears for `history_graph_dashboard` (axis changed), regenerate once:
```
UPDATE_GOLDEN=1 uv run --with pytest --with pyyaml pytest tests/test_golden.py -q
uv run --with pytest --with pyyaml pytest -q
```
Expected: `123 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Fixed-window x-axis with dotted hold-last-value tail

History graphs now span [now - hours, now] and hold the last received
value forward as a dashed line when an entity has stopped reporting.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Golden coverage + config example + docs

**Files:**
- Test: `tests/test_golden.py` (two new golden tests)
- Modify: `examples/config.yaml`, `README.md`, `AGENTS.md`

- [ ] **Step 1: Add golden tests for normal and stale graphs**

In `tests/test_golden.py`, add these two tests inside `class TestGoldenImages` (after `test_history_graph_dashboard`):

```python
    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_stale_tail(self, mock_fetch_history):
        """Entity stopped reporting 12h before now -> long dotted hold tail."""
        mock_fetch_history.return_value = [[
            {'state': '18.0', 'last_changed': '2024-01-15T06:00:00+00:00'},
            {'state': '19.5', 'last_changed': '2024-01-15T08:00:00+00:00'},
            {'state': '21.0', 'last_changed': '2024-01-15T10:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'stale',
            'title': 'Stale Sensor',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Temperature',
                 'type': 'history_graph', 'hours': 24},
            ],
        }
        # Last reading 10:00; now 22:00 -> 12h dotted tail inside a 24h window.
        fixed_now = datetime(2024, 1, 15, 22, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_stale_tail')

    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_custom_hours(self, mock_fetch_history):
        """A 6h window with a recent reading renders a short tail."""
        mock_fetch_history.return_value = [[
            {'state': '60', 'last_changed': '2024-01-15T17:00:00+00:00'},
            {'state': '62', 'last_changed': '2024-01-15T18:30:00+00:00'},
            {'state': '59', 'last_changed': '2024-01-15T20:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'recent',
            'title': 'Recent',
            'components': [
                {'entity_name': 'sensor.humidity', 'friendly_name': 'Humidity',
                 'type': 'history_graph', 'hours': 6},
            ],
        }
        fixed_now = datetime(2024, 1, 15, 20, 30, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_custom_hours')
```

- [ ] **Step 2: Generate and verify the new goldens**

Run: `UPDATE_GOLDEN=1 uv run --with pytest --with pyyaml pytest tests/test_golden.py -q`
Then verify they reproduce deterministically (second run compares):
Run: `uv run --with pytest --with pyyaml pytest tests/test_golden.py -q`
Expected: all golden tests pass (deterministic — windows are fixed via `now`).

- [ ] **Step 3: Manually eyeball the stale golden (sanity)**

Run: `python3 -c "from PIL import Image; im=Image.open('tests/golden/history_graph_stale_tail.png'); print('size', im.size)"`
Expected: prints `size (800, 480)`. (Optional visual check: open the PNG and confirm the right ~half of the temperature graph is a dashed horizontal line.)

- [ ] **Step 4: Document `hours` in the example config**

In `examples/config.yaml`, find the first `type: history_graph` entry (around line 103) and add an annotated `hours` example. Change:

```yaml
        type: history_graph
```

(the first occurrence, for `sensor.sensor_name`) to:

```yaml
        type: history_graph
        # Optional: width of the rolling time window in hours (default: 24).
        # The graph's right edge is always "now"; once an entity stops
        # reporting, its last value is held forward as a dotted line.
        hours: 12
```

- [ ] **Step 5: Document `hours` in README.md**

In `README.md`, in the configuration documentation for components (near the `history_graph` description), add a line describing the option. Add this bullet/line where component options are described:

```markdown
- `hours` (history_graph only, optional): width of the rolling time window in hours. Default `24`. The x-axis always ends at the current time; when an entity stops reporting, its last value is held forward as a dotted line.
```

- [ ] **Step 6: Document `hours` in AGENTS.md**

In `AGENTS.md`, the `## API Endpoints` / component notes do not list per-component options; add a short note under a relevant section (e.g., near the config description) so future agents know the field exists:

```markdown
- `history_graph` components accept an optional `hours` field (default 24) controlling the rolling window width; stale entities hold their last value as a dotted line to "now".
```

- [ ] **Step 7: Run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `125 passed` (123 + 2 new golden tests).

- [ ] **Step 8: Commit**

```bash
git add tests/test_golden.py examples/config.yaml README.md AGENTS.md
git commit -m "test: Golden coverage for dotted tail; document hours option

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Full suite:** `uv run --with pytest --with pyyaml pytest -q` → `125 passed`.
- [ ] **No accidental wall-clock dependence in goldens:** run the suite twice in a row; golden tests pass both times (deterministic).
- [ ] **Behavior smoke (real draw):**
  ```
  PYTHONPATH=src python3 -c "
  from datetime import datetime, timezone, timedelta
  import logging
  from trmnl_server.components import _draw_graph_component
  now = datetime(2024,1,15,22,0,tzinfo=timezone.utc)
  pts = [(datetime(2024,1,15,8,0,tzinfo=timezone.utc), 20.0),
         (datetime(2024,1,15,10,0,tzinfo=timezone.utc), 21.0)]
  img = _draw_graph_component('T', pts, 400, 300, logging.getLogger(),
        window_start=now-timedelta(hours=24), window_end=now)
  print('rendered', img.size)
  "
  ```
  Expected: `rendered (400, 300)` with no exception.
- [ ] **Tree clean** after the four commits; `git status` clean.

## Notes / Out of Scope

- No global/per-dashboard window default (per-component `hours` only).
- No leading dotted line for data that starts late (trailing hold only).
- No staleness threshold (a trailing dotted segment always exists but is only visible when meaningful).
- Golden PNGs remain gitignored (`*.png`); regeneration produces no commit.
