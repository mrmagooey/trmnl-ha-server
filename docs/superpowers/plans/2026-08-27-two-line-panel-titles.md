# Two-Line Panel Titles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dashboard row resolves a title font size *and* a line count together, so a long title wraps to two lines instead of dragging its whole row down the size ladder.

**Architecture:** `tile_components` evaluates each row twice — once at one line, once at two with a band-height cap — and wraps only when that raises the row's size. Both values pass to every panel in the row. Each drawing function reserves a title band and starts its content beneath it, but only when the title actually wraps; at one line every content origin keeps its literal existing constant, so existing rendering is byte-identical by construction, **except** the entity component's value height clause (see the carve-out below).

**Tech Stack:** Python 3, Pillow 12 (PIL), `unittest`, `pytest` via `uv`.

**Spec:** `docs/superpowers/specs/2026-08-27-two-line-panel-titles-design.md`

## Global Constraints

- Branch `feature/two-line-panel-titles`. Do not commit to `main` or to `feature/standardise-panel-title-font-size`.
- Run tests with `uv run pytest` from the repo root. There is NO bare `python` on PATH — use `uv run python`.
- Exact constant values: `TITLE_MAX_LINES = 2`, `TITLE_WRAP_MIN_GAIN = 1`, `TITLE_LINE_SPACING = 4`, `TITLE_BAND_GAP = 4`, `TITLE_BAND_MAX_PERCENT = 45`.
- Measured band heights, unscaled, `(1 line, 2 lines)`: rung 35 `(46, 87)`, 30 `(39, 76)`, 26 `(34, 66)`, 22 `(29, 57)`, 18 `(24, 47)`. Tests assert these.
- **Byte-identity at one line is the safety property of this whole change.** At `title_lines == 1` every content origin uses its literal existing constant unconditionally. Never write `max(LEGACY, band)` on the one-line path — the one-line band at rung 35 is 46px, which exceeds the graph's 40px margin and would shift every graph.
- **Carve-out:** `_draw_entity_component`'s value-height clause (`or value_bbox[3] > avail_h`) and its `value_y = max(avail_top, value_y)` clamp are deliberately *unconditional*, not gated on `title_lines > 1`. This is a genuine exception to byte-identity at one line, not an oversight: on tiles shorter than ~183px, a narrow value (e.g. `"72"`) never triggers the pre-existing width-shrink loop, so before this change it stayed at the maximum font and was clipped top and bottom (e.g. `21.5` rendered as `21 5`, its decimal point cut off). Keeping the clause unconditional fixes that pre-existing clipping bug even at one line; gating it on `title_lines > 1` would leave the bug in place for every row that never wraps.
- All 9 existing golden images must stay byte-identical. Two golden tests fail at the branch point already — `test_entity_attribute_dashboard` and `test_history_graph_bipolar` — from stale references, red on `main` too. Those two are expected. ANY other golden failure is a real regression: fix the code, never regenerate a golden to make it pass.
- Do NOT run `UPDATE_GOLDEN=1`. Only Task 6 adds a golden, and only its own.
- `spacing` for the title band is `TITLE_LINE_SPACING * COMPONENT_SCALE`. `spacing` for the entity *value* is `4` ABSOLUTE (PIL's default, not scaled). Do not conflate them.
- Follow file conventions: explicit local type annotations, docstrings with `Args:`/`Returns:`.

---

### Task 1: Constants, `_wrap_title`, `_title_band_height`

**Files:**
- Modify: `src/trmnl_server/components.py` (constants near line 20; helpers after `_ellipsize`, which ends ~line 135)
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_load_font(size, logger)`, `COMPONENT_SCALE`, `TITLE_SIZE_LADDER`.
- Produces: `TITLE_MAX_LINES`, `TITLE_WRAP_MIN_GAIN`, `TITLE_LINE_SPACING`, `TITLE_BAND_GAP`, `TITLE_BAND_MAX_PERCENT`, `_wrap_title(text, font, max_width, max_lines) -> list[str] | None`, `_title_band_height(font_size, lines, logger) -> int`.

- [ ] **Step 1: Write the failing tests**

Extend the existing parenthesised import block in `tests/test_components.py` with `_wrap_title`, `_title_band_height`, `TITLE_MAX_LINES`, `TITLE_BAND_MAX_PERCENT`. Then add:

```python
class TestWrapTitle(unittest.TestCase):
    """Greedy pixel word wrap for panel titles."""

    def _font(self, size=35):
        return _load_font(size * COMPONENT_SCALE, mock_logger)

    def test_short_text_returns_single_line(self):
        self.assertEqual(_wrap_title("CPU", self._font(), 760, 2), ["CPU"])

    def test_wraps_onto_two_lines_when_needed(self):
        lines = _wrap_title("Back Garden Soil Moisture Level", self._font(), 760, 2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(" ".join(lines), "Back Garden Soil Moisture Level")

    def test_never_breaks_a_word(self):
        lines = _wrap_title("Supercalifragilistic Expialidocious", self._font(), 760, 2)
        for line in lines or []:
            for word in line.split():
                self.assertIn(word, "Supercalifragilistic Expialidocious")

    def test_returns_none_when_more_lines_needed(self):
        self.assertIsNone(
            _wrap_title("One Two Three Four Five Six Seven Eight Nine Ten", self._font(), 200, 2)
        )

    def test_single_unbreakable_word_returns_one_line(self):
        # A word that cannot fit is still returned; _ellipsize handles it later.
        self.assertEqual(_wrap_title("Supercalifragilistic", self._font(), 50, 2),
                         ["Supercalifragilistic"])

    def test_empty_string(self):
        self.assertEqual(_wrap_title("", self._font(), 760, 2), [""])

    def test_every_returned_line_fits_when_not_none(self):
        font = self._font(18)
        lines = _wrap_title("Back Garden Soil Moisture Level", font, 400, 2)
        if lines is not None and len(lines) > 1:
            for line in lines:
                self.assertLessEqual(font.getbbox(line)[2] - font.getbbox(line)[0], 400)


class TestTitleBandHeight(unittest.TestCase):
    """Band height must match the measured table the design was calibrated on."""

    EXPECTED = {35: (46, 87), 30: (39, 76), 26: (34, 66), 22: (29, 57), 18: (24, 47)}

    def test_matches_measured_table(self):
        for size, (one, two) in self.EXPECTED.items():
            self.assertEqual(_title_band_height(size, 1, mock_logger), one, f"rung {size}, 1 line")
            self.assertEqual(_title_band_height(size, 2, mock_logger), two, f"rung {size}, 2 lines")

    def test_two_lines_always_taller_than_one(self):
        for size in TITLE_SIZE_LADDER:
            self.assertGreater(_title_band_height(size, 2, mock_logger),
                               _title_band_height(size, 1, mock_logger))

    def test_one_line_band_at_top_rung_exceeds_graph_margin(self):
        """Guards the reason the 1-line path must NOT use max(40, band)."""
        self.assertGreater(_title_band_height(35, 1, mock_logger), 40)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k "WrapTitle or TitleBandHeight" -v`
Expected: FAIL at import — `ImportError: cannot import name '_wrap_title'`.

- [ ] **Step 3: Add the constants**

Beside the existing title constants near line 20:

```python
TITLE_MAX_LINES: int = 2
# A wrap must gain at least this many ladder rungs for a row to spend the
# vertical space on a second title line.
TITLE_WRAP_MIN_GAIN: int = 1
TITLE_LINE_SPACING: int = 4
TITLE_BAND_GAP: int = 4
# A title band may not consume more than this share of its tile's height.
TITLE_BAND_MAX_PERCENT: int = 45
```

- [ ] **Step 4: Add the helpers**

After `_ellipsize`:

```python
def _wrap_title(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str] | None:
    """Wraps a title onto at most max_lines, breaking only at spaces.

    Measures with the font's own getbbox so it can run before any canvas
    exists. A single word wider than max_width is returned on its own line
    rather than broken; callers ellipsize such a line.

    Args:
        text: The title string
        font: Font the title will be drawn with
        max_width: Available width in the same (scaled) units as the font
        max_lines: Maximum number of lines permitted

    Returns:
        The wrapped lines, or None if the text needs more than max_lines
    """
    words: list[str] = text.split()
    if not words:
        return [text]

    lines: list[str] = []
    current: str = words[0]
    for word in words[1:]:
        candidate: str = current + " " + word
        bbox = font.getbbox(candidate)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)

    return lines if len(lines) <= max_lines else None


def _title_band_height(font_size: int, lines: int, logger: "Logger") -> int:
    """Height reserved below a title's anchor for the given line count.

    Measured through the same PIL routine the drawing functions paint with, so
    the reserved band and the painted extent cannot diverge. Uses a fixed
    "Ag" ascender/descender probe so the band does not vary with the glyphs of
    a particular title.

    Args:
        font_size: Unscaled title font size
        lines: Number of title lines
        logger: Logger instance

    Returns:
        Unscaled height from the title anchor to the bottom of its ink
    """
    font = _load_font(font_size * COMPONENT_SCALE, logger)
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    bbox = probe.multiline_textbbox(
        (0, 0),
        "\n".join(["Ag"] * max(1, lines)),
        font=font,
        spacing=TITLE_LINE_SPACING * COMPONENT_SCALE,
    )
    return bbox[3] // COMPONENT_SCALE
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k "WrapTitle or TitleBandHeight" -v`
Expected: PASS, 10 tests.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: the same result as before this task — nothing calls the new helpers yet. Only `test_entity_attribute_dashboard` and `test_history_graph_bipolar` may fail.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: add title wrapping and band-height helpers"
```

---

### Task 2: `_fit_title_size` gains `lines` and `max_band`

**Files:**
- Modify: `src/trmnl_server/components.py` — `_fit_title_size` at line 88
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_wrap_title`, `_title_band_height` from Task 1.
- Produces: `_fit_title_size(text, tile_width, logger, *, lines: int = 1, max_band: int | None = None) -> int | None`.

- [ ] **Step 1: Write the failing tests**

```python
class TestFitTitleSizeWithLines(unittest.TestCase):
    """Two-line fitting and the band-height cap."""

    LONG = "Back Garden Soil Moisture Level"

    def test_two_lines_reaches_a_higher_rung_than_one(self):
        one = _fit_title_size(self.LONG, 400, mock_logger)
        two = _fit_title_size(self.LONG, 400, mock_logger, lines=2)
        self.assertEqual(one, 22)
        self.assertEqual(two, 35)

    def test_default_call_is_unchanged(self):
        self.assertEqual(_fit_title_size("CPU", 400, mock_logger), 35)

    def test_max_band_caps_the_rung(self):
        # 146px tile -> cap 65 -> rung 22 (57) is the largest 2-line band that fits.
        self.assertEqual(
            _fit_title_size(self.LONG, 400, mock_logger, lines=2, max_band=65), 22
        )

    def test_returns_none_when_cap_excludes_every_rung(self):
        # 88px tile -> cap 39 -> below rung 18's 2-line band of 47.
        self.assertIsNone(
            _fit_title_size(self.LONG, 400, mock_logger, lines=2, max_band=39)
        )

    def test_none_only_ever_happens_with_max_band(self):
        for width in (10, 50, 200, 800):
            self.assertIsNotNone(_fit_title_size(self.LONG, width, mock_logger))
            self.assertIsNotNone(_fit_title_size(self.LONG, width, mock_logger, lines=2))

    def test_result_is_always_a_ladder_member_or_none(self):
        for cap in (30, 39, 47, 65, 99, None):
            got = _fit_title_size(self.LONG, 400, mock_logger, lines=2, max_band=cap)
            self.assertTrue(got is None or got in TITLE_SIZE_LADDER)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k FitTitleSizeWithLines -v`
Expected: FAIL — `TypeError: _fit_title_size() got an unexpected keyword argument 'lines'`.

- [ ] **Step 3: Rewrite `_fit_title_size`**

Replace the function at line 88 with:

```python
def _fit_title_size(
    text: str,
    tile_width: int,
    logger: "Logger",
    *,
    lines: int = 1,
    max_band: int | None = None,
) -> int | None:
    """Picks the largest ladder rung whose title fits the given tile width.

    Runs before any canvas exists, so it measures with the font's own getbbox
    rather than ImageDraw.textbbox.

    Args:
        text: The title string that will be drawn
        tile_width: Unscaled width of the tile the title must fit
        logger: Logger instance
        lines: Maximum title lines to wrap onto
        max_band: Unscaled cap on the title band's height, or None for no cap

    Returns:
        A size from TITLE_SIZE_LADDER; the smallest rung if none fit. Returns
        None only when max_band is given and excludes every rung.
    """
    budget: int = (tile_width - TITLE_PADDING) * COMPONENT_SCALE
    for size in TITLE_SIZE_LADDER:
        if max_band is not None and _title_band_height(size, lines, logger) > max_band:
            continue
        font = _load_font(size * COMPONENT_SCALE, logger)
        wrapped = _wrap_title(text, font, budget, lines)
        if wrapped is None:
            continue
        if all(font.getbbox(line)[2] - font.getbbox(line)[0] <= budget for line in wrapped):
            return size

    if max_band is not None:
        # Every rung either overflowed the band cap or could not be wrapped.
        # Distinguish "cap excluded everything" from "nothing fitted the width".
        if all(
            _title_band_height(size, lines, logger) > max_band
            for size in TITLE_SIZE_LADDER
        ):
            return None
    return TITLE_SIZE_LADDER[-1]
```

Note the single-line path is unchanged in behaviour: with `lines=1`,
`_wrap_title` returns one line for any text, and with `max_band=None` the cap
branches are skipped entirely.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k FitTitleSizeWithLines -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Run the existing `_fit_title_size` tests**

Run: `uv run pytest tests/test_components.py -k "FitTitleSize or RowTitleSizeHarmonisation" -q`
Expected: PASS. The pre-existing single-line tests must be untouched.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: only the two known golden failures.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: fit titles across multiple lines with a band cap"
```

---

### Task 3: Two-line titles in calendar, entities and todo

**Files:**
- Modify: `src/trmnl_server/components.py` — `_todo_capacity` (825), `_draw_calendar_component` (611, `y_pos` at 661), `_draw_entities_component` (728, `y_pos` at 776), `_draw_todo_list_component` (844, `header_y` at 931)
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_wrap_title`, `_title_band_height`, `TITLE_LINE_SPACING`, `TITLE_BAND_GAP`.
- Produces: these three functions gain keyword-only `title_lines: int = 1`; `_todo_capacity(height, columns, title_font_size=COMPONENT_TITLE_FONT_SIZE, title_lines=1)`.

- [ ] **Step 1: Write the failing tests**

```python
class TestTwoLineSimpleComponents(unittest.TestCase):
    """Calendar, entities and todo honour a two-line title band."""

    LONG = "Back Garden Soil Moisture Level"

    def test_calendar_accepts_title_lines(self):
        img = _draw_calendar_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_entities_accepts_title_lines(self):
        img = _draw_entities_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_todo_accepts_title_lines(self):
        img = _draw_todo_list_component(self.LONG, [], 400, 220, mock_logger,
                                        title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_two_lines_differs_from_one(self):
        one = _draw_calendar_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=1)
        two = _draw_calendar_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=2)
        self.assertNotEqual(one.tobytes(), two.tobytes())

    def test_one_line_default_is_unchanged(self):
        a = _draw_entities_component("Short", [], 400, 220, mock_logger, title_font_size=35)
        b = _draw_entities_component("Short", [], 400, 220, mock_logger,
                                     title_font_size=35, title_lines=1)
        self.assertEqual(a.tobytes(), b.tobytes())


