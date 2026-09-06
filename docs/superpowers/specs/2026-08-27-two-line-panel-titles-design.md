# Two-line panel titles

Builds on `2026-08-27-panel-title-font-standardisation-design.md`, which made
every panel in a grid row share one title size drawn from
`TITLE_SIZE_LADDER = (35, 30, 26, 22, 18)`.

## Problem

A long title forces its whole row down the ladder, and if it does not fit even
at rung 18 it is ellipsis-truncated. Wrapping trades vertical space for
horizontal, letting the row keep a larger size. Measured at a 400px tile:

| Title | 1 line | 2 lines |
| --- | --- | --- |
| `Back Garden Soil Moisture Level` | rung 22 | rung 35 |
| `Extremely Long Living Room Temperature Sensor` | rung 18, truncated | rung 26 |
| `Living Room Temperature` | rung 30 | rung 35 |

Three lines is worse than two: it starts breaking words mid-token for
diminishing returns.

## Approach

A row resolves **two** values instead of one: a font size and a line count.
Both are shared by every panel in the row, so neighbours keep aligned content
origins as well as matching title sizes.

## Constants

```python
TITLE_MAX_LINES: int = 2
TITLE_WRAP_MIN_GAIN: int = 1    # ladder rungs a wrap must gain to be worth it
TITLE_LINE_SPACING: int = 4     # unscaled, inter-line gap
TITLE_BAND_GAP: int = 4         # unscaled, gap between title ink and content
TITLE_BAND_MAX_PERCENT: int = 45  # a title band may not exceed this % of tile height
```

## Helpers

- `_wrap_title(text, font, max_width, max_lines) -> list[str] | None` — greedy
  pixel word wrap measured with `font.getbbox`. Never breaks a word. Returns
  `None` when the text needs more than `max_lines`.
- `_title_band_height(font_size, lines, logger) -> int` — unscaled height
  reserved below the title's anchor. Builds a scratch
  `ImageDraw.Draw(Image.new('RGB', (1, 1)))`, calls `multiline_textbbox` on an
  `"Ag"` probe repeated `lines` times with
  `spacing=TITLE_LINE_SPACING * COMPONENT_SCALE`, and returns
  `bbox[3] // COMPONENT_SCALE`. Measurement and painting go through the same
  PIL routine with the same spacing, so the reserved band and the painted
  extent cannot diverge.
- `_fit_title_size(text, tile_width, logger, *, lines=1, max_band=None)
  -> int | None` — the largest rung fitting both the wrapped width and, when
  `max_band` is given, a band height within it. **Returns `None` only when
  `max_band` excludes every rung.** With `max_band=None` — every one-line call
  and every pre-existing call site — behaviour and the "smallest rung if none
  fit" fallback are unchanged, so no existing caller can observe `None`.

Measured band heights (unscaled): rung 35 → 46 / 87, rung 30 → 39 / 76,
rung 26 → 34 / 66, rung 22 → 29 / 57, rung 18 → 24 / 47.

## Row resolution

In `tile_components`, per row. `tile_height` is read explicitly from the row's
first placement — every panel in a row shares one height in both layout
branches.

```python
tile_height = row[0][4]
row_panels = [(rd, w) for rd, _, _, w, _ in row if rd.get('data') is not None]

s1 = min(
    (_fit_title_size(_panel_title_text(rd), w, logger) for rd, w in row_panels),
    default=COMPONENT_TITLE_FONT_SIZE,
)

cap = tile_height * TITLE_BAND_MAX_PERCENT // 100
s2_results = [
    _fit_title_size(_panel_title_text(rd), w, logger, lines=2, max_band=cap)
    for rd, w in row_panels
]
s2 = None if (not s2_results or any(r is None for r in s2_results)) else min(s2_results)

if s2 is not None and TITLE_SIZE_LADDER.index(s1) - TITLE_SIZE_LADDER.index(s2) >= TITLE_WRAP_MIN_GAIN:
    title_font_size, title_lines = s2, 2
else:
    title_font_size, title_lines = s1, 1
```

`s2_results` must be a materialised list checked with `any(... is None ...)`
*before* `min()` is called. Feeding a generator with mixed `None`/int straight
into `min()` raises `TypeError`, and mixed results are the expected case on
dashboards with many components.

The band cap matters: `num_rows = ceil(sqrt(n))` over an unbounded component
count reaches `tile_height = 88` at 17 components, where the cap (39px) is
below even rung 18's two-line band (47px). No rung qualifies, `s2` is `None`,
and the row falls back to one line — today's behaviour.

