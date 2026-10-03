# Titleless Cards (`hide_title`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-component `hide_title: true` option that renders a card with no title and lets its content take the freed space.

**Architecture:** The option is validated in `render_dashboard_image` and carried in the render entry. `tile_components` gives a titleless card `title_lines = NO_TITLE_LINES` (0) and leaves it out of the row's shared title-size fit. Each drawer and layout helper gets an explicit `title_lines == NO_TITLE_LINES` branch, placed before the existing `<= 1` / `> 1` checks (which would otherwise treat 0 as 1), that skips the title and uses a minimal top inset.

**Tech Stack:** Python 3.12, Pillow, unittest/pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-03-hide-title-design.md`

## Global Constraints

- Branch: `feat/hide-title` only. Never commit to `main`.
- Run tests with `uv run pytest tests/ -q`. The full suite must pass before each commit, except `tests/test_firmware_e2e.py::TestFirmwareEndToEnd::test_display_then_firmware_download_matches_github`, which fails on main from GitHub API rate limiting (403).
- Existing golden images must not change. Only new goldens are added.
- Style: type hints on everything, Google-style docstrings, `logger.warning` with context on bad config, snake_case, about 100-character lines, comment density matching `components.py`.
- Commit trailer, on every commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FiygobwBA9XTJk4h8bs8u2
  ```

## Review Focus

1. **A titleless card beside a titled card whose title wraps to 2 lines.** The titleless card must get 0 lines, not the row's 2. Test this in Task 1.
2. **A row where every card is titleless.** `row_panels` is empty, and the row must render without error. Test this in Task 1.
3. **A paginating titleless todo list.** The page indicator must not overlap the first row. Test this in Task 2.
4. **A titleless `url` card.** It must flow through the same path as `entity`, and the key must not be dropped. Test this in Task 1 and Task 3.
5. **A `hide_title` card whose data is missing.** It still renders the "No data for X" placeholder. Test this in Task 1.

---

### Task 1: Config, render entry and tiling

**Files:**
- Modify: `src/trmnl_server/components.py`
  - Add the constant near `GAP_STYLE_DEFAULT` (~L38).
  - Add `_resolve_hide_title` after `_resolve_max_gap` (~L973).
  - Change `_panel_draws_a_title` (~L256).
  - Change the row loop in `tile_components` (~L2240-2305).
  - Change the render entry in `render_dashboard_image` (~L2430).
- Modify: `src/trmnl_server/models.py`. Add `hide_title: bool` to `ComponentConfig` (near `gap_style`, ~L55) and `hide_title: NotRequired[bool]` to `RenderData` (~L166).
- Test: `tests/test_components.py` (new classes at the end).

**Interfaces:**
- Produces:
  - `NO_TITLE_LINES: int = 0`
  - `_resolve_hide_title(component: ComponentConfig, logger: Logger) -> bool`
  - The render entry key `'hide_title': True`, present only when true.
  - Drawers receive `title_lines=NO_TITLE_LINES` for titleless cards.

- [ ] **Step 1: Write the failing tests**

```python
from trmnl_server.components import NO_TITLE_LINES, _resolve_hide_title, _panel_draws_a_title

class TestResolveHideTitle(unittest.TestCase):
    """Config validation for hide_title."""

    def test_absent_is_false(self):
        """No hide_title key means the title is shown."""
        self.assertFalse(_resolve_hide_title({}, mock.Mock()))

    def test_bools_pass_through(self):
        """True and False are taken as given."""
        self.assertTrue(_resolve_hide_title({'hide_title': True}, mock.Mock()))
        self.assertFalse(_resolve_hide_title({'hide_title': False}, mock.Mock()))

    def test_invalid_warns_and_shows_title(self):
        """A non-bool value logs a warning and falls back to showing the title."""
        for raw in ('yes', 1, 0, None, [True]):
            logger = mock.Mock()
            with self.subTest(raw=raw):
                self.assertFalse(_resolve_hide_title({'hide_title': raw}, logger))
                logger.warning.assert_called_once()


class TestPanelDrawsATitleHidden(unittest.TestCase):
    def test_hidden_title_does_not_count(self):
        """A hide_title panel is excluded from the row title fit."""
        self.assertFalse(_panel_draws_a_title(
            {'type': 'entity', 'friendly_name': 'X', 'data': 5, 'hide_title': True}))
```

