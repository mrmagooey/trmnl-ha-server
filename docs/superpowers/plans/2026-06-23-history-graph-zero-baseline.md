# History Graph Zero-Baseline (Bipolar) Variant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `zero_baseline` flag to the existing `history_graph` component that draws an in-graph zero reference line, so values that swing positive and negative read against a clear zero.

**Architecture:** Extend the single renderer `_draw_graph_component` with a keyword-only `zero_baseline: bool = False` parameter. When true, widen the value range to include 0, draw a thin horizontal zero line, and force a labeled `0` y-tick. Thread the flag from `ComponentConfig` → `RenderData` → the `history_graph` dispatch branch. The default (flag-off) path stays byte-for-byte identical to today.

**Tech Stack:** Python 3.12, Pillow (PIL) for hand-rolled drawing, `unittest` + pytest, pixel-comparison golden tests.

## Global Constraints

- Field name is exactly **`zero_baseline`**, type `bool`, default `false`.
- The component `type` stays `history_graph`; do **not** add to `VALID_COMPONENT_TYPES`.
- Default/flag-off rendering must remain **byte-for-byte identical** — existing golden files (`tests/golden/history_graph_*.png`) must not change.
- Drawing weights (with `scale = 2`): data line `4 * scale` (8px); bottom/left axes `scale * 2` (4px); **zero line `scale` (2px)** — strictly thinner than the axes.
- Value range when flag on: `min_val = min(0.0, min(values))`, `max_val = max(0.0, max(values))`, then the existing `if max_val == min_val: max_val += 1; min_val -= 1` guard runs.
- The forced `0` y-tick must not double-draw if an evenly-spaced tick already lands on `0`.
- All three test levels (unit, integration, golden) per the repo test policy.

---

### Task 1: Add `zero_baseline` to the config and render-data types

**Files:**
- Modify: `src/trmnl_server/models.py:43-53` (`ComponentConfig`)
- Modify: `src/trmnl_server/models.py:139-148` (`RenderData`)

**Interfaces:**
- Consumes: nothing (pure type change).
- Produces: `ComponentConfig` gains optional `zero_baseline: bool`; `RenderData` gains `zero_baseline: NotRequired[bool]`. Later tasks read these keys.

Both are `TypedDict`s. `ComponentConfig` is `total=False` (all keys optional already). `RenderData` uses `Required`/`NotRequired` explicitly, so the new key must be `NotRequired[bool]`. `NotRequired` is already imported in this file (used by `RenderData`).

- [ ] **Step 1: Add the field to `ComponentConfig`**

In `src/trmnl_server/models.py`, add `zero_baseline: bool` to `ComponentConfig` (after `hours: int`):

```python
class ComponentConfig(TypedDict, total=False):
    """Configuration for a single dashboard component."""
    entity_name: str
    attribute: str
    friendly_name: str
    type: Literal["history_graph", "entity", "calendar", "entities", "todo_list"]
    arguments: CalendarArguments
    entities: list[EntityItem]
    large_display: bool
    columns: int
    hours: int
    zero_baseline: bool
```

- [ ] **Step 2: Add the field to `RenderData`**

In the same file, add `zero_baseline: NotRequired[bool]` to `RenderData` (after `todo_key`):

```python
class RenderData(TypedDict, total=False):
    """Data structure for component rendering pipeline."""
    type: Required[str]
    friendly_name: Required[str]
    data: Required[object]
    large_display: Required[bool]
    window_start: NotRequired[datetime]
    window_end: NotRequired[datetime]
    columns: NotRequired[int]
    todo_key: NotRequired[str]
    zero_baseline: NotRequired[bool]
```

- [ ] **Step 3: Verify the package still imports**

Run: `cd /home/peter/projects/trmnl-ha-server && python -c "import trmnl_server.models"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
cd /home/peter/projects/trmnl-ha-server
git add src/trmnl_server/models.py
git commit -m "feat: Add zero_baseline field to component config types"
```

---

### Task 2: Render the zero baseline in `_draw_graph_component`

**Files:**
- Modify: `src/trmnl_server/components.py:157-345` (`_draw_graph_component`)
- Test: `tests/test_components.py` (class `TestDrawGraphComponent`, append new tests)

**Interfaces:**
- Consumes: nothing from other tasks (renderer is self-contained).
- Produces: new keyword-only parameter on the renderer:
  `_draw_graph_component(friendly_name, data_points, width, height, logger, *, window_start, window_end, zero_baseline: bool = False) -> Image.Image`.
  Task 3 calls it with `zero_baseline=...`.

