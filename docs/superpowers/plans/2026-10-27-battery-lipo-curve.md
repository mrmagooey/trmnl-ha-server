# Battery LiPo Curve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Battery percentage follows a LiPo discharge curve (3.0V = 0%, 4.2V = 100%) instead of a linear 2.4–4.2V map.

**Architecture:** `voltage_to_percent` in `metrics.py` interpolates linearly between the points of a 13-point module constant `_LIPO_CURVE`, clamping at both ends. It is already the single source for the on-screen text (`components.py`) and `/api/metrics`, so nothing else changes in `src/`.

**Tech Stack:** Python 3.12, Pillow, unittest/pytest via `uv`.

**Spec:** `docs/superpowers/specs/2026-10-27-battery-lipo-curve-design.md`

## Global Constraints

- Curve points (V → %), exactly: 3.00→0, 3.10→2, 3.20→5, 3.30→10, 3.42→20, 3.53→30, 3.63→40, 3.72→50, 3.80→60, 3.89→70, 3.99→80, 4.05→90, 4.20→100.
- `v <= 3.00` → 0; `v >= 4.20` → 100; result is `int(round(...))`.
- Validation bounds (2.4–4.2V in `state.py` and `api.py`) are NOT changed. No change to `api.py`, `state.py`, `components.py`.
- No smoothing, no consume-once change, no new logging (deferred by the spec).
- Test values must avoid exact `.5` ties (e.g. 3.25V).
- Code style per AGENTS.md: type hints, Google-style docstrings, `unittest.TestCase`, comments explain *why*.

## Review Focus

1. A reading between 2.4V and 3.0V (accepted by validation) shows 0%, never a negative or error. Covered by the clamp tests.
2. A reading exactly on a table point returns that point's percent, not an off-by-one from float error. Covered by the every-point test.
3. Readings just inside each end (3.01V, 4.19V) interpolate rather than hitting an index error in `bisect`. Covered by the monotonic sweep across 2.40–4.30V.
4. The on-screen text and `/api/metrics` show the same percent for the same reading. Covered by the components text test (48%) and the metrics e2e test (48).
5. Only the `entity_dashboard_with_battery` golden changes. Covered by the golden review step.

---

### Task 1: LiPo curve for `voltage_to_percent`

**Files:**
- Modify: `src/trmnl_server/metrics.py` (`_V_MIN`/`_V_MAX` constants ~L15-18, `voltage_to_percent` ~L31-38)
- Test: `tests/test_metrics.py` (`TestVoltageToPercent`)
- Test: `tests/test_components.py` (`TestBatteryPercentParity` ~L87-93)
- Test: `tests/test_api.py` (`TestAPIMetrics`, new method)
- Golden: `tests/golden/entity_dashboard_with_battery.png`
- Docs: `README.md` (`Battery-Voltage` row ~L283), `CHANGELOG.md` (`## [Unreleased]`)

**Interfaces:**
- Produces: `voltage_to_percent(voltage: float) -> int` (signature unchanged) and `_LIPO_CURVE: tuple[tuple[float, int], ...]`.

- [ ] **Step 1: Replace the unit tests in `tests/test_metrics.py`**

Change the import to also import `_LIPO_CURVE`:

```python
from trmnl_server.metrics import (
    ServeEvent,
    aggregate_metrics,
    voltage_to_percent,
    WINDOW_DAYS,
    _LIPO_CURVE,
)
```

Replace the whole `TestVoltageToPercent` class with:

```python
class TestVoltageToPercent(unittest.TestCase):
    """Battery percent follows a LiPo discharge curve, 3.0V = 0% to 4.2V = 100%."""

    CURVE = [
        (3.00, 0), (3.10, 2), (3.20, 5), (3.30, 10), (3.42, 20), (3.53, 30),
        (3.63, 40), (3.72, 50), (3.80, 60), (3.89, 70), (3.99, 80), (4.05, 90),
        (4.20, 100),
    ]

    def test_every_table_point_returns_its_percent(self):
        """A reading exactly on a curve point returns that point's percent."""
        for volts, pct in self.CURVE:
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), pct)

    def test_interpolates_between_points(self):
        """Values between points are interpolated linearly and rounded."""
        for volts, pct in ((3.7, 48), (3.35, 14), (3.76, 55), (3.05, 1), (4.1, 93)):
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), pct)

    def test_at_or_below_three_volts_is_zero(self):
        """3.0V is empty; lower readings that pass validation (down to 2.4V) clamp to 0."""
        for volts in (3.0, 2.9, 2.4, 2.0):
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), 0)

    def test_at_or_above_four_point_two_is_hundred(self):
        """4.2V and above is full."""
        for volts in (4.2, 4.3, 4.5):
            with self.subTest(volts=volts):
                self.assertEqual(voltage_to_percent(volts), 100)

    def test_percent_never_falls_as_voltage_rises(self):
        """Sweeping 2.40V to 4.30V in 0.01V steps never decreases and stays in 0..100."""
        previous = 0
        for step in range(240, 431):
            pct = voltage_to_percent(step / 100)
            self.assertGreaterEqual(pct, previous, f"dropped at {step / 100}V")
            self.assertTrue(0 <= pct <= 100)
            previous = pct

    def test_curve_constant_matches_spec_and_is_strictly_ascending(self):
        """bisect needs strictly ascending voltages; the points are the spec's table."""
        self.assertEqual(list(_LIPO_CURVE), self.CURVE)
        volts = [v for v, _ in _LIPO_CURVE]
        self.assertEqual(volts, sorted(set(volts)))
```

- [ ] **Step 2: Replace `TestBatteryPercentParity` in `tests/test_components.py`**

It asserts the legacy linear formula. Replace the class (keep the existing `from trmnl_server.metrics import voltage_to_percent` import only if still used; remove it if not) with:

```python
class TestBatteryTextUsesCurve(unittest.TestCase):
    """The on-screen battery text shows the LiPo-curve percent, as /api/metrics does."""

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    @mock.patch('trmnl_server.state.server_state')
    def test_three_point_seven_volts_renders_48_percent(self, mock_state, mock_get_entity_state):
        """3.7V was 72% on the old linear map; the curve gives 48%."""
        mock_get_entity_state.return_value = {'state': 'On'}
        mock_state.consume_battery_voltage.return_value = 3.7
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'entity'},
            ],
        }
        drawn: list[str] = []
        original_text = ImageDraw.ImageDraw.text

        def spy(self, xy, text, *args, **kwargs):
            drawn.append(text)
            return original_text(self, xy, text, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, 'text', spy):
            render_dashboard_image(dashboard, mock_logger, 'AA:BB:CC:DD:EE:FF')

        self.assertIn('48%', drawn)
        self.assertNotIn('72%', drawn)
```

Ensure `ImageDraw` is imported in the test module (`from PIL import ImageDraw` — check the existing PIL import line and extend it) and `render_dashboard_image` is imported (it is used elsewhere in the file).

- [ ] **Step 3: Add the end-to-end test to `TestAPIMetrics` in `tests/test_api.py`**