Add a tiling integration class. Patch each `_draw_*_component` (and `_create_info_image`) with a `mock.Mock` that returns `Image.new('RGB', (w, h), 'white')`, call `tile_components`, then read each call's `title_lines` kwarg:

```python
class TestHideTitleTiling(unittest.TestCase):
    """Integration: titleless cards get title_lines=0 and leave the row title fit."""

    def _tile(self, render_data):
        calls = {}
        def fake(name):
            def _f(friendly_name, data, w, h, logger, **kw):
                calls.setdefault(friendly_name, kw)
                return Image.new('RGB', (w, h), 'white')
            return _f
        with mock.patch('trmnl_server.components._draw_entity_component', side_effect=fake('e')), \
             mock.patch('trmnl_server.components._draw_entities_component', side_effect=fake('es')):
            tile_components(render_data, 800, 480, 40, mock.Mock())
        return calls

    def test_mixed_row_titleless_gets_zero_neighbour_wraps(self):
        """A titled neighbour that wraps to 2 lines must not give the titleless card 2."""
        long_name = 'An extremely long panel title that has to wrap onto two lines'
        calls = self._tile([
            {'type': 'entity', 'friendly_name': long_name, 'data': 1},
            {'type': 'entity', 'friendly_name': 'Hidden', 'data': 2, 'hide_title': True},
        ])
        self.assertEqual(calls['Hidden']['title_lines'], NO_TITLE_LINES)
        self.assertEqual(calls[long_name]['title_lines'], 2)

    def test_titleless_card_does_not_shrink_neighbour_title(self):
        """A long hidden title is not measured, so the neighbour keeps the largest size."""
        calls = self._tile([
            {'type': 'entity', 'friendly_name': 'Short', 'data': 1},
            {'type': 'entity', 'friendly_name': 'W' * 80, 'data': 2, 'hide_title': True},
        ])
        self.assertEqual(calls['Short']['title_font_size'], COMPONENT_TITLE_FONT_SIZE)

    def test_all_titleless_row_renders(self):
        """A row in which every card hides its title still tiles without error."""
        calls = self._tile([
            {'type': 'entity', 'friendly_name': 'A', 'data': 1, 'hide_title': True},
            {'type': 'entity', 'friendly_name': 'B', 'data': 2, 'hide_title': True},
        ])
        self.assertEqual({c['title_lines'] for c in calls.values()}, {NO_TITLE_LINES})

    def test_no_data_placeholder_unchanged(self):
        """hide_title does not suppress the 'No data for X' placeholder."""
        with mock.patch('trmnl_server.components._create_info_image',
                        return_value=Image.new('RGB', (10, 10))) as info:
            tile_components([{'type': 'entity', 'friendly_name': 'Gone', 'data': None,
                              'hide_title': True}], 800, 480, 40, mock.Mock())
        self.assertIn('Gone', info.call_args[0][0])
```

Also add a dispatch test, following the existing `TestMaxGapDispatch` pattern (it patches `get_entity_state`/`_fetch_history` and the drawer). Render a dashboard whose `url` component and `entity` component both have `hide_title: True`, and assert both drawers received `title_lines=NO_TITLE_LINES`. For the `url` component, patch `trmnl_server.url_source.get_value` (or whatever `render_dashboard_image` calls for url; check ~L2380-2400) to return `'42'`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -q -k "HideTitle or PanelDrawsATitleHidden"`
Expected: ImportError on `NO_TITLE_LINES` / `_resolve_hide_title`.

- [ ] **Step 3: Implement**

```python
# components.py, near GAP_STYLE_DEFAULT
# title_lines value for a card configured with hide_title: no title band at all.
NO_TITLE_LINES: int = 0