Reference — current relevant regions of `_draw_graph_component`:
- Signature at lines 157-166 (keyword-only block after `*,`).
- Range computation at lines 245-251:
  ```python
  min_val: float = min(values)
  max_val: float = max(values)
  if max_val == min_val:
      max_val += 1
      min_val -= 1
  ```
- Y-axis label loop at lines 270-286.
- `to_coords` helper at lines 310-314 (do **not** change its formula).

This task is TDD: write the failing tests first, then implement.

- [ ] **Step 1: Write failing unit tests**

Append to `class TestDrawGraphComponent` in `tests/test_components.py`:

```python
    def test_zero_baseline_default_off_unchanged(self):
        """Omitting zero_baseline renders identically to passing it False."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 5.0),
            (datetime(2025, 1, 15, 10, 0), 8.0),
        ]
        kwargs = dict(
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        default = _draw_graph_component("S", data_points, 400, 300, mock_logger, **kwargs)
        explicit_off = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger, zero_baseline=False, **kwargs
        )
        self.assertIsNone(
            ImageChops.difference(default, explicit_off).getbbox(),
            "default path must equal zero_baseline=False",
        )

    def test_zero_baseline_changes_bipolar_rendering(self):
        """For data crossing zero, the flag changes the rendered image."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -10.0),
            (datetime(2025, 1, 15, 10, 0), 10.0),
        ]
        kwargs = dict(
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        off = _draw_graph_component("S", data_points, 400, 300, mock_logger, **kwargs)
        on = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger, zero_baseline=True, **kwargs
        )
        self.assertIsNotNone(
            ImageChops.difference(off, on).getbbox(),
            "zero_baseline must change rendering for bipolar data",
        )

    def test_zero_baseline_draws_horizontal_line_near_mid(self):
        """Symmetric data (-10..+10) puts the zero line near vertical centre,
        spanning most of the plot width as a near-continuous black row."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -10.0),
            (datetime(2025, 1, 15, 9, 30), 0.0),
            (datetime(2025, 1, 15, 10, 0), 10.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        w, h = img.size  # (400, 300)
        # Scan the central horizontal band for a row that is mostly black across
        # the plot width (the zero line spans the full graph width).
        def black(px):
            return sum(px) < 240
        best = 0
        for y in range(int(h * 0.35), int(h * 0.65)):
            count = sum(
                1 for x in range(int(w * 0.15), int(w * 0.80))
                if black(img.getpixel((x, y)))
            )
            best = max(best, count)
        span = int(w * 0.80) - int(w * 0.15)
        self.assertGreater(
            best, span * 0.6,
            "expected a near-continuous horizontal zero line in the central band",
        )

    def test_zero_baseline_all_positive_includes_zero(self):
        """All-positive data with the flag on still renders (floor pulled to 0)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 5.0),
            (datetime(2025, 1, 15, 10, 0), 9.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_zero_baseline_all_negative_includes_zero(self):
        """All-negative data with the flag on still renders (ceiling pulled to 0)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -5.0),
            (datetime(2025, 1, 15, 10, 0), -9.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_zero_baseline_flat_at_zero(self):
        """A flat line at exactly 0 with the flag on renders without error."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 0.0),
            (datetime(2025, 1, 15, 10, 0), 0.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest tests/test_components.py -k zero_baseline -v`
Expected: FAIL — `_draw_graph_component()` got an unexpected keyword argument `'zero_baseline'`.

- [ ] **Step 3: Add the parameter to the signature**

In `src/trmnl_server/components.py`, change the `_draw_graph_component` signature (lines 157-166) to add the keyword-only param and document it:

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
    zero_baseline: bool = False,
) -> Image.Image:
```

Add to the docstring Args (after the `window_end` line, ~line 176):

```python
        zero_baseline: When True, include 0 in the value range and draw a thin
            horizontal zero reference line with a labeled 0 y-tick.
```

- [ ] **Step 4: Widen the value range when the flag is on**

Replace the range computation at lines 245-251:

```python
    min_val: float = min(values)
    max_val: float = max(values)

    # Avoid division by zero
    if max_val == min_val:
        max_val += 1
        min_val -= 1
```

with:

```python
    min_val: float = min(values)
    max_val: float = max(values)

    # Bipolar variant: anchor the range so 0 is always inside it.
    if zero_baseline:
        min_val = min(0.0, min_val)
        max_val = max(0.0, max_val)

    # Avoid division by zero
    if max_val == min_val:
        max_val += 1
        min_val -= 1
