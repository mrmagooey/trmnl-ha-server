# Todo List Columns + Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `todo_list` components in multiple columns and rotate through pages of items across e-ink refreshes when they overflow, with a per-card count and page indicator.

**Architecture:** A per-component `columns` config and a deterministic capacity (rows-per-column × columns, derived from card height, independent of item text). When incomplete items exceed one columned screenful, an in-memory page counter in `ServerState` rotates the visible page once per render. The pagination key is built in the render loop (which has `device_id`/dashboard name) and carried on `RenderData` to `_render_component` (which lacks them).

**Tech Stack:** Python 3.12, Pillow, stdlib, pytest.

**Branch:** `todo-list-columns-pagination` (work in an isolated worktree on this branch).

**Spec:** `docs/superpowers/specs/2026-06-08-todo-list-columns-pagination-design.md`

**Baseline:** `128 passed`. **Test command (everywhere):**
```
uv run --with pytest --with pyyaml pytest -q
```

---

## Shared constants (used by Tasks 2 and 3 — define once)

In `src/trmnl_server/components.py`, near the other module constants (e.g. by `COMPONENT_TITLE_FONT_SIZE`), these unscaled-pixel layout constants are introduced in Task 2 and reused in Task 3:
```python
TODO_HEADER_H: int = 50   # header band height (unscaled px)
TODO_ROW_H: int = 36      # per-item row height: checkbox(24) + spacing(12)
TODO_BOTTOM_PAD: int = 15 # bottom padding (unscaled px)
```

---

## File Structure

- `src/trmnl_server/state.py` — page counter store + `next_todo_page` / `reset_todo_pages`.
- `src/trmnl_server/components.py` — `_todo_capacity` helper, constants, rewritten `_draw_todo_list_component` (columns + pagination + header), wiring in the render loop + `_render_component`.
- `src/trmnl_server/models.py` — `columns` + `todo_key` on `RenderData`.
- Tests: `tests/test_state.py`, `tests/test_components.py`, `tests/test_golden.py`.
- Docs: `examples/config.yaml`, `README.md`, `AGENTS.md`.

---

## Task 1: Page counter in ServerState

**Files:**
- Modify: `src/trmnl_server/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py` (before any `if __name__` guard). It imports `ServerState` already; confirm and add this class:
```python
class TestTodoPagination(unittest.TestCase):
    """Tests for todo-list page rotation state."""

    def test_first_call_returns_zero(self):
        s = ServerState()
        self.assertEqual(s.next_todo_page("k", 3), 0)

    def test_advances_and_wraps(self):
        s = ServerState()
        seen = [s.next_todo_page("k", 3) for _ in range(4)]
        self.assertEqual(seen, [0, 1, 2, 0])

    def test_isolated_by_key(self):
        s = ServerState()
        self.assertEqual(s.next_todo_page("a", 2), 0)
        self.assertEqual(s.next_todo_page("a", 2), 1)
        # Different key has its own counter.
        self.assertEqual(s.next_todo_page("b", 2), 0)

    def test_single_page_never_rotates(self):
        s = ServerState()
        self.assertEqual(s.next_todo_page("k", 1), 0)
        self.assertEqual(s.next_todo_page("k", 1), 0)

    def test_reset_clears(self):
        s = ServerState()
        s.next_todo_page("k", 3)
        s.reset_todo_pages()
        self.assertEqual(s.next_todo_page("k", 3), 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --with pytest --with pyyaml pytest tests/test_state.py::TestTodoPagination -q`
Expected: FAIL — `AttributeError: 'ServerState' object has no attribute 'next_todo_page'`.

- [ ] **Step 3: Implement**

In `src/trmnl_server/state.py`, add a `_todo_pages` dict to `__init__` and the two methods. In `__init__`, after `self._battery_voltages: dict[str, float] = {}` add:
```python
        self._todo_pages: dict[str, int] = {}
```
Then add these methods to `ServerState` (after `consume_battery_voltage`):
```python
    def next_todo_page(self, key: str, num_pages: int) -> int:
        """Return the current page for a todo component, then advance it.

        Returns 0 (and stores nothing) when num_pages <= 1, so a list that
        fits one screenful never rotates.
        """
        if num_pages <= 1:
            return 0
        with self._lock:
            current = self._todo_pages.get(key, 0) % num_pages
            self._todo_pages[key] = (current + 1) % num_pages
            return current

    def reset_todo_pages(self) -> None:
        """Clear all todo page counters (used by tests)."""
        with self._lock:
            self._todo_pages.clear()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest --with pyyaml pytest tests/test_state.py::TestTodoPagination -q`
