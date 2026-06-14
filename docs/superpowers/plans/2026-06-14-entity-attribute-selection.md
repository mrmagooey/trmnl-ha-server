# Entity Attribute Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users display a Home Assistant entity *attribute* instead of its `state` in `entity` and `entities` components, via a new optional `attribute` config field.

**Architecture:** Add a shared `_select_entity_value()` helper in `hass_client.py` that, given an already-fetched `EntityState`, returns either the entity `state` (when no attribute is requested) or the named attribute's value (stringified). Wire it into the `entity` and `entities` branches of `render_dashboard_image()`. Add the `attribute` field to the config TypedDicts. The HA fetch path is unchanged — `get_entity_state()` already returns the full `attributes` dict.

**Tech Stack:** Python, Pillow (PIL), `unittest.mock`, pytest. Tests mock `trmnl_server.hass_client.get_entity_state` and render through `render_dashboard_image()`; golden tests compare full-render PNG output.

---

## File Structure

- `src/trmnl_server/models.py` — add `attribute` to `ComponentConfig` and `EntityItem` (schema).
- `src/trmnl_server/hass_client.py` — add `_select_entity_value()` helper (value selection logic, lives beside `_cast_to_numbers` and `_fetch_todo_list`).
- `src/trmnl_server/components.py` — call `_select_entity_value()` in the `entity` and `entities` branches of `render_dashboard_image()`.
- `tests/test_hass_client.py` — unit tests for `_select_entity_value()`.
- `tests/test_server.py` — integration tests rendering `entity`/`entities` dashboards with attributes.
- `tests/test_golden.py` — e2e golden test for an attribute dashboard.
- `README.md`, `examples/config.yaml` — documentation.

---

## Task 1: Add `attribute` to the config schema

**Files:**
- Modify: `src/trmnl_server/models.py:42-51` (`ComponentConfig`)
- Modify: `src/trmnl_server/models.py:28-31` (`EntityItem`)

`EntityItem` is currently a total TypedDict (both keys required). Keep both required and add `attribute` as `NotRequired`. `NotRequired` is already imported at `models.py:7`.

- [ ] **Step 1: Add `attribute` to `ComponentConfig`**

In `ComponentConfig` (a `total=False` TypedDict), add the field:

```python
class ComponentConfig(TypedDict, total=False):
    """Configuration for a single dashboard component."""
    entity_name: str
    attribute: str
    friendly_name: str
    type: Literal["history_graph", "entity", "calendar", "entities", "todo_list"]
    arguments: CalendarArguments
    entities: list[EntityItem]
    large_display: bool
    columns: int
    hours: int
```

- [ ] **Step 2: Add `attribute` to `EntityItem`**

```python
class EntityItem(TypedDict):
    """Single entity entry in an entities list."""
    entity_name: str
    friendly_name: str
    attribute: NotRequired[str]
```

- [ ] **Step 3: Commit**

```bash
git add src/trmnl_server/models.py
git commit -m "feat: Add optional attribute field to config schema"
```

---

## Task 2: Add `_select_entity_value()` helper (unit-tested, TDD)

**Files:**
- Modify: `src/trmnl_server/hass_client.py` (add helper after `_cast_to_numbers`, which ends at `hass_client.py:45`)
- Test: `tests/test_hass_client.py`

The helper takes an already-fetched `EntityState` (or `None`), the requested attribute name (or empty/`None`), the entity name (for log context), and a logger. It returns a `str` value or `None`. Non-scalar attribute values are stringified. A missing attribute logs a warning and returns `None`, mirroring missing-state behavior.

- [ ] **Step 1: Write the failing unit tests**

`tests/test_hass_client.py` uses `unittest` (it has `import unittest`, a module-level `mock_logger = mock.Mock(spec=logging.Logger)`, and a `from trmnl_server.hass_client import (...)` tuple). First add `_select_entity_value` to that import tuple:

```python
from trmnl_server.hass_client import (
    _cast_to_numbers,
    _fetch_history,
    _process_history_to_points,
    _select_entity_value,
)
```

Then add this test class (use a fresh logger per test so `assert_called_once()` is not polluted by the shared module-level `mock_logger`):

