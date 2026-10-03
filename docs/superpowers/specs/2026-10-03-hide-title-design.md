# Titleless cards (`hide_title`) — design

**Request (verbatim):** "Make a new feature, the ability to render a card without a title and have
the card content use the extra space."

Designed autonomously (auto-develop); the decision log below was approved by an independent
coherence review.

## Behaviour

A component may set `hide_title: true` (default `false`). Such a card draws no title, and its
content starts at a minimal top inset instead of below the title band, using the reclaimed space.
Applies to every component type: `history_graph`, `entity`, `url`, `entities`, `calendar`,
`todo_list`.

## Decision log

| # | Question | Chosen | Why | Confidence |
|---|---|---|---|---|
| 1 | Config surface | `hide_title: true` (bool, default false) | Matches existing default-false booleans (`large_display`, `zero_baseline`). `friendly_name` stays required — placeholders and logs use it. | medium |
| 2 | Which types | All six | Request says "a card". | high |
| 3 | Internal representation | Titleless card is rendered with `title_lines = 0` (named constant `NO_TITLE_LINES = 0`) | All drawers and content-top helpers already derive layout from `title_lines`. | medium |
| 4 | Row title harmonisation | Titleless cards excluded from the row title fit (`_panel_draws_a_title` → False); each is rendered and body-fit with its own `title_lines = 0`, not the row's value | A hidden title must not shrink neighbours' titles. | high |
| 5 | No-data placeholders | Unchanged ("No data for <friendly_name>") even with `hide_title` | They exist to name what failed. Documented as an exception. | high |
| 6 | todo_list "(N)" count (part of its title) | Dropped with the title; page indicator unchanged | YAGNI. Documented. | medium |
| 7 | Reclaimed space | Per-type minimal inset that clips no ink (graph keeps room for its top y-axis label; entity/url value centred on its real ink box in the full tile) | That is the "use the extra space" requirement. | high |
| 8 | Invalid value | Non-bool → `logger.warning` with context, treated as `false` | Mirrors `_resolve_gap_style` / `_resolve_max_gap`. | high |

## Design

1. **Config → render data.** `_resolve_hide_title(component, logger) -> bool` beside the other
   `_resolve_*` validators. `render_dashboard_image` writes `hide_title: True` into the render
   entry only when true (same pattern as `zero_baseline`/`gap_style`), for every component type
   including `url`. Add `hide_title` to `ComponentConfig` and `RenderData` in `models.py`.
2. **Tiling.** `_panel_draws_a_title` returns False when `render_data.get('hide_title')`.
   In `tile_components`, a hidden-title card gets `title_lines = NO_TITLE_LINES` for both
   `_panel_body_fit` and `_render_component`; other cards keep the row's resolved value.
   An all-titleless row falls back to defaults harmlessly (row_panels empty).
3. **Drawers / layout helpers.** Every existing check treats 0 like 1 (`title_lines <= 1`,
   `title_lines > 1 … else`), so each needs an explicit `title_lines == 0` branch placed
   *before* those checks:
   - `_calendar_content_top`, `_todo_header_height` — minimal inset. Pagination/capacity
     (`_calendar_capacity`, `_todo_capacity`) and drawing share these, so they cannot diverge.
   - `_draw_graph_component` — skip title; `margin_top` reduced to the minimum that keeps the top
     y-axis label unclipped.
   - `_draw_entity_component` (entity and url) — skip title; centre the actual ink box in the full
     tile (as the `title_lines > 1` path does), not the fixed `y_tweak`; clamp so ink never clips
     top or bottom. The value may grow larger; the existing width/height shrink loop bounds it.
   - `_draw_entities_component` — skip title; `y_pos` minimal inset.
   - `_draw_calendar_component`, `_draw_todo_list_component` — skip title; use the helpers above.
     The todo page indicator is drawn top-right at y=12 inside the title band, so a titleless
     todo keeps a fixed band just tall enough for it (`TODO_NO_TITLE_HEADER_H`, measured so the
     indicator's ink clears the first row). Fixed rather than conditional on pagination, because
     capacity decides pagination and a header that depends on pagination would be circular.
   - The title-drawing block in each drawer is guarded by `title_lines != NO_TITLE_LINES`.
4. **Body size.** Body size remains harmonised as the row minimum, so hiding a title buys more
   rows/space, not necessarily larger body text than the row's harmonised size. Documented.

## Testing (all three levels)

- **Unit:** `_resolve_hide_title` (absent → False, True/False, invalid → warning + False);
  `_calendar_content_top` / `_todo_header_height` at 0 are smaller than at 1; capacity at 0 is
  ≥ capacity at 1; per drawer, title ink absent and content starts higher at `title_lines=0`
  (regression against the `<= 1` fall-through); `_panel_draws_a_title` False when hidden.
- **Integration:** `tile_components` — mixed row where a titled neighbour wraps to 2 lines: the
  titleless card receives 0, the neighbour 2; titleless card excluded from the row title fit;
  all-titleless row renders; config `hide_title` flows through `render_dashboard_image` to the
  drawer, including for `url`.
- **Golden:** one new golden per type rendered titleless. Existing goldens must not change.
- **E2E:** HTTP `/static/<name>.png` test that the served PNG differs with and without
  `hide_title`.

## Docs

README component options: `hide_title` bullet, noting the todo count is dropped, no-data
placeholders still name the card, and body text stays at the row's harmonised size.
AGENTS.md Component Notes entry.