Expected: 5 passed.

- [ ] **Step 5: Full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `133 passed` (128 + 5).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/state.py tests/test_state.py
git commit -m "feat: Add todo-list page rotation state to ServerState

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `_todo_capacity` helper + layout constants

**Files:**
- Modify: `src/trmnl_server/components.py`
- Test: `tests/test_components.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_components.py`, add `_todo_capacity` to the `from trmnl_server.components import (...)` block:
```python
    _todo_capacity,
```
Add this test class at the end (before any `if __name__` guard):
```python
class TestTodoCapacity(unittest.TestCase):
    """Tests for todo-list page capacity math."""

    def test_single_column(self):
        # height 480 -> body = 480 - 50 - 15 = 415; 415 // 36 = 11 rows.
        rows, cap = _todo_capacity(480, 1)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 11)

    def test_multi_column_multiplies(self):
        rows, cap = _todo_capacity(480, 3)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 33)

    def test_minimum_one_row(self):
        # A tiny card still yields at least one row.
        rows, cap = _todo_capacity(10, 2)
        self.assertEqual(rows, 1)
        self.assertEqual(cap, 2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestTodoCapacity -q`
Expected: FAIL — `ImportError: cannot import name '_todo_capacity'`.

- [ ] **Step 3: Implement constants + helper**

In `src/trmnl_server/components.py`, near `COMPONENT_TITLE_FONT_SIZE`, add:
```python
TODO_HEADER_H: int = 50
TODO_ROW_H: int = 36
TODO_BOTTOM_PAD: int = 15
```
Then add this function at module level, immediately above `def _draw_todo_list_component(`:
```python
def _todo_capacity(height: int, columns: int) -> tuple[int, int]:
    """Compute todo-list page capacity for a component of the given height.

    Works in unscaled pixels (the draw function applies its own scale). The
    row count is scale-invariant, so this and the draw function agree.

    Args:
        height: Component (tile) height in unscaled pixels.
        columns: Number of columns (>= 1).

    Returns:
        (rows_per_column, capacity) where capacity = rows_per_column * columns.
    """
    cols = columns if isinstance(columns, int) and columns > 0 else 1
    body = height - TODO_HEADER_H - TODO_BOTTOM_PAD
    rows_per_column = max(1, body // TODO_ROW_H)
    return rows_per_column, rows_per_column * cols
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestTodoCapacity -q`
Expected: 3 passed.

- [ ] **Step 5: Full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `136 passed` (133 + 3).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Add todo-list page capacity helper and layout constants

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Columns + pagination rendering in `_draw_todo_list_component`

**Files:**
- Modify: `src/trmnl_server/components.py` (`_draw_todo_list_component`)
- Test: `tests/test_components.py`

The current function draws a single column and silently breaks on overflow. Replace its body with a column-major, paginated layout. The signature gains keyword-only `columns`/`page` with defaults, so existing callers and tests keep working.

- [ ] **Step 1: Write the new tests**