```python
class TestSelectEntityValue(unittest.TestCase):
    def setUp(self):
        self.logger = mock.Mock(spec=logging.Logger)

    def test_no_attribute_returns_state(self):
        state_data = {'state': 'cool', 'attributes': {'current_temperature': 21.5}}
        result = _select_entity_value(state_data, None, 'climate.lr', self.logger)
        self.assertEqual(result, 'cool')

    def test_empty_attribute_returns_state(self):
        state_data = {'state': 'cool', 'attributes': {'current_temperature': 21.5}}
        result = _select_entity_value(state_data, '', 'climate.lr', self.logger)
        self.assertEqual(result, 'cool')

    def test_attribute_present_returns_stringified_value(self):
        state_data = {'state': 'cool', 'attributes': {'current_temperature': 21.5}}
        result = _select_entity_value(state_data, 'current_temperature', 'climate.lr', self.logger)
        self.assertEqual(result, '21.5')

    def test_attribute_missing_warns_and_returns_none(self):
        state_data = {'state': 'cool', 'attributes': {}}
        result = _select_entity_value(state_data, 'current_temperature', 'climate.lr', self.logger)
        self.assertIsNone(result)
        self.logger.warning.assert_called_once()

    def test_non_scalar_attribute_is_stringified(self):
        forecast = [{'temp': 1}]
        state_data = {'state': 'sunny', 'attributes': {'forecast': forecast}}
        result = _select_entity_value(state_data, 'forecast', 'weather.home', self.logger)
        self.assertEqual(result, str(forecast))

    def test_none_state_data_returns_none(self):
        result = _select_entity_value(None, 'current_temperature', 'climate.lr', self.logger)
        self.assertIsNone(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hass_client.py::TestSelectEntityValue -v`
Expected: FAIL with `ImportError`/`cannot import name '_select_entity_value'`.

- [ ] **Step 3: Implement the helper**

Add to `src/trmnl_server/hass_client.py` immediately after `_cast_to_numbers` (after line 45). The module already imports `Logger`-style typing via the `"Logger"` forward ref used elsewhere in the file; match the existing signature style (`logger: "Logger"`). Import `EntityState` from `.models` if not already imported in this file — check the existing imports and add it to the existing `from .models import ...` line if present, otherwise add the import.

```python
def _select_entity_value(
    state_data: "EntityState | None",
    attribute: str | None,
    entity_name: str,
    logger: "Logger",
) -> str | None:
    """Select the display value for an entity: its state, or a named attribute.

    Returns the entity state when no attribute is requested. When an attribute
    is requested, returns its value as a string (non-scalars are stringified).
    A missing attribute logs a warning and returns None, mirroring the
    behavior when an entity has no state.
    """
    if state_data is None:
        return None
    if not attribute:
        return state_data.get('state')
    attributes = state_data.get('attributes', {})
    if attribute not in attributes:
        logger.warning(
            "Attribute %r not found on %s; rendering blank.",
            attribute, entity_name,
        )
        return None
    return str(attributes[attribute])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hass_client.py::TestSelectEntityValue -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/hass_client.py tests/test_hass_client.py
git commit -m "feat: Add _select_entity_value helper for attribute selection"
```

---

## Task 3: Wire attribute selection into the `entity` component (integration, TDD)

**Files:**
- Modify: `src/trmnl_server/components.py:1010-1014` (import block) and `:1047-1052` (`entity` branch)
- Test: `tests/test_server.py`

