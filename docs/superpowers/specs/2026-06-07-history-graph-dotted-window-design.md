# History Graph: Fixed Time Window with Dotted "Hold Last Value" Tail — Design

**Date:** 2026-06-07
**Status:** Approved (pending spec review)

## Goal

Make `history_graph` components advance their time axis to "now" on every
render, even when an entity has stopped reporting. When there are no
measurements between the last reading and "now", hold the last received value
forward as a horizontal **dotted** line, signalling stale/projected data.

## Problem (current behavior)

`_draw_graph_component` derives the x-axis from the data itself
(`min_time = min(times)`, `max_time = max(times)`). So when an entity stops
reporting, the right edge freezes at the last reading — the graph stops
"advancing" and there is no visual indication the data is stale.

## Decisions (locked via brainstorming)

- **Window model:** fixed rolling window of `hours`, right edge = render time
  ("now"). Both edges move; data older than the window scrolls off the left.
- **Config:** new optional per-component `hours: int`; default **24** when
  omitted or invalid.
- **Stale tail:** horizontal dotted line holding the last received value, from
  the last real measurement to the right edge.
- **Dotted styling:** black, same thickness as the solid line, ~12px-on /
  8px-off dashes (at 2× internal scale).
- **Fetch:** fetch exactly `[now − hours, now]` from Home Assistant (not the
  default window + clip).
- **Leading gap:** if data starts partway into the window, leave the left part
  blank — only the *trailing* gap gets the dotted hold (no leading dotted line).

## Data path (unchanged shape)

`_fetch_history(entity)` → `_process_history_to_points()` →
`list[tuple[datetime, float]]` → `_draw_graph_component()`.
The orchestration loop lives in `render_dashboard_image` in
`src/trmnl_server/components.py`.

## Changes

### 1. Config schema (`models.py`)

Add to `ComponentConfig` (which is `total=False`):

```python
    hours: int
```

Resolution rule (applied where the component is processed): read
`component.get('hours', 24)`; if the value is not a positive int, log once and
use `24`.

### 2. Single render timestamp

In `render_dashboard_image`, capture one timezone-aware `now` at the top of the
render pass and use it for every graph on the dashboard, so all graphs share an
identical right edge. For each `history_graph` component:

- `window_end = now`
- `window_start = now - timedelta(hours=hours)`

### 3. Windowed fetch (`hass_client._fetch_history`)

Extend the signature to accept the window and build a windowed HA URL:

```python
def _fetch_history(
    entity_name: str,
    logger: "Logger",
    *,
    start: datetime,
    end: datetime,
) -> list[list[HistoryPoint]] | None:
    ...
    start_iso = start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end_iso = end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    url = (
        f"{HASS_URL}/api/history/period/{start_iso}"
        f"?filter_entity_id={entity_name}&end_time={end_iso}"
    )
```

HA returns the entity's state *as of* `start` as the first point, giving a
left-edge anchor at the held value — so even a fully-stale entity has a value to
hold across the whole window, and `hours > 24` actually fetches more history.

`_process_history_to_points` is unchanged.

### 4. Fixed window + dotted tail (`_draw_graph_component`)

Extend the signature to take the window explicitly:

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

Behavior:

- **No-data case** (`not data_points`): keep the existing "No numeric data
  for …" message. Unchanged.
- **X-axis bounds:** use `min_time = window_start`, `max_time = window_end`
  instead of deriving them from the data. `time_delta = window_end -
  window_start` (already guaranteed > 0 since `hours >= 1`). X-axis labels are
  computed from this fixed window.
- **Y-axis range:** unchanged — based on the real values
  (`min(values)`/`max(values)`, with the existing equal-min/max guard).
- **Solid line:** plot the real measurements via the existing `to_coords`
  (which now maps against the fixed window). Points outside `[window_start,
  window_end]` should not occur (fetch is windowed), but coordinates are clamped
  defensively so a stray point can't draw outside the plot area.
- **Dotted hold tail:** let `(t_last, v_last)` be the last real measurement.
  Draw a horizontal dotted line at `v_last` from `to_coords(t_last, v_last)` to
  `to_coords(window_end, v_last)`. Implemented with a small dashed-line helper
  (PIL has no native dash): black, width `4 * scale`, ~`12 * scale` on /
  `8 * scale` off. If `t_last == window_end` (degenerate), nothing visible is
  drawn — fine.
- **Last-value text label:** unchanged — positioned at `v_last`'s y.

### 5. Threading window → draw

The draw happens later from `RenderData`, so the window must ride along. Add the
window bounds to the history-graph `RenderData` payload (e.g. store
`window_start`/`window_end` alongside the points, or store `hours` + the shared
`now` and recompute in the draw call). Fetch and draw MUST use the same window.

## Dashed-line helper

Add a small module-level helper in `components.py`:

```python
def _draw_dashed_line(d, start, end, *, fill, width, dash_on, dash_off):
    """Draw a dashed straight line between two points."""
```

Used for the hold tail. Kept generic and unit-testable in isolation.

## Edge cases

| Case | Behavior |
|------|----------|
| No history at all in window | Existing "No numeric data" message |
| Only the left-edge anchor point (fully stale) | Flat dotted line at held value across the whole window; last-value label shown |
| Single real reading mid-window | Solid up to it is trivial (1 point), dotted hold from it to now |
| Data starts late (leading gap) | Left part blank; no leading dotted line |
| `hours` missing/invalid (≤0, non-int) | Default to 24, logged once |
| Fresh sensor (last reading seconds ago) | Negligible/invisible dotted tail (self-managing) |

## Testing (three levels)

- **Unit (`test_components.py`):**
  - `_draw_dashed_line` produces a dashed (gapped) line, not a solid one.
  - `_draw_graph_component` with an explicit window: dotted tail drawn from last
    point to right edge; x bounds follow the window, not the data; fully-stale
    input → flat dotted hold; empty input → "No numeric data" message.
  - `hours` resolution: default 24, invalid → 24 (logged once).
- **Unit (`test_hass_client.py`):** `_fetch_history` builds the windowed URL
  (start path segment + `end_time` query) and still handles HTTP/URL errors.
- **Integration (`test_server.py`/component path):** config with `hours` →
  fetch (mocked) → parse → draw yields a valid image for normal, stale, and
  empty entities without error.
- **E2E/golden (`test_golden.py`):** add golden image(s) for a stale-entity
  graph (visible dotted tail) and a normal graph; existing goldens still pass.

## Out of scope

- No change to non-graph components.
- No global/per-dashboard window default (per-component `hours` only).
- No backward (leading) hold line.
- No staleness threshold (trailing dotted tail is always present but only
  visible when meaningful).