In `tests/test_components.py`, add this class at the end (the existing `TestDrawTodoListComponent` stays unchanged — its calls use the new defaults):
```python
class TestTodoListPaginationRender(unittest.TestCase):
    """Tests for columns + pagination in _draw_todo_list_component."""

    @staticmethod
    def _items(n):
        return [{'summary': f'Item {i}', 'status': 'needs_action'} for i in range(n)]

    def test_count_in_title(self):
        # 5 incomplete items -> title contains "(5)".
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("Shopping", self._items(5), 400, 300, mock_logger)
        drawn = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertIn("Shopping (5)", drawn)

    def test_page_indicator_only_when_multipage(self):
        # One page (few items): no "/" indicator.
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", self._items(3), 400, 300, mock_logger, columns=1, page=0)
        single = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertNotIn("/", single)
        # Many items at 1 column on a short card -> multiple pages -> "1/N".
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", self._items(60), 400, 300, mock_logger, columns=1, page=0)
        multi = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertRegex(multi, r"1/\d+")

    def test_pagination_shows_different_items_per_page(self):
        from PIL import ImageChops
        items = self._items(60)
        page0 = _draw_todo_list_component("L", items, 400, 300, mock_logger, columns=1, page=0)
        page1 = _draw_todo_list_component("L", items, 400, 300, mock_logger, columns=1, page=1)
        self.assertIsNotNone(
            ImageChops.difference(page0, page1).getbbox(),
            "different pages must render different items",
        )

    def test_columns_fit_more_than_single_column(self):
        # With 2 columns a card holds more items on one page than with 1 column,
        # so a count that paginates at 1 column may fit on a single 2-col page.
        # Card height 480 -> 11 rows/column; 2 columns -> capacity 22.
        items = self._items(20)
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", items, 400, 480, mock_logger, columns=2, page=0)
        two_col = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        # 20 items <= 22 capacity -> single page, no indicator.
        self.assertNotIn("/", two_col)

    def test_long_item_is_truncated_with_ellipsis(self):
        long_item = [{'summary': 'X' * 200, 'status': 'needs_action'}]
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", long_item, 400, 300, mock_logger, columns=2, page=0)
        drawn = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertIn("…", drawn)  # ellipsis character

    def test_empty_list_message_unchanged(self):
        img = _draw_todo_list_component("L", [], 400, 300, mock_logger)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestTodoListPaginationRender -q`
Expected: FAIL — `test_count_in_title` (no "(5)") and others fail, because the current function neither adds the count nor accepts `columns`/`page` (TypeError on the `columns=` kwarg).

- [ ] **Step 3: Rewrite `_draw_todo_list_component`**

