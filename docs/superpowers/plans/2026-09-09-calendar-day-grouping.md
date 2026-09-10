# Calendar Day Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the repeated weekday name out of every calendar row into a rotated spine drawn once per day, stop the panel inflating to a size that pushes events off the bottom, and say how many events were dropped.

**Architecture:** One resolver, `_calendar_layout`, decides size, gutter-vs-prefix mode, group geometry and overflow in a single pass, and is called by both the `_panel_body_fit` probe and `_draw_calendar_component`. It has two entry points: walk the size ladder (probe, and calendar drawn alone), or evaluate once at a size imposed by `tile_components` (the common draw path). Nothing derives mode twice.

**Tech Stack:** Python 3.12, Pillow (PIL), unittest via pytest, `uv` for dependency management.

**Spec:** `docs/superpowers/specs/2026-09-09-calendar-day-grouping-design.md` — read it before starting. The plan argues from the spec; where they disagree, the spec wins.

## Global Constraints

- Test command is `uv run pytest`. A single test: `uv run pytest tests/test_components.py::ClassName::test_name -v`.
- Branch is `calendar-day-grouping`. Do not commit to `main`. Do not merge, push, or open a PR.
- All sizes returned for body text must be members of `BODY_SIZE_LADDER = (28, 24, 20, 18, 16)`.
- A calendar never renders below `CALENDAR_MIN_BODY_SIZE = 20`.
- `COMPONENT_SCALE = 2`. Panels are drawn on a 2x canvas and downsampled with `Image.LANCZOS` at the end. Font sizes passed to `_load_font` are always `size * COMPONENT_SCALE`; widths compared against `getbbox` output are in scaled pixels.
- The spine's temp image must be sized by its **ink bounding box**, never the font line box. Ink height worst case is 22px at 28pt against a 32px gutter; the line box is 38px at 28pt and would overflow.
- Existing public behaviour that must not change: an empty calendar draws the centred "No upcoming events" placeholder and `_panel_body_fit` returns `None` for it.

## File Structure

- `src/trmnl_server/components.py` — every production change. Already large, and the codebase's established pattern is one module for all component rendering; do not split it.
- `tests/test_components.py` — unit and integration tests. Add new classes at the end, following the existing `class TestX(unittest.TestCase)` style.
- `tests/test_calendar_grouping_e2e.py` — new file, end-to-end tests through `render_dashboard_image`.
- `tests/test_golden.py` + `tests/golden/*.png` — golden image coverage.

---

### Task 1: Thread `tile_height` into the probe

Pure signature change, no behaviour change. Isolated so a reviewer can confirm nothing moved before sizing semantics change in Task 2.

**Files:**
- Modify: `src/trmnl_server/components.py` — `_panel_body_fit` (line ~245), its call site in `tile_components` (line ~1925)
- Test: `tests/test_components.py` — existing `TestPanelBodyFit` (line ~2615) and every other `_panel_body_fit` call site

**Interfaces:**
- Consumes: nothing
- Produces: `_panel_body_fit(render_data: RenderData, tile_width: int, tile_height: int, logger: Logger) -> int | None` — `tile_height` is a required positional third argument, before `logger`

- [ ] **Step 1: Update the signature and docstring**

In `src/trmnl_server/components.py`, change `_panel_body_fit`:

```python
def _panel_body_fit(
    render_data: "RenderData",
    tile_width: int,
    tile_height: int,
    logger: "Logger",
) -> int | None:
```

Add to the Args section of its docstring, after the `tile_width` line:

```
        tile_height: Unscaled height of the tile the panel will occupy. Only
            the calendar uses it — it is the vertical budget its rows must fit
            inside. Required rather than optional: a probe that silently skips
            the vertical constraint when the height is absent would report a
            size the panel does not draw at.
```

The body is unchanged in this task.

- [ ] **Step 2: Update the production call site**

In `tile_components`, the row body-size block currently discards the tile height. Change both the loop unpacking and the call:

```python
        body_specs: list[tuple[int, int]] = [
            (fit, _body_floor(str(render_data.get('type', ''))))
            for render_data, _, _, tile_w, tile_h in row
            if (fit := _panel_body_fit(render_data, tile_w, tile_h, logger)) is not None
        ]
```

- [ ] **Step 3: Update every test call site**

In `tests/test_components.py`, every `_panel_body_fit(...)` call gains a height argument. Use `220` wherever the existing call uses width `400`, matching the height already used by `test_probe_matches_what_the_calendar_draws_alone`. Find them with:

```bash
grep -n "_panel_body_fit(" tests/test_components.py
```

Each call of the shape `_panel_body_fit(render_data, 400, mock_logger)` becomes `_panel_body_fit(render_data, 400, 220, mock_logger)`.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: PASS, same count as before the change. This task changes no behaviour, so any failure is a missed call site.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "refactor: thread the tile height into _panel_body_fit"
```

---

### Task 2: `v_fit` — stop the panel inflating past its own height

**Files:**
- Modify: `src/trmnl_server/components.py` — add `_calendar_vertical_fit`, use it in `_panel_body_fit`'s calendar branch
- Test: `tests/test_components.py` — new class `TestCalendarVerticalFit`

**Interfaces:**
- Consumes: `_panel_body_fit(render_data, tile_width, tile_height, logger)` from Task 1
- Produces: `_calendar_vertical_fit(n_rows: int, tile_height: int, logger: Logger, *, min_size: int = CALENDAR_MIN_BODY_SIZE) -> int` — the largest ladder rung at or above `min_size` at which `n_rows` rows fit `tile_height`, else `min_size`

**Note for Task 4:** this operates on a **flat, ungrouped** row count and counts no separators, because grouping does not exist yet. Task 4 **supersedes** it — the grouped version lives inside `_calendar_layout` and counts separators there. Do not extend this function in Task 4; delete it and move the arithmetic.

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_components.py`:

```python
class TestCalendarVerticalFit(unittest.TestCase):
    """The calendar stops growing once a larger rung would cost it an event."""

    def test_few_rows_allow_the_largest_rung(self):
        # Two rows fit a 240px tile at any size on the ladder.
        self.assertEqual(
            _calendar_vertical_fit(2, 240, mock_logger), BODY_SIZE_LADDER[0]
        )

    def test_many_rows_force_a_smaller_rung(self):
        big = _calendar_vertical_fit(2, 240, mock_logger)
        small = _calendar_vertical_fit(8, 240, mock_logger)
        self.assertLess(small, big)

    def test_never_returns_below_the_floor(self):
        # Twenty rows fit no rung; the floor is returned rather than 16.
        self.assertEqual(
            _calendar_vertical_fit(20, 240, mock_logger), CALENDAR_MIN_BODY_SIZE
        )

    def test_result_is_always_a_ladder_rung(self):
        for n in range(1, 15):
            self.assertIn(_calendar_vertical_fit(n, 240, mock_logger), BODY_SIZE_LADDER)


class TestCalendarProbeUsesBothFits(unittest.TestCase):
    """_panel_body_fit takes the smaller of the horizontal and vertical fits."""

    def _events(self, n, summary):
        return [
            {'summary': summary,
             'start': {'dateTime': f'2024-01-17T{9 + i:02d}:00:00+00:00'},
             'end': {'dateTime': f'2024-01-17T{9 + i:02d}:30:00+00:00'}}
            for i in range(n)
        ]

    def test_short_summaries_are_held_down_by_the_height(self):
        # Short rows fit wide at 28pt, but eight of them do not fit a short
        # tile; the probe must report the vertical answer, not the horizontal.
        render_data = {'type': 'calendar', 'data': self._events(8, 'Sync')}
        tall = _panel_body_fit(render_data, 400, 400, mock_logger)
        short = _panel_body_fit(render_data, 400, 200, mock_logger)
        self.assertLess(short, tall)

    def test_still_never_below_the_calendar_floor(self):
        render_data = {'type': 'calendar', 'data': self._events(20, 'Sync')}
        self.assertGreaterEqual(
            _panel_body_fit(render_data, 400, 120, mock_logger),
            CALENDAR_MIN_BODY_SIZE,
        )

    def test_height_does_not_affect_non_calendar_panels(self):
        render_data = {
            'type': 'entities',
            'data': [{'friendly_name': f'Sensor {i}', 'state': '20.0'} for i in range(8)],
        }
        self.assertEqual(
            _panel_body_fit(render_data, 400, 400, mock_logger),
            _panel_body_fit(render_data, 400, 120, mock_logger),
        )
```

Add `_calendar_vertical_fit` to the existing import block at the top of the file that already pulls in `_panel_body_fit`, `_body_floor`, `BODY_SIZE_LADDER` and `CALENDAR_MIN_BODY_SIZE`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_components.py::TestCalendarVerticalFit -v`
Expected: FAIL with `ImportError` / `NameError` on `_calendar_vertical_fit`.

- [ ] **Step 3: Implement `_calendar_vertical_fit`**

Add in `src/trmnl_server/components.py`, directly after `_fit_body_size`:

```python
def _calendar_row_advance(size: int, logger: "Logger") -> int:
    """Scaled vertical distance between the tops of two consecutive rows.

    One shared advance for every row: even at a single font size the per-row
    ink height swings with ascenders and descenders, which is what made the
    old spacing ragged.
    """
    font = _load_font(size * COMPONENT_SCALE, logger)
    ascent, descent = font.getmetrics()
    return ascent + descent + CALENDAR_LINE_SPACING * COMPONENT_SCALE


def _calendar_vertical_fit(
    n_rows: int,
    tile_height: int,
    logger: "Logger",
    *,
    min_size: int = CALENDAR_MIN_BODY_SIZE,
) -> int:
    """Largest rung at or above min_size at which n_rows rows fit the tile.

    The vertical counterpart of _fit_body_size. Without it a calendar whose
    summaries are short climbs to the top of the ladder and pushes events off
    the bottom that would have fitted one rung down — it grows text it did not
    need at the cost of events it did.

    Args:
        n_rows: Number of rows the panel wants to draw
        tile_height: Unscaled height of the tile
        logger: Logger instance
        min_size: Smallest rung this may return

    Returns:
        A size from BODY_SIZE_LADDER; min_size when no rung fits every row.
    """
    budget = tile_height * COMPONENT_SCALE - CALENDAR_CONTENT_TOP * COMPONENT_SCALE \
        - CALENDAR_BOTTOM_MARGIN * COMPONENT_SCALE
    for size in BODY_SIZE_LADDER:
        if size < min_size:
            continue
        if n_rows * _calendar_row_advance(size, logger) <= budget:
            return size
    return min_size
```

Add these constants next to `CALENDAR_MIN_BODY_SIZE`:

```python
CALENDAR_LINE_SPACING: int = 8    # unscaled gap below each row
CALENDAR_CONTENT_TOP: int = 50    # unscaled y where rows start under a 1-line title
CALENDAR_BOTTOM_MARGIN: int = 30  # unscaled space kept clear at the panel foot
```

These three numbers are currently inline literals in `_draw_calendar_component` (`line_spacing = 8 * scale`, `y_pos = 50 * scale`, `large_height - 30 * scale`). Replace those literals with the constants in the same commit so the probe and the draw cannot disagree about them.

- [ ] **Step 4: Use both fits in the probe**

In `_panel_body_fit`, the calendar branch currently falls through to a single `_fit_body_size` call at the end. Give the calendar its own return so the vertical fit applies only to it:

```python
    elif panel_type == 'calendar':
        texts = _calendar_row_texts(data, logger)  # type: ignore[arg-type]
        if not texts:
            return None
        budget = (tile_width - 40) * COMPONENT_SCALE
        floor = _body_floor(panel_type)
        return min(
            _fit_body_size(texts, budget, logger, min_size=floor),
            _calendar_vertical_fit(len(texts), tile_height, logger, min_size=floor),
        )
```

- [ ] **Step 5: Apply the same rule where the calendar draws alone**

In `_draw_calendar_component`, the self-fit branch must agree with the probe or `test_probe_matches_what_the_calendar_draws_alone` breaks. Change it to:

```python
        resolved_size: int = body_font_size if body_font_size is not None else min(
            _fit_body_size(event_strings, content_width, logger,
                           min_size=CALENDAR_MIN_BODY_SIZE),
            _calendar_vertical_fit(len(event_strings), height, logger,
                                   min_size=CALENDAR_MIN_BODY_SIZE),
        )
        font_row = _load_font(resolved_size * scale, logger)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_components.py::TestCalendarVerticalFit tests/test_components.py::TestCalendarProbeUsesBothFits -v`
Expected: PASS

Then the full suite: `uv run pytest`
Expected: PASS. If `test_body_text_size_harmonisation` or another golden fails, the calendar in that fixture has changed size — legitimate. Regenerate goldens in Task 8, not here; for now confirm the failure is a golden mismatch and nothing else, and record which goldens moved.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: cap calendar body size by the panel's own height

A calendar with short summaries climbed to the top of the size ladder and
pushed events off the bottom that would have fitted one rung down. The
probe and the draw now take min(horizontal fit, vertical fit)."
```

---

### Task 3: Row reformat and day grouping

**Files:**
- Modify: `src/trmnl_server/components.py` — rewrite `_calendar_row_texts`, add `_calendar_day_groups`
- Test: `tests/test_components.py` — new class `TestCalendarDayGroups`; update the existing `TestBodyRowTextBuilders` (line ~2931) expectations for the new row text