```

- [ ] **Step 5: Force a labeled `0` y-tick when the flag is on**

The y-label loop is at lines 270-286. After that loop ends (immediately after the `d.line([(margin - (5 * scale), y), (margin, y)], fill='black', width=scale)` at line 286), add a forced zero tick that reuses the same label/tick drawing, skipping it if an evenly-spaced tick already landed on 0:

```python
    # Bipolar variant: guarantee a labeled "0" tick (unless one already lands on 0).
    if zero_baseline:
        existing_tick_vals = [
            min_val + (max_val - min_val) * i / num_y_labels
            for i in range(num_y_labels + 1)
        ]
        if not any(abs(v) < 1e-9 for v in existing_tick_vals):
            zero_y: float = (large_height - margin) - (
                (0.0 - min_val) / (max_val - min_val)
            ) * graph_height
            zlabel: str = "0.0"
            ztext_bbox = d.textbbox((0, 0), zlabel, font=font_axes)
            ztext_width: int = ztext_bbox[2] - ztext_bbox[0]
            ztext_height: int = ztext_bbox[3] - ztext_bbox[1]
            d.text(
                (margin - ztext_width - (5 * scale), zero_y - ztext_height / 2),
                zlabel,
                font=font_axes,
                fill='black',
            )
            d.line(
                [(margin - (5 * scale), zero_y), (margin, zero_y)],
                fill='black',
                width=scale,
            )
```

- [ ] **Step 6: Draw the thin zero line across the plot when the flag is on**

The `to_coords` helper is defined at lines 310-314. Immediately **after** its definition (before "Display last value" at line 316), add the zero line so it sits under the data line (drawn later at line 327-329):

```python
    # Bipolar variant: thin horizontal reference line at value 0, spanning the
    # plot width. Thinner (width=scale) than the axes (scale * 2) and the data
    # line (4 * scale) so the visual hierarchy reads data > axes > zero line.
    if zero_baseline:
        _zx0, zero_line_y = to_coords(min_time, 0.0)
        d.line(
            [(margin, zero_line_y), (margin + graph_width, zero_line_y)],
            fill='black',
            width=scale,
        )
```

Note: `to_coords` clamps x to `[margin, margin + graph_width]`; we pass explicit x endpoints (`margin` and `margin + graph_width`) and take only the y from `to_coords`.

- [ ] **Step 7: Run the new unit tests to verify they pass**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest tests/test_components.py -k zero_baseline -v`
Expected: PASS (all 6 new tests).