Replace the entire current `_draw_todo_list_component` function in `src/trmnl_server/components.py` with:
```python
def _draw_todo_list_component(
    friendly_name: str,
    items: list[dict[str, str]],
    width: int,
    height: int,
    logger: "Logger",
    *,
    columns: int = 1,
    page: int = 0,
) -> Image.Image:
    """Draws a todo list with checkboxes, columns, and pagination.

    Incomplete items are laid out column-major across `columns` columns. When
    they overflow one screenful, the list paginates: `page` selects which
    screenful to show (wrapping), and a page indicator is drawn. The title
    shows the total incomplete count.

    Args:
        friendly_name: Display name for the component
        items: List of todo items with 'summary' and 'status' keys
        width: Component width in pixels
        height: Component height in pixels
        logger: Logger instance
        columns: Number of columns (>= 1; invalid coerced to 1)
        page: Page index to render (wrapped modulo the page count)

    Returns:
        Rendered PIL Image
    """
    cols: int = columns if isinstance(columns, int) and columns > 0 else 1
    scale: int = 2
    large_width: int = width * scale
    large_height: int = height * scale
    img = Image.new('RGB', (large_width, large_height), color='white')
    d = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(NOTO_FONT, COMPONENT_TITLE_FONT_SIZE * scale)
        font_indicator = ImageFont.truetype(NOTO_FONT, 18 * scale)
    except IOError:
        if not _font_warned[0]:
            logger.warning("%s not found. Using default font.", NOTO_FONT)
            _font_warned[0] = True
        font_title = ImageFont.load_default()
        font_indicator = ImageFont.load_default()

    incomplete: list[dict[str, str]] = [
        it for it in items if it.get('status', 'needs_action') != 'completed'
    ]
    total: int = len(incomplete)

    # Title with count.
    title_text: str = f"{friendly_name} ({total})"
    title_bbox = d.textbbox((0, 0), title_text, font=font_title)
    title_width: int = title_bbox[2] - title_bbox[0]
    d.text(((large_width - title_width) / 2, 5 * scale), title_text, font=font_title, fill='black')

    if total == 0:
        msg: str = "No items to display"
        font_item = font_indicator
        try:
            font_item = ImageFont.truetype(NOTO_FONT, 28 * scale)
        except IOError:
            pass
        msg_bbox = d.textbbox((0, 0), msg, font=font_item)
        msg_width: int = msg_bbox[2] - msg_bbox[0]
        d.text(((large_width - msg_width) / 2, TODO_HEADER_H * scale), msg, font=font_item, fill='black')
        return img.resize((width, height), Image.LANCZOS)

    rows_per_column, capacity = _todo_capacity(height, cols)
    num_pages: int = max(1, ceil(total / capacity))
    page_idx: int = page % num_pages
    page_items: list[dict[str, str]] = incomplete[page_idx * capacity:(page_idx + 1) * capacity]

    # Page indicator (top-right) only when paginating.
    if num_pages > 1:
        indicator: str = f"{page_idx + 1}/{num_pages}"
        ind_bbox = d.textbbox((0, 0), indicator, font=font_indicator)
        ind_width: int = ind_bbox[2] - ind_bbox[0]
        d.text((large_width - ind_width - 10 * scale, 12 * scale), indicator, font=font_indicator, fill='black')

    header_y: int = TODO_HEADER_H * scale
    row_h: int = TODO_ROW_H * scale
    checkbox_size: int = 24 * scale
    col_width: int = large_width // cols

    for i, item in enumerate(page_items):
        col: int = i // rows_per_column
        row: int = i % rows_per_column
        col_x: int = col * col_width
        y: int = header_y + row * row_h

        checkbox_x: int = col_x + 15 * scale
        d.rectangle(
            [(checkbox_x, y), (checkbox_x + checkbox_size, y + checkbox_size)],
            outline='black',
            width=2,
        )

        text_x: int = checkbox_x + checkbox_size + 8 * scale
        available_width: int = col_width - (text_x - col_x) - 8 * scale
        summary: str = item.get('summary', '')

        # Shrink to fit the column width; ellipsis-truncate at the floor.
        font_size: int = 28 * scale
        try:
            dyn_font = ImageFont.truetype(NOTO_FONT, font_size)
            text_bbox = d.textbbox((0, 0), summary, font=dyn_font)
            while (text_bbox[2] - text_bbox[0]) > available_width and font_size > 16:
                font_size -= 2
                dyn_font = ImageFont.truetype(NOTO_FONT, font_size)
                text_bbox = d.textbbox((0, 0), summary, font=dyn_font)
            # Still too wide at the floor -> ellipsis-truncate.
            if (text_bbox[2] - text_bbox[0]) > available_width and len(summary) > 1:
                truncated = summary
                while truncated and (d.textbbox((0, 0), truncated + '…', font=dyn_font)[2]) > available_width:
                    truncated = truncated[:-1]
                summary = (truncated + '…') if truncated else '…'
                text_bbox = d.textbbox((0, 0), summary, font=dyn_font)
        except IOError:
            dyn_font = ImageFont.load_default()
            text_bbox = d.textbbox((0, 0), summary, font=dyn_font)

        text_y: int = y + (checkbox_size - (text_bbox[3] - text_bbox[1])) // 2
        d.text((text_x, text_y), summary, font=dyn_font, fill='black')

    return img.resize((width, height), Image.LANCZOS)
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `uv run --with pytest --with pyyaml pytest tests/test_components.py::TestTodoListPaginationRender tests/test_components.py::TestDrawTodoListComponent -q`
Expected: all pass (6 new + 4 existing = 10).

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `142 passed` (136 + 6).

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Column-major, paginated todo_list rendering with count + indicator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire columns + pagination through the render path

**Files:**
- Modify: `src/trmnl_server/models.py`, `src/trmnl_server/components.py`
- Test: `tests/test_components.py`

- [ ] **Step 1: Add config + RenderData fields (models.py)**

In `src/trmnl_server/models.py`:
- Add `columns` to `ComponentConfig` (already `total=False`), after `large_display: bool`:
  ```python
      columns: int
  ```
- Add two `NotRequired` keys to `RenderData` (it is already `total=False` with `Required`/`NotRequired` from the graph feature). After the `window_end` key add:
  ```python
      columns: NotRequired[int]
      todo_key: NotRequired[str]
  ```

- [ ] **Step 2: Build the key + columns in the render loop (components.py)**

In `render_dashboard_image`, change the loop header from:
```python
    for component in components:
```
to:
```python
    for component_index, component in enumerate(components):