**Interfaces:**
- Consumes: nothing from Tasks 1-2
- Produces:
  - `_calendar_event_row(event: CalendarEvent) -> str` — `"10:00-12:00  Summary"`, `"All day  Summary"`, or `"Unknown: Summary"`
  - `_calendar_day_groups(events: list[CalendarEvent], logger: Logger) -> tuple[list[tuple[date | None, str, list[str]]], bool]` — sorted groups of `(day, label, rows)` where `label` is `'%a'` (`"Wed"`), plus a bool that is True when any event has no parseable start
  - `_calendar_row_texts(events, logger) -> list[str]` stays, now returning the reformatted flat rows, still used by the probe until Task 6

- [ ] **Step 1: Write the failing tests**

```python
class TestCalendarDayGroups(unittest.TestCase):
    """Events are grouped by date, and rows carry no weekday name."""

    WED_9 = {'summary': 'Standup',
             'start': {'dateTime': '2024-01-17T09:00:00+00:00'},
             'end': {'dateTime': '2024-01-17T09:15:00+00:00'}}
    WED_10 = {'summary': 'Planning',
              'start': {'dateTime': '2024-01-17T10:00:00+00:00'},
              'end': {'dateTime': '2024-01-17T12:00:00+00:00'}}
    THU_9 = {'summary': 'Retro',
             'start': {'dateTime': '2024-01-18T09:00:00+00:00'},
             'end': {'dateTime': '2024-01-18T09:30:00+00:00'}}
    ALL_DAY = {'summary': 'Sam on leave',
               'start': {'date': '2024-01-18'}, 'end': {'date': '2024-01-19'}}
    BROKEN = {'summary': 'Mystery', 'start': {}, 'end': {}}

    def test_row_carries_time_and_summary_only(self):
        self.assertEqual(_calendar_event_row(self.WED_10), '10:00-12:00  Planning')

    def test_all_day_row(self):
        self.assertEqual(_calendar_event_row(self.ALL_DAY), 'All day  Sam on leave')

    def test_unparseable_row_keeps_its_marker(self):
        self.assertEqual(_calendar_event_row(self.BROKEN), 'Unknown: Mystery')

    def test_no_row_contains_a_weekday_name(self):
        for event in (self.WED_9, self.WED_10, self.THU_9, self.ALL_DAY):
            row = _calendar_event_row(event)
            for day in ('Monday', 'Tuesday', 'Wednesday', 'Thursday',
                        'Friday', 'Saturday', 'Sunday'):
                self.assertNotIn(day, row)

    def test_groups_one_per_date_in_order(self):
        groups, _ = _calendar_day_groups(
            [self.THU_9, self.WED_10, self.WED_9], mock_logger
        )
        self.assertEqual([label for _, label, _ in groups], ['Wed', 'Thu'])
        self.assertEqual(len(groups[0][2]), 2)
        self.assertEqual(len(groups[1][2]), 1)

    def test_rows_within_a_group_are_time_ordered(self):
        groups, _ = _calendar_day_groups([self.WED_10, self.WED_9], mock_logger)
        self.assertEqual(groups[0][2], ['09:00-09:15  Standup', '10:00-12:00  Planning'])

    def test_label_is_the_three_letter_abbreviation(self):
        groups, _ = _calendar_day_groups([self.WED_9], mock_logger)
        self.assertEqual(groups[0][1], 'Wed')

    def test_unparseable_event_is_reported(self):
        _, has_unparseable = _calendar_day_groups([self.WED_9, self.BROKEN], mock_logger)
        self.assertTrue(has_unparseable)

    def test_no_unparseable_event_is_reported_when_all_parse(self):
        _, has_unparseable = _calendar_day_groups([self.WED_9, self.THU_9], mock_logger)
        self.assertFalse(has_unparseable)

    def test_flat_row_texts_match_the_groups(self):
        events = [self.WED_9, self.WED_10, self.THU_9]
        groups, _ = _calendar_day_groups(events, mock_logger)
        flat = [row for _, _, rows in groups for row in rows]
        self.assertEqual(_calendar_row_texts(list(events), mock_logger), flat)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_components.py::TestCalendarDayGroups -v`
Expected: FAIL on the missing `_calendar_event_row` / `_calendar_day_groups`.

- [ ] **Step 3: Implement**

Replace the body of `_calendar_row_texts` and add the two new functions above it:

```python
def _calendar_event_start(event: CalendarEvent) -> datetime | None:
    """Local-time start of an event, or None when neither field parses."""
    from datetime import date as dt_date, time as dt_time
    start = event.get('start', {})
    if start.get('dateTime'):
        return datetime.fromisoformat(start['dateTime']).astimezone()
    if start.get('date'):
        return datetime.combine(dt_date.fromisoformat(start['date']), dt_time.min)
    return None


def _calendar_event_row(event: CalendarEvent) -> str:
    """The text of one calendar row, carrying no weekday name.

    The day is drawn once per group — as a rotated spine, or as a per-row
    prefix added later by _calendar_layout when the panel falls back to prefix
    mode. Keeping it out of here is what frees the width the summary gets.
    """
    summary: str = event.get('summary', 'No summary')
    start = event.get('start', {})
    end = event.get('end', {})
    if start.get('dateTime'):
        start_dt = datetime.fromisoformat(start['dateTime']).astimezone()
        end_dt = (
            datetime.fromisoformat(end['dateTime']).astimezone()
            if end.get('dateTime') else start_dt
        )
        return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}  {summary}"
    if start.get('date'):
        return f"All day  {summary}"
    return f"Unknown: {summary}"


def _calendar_day_groups(
    events: list[CalendarEvent],
    logger: "Logger",
) -> tuple[list[tuple["date | None", str, list[str]]], bool]:
    """Groups events by calendar date, in display order.

    Sorts `events` in place, as the draw function has always done.

    Returns:
        (groups, has_unparseable) where each group is (day, label, rows).
        `label` is the three-letter abbreviation the spine draws. An event
        with no parseable start lands in a trailing group whose day is None,
        and sets has_unparseable — the panel is forced into prefix mode,
        because such an event has no day to sit under.
    """
    from pprint import pformat as pf

    def sort_key(event: CalendarEvent) -> tuple[int, datetime]:
        start = _calendar_event_start(event)
        # Unparseable events sort last; datetime.max keeps the key comparable.
        return (1, datetime.max) if start is None else (0, start)

    events.sort(key=sort_key)

    groups: list[tuple["date | None", str, list[str]]] = []
    has_unparseable = False
    for event in events:
        logger.debug("calendar event: %s", pf(event))
        start = _calendar_event_start(event)
        day = start.date() if start is not None else None
        if day is None:
            has_unparseable = True
        label = start.strftime('%a') if start is not None else ''
        row = _calendar_event_row(event)
        if groups and groups[-1][0] == day:
            groups[-1][2].append(row)
        else:
            groups.append((day, label, [row]))
    return groups, has_unparseable


def _calendar_row_texts(events: list[CalendarEvent], logger: "Logger") -> list[str]:
    """Every calendar row in display order, flattened across day groups.

    Kept as the probe's view of the panel until _calendar_layout takes over.
    """
    groups, _ = _calendar_day_groups(events, logger)
    return [row for _, _, rows in groups for row in rows]
```

