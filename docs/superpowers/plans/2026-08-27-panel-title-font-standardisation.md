# Panel Title Font Standardisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Panels sharing a grid row render their titles at one shared font size, chosen from a fixed ladder, so a dashboard shows one title size (or two where genuinely needed) instead of five.

**Architecture:** `tile_components` computes its layout into an explicit list of rows before rendering. Each panel resolves the largest ladder rung whose title fits its tile width; the row renders at the minimum of its panels' rungs. The five drawing functions accept the resolved size through a new keyword-only argument and skip their own sizing when it is supplied.

**Tech Stack:** Python 3, Pillow (PIL), `unittest`, `pytest` as the runner, `uv` as the environment manager.

**Spec:** `docs/superpowers/specs/2026-08-27-panel-title-font-standardisation-design.md`

## Global Constraints

- All work happens on branch `feature/standardise-panel-title-font-size`. Do not commit to `main`.
- Run tests with `uv run pytest` from the repo root. There is no bare `python` on PATH — use `uv run python` if you need an interpreter.
- Single production file: `src/trmnl_server/components.py`. Do not restructure or split it.
- `TITLE_SIZE_LADDER = (35, 30, 26, 22, 18)`, `TITLE_PADDING = 20` (unscaled, total horizontal budget), `COMPONENT_SCALE = 2`. These exact values.
- Titles never grow above 35. The ladder only shrinks.
- Passing `title_font_size=None` to any drawing function must leave its behaviour byte-identical to today. The existing ~30 direct-call tests in `tests/test_components.py` must keep passing unmodified.
- Follow the file's existing conventions: explicit type annotations on locals, docstrings with an `Args:`/`Returns:` block, `mock_logger = mock.Mock(spec=logging.Logger)` in tests.

---

### Task 1: Ladder constants and measurement helpers

**Files:**
- Modify: `src/trmnl_server/components.py` (constants near line 21; new helpers after `_load_font`, which ends at line 45)
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_load_font(size: int, logger) -> ImageFont.FreeTypeFont` (already exists at line 29).
- Produces:
  - `COMPONENT_SCALE: int = 2`
  - `TITLE_SIZE_LADDER: tuple[int, ...] = (35, 30, 26, 22, 18)`
  - `TITLE_PADDING: int = 20`
  - `_incomplete_items(items: list[dict[str, str]]) -> list[dict[str, str]]`
  - `_panel_title_text(render_data: RenderData) -> str`
  - `_fit_title_size(text: str, tile_width: int, logger: "Logger") -> int`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_components.py`. Extend the existing import block from
`trmnl_server.components` with `_fit_title_size`, `_panel_title_text`,
`_incomplete_items`, `TITLE_SIZE_LADDER`, `COMPONENT_TITLE_FONT_SIZE`.