def _resolve_hide_title(component: "ComponentConfig", logger: "Logger") -> bool:
    """Reads a component's hide_title setting, warning on an invalid one.

    Args:
        component: The component's configuration
        logger: Logger instance

    Returns:
        True only when hide_title is the boolean True
    """
    raw: object = component.get('hide_title', False)
    if isinstance(raw, bool):
        return raw
    logger.warning(
        "Invalid 'hide_title' (%r) for %s; expected true or false. Showing the title.",
        raw, component.get('friendly_name'),
    )
    return False
```

In `_panel_draws_a_title`, add this before the existing checks, and add a line to the docstring:

```python
    if render_data.get('hide_title'):
        return False
```

In `render_dashboard_image`, after building `render_entry`:

```python
        if _resolve_hide_title(component, logger):
            render_entry['hide_title'] = True
```

In `tile_components`, in the loop that computes `body_specs` and in the final render loop, use a per-card line count:

```python
        def _lines_for(render_data: RenderData) -> int:
            return NO_TITLE_LINES if render_data.get('hide_title') else title_lines
```

Pass `title_lines=_lines_for(render_data)` to `_panel_body_fit`, and `_lines_for(render_data)` as the `title_lines` argument to `_render_component`. Define `_lines_for` once, inside the `for row in rows:` loop and after `title_lines` is resolved. `title_font_size` is passed unchanged; drawers ignore it at 0 lines.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -q -k "HideTitle or PanelDrawsATitleHidden"`
Expected: PASS. The drawers still draw a title at 0 lines until Tasks 2-3; that's fine, because these tests mock the drawers.

- [ ] **Step 5: Run the full suite, then commit**

```bash
uv run pytest tests/ -q
git add src/trmnl_server/components.py src/trmnl_server/models.py tests/test_components.py
git commit -m "feat: hide_title option routes titleless cards through tiling with zero title lines"
```

---

### Task 2: List cards (calendar, entities, todo_list) drop the title and start higher

**Files:**
- Modify: `src/trmnl_server/components.py`:
  - constants near `TODO_HEADER_H` (~L66);
  - `_calendar_content_top` (~L630);
  - `_todo_header_height` (~L803);
  - `_draw_calendar_component` title block (~L1646-1666);
  - `_draw_entities_component` title block and `y_pos` (~L1783-1809);
  - `_draw_todo_list_component` title block (~L1948-1969).
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `NO_TITLE_LINES` (Task 1).
- Produces:
  - constants `NO_TITLE_CONTENT_TOP: int = 10` and `TODO_NO_TITLE_HEADER_H: int = 40`;
  - `_calendar_content_top(..., title_lines=0) == NO_TITLE_CONTENT_TOP`;
  - `_todo_header_height(..., title_lines=0) == TODO_NO_TITLE_HEADER_H`.

`TODO_NO_TITLE_HEADER_H` is 40 because the page indicator is drawn at y=12 at size 18, and that font's bbox bottom is 20, so the ink ends at 32. Adding an 8px gap gives 40.

- [ ] **Step 1: Write the failing tests**

