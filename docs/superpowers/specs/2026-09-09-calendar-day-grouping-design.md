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

It sits **inside** the last group's spine extent — the rule extends by one
`row_advance` to cover it. A row with no spine sitting directly beneath a column
of spined rows reads as a glitch rather than as a deliberate summary line.

## Accepted consequences

**A single-event day always forces prefix mode.** Even the abbreviation needs
about two rows of height (83px rotated against a 39px row at 20pt). A day with
exactly one event can never satisfy gate (a) at any size. This is geometry, not
a tunable, and it means a panel containing one sparse day renders entirely in
prefix mode.

**The overflow count can span days the spine does not name.** `+7 more` is
anchored to the last drawn group, but the events it counts may fall on later
days. Correct alternatives — an unanchored row, or a per-day count — both look
worse for a one-line indicator.

**A calendar's size is still subject to its layout row.** `tile_components`
settles a whole row of panels on one shared body size, so a sibling can force
the calendar below its own `v_fit`; the calendar then truncates as it does
today. Preserving one size per row is worth more than letting the calendar
optimise privately.

**An all-day-only panel now reaches gutter mode.** Two `All day` rows beside a
spine is mildly over-decorated. Cosmetic, and not worth a special case.

## Testing

- **Unit** — `_calendar_layout` picks `min(h_fit, v_fit)`; returns prefix mode
  when a group is too short for its spine (gate a) and when the remaining width
  is under 60px (gate b); never returns a size below `CALENDAR_MIN_BODY_SIZE`;
  reports the overflow count and reserves its row. Row strings carry no day name
  in gutter mode and a `%a ` prefix in prefix mode. The probe-equivalence
  invariant: the size `_panel_body_fit` reports equals the size the panel draws
  alone, in **both** modes.
- **Integration** — `tile_components` passes the tile height through; a calendar
  beside an entities panel still settles on one shared size; a 266px tile falls
  back to prefix mode rather than rendering an unreadable gutter; a panel that
  cannot show every event draws `+N more`.
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