Append this method to `TestAPIMetrics` (it uses the class's existing `create_handler` and `setUp`):

```python
    @mock.patch('trmnl_server.api._aligned_refresh_rate', return_value=288)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_battery_header_reported_on_lipo_curve(self, mock_read_config, _vis, _rate):
        """A Battery-Voltage header sent via do_GET shows up in /api/metrics on the LiPo curve.

        3.30V is nearly empty: the curve reports 10%, where the old linear map said 50%.
        """
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'morning'}]}],
            'dashboards': [],
        }
        display = self.create_handler(
            '/api/display',
            {'ID': 'AA:BB:CC:DD:EE:FF', 'Battery-Voltage': '3.30'},
        )
        display.do_GET()
        self.assertEqual(display._response_code, 200)

        metrics = self.create_handler('/api/metrics')
        metrics.do_GET()
        metrics.wfile.seek(0)
        out = json.loads(metrics.wfile.read().decode())
        today = out['battery']['AA:BB:CC:DD:EE:FF']['daily'][-1]
        self.assertEqual(today['voltage'], 3.3)
        self.assertEqual(today['percent'], 10)
```

If `do_GET` on `/api/display` needs more stubbing than the existing `_handle_api_display` tests use, add only what it needs and explain why in the report.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metrics.py tests/test_components.py::TestBatteryTextUsesCurve "tests/test_api.py::TestAPIMetrics::test_battery_header_reported_on_lipo_curve" -q`
Expected: FAIL — `ImportError: cannot import name '_LIPO_CURVE'` for test_metrics; `'48%' not in [...]` for the components test; `50 != 10` for the API test.

- [ ] **Step 5: Implement in `src/trmnl_server/metrics.py`**

Add `import bisect` to the stdlib imports. Replace the `_V_MIN` / `_V_MAX` block and its comment with:

```python
# Single-cell LiPo resting voltage -> percent. TRMNL firmware reads the battery
# before Wi-Fi and the display turn on, so readings are close to open-circuit
# voltage. Points from 3.30V up are Meshtastic's OCV_ARRAY; below that the tail
# is stretched to 0% at 3.0V, matching TRMNL's own byos_laravel server and the
# TRMNL X firmware fallback. A linear map is wrong here: a LiPo spends most of
# its capacity on a flat plateau and falls steeply near empty.
# Voltages must be strictly ascending (voltage_to_percent bisects them).
_LIPO_CURVE: tuple[tuple[float, int], ...] = (
    (3.00, 0),
    (3.10, 2),
    (3.20, 5),
    (3.30, 10),
    (3.42, 20),
    (3.53, 30),
    (3.63, 40),
    (3.72, 50),
    (3.80, 60),
    (3.89, 70),
    (3.99, 80),
    (4.05, 90),
    (4.20, 100),
)
_LIPO_VOLTS: tuple[float, ...] = tuple(v for v, _ in _LIPO_CURVE)
```

Replace `voltage_to_percent` with:

```python
def voltage_to_percent(voltage: float) -> int:
    """Map a battery voltage to 0–100% along the LiPo discharge curve.

    Interpolates linearly between the two `_LIPO_CURVE` points that bracket
    `voltage`, clamping to 0 at or below 3.0V and 100 at or above 4.2V. Both
    the on-screen battery text and /api/metrics call this, so they always agree.
    """
    if voltage <= _LIPO_VOLTS[0]:
        return 0
    if voltage >= _LIPO_VOLTS[-1]:
        return 100
    i: int = bisect.bisect_right(_LIPO_VOLTS, voltage)
    v_lo, p_lo = _LIPO_CURVE[i - 1]
    v_hi, p_hi = _LIPO_CURVE[i]
    return int(round(p_lo + (p_hi - p_lo) * (voltage - v_lo) / (v_hi - v_lo)))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run the Step 4 command. Expected: PASS. Then: `uv run pytest tests/test_metrics.py tests/test_api.py tests/test_state.py tests/test_components.py -q` — Expected: PASS.

- [ ] **Step 7: Regenerate goldens and review**

Run: `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py -q`, then `git status --short tests/golden`.
Expected: only `tests/golden/entity_dashboard_with_battery.png` changes. Confirm with `ImageChops.difference` that the diff bbox is in the top-right battery-text area. If any other golden changes, stop and report.

- [ ] **Step 8: Docs**

`README.md`, the `Battery-Voltage` row of the device-headers table, becomes:

```markdown
| `Battery-Voltage` | Optional battery voltage, rendered on the dashboard image as a percentage along a LiPo discharge curve (3.0V = 0%, 4.2V = 100%) |
```

`CHANGELOG.md`, under `## [Unreleased]`:

```markdown
### Changed
- Battery percentage follows a LiPo discharge curve instead of a straight line from 2.4V to 4.2V, on the dashboard and in `/api/metrics`. 3.0V is now 0%. Previously a nearly empty battery at 3.3V read 50%, so the percentage dropped slowly to about half and then fell quickly, or the device died while still showing a third of its charge.
```

- [ ] **Step 9: Full suite**

Run: `uv run pytest tests/ -q` (about 7 min). Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/trmnl_server/metrics.py tests/test_metrics.py tests/test_components.py tests/test_api.py tests/golden/entity_dashboard_with_battery.png README.md CHANGELOG.md
git commit -m "fix: battery percentage follows a LiPo discharge curve, 3.0V = 0%"
```
(The message ends with the session's Co-Authored-By / Claude-Session trailer lines.)
