# A minimum body font size for calendar panels

## Problem

A calendar panel sizes its event rows with `_fit_body_size`, which walks
`BODY_SIZE_LADDER = (28, 24, 20, 18, 16)` and returns the largest rung at which
*every* row fits the tile width — falling back to the smallest rung, 16, when no
rung fits them all. Rows that still overflow at that point are truncated by
`_ellipsize`.

The fallback is too low. A single long summary — `"Wednesday 10:00-12:00:
Quarterly planning review with the platform team"` on a 400px half-width tile —
drags the whole panel to 16, which is barely legible on the e-ink panel at
arm's length. The user's words: "long calendar items are rendering at a tiny
font size".

The machinery to fix this already exists. Only the floor is wrong.

## Approach

Raise the floor for calendar rows from 16 to 20, and let the existing
`_ellipsize` call absorb what no longer fits. A long summary should cost its
own tail, not the panel's legibility.

20 was chosen by the user from four rendered example dashboards (16 / 18 / 20 /
24) of a 2x2 grid pairing calendar and entities panels. Those previews settled
the *value*; they did not distinguish between the possible *scopes* below.

### Scope: why the floor is not global

Three ways to apply a floor were considered.

- **(A) Lower the global ladder to `(28, 24, 20)`.** A one-line change, but it
  also stops an entities- or todo-only row — no calendar anywhere in it — from
  shrinking below 20. The request is scoped to "the calendar card"; this
  changes panels the user did not ask about.
- **(B) Clamp the calendar only, after the row resolves its shared size.** The
  calendar renders at 20 while a list beside it stays at 16. This abandons the
  one-size-per-row invariant `tile_components` deliberately maintains ("a list
  beside a list reads as one block rather than two unrelated type sizes").
- **(C) A calendar panel raises the body floor for its whole row.** Chosen.
  Honours the stated scope and preserves one size per row.

(C) is reversible: widening it to (A) later is a one-line change.

### Accepted consequence

Under (C) a calendar pulls its row-mates up to 20 as well, so an entities or
todo panel sharing that row can now truncate rows it previously rendered in
full. This is inherent to *any* minimum — (A) affects siblings identically —
and truncating instead of shrinking is precisely the behaviour asked for. The
siblings truncate through the `_ellipsize` / `_ellipsize_prefix` calls they
already make, so nothing renders broken, only shorter. Explicitly accepted.

### Not a config option

The floor is a module constant, not a per-component YAML option. One value was
chosen and no second calendar needs a different one. A `ponytail:` comment
records the upgrade path.

## Design

### New constant (`src/trmnl_server/components.py`)

```python
# A calendar row is truncated with an ellipsis rather than shrunk below this
# rung: a long summary should cost its own tail, not the panel's legibility.
# ponytail: one constant for every calendar. Promote to a per-component
# `min_font_size` option if a second calendar ever needs a different floor.
CALENDAR_MIN_BODY_SIZE: int = 20
```

Kept a ladder rung. A free integer would break the quantisation that makes
neighbouring panels comparable.

### One policy, one helper, three consumers

The floor is a single policy — "how small may this panel type's body text
go" — read by three different consumers. It lives in one helper so that
changing it means editing one function:

```python
def _body_floor(panel_type: str) -> int:
    """The smallest body rung a panel of this type may render at."""
    return CALENDAR_MIN_BODY_SIZE if panel_type == 'calendar' else BODY_SIZE_LADDER[-1]
```

**Consumer 1 — `_fit_body_size` gains the floor as a parameter.**

```python
def _fit_body_size(texts, max_width, logger, *, min_size: int = BODY_SIZE_LADDER[-1]) -> int:
```

It considers only rungs `>= min_size` and returns `min_size` when none of them
fits every text. The default leaves every existing caller unchanged.

**Consumer 2 — `_panel_body_fit` floors its probe.**

```python
return _fit_body_size(texts, budget, logger, min_size=_body_floor(panel_type))
```

`_panel_body_fit` is a *probe*: its formula is deliberately byte-identical to
what the panel renders when drawn alone, an invariant
`TestPanelBodyFit.test_probe_matches_what_the_panel_draws_alone` already pins
for entities. Leaving the probe unfloored while flooring the render would make
the probe lie for calendars — reporting 16 for a panel that draws at 20.

**Consumer 3 — the row rule in `tile_components`.**

Flooring the probe is not sufficient on its own: the row settles on
`min(body_fits)`, so a sibling that fits at 16 would drag the calendar back
down. The row rule becomes "the smallest size any panel needs, but no lower
than the highest floor present":

```python
body_specs: list[tuple[int, int]] = [
    (fit, _body_floor(str(render_data.get('type', ''))))
    for render_data, _, _, tile_w, _ in row
    if (fit := _panel_body_fit(render_data, tile_w, logger)) is not None
]
body_font_size: int | None = (
    max(min(f for f, _ in body_specs), max(fl for _, fl in body_specs))
    if body_specs else None
)
```

A panel contributes a floor only if it contributed a fit. An empty calendar
draws a centred "No upcoming events" placeholder rather than rows, so it must
not raise its neighbours — the `fit is not None` gate is what stops it.

**Consumer 4 — `_draw_calendar_component`'s self-fit path.**

```python
else _fit_body_size(event_strings, content_width, logger,
                    min_size=CALENDAR_MIN_BODY_SIZE)
```

This branch only runs when `body_font_size is None`, which no production caller
does today: `tile_components` always supplies a size when the calendar has
events, and an empty calendar returns via the placeholder branch first. It is
kept because it is what holds consumers 2 and 4 in agreement — the probe's
promise is only true if the self-fit path applies the same floor. Without it, a
direct caller silently gets 16 and the probe-equivalence invariant breaks.

### No new truncation code

Rows that still overflow at 20 pass through the `_ellipsize` call
`_draw_calendar_component` already makes. Fewer events fit vertically at the
larger size; the existing `y_pos > large_height - 30 * scale` break already
handles that. Paging is out of scope.

## Testing

- **Unit** — `_fit_body_size` never returns below `min_size` and still selects
  the largest fitting rung at or above it; `_body_floor` returns 20 for
  `'calendar'` and 16 otherwise; `_draw_calendar_component` with long summaries
  and no explicit `body_font_size` draws at `>= 20` and emits an ellipsis; the
  calendar counterpart of the existing probe-equivalence test — the size
  `_panel_body_fit` reports equals the size the panel draws alone.
- **Integration** — `tile_components` on a calendar + entities row settles both
  panels at `>= 20`; a row of entities + todo with no calendar still reaches 16
  (pinning the scope decision); an empty calendar beside an entities panel does
  not raise that panel; a sibling entities panel pulled up to 20 ellipsizes its
  over-long row rather than rendering it clipped.
- **End-to-end** — `render_dashboard_image` with mocked Home Assistant calendar
  data containing an over-long summary yields a dashboard whose calendar rows
  are ellipsized at the floor size.
- **Golden** — `test_body_text_size_harmonisation` pairs an entities panel with
  a long-summary calendar and must be regenerated. The regenerated image is to
  be inspected before committing, and the change to its entities panel called
  out in the commit message as the accepted consequence described above.