class TestTodoCapacityWithBand(unittest.TestCase):
    """Pagination must use the same header height the panel draws."""

    def test_one_line_matches_legacy_constant(self):
        self.assertEqual(_todo_capacity(220, 1), _todo_capacity(220, 1, 35, 1))

    def test_two_lines_reduces_capacity(self):
        one = _todo_capacity(220, 1, 35, 1)[1]
        two = _todo_capacity(220, 1, 35, 2)[1]
        self.assertLess(two, one)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k "TwoLineSimpleComponents or TodoCapacityWithBand" -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'title_lines'`.

- [ ] **Step 3: Update `_todo_capacity`**

```python
def _todo_capacity(
    height: int,
    columns: int,
    title_font_size: int = COMPONENT_TITLE_FONT_SIZE,
    title_lines: int = 1,
    logger: "Logger | None" = None,
) -> tuple[int, int]:
```

Inside, replace `body = height - TODO_HEADER_H - TODO_BOTTOM_PAD` with:

```python
    if title_lines > 1 and logger is not None:
        header = max(
            TODO_HEADER_H,
            5 + _title_band_height(title_font_size, title_lines, logger) + TITLE_BAND_GAP,
        )
    else:
        header = TODO_HEADER_H
    body = height - header - TODO_BOTTOM_PAD
