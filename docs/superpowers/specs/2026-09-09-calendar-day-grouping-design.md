# Calendar day grouping and row reformat

## Problem

A calendar row is built by `_calendar_row_texts` as one flat string per event:

```python
f"{day_name} {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}: {summary}"
# "Wednesday 10:00-12:00: Quarterly planning review with the platform team"
```

Two things are wrong with it.

**The day name repeats and mostly says nothing.** `arguments.days` defaults to
1, so in the common case every event in the panel falls on the same day and the
weekday name is pure repetition. Even at `days: 2` there are only two distinct
values across the whole panel.

**The prefix crowds out the event.** Measured with the real font at 20pt, on a
400px half-width tile (360px content budget after padding):

| | width |
|---|---|
| `Wednesday 10:00-12:00: ` | 233px |
| left for the summary | **127px** |

Roughly 65% of every row is metadata. A typical summary measures 461px, so it
truncates regardless — the question is whether it truncates with 127px of
readable text or with 208px.

A second, independent defect shares the same fix. `_fit_body_size` picks the
largest ladder rung that fits *horizontally* and takes no account of the panel's
height, so a calendar with short summaries inflates to 28pt and pushes events
off the bottom that would have fitted at 24. The panel grows text it did not
need at the cost of events it did.

## Approach

Move the day out of the row text and into a rotated spine in a left gutter,
drawn once per day-group. Add a vertical constraint to the size choice so the
panel stops inflating past the point where it costs an event. Tell the user when
events were dropped.

**Which part delivers what.** These are two independent wins and it is worth not
confusing them. Removing the repeated day name is a purely *horizontal* saving —
it buys summary text (127px → 208px), not events; grouping in fact spends a
little vertical space on separators. The *vertical* win comes entirely from
`v_fit` and the overflow row: `v_fit` stops the panel inflating to a size that
pushes events off the bottom, and the overflow row admits to what it dropped.
The two ship together because they touch the same resolver and the same probe,
not because either causes the other.

All figures below come from prototype renders through the real drawing pipeline
at 400x240 unless stated otherwise.

### Row format

```python
f"{start:%H:%M}-{end:%H:%M}  {summary}"   # two spaces
f"All day  {summary}"                      # all-day events
f"Unknown: {summary}"                      # no parseable start (unchanged)
```

No day name, no colon. The colon goes because the two-space gap already
separates the columns and reads more cleanly when times align vertically.

An event with no parseable start keeps its current `Unknown: ` text and has no
date to group by. Rather than invent a spineless group for it, **any such event
forces the panel into prefix mode**, where every row is self-describing and no
grouping is implied. This is rare enough that a simple rule beats a correct-
looking layout with an unlabelled group in it.

### The spine

Events are grouped by calendar date in display order. Each group draws its
**three-letter day abbreviation** (`%a` — `Wed`, not `WED`) rotated 90° to read
bottom-to-top, in a 32px unscaled gutter on the left, vertically centred against
the group's rows. A 2px vertical rule separates the gutter from the rows, and a
thin horizontal separator divides day groups.

PIL cannot draw rotated text directly. The spine is rendered by drawing the
abbreviation to a temporary RGB image sized to its **ink bounding box** at
`size * COMPONENT_SCALE`, calling `.rotate(90, expand=True)`, and pasting the
result into the gutter. This happens on the 2x canvas alongside every other
draw, before the existing final `img.resize(..., LANCZOS)`, so the spine
downsamples with the same filter as the rest of the panel and needs no special
handling.

The ink box, not the font's line box, and it matters. After rotation the text's
*height* becomes the spine's *width*, which must fit the 32px gutter. Measured
worst case across all seven abbreviations:

| rung | ink height | line height |
|---|---|---|
| 28pt | **22px** | 38px |
| 24pt | 18px | 33px |
| 20pt | 15px | 27px |

Sizing the temp image by the ink box clears the gutter at every rung with 10px
to spare at the worst. Sizing it by the line box would overflow the gutter at
28pt. No third gate is needed — but this is why.