```python
class TestTitlelessListLayout(unittest.TestCase):
    """Unit: list cards at title_lines=0 start content higher and fit more rows."""

    def test_calendar_content_top_shrinks(self):
        self.assertEqual(_calendar_content_top(None, NO_TITLE_LINES, mock.Mock()), NO_TITLE_CONTENT_TOP)
        self.assertLess(NO_TITLE_CONTENT_TOP, _calendar_content_top(None, 1, mock.Mock()))

    def test_todo_header_shrinks_but_keeps_indicator_band(self):
        self.assertEqual(_todo_header_height(None, NO_TITLE_LINES, mock.Mock()), TODO_NO_TITLE_HEADER_H)
        self.assertLess(TODO_NO_TITLE_HEADER_H, _todo_header_height(None, 1, mock.Mock()))

    def test_todo_capacity_grows(self):
        _, cap1 = _todo_capacity(200, 1, COMPONENT_TITLE_FONT_SIZE, 1, mock.Mock())
        _, cap0 = _todo_capacity(200, 1, COMPONENT_TITLE_FONT_SIZE, NO_TITLE_LINES, mock.Mock())
        self.assertGreater(cap0, cap1)

    def test_calendar_capacity_not_smaller(self):
        # Use the existing _calendar_capacity call shape from the calendar tests in this file.
        ...  # assert capacity at NO_TITLE_LINES >= capacity at 1 for the same height/width/size
```

For the `test_calendar_capacity_not_smaller` body, copy the argument shape of an existing `_calendar_capacity` test in this file and call it twice, once with `title_lines=1` and once with `NO_TITLE_LINES`. Assert `>=`, and `>` if the tile height leaves room for a whole extra row (use height 240).

Drawer regression tests check that no title ink is drawn and that content moves up. Render each drawer at `title_lines=1` and at `NO_TITLE_LINES` with the same data, convert to `'L'`, and find the first row (y) containing any pixel below 128:

```python
def _first_ink_row(img):
    g = img.convert('L')
    w, h = g.size
    px = g.load()
    for y in range(h):
        if any(px[x, y] < 128 for x in range(w)):
            return y
    return None

class TestTitlelessListDrawers(unittest.TestCase):
    """Regression: title_lines=0 must not fall through the `<= 1` paths and still draw a title."""

    def _both(self, draw, *args, **kw):
        a = draw(*args, title_lines=1, **kw)
        b = draw(*args, title_lines=NO_TITLE_LINES, **kw)
        return _first_ink_row(a), _first_ink_row(b), b

    def test_entities(self):
        rows = [{'friendly_name': 'Kitchen', 'state': '21.5'}]  # match _draw_entities_component's expected data shape
        t1, t0, _ = self._both(_draw_entities_component, 'Title', rows, 300, 200, mock.Mock())
        self.assertLess(t0, t1)

    def test_calendar(self): ...   # same pattern with one event; t0 < t1
    def test_todo(self): ...       # same pattern with one item; t0 < t1
```

Fill `test_calendar` and `test_todo` with data shaped like the existing calendar and todo tests in this file.

Add a paginating titleless todo test. With 30 items in a 200px-high tile at `NO_TITLE_LINES`:
- the indicator ink (the right-most 60px columns) must end above `TODO_NO_TITLE_HEADER_H`;
- the first checkbox row must start at or below `TODO_NO_TITLE_HEADER_H`.

Assert this via `_first_ink_row` on a crop of the left 40px, compared against `TODO_NO_TITLE_HEADER_H`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -q -k "Titleless"`
Expected: ImportError on the new constants, then assertion failures, because 0 falls into the `<= 1` path.

- [ ] **Step 3: Implement**

```python
# near TODO_HEADER_H
# Top inset for a hide_title card: content starts here instead of below a title.
NO_TITLE_CONTENT_TOP: int = 10
# A titleless todo keeps a band for its top-right page indicator (drawn at y=12,
# ink ending ~32); fixed rather than pagination-dependent, since capacity decides
# pagination and a pagination-dependent header would be circular.
TODO_NO_TITLE_HEADER_H: int = 40
```

In `_calendar_content_top` and `_todo_header_height`, add this as the first statement and add a line to each docstring:

```python
    if title_lines == NO_TITLE_LINES:
        return NO_TITLE_CONTENT_TOP          # (_todo_header_height: TODO_NO_TITLE_HEADER_H)
```

In each of the three drawers, wrap the whole `# Draw title` block (from `if title_lines > 1:` / `title_text` through `d.multiline_text(...)`) in `if title_lines != NO_TITLE_LINES:`. In `_draw_entities_component`, replace the `y_pos` branch with:

```python
    if title_lines == NO_TITLE_LINES:
        y_pos: int = NO_TITLE_CONTENT_TOP * scale
    elif title_lines > 1:
        ...existing...
    else:
        y_pos = 50 * scale
```

The calendar and todo drawers already take their top from the helpers.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -q -k "Titleless"`, then `uv run pytest tests/ -q`.
Expected: PASS. No existing golden changes.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: titleless calendar, entities and todo cards reclaim the title band"
```

---

### Task 3: Graph and entity/url cards drop the title and use the space

**Files:**
- Modify: `src/trmnl_server/components.py`:
  - `_draw_graph_component` (title-font block ~L1128-1150, `margin_top` ~L1163, title draw ~L1189-1208);
  - `_draw_entity_component` (title block ~L1396-1442, `avail_top` ~L1444, centring ~L1544-1570).
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `NO_TITLE_LINES` (Task 1), `NO_TITLE_CONTENT_TOP` (Task 2).
- Produces: `GRAPH_NO_TITLE_MARGIN_TOP: int = 15`. The top y-axis label is centred on `margin_top` and its ink is about 10px tall, so 15 keeps it clear of the edge.

- [ ] **Step 1: Write the failing tests**

```python
class TestTitlelessGraphAndEntity(unittest.TestCase):
    """Regression: graph and entity cards at title_lines=0 draw no title and use the space."""

    def test_graph_plot_starts_higher(self):
        now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        pts = [(now - timedelta(hours=2), 1.0), (now - timedelta(minutes=5), 3.0)]
        kw = dict(window_start=now - timedelta(hours=24), window_end=now)
        a = _draw_graph_component('Title', pts, 400, 240, mock.Mock(), title_lines=1, **kw)
        b = _draw_graph_component('Title', pts, 400, 240, mock.Mock(), title_lines=NO_TITLE_LINES, **kw)
        self.assertLess(_first_ink_row(b), _first_ink_row(a))
        # The y-axis line starts at margin_top: scan column x=40 (the axis) for the first ink.
        self.assertLessEqual(_first_ink_row(b.crop((38, 0, 42, 240))), GRAPH_NO_TITLE_MARGIN_TOP + 1)

    def test_entity_value_grows_and_is_centred(self):
        a = _draw_entity_component('Title', 42, 300, 200, mock.Mock(), title_lines=1)
        b = _draw_entity_component('Title', 42, 300, 200, mock.Mock(), title_lines=NO_TITLE_LINES)
        ink = lambda im: im.convert('L').point(lambda p: 255 if p < 128 else 0).getbbox()
        ba = ink(b)
        top, bottom = ba[1], 200 - ba[3]
        self.assertLessEqual(abs(top - bottom), 4)          # vertically centred
        self.assertGreater(ba[3] - ba[1], 0)
        self.assertGreaterEqual(ba[1], 0)
        self.assertLessEqual(ba[3], 200)                    # never clipped
        # Value text is at least as tall as the titled version's value
        # (the titled image's ink includes the title, so compare against its lower part).
```

Add one more test: a long string value such as `'Partly cloudy with showers'` at `NO_TITLE_LINES` in a 200x120 tile. Assert its ink bbox lies inside the tile with a margin of at least 1px on every side.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -q -k "TitlelessGraphAndEntity"`
Expected: FAIL. At 0 lines the title is still drawn and `margin_top` stays at 40.

- [ ] **Step 3: Implement**

Graph:
```python
GRAPH_NO_TITLE_MARGIN_TOP: int = 15  # unscaled; clears the top y-axis label's ink
...
    if title_lines == NO_TITLE_LINES:
        margin_top: int = GRAPH_NO_TITLE_MARGIN_TOP * scale
    elif title_lines > 1:
        ...existing...
    else:
        margin_top = 40 * scale
```
Wrap the `# Draw title` block in `if title_lines != NO_TITLE_LINES:`. Leave the title-font loading in place, because the no-data message uses `font_title`.