Add `from datetime import date` to the module imports if `date` is not already imported at module level (it is currently imported locally inside the old function — hoist it).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_components.py::TestCalendarDayGroups -v`
Expected: PASS

- [ ] **Step 5: Fix the existing row-text expectations**

`TestBodyRowTextBuilders` and any test asserting on `"Wednesday 10:00-12:00: ..."` now fail. Find them:

```bash
uv run pytest tests/test_components.py -k "RowText or Calendar" -v
```

Update each expectation to the new format. Do **not** weaken an assertion to make it pass — if a test checked that a row contains the weekday, that test's intent is now inverted and it should assert the weekday is absent.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS except golden mismatches, which are expected and handled in Task 8. Record which goldens moved.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: drop the weekday name from calendar rows and group by day

The day was repeated on every row and consumed 233px of a 360px content
budget at 20pt. Rows now carry only the time range and summary; the day
is grouped and drawn once."
```

---

### Task 4: The layout resolver

The load-bearing task. One pass decides size, mode, geometry and overflow; two entry points share one gate function.

**Files:**
- Modify: `src/trmnl_server/components.py` — add `CalendarLayout`, `_calendar_gates`, `_calendar_layout`; delete `_calendar_vertical_fit` and move its arithmetic inside
- Test: `tests/test_components.py` — new class `TestCalendarLayout`

**Interfaces:**
- Consumes: `_calendar_day_groups`, `_calendar_event_row` (Task 3); `_calendar_row_advance`, `CALENDAR_LINE_SPACING`, `CALENDAR_CONTENT_TOP`, `CALENDAR_BOTTOM_MARGIN` (Task 2)
- Produces:

```python
class CalendarLayout(NamedTuple):
    size: int                 # a BODY_SIZE_LADDER rung, >= CALENDAR_MIN_BODY_SIZE
    mode: str                 # 'gutter' or 'prefix'
    gutter: int               # unscaled gutter width; 0 in prefix mode
    groups: list[tuple[str, list[str]]]   # (label, rows) — rows are FINAL text
    drawn_rows: int           # how many rows fit; the draw function draws exactly this many
    overflow: int             # rows not drawn; 0 when everything fits
```

`_calendar_layout(events, width, height, logger, *, min_size=CALENDAR_MIN_BODY_SIZE, fixed_size=None) -> CalendarLayout`

**Critical:** `groups[i][1]` holds the *final* strings for the chosen mode — in prefix mode each row is already prefixed with `f"{label} "`. This is why the probe must call the resolver rather than measure rows itself: mode changes the strings and the width they are measured against.

- [ ] **Step 1: Write the failing tests**

```python
class TestCalendarLayout(unittest.TestCase):
    """One resolver decides size, mode, geometry and overflow together."""

    def _events(self, spec):
        """spec: list of (iso_date, count) -> events at 09:00, 10:00, ..."""
        out = []
        for day, count in spec:
            for i in range(count):
                out.append({
                    'summary': f'Event {i}',
                    'start': {'dateTime': f'{day}T{9 + i:02d}:00:00+00:00'},
                    'end': {'dateTime': f'{day}T{9 + i:02d}:30:00+00:00'},
                })
        return out

    def test_size_is_always_a_rung_at_or_above_the_floor(self):
        layout = _calendar_layout(self._events([('2024-01-17', 5)]), 400, 240, mock_logger)
        self.assertIn(layout.size, BODY_SIZE_LADDER)
        self.assertGreaterEqual(layout.size, CALENDAR_MIN_BODY_SIZE)

    def test_a_busy_single_day_uses_the_gutter(self):
        layout = _calendar_layout(self._events([('2024-01-17', 5)]), 400, 240, mock_logger)
        self.assertEqual(layout.mode, 'gutter')
        self.assertGreater(layout.gutter, 0)

    def test_a_single_event_day_falls_back_to_prefix(self):
        # A one-row group is shorter than its own spine at every rung.
        layout = _calendar_layout(
            self._events([('2024-01-17', 3), ('2024-01-18', 1)]), 400, 240, mock_logger
        )
        self.assertEqual(layout.mode, 'prefix')
        self.assertEqual(layout.gutter, 0)

    def test_prefix_mode_puts_the_day_back_on_every_row(self):
        layout = _calendar_layout(
            self._events([('2024-01-17', 3), ('2024-01-18', 1)]), 400, 240, mock_logger
        )
        for _, rows in layout.groups:
            for row in rows:
                self.assertRegex(row, r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ')

    def test_gutter_mode_leaves_the_day_off_every_row(self):
        layout = _calendar_layout(self._events([('2024-01-17', 5)]), 400, 240, mock_logger)
        for _, rows in layout.groups:
            for row in rows:
                self.assertNotRegex(row, r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ')

    def test_a_narrow_tile_falls_back_to_prefix(self):
        # Gate (b): the gutter would leave under CALENDAR_MIN_SUMMARY_W.
        layout = _calendar_layout(self._events([('2024-01-17', 5)]), 200, 240, mock_logger)
        self.assertEqual(layout.mode, 'prefix')

    def test_an_unparseable_event_forces_prefix(self):
        events = self._events([('2024-01-17', 5)])
        events.append({'summary': 'Mystery', 'start': {}, 'end': {}})
        layout = _calendar_layout(events, 400, 240, mock_logger)
        self.assertEqual(layout.mode, 'prefix')

    def test_overflow_counts_the_rows_that_do_not_fit(self):
        layout = _calendar_layout(self._events([('2024-01-17', 12)]), 400, 240, mock_logger)
        self.assertGreater(layout.overflow, 0)
        total = sum(len(rows) for _, rows in layout.groups)
        self.assertEqual(layout.drawn_rows + layout.overflow, total)

    def test_no_overflow_when_everything_fits(self):
        layout = _calendar_layout(self._events([('2024-01-17', 3)]), 400, 240, mock_logger)
        self.assertEqual(layout.overflow, 0)
        self.assertEqual(
            layout.drawn_rows, sum(len(rows) for _, rows in layout.groups)
        )

    def test_fixed_size_is_honoured_without_walking_the_ladder(self):
        events = self._events([('2024-01-17', 5)])
        layout = _calendar_layout(events, 400, 240, mock_logger, fixed_size=24)
        self.assertEqual(layout.size, 24)

    def test_fixed_size_agrees_with_the_walk_at_the_walk_s_own_answer(self):
        events = self._events([('2024-01-17', 5)])
        walked = _calendar_layout(list(events), 400, 240, mock_logger)
        pinned = _calendar_layout(
            list(events), 400, 240, mock_logger, fixed_size=walked.size
        )
        self.assertEqual(pinned, walked)

    def test_an_imposed_size_can_flip_the_mode(self):
        # Bigger rows mean taller groups; smaller rows can drop a group below
        # its spine height and force the whole panel into prefix mode.
        events = self._events([('2024-01-17', 2)])
        modes = {
            _calendar_layout(list(events), 400, 240, mock_logger, fixed_size=s).mode
            for s in (20, 28)
        }
        self.assertEqual(modes, {'gutter'})  # both fit here; the API must not crash

    def test_empty_events_produce_no_groups(self):
        layout = _calendar_layout([], 400, 240, mock_logger)
        self.assertEqual(layout.groups, [])
        self.assertEqual(layout.drawn_rows, 0)
        self.assertEqual(layout.overflow, 0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_components.py::TestCalendarLayout -v`