`Wed` rather than `Wednesday` is the decision this design turns on. The full
name is 173px tall rotated, which needs a group about five rows deep before it
fits; prototype renders showed three of four realistic multi-day layouts falling
back to a dayless prefix, and the busy panels where grouping matters most
dropping the spine entirely. The abbreviation is 83px, which fits nearly any
group.

`%a` also produces exactly `Wed`, so a panel that falls back to prefix mode
shows the same token in the same case. Title case over upper case: the ascender
on the `d` gives the rotated glyphs distinguishable shapes, and all-caps reads
as emphasis a routine day label does not need.

### Prefix mode, and the two gates

The gutter is used only when **both** hold, evaluated at the candidate size
currently under test rather than at some already-resolved one:

- **(a) every** day-group is tall enough to carry its spine, and
- **(b)** the content width remaining after the gutter and the
  `"HH:MM-HH:MM  "` prefix is at least **60px** unscaled.

If either fails, the whole panel falls back to **prefix mode**: no gutter, and
every row carries a `f"{day:%a} "` prefix instead.

**Prefix mode keeps the between-day separators.** They are the only grouping cue
left once the spine is gone, and keeping them makes the vertical budget
identical in both modes — `v_fit` counts the same separators whichever mode the
panel lands in, so the row arithmetic does not have to be resolved before the
mode is.

The choice is all-or-nothing per panel. Mixing modes between groups would leave
rows starting at different x positions within one panel, which reads as a
rendering fault.

Gate (b) is what stops the pathological narrow tile. At 200x240 the gutter
leaves *negative* width for the summary; every row renders as a truncated
timestamp and an ellipsis. Such a tile requires 16 components on one dashboard
(`num_rows = ceil(sqrt(n))`, `tile_width = width // cols`); the realistic narrow
case is 266px at nine components.

### Sizing: two fits, take the smaller

Walk `BODY_SIZE_LADDER`, considering only rungs at or above
`CALENDAR_MIN_BODY_SIZE`:

- **`h_fit`** — the largest rung at which every row string fits the available
  content width. Today's rule, but measured against the new shorter strings and
  the width left after the gutter or prefix.
- **`v_fit`** — the largest rung at which every event fits vertically, counting
  group separators.

`v_fit`'s overflow reservation is not circular: at each candidate rung, first
ask whether all events fit. If they do, no row is reserved. If they do not, the
rung fails `v_fit` regardless, and the overflow row is reserved later — out of
the rows the *resolved* size can draw — by replacing the last one.

The resolved size is `min(h_fit, v_fit)`. Each falls back to
`CALENDAR_MIN_BODY_SIZE` when no rung qualifies, matching the existing
`_fit_body_size` contract.

`v_fit` is what stops the panel over-inflating: on an all-short-summary fixture
it holds the panel at 24pt where the horizontal rule alone would have climbed to
28 and dropped a row.

Note what this does *not* do. With the 20pt floor, a genuinely dense day cannot
be made to fit — there is no legal rung below the floor to drop to. `v_fit`
prevents the panel growing into dropping events; it cannot rescue a day with
twelve of them.

### One resolver behind both the probe and the draw

Font size determines row height, which determines group height, which determines
whether the spine fits, which determines content width, which feeds back into
the size. The loop is broken by evaluating the **whole layout** — mode, both
fits, group geometry — at each candidate rung, and taking the first rung that
works.

That evaluation lives in one function:

```python
def _calendar_layout(
    events: list[CalendarEvent],
    width: int,
    height: int,
    logger: "Logger",
    *,
    min_size: int = CALENDAR_MIN_BODY_SIZE,
    fixed_size: int | None = None,
) -> CalendarLayout: ...
```

returning the resolved size, the mode, the gutter width, the day-groups with
their row strings, and the overflow count.

Both consumers call it. `_panel_body_fit` reads the size off it;
`_draw_calendar_component` uses all of it. This is not tidiness — it is the
invariant `test_probe_matches_what_the_calendar_draws_alone` pins. If the probe
and the draw function each derived gutter mode independently they would drift,
and the probe would report a size the panel does not draw at. The 1.10.0 design
called this trap out for the floor; grouping makes it sharper, because now the
mode changes the content width too.

