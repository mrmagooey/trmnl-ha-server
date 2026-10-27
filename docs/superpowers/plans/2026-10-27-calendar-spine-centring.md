# Centred Calendar Day Spines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centre each rotated calendar day label (spine) horizontally between the card's left edge and the gutter's vertical rule, instead of pasting it at a fixed x = 4.

**Architecture:** `_draw_spine` gains a keyword-only `right` (scaled x of the rule's left ink edge) and pastes the rotated label at `max(0, (right - rotated.width) // 2)`. `_draw_calendar_component` computes the rule x once, draws the rule from it, and passes `right` derived from the same value, so the label and the rule share one source of truth.

**Tech Stack:** Python 3.12, Pillow, unittest/pytest via `uv`.

**Spec:** `docs/superpowers/specs/2026-10-27-calendar-spine-centring-design.md`

## Global Constraints

- Gutter mode only; prefix mode draws no spines and must be pixel-identical (its goldens must not change).
- Vertical placement, font sizes and label text are unchanged.
- The new parameter is keyword-only (`*, right: int`) so `mock.patch(..., side_effect=_draw_spine)` spies keep working.
- All drawing happens at `COMPONENT_SCALE` (2) and is downsampled with LANCZOS.
- Code style follows AGENTS.md: type hints, Google-style docstrings, explanatory *why* comments, `unittest.TestCase`.

## Review Focus

1. Labels of different ink widths (e.g. "Wed" vs "Fri", two-letter "Mo") at sizes 16/20/28 must each centre on their own width. This is covered by the Task 1 unit test's label × size grid.
2. A label wider than `right` must never be pasted at a negative x; it clamps to 0. This is covered by the Task 1 unit test `test_spine_wider_than_gutter_clamps_to_left_edge`.
3. The rule must still be drawn at exactly `x_text - 8 * scale` with width `2 * scale`. This is covered by the existing tests `test_gutter_mode_draws_a_vertical_rule_between_spine_and_rows` and `test_gutter_rule_is_drawn_two_px_thick_on_the_scaled_canvas`, which must keep passing unchanged.
4. Prefix-mode output must be unchanged. This is covered by the Task 1 golden review step: prefix goldens must not appear in `git status`.
5. A spine on a truncated group, which has a short vertical span, must still centre horizontally. Horizontal centring is independent of `top`/`bottom`, and the unit test uses a short span for one case.

---

### Task 1: Centre the spine between the card edge and the rule

**Files:**
- Modify: `src/trmnl_server/components.py`: `_draw_spine` (~L1819-1836) and the gutter block in `_draw_calendar_component` (~L1934-1943).
- Test: `tests/test_components.py`, a new class `TestSpineCentring` appended near `TestCalendarGatesTwoLetterSpine`.
- Test: `tests/test_calendar_grouping_e2e.py`, a new test method.
- Goldens: `tests/golden/*.png`, regenerated for gutter-mode calendars only.

**Interfaces:**
- Produces: `_draw_spine(img: Image.Image, label: str, size: int, top: int, bottom: int, logger: "Logger", *, right: int) -> None`, where `right` is the scaled x of the gutter's visible right boundary (the rule's left ink edge).

- [ ] **Step 1: Write the failing unit tests**

Add `_draw_spine` to the `from trmnl_server.components import (...)` list at the top of `tests/test_components.py` if it isn't already imported. Then append:

```python
class TestSpineCentring(unittest.TestCase):
    """A day spine sits centred between the card's left edge and the gutter rule.

    Spec: docs/superpowers/specs/2026-10-27-calendar-spine-centring-design.md
    """

    @staticmethod
    def _ink_columns(img: Image.Image) -> tuple[int, int]:
        """(first, last) x holding any non-white pixel."""
        box = ImageChops.invert(img.convert('L')).getbbox()
        assert box is not None, "nothing was drawn"
        return box[0], box[2] - 1

    def test_spine_ink_is_centred_between_card_edge_and_right_bound(self):
        """Left gap to x=0 equals right gap to `right`, for every label and size."""
        right = 86  # the rule's left ink edge on the scaled canvas: (20+32-8)*2 - 2
        for size in (16, 20, 28):
            for label, top, bottom in (('Wed', 0, 300), ('Fri', 0, 300), ('Mo', 40, 100)):
                with self.subTest(size=size, label=label):
                    img = Image.new('RGB', (200, 400), 'white')
                    _draw_spine(img, label, size, top, bottom, mock_logger, right=right)
                    first, last = self._ink_columns(img)
                    left_gap = first
                    right_gap = right - (last + 1)
                    self.assertLessEqual(abs(left_gap - right_gap), 1,
                                         f"gaps {left_gap} vs {right_gap}")

    def test_spine_wider_than_gutter_clamps_to_left_edge(self):
        """A bound narrower than the label pastes at x=0, never off-canvas."""
        img = Image.new('RGB', (200, 400), 'white')
        _draw_spine(img, 'Wed', 28, 0, 300, mock_logger, right=10)
        first, _ = self._ink_columns(img)
        self.assertLessEqual(first, 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py::TestSpineCentring -v`