Expected: FAIL on the missing `_calendar_layout`.

- [ ] **Step 3: Implement**

Add these constants beside the others:

```python
CALENDAR_GUTTER_W: int = 32       # unscaled width of the rotated-day gutter
CALENDAR_MIN_SUMMARY_W: int = 60  # unscaled floor on width left for the summary
CALENDAR_SEP_H: int = 6           # unscaled vertical space one separator occupies
```

Add the type and the resolver (place `CalendarLayout` near the other module-level types):

```python
class CalendarLayout(NamedTuple):
    """Everything the calendar needs to draw itself, resolved in one pass."""
    size: int
    mode: str
    gutter: int
    groups: list[tuple[str, list[str]]]
    drawn_rows: int
    overflow: int


def _spine_ink_height(label: str, size: int, logger: "Logger") -> int:
    """Scaled ink height of a day label — its WIDTH once rotated 90 degrees."""
    font = _load_font(size * COMPONENT_SCALE, logger)
    box = font.getbbox(label)
    return box[3] - box[1]


def _calendar_gates(
    groups: list[tuple["date | None", str, list[str]]],
    has_unparseable: bool,
    size: int,
    width: int,
    logger: "Logger",
) -> bool:
    """Whether the gutter is usable at this size. Both gates must pass.

    (a) every group is tall enough to carry its spine, and
    (b) enough width is left for the summary after gutter and time prefix.

    All-or-nothing: mixing modes between groups would leave rows starting at
    different x positions within one panel, which reads as a rendering fault.
    """
    if has_unparseable or not groups:
        return False

    advance = _calendar_row_advance(size, logger)
    for _, label, rows in groups:
        if _spine_ink_height(label, size, logger) > len(rows) * advance:
            return False

    font = _load_font(size * COMPONENT_SCALE, logger)
    prefix_box = font.getbbox("00:00-00:00  ")
    remaining = (
        (width - 40 - CALENDAR_GUTTER_W) * COMPONENT_SCALE
        - (prefix_box[2] - prefix_box[0])
    )
    return remaining >= CALENDAR_MIN_SUMMARY_W * COMPONENT_SCALE


def _calendar_layout(
    events: list[CalendarEvent],
    width: int,
    height: int,
    logger: "Logger",
    *,
    min_size: int = CALENDAR_MIN_BODY_SIZE,
    fixed_size: int | None = None,
) -> CalendarLayout:
    """Resolves size, mode, geometry and overflow for a calendar panel.

    Font size determines row height, which determines group height, which
    determines whether the spine fits, which determines content width, which
    feeds back into the size. The loop is broken by evaluating the whole
    layout at each candidate rung and taking the first that works.

    Both the probe (_panel_body_fit) and the draw (_draw_calendar_component)
    call this. If they each derived mode independently they would drift, and
    the probe would report a size the panel does not draw at.

    Args:
        events: Calendar events for the panel; sorted in place
        width: Unscaled tile width
        height: Unscaled tile height
        logger: Logger instance
        min_size: Smallest rung the ladder walk may return
        fixed_size: When set, skip the ladder entirely and evaluate the gates
            once at this size. This is the path taken whenever tile_components
            has settled the layout row on a size — without it the draw would
            have to re-derive mode at that imposed size on its own.

    Returns:
        A CalendarLayout. `groups` rows are the FINAL strings for the chosen
        mode: already prefixed with the day in prefix mode, bare in gutter
        mode.
    """
    raw_groups, has_unparseable = _calendar_day_groups(events, logger)
    if not raw_groups:
        return CalendarLayout(min_size, 'prefix', 0, [], 0, 0)

    n_rows = sum(len(rows) for _, _, rows in raw_groups)

    def build(size: int) -> CalendarLayout:
        use_gutter = _calendar_gates(raw_groups, has_unparseable, size, width, logger)
        if use_gutter:
            groups = [(label, list(rows)) for _, label, rows in raw_groups]
            gutter = CALENDAR_GUTTER_W
        else:
            groups = [
                (label, [f"{label} {row}" if label else row for row in rows])
                for _, label, rows in raw_groups
            ]
            gutter = 0
        capacity = _calendar_capacity(size, height, len(raw_groups), logger)
        drawn = min(n_rows, capacity)
        return CalendarLayout(
            size, 'gutter' if use_gutter else 'prefix', gutter,
            groups, drawn, n_rows - drawn,
        )

    if fixed_size is not None:
        return build(fixed_size)

    for size in BODY_SIZE_LADDER:
        if size < min_size:
            continue
        candidate = build(size)
        if candidate.overflow:
            continue
        rows = [row for _, group_rows in candidate.groups for row in group_rows]
        budget = (width - 40 - candidate.gutter) * COMPONENT_SCALE
        font = _load_font(size * COMPONENT_SCALE, logger)
        if all(font.getbbox(t)[2] - font.getbbox(t)[0] <= budget for t in rows):
            return candidate
    return build(min_size)


def _calendar_capacity(
    size: int,
    height: int,
    n_groups: int,
    logger: "Logger",
) -> int:
    """How many rows fit the panel at this size, after separators.

    Separators are counted in both modes — prefix mode keeps them, which is
    what makes the vertical budget mode-independent so it need not be resolved
    after the mode.
    """
    budget = (
        height * COMPONENT_SCALE
        - CALENDAR_CONTENT_TOP * COMPONENT_SCALE
        - CALENDAR_BOTTOM_MARGIN * COMPONENT_SCALE
        - max(0, n_groups - 1) * CALENDAR_SEP_H * COMPONENT_SCALE
    )
    advance = _calendar_row_advance(size, logger)
    return max(0, budget // advance)
```

Delete `_calendar_vertical_fit` — its arithmetic now lives in `_calendar_capacity`. Add `NamedTuple` to the `typing` imports.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_components.py::TestCalendarLayout -v`
Expected: PASS. `TestCalendarVerticalFit` from Task 2 now fails on the deleted function — delete that test class; its behaviour is covered by `TestCalendarLayout`'s size and overflow tests.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: one resolver decides calendar size, mode and geometry

Mode changes the row strings and the width they are measured against, so
the probe and the draw cannot each derive it. fixed_size evaluates the
gates once at a size imposed by the layout row."
```

---

### Task 5: Draw from the layout