```

Document the new parameters in the docstring. At one line the value is
`TODO_HEADER_H` exactly, so existing callers are unaffected.

- [ ] **Step 4: Update the three drawing functions**

For each of `_draw_calendar_component`, `_draw_entities_component` and
`_draw_todo_list_component`, add `title_lines: int = 1` to the keyword-only
block and document it. Then, where each currently ellipsizes and draws a
single-line title, replace with:

```python
    title_lines_text: list[str] = _wrap_title(
        title_text, font_title, large_width - TITLE_PADDING * scale, max(1, title_lines)
    ) or [title_text]
    title_lines_text = [
        _ellipsize(line, font_title, large_width - TITLE_PADDING * scale, d)
        for line in title_lines_text
    ]
    rendered_title: str = "\n".join(title_lines_text)
    text_bbox = d.multiline_textbbox((0, 0), rendered_title, font=font_title,
                                     spacing=TITLE_LINE_SPACING * scale)
    text_width = text_bbox[2] - text_bbox[0]
    d.multiline_text(
        ((large_width - text_width) / 2, 5 * scale), rendered_title,
        font=font_title, fill='black', align='center',
        spacing=TITLE_LINE_SPACING * scale,
    )
```

`title_text` is whatever string that function already drew — for todo that is
the composed `f"{friendly_name} ({total})"`, NOT the bare name.

Then change each content origin. In calendar and entities:

```python
    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        y_pos: int = max(50 * scale, 5 * scale + band + TITLE_BAND_GAP * scale)
    else:
        y_pos = 50 * scale