The integration test mocks `get_entity_state` to return an `attributes` dict and patches `_draw_entity_component` (a module-level function in `components.py`) to capture the `data` value selected by the pipeline, returning a blank image so the paste still works.

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_server.py` (it already imports `render_dashboard_image`, `mock`, and defines `mock_logger`). Add `from PIL import Image` if not present.

```python
    @mock.patch('trmnl_server.components._draw_entity_component')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_render_dashboard_image_entity_attribute(
        self, mock_get_entity_state, mock_draw_entity,
    ):
        """An entity component with `attribute` renders that attribute's value."""
        mock_get_entity_state.return_value = {
            'state': 'cool',
            'attributes': {'current_temperature': 21.5},
        }
        mock_draw_entity.return_value = Image.new('RGB', (10, 10), 'white')
        dashboard = {
            'name': 'test',
            'components': [
                {
                    'type': 'entity',
                    'entity_name': 'climate.living_room',
                    'attribute': 'current_temperature',
                    'friendly_name': 'Temp',
                },
            ],
        }

        render_dashboard_image(dashboard, mock_logger)

        # data is the 2nd positional arg of _draw_entity_component
        called_data = mock_draw_entity.call_args.args[1]
        assert called_data == 21.5  # '21.5' -> _cast_to_numbers -> float
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest "tests/test_server.py::TestServer::test_render_dashboard_image_entity_attribute" -v`
(`TestServer` holds the existing entity tests.)
Expected: FAIL — `called_data` is `'cool'` (state), not `21.5`, because the attribute is ignored.

- [ ] **Step 3: Update the import block and `entity` branch**

In `render_dashboard_image()`, add `_select_entity_value` to the `from .hass_client import (...)` block (currently `components.py:1010-1014`):

```python
    from .hass_client import (
        get_entity_state,
        _fetch_history,
        _fetch_calendar_events,
        _process_history_to_points,
        _cast_to_numbers,
        _select_entity_value,
    )