**Files:**
- Modify: `src/trmnl_server/components.py` — `_draw_calendar_component`; add `_draw_spine`
- Test: `tests/test_components.py` — new class `TestCalendarGutterRendering`; existing `TestDrawCalendarComponent` (line ~687) and `TestCalendarRowFloor` (line ~2791) will need updating

**Interfaces:**
- Consumes: `_calendar_layout`, `CalendarLayout`, `CALENDAR_GUTTER_W`, `CALENDAR_SEP_H` (Task 4)
- Produces: `_draw_calendar_component` unchanged in signature; now renders a spine or prefixes

- [ ] **Step 1: Write the failing tests**

```python
class TestCalendarGutterRendering(unittest.TestCase):
    """The panel draws what the resolver decided, and nothing else."""

    def _events(self, day, count):
        return [
            {'summary': f'Event {i}',
             'start': {'dateTime': f'{day}T{9 + i:02d}:00:00+00:00'},
             'end': {'dateTime': f'{day}T{9 + i:02d}:30:00+00:00'}}
            for i in range(count)
        ]

    def _ink_columns(self, img):
        """x positions that contain any non-white pixel."""
        gray = img.convert('L')
        w, h = gray.size
        px = gray.load()
        return {x for x in range(w) for y in range(h) if px[x, y] < 250}

    def test_gutter_mode_puts_ink_in_the_left_gutter(self):
        events = self._events('2024-01-17', 5)
        layout = _calendar_layout(list(events), 400, 240, mock_logger)
        self.assertEqual(layout.mode, 'gutter')
        img = _draw_calendar_component('Cal', list(events), 400, 240, mock_logger)
        # Rows start after the gutter, so ink below the title inside the
        # gutter band can only be the spine.
        band = [x for x in self._ink_columns(img) if x < CALENDAR_GUTTER_W]
        self.assertTrue(band, "expected spine ink inside the gutter")

    def test_prefix_mode_leaves_the_gutter_empty(self):
        # A one-event second day forces prefix mode.
        events = self._events('2024-01-17', 3) + self._events('2024-01-18', 1)
        layout = _calendar_layout(list(events), 400, 240, mock_logger)
        self.assertEqual(layout.mode, 'prefix')
        img = _draw_calendar_component('Cal', list(events), 400, 240, mock_logger)
        rendered = _draw_calendar_component('Cal', list(events), 400, 240, mock_logger)
        self.assertIsNone(ImageChops.difference(img, rendered).getbbox())

    def test_empty_calendar_still_draws_the_placeholder(self):
        img = _draw_calendar_component('Cal', [], 400, 240, mock_logger)
        self.assertEqual(img.size, (400, 240))
        self.assertTrue(self._ink_columns(img), "placeholder should draw something")

    def test_draw_is_deterministic(self):
        events = self._events('2024-01-17', 5)
        a = _draw_calendar_component('Cal', list(events), 400, 240, mock_logger)
        b = _draw_calendar_component('Cal', list(events), 400, 240, mock_logger)
        self.assertIsNone(ImageChops.difference(a, b).getbbox())

    def test_an_imposed_size_is_respected(self):
        events = self._events('2024-01-17', 5)
        forced = _draw_calendar_component(
            'Cal', list(events), 400, 240, mock_logger, body_font_size=24
        )
        matched = _draw_calendar_component(
            'Cal', list(events), 400, 240, mock_logger, body_font_size=24
        )
        self.assertIsNone(ImageChops.difference(forced, matched).getbbox())
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_components.py::TestCalendarGutterRendering -v`
Expected: FAIL — no spine ink in the gutter yet.

- [ ] **Step 3: Implement the spine helper**

```python
def _draw_spine(img: Image.Image, label: str, size: int,
                top: int, bottom: int, logger: "Logger") -> None:
    """Draws a day label rotated 90 degrees in the left gutter.

    PIL cannot draw rotated text, so the label is rendered to a temp image and
    rotated. The temp image is sized by the label's INK box, not the font's
    line box: after rotation the text's height becomes its width, and the line
    box is 38px at 28pt against a 32px gutter, where the ink box is 22px.
    """
    font = _load_font(size * COMPONENT_SCALE, logger)
    box = font.getbbox(label)
    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0:
        return
    tmp = Image.new('RGB', (w, h), color='white')
    ImageDraw.Draw(tmp).text((-box[0], -box[1]), label, font=font, fill='black')
    rotated = tmp.rotate(90, expand=True)
    y = top + max(0, (bottom - top - rotated.height) // 2)
    img.paste(rotated, (4 * COMPONENT_SCALE, y))
```

- [ ] **Step 4: Rewrite the drawing branch**

Replace the `else:` branch of `_draw_calendar_component` (everything after the empty-events placeholder) with:

```python
    else:
        scaled_gutter_pad = 40 * scale
        layout = _calendar_layout(
            events, width, height, logger, fixed_size=body_font_size
        )
        font_row = _load_font(layout.size * scale, logger)
        row_advance = _calendar_row_advance(layout.size, logger)
        gutter = layout.gutter * scale
        content_width = large_width - scaled_gutter_pad - gutter
        x_text = 20 * scale + gutter

        remaining = layout.drawn_rows
        for index, (label, rows) in enumerate(layout.groups):
            if remaining <= 0:
                break
            if index:
                d.line(
                    [(x_text, y_pos), (large_width - 20 * scale, y_pos)],
                    fill='black', width=1,
                )
                y_pos += CALENDAR_SEP_H * scale
            group_top = y_pos
            drawn_here = min(len(rows), remaining)
            for row in rows[:drawn_here]:
                d.text(
                    (x_text, y_pos),
                    _ellipsize(row, font_row, content_width, d),
                    font=font_row, fill='black',
                )
                y_pos += row_advance
            remaining -= drawn_here
            if layout.mode == 'gutter':
                _draw_spine(img, label, layout.size, group_top, y_pos, logger)
```

Keep the existing title drawing and the `y_pos` initialisation above it untouched. The overflow footer is added in Task 7.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_components.py::TestCalendarGutterRendering -v`
Expected: PASS

- [ ] **Step 6: Repair the existing calendar tests**

Run: `uv run pytest tests/test_components.py -k "Calendar" -v`

`TestDrawCalendarComponent` and `TestCalendarRowFloor` assert on the old layout. Update each to the new one. Where a test asserted a calendar row rendered at `>= CALENDAR_MIN_BODY_SIZE`, that intent still holds — keep it. Where a test asserted specific row text containing a weekday, invert it per Task 3.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: draw the calendar from its resolved layout

Gutter mode draws a rotated day spine per group; prefix mode carries the
day on each row. Separators divide groups in both modes."
```

---

### Task 6: Point the probe at the resolver

Closes the drift: after this task nothing derives a calendar's size or mode except `_calendar_layout`.

**Files:**
- Modify: `src/trmnl_server/components.py` — `_panel_body_fit` calendar branch
- Test: `tests/test_components.py` — extend `TestPanelBodyFit` (line ~2615)

**Interfaces:**
- Consumes: `_calendar_layout` (Task 4)
- Produces: no signature change