```

In todo, the same shape for `header_y`, using `TODO_HEADER_H * scale` as the
legacy value. **Do not write `max(50 * scale, band)` on the one-line path** —
the one-line branch must be the bare literal.

Todo must also pass its own size and lines to `_todo_capacity` if it calls it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k "TwoLineSimpleComponents or TodoCapacityWithBand" -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: only the two known golden failures. Nothing passes `title_lines > 1` yet, so every golden must be unchanged.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: two-line titles for calendar, entities and todo"
```

---

### Task 4: Two-line titles in the graph component

**Files:**
- Modify: `src/trmnl_server/components.py` — `_draw_graph_component` (247), `margin` at 315
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_wrap_title`, `_title_band_height`, `TITLE_BAND_GAP`.
- Produces: `_draw_graph_component` gains keyword-only `title_lines: int = 1`.

**The margin split is the whole risk of this task.** `margin` is used as BOTH a horizontal and a vertical measure, sometimes in the same statement. Line 365 is `[(margin, margin), (margin, large_height - margin)]`: the first `margin` is an x, the second is the vertical TOP, the third is an x, the fourth is the vertical BOTTOM.

- [ ] **Step 1: Write the failing tests**

```python
class TestGraphTwoLineTitle(unittest.TestCase):
    """The graph reserves a taller top margin only when its title wraps."""

    def _points(self):
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        return start, end, [(start, 1.0), (end, 2.0)]

    def test_accepts_title_lines(self):
        start, end, pts = self._points()
        img = _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                    mock_logger, window_start=start, window_end=end,
                                    title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_two_lines_differs_from_one(self):
        start, end, pts = self._points()
        kw = dict(window_start=start, window_end=end, title_font_size=35)
        one = _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                    mock_logger, title_lines=1, **kw)
        two = _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                    mock_logger, title_lines=2, **kw)
        self.assertNotEqual(one.tobytes(), two.tobytes())

    def test_one_line_is_byte_identical_to_omitting_the_argument(self):
        """The 1-line path must not route through max(40*scale, band)."""
        start, end, pts = self._points()
        kw = dict(window_start=start, window_end=end, title_font_size=35)
        a = _draw_graph_component("CPU", pts, 400, 220, mock_logger, **kw)
        b = _draw_graph_component("CPU", pts, 400, 220, mock_logger, title_lines=1, **kw)
        self.assertEqual(a.tobytes(), b.tobytes())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k GraphTwoLineTitle -v`
Expected: FAIL — unexpected keyword argument `title_lines`.

- [ ] **Step 3: Split the margin into three**

Replace lines 315-318 with:

```python
    # `margin` historically meant both the left inset and the top/bottom inset.
    # A wrapped title needs a taller top only, so the three are now distinct.
    margin_left: int = 40 * scale
    margin_bottom: int = 40 * scale
    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        margin_top: int = max(40 * scale, 2 * scale + band + TITLE_BAND_GAP * scale)
    else:
        margin_top = 40 * scale
    margin_right: int = ceil(margin_left * 1.6)
    graph_width: int = large_width - margin_left - margin_right
    graph_height: int = large_height - margin_top - margin_bottom - (10 * scale)