**`fixed_size` is what makes that true in the common case.** A calendar sharing
a layout row does not draw at the size it chose: `tile_components` settles the
row on one size and passes it to every panel. Without `fixed_size` the draw
function would have to re-derive mode and group geometry at that imposed size on
its own — reintroducing the drift for *mode*, which is worse than the drift for
size, because mode also changes the content width every row is ellipsized
against.

So the resolver has two entry points into the same gate logic:

- `fixed_size=None` — walk the ladder, evaluate the gates at each candidate,
  return the first rung that works. This is the probe's path, and the path for a
  calendar drawn alone.
- `fixed_size=N` — skip the ladder entirely and evaluate the gates **once** at
  `N`, returning the mode and geometry that hold there. This is the path
  `_draw_calendar_component` takes whenever `body_font_size` is supplied.

Gate evaluation is one function called from both paths, so a mode is never
derived twice by two pieces of code. A row-imposed size can therefore flip a
panel from gutter to prefix mode — that is correct behaviour, not a failure: at
a smaller imposed size the group is shorter and may no longer carry its spine.

### `_panel_body_fit` gains the tile height

`v_fit` needs the panel's height, and `_panel_body_fit` currently takes only
`tile_width`. The height is already to hand at the one production call site —
`tile_components` iterates `(render_data, _, _, tile_w, tile_h)` and discards
the last element.

Add `tile_height` as a **required positional** parameter. Not an optional one
with a default: a probe that silently skips the vertical constraint when the
height is absent is exactly the drift this design is trying to prevent. The
roughly ten test call sites are updated as part of the change.

The `entities` and `todo_list` branches ignore it. Only the calendar has a
vertical fit.

### The overflow row

When events do not fit, the last drawn row is replaced by `f"+{n} more"`, where
`n` counts every undrawn event including the one whose row was taken. It is
drawn in the row font, aligned with the rows, and `v_fit` reserves a row for it
when the panel cannot show everything.

It sits **outside** every group's spine extent, below a separator, so it reads
as a footer for the panel rather than as a row of any one day.

**That separator is drawn for the footer specifically, whenever a footer is
drawn** — including when the panel has a single day-group and therefore no
between-group separators at all. This is the default case (`days` is 1), so
relying on an inter-group divider being present would leave the footer
unseparated exactly where it matters most. `v_fit` reserves the footer's row
*and* its separator together; a panel that cannot afford both does not get a
footer.

The alternative — extending the last group's rule to cover it — looks tidier but
is a lie: the dropped events may fall on days after the one the spine names, so
anchoring `+7 more` under `Wed` tells the user those seven are Wednesday's. A
count that misattributes its contents is worse than a row that sits slightly
apart, and the separator above it is what stops it reading as a spine that
failed to draw.

## Accepted consequences

**A single-event day always forces prefix mode.** Even the abbreviation needs
about two rows of height (83px rotated against a 39px row at 20pt). A day with
exactly one event can never satisfy gate (a) at any size. This is geometry, not
a tunable, and it means a panel containing one sparse day renders entirely in
prefix mode.

**A calendar's size is still subject to its layout row.** `tile_components`
settles a whole row of panels on one shared body size, so a sibling can force
the calendar below its own `v_fit`. Preserving one size per row is worth more
than letting the calendar optimise privately.

What that costs is larger than it first appears, and is why `fixed_size` exists:
an imposed size can flip the panel out of gutter mode entirely, because a
smaller size means shorter groups and a spine that no longer fits. A calendar
can therefore render with a gutter alone and with prefix rows beside a sibling.
That is consistent — both modes are legible and carry the same information — but
it means the mode is a property of the layout, not of the calendar, and the
tests must cover a calendar whose mode is decided by its neighbours.

**An all-day-only panel now reaches gutter mode.** Two `All day` rows beside a
spine is mildly over-decorated. Cosmetic, and not worth a special case.