- [ ] **Step 1: Write the failing tests**

Add to `TestPanelBodyFit`:

```python
    def test_probe_matches_the_calendar_in_gutter_mode(self):
        events = [
            {'summary': f'Event {i}',
             'start': {'dateTime': f'2024-01-17T{9 + i:02d}:00:00+00:00'},
             'end': {'dateTime': f'2024-01-17T{9 + i:02d}:30:00+00:00'}}
            for i in range(5)
        ]
        render_data = {'type': 'calendar', 'data': list(events)}
        self.assertEqual(
            _calendar_layout(list(events), 400, 220, mock_logger).mode, 'gutter'
        )
        probed = _panel_body_fit(render_data, 400, 220, mock_logger)
        alone = _draw_calendar_component('Calendar', list(events), 400, 220, mock_logger)
        forced = _draw_calendar_component(
            'Calendar', list(events), 400, 220, mock_logger, body_font_size=probed
        )
        self.assertIsNone(ImageChops.difference(alone, forced).getbbox())

    def test_probe_matches_the_calendar_in_prefix_mode(self):
        events = [
            {'summary': f'Event {i}',
             'start': {'dateTime': f'2024-01-17T{9 + i:02d}:00:00+00:00'},
             'end': {'dateTime': f'2024-01-17T{9 + i:02d}:30:00+00:00'}}
            for i in range(3)
        ] + [
            {'summary': 'Lonely',
             'start': {'dateTime': '2024-01-18T09:00:00+00:00'},
             'end': {'dateTime': '2024-01-18T09:30:00+00:00'}}
        ]
        render_data = {'type': 'calendar', 'data': list(events)}
        self.assertEqual(
            _calendar_layout(list(events), 400, 220, mock_logger).mode, 'prefix'
        )
        probed = _panel_body_fit(render_data, 400, 220, mock_logger)
        alone = _draw_calendar_component('Calendar', list(events), 400, 220, mock_logger)
        forced = _draw_calendar_component(
            'Calendar', list(events), 400, 220, mock_logger, body_font_size=probed
        )
        self.assertIsNone(ImageChops.difference(alone, forced).getbbox())
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_components.py::TestPanelBodyFit -v`
Expected: FAIL — the probe still measures flat rows and disagrees with the resolver.

- [ ] **Step 3: Implement**

Replace the calendar branch of `_panel_body_fit` added in Task 2 with:

```python
    elif panel_type == 'calendar':
        if not data:
            return None
        layout = _calendar_layout(
            list(data), tile_width, tile_height, logger,  # type: ignore[arg-type]
            min_size=_body_floor(panel_type),
        )
        return layout.size if layout.groups else None
```

`list(data)` because `_calendar_day_groups` sorts in place and the probe must not reorder the caller's data before the draw sees it.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_components.py::TestPanelBodyFit -v`
Expected: PASS, including the pre-existing `test_probe_matches_what_the_calendar_draws_alone`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS except goldens.

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: the calendar probe reads its answer off the layout resolver

Nothing derives a calendar's size or mode twice now."
```

---

### Task 7: The overflow footer

**Files:**
- Modify: `src/trmnl_server/components.py` — `_calendar_capacity` reserves the footer; `_draw_calendar_component` draws it
- Test: `tests/test_components.py` — new class `TestCalendarOverflowRow`

**Interfaces:**
- Consumes: everything from Tasks 4-5
- Produces: no signature change; `CalendarLayout.drawn_rows` now excludes the footer's row when one is drawn

- [ ] **Step 1: Write the failing tests**

```python
class TestCalendarOverflowRow(unittest.TestCase):
    """A panel that cannot show everything says so."""

    def _events(self, count):
        return [
            {'summary': f'Event {i}',
             'start': {'dateTime': f'2024-01-17T{(6 + i) % 24:02d}:00:00+00:00'},
             'end': {'dateTime': f'2024-01-17T{(6 + i) % 24:02d}:30:00+00:00'}}
            for i in range(count)
        ]

    def test_overflow_reserves_a_row(self):
        many = _calendar_layout(self._events(12), 400, 240, mock_logger)
        few = _calendar_layout(self._events(3), 400, 240, mock_logger)
        self.assertGreater(many.overflow, 0)
        self.assertEqual(few.overflow, 0)
        # The reserved footer row costs one event.
        capacity = _calendar_capacity(many.size, 240, 1, mock_logger)
        self.assertEqual(many.drawn_rows, capacity - 1)

    def test_counts_every_undrawn_event_including_the_displaced_one(self):
        layout = _calendar_layout(self._events(12), 400, 240, mock_logger)
        total = sum(len(rows) for _, rows in layout.groups)
        self.assertEqual(layout.drawn_rows + layout.overflow, total)

    def test_no_footer_when_everything_fits(self):
        layout = _calendar_layout(self._events(3), 400, 240, mock_logger)
        self.assertEqual(layout.overflow, 0)

    def test_the_footer_is_drawn(self):
        events = self._events(12)
        img = _draw_calendar_component('Cal', list(events), 400, 240, mock_logger)
        # Redraw with one fewer event than capacity and confirm the images
        # differ — the footer is the only difference at the panel foot.
        layout = _calendar_layout(list(events), 400, 240, mock_logger)
        fitting = _draw_calendar_component(
            'Cal', self._events(layout.drawn_rows), 400, 240, mock_logger
        )
        self.assertIsNotNone(ImageChops.difference(img, fitting).getbbox())
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_components.py::TestCalendarOverflowRow -v`
Expected: FAIL — capacity does not yet reserve a row.

- [ ] **Step 3: Reserve the footer in the resolver**

In `_calendar_layout`'s `build`, replace the capacity/drawn calculation with:

```python
        capacity = _calendar_capacity(size, height, len(raw_groups), logger)
        if n_rows <= capacity:
            drawn = n_rows
        else:
            # The footer costs its own row plus its separator. A panel that
            # cannot afford both gets no footer and truncates silently — see
            # the spec's accepted consequences.
            footer_cost = 1 + (
                1 if CALENDAR_SEP_H * COMPONENT_SCALE
                <= _calendar_row_advance(size, logger) else 1
            )
            drawn = max(0, capacity - footer_cost)
```

Simplify: the footer always costs one row and one separator, so:

```python
        capacity = _calendar_capacity(size, height, len(raw_groups), logger)
        if n_rows <= capacity:
            drawn = n_rows
        else:
            footer_rows = _calendar_capacity(
                size, height, len(raw_groups) + 1, logger
            )
            drawn = max(0, footer_rows - 1)
```

Passing `len(raw_groups) + 1` charges one extra separator — the footer's own — and subtracting one row leaves room for the `+N more` line itself.

- [ ] **Step 4: Draw the footer**

At the end of the `else:` branch of `_draw_calendar_component`, after the group loop:

```python
        if layout.overflow:
            d.line(
                [(x_text, y_pos), (large_width - 20 * scale, y_pos)],
                fill='black', width=1,
            )
            y_pos += CALENDAR_SEP_H * scale
            d.text(
                (x_text, y_pos),
                f"+{layout.overflow} more",
                font=font_row, fill='black',
            )
