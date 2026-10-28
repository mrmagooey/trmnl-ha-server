# Battery percentage follows a LiPo discharge curve — design

**Request (verbatim):** "I'd like to keep the 3v lower bound as per the table. Deliver via auto-develop"

The table it refers to (researched; points from 3.30V up are Meshtastic's `OCV_ARRAY`, the tail is
stretched to match TRMNL's own 3.0V = 0% in `byos_laravel` and the TRMNL X firmware fallback):

| V | % |
|---|---|
| 4.20 | 100 |
| 4.05 | 90 |
| 3.99 | 80 |
| 3.89 | 70 |
| 3.80 | 60 |
| 3.72 | 50 |
| 3.63 | 40 |
| 3.53 | 30 |
| 3.42 | 20 |
| 3.30 | 10 |
| 3.20 | 5 |
| 3.10 | 2 |
| 3.00 | 0 |

**Symptom being fixed:** the battery slowly drops to ~50% then quickly falls the rest of the way, or
the device dies while still above 0. Cause: `voltage_to_percent` maps 2.4V–4.2V linearly, so 3.3V
(nearly empty for a LiPo) reads 50% and 3.0V reads 33%. TRMNL firmware reads the voltage at idle,
before Wi-Fi and the display turn on, so an open-circuit-voltage curve is the right model.

Designed autonomously (auto-develop); the decision log was approved by an independent coherence
review.

## Behaviour

- `voltage_to_percent(v)` interpolates linearly between the two table points that bracket `v` and
  rounds to an int (`int(round(...))`).
- `v <= 3.00` → 0. `v >= 4.20` → 100.
- It stays the single source of the percentage for both the on-screen text (`components.py`) and
  `/api/metrics` (`metrics.py`), so they cannot drift apart.
- Validation is unchanged: readings outside 2.4–4.2V are still rejected in `state.py` / `api.py`.
  A reading between 2.4V and 3.0V is accepted and shows 0%.

Reference values: 3.7V → 48 (was 72), 3.35V → 14, 3.76V → 55, 3.3V → 10 (was 50), 3.0V → 0 (was 33).

## Decision log

| # | Question | Chosen | Why | Confidence |
|---|---|---|---|---|
| 1 | Mapping | Piecewise-linear interpolation between points, rounded | Matches Meshtastic's use of the same table; no jumps between points | high |
| 2 | Outside the table | Clamp (≤3.0V → 0, ≥4.2V → 100) | User asked for 3.0V as the 0% bound | high |
| 3 | What "keep the 3V lower bound" covers | Only the 0% point; validation stays 2.4–4.2V | Rejecting readings below 3.0V would drop a dying battery's last readings and leave a stale higher %, re-creating the "dies above 0" symptom. Reversing is a one-line bound change | medium |
| 4 | Where the table lives | Module constant `_LIPO_CURVE` (ascending `(volts, percent)` tuples) in `metrics.py` beside `voltage_to_percent` | Single source for screen and metrics; a config option is YAGNI | high |
| 5 | Smoothing, consume-once clearing, logging out-of-range readings, accepting >4.2V | Deferred | Not requested; separate concerns | high |
| 6 | Docs | README `Battery-Voltage` row notes the curve; CHANGELOG `[Unreleased]` "Changed" entry | Users will see their % change | medium |

## Design

- `metrics.py`: remove `_V_MIN` / `_V_MAX`; add `_LIPO_CURVE: tuple[tuple[float, int], ...]` with the
  13 points above in ascending voltage order, and a comment citing the sources and the reason for the
  3.0V floor. `voltage_to_percent` clamps at both ends, finds the bracketing pair with
  `bisect`, interpolates, and rounds. Rewrite its docstring and the comment that claimed the range
  mirrors the validation bounds.
- No change to `api.py`, `state.py` or `components.py` (it already imports `voltage_to_percent`).

## Testing

Test values must avoid exact `.5` ties (e.g. 3.25V), which are fragile under float error and
Python's banker's rounding.

- **Unit (`tests/test_metrics.py`):** every table point returns its exact percent; interpolated values
  3.7→48, 3.35→14, 3.76→55; clamps 3.0→0, 2.9→0, 2.4→0, 4.2→100, 4.3→100; output is non-decreasing
  across 2.40–4.30V in 0.01V steps; `_LIPO_CURVE` voltages are strictly ascending (guards the
  `bisect` assumption). Replace the linear-formula tests.
- **Unit (`tests/test_components.py`):** replace `TestBatteryPercentParity` (it asserts the legacy
  linear formula) with a check that the rendered battery text uses `voltage_to_percent`.
- **Integration:** `/api/metrics` aggregation reports the curve's percent; the existing
  render-with-battery test keeps passing; regenerate the `entity_dashboard_with_battery` golden
  (3.7V: 72% → 48%) and confirm only that golden changes.
- **End-to-end:** a `Battery-Voltage` header sent through `do_GET` on `/api/display`, then
  `/api/metrics` via `do_GET`, reports the curve's percent for that reading.
