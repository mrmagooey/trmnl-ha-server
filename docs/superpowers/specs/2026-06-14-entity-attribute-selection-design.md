# Entity attribute selection — design

**Date:** 2026-06-14
**Status:** Approved

## Goal

Let users display a Home Assistant entity *attribute* instead of its `state`
in `entity` and `entities` dashboard components, via a new optional
`attribute` config field.

Home Assistant entities expose both a `state` and an `attributes` dict. The
server already fetches the full entity object (including `attributes`) via
`get_entity_state()`, but `entity` and `entities` components only read
`state_data.get('state')`. This feature surfaces the already-fetched
attributes to users.

## Non-goals

- `history_graph` attribute support (graphing an attribute over time) — out of
  scope for this change.
- `todo_list` / `calendar` changes — these already consume attributes in their
  own way.
- Nested attribute paths (e.g. `forecast.0.temperature`) — the separate
  `attribute` field leaves room to add this later, but it is not implemented
  now.

## Config syntax

A new optional `attribute` field. Absent or empty → current behavior (use
`state`). Fully backward compatible.

Single-value `entity` component:

```yaml
- entity_name: "climate.living_room"
  attribute: "current_temperature"   # NEW, optional
  friendly_name: "Living Room Temp"
  type: entity
```

Per-row in an `entities` list — each row independent, so state rows and
attribute rows can be mixed:

```yaml
- friendly_name: "Climate"
  type: entities
  entities:
    - entity_name: "climate.living_room"
      attribute: "current_temperature"   # NEW, optional
      friendly_name: "Temp"
    - entity_name: "sensor.humidity"      # no attribute → state, as today
      friendly_name: "Humidity"
```

### Why a separate field (not dotted/colon notation)

HA entity_ids are always `domain.object_id` with exactly one dot, and the
`object_id` is a slug that cannot contain a dot. Dotted notation
(`climate.living_room.temperature`) parses unambiguously for the common case,
but gets fragile at two edges: attribute names that themselves contain a dot,
and future nested-path access. A separate `attribute` field sidesteps both,
is trivially validated, and matches the existing TypedDict config style.

## Schema changes — `src/trmnl_server/models.py`

- `ComponentConfig` (already `total=False`): add `attribute: str`.
- `EntityItem` (currently a total TypedDict with required `entity_name` and
  `friendly_name`): add an optional `attribute` key. Keep `entity_name` and
  `friendly_name` required; mark `attribute` `NotRequired` so the two existing
  keys stay required while `attribute` is optional.

## Fetch/render changes — `src/trmnl_server/components.py`

A small shared helper selects the value from an already-fetched `EntityState`:

```python
def _select_entity_value(state_data, attribute, entity_name, logger):
    if state_data is None:
        return None
    if not attribute:
        return state_data.get('state')
    attrs = state_data.get('attributes', {})
    if attribute not in attrs:
        logger.warning(
            "Attribute %r not found on %s; rendering blank.",
            attribute, entity_name,
        )
        return None
    return str(attrs[attribute])   # stringify non-scalars
```

- `entity` branch (around line 1047): read `component.get('attribute')`, call
  the helper instead of `state_data.get('state')`. Continue to apply
  `_cast_to_numbers` to the result so numeric attributes render as numbers.
- `entities` branch (around line 1064): read `item.get('attribute')` per row,
  use the same helper, then `_cast_to_numbers` as today.

## Edge-case behavior

- **Missing attribute** (key not present on the entity): log a warning and
  return `None`. Mirrors existing missing-`state` behavior; the renderer
  already handles `None` gracefully.
- **Non-scalar value** (list/dict, e.g. a weather `forecast`): `str(value)`,
  displayed as-is. `_cast_to_numbers` leaves non-numeric strings untouched.

## Testing (all three levels)

- **Unit** — `_select_entity_value`:
  - no attribute → returns `state`
  - attribute present → returns its value
  - attribute missing → logs warning, returns `None`
  - non-scalar value → returns `str(value)`
  - `state_data is None` → returns `None`
- **Integration** — `entity` and `entities` rendering pipeline with a faked
  `get_entity_state` returning an `attributes` dict; assert the selected value
  flows into the produced `RenderData`. Include a mixed `entities` list
  (one attribute row, one state row).
- **E2E** — a dashboard config containing an `attribute` row rendered through
  the display path; assert the attribute value appears in the output.

## Documentation

- `README.md`: document the optional `attribute` field for `entity` and
  `entities`, with an example.
- `examples/config.yaml`: add an `attribute` example.