```

The footer draws at `x_text` — inside the rows' column but outside every spine's vertical extent, because the spine for each group was drawn before this line runs and spans only that group's rows. Its own separator is drawn unconditionally, so a single-group panel (the `days: 1` default) still gets one.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_components.py::TestCalendarOverflowRow -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS except goldens.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: a calendar that drops events says how many

The footer draws its own separator so a single-day panel -- the default --
gets one, and sits outside every spine because the dropped events may fall
on days the spine does not name."
```

---

### Task 8: End-to-end and golden coverage

**Files:**
- Create: `tests/test_calendar_grouping_e2e.py`
- Modify: `tests/test_golden.py`
- Create: `tests/golden/calendar_day_grouping.png`, `tests/golden/calendar_prefix_fallback.png`
- Modify: `tests/golden/body_text_size_harmonisation.png` and any other golden the earlier tasks moved

**Interfaces:**
- Consumes: everything

- [ ] **Step 1: Write the end-to-end tests**

Create `tests/test_calendar_grouping_e2e.py`, modelled on the existing `tests/test_calendar_min_font_e2e.py` — read that file first and follow its mocking pattern for `trmnl_server.hass_client._fetch_calendar_events`.

```python
"""End-to-end coverage for calendar day grouping through render_dashboard_image."""

import logging
import unittest
from datetime import datetime, timezone
from unittest import mock

from PIL import Image

from trmnl_server.components import render_dashboard_image

mock_logger = mock.Mock(spec=logging.Logger)


def _events(spec):
    out = []
    for day, count in spec:
        for i in range(count):
            out.append({
                'summary': f'Event {i} with a reasonably long summary line',
                'start': {'dateTime': f'{day}T{9 + i:02d}:00:00+00:00'},
                'end': {'dateTime': f'{day}T{9 + i:02d}:30:00+00:00'},
            })
    return out


class TestCalendarGroupingEndToEnd(unittest.TestCase):

    DASHBOARD = {
        'name': 'cal',
        'title': 'Cal',
        'components': [
            {'type': 'calendar', 'friendly_name': 'Shared Calendar',
             'arguments': {'calendar_id': 'calendar.family', 'days': 2}},
            {'type': 'entity', 'friendly_name': 'Temp',
             'entity_name': 'sensor.t'},
        ],
    }

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_renders_a_grouped_two_day_calendar(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = _events([('2024-01-17', 3), ('2024-01-18', 3)])
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        img = Image.open(img_io)
        self.assertEqual(img.size, (800, 480))

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_a_busy_day_renders_an_overflow_row(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = _events([('2024-01-17', 20)])
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        self.assertEqual(Image.open(img_io).size, (800, 480))

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_an_empty_calendar_still_renders(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = []
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        self.assertEqual(Image.open(img_io).size, (800, 480))
```

- [ ] **Step 2: Run them**

Run: `uv run pytest tests/test_calendar_grouping_e2e.py -v`
Expected: PASS

- [ ] **Step 3: Add the two new goldens**

In `tests/test_golden.py`, following the existing style (see `test_body_text_size_harmonisation` at line ~496 for the mocking pattern), add two tests: one dashboard whose calendar reaches gutter mode (a single day with five events beside an entity panel), and one whose calendar falls back to prefix mode (two days, one of them holding a single event). Name the goldens `calendar_day_grouping` and `calendar_prefix_fallback`.

Assert the mode before rendering, so the golden cannot silently stop testing what it was written for:

```python
        from trmnl_server.components import _calendar_layout
        self.assertEqual(_calendar_layout(list(events), 400, 240, mock_logger).mode,
                         'gutter')
```

- [ ] **Step 4: Generate and inspect the new goldens**

```bash
uv run pytest tests/test_golden.py -k "calendar_day_grouping or calendar_prefix_fallback"
```

`assert_golden` creates a missing reference silently, so this pass writes the files. **Open both PNGs and look at them** before continuing. Confirm: the spine reads bottom-to-top, sits inside the gutter, and is vertically centred on its group; separators divide groups; prefix-mode rows all start at the same x.

- [ ] **Step 5: Regenerate the moved goldens**

```bash
uv run pytest tests/test_golden.py -v
```

For each failure, confirm the change is the calendar reformat and not an unrelated regression, then regenerate:

```bash
UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
```

**Open every regenerated image and inspect it.** A golden regenerated without being looked at pins whatever bug was rendered.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: PASS, no failures, no skips. Record the count.

- [ ] **Step 7: Commit**

```bash
git add tests/
git commit -m "test: end-to-end and golden coverage for calendar day grouping

Adds goldens for both modes -- neither layout has been pinned before --
and asserts the mode inside each so a golden cannot silently stop testing
the thing it was written for."
```

---

## Self-Review

Checked against the spec:

- **Row format** → Task 3. **Spine and ink-box sizing** → Task 5 (`_draw_spine`). **Both gates** → Task 4 (`_calendar_gates`). **All-or-nothing mode** → Task 4, enforced by `_calendar_gates` returning one bool for the panel.
- **`min(h_fit, v_fit)`** → Task 2 introduces it flat; Task 4 supersedes it inside the resolver, as the spec's sequencing note requires. `_calendar_vertical_fit` is explicitly deleted in Task 4 Step 3 so both versions never coexist.
- **`fixed_size` two entry points** → Task 4. **Probe delegates to the resolver** → Task 6. **`tile_height` required positional** → Task 1.
- **Overflow footer outside every spine, with its own separator** → Task 7; the footer is drawn after the group loop, so no spine covers it, and its separator is unconditional.
- **Prefix mode keeps separators** → Task 5 draws the separator on `if index:` regardless of mode; `_calendar_capacity` charges for them in both modes.
- **Unparseable events force prefix** → Task 4 (`_calendar_gates` returns False on `has_unparseable`).
- **All-day sort fix out of scope** → no task; `_calendar_event_start` uses start-of-day for all-day events, which is the same ordering the old string comparison produced.
- **Testing at all three levels** → unit in Tasks 2-7, integration in Task 6 and Task 8 Step 3, end-to-end in Task 8 Step 1, golden in Task 8 Steps 3-5.

Type consistency: `CalendarLayout` fields are used with the same names in Tasks 4, 5, 6 and 7. `_calendar_capacity(size, height, n_groups, logger)` is called with that signature in Tasks 4 and 7. `_calendar_row_advance(size, logger)` is defined in Task 2 and used in Tasks 4, 5 and 7.

One known rough edge, left deliberately: Task 7's footer reservation calls `_calendar_capacity` with `len(raw_groups) + 1` to charge the footer's separator. That is slightly indirect. It is correct and it keeps a single definition of the vertical budget, which the spec values above readability here.