Expected: FAIL with `TypeError: _draw_spine() got an unexpected keyword argument 'right'`.

- [ ] **Step 3: Implement**

In `_draw_spine`, change the signature and the paste. Extend the docstring with an `Args`-style note for `right` that matches the existing docstring style:

```python
def _draw_spine(img: Image.Image, label: str, size: int,
                top: int, bottom: int, logger: "Logger", *, right: int) -> None:
    """Draws a day label rotated 90 degrees in the left gutter.

    PIL cannot draw rotated text, so the label is rendered to a temp image and
    rotated. The temp image is sized by the label's INK box, not the font's
    line box: after rotation the text's height becomes its width, and the line
    box is 38px at 28pt against a 32px gutter, where the ink box is 22px.

    The label is centred horizontally between the card's left edge and
    `right`, the scaled x of the gutter rule's left ink edge -- the visible
    boundary of the label column -- so it no longer hugs the card edge.
    """
    ...
    y = top + max(0, (bottom - top - rotated.height) // 2)
    x = max(0, (right - rotated.width) // 2)
    img.paste(rotated, (x, y))
```

In `_draw_calendar_component`, replace the gutter block so that the rule x is computed once:

```python
            if layout.mode == 'gutter':
                # A 2px vertical rule between the spine and the row text,
                # spanning only the rows this group actually drew (group_top
                # to y_pos, the same span _draw_spine uses) -- a group
                # truncated by the row budget gets a rule sized to match.
                rule_x = x_text - 8 * scale
                rule_width = 2 * scale
                d.line(
                    [(rule_x, group_top), (rule_x, y_pos)],
                    fill='black', width=rule_width,
                )
                # The spine centres against the rule's left ink edge: a line
                # of width w drawn at rule_x spans rule_x - w//2 onwards.
                _draw_spine(img, label, layout.size, group_top, y_pos, logger,
                            right=rule_x - rule_width // 2)
```

- [ ] **Step 4: Run the unit tests and the existing calendar tests**

Run: `uv run pytest tests/test_components.py -q -k "Spine or calendar or Calendar"`
Expected: PASS, including the existing rule tests, which are unchanged.

- [ ] **Step 5: Write the e2e test**

Append to `TestCalendarGroupingEndToEnd` in `tests/test_calendar_grouping_e2e.py`:

```python
    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    def test_spine_is_centred_between_card_edge_and_gutter_rule(self, mock_cal):
        """On the final image the spine's left gap equals its gap to the rule.

        The rule is the tallest dark column just left of the row text; the
        spine is the ink to its left. Measured on the downsampled output, so a
        1px tolerance absorbs LANCZOS edge softening.
        """
        events = _events([('2024-01-17', 3), ('2024-01-18', 3)])
        mock_cal.return_value = events
        layout = _calendar_layout(list(events), _SOLO_TILE_W, _SOLO_TILE_H, mock_logger)
        self.assertEqual(layout.mode, 'gutter')

        img = Image.open(render_dashboard_image(self.DASHBOARD_SOLO, mock_logger)).convert('L')
        w, h = img.size
        px = img.load()
        dark = lambda x, y: px[x, y] < 128
        # Rows below the header band, where only spine, rule and row text live.
        ys = range(_TOP_MARGIN + 40, h)
        col_counts = [sum(dark(x, y) for y in ys) for x in range(0, 52)]
        rule_left = max(range(52), key=lambda x: col_counts[x])
        while rule_left > 0 and col_counts[rule_left - 1] > col_counts[rule_left] // 2:
            rule_left -= 1
        spine_cols = [x for x in range(rule_left) if col_counts[x] > 0]
        self.assertTrue(spine_cols, "no spine ink found left of the rule")
        left_gap = spine_cols[0]
        right_gap = rule_left - (spine_cols[-1] + 1)
        self.assertLessEqual(abs(left_gap - right_gap), 1,
                             f"spine gaps {left_gap} (edge) vs {right_gap} (rule)")
```

If the rule-detection heuristic misfires on the real image, fix the detection rather than loosening the tolerance, and explain why in the report.

- [ ] **Step 6: Run the e2e test**

Run: `uv run pytest tests/test_calendar_grouping_e2e.py -v`
Expected: PASS. Before Step 3 this test would fail, because the left gap was about 4 px and the right gap about 25 px.

- [ ] **Step 7: Regenerate goldens and review the diff**

Run: `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py -q`, then `git status --short tests/golden`.
Expected: only goldens that contain gutter-mode calendars change. For each changed PNG, compare old (`git show HEAD:tests/golden/<name>.png`) and new, and confirm that the pixel diff bbox (`ImageChops.difference(...).getbbox()`) lies within the calendar's gutter columns (x < 52 in panel coordinates). `calendar_prefix_fallback.png` must NOT change; if it does, stop and report.

- [ ] **Step 8: Full suite**

Run: `uv run pytest tests/ -q` (about 7 min).
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py tests/test_calendar_grouping_e2e.py tests/golden/
git commit -m "feat: centre calendar day spines between the card edge and the gutter rule"
```
(The message ends with the session's Co-Authored-By / Claude-Session trailer lines.)