## Implementation sequencing

The sizing fix and the grouping work are independent defects that happen to meet
in the same resolver. They land as three separately reviewable commits on one
branch, in this order, each green before the next starts:

1. **`v_fit` and the height plumbing** — `min(h_fit, v_fit)`, `tile_height`
   threaded through `_panel_body_fit` and its call sites. Touches sizing
   semantics and a signature used by non-calendar panels; nothing about the
   calendar's appearance changes yet.

   At this point `v_fit` operates on the **flat, ungrouped** row list and counts
   no separators, because grouping does not exist yet. Commit 2 **supersedes**
   it — the grouped version moves inside `_calendar_layout` and counts
   separators there. It is not extended in place, and the flat version does not
   survive alongside it. Saying so explicitly because the design elsewhere
   forbids deriving the same thing in two places, and a half-finished
   intermediate state is where that rule gets broken by accident.
2. **Row reformat, grouping and the two modes** — `_calendar_layout` with both
   entry points, the spine, prefix fallback, separators. This is the visible
   change.
3. **The overflow row** — smallest and most self-contained; depends on `v_fit`
   from step 1 for the reservation arithmetic.

One branch rather than three because steps 2 and 3 both need step 1's resolver
signature; splitting the branch would mean rebasing the same file three times
for no review benefit.

## Testing

- **Unit** — `_calendar_layout` picks `min(h_fit, v_fit)`; returns prefix mode
  when a group is too short for its spine (gate a) and when the remaining width
  is under 60px (gate b); never returns a size below `CALENDAR_MIN_BODY_SIZE`;
  reports the overflow count and reserves its row. Row strings carry no day name
  in gutter mode and a `%a ` prefix in prefix mode. The probe-equivalence
  invariant: the size `_panel_body_fit` reports equals the size the panel draws
  alone, in **both** modes. `fixed_size=N` returns the mode and geometry that
  hold at `N` without walking the ladder, and agrees with the `fixed_size=None`
  result whenever `N` is the size that walk would have chosen. An event with no
  parseable start forces prefix mode. Both modes draw the same separators, so
  `v_fit` returns the same rung either way.
- **Integration** — `tile_components` passes the tile height through; a calendar
  beside an entities panel still settles on one shared size; a 266px tile falls
  back to prefix mode rather than rendering an unreadable gutter; a panel that
  cannot show every event draws `+N more` below the final separator, outside any
  spine. **A calendar that uses the gutter alone renders in prefix mode when a
  sibling forces it to a smaller size** — the mode-is-a-property-of-the-layout
  case, which is the one most likely to regress.
- **End-to-end** — `render_dashboard_image` with mocked Home Assistant data
  spanning two days yields a dashboard whose calendar groups its events under
  rotated day spines; a single-day dashboard with more events than fit yields a
  visible overflow row.
- **Golden** — the existing calendar goldens change and must be regenerated;
  regenerated images are to be inspected before committing. Add a golden for a
  two-day grouped panel and one for the prefix-mode fallback, since neither
  layout has ever been pinned.

## Out of scope

- **The all-day sort order.** All-day events currently sort before same-day
  timed events because the sort key compares a bare `date` string against a
  `dateTime` string. Prototyping showed the "fix" is a no-op: `"2024-01-17"` is
  a lexical prefix of `"2024-01-17T09:00:00+00:00"`, so the string comparison
  already places all-day events exactly where start-of-day would. Worth
  revisiting only as robustness against mixed offsets.
- **A narrow-tile row format.** Tiles below roughly 266px cannot show a useful
  summary in any format. Gate (b) makes them degrade predictably rather than
  render nonsense; a dedicated format is a separate question.
- **Paging.** A dense day shows what fits plus a count. Cycling through pages,
  as the todo panel does, is not part of this change.
- **Making the floor or the gutter configurable.** Both stay module constants.
  `CALENDAR_MIN_BODY_SIZE` already carries a `ponytail:` note recording the
  upgrade path if a second calendar ever needs different values.