```

- [ ] **Step 4: Reassign every remaining `margin` reference**

Work through the function and replace each bare `margin` per this mapping. There must be NO bare `margin` left when you are done — verify with `grep -n "\bmargin\b" src/trmnl_server/components.py` over the function's range.

- `margin_left`: line 365 x of BOTH points; line 370 x of point 1; 387; 392 (both); 409; 415 (both); 425; 443; 444 (both); 454 (both).
- `margin_top`: line 365 y of the FIRST point ONLY.
- `margin_bottom`: line 365 y of point 2; 370 y of BOTH points; 379; 401; 430; 436 (both); 445.

- [ ] **Step 5: Wrap and paint the title**

Apply the same wrap/ellipsize/`multiline_text` block as Task 3, but drawn at
`2 * scale` (the graph's existing title y), not `5 * scale`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k GraphTwoLineTitle -v`
Expected: PASS, 3 tests.

- [ ] **Step 7: Run the full suite — the golden check is the real gate**

Run: `uv run pytest -q`
Expected: ONLY `test_entity_attribute_dashboard` and `test_history_graph_bipolar` fail. If any `history_graph_*` golden other than `bipolar` fails, the margin split is wrong — a mis-assigned horizontal/vertical shifts the plot. Fix the mapping; do NOT regenerate.