Because the gain test compares ladder indices, an `s2` no better than `s1`
yields `<= 0` and the row keeps one line. No extra guard is needed.

## Threading the band through the components

All five drawing functions gain keyword-only `title_lines: int = 1`, re-wrap
via `_wrap_title`, paint with
`multiline_text(..., align='center', spacing=TITLE_LINE_SPACING * scale)`, and
`_ellipsize` any single line that still overflows.

**Byte-identity is structural, not arithmetic.** At `title_lines == 1` every
content origin keeps its literal existing constant *unconditionally* — there is
no `max()` against the band anywhere on the one-line path. The band only ever
raises an origin when the title actually wraps:

| Component | 1 line | 2 lines |
| --- | --- | --- |
| graph | `margin_top = 40 * scale` | `max(40 * scale, title_y + band + TITLE_BAND_GAP * scale)` |
| calendar, entities | `y_pos = 50 * scale` | `max(50 * scale, title_y + band + TITLE_BAND_GAP * scale)` |
| todo | `header_y = TODO_HEADER_H * scale` | `max(TODO_HEADER_H * scale, title_y + band + TITLE_BAND_GAP * scale)` |
| entity | `avail_top = 0` | `avail_top = band` |

This guard shape is deliberate. A `max(40 * scale, band)` form would break
byte-identity, because the one-line band at rung 35 is 46px against the graph's
40px margin.

`_todo_capacity` takes the same size and line count so pagination matches the
drawn header; at one line it uses `TODO_HEADER_H` unchanged.

### Graph margin split

`margin` currently does double duty as horizontal and vertical, so it becomes
three names:

- `margin_left = 40 * scale` (unchanged) — lines 316, 317, 365 (x of both
  points), 370 (x of point 1), 387, 392, 409, 415, 425, 443, 444, 454.
- `margin_top` per the table above — lines 318 and 365 (y of the first point
  only).
- `margin_bottom = 40 * scale` (unchanged) — lines 318, 365 (y of point 2),
  370 (y of both), 379, 401, 430, 436, 445.

`graph_height = large_height - margin_top - margin_bottom - (10 * scale)`.

### Entity value placement

The value is centred, not stacked below the title, and its shrink loop is
width-only — so a two-line band can leave it nowhere valid. Measured: a 266x146
tile needs 158px for a 2-line band plus the value, in 146px.

```python
avail_top = band_scaled if title_lines > 1 else 0
avail_h = large_height - avail_top
```

1. The existing shrink loop's condition gains a height clause: continue while
   `value_width > large_width - padding or value_height > avail_h`. Same `-= 4`
   step, same `16 * scale` floor, same `except IOError` structure.
2. After the existing wrap block, bound the result:
   `max_value_lines = max(1, avail_h // line_pitch)`; keep only that many lines
   and `_ellipsize` the last kept one. `line_pitch` must be derived with
   `spacing=4` **absolute** — PIL's default when `text()` renders an embedded
   newline is 4 unscaled pixels, not `4 * scale`.
3. `value_y = avail_top + (avail_h - value_height) / 2 - final_y_tweak`, then
   `value_y = max(float(avail_top), value_y)`. `final_y_tweak` keeps its
   existing definition.

At one line `avail_top` is 0 and `avail_h` is the full height, so the height
clause only fires where the value already overflowed — a pre-existing bug.

## Deliberately not done

The entity value's existing wrap loop is **not** unified with `_wrap_title`. It
measures with `d.textbbox` and a strict `<`; the title wrap needs
`font.getbbox` and `<=` because the row resolver runs before any canvas exists.
Unifying them risks shifting existing value renders by a word for no benefit
here. The duplication carries a `ponytail:` comment naming the reason.

## Testing

- **Unit** — `_wrap_title` (fits, wraps, unbreakable word, empty string, returns
  `None` past `max_lines`); `_title_band_height` against the measured table;
  `_fit_title_size` with `lines=2` and with a `max_band` that excludes every
  rung (returns `None`); the gain arithmetic; the value height clause and line
  cap.
- **Integration** — a row wraps only when the gain threshold is met; every panel
  in a row receives the same size *and* the same line count; a row with mixed
  `None`/int results does not raise; the band cap prevents wrapping at
  `tile_height = 88`; a placeholder-only row falls back to `(35, 1)`;
  `_todo_capacity` agrees with the drawn header.
- **End-to-end** — a new golden showing a wrapped row, and all 9 existing
  goldens byte-identical. The two pre-existing golden failures
  (`entity_attribute_dashboard`, `history_graph_bipolar`) are stale on `main`
  and out of scope.
