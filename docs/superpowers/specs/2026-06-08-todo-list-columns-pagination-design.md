# Todo List: Multiple Columns + Pagination — Design

**Date:** 2026-06-08
**Status:** Approved (pending spec review)

## Goal

Let a `todo_list` component show many more items than fit in today's single
vertical column, by (a) laying items into multiple columns on one card, and
(b) rotating through pages of items across successive e-ink refreshes when even
the multi-column card overflows.

## Problem (current behavior)

`_draw_todo_list_component` draws incomplete items in a single vertical column,
top to bottom. When it runs out of vertical space it simply `break`s — extra
items are **silently dropped** with no indication. There is no way to show more
items and no signal that items are hidden.

## Decisions (locked via brainstorming)

- **Scope:** one combined spec covering columns AND pagination.
- **Columns:** explicit per-component `columns: int` (default 1; invalid → 1).
- **Page size:** automatic — a page is one full columned screenful. Pagination
  engages only when incomplete items overflow that screenful.
- **Affordance:** title shows the total count, e.g. `Shopping (12)`; a `2/3`
  page indicator appears at top-right only when there is more than one page.
- **Fill order:** column-major (down column 1, then column 2, …).
- **Long items:** ellipsis-truncate text that still doesn't fit a column at the
  16px font floor (today such text overflows).
- **Pagination engages automatically** on overflow; no opt-out toggle for now.
- **State:** in-memory page counter in `ServerState`, advanced once per render,
  reset to 0 on server restart.

## Behavior summary

- A card whose incomplete items fit one columned screenful behaves exactly as
  today plus columns: no page indicator, no rotation. `columns: 1` with a short
  list == current output (plus the title count).
- A card that overflows shows page 0 first, then page 1, page 2, … on each
  refresh, wrapping back to 0.

## Rendering

### Capacity (deterministic)
- `row_height` is fixed (checkbox size + line spacing) — unchanged from today.
- `body_height` = card height minus the header band.
- `rows_per_column = max(1, floor(body_height / row_height))`.
- `capacity = rows_per_column × columns`.
- Capacity does **not** depend on item text, so page boundaries are stable
  regardless of how long individual items are. This is what makes pagination
  deterministic.

### Column layout
- Column width = `body_width / columns` (with the existing left margin for the
  checkbox). The per-item font auto-shrink (28→16px) still runs against the
  *column* width, not the full card width.
- If an item's text still exceeds the column width at the 16px floor, truncate
  with a trailing `…` so it cannot bleed into the next column.
- Items for the current page are placed **column-major**: the first
  `rows_per_column` items fill column 1 top-to-bottom, the next fill column 2,
  etc.

### Header
- Title text becomes `"{friendly_name} ({total_incomplete})"`.
- When `num_pages > 1`, draw a `"{page+1}/{num_pages}"` indicator at the
  top-right of the header band.

## Pagination state

### `ServerState` (state.py)
Add an in-memory page store with a thread-safe accessor:

- `next_todo_page(key: str, num_pages: int) -> int`
  - Returns the current page index for `key` (default 0 when unseen), then
    stores `(current + 1) % num_pages` as the next page. Guarded by the existing
    lock. If `num_pages <= 1`, returns 0 and stores nothing (no rotation).
- `reset_todo_pages() -> None` — clears the store (used by tests).

### Key
`key = f"{device_id}:{dashboard_name}:{entity_name}:{component_index}"`, so
multiple todo cards (even on the same dashboard, even sharing an entity) rotate
independently per device. `device_id` may be `None` (standalone/no device) —
included as the literal string in the key, which is acceptable.

### Cadence
`render_dashboard_image` runs once per static-PNG fetch (`api.py:270`), i.e.
roughly once per device refresh. The page advances once per render, so each
refresh shows the next page. Best-effort: a device that double-fetches the PNG
could advance twice; acceptable.

## Code structure

- **`models.py`** — add `columns: int` to `ComponentConfig` (already
  `total=False`).
- **`state.py`** — add `_todo_pages: dict[str, int]` plus `next_todo_page` and
  `reset_todo_pages`, lock-guarded.
- **`components.py`**
  - `_todo_capacity(height: int, columns: int) -> tuple[int, int]` — takes the
    full component (tile) height, derives the body band (subtracting the header)
    and applies the internal `scale` itself, and returns
    `(rows_per_column, capacity)`. Pure, unit-testable. **Both** the draw
    function and `_render_component` call this single helper with the same
    `height`, so their capacity (and therefore page count) can never diverge.
  - `_draw_todo_list_component(..., *, columns: int = 1, page: int = 0)` —
    filters incomplete items, calls `_todo_capacity(height, columns)`, computes
    `num_pages = max(1, ceil(total / capacity))`, slices the page
    (`page % num_pages`), draws the column-major grid with ellipsis truncation,
    and draws the header count + page indicator. Pure given `columns`/`page`.
  - `_render_component` (todo branch) — calls `_todo_capacity(tile_height,
    columns)`, computes `num_pages = max(1, ceil(total_incomplete / capacity))`
    (identical formula to the draw function), obtains the page via
    `server_state.next_todo_page(key, num_pages)`, and passes `columns`/`page`
    to the draw function. `device_id` and the dashboard
    name are available via the enclosing `render_dashboard_image` scope; the
    component index comes from the render loop.

### Threading `columns` and the key
`columns` is read from the component config in the render loop and carried on
the todo `RenderData` (a new `NotRequired[int]` key, mirroring how the graph
window bounds are carried). The pagination key parts (dashboard name, entity
name, component index) are likewise carried on `RenderData` so `_render_component`
can build the key without re-deriving config.

## Determinism / testing

- The draw function is pure: tests call it with explicit `columns`/`page`.
- `ServerState` starts empty, so the first render of a card returns page 0 —
  golden/integration tests that render once are deterministic. Tests that
  exercise rotation call `next_todo_page` directly or render repeatedly.
- Tests reset pagination state in `setUp` via `reset_todo_pages()` to avoid
  cross-test leakage through the global `server_state` singleton.

### Three levels
- **Unit:**
  - `_todo_capacity` math (rows/capacity for given height/columns; floor; min 1).
  - `next_todo_page` — returns 0 first, advances, wraps at `num_pages`, isolates
    by key, no-ops for `num_pages <= 1`.
  - `_draw_todo_list_component` with explicit `columns`/`page`: column-major
    placement, ellipsis on an over-long item, page indicator present only when
    `num_pages > 1`, count in title, empty-list message unchanged.
- **Integration:** render path (`render_dashboard_image`) with a mocked
  `_fetch_todo_list` returning enough items to overflow — image renders, first
  render is page 0.
- **E2E/golden:** a 2-column overflowing todo dashboard (deterministic page 0)
  golden image.

## Edge cases

| Case | Behavior |
|------|----------|
| Items fit one screenful | One page; no indicator; no rotation (today's behavior + columns + count) |
| `columns` missing/invalid | Default 1, logged once |
| Empty / all-completed list | Existing "No items to display" message |
| Item too long for column at 16px | Ellipsis-truncated |
| Item set changes between refreshes | Page boundaries shift (best-effort; stable HA order assumed) |
| `device_id` is None (standalone) | Key uses the literal "None"; rotation still works per dashboard/entity |
| Server restart | Page resets to 0 |

## Out of scope

- A `paginate: false` opt-out toggle (possible future).
- Showing completed items.
- Auto-fit / automatic column count.
- Persisting pagination state across restarts.