- [ ] **Step 8: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: two-line titles for the graph component"
```

---

### Task 5: Two-line titles and a bounded value in the entity component

**Files:**
- Modify: `src/trmnl_server/components.py` — `_draw_entity_component` (491), title at 551, value loop ~562-593, placement 603-604
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_wrap_title`, `_title_band_height`, `_ellipsize`.
- Produces: `_draw_entity_component` gains keyword-only `title_lines: int = 1`.

The value is vertically CENTRED, not stacked below the title, and its shrink loop is width-only — so a two-line band can leave it nowhere valid.

- [ ] **Step 1: Write the failing tests**

```python
class TestEntityTwoLineTitle(unittest.TestCase):
    """The entity value is bounded by the region below a wrapped title."""

    LONG = "Back Garden Soil Moisture Level"

    def test_accepts_title_lines(self):
        img = _draw_entity_component(self.LONG, 21.5, 400, 220, mock_logger,
                                     title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_two_lines_differs_from_one(self):
        one = _draw_entity_component(self.LONG, 21.5, 400, 220, mock_logger,
                                     title_font_size=35, title_lines=1)
        two = _draw_entity_component(self.LONG, 21.5, 400, 220, mock_logger,
                                     title_font_size=35, title_lines=2)
        self.assertNotEqual(one.tobytes(), two.tobytes())

    def test_one_line_is_byte_identical_to_omitting_the_argument(self):
        a = _draw_entity_component("CPU", 21.5, 400, 220, mock_logger, title_font_size=35)
        b = _draw_entity_component("CPU", 21.5, 400, 220, mock_logger,
                                   title_font_size=35, title_lines=1)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_value_does_not_overflow_a_short_tile_with_a_wrapped_title(self):
        """266x146 needed 158px before this fix. Top rows must stay blank."""
        img = _draw_entity_component(self.LONG, 21.5, 266, 146, mock_logger,
                                     title_font_size=18, title_lines=2)
        px = img.convert('L').load()
        # The bottom-most row must not be inked: the value has to fit.
        self.assertTrue(all(px[x, img.height - 1] > 200 for x in range(img.width)))

    def test_long_multiword_value_is_bounded(self):
        img = _draw_entity_component(
            "Weather", "Partly Cloudy With Heavy Showers And Thunder",
            150, 90, mock_logger, title_font_size=18, title_lines=2,
        )
        px = img.convert('L').load()
        self.assertTrue(all(px[x, img.height - 1] > 200 for x in range(img.width)))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k EntityTwoLineTitle -v`
Expected: FAIL — unexpected keyword argument `title_lines`.

- [ ] **Step 3: Add the parameter and the title band**

Add `title_lines: int = 1` keyword-only and document it. Apply the same
wrap/ellipsize/`multiline_text` block as Task 3, drawn at the existing
`title_y`. Then compute the available region:

```python
    if title_lines > 1:
        band: int = _title_band_height(
            title_font_size or COMPONENT_TITLE_FONT_SIZE, title_lines, logger
        ) * scale
        avail_top: int = band
    else:
        avail_top = 0
    avail_h: int = large_height - avail_top
```

- [ ] **Step 4: Give the value shrink loop a height budget**

Change the existing loop's condition from width-only to width-or-height, keeping the same step, floor and try/except structure:

```python
        while (
            value_width > large_width - padding
            or (value_bbox[3] - value_bbox[1]) > avail_h
        ):
            font_size -= 4
            if font_size <= min_font_size:
                break
            font_value = ImageFont.truetype(NOTO_FONT, font_size)
            value_bbox = d.textbbox((0, 0), value_str, font=font_value)
            value_width = value_bbox[2] - value_bbox[0]
```

- [ ] **Step 5: Bound the wrapped value**

