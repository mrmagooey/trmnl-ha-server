# Plan: a minimum body font size for calendar panels

Spec: `docs/superpowers/specs/2026-09-09-calendar-minimum-body-font-size-design.md`

Every change lands in `src/trmnl_server/components.py` and its tests, so the
tasks are sequential — no parallel implementers on this file.

## Task 1 — the floor and its one policy helper

- [ ] Add `CALENDAR_MIN_BODY_SIZE: int = 20` next to `BODY_SIZE_LADDER`, with
      the comment and the `ponytail:` upgrade-path note from the spec.
- [ ] Add `_body_floor(panel_type: str) -> int` returning
      `CALENDAR_MIN_BODY_SIZE` for `'calendar'`, `BODY_SIZE_LADDER[-1]`
      otherwise.
- [ ] Unit test: `_body_floor` returns 20 for `'calendar'`, 16 for every other
      panel type.

## Task 2 — `_fit_body_size` learns a floor

- [ ] Add keyword-only `min_size: int = BODY_SIZE_LADDER[-1]`; consider only
      rungs `>= min_size`; return `min_size` when none fits every text.
- [ ] Update the docstring — the "smallest rung" promise becomes "smallest rung
      at or above `min_size`".
- [ ] Unit tests: never returns below `min_size`; still picks the largest
      fitting rung at or above it; existing callers unaffected by the default.

## Task 3 — the three consumers

- [ ] `_panel_body_fit` passes `min_size=_body_floor(panel_type)`.
- [ ] `_draw_calendar_component`'s self-fit branch passes
      `min_size=CALENDAR_MIN_BODY_SIZE`.
- [ ] `tile_components`: replace the `body_fits` / `min(body_fits)` pair with
      the `body_specs` comprehension and
      `max(min(fits), max(floors))` from the spec.
- [ ] Unit test: the calendar counterpart of
      `TestPanelBodyFit.test_probe_matches_what_the_panel_draws_alone` — the
      size `_panel_body_fit` reports equals the size the panel draws alone.
- [ ] Unit test: `_draw_calendar_component` with long summaries and no explicit
      `body_font_size` draws at `>= 20` and emits an ellipsis.

## Task 4 — integration and end-to-end coverage

- [ ] Integration: `tile_components` on a calendar + entities row settles both
      panels at `>= 20`.
- [ ] Integration: a row of entities + todo with no calendar still reaches 16.
- [ ] Integration: an empty calendar beside an entities panel does not raise
      that panel's size.
- [ ] Integration: a sibling entities panel pulled up to 20 ellipsizes its
      over-long row rather than rendering it clipped.
- [ ] End-to-end: `render_dashboard_image` with mocked calendar data containing
      an over-long summary yields ellipsized calendar rows at the floor size.

## Task 5 — goldens

- [ ] Run the full suite. Regenerate only the goldens that legitimately changed
      (`UPDATE_GOLDEN=1`), expected to be `test_body_text_size_harmonisation`.
- [ ] Inspect the regenerated image before committing it.
- [ ] Note the change to its entities panel in the commit message as the
      accepted sibling consequence from the spec.