```python
class TestFitTitleSize(unittest.TestCase):
    """Title sizing picks rungs off the ladder and never anything else."""

    def test_short_title_in_wide_tile_gets_top_rung(self):
        self.assertEqual(_fit_title_size("CPU", 800, mock_logger), 35)

    def test_long_title_in_narrow_tile_drops_below_top_rung(self):
        size = _fit_title_size("Living Room Temperature Sensor", 200, mock_logger)
        self.assertLess(size, 35)

    def test_only_ever_returns_ladder_values(self):
        for width in range(60, 800, 20):
            size = _fit_title_size("Living Room Temperature Sensor", width, mock_logger)
            self.assertIn(size, TITLE_SIZE_LADDER)

    def test_floors_at_smallest_rung_when_nothing_fits(self):
        self.assertEqual(_fit_title_size("x" * 400, 100, mock_logger), TITLE_SIZE_LADDER[-1])

    def test_wider_tile_never_yields_a_smaller_size(self):
        text = "Living Room Temperature Sensor"
        sizes = [_fit_title_size(text, w, mock_logger) for w in range(100, 801, 50)]
        self.assertEqual(sizes, sorted(sizes))

    def test_empty_title_gets_top_rung(self):
        self.assertEqual(_fit_title_size("", 200, mock_logger), 35)


class TestIncompleteItems(unittest.TestCase):
    """The shared predicate for which todo items a panel displays."""

    def test_drops_completed_items(self):
        items = [
            {'summary': 'a', 'status': 'needs_action'},
            {'summary': 'b', 'status': 'completed'},
            {'summary': 'c', 'status': 'needs_action'},
        ]
        self.assertEqual(len(_incomplete_items(items)), 2)

    def test_missing_status_counts_as_incomplete(self):
        self.assertEqual(len(_incomplete_items([{'summary': 'a'}])), 1)

    def test_ignores_non_dict_entries(self):
        self.assertEqual(len(_incomplete_items(['nope', {'summary': 'a'}])), 1)


class TestPanelTitleText(unittest.TestCase):
    """The measured string must match the string a panel actually draws."""

    def test_plain_panel_uses_friendly_name(self):
        data = {'type': 'entity', 'friendly_name': 'Kitchen', 'data': 'on'}
        self.assertEqual(_panel_title_text(data), 'Kitchen')

    def test_todo_panel_includes_incomplete_count(self):
        data = {
            'type': 'todo_list',
            'friendly_name': 'Tasks',
            'data': [
                {'summary': 'a', 'status': 'needs_action'},
                {'summary': 'b', 'status': 'completed'},
            ],
        }
        self.assertEqual(_panel_title_text(data), 'Tasks (1)')

    def test_todo_panel_with_non_list_data_counts_zero(self):
        data = {'type': 'todo_list', 'friendly_name': 'Tasks', 'data': None}
        self.assertEqual(_panel_title_text(data), 'Tasks (0)')

    def test_missing_friendly_name_is_empty_string(self):
        self.assertEqual(_panel_title_text({'type': 'entity', 'data': 'x'}), '')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k "FitTitleSize or IncompleteItems or PanelTitleText" -v`
Expected: FAIL at import — `ImportError: cannot import name '_fit_title_size'`.

- [ ] **Step 3: Add the constants**

In `src/trmnl_server/components.py`, alongside `COMPONENT_TITLE_FONT_SIZE` at line 21:

```python
COMPONENT_TITLE_FONT_SIZE: int = 35
COMPONENT_SCALE: int = 2
# Panel titles are quantised to these sizes so that neighbouring panels land on
# the same rung instead of each shrinking to its own arbitrary fit.
TITLE_SIZE_LADDER: tuple[int, ...] = (35, 30, 26, 22, 18)
TITLE_PADDING: int = 20
```

- [ ] **Step 4: Add the helpers**

Insert after `_load_font` (which ends at line 45, before `_create_info_image`):

```python
def _incomplete_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Selects the todo items a panel actually displays.

    Args:
        items: Raw todo items, which may contain non-dict entries

    Returns:
        Items not marked completed, in their original order
    """
    return [
        it for it in items
        if isinstance(it, dict) and it.get('status', 'needs_action') != 'completed'
    ]


def _panel_title_text(render_data: "RenderData") -> str:
    """Returns the title string a panel will actually draw.

    Todo panels append their incomplete count to the friendly name, so measuring
    the friendly name alone would under-measure them.

    Args:
        render_data: Component render data

    Returns:
        The title string, including any suffix the component adds
    """
    name: str = str(render_data.get('friendly_name', ''))
    if render_data.get('type') == 'todo_list':
        data = render_data.get('data')
        total: int = len(_incomplete_items(data)) if isinstance(data, list) else 0
        return f"{name} ({total})"
    return name


def _fit_title_size(text: str, tile_width: int, logger: "Logger") -> int:
    """Picks the largest ladder rung whose title fits the given tile width.

    Runs before any canvas exists, so it measures with the font's own getbbox
    rather than ImageDraw.textbbox.

    Args:
        text: The title string that will be drawn
        tile_width: Unscaled width of the tile the title must fit
        logger: Logger instance

    Returns:
        A size from TITLE_SIZE_LADDER; the smallest rung if none fit
    """
    budget: int = (tile_width - TITLE_PADDING) * COMPONENT_SCALE
    for size in TITLE_SIZE_LADDER:
        font = _load_font(size * COMPONENT_SCALE, logger)
        bbox = font.getbbox(text)
        if bbox[2] - bbox[0] <= budget:
            return size
    return TITLE_SIZE_LADDER[-1]
```