After the existing "wrap if still too wide" block produces `value_str`, add:

```python
        if '\n' in value_str:
            # PIL's text() uses spacing=4 ABSOLUTE for embedded newlines.
            probe_bbox = d.multiline_textbbox((0, 0), "Ag", font=font_value, spacing=4)
            line_pitch: int = max(1, probe_bbox[3])
            max_value_lines: int = max(1, avail_h // line_pitch)
            wrapped_lines: list[str] = value_str.split('\n')
            if len(wrapped_lines) > max_value_lines:
                wrapped_lines = wrapped_lines[:max_value_lines]
                wrapped_lines[-1] = _ellipsize(
                    wrapped_lines[-1], font_value, large_width - padding, d
                )
                value_str = '\n'.join(wrapped_lines)
```

- [ ] **Step 6: Centre the value in the available region**

Replace line 604 with:

```python
    value_y: float = avail_top + (avail_h - value_height) / 2 - final_y_tweak
    value_y = max(float(avail_top), value_y)
```

`final_y_tweak` keeps its existing definition on line 603. At one line
`avail_top` is 0 and `avail_h` is `large_height`, so this reduces exactly to
today's expression.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k EntityTwoLineTitle -v`
Expected: PASS, 5 tests.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: ONLY the two known golden failures. Every entity golden must be unchanged — their values all resolve well under the tile width and never reach the wrap block, so the new clauses must not fire.