- [ ] **Step 8: Run the full unit + golden suite to confirm no regressions**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest tests/test_components.py tests/test_golden.py -v`
Expected: PASS — in particular the existing `test_history_graph_*` golden tests are unchanged (default path untouched).

- [ ] **Step 9: Commit**

```bash
cd /home/peter/projects/trmnl-ha-server
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Draw zero baseline reference line in history graph"
```

---

### Task 3: Thread `zero_baseline` through dispatch and dashboard assembly

**Files:**
- Modify: `src/trmnl_server/components.py:875-889` (`history_graph` branch of `_render_component`)
- Modify: `src/trmnl_server/components.py:1034-1047` (`history_graph` branch of `render_dashboard_image`)
- Test: `tests/test_components.py` (integration test of the dispatch + assembly)

**Interfaces:**
- Consumes: `_draw_graph_component(..., zero_baseline=...)` from Task 2; `RenderData['zero_baseline']` and `ComponentConfig['zero_baseline']` from Task 1.
- Produces: end-to-end wiring so a dashboard component with `zero_baseline: true` reaches the renderer.

- [ ] **Step 1: Write the failing integration test**

Append a new test class to `tests/test_components.py`:

```python
class TestZeroBaselineDispatch(unittest.TestCase):
    """Integration: zero_baseline flows from config through dispatch to render."""

    def test_zero_baseline_flows_from_config_to_render(self):
        """A history_graph config with zero_baseline=True reaches the renderer."""
        from datetime import datetime, timezone
        with mock.patch(
            'trmnl_server.components._draw_graph_component'
        ) as mock_draw:
            mock_draw.return_value = Image.new('RGB', (10, 10), 'white')
            with mock.patch(
                'trmnl_server.hass_client._fetch_history'
            ) as mock_fetch:
                mock_fetch.return_value = [[
                    {'state': '-5', 'last_changed': '2024-01-15T09:00:00+00:00'},
                    {'state': '5', 'last_changed': '2024-01-15T10:00:00+00:00'},
                ]]
                dashboard = {
                    'name': 'bp',
                    'components': [{
                        'entity_name': 'sensor.net_power',
                        'friendly_name': 'Net Power',
                        'type': 'history_graph',
                        'zero_baseline': True,
                    }],
                }
                fixed_now = datetime(2024, 1, 15, 11, 0, tzinfo=timezone.utc)
                render_dashboard_image(dashboard, mock_logger, now=fixed_now)

        self.assertTrue(mock_draw.called, "_draw_graph_component should be called")
        _, kwargs = mock_draw.call_args
        self.assertTrue(
            kwargs.get('zero_baseline'),
            "zero_baseline=True must be forwarded to the renderer",
        )

    def test_zero_baseline_defaults_false_when_absent(self):
        """Without the flag, the renderer receives zero_baseline False/absent."""
        from datetime import datetime, timezone
        with mock.patch(
            'trmnl_server.components._draw_graph_component'
        ) as mock_draw:
            mock_draw.return_value = Image.new('RGB', (10, 10), 'white')
            with mock.patch(
                'trmnl_server.hass_client._fetch_history'
            ) as mock_fetch:
                mock_fetch.return_value = [[
                    {'state': '1', 'last_changed': '2024-01-15T09:00:00+00:00'},
                    {'state': '2', 'last_changed': '2024-01-15T10:00:00+00:00'},
                ]]
                dashboard = {
                    'name': 'bp',
                    'components': [{
                        'entity_name': 'sensor.temp',
                        'friendly_name': 'Temp',
                        'type': 'history_graph',
                    }],
                }
                fixed_now = datetime(2024, 1, 15, 11, 0, tzinfo=timezone.utc)
                render_dashboard_image(dashboard, mock_logger, now=fixed_now)

        _, kwargs = mock_draw.call_args
        self.assertFalse(
            kwargs.get('zero_baseline', False),
            "zero_baseline must default to False when not configured",
        )
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest tests/test_components.py::TestZeroBaselineDispatch -v`
Expected: FAIL — `test_zero_baseline_flows_from_config_to_render` fails because `zero_baseline` is not forwarded (kwarg missing/None).

- [ ] **Step 3: Carry the flag in `RenderData` during dashboard assembly**

In `render_dashboard_image`, per-component locals are initialized around lines 1031-1032 (`graph_window`, `todo_meta`, both default `None`) and the `RenderData` dict (`render_entry`) is assembled at lines 1100-1112, where optional keys are set conditionally (e.g. `if graph_window is not None: render_entry['window_start'] = ...`). Mirror that pattern with a dedicated local.

First, add a local initializer next to `graph_window`/`todo_meta` (lines 1031-1032):

```python
        graph_zero_baseline: bool = False
```

Then, inside the `history_graph` branch, after `data = _process_history_to_points(history)` (line 1047), capture the config value:

```python
            graph_zero_baseline = bool(component.get('zero_baseline', False))
```

Finally, in the `render_entry` assembly block (after the `if graph_window is not None:` block at lines 1106-1108), add:

```python
        if graph_zero_baseline:
            render_entry['zero_baseline'] = True
```

This keeps the key absent for non-graph components and for graphs that don't set it, matching the existing conditional-key style. The key is `NotRequired[bool]`, so absence is valid.

- [ ] **Step 4: Forward the flag in the dispatch branch**

In `_render_component`, the `history_graph` branch (lines 875-889), read the flag from `render_data` and pass it to `_draw_graph_component`:

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
                zero_baseline=bool(render_data.get('zero_baseline', False)),
            )
```

- [ ] **Step 5: Run the integration tests to verify they pass**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest tests/test_components.py::TestZeroBaselineDispatch -v`
Expected: PASS (both tests).

- [ ] **Step 6: Run the full suite**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
cd /home/peter/projects/trmnl-ha-server
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Wire zero_baseline from dashboard config to graph renderer"
```

---

### Task 4: Golden (e2e) test for the bipolar graph

**Files:**
- Modify: `tests/test_golden.py` (add one test method in `TestGoldenImages`)
- Create: `tests/golden/history_graph_bipolar.png` (generated via `UPDATE_GOLDEN=1`)

**Interfaces:**
- Consumes: `render_dashboard_image`, `assert_golden`, `mock_datetime` (already in `tests/test_golden.py`); the `zero_baseline` config key from Tasks 1/3.
- Produces: a committed golden image exercising the full pipeline for bipolar data.