```

Replace the `entity` branch (`components.py:1047-1052`):

```python
        elif component_type == 'entity':
            entity_name = component.get('entity_name', '')
            attribute = component.get('attribute')
            state_data = get_entity_state(entity_name, logger)
            data = _select_entity_value(state_data, attribute, entity_name, logger)
            if data:
                data = _cast_to_numbers(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest "tests/test_server.py::TestServer::test_render_dashboard_image_entity_attribute" -v`
Expected: PASS.

- [ ] **Step 5: Run the existing entity test to confirm no regression**

Run: `python -m pytest "tests/test_server.py::TestServer::test_render_dashboard_image_entity" -v`
Expected: PASS (state-only path unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_server.py
git commit -m "feat: Support attribute selection in entity component"
```

---

## Task 4: Wire attribute selection into the `entities` component (integration, TDD)

**Files:**
- Modify: `src/trmnl_server/components.py:1064-1077` (`entities` branch)
- Test: `tests/test_server.py`

Each row in the `entities` list carries its own optional `attribute`, so a list can mix attribute rows and state rows.

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_server.py`, same class:

```python
    @mock.patch('trmnl_server.components._draw_entities_component')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_render_dashboard_image_entities_attribute_mixed(
        self, mock_get_entity_state, mock_draw_entities,
    ):
        """An entities list mixes an attribute row and a plain state row."""
        mock_get_entity_state.side_effect = [
            {'state': 'cool', 'attributes': {'current_temperature': 21.5}},
            {'state': '55', 'attributes': {}},
        ]
        mock_draw_entities.return_value = Image.new('RGB', (10, 10), 'white')
        dashboard = {
            'name': 'test',
            'components': [
                {
                    'type': 'entities',
                    'friendly_name': 'Climate',
                    'entities': [
                        {
                            'entity_name': 'climate.living_room',
                            'attribute': 'current_temperature',
                            'friendly_name': 'Temp',
                        },
                        {
                            'entity_name': 'sensor.humidity',
                            'friendly_name': 'Humidity',
                        },
                    ],
                },
            ],
        }

        render_dashboard_image(dashboard, mock_logger)

        entity_states = mock_draw_entities.call_args.args[1]
        assert entity_states == [
            {'friendly_name': 'Temp', 'state': 21.5},
            {'friendly_name': 'Humidity', 'state': 55},
        ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest "tests/test_server.py::TestServer::test_render_dashboard_image_entities_attribute_mixed" -v`
Expected: FAIL — first row's `state` is `'cool'` (the state), not `21.5`.

- [ ] **Step 3: Update the `entities` branch**

Replace `components.py:1064-1077`:

```python
        elif component_type == 'entities':
            entity_list = component.get('entities', [])
            entity_states: list[dict[str, str | float | None]] = []
            for item in entity_list:
                entity_name = item.get('entity_name', '')
                attribute = item.get('attribute')
                state_data = get_entity_state(entity_name, logger)
                state: str | float | None = _select_entity_value(
                    state_data, attribute, entity_name, logger,
                )
                if state:
                    state = _cast_to_numbers(state)
                entity_states.append({
                    'friendly_name': item.get('friendly_name', ''),
                    'state': state,
                })
            data = entity_states
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest "tests/test_server.py::TestServer::test_render_dashboard_image_entities_attribute_mixed" -v`
Expected: PASS.

- [ ] **Step 5: Run the existing entities test to confirm no regression**

Run: `python -m pytest "tests/test_server.py::TestServer::test_render_dashboard_image_entities_list" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/components.py tests/test_server.py
git commit -m "feat: Support per-row attribute selection in entities component"
```

---

## Task 5: E2E golden test for an attribute dashboard

**Files:**
- Test: `tests/test_golden.py`
- Create: `tests/golden/entity_attribute_dashboard.png` (generated via `UPDATE_GOLDEN=1`)

This renders a full dashboard containing an attribute-backed `entity` component through `render_dashboard_image()` and compares the PNG to a golden reference — exercising the full select → cast → draw → tile → encode path.

- [ ] **Step 1: Write the e2e test**

Add to `tests/test_golden.py` (it imports `render_dashboard_image`, `mock`, `mock_logger`, and provides `assert_golden`). Follow the existing pattern of patching `trmnl_server.hass_client.get_entity_state`.

```python
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_entity_attribute_dashboard(self, mock_get_entity_state):
        mock_get_entity_state.return_value = {
            'state': 'cool',
            'attributes': {'current_temperature': 21.5},
        }
        dashboard = {
            'name': 'attr',
            'components': [
                {
                    'type': 'entity',
                    'entity_name': 'climate.living_room',
                    'attribute': 'current_temperature',
                    'friendly_name': 'Living Room Temp',
                },
            ],
        }
        img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'entity_attribute_dashboard')
```

- [ ] **Step 2: Generate the golden image**

Run: `UPDATE_GOLDEN=1 python -m pytest "tests/test_golden.py::TestGoldenImages::test_entity_attribute_dashboard" -v`
(`TestGoldenImages` holds the existing golden tests.)
Expected: PASS, and `tests/golden/entity_attribute_dashboard.png` is created. Visually confirm the PNG shows the temperature value `21.5` under "Living Room Temp".

- [ ] **Step 3: Re-run without UPDATE_GOLDEN to verify the comparison**

Run: `python -m pytest "tests/test_golden.py::TestGoldenImages::test_entity_attribute_dashboard" -v`
Expected: PASS (renders identically to the golden).

- [ ] **Step 4: Commit**

```bash
git add tests/test_golden.py tests/golden/entity_attribute_dashboard.png
git commit -m "test: Add e2e golden test for entity attribute rendering"
```

---

## Task 6: Documentation

**Files:**
- Modify: `README.md` (the component config section, around lines 63-110)
- Modify: `examples/config.yaml`

- [ ] **Step 1: Document the `attribute` field in README.md**

In the `entity` component documentation, add the optional `attribute` field with an explanation and example. Add the same note for `entities` rows. Use this wording:

> **`attribute`** *(optional, `entity` and `entities`)* — display a specific Home Assistant entity *attribute* instead of the entity state. Omit it to show the state (default). Example: a `climate.*` entity's `current_temperature`. Missing attributes render blank.

Add an example block:

```yaml
- entity_name: "climate.living_room"
  attribute: "current_temperature"
  friendly_name: "Living Room Temp"
  type: entity
```

- [ ] **Step 2: Add an example to examples/config.yaml**

Add an `attribute`-using entity (and a mixed `entities` row) near the existing `entity`/`entities` examples, with a brief comment:

```yaml
    # Show a specific attribute instead of the entity state
    - entity_name: "climate.living_room"
      attribute: "current_temperature"
      friendly_name: "Living Room Temp"
      type: entity
```

- [ ] **Step 3: Commit**

```bash
git add README.md examples/config.yaml
git commit -m "docs: Document entity attribute selection"
```

---

## Final verification

- [ ] **Run the full test suite**

Run: `python -m pytest -v`
Expected: all tests pass, including the new unit, integration, and golden tests.