- [ ] **Step 9: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: two-line titles and bounded value for the entity component"
```

---

### Task 6: Row resolution and end-to-end coverage

**Files:**
- Modify: `src/trmnl_server/components.py` — `tile_components` (1001), its `_render_component`, and the row loop
- Modify: `tests/test_components.py`, `tests/test_golden.py`
- Create: `tests/golden/two_line_title_harmonisation.png`

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: no new public names; `tile_components` keeps its signature.

- [ ] **Step 1: Write the failing tests**

```python
class TestRowLineCountResolution(unittest.TestCase):
    """A row shares a line count as well as a size."""

    LONG = "Back Garden Soil Moisture Level"

    def _capture(self, render_data, width=800, height=480):
        seen = []

        def fake(friendly_name, value, w, h, logger, *, title_font_size=None, title_lines=1):
            seen.append((friendly_name, title_font_size, title_lines))
            return Image.new('RGB', (w, h), color='white')

        with mock.patch('trmnl_server.components._draw_entity_component', side_effect=fake):
            tile_components(render_data, width, height, 40, mock_logger)
        return {n: (s, l) for n, s, l in seen}

    def _panel(self, name, large=False):
        return {'type': 'entity', 'friendly_name': name, 'data': 'v', 'large_display': large}

    def test_row_wraps_to_gain_a_bigger_font(self):
        got = self._capture([self._panel('A'), self._panel('B'),
                             self._panel('C'), self._panel(self.LONG)])
        self.assertEqual(got[self.LONG], (35, 2))
        self.assertEqual(got['C'], (35, 2))

    def test_neighbours_share_size_and_line_count(self):
        got = self._capture([self._panel('A'), self._panel('B'),
                             self._panel('C'), self._panel(self.LONG)])
        self.assertEqual(got['C'], got[self.LONG])
        self.assertEqual(got['A'], got['B'])

    def test_no_wrap_when_nothing_is_gained(self):
        got = self._capture([self._panel('A'), self._panel('B'),
                             self._panel('C'), self._panel('D')])
        for value in got.values():
            self.assertEqual(value, (35, 1))

    def test_mixed_none_results_do_not_raise(self):
        """17 panels -> tile_height 88 -> the band cap excludes every rung."""
        panels = [self._panel(f'Panel Number {i}') for i in range(17)]
        got = self._capture(panels)
        for size, lines in got.values():
            self.assertEqual(lines, 1)

    def test_placeholder_only_row_falls_back(self):
        got = self._capture([
            {'type': 'entity', 'friendly_name': 'X', 'data': None, 'large_display': False},
            {'type': 'entity', 'friendly_name': 'Y', 'data': None, 'large_display': False},
        ])
        self.assertEqual(got, {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k RowLineCountResolution -v`
Expected: FAIL — the fake receives `title_lines=1` always, so `test_row_wraps_to_gain_a_bigger_font` fails asserting `(35, 2)`.

- [ ] **Step 3: Add `title_lines` to `_render_component`**

Give the nested `_render_component` a `title_lines: int` parameter and pass
`title_lines=title_lines` to all five `_draw_*_component` calls. Pass the same
size and lines into `_todo_capacity` in the todo branch.

- [ ] **Step 4: Replace the row resolution**

Replace the existing per-row `title_font_size = min(...)` block with:

```python
    for row in rows:
        tile_height_for_row: int = row[0][4]
        row_panels = [
            (render_data, tile_w)
            for render_data, _, _, tile_w, _ in row
            if render_data.get('data') is not None
        ]

        s1: int = min(
            (
                _fit_title_size(_panel_title_text(render_data), tile_w, logger)
                for render_data, tile_w in row_panels
            ),
            default=COMPONENT_TITLE_FONT_SIZE,
        )

        cap: int = tile_height_for_row * TITLE_BAND_MAX_PERCENT // 100
        s2_results: list[int | None] = [
            _fit_title_size(
                _panel_title_text(render_data), tile_w, logger,
                lines=TITLE_MAX_LINES, max_band=cap,
            )
            for render_data, tile_w in row_panels
        ]
        # Materialise and check for None BEFORE min(): min() over a mix of
        # None and int raises TypeError.
        s2: int | None = (
            None
            if (not s2_results or any(r is None for r in s2_results))
            else min(s2_results)
        )

        if s2 is not None and (
            TITLE_SIZE_LADDER.index(s1) - TITLE_SIZE_LADDER.index(s2) >= TITLE_WRAP_MIN_GAIN
        ):
            title_font_size, title_lines = s2, TITLE_MAX_LINES
        else:
            title_font_size, title_lines = s1, 1

        for render_data, x, y, tile_w, tile_h in row:
            component_image = _render_component(render_data, tile_w, tile_h,
                                                title_font_size, title_lines)
            if component_image:
                final_image.paste(component_image, (x, y))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k RowLineCountResolution -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Run the whole component suite**

Run: `uv run pytest tests/test_components.py -q`
Expected: PASS.

- [ ] **Step 7: Add the end-to-end golden test**

In `tests/test_golden.py`, inside `TestGoldenImages`, following the style of `test_title_size_harmonisation`:

```python
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_two_line_title_harmonisation(self, mock_get_entity_state):
        """A row whose long title wraps to two lines, keeping a large font."""
        mock_get_entity_state.return_value = {'state': '21.5', 'attributes': {}}
        dashboard = {
            'name': 'twoline',
            'title': 'Two Line',
            'components': [
                {'entity_name': 'sensor.a', 'friendly_name': 'Kitchen', 'type': 'entity'},
                {'entity_name': 'sensor.b', 'friendly_name': 'Hallway', 'type': 'entity'},
                {'entity_name': 'sensor.c', 'friendly_name': 'Study', 'type': 'entity'},
                {'entity_name': 'sensor.d',
                 'friendly_name': 'Back Garden Soil Moisture Level', 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'two_line_title_harmonisation')
```

- [ ] **Step 8: Generate the golden and LOOK AT IT**

Run: `uv run pytest tests/test_golden.py::TestGoldenImages::test_two_line_title_harmonisation -q`
Expected: PASS — `assert_golden` creates the file on first run.

Then open `tests/golden/two_line_title_harmonisation.png` with the Read tool and **actually look at it**. Confirm:
- "Back Garden Soil Moisture Level" is on TWO lines, both centred, at a visibly larger font than a single-line version would allow.
- "Study" shares that same size and its content starts at the same height.
- No title is clipped, and no value overlaps a title.

If it does not look right, that is a bug in Tasks 3-6 — stop and report it. Do NOT adjust the test to match a bad render.

- [ ] **Step 9: Verify the existing goldens are untouched**

Run: `uv run pytest -q`
Expected: ONLY `test_entity_attribute_dashboard` and `test_history_graph_bipolar` fail.

- [ ] **Step 10: Commit**

`git add -f` is REQUIRED for the PNG — `.gitignore` line 3 is `*.png`.

```bash
rm -f tests/golden/*.diff.png
git add src/trmnl_server/components.py tests/test_components.py tests/test_golden.py
git add -f tests/golden/two_line_title_harmonisation.png
git commit -m "feat: resolve title line count per row with golden coverage"
```

---

## Definition of done

- `uv run pytest -q` shows only the two known pre-existing golden failures.
- All 9 pre-existing goldens byte-identical.
- A row with a long title wraps to two lines and keeps a larger font; a row of short titles stays on one line.
- Neighbouring panels share both size and line count.
- 17+ components render without raising and fall back to one line.
- The new golden has been looked at and shows a correctly wrapped, unclipped title.
