# Centred calendar day spines — design

**Request (verbatim):** "For the calendar card, the rotated day labels are left justified but centre
justified (between the left edge of the card and the start of the calendar text) would likely look
better and be more readable. The effective result is to move the day labels to the right by perhaps
10 pixels."

Designed autonomously (auto-develop); the decision log below was approved by an independent
coherence review.

## Behaviour

In gutter mode, each rotated day label (spine) is centred horizontally between the card's left
edge (x = 0) and the left ink edge of the vertical rule that separates the gutter from the event
rows. Previously it was pasted at a fixed x = 4 (unscaled). At body size 20 this moves labels right
by about 10.5 px; at size 28 by about 7 px. Vertical placement, font sizes, label text and prefix
mode are unchanged.

## Geometry (unscaled px; drawn at `COMPONENT_SCALE` = 2)

- `CALENDAR_GUTTER_W` = 32; row text starts at `x_text = 20 + 32 = 52`.
- The rule is drawn at `x_text - 8 = 44` with width `2` (4 scaled px, centred on the line), so its
  left ink edge is at 43.
- Rotated label width = the label's ink height: ~14.5 px at size 20, ~21 px at size 28.
- New label x = `(rule_left_edge - rotated.width) // 2` in scaled px — equal gaps on both sides of
  the label within ±1 scaled px (integer division).

## Decision log

| # | Question | Chosen | Why | Confidence |
|---|---|---|---|---|
| 1 | Right-hand bound | The vertical rule's left ink edge, not the row-text start (x = 52) | The rule is the visible edge of the label column, so centring against it reads as centred. It gives the requested "perhaps 10 pixels" (+10.5 at size 20); text start would give +14.5 and look pushed against the rule. Switching to the text start is a one-line change. | medium |
| 2 | Centre on each label's own ink width, or the widest at that size | Own ink width | Labels at one size differ by ≤ 2 scaled px; the function already measures the ink box. | high |
| 3 | Where the bound comes from | The caller passes it to `_draw_spine` as a keyword argument, computed from the same expression that draws the rule | One source of truth: the label follows if the gutter or rule moves. Removes the independent `4 * COMPONENT_SCALE`. Keyword keeps existing spies (`side_effect=_draw_spine`) compatible. | high |
| 4 | Vertical placement / sizes | Unchanged | Not requested (YAGNI). | high |
| 5 | Prefix mode | Unaffected | It draws no spines. | high |

## Design

- `_draw_spine(img, label, size, top, bottom, logger, *, right)` — `right` is the scaled x of the
  gutter's visible right boundary (the rule's left ink edge). Paste x becomes
  `max(0, (right - rotated.width) // 2)`.
- `_draw_calendar_component` computes the rule's x once (`x_text - 8 * scale`), uses it for the
  rule, and passes `right = rule_x - rule_width // 2` to `_draw_spine`, where `rule_width` is the
  same value passed to `d.line`.

## Testing

- **Unit:** `_draw_spine` on a blank canvas, for several labels at sizes 16/20/28: the ink's left
  gap to x = 0 equals its right gap to `right` within ±1 scaled px.
- **Integration:** regenerate gutter-mode goldens; review the diffs to confirm only the spine
  columns moved and no prefix-mode golden changed.
- **End-to-end:** render a gutter-mode calendar dashboard via `render_dashboard_image` and assert,
  on the final image, that the spine ink's left gap to the panel edge equals its gap to the rule's
  ink within ±1 px.