```
Then add a `todo_meta` variable alongside the existing `graph_window` initialization. Immediately after the line `graph_window: tuple[datetime, datetime] | None = None` add:
```python
        todo_meta: tuple[int, str] | None = None
```
Replace the existing `todo_list` branch:
```python
        elif component_type == 'todo_list':
            from .hass_client import _fetch_todo_list
            entity_name = component.get('entity_name', '')
            data = _fetch_todo_list(entity_name, logger)
```
with:
```python
        elif component_type == 'todo_list':
            from .hass_client import _fetch_todo_list
            entity_name = component.get('entity_name', '')
            data = _fetch_todo_list(entity_name, logger)
            todo_columns = component.get('columns', 1)
            if isinstance(todo_columns, bool) or not isinstance(todo_columns, int) or todo_columns <= 0:
                logger.warning(
                    "Invalid 'columns' (%r) for %s; defaulting to 1.",
                    todo_columns, component.get('friendly_name'),
                )
                todo_columns = 1
            dashboard_name: str = dashboard.get('name', '')
            todo_key: str = f"{device_id}:{dashboard_name}:{entity_name}:{component_index}"
            todo_meta = (todo_columns, todo_key)
```
Then where the `render_entry` window keys are attached, add the todo keys. After:
```python
        if graph_window is not None:
            render_entry['window_start'] = graph_window[0]
            render_entry['window_end'] = graph_window[1]
```
add:
```python
        if todo_meta is not None:
            render_entry['columns'] = todo_meta[0]
            render_entry['todo_key'] = todo_meta[1]
```

- [ ] **Step 3: Consume them in `_render_component` (components.py)**

`_render_component` is nested inside `tile_components`. At the very top of `tile_components` (just inside the function, before `_render_component` is defined), add a local import:
```python
    from .state import server_state
```
Then replace the `_render_component` todo branch:
```python
        elif component_type == 'todo_list':
            return _draw_todo_list_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
            )
```
with:
```python
        elif component_type == 'todo_list':
            todo_columns = render_data.get('columns', 1)
            todo_key = render_data.get('todo_key')
            items_list = data if isinstance(data, list) else []
            total_incomplete = sum(
                1 for it in items_list
                if isinstance(it, dict) and it.get('status', 'needs_action') != 'completed'
            )
            _, capacity = _todo_capacity(tile_height, todo_columns)
            num_pages = max(1, ceil(total_incomplete / capacity))
            page = server_state.next_todo_page(todo_key, num_pages) if todo_key else 0
            return _draw_todo_list_component(
                friendly_name,
                data,  # type: ignore[arg-type]
                tile_width,
                tile_height,
                logger,
                columns=todo_columns,
                page=page,
            )
```

- [ ] **Step 4: Write an integration test**

In `tests/test_components.py`, find the `TestRenderDashboardImage` class. Add a `setUp` that resets pagination state (if the class has no `setUp`, add one; if it has one, add the reset line to it):
```python
    def setUp(self):
        from trmnl_server.state import server_state
        server_state.reset_todo_pages()
```
Then add this test method to that class:
```python
    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_overflow_renders_first_page(self, mock_fetch_todo):
        """A todo_list with more items than fit renders (page 0 on first render)."""
        mock_fetch_todo.return_value = [
            {'summary': f'Item {i}', 'status': 'needs_action'} for i in range(50)
        ]
        dashboard = {
            'name': 'chores',
            'components': [
                {'entity_name': 'todo.chores', 'friendly_name': 'Chores',
                 'type': 'todo_list', 'columns': 2},
            ],
        }
        img_io = render_dashboard_image(dashboard, mock_logger)
        self.assertIsInstance(img_io, io.BytesIO)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `143 passed` (142 + 1). If a pre-existing todo render test (`test_todo_list_component`) is now flaky due to shared pagination state, ensure its enclosing class's `setUp` calls `server_state.reset_todo_pages()` (Step 4 covers `TestRenderDashboardImage`; apply the same reset to any other class that renders todo components).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/models.py src/trmnl_server/components.py tests/test_components.py
git commit -m "feat: Wire todo_list columns + per-refresh pagination through render path

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Golden coverage + docs

**Files:**
- Test: `tests/test_golden.py`
- Modify: `examples/config.yaml`, `README.md`, `AGENTS.md`