- [ ] **Step 1: Add the golden test method**

Append to `class TestGoldenImages` in `tests/test_golden.py` (follow the existing `test_history_graph_*` pattern; use deterministic UTC timestamps and a fixed `now`):

```python
    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_bipolar(self, mock_fetch_history):
        """A zero_baseline graph for data spanning negative to positive values."""
        mock_fetch_history.return_value = [[
            {'state': '-8.0', 'last_changed': '2024-01-15T08:00:00+00:00'},
            {'state': '-3.0', 'last_changed': '2024-01-15T10:00:00+00:00'},
            {'state': '2.0', 'last_changed': '2024-01-15T12:00:00+00:00'},
            {'state': '6.0', 'last_changed': '2024-01-15T14:00:00+00:00'},
            {'state': '-1.0', 'last_changed': '2024-01-15T16:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'netpower',
            'title': 'Net Power',
            'components': [
                {'entity_name': 'sensor.net_power', 'friendly_name': 'Net Power',
                 'type': 'history_graph', 'zero_baseline': True, 'hours': 24},
            ],
        }
        fixed_now = datetime(2024, 1, 15, 17, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_bipolar')
```

- [ ] **Step 2: Generate the golden image**

Run: `cd /home/peter/projects/trmnl-ha-server && UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py::TestGoldenImages::test_history_graph_bipolar -v`
Expected: PASS; `tests/golden/history_graph_bipolar.png` created.

- [ ] **Step 3: Visually sanity-check the generated golden**

Open `tests/golden/history_graph_bipolar.png` and confirm: a thin horizontal zero line crosses the plot, the data line goes below it (negative) and above it (positive), and a `0.0` tick is labeled on the y-axis. If it looks wrong, fix Task 2 before continuing (delete the png, re-run with `UPDATE_GOLDEN=1`).

- [ ] **Step 4: Re-run without UPDATE to confirm the comparison passes**

Run: `cd /home/peter/projects/trmnl-ha-server && python -m pytest tests/test_golden.py -v`
Expected: PASS — new bipolar golden matches, all existing goldens unchanged.

- [ ] **Step 5: Commit**

```bash
cd /home/peter/projects/trmnl-ha-server
git add tests/test_golden.py tests/golden/history_graph_bipolar.png
git commit -m "test: Add golden image for zero_baseline history graph"
```

---

### Task 5: Document the `zero_baseline` flag

**Files:**
- Modify: `README.md:111` (component-options list, near the `hours` bullet)
- Modify: `CHANGELOG.md` (add an entry under an Unreleased/next section if that is the file's convention)

**Interfaces:**
- Consumes: nothing.
- Produces: user-facing docs for the flag.

- [ ] **Step 1: Add a README bullet**

In `README.md`, directly after the `hours` bullet (line 111), add:

```markdown
- `zero_baseline` (history_graph only, optional): when `true`, the graph includes 0 in its value range and draws a thin horizontal reference line at 0, with a labeled `0` on the y-axis. Use this for values that go both positive and negative (e.g. net power import/export) so you can see at a glance which side of zero the line is on. Default `false`.
```

- [ ] **Step 2: Add a CHANGELOG entry**

Read `CHANGELOG.md` first to match its format. Add an entry describing: "history_graph: optional `zero_baseline` flag draws an in-graph zero reference line for values that span positive and negative." Place it under the appropriate next-version / Unreleased heading per the file's existing convention.

- [ ] **Step 3: Verify docs reference the correct flag name**

Run: `cd /home/peter/projects/trmnl-ha-server && grep -rn "zero_baseline" README.md CHANGELOG.md`
Expected: the flag name appears in both files, spelled exactly `zero_baseline`.

- [ ] **Step 4: Commit**

```bash
cd /home/peter/projects/trmnl-ha-server
git add README.md CHANGELOG.md
git commit -m "docs: Document history_graph zero_baseline flag"
```

---

## Final Verification

- [ ] Run the complete test suite: `cd /home/peter/projects/trmnl-ha-server && python -m pytest -v`
  Expected: all pass, including unchanged existing golden images.
- [ ] Confirm the default path is untouched: `git diff --stat main` shows changes only in `models.py`, `components.py`, `tests/`, `README.md`, `CHANGELOG.md`, and the new golden png.
- [ ] Confirm no new entry was added to `VALID_COMPONENT_TYPES` (`grep -n VALID_COMPONENT_TYPES src/trmnl_server/config.py` and verify the set is unchanged).
