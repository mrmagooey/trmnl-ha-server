# History Graph — Zero-Baseline (Bipolar) Variant

**Date:** 2026-06-23
**Status:** Approved design, pending implementation plan

## Problem

The current history graph (`_draw_graph_component` in
`src/trmnl_server/components.py`) scales its y-axis to the data's
`min_val…max_val` and draws the x-axis along the bottom edge. For sensors
whose values swing between positive and negative (e.g. a power balance that
is sometimes import, sometimes export; temperature deltas; net flow), there
is no visual reference for zero — the line just wanders, and you cannot tell
at a glance whether the current value is above or below zero.

This design adds an opt-in variant that draws a **zero reference line**
inside the graph, so positive values sit above it and negative values below.

## Goals

- Let a user opt a single `history_graph` into a zero-baseline rendering via a
  config flag.
- Always show a horizontal zero line and a labeled `0` tick when the flag is
  on.
- Make full use of the limited e-ink vertical space (proportional, not forced
  symmetric).
- Leave the default (flag-off) rendering **byte-for-byte identical** to today.

## Non-goals

- No new component `type` (the existing `history_graph` is reused).
- No symmetric `-M…+M` scaling, no per-region shading/fill, no color (the
  target is a 1-bit e-ink display).
- No change to data fetching or `_process_history_to_points`.

## Configuration

A new optional boolean on the existing component type:

```yaml
- type: history_graph
  entity_name: sensor.power_balance
  zero_baseline: true    # NEW — opt-in, default false
  hours: 24
```

- **Field name:** `zero_baseline` (`bool`, default `false`).
- Added to `ComponentConfig` (`src/trmnl_server/models.py:43`).
- Threaded through `RenderData` (`src/trmnl_server/models.py:139`) as
  `zero_baseline: NotRequired[bool]` so the dispatcher can pass it to the
  renderer.
- `type` stays `history_graph`; `VALID_COMPONENT_TYPES` is **unchanged**.
- When `false`/absent → identical to current behavior.

## Rendering behavior

`_draw_graph_component` stays the single entry point and gains a keyword-only
parameter `zero_baseline: bool = False`. The axis/label/line/stale-tail
machinery is shared; only the differences below are gated on the flag. (No
second function — duplicating ~190 lines would create two maintenance sites.)

When `zero_baseline` is **true**:

1. **Value range** — instead of `min(values)…max(values)`, the range becomes:
   ```python
   min_val = min(0.0, min(values))
   max_val = max(0.0, max(values))
   ```
   This guarantees `0` is within the drawn range (zero-anchored, proportional
   — Section-2 decision "B"). All-positive data pulls the floor to 0;
   all-negative data pulls the ceiling to 0. The existing
   `if max_val == min_val: max_val += 1; min_val -= 1` guard still runs
   afterward (covers flat-at-zero / single-point).

2. **Zero line** — a solid horizontal line at the y-pixel of value `0`,
   spanning the graph width (`margin` → `margin + graph_width`), drawn at
   width **`scale`** (2px). This is deliberately *thinner* than the bottom/left
   axes (`scale * 2` = 4px) and much thinner than the data line (`4 * scale` =
   8px), giving an unambiguous visual hierarchy:
   data line > axes > zero line.

3. **Y-axis ticks** — same even spacing across the new range, **plus** a forced
   labeled tick at value `0` (so the zero gridline is always readable).
   Negative labels render below the zero line, positive above. The forced `0`
   tick must not double-draw if an evenly-spaced tick already lands on 0.

4. **X (time) labels** — unchanged; stay along the bottom edge.

5. **Last-value text and dashed stale-tail** — unchanged; they key off
   `to_coords`, which now simply maps a wider range.

Everything else (2× antialias scale, margins, fonts, LANCZOS downsize) is
untouched. The `to_coords` y-formula
`(large_height - margin) - ((v - min_val) / (max_val - min_val)) * graph_height`
needs no change — widening `min_val/max_val` to include 0 makes it place the
zero line correctly on its own.

## Dispatch

In `tile_components()` (`src/trmnl_server/components.py`, the
`history_graph` branch) read `zero_baseline` from `render_data` (default
`False`) and pass it through to `_draw_graph_component`. In
`render_dashboard_image()` where `RenderData` is assembled for a
`history_graph` component, copy `zero_baseline` from the `ComponentConfig`.

## Edge cases

- **All-positive** + flag on → floor pulled to 0; zero line coincides with the
  bottom axis. Correct; reads as a normal 0-anchored graph.
- **All-negative** + flag on → ceiling pulled to 0; zero line at the top.
- **Flat at exactly 0 / single point** → `min_val == max_val == 0`, the `±1`
  guard makes range `-1…1`, zero line lands mid-graph.
- **No data** → existing "No numeric data" message path; flag has no effect.
- **Same timestamp / single point** → identical to today.

## Testing

Per the three-level policy:

- **Unit** (`tests/test_components.py`):
  - data crossing zero with `zero_baseline=True` → assert a horizontal line is
    drawn at the expected zero y-pixel, and that it is thinner than the axes;
  - all-positive, all-negative, flat-at-zero with the flag on;
  - regression: default path (flag off / omitted) renders exactly as before.
- **Integration** (`tests/test_components.py`, dispatch level):
  - `zero_baseline` parsed from `ComponentConfig` into `RenderData`;
  - a `RenderData` carrying `zero_baseline=True` routes through
    `tile_components()` and renders without error.
- **E2E / golden** (`tests/test_golden.py`):
  - new golden `tests/golden/history_graph_bipolar.png` from a sensor history
    spanning negative→positive, using **deterministic** timestamps (per fix
    `0a2c9f5`);
  - existing golden files must remain byte-identical (regression guard that
    the default path did not move).

## Files touched

- `src/trmnl_server/models.py` — `ComponentConfig`, `RenderData`.
- `src/trmnl_server/components.py` — `_draw_graph_component` (new kwarg +
  gated logic), `tile_components` dispatch, `render_dashboard_image` assembly.
- `tests/test_components.py` — unit + integration cases.
- `tests/test_golden.py` + `tests/golden/history_graph_bipolar.png` — golden.
- Docs: document the `zero_baseline` flag wherever the other `history_graph`
  options are documented.