- [ ] **Step 1: Add a golden test**

In `tests/test_golden.py`, add a `setUp` reset if not present (the class is `TestGoldenImages`; it already has a `setUp` calling `mock_logger.reset_mock()` — add the todo reset to it):
```python
        from trmnl_server.state import server_state
        server_state.reset_todo_pages()
```
Add this test inside `class TestGoldenImages`:
```python
    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_two_column_overflow(self, mock_fetch_todo):
        """A two-column todo list that overflows to multiple pages (page 0)."""
        mock_fetch_todo.return_value = [
            {'summary': f'Task {i}', 'status': 'needs_action'} for i in range(40)
        ]
        dashboard = {
            'name': 'tasks',
            'title': 'Tasks',
            'components': [
                {'entity_name': 'todo.tasks', 'friendly_name': 'Tasks',
                 'type': 'todo_list', 'columns': 2},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'todo_two_column_overflow')
```

- [ ] **Step 2: Generate and verify determinism**

Run: `UPDATE_GOLDEN=1 uv run --with pytest --with pyyaml pytest tests/test_golden.py -q`
Run: `uv run --with pytest --with pyyaml pytest tests/test_golden.py -q`
Expected: all golden tests pass on the second (comparison) run. (The reset in `setUp` guarantees page 0 each run, so it is deterministic.)

- [ ] **Step 3: Document `columns` in the example config**

In `examples/config.yaml`, find the commented todo example (the block with `type: "todo_list"` and `entity_name: "todo.shopping_list"`). Replace that commented block with:
```yaml
      # Example todo_list component (commented out):
      # - friendly_name: "Shopping List"
      #   type: "todo_list"
      #   entity_name: "todo.shopping_list"
      #   columns: 2   # optional, default 1; lay items into N columns.
      #   # When items overflow the card, it pages through them on each
      #   # refresh, showing the count and a page indicator (e.g. 2/3).
```

- [ ] **Step 4: Document `columns` in README.md**

In `README.md`, in the Component Types area near the `todo_list` row, add an option line below the table (consistent with the existing `hours` line):
```markdown
- `columns` (todo_list only, optional): number of columns to lay items into. Default `1`. When incomplete items overflow the card, it paginates — cycling to the next page on each refresh — and shows the item count plus a page indicator.
```

- [ ] **Step 5: Document in AGENTS.md**

In `AGENTS.md`, near the existing `history_graph`/component note, add:
```markdown
- `todo_list` components accept an optional `columns` field (default 1). Overflowing lists paginate across refreshes (page state held in `ServerState`, in-memory) and show a count + page indicator.
```

- [ ] **Step 6: Full suite**

Run: `uv run --with pytest --with pyyaml pytest -q`
Expected: `144 passed` (143 + 1 golden test).

- [ ] **Step 7: Commit**

```bash
git add tests/test_golden.py examples/config.yaml README.md AGENTS.md
git commit -m "test: Golden for two-column overflow todo; document columns option

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final Verification

- [ ] **Full suite:** `uv run --with pytest --with pyyaml pytest -q` → `144 passed`.
- [ ] **Determinism:** run the suite twice; golden tests pass both times.
- [ ] **Behavior smoke:**
  ```
  PYTHONPATH=src uv run --with pillow python3 -c "
  import logging
  from trmnl_server.components import _draw_todo_list_component
  items = [{'summary': f'Item {i}', 'status': 'needs_action'} for i in range(40)]
  p0 = _draw_todo_list_component('Chores', items, 400, 300, logging.getLogger(), columns=2, page=0)
  p1 = _draw_todo_list_component('Chores', items, 400, 300, logging.getLogger(), columns=2, page=1)
  from PIL import ImageChops
  print('pages differ:', ImageChops.difference(p0, p1).getbbox() is not None)
  "
  ```
  Expected: `pages differ: True`.
- [ ] **Tree clean** after the five commits.

## Notes / Out of Scope

- No `paginate: false` opt-out (future).
- No completed-item display, no auto-fit columns.
- Page state is in-memory (resets on restart) and keyed per device+dashboard+entity+index.
- Golden PNGs remain gitignored; regeneration produces no commit.