Entity: wrap the title draw (`# Draw title` through `d.multiline_text`) in `if title_lines != NO_TITLE_LINES:`. Keep `avail_top = 0` and `avail_h = large_height` for 0 lines (the existing `else` already gives this; make it explicit). In the centring block, give 0 lines the ink-box path that the `title_lines > 1` branch uses, not the fixed `y_tweak`:

```python
    if title_lines > 1 or title_lines == NO_TITLE_LINES:
        value_y: float = avail_top + (avail_h - value_height) / 2 - value_bbox[1]
        min_value_y: float = avail_top - value_bbox[1]
```

Update the comment above it so it explains that the titleless path centres the real ink for the same reason. The bottom clamp after it already applies to every path.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -q -k "TitlelessGraphAndEntity"`, then `uv run pytest tests/ -q`.
Expected: PASS. No existing golden changes.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: titleless graph and entity cards reclaim the title band"
```

---

### Task 4: Goldens, end-to-end test and docs

**Files:**
- Test: `tests/test_golden.py` (new test methods in `TestGoldenImages`).
- Test: `tests/test_api.py` (a new e2e test next to `test_static_png_max_gap_minutes_changes_the_served_image`).
- Modify: `README.md` (component options list, after `max_gap_minutes` / `zero_baseline`).
- Modify: `AGENTS.md` (the "Component Notes" list).

**Interfaces:**
- Consumes: the full feature from Tasks 1-3.

- [ ] **Step 1: Add golden tests**

Copy the shape of `test_body_text_size_harmonisation` / `title_size_harmonisation` in `tests/test_golden.py` (they mock the HA fetchers and call `render_dashboard_image`). Add `test_hide_title_all_types`: one dashboard with six components, one of each type (`history_graph`, `entity`, `url`, `entities`, `calendar`, `todo_list`). Every component has `hide_title: True` except one titled `entity`, so the mixed-row behaviour is pinned too. Then `assert_golden(img_io, 'hide_title_all_types')`. Add `test_hide_title_large_display_calendar`: a `large_display: True` calendar with `hide_title: True` and enough events to show the reclaimed rows. Then `assert_golden(img_io, 'hide_title_large_display_calendar')`.

Generate them with `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py -q -k hide_title`. Open both PNGs with the Read tool and confirm by eye that:
- no titled card is missing its title;
- no titleless card shows a title;
- nothing is clipped.

Then run `uv run pytest tests/test_golden.py -q` without `UPDATE_GOLDEN` and confirm that every existing golden still passes untouched (`git status tests/golden` shows only the two new files).

- [ ] **Step 2: Add the e2e test**

In `tests/test_api.py`, copy `test_static_png_max_gap_minutes_changes_the_served_image`. Serve the same dashboard (one `entity` component) twice, once with `hide_title` absent and once with `hide_title: True`, through the HTTP server, and assert the two served PNG bodies differ, have size (800, 480) and mode '1'.

- [ ] **Step 3: Docs**

README bullet:

```markdown
- `hide_title` (any component, optional): when `true`, the card draws no title and its content moves up into the freed space. Default `false`. `friendly_name` is still required: a card with no data still shows "No data for <friendly_name>". A todo list loses its "(N)" item count with the title but keeps its page indicator. Body text stays at the size shared across its row, so the space goes to extra rows rather than larger text.
```

AGENTS.md Component Notes bullet:

```markdown
- Any component accepts `hide_title: true`: it is rendered with `title_lines = NO_TITLE_LINES` (0) and excluded from the row's title-size fit. Every layout helper checks `title_lines == NO_TITLE_LINES` before its `<= 1` / `> 1` branches, which would otherwise treat 0 as 1.
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: everything passes except the known rate-limited firmware e2e test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_golden.py tests/golden/hide_title_*.png tests/test_api.py README.md AGENTS.md
git commit -m "test: golden and e2e coverage for hide_title; document the option"
```
