# Standardising panel title font sizes

## Problem

Each panel renders its title independently. `_draw_graph_component` and
`_draw_entity_component` start at `COMPONENT_TITLE_FONT_SIZE` (35) and shrink by
2 until the title fits the tile width, so a short title stays at 35 while its
neighbour lands at 21. `_draw_calendar_component`, `_draw_entities_component`
and `_draw_todo_list_component` never shrink at all and simply overflow.

The result is a dashboard where adjacent panels carry visibly different title
sizes. This is an aesthetic fix.

## Approach

Panels sharing a grid row share one title size, chosen from a fixed ladder.

- Each panel resolves the largest ladder rung whose title fits its tile width.
- The row takes the minimum of its panels' rungs.
- Every panel in the row renders at that size.

Because candidates are drawn from the ladder, rows needing similar sizes land on
the same rung. A dashboard shows one title size, or two where a title genuinely
demands it — never five. Titles never grow beyond 35.

## Design

### New module-level values (`src/trmnl_server/components.py`)

```python
COMPONENT_SCALE: int = 2                                  # was a local in 5 functions
TITLE_SIZE_LADDER: tuple[int, ...] = (35, 30, 26, 22, 18)
TITLE_PADDING: int = 20                                   # unscaled, total horizontal budget
```

`COMPONENT_SCALE` replaces the `scale: int = 2` local in all five drawing
functions. The measuring pass and the rendering pass must agree on it exactly; a
drifting literal would break fitting silently.

### New helpers

- `_incomplete_count(items) -> int` — counts items whose `status` is not
  `'completed'`. Shared by the measuring pass and `_draw_todo_list_component`,
  which currently computes it inline.
- `_panel_title_text(render_data) -> str` — the string a panel actually draws:
  `friendly_name`, or `f"{friendly_name} ({n})"` for `todo_list`. Measuring the
  bare name for a todo panel under-measures and the title still overflows.
- `_fit_title_size(text, tile_width, logger) -> int` — the largest rung in
  `TITLE_SIZE_LADDER` whose rendered width fits
  `(tile_width - TITLE_PADDING) * COMPONENT_SCALE`; the smallest rung if none
  fit. It runs before any canvas exists, so it measures with
  `FreeTypeFont.getbbox()`, not `ImageDraw.textbbox`. Fonts load through the
  existing `_load_font`, inheriting its `IOError` fallback.

### Changes to the five drawing functions

Each gains a keyword-only `title_font_size: int | None = None`. When supplied,
the function uses exactly that size (times `COMPONENT_SCALE`) and skips its own
shrink loop. When `None`, behaviour is unchanged — this keeps the ~30 existing
tests that call these functions directly working untouched, and keeps the
functions independently testable.

Passing a resolved size to the three functions that never shrank also fixes
their overflow, which is the same defect on a different code path.

### Changes to `tile_components`

Geometry moves out of the render loop. Both layout branches build:

```python
rows: list[list[tuple[RenderData, int, int, int, int]]]   # (render_data, x, y, w, h)
```

- `large_display` branch: row 0 is the single full-width panel; row 1 is the N
  panels beneath it. The large panel forms its own group — it has far more room,
  and dragging it down to the narrow row's size would look worse, not more
  uniform.
- Grid branch: one entry per grid row.

Then, per row:

```python
size = min(
    (_fit_title_size(_panel_title_text(rd), w, logger)
     for rd, _, _, w, _ in row if rd.get('data') is not None),
    default=COMPONENT_TITLE_FONT_SIZE,
)
```

and each panel renders with `title_font_size=size`.

Panels with `data is None` render as `_create_info_image` placeholders, which
draw a centred message with their own independent fit logic rather than a panel
title. They are excluded from the minimum so a placeholder cannot drag a whole
row down.

## Out of scope

- `_create_info_image` keeps its own shrink-to-fit. A row mixing a real panel
  with a no-data placeholder can still show two differently sized text blocks;
  the placeholder is a different kind of element, and harmonising it is a
  separate question.
- Titles that do not fit at the smallest rung (18) clip, matching how the
  existing graph and entity bail-outs behave. No ellipsis truncation.

## Testing

- **Unit** — `_fit_title_size` returns the largest fitting rung, only ever
  returns ladder values, and floors at 18 when nothing fits; `_panel_title_text`
  includes the todo count; `_incomplete_count` ignores completed items; each of
  the five drawing functions honours an explicit `title_font_size` and is
  unchanged when it is `None`.
- **Integration** — `tile_components` with the drawing functions patched to
  capture the `title_font_size` they receive: every panel in a row gets the same
  size; a row of short titles and a row containing a long title get two
  different sizes; the `large_display` panel gets its own size independent of
  the row below; no-data panels are excluded from the row minimum.
- **End-to-end** — a golden-image test rendering a dashboard through
  `render_dashboard_image` with sharply differing title lengths side by side,
  plus regeneration of the existing goldens whose titles legitimately shift.
  Every regenerated diff is inspected, since that inspection is the actual
  aesthetic verification.