`RenderData` is already imported in this module's `TYPE_CHECKING` block or from
`.models`; check the existing imports at the top of the file and add it in the
same style if it is not there yet.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k "FitTitleSize or IncompleteItems or PanelTitleText" -v`
Expected: PASS, 13 tests.

- [ ] **Step 6: Run the full suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: PASS. Nothing calls the new helpers yet, so no golden image should shift.

- [ ] **Step 7: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: add title size ladder and measurement helpers"
```

---

### Task 2: Thread `title_font_size` through the five drawing functions

**Files:**
- Modify: `src/trmnl_server/components.py`
  - `_draw_graph_component` (line 157; sizing block at ~191-204)
  - `_draw_entity_component` (line 393; sizing block at ~419-432)
  - `_draw_calendar_component` (line 504; font load at ~532)
  - `_draw_entities_component` (line 613; font load at ~639)
  - `_draw_todo_list_component` (line 721; font load at ~758, incomplete list at ~766-770)
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `COMPONENT_SCALE`, `TITLE_PADDING`, `_incomplete_items` from Task 1.
- Produces: each of the five functions gains keyword-only
  `title_font_size: int | None = None`. When an int, the title renders at exactly
  `title_font_size * COMPONENT_SCALE` and no per-function sizing runs. When
  `None`, behaviour is byte-identical to today.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_components.py`:

```python
class TestExplicitTitleFontSize(unittest.TestCase):
    """Every panel type must honour an externally resolved title size."""

    def test_graph_component_accepts_title_font_size(self):
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        points = [(start, 1.0), (end, 2.0)]
        img = _draw_graph_component(
            "Sensor", points, 400, 240, mock_logger,
            window_start=start, window_end=end, title_font_size=22,
        )
        self.assertEqual(img.size, (400, 240))

    def test_entity_component_accepts_title_font_size(self):
        img = _draw_entity_component("Sensor", 21.5, 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_calendar_component_accepts_title_font_size(self):
        img = _draw_calendar_component("Cal", [], 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_entities_component_accepts_title_font_size(self):
        img = _draw_entities_component("Ents", [], 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_todo_component_accepts_title_font_size(self):
        img = _draw_todo_list_component("Tasks", [], 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_explicit_size_actually_changes_the_title(self):
        """A larger title size must produce visibly different pixels."""
        small = _draw_entity_component("Sensor", 1, 400, 240, mock_logger, title_font_size=18)
        large = _draw_entity_component("Sensor", 1, 400, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(small.tobytes(), large.tobytes())

    def test_none_matches_the_default_rendering(self):
        """Omitting the argument must be identical to passing None."""
        a = _draw_entity_component("Sensor", 1, 400, 240, mock_logger)
        b = _draw_entity_component("Sensor", 1, 400, 240, mock_logger, title_font_size=None)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_explicit_size_overrides_the_shrink_loop(self):
        """A long title forced to 35 must differ from the same title left to shrink."""
        name = "Extremely Long Living Room Temperature Sensor Name"
        shrunk = _draw_entity_component(name, 1, 300, 240, mock_logger)
        forced = _draw_entity_component(name, 1, 300, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(shrunk.tobytes(), forced.tobytes())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k ExplicitTitleFontSize -v`
Expected: FAIL with `TypeError: _draw_graph_component() got an unexpected keyword argument 'title_font_size'`.

- [ ] **Step 3: Update `_draw_graph_component`**

Add the parameter to the keyword-only block in its signature (after `zero_baseline: bool = False`):

```python
    title_font_size: int | None = None,
```

Document it in the docstring's `Args:` block:

```
        title_font_size: Title size resolved by the caller. When None, the
            title shrinks to fit this component's own width.
```

Change the local `scale: int = 2` to `scale: int = COMPONENT_SCALE`, then replace
the sizing block (currently lines ~191-204) with:

```python
    try:
        padding: int = TITLE_PADDING * scale
        if title_font_size is not None:
            resolved_title_size: int = title_font_size * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        else:
            resolved_title_size = COMPONENT_TITLE_FONT_SIZE * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
            title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
            title_width_val: int = title_bbox[2] - title_bbox[0]

            while title_width_val > large_width - padding:
                resolved_title_size -= 2
                if resolved_title_size <= 8:
                    break
                font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
                title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
                title_width_val = title_bbox[2] - title_bbox[0]

        font_axes = ImageFont.truetype(NOTO_FONT, 15 * scale)
        font_value = ImageFont.truetype(NOTO_FONT, 30 * scale)
    except IOError:
```

Leave the `except IOError:` body untouched.

- [ ] **Step 4: Update `_draw_entity_component`**

Add `title_font_size: int | None = None` as a keyword-only parameter (add a bare
`*,` before it, since this function has no keyword-only block yet) and document
it with the same wording. Change `scale: int = 2` to `scale: int = COMPONENT_SCALE`.
Replace the sizing block at ~419-432 with:

```python
    padding: int = TITLE_PADDING * scale
    font_title = ImageFont.load_default()
    try:
        if title_font_size is not None:
            resolved_title_size: int = title_font_size * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
        else:
            resolved_title_size = COMPONENT_TITLE_FONT_SIZE * scale
            font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
            title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
            title_width_val: int = title_bbox[2] - title_bbox[0]

            while title_width_val > large_width - padding:
                resolved_title_size -= 2
                if resolved_title_size <= 8:
                    break
                font_title = ImageFont.truetype(NOTO_FONT, resolved_title_size)
                title_bbox = d.textbbox((0, 0), friendly_name, font=font_title)
                title_width_val = title_bbox[2] - title_bbox[0]
    except IOError:
```

Leave the `except IOError:` body untouched.

- [ ] **Step 5: Update the three non-shrinking components**

For `_draw_calendar_component`, `_draw_entities_component` and
`_draw_todo_list_component`: add keyword-only `title_font_size: int | None = None`
(calendar and entities need a bare `*,` added; todo already has one), document it
identically, change `scale: int = 2` to `scale: int = COMPONENT_SCALE`, and
replace each function's title font load with:

```python
        font_title = ImageFont.truetype(
            NOTO_FONT, (title_font_size or COMPONENT_TITLE_FONT_SIZE) * scale
        )
```

These three previously drew at a fixed 35 and overflowed their tile. Supplying a
resolved size fixes that overflow as a consequence.

In `_draw_todo_list_component` only, also replace the inline comprehension:

```python
    incomplete: list[dict[str, str]] = [
        it for it in items
        if isinstance(it, dict) and it.get('status', 'needs_action') != 'completed'
    ]
    total: int = len(incomplete)
```

with:

```python
    incomplete: list[dict[str, str]] = _incomplete_items(items)
    total: int = len(incomplete)
```

so the drawn title and the measured title share one definition of "incomplete".

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k ExplicitTitleFontSize -v`
Expected: PASS, 8 tests.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, including all golden image tests. Nothing passes a
`title_font_size` yet, so rendering is unchanged. **If a golden test fails here,
the `None` path is not byte-identical — fix it rather than regenerating the
golden.**

- [ ] **Step 8: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: let callers supply a resolved panel title font size"
```

---

### Task 3: Resolve one title size per row in `tile_components`

**Files:**
- Modify: `src/trmnl_server/components.py` — `tile_components` (line 873), its nested `_render_component` (line 909), and the layout branches (lines ~981-1032)
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `_fit_title_size`, `_panel_title_text`, `COMPONENT_TITLE_FONT_SIZE` from Task 1; the `title_font_size` keyword from Task 2.
- Produces: no new public names. `tile_components` keeps its existing signature
  `(component_render_data, width, height, top_margin, logger) -> Image.Image`.

**Layout facts you will need:** the grid branch uses `rows = ceil(sqrt(n))` and
`cols = ceil(n / rows)`. So `n=2` is two stacked rows of one, `n=3` is a row of
two above a row of one, and `n=4` is a 2x2 grid. Tests below rely on this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_components.py`:

```python
class TestRowTitleSizeHarmonisation(unittest.TestCase):
    """Panels in a row share one title size; rows may differ."""

    LONG = "Extremely Long Living Room Temperature Sensor Name"

    def _sizes(self, render_data):
        """Renders a dashboard and returns the title_font_size each panel got."""
        captured = []

        def fake_draw(friendly_name, value, width, height, logger, *, title_font_size=None):
            captured.append((friendly_name, title_font_size))
            return Image.new('RGB', (width, height), color='white')

        with mock.patch('trmnl_server.components._draw_entity_component', side_effect=fake_draw):
            tile_components(render_data, 800, 480, 40, mock_logger)
        return dict(captured)

    def _panel(self, name, large=False):
        return {'type': 'entity', 'friendly_name': name, 'data': 'v', 'large_display': large}

    def test_panels_in_the_same_row_get_the_same_size(self):
        # n=4 gives a 2x2 grid: row 0 is A and B, row 1 is C and the long title.
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel(self.LONG),
        ])
        self.assertEqual(sizes['C'], sizes[self.LONG])

    def test_a_row_with_a_long_title_uses_a_second_smaller_size(self):
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel(self.LONG),
        ])
        self.assertEqual(sizes['A'], sizes['B'])
        self.assertLess(sizes[self.LONG], sizes['A'])

    def test_every_resolved_size_is_a_ladder_rung(self):
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel(self.LONG),
        ])
        for size in sizes.values():
            self.assertIn(size, TITLE_SIZE_LADDER)

    def test_all_short_titles_collapse_to_one_size(self):
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel('D'),
        ])
        self.assertEqual(len(set(sizes.values())), 1)

    def test_large_display_panel_is_sized_independently(self):
        """The full-width panel is fitted to its own width, not the row below."""
        sizes = self._sizes([
            self._panel(self.LONG, large=True),
            self._panel('A'), self._panel('B'), self._panel('C'),
        ])
        # The large panel spans the full 800px, so it resolves against that
        # width alone -- independently of the three narrow panels beneath it.
        self.assertEqual(sizes[self.LONG], _fit_title_size(self.LONG, 800, mock_logger))
        self.assertEqual(sizes['A'], sizes['B'])
        self.assertEqual(sizes['B'], sizes['C'])

    def test_no_data_panels_are_excluded_from_the_row_minimum(self):
        """A placeholder's long name must not shrink its neighbour's title."""
        with_placeholder = [
            self._panel('A'), self._panel('B'),
            self._panel('C'), {'type': 'entity', 'friendly_name': self.LONG,
                               'data': None, 'large_display': False},
        ]
        sizes = self._sizes(with_placeholder)
        self.assertEqual(sizes['C'], 35)

    def test_row_of_only_no_data_panels_does_not_crash(self):
        sizes = self._sizes([
            {'type': 'entity', 'friendly_name': 'X', 'data': None, 'large_display': False},
            {'type': 'entity', 'friendly_name': 'Y', 'data': None, 'large_display': False},
        ])
        self.assertEqual(sizes, {})

    def test_empty_component_list_still_returns_a_blank_image(self):
        img = tile_components([], 800, 480, 40, mock_logger)
        self.assertEqual(img.size, (800, 480))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_components.py -k RowTitleSizeHarmonisation -v`
Expected: FAIL — `fake_draw` receives `title_font_size=None`, so
`test_panels_in_the_same_row_get_the_same_size` passes trivially while
`test_a_row_with_a_long_title_uses_a_second_smaller_size` fails on
`assertLess(None, None)` raising `TypeError`.

- [ ] **Step 3: Give `_render_component` a title size parameter**

Change its signature to:

```python
    def _render_component(
        render_data: RenderData,
        tile_width: int,
        tile_height: int,
        title_font_size: int,
    ) -> Image.Image:
```

and pass `title_font_size=title_font_size` to each of the five
`_draw_*_component` calls in its body. The `_create_info_image` calls (the
`data is None` branch and the unknown-type branch) do not take it — leave them.

In the `todo_list` branch, replace the inline incomplete-count computation:

```python
            total_incomplete = sum(
                1 for it in items_list
                if isinstance(it, dict) and it.get('status', 'needs_action') != 'completed'
            )
```

with:

```python
            total_incomplete = len(_incomplete_items(items_list))
```

- [ ] **Step 4: Replace both layout branches with a placement list**

Replace everything from `available_height: int = height - top_margin` down to
`return final_image` with:

```python
    available_height: int = height - top_margin

    # Geometry is resolved before rendering so that each row's panels can agree
    # on one title size. A row is exactly the set of panels drawn side by side.
    rows: list[list[tuple[RenderData, int, int, int, int]]] = []

    if large_component_data:
        # Top half for the large component; it forms its own row because it has
        # the full width to itself.
        large_height: int = available_height // 2
        rows.append([(large_component_data, 0, top_margin, width, large_height)])

        num_components: int = len(other_components_data)
        if num_components > 0:
            bottom_y_start: int = top_margin + large_height
            bottom_available_height: int = height - bottom_y_start

            cols: int = num_components
            tile_width: int = width // cols
            tile_height: int = bottom_available_height

            if tile_width > 0 and tile_height > 0:
                rows.append([
                    (render_data, i * tile_width, bottom_y_start, tile_width, tile_height)
                    for i, render_data in enumerate(other_components_data)
                ])
    else:
        # Tile all in a grid
        num_components = len(component_render_data)
        num_rows: int = int(ceil(sqrt(num_components)))
        cols = int(ceil(num_components / num_rows))

        tile_width = width // cols
        tile_height = available_height // num_rows

        if tile_width > 0 and tile_height > 0:
            for row_index in range(num_rows):
                row_placements = [
                    (
                        render_data,
                        (i % cols) * tile_width,
                        top_margin + (i // cols) * tile_height,
                        tile_width,
                        tile_height,
                    )
                    for i, render_data in enumerate(component_render_data)
                    if i // cols == row_index
                ]
                if row_placements:
                    rows.append(row_placements)

    for row in rows:
        # Panels rendering as no-data placeholders draw a centred message rather
        # than a title, so they must not drag their neighbours' size down.
        title_font_size: int = min(
            (
                _fit_title_size(_panel_title_text(render_data), tile_w, logger)
                for render_data, _, _, tile_w, _ in row
                if render_data.get('data') is not None
            ),
            default=COMPONENT_TITLE_FONT_SIZE,
        )
        for render_data, x, y, tile_w, tile_h in row:
            component_image = _render_component(render_data, tile_w, tile_h, title_font_size)
            if component_image:
                final_image.paste(component_image, (x, y))

    return final_image
```

Remove the now-unused `component_image: Image.Image` annotation from the old
large-component block if it no longer type-checks; declare it in the loop above
instead.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_components.py -k RowTitleSizeHarmonisation -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Run the full unit and integration suite**

Run: `uv run pytest tests/test_components.py -q`
Expected: PASS. `TestTileComponents` at line 594 only asserts
`isinstance(img, Image.Image)`, so it is unaffected by the refactor.

- [ ] **Step 7: Confirm the golden tests now fail for the right reason**

Run: `uv run pytest tests/test_golden.py -q`
Expected: some tests FAIL. This is expected — title sizes have legitimately
changed. Do not regenerate them here; Task 4 handles that. Record which golden
tests failed, you will need the list.

- [ ] **Step 8: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: harmonise panel title font size across each row"
```

---

### Task 4: End-to-end golden coverage and golden regeneration

**Files:**
- Modify: `tests/test_golden.py`
- Modify: `tests/golden/*.png` (regenerated)
- Create: `tests/golden/title_size_harmonisation.png` (generated by the run)

**Interfaces:**
- Consumes: the full rendering path via `render_dashboard_image`.
- Produces: no code interfaces; a new golden reference image.

- [ ] **Step 1: Write the new end-to-end golden test**

Add to `tests/test_golden.py`, inside `TestGoldenImages`, following the style of
`test_entity_dashboard` at line 172:

```python
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_title_size_harmonisation(self, mock_get_entity_state):
        """Four panels in a 2x2 grid: the top row shares one title size, the
        bottom row drops to a smaller one because of a long title."""
        mock_get_entity_state.return_value = {'state': '21.5', 'attributes': {}}
        dashboard = {
            'name': 'harmonisation',
            'title': 'Harmonisation',
            'components': [
                {'entity_name': 'sensor.a', 'friendly_name': 'Kitchen', 'type': 'entity'},
                {'entity_name': 'sensor.b', 'friendly_name': 'Hallway', 'type': 'entity'},
                {'entity_name': 'sensor.c', 'friendly_name': 'Study', 'type': 'entity'},
                {'entity_name': 'sensor.d',
                 'friendly_name': 'Extremely Long Living Room Temperature Sensor',
                 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'title_size_harmonisation')
```

- [ ] **Step 2: Generate the new golden and inspect it**

Run: `uv run pytest tests/test_golden.py::TestGoldenImages::test_title_size_harmonisation -q`
Expected: PASS — `assert_golden` creates the file on first run because it does
not exist yet.

Then open `tests/golden/title_size_harmonisation.png` and **look at it**. Confirm
by eye: "Kitchen", "Hallway" and "Study" render at the same size as each other's
row-mates, and the long title's row is uniformly smaller — not one large title
next to one small one. If it does not look right, the bug is in Task 3, not here.

- [ ] **Step 3: Regenerate the pre-existing goldens**

Run: `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py -q`
Expected: PASS, all goldens rewritten.

- [ ] **Step 4: Inspect every regenerated golden**

Run: `git diff --stat tests/golden/`

For each `.png` that changed, open both the new file and the committed version
(`git show HEAD:tests/golden/<name>.png > /tmp/<name>-old.png`) and compare them
by eye. The only differences should be title font sizes. **Any change to graph
lines, calendar text, todo items, layout or margins is a bug — stop and
investigate rather than accepting the new golden.**

Single-component dashboards should be unchanged, since a lone panel is a row of
one and keeps its own fitted size.

- [ ] **Step 5: Delete stale diff artifacts**

Run: `rm -f tests/golden/*.diff.png`

These are debugging leftovers from failed comparisons and must not be committed.
Check whether any are already tracked with `git ls-files tests/golden/`; if
`entity_attribute_dashboard.diff.png` and `history_graph_bipolar.diff.png` are
tracked, remove them with `git rm` and mention it in the commit body.

- [ ] **Step 6: Run the entire suite**

Run: `uv run pytest -q`
Expected: PASS, all tests including the network-dependent
`tests/test_firmware_e2e.py`. If you are offline, run
`uv run pytest -q --ignore=tests/test_firmware_e2e.py` and say so in your report.

- [ ] **Step 7: Commit**

```bash
git add tests/test_golden.py tests/golden/
git commit -m "test: golden coverage for row title size harmonisation"
```

---

## Definition of done

- `uv run pytest -q` passes in full.
- A dashboard with four short titles renders one title size throughout.
- A dashboard mixing short and long titles renders at most two sizes, and panels
  side by side always match.
- The three previously non-shrinking component types no longer overflow their
  tile.
- Every regenerated golden has been inspected and differs only in title size.
