# Metrics Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `GET /api/metrics` endpoint reporting dashboards served over the last 7 days (total + by device id) and per-device battery state (latest voltage + percent for each of the last 7 days).

**Architecture:** A single in-memory ring buffer of `ServeEvent`s lives in `ServerState`. Each `/api/display` poll that selects a dashboard records one event `{ts, device_id, dashboard, battery_voltage|None}`. A pure aggregation module (`metrics.py`) turns the event list + a reference `now` into the response JSON. The endpoint serves a snapshot of that aggregation.

**Tech Stack:** Python 3.12 stdlib only (`http.server`, `collections.deque`, `datetime`, `dataclasses`, `threading`, `json`). Tests use `unittest` (run via pytest).

## Global Constraints

- Python 3.12+, **stdlib only** — no new third-party dependencies.
- No persistence layer: history is in-memory and lost on restart (accepted).
- Endpoint is **open, no auth** — consistent with the rest of the server.
- Output is keyed by device `ID`/MAC only — **no device names**.
- Voltage→percent MUST match the existing on-screen formula: linear 2.4–4.2V, clamped 0–100, rounded to int.
- Day buckets and `generated_at` use **server local time** (`datetime.fromtimestamp`).
- All `ServerState` buffer access guarded by the existing `self._lock`.
- Battery for an event MUST come from the request header value parsed in `_handle_api_display`, NOT from `consume_battery_voltage` (which clears the cache).
- Follow existing test style: `unittest.TestCase`, inject `now`/`ts` for determinism.

---

### Task 1: Pure metrics aggregation module

**Files:**
- Create: `src/trmnl_server/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `ServeEvent` — `@dataclass` with fields `ts: float`, `device_id: str`, `dashboard: str`, `battery_voltage: float | None`.
  - `voltage_to_percent(voltage: float) -> int`
  - `aggregate_metrics(events: list[ServeEvent], now: float) -> dict`
  - `WINDOW_DAYS: int = 7`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics.py`:

```python
"""Unit tests for the pure metrics aggregation module."""

import unittest
from datetime import datetime, timedelta

from trmnl_server.metrics import (
    ServeEvent,
    aggregate_metrics,
    voltage_to_percent,
    WINDOW_DAYS,
)


def ts_for(d: datetime) -> float:
    """Local-time epoch for a datetime (matches aggregate's fromtimestamp)."""
    return d.timestamp()


class TestVoltageToPercent(unittest.TestCase):
    def test_minimum_is_zero(self):
        self.assertEqual(voltage_to_percent(2.4), 0)

    def test_maximum_is_hundred(self):
        self.assertEqual(voltage_to_percent(4.2), 100)

    def test_midpoint(self):
        self.assertEqual(voltage_to_percent(3.3), 50)

    def test_clamps_below_range(self):
        self.assertEqual(voltage_to_percent(2.0), 0)

    def test_clamps_above_range(self):
        self.assertEqual(voltage_to_percent(4.5), 100)

    def test_matches_legacy_inline_formula(self):
        # The exact formula previously inlined in components.py:1186.
        for v in (2.4, 2.9, 3.3, 3.7, 3.91, 4.2):
            expected = max(0, min(100, int(round(((v - 2.4) / (4.2 - 2.4)) * 100))))
            self.assertEqual(voltage_to_percent(v), expected)


class TestAggregateMetrics(unittest.TestCase):
    def setUp(self):
        # A fixed, tz-stable "now": noon today.
        self.now_dt = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.now = ts_for(self.now_dt)

    def test_empty_events(self):
        out = aggregate_metrics([], self.now)
        self.assertEqual(out["window_days"], WINDOW_DAYS)
        self.assertEqual(out["dashboards_served"]["total"], 0)
        self.assertEqual(out["dashboards_served"]["by_device"], {})
        self.assertEqual(out["battery"], {})

    def test_counts_total_and_by_device(self):
        events = [
            ServeEvent(self.now, "AA", "morning", 3.9),
            ServeEvent(self.now, "AA", "evening", 3.8),
            ServeEvent(self.now, "BB", "morning", None),
        ]
        out = aggregate_metrics(events, self.now)
        self.assertEqual(out["dashboards_served"]["total"], 3)
        self.assertEqual(out["dashboards_served"]["by_device"]["AA"]["count"], 2)
        self.assertEqual(out["dashboards_served"]["by_device"]["BB"]["count"], 1)

    def test_daily_has_seven_entries_oldest_first(self):
        events = [ServeEvent(self.now, "AA", "morning", 3.9)]
        daily = aggregate_metrics(events, self.now)["battery"]["AA"]["daily"]
        self.assertEqual(len(daily), 7)
        dates = [d["date"] for d in daily]
        self.assertEqual(dates, sorted(dates))  # ascending = oldest first
        self.assertEqual(dates[-1], self.now_dt.date().isoformat())  # today last

    def test_latest_reading_per_day_wins(self):
        early = self.now_dt.replace(hour=8)
        late = self.now_dt.replace(hour=20)
        events = [
            ServeEvent(ts_for(early), "AA", "morning", 4.0),
            ServeEvent(ts_for(late), "AA", "evening", 3.5),
        ]
        today = aggregate_metrics(events, self.now)["battery"]["AA"]["daily"][-1]
        self.assertEqual(today["voltage"], 3.5)  # the later reading
        self.assertEqual(today["percent"], voltage_to_percent(3.5))

    def test_day_with_no_reading_is_null_object(self):
        events = [ServeEvent(self.now, "AA", "morning", 3.9)]
        daily = aggregate_metrics(events, self.now)["battery"]["AA"]["daily"]
        yesterday = daily[-2]
        self.assertEqual(yesterday["voltage"], None)
        self.assertEqual(yesterday["percent"], None)
        self.assertIn("date", yesterday)  # slot is an object, never null itself

    def test_device_with_serves_but_no_battery_appears_with_all_null(self):
        events = [ServeEvent(self.now, "BB", "morning", None)]
        out = aggregate_metrics(events, self.now)
        self.assertIn("BB", out["battery"])
        daily = out["battery"]["BB"]["daily"]
        self.assertEqual(len(daily), 7)
        self.assertTrue(all(d["voltage"] is None for d in daily))
        # Device key sets match between the two sections.
        self.assertEqual(
            set(out["dashboards_served"]["by_device"]),
            set(out["battery"]),
        )

    def test_events_older_than_window_excluded(self):
        old = ts_for(self.now_dt - timedelta(days=8))
        events = [
            ServeEvent(self.now, "AA", "morning", 3.9),
            ServeEvent(old, "AA", "morning", 3.9),
        ]
        out = aggregate_metrics(events, self.now)
        self.assertEqual(out["dashboards_served"]["total"], 1)

    def test_generated_at_has_no_microseconds(self):
        out = aggregate_metrics([], self.now)
        self.assertNotIn(".", out["generated_at"])  # microsecond stripped


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trmnl_server.metrics'`.

- [ ] **Step 3: Write the implementation**

Create `src/trmnl_server/metrics.py`:

```python
"""Pure aggregation for the /api/metrics endpoint.

No HTTP, no shared state, no I/O — every function here is deterministic given
its inputs, so it is unit-testable in isolation. Day buckets and timestamps use
server local time via datetime.fromtimestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW_DAYS: int = 7

# Voltage range for the linear battery percentage. Mirrors the validation
# bounds in ServerState.set_battery_voltage and the on-screen formula.
_V_MIN: float = 2.4
_V_MAX: float = 4.2


@dataclass
class ServeEvent:
    """One dashboard-served event recorded at /api/display poll time."""

    ts: float
    device_id: str
    dashboard: str
    battery_voltage: float | None


def voltage_to_percent(voltage: float) -> int:
    """Map a battery voltage to 0–100%, linear across 2.4–4.2V, clamped.

    Identical to the formula formerly inlined in components.py so the metrics
    percentage and the on-screen percentage can never drift apart.
    """
    pct: int = int(round(((voltage - _V_MIN) / (_V_MAX - _V_MIN)) * 100))
    return max(0, min(100, pct))


def aggregate_metrics(events: list[ServeEvent], now: float) -> dict:
    """Turn a list of ServeEvents into the /api/metrics response dict.

    `now` is an epoch float; the 7-day window is the 7 most recent local
    calendar dates (today inclusive).
    """
    today = datetime.fromtimestamp(now).date()
    # Oldest first: today-6 ... today.
    window_dates = [today - timedelta(days=i) for i in range(WINDOW_DAYS - 1, -1, -1)]
    window_date_set = set(window_dates)

    in_window = [
        e for e in events
        if datetime.fromtimestamp(e.ts).date() in window_date_set
    ]

    # Group surviving events by device.
    devices: dict[str, list[ServeEvent]] = {}
    for e in in_window:
        devices.setdefault(e.device_id, []).append(e)

    by_device: dict[str, dict] = {}
    battery: dict[str, dict] = {}
    for device_id in sorted(devices):
        dev_events = devices[device_id]
        by_device[device_id] = {"count": len(dev_events)}

        daily = []
        for d in window_dates:
            day_readings = [
                e for e in dev_events
                if e.battery_voltage is not None
                and datetime.fromtimestamp(e.ts).date() == d
            ]
            if day_readings:
                latest = max(day_readings, key=lambda e: e.ts)
                v = latest.battery_voltage
                daily.append({
                    "date": d.isoformat(),
                    "voltage": v,
                    "percent": voltage_to_percent(v),
                })
            else:
                daily.append({"date": d.isoformat(), "voltage": None, "percent": None})
        battery[device_id] = {"daily": daily}

    return {
        "window_days": WINDOW_DAYS,
        "generated_at": datetime.fromtimestamp(now).replace(microsecond=0).isoformat(),
        "dashboards_served": {
            "total": len(in_window),
            "by_device": by_device,
        },
        "battery": battery,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/metrics.py tests/test_metrics.py
git commit -m "feat: add pure metrics aggregation module"
```

---

### Task 2: ServerState ring buffer (record + snapshot)

**Files:**
- Modify: `src/trmnl_server/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `ServeEvent`, `aggregate_metrics` from `trmnl_server.metrics` (Task 1).
- Produces:
  - `ServerState.record_serve_event(device_id: str, dashboard: str, battery_voltage: float | None, ts: float | None = None) -> None`
  - `ServerState.metrics_snapshot(now: float | None = None) -> dict`
  - `ServerState.reset_metrics() -> None` (test helper, mirrors `reset_todo_pages`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py` (before the `if __name__` block):

```python
class TestMetricsState(unittest.TestCase):
    """Tests for the in-memory serve-event ring buffer."""

    def test_record_then_snapshot_counts(self):
        s = ServerState()
        s.record_serve_event("AA", "morning", 3.9)
        s.record_serve_event("AA", "evening", 3.8)
        s.record_serve_event("BB", "morning", None)
        out = s.metrics_snapshot()
        self.assertEqual(out["dashboards_served"]["total"], 3)
        self.assertEqual(out["dashboards_served"]["by_device"]["AA"]["count"], 2)

    def test_snapshot_uses_injected_now(self):
        import time
        s = ServerState()
        s.record_serve_event("AA", "morning", 3.9, ts=time.time())
        out = s.metrics_snapshot(now=time.time())
        self.assertEqual(out["dashboards_served"]["total"], 1)

    def test_old_events_pruned_on_record(self):
        import time
        s = ServerState()
        now = time.time()
        # An event 9 days old should be pruned once a fresh event arrives.
        s.record_serve_event("AA", "old", 3.9, ts=now - 9 * 86400)
        s.record_serve_event("AA", "new", 3.9, ts=now)
        # Internal buffer should hold only the fresh event.
        self.assertEqual(len(s._serve_events), 1)

    def test_empty_snapshot(self):
        s = ServerState()
        out = s.metrics_snapshot()
        self.assertEqual(out["dashboards_served"]["total"], 0)
        self.assertEqual(out["battery"], {})

    def test_reset_metrics_clears(self):
        s = ServerState()
        s.record_serve_event("AA", "morning", 3.9)
        s.reset_metrics()
        self.assertEqual(s.metrics_snapshot()["dashboards_served"]["total"], 0)

    def test_concurrent_records_are_safe(self):
        import threading
        s = ServerState()

        def worker():
            for _ in range(100):
                s.record_serve_event("AA", "morning", 3.9)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(s.metrics_snapshot()["dashboards_served"]["total"], 400)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_state.py::TestMetricsState -v`
Expected: FAIL — `AttributeError: 'ServerState' object has no attribute 'record_serve_event'`.

- [ ] **Step 3: Write the implementation**

Edit `src/trmnl_server/state.py`. Replace the import/header section and `__init__`, and add the new methods.

At the top, replace:

```python
import threading
```

with:

```python
import threading
import time
from collections import deque

from .metrics import ServeEvent, aggregate_metrics
```

In `__init__`, after `self._todo_pages` line, add the buffer:

```python
        # In-memory serve-event ring buffer for /api/metrics. Events older than
        # the retention margin are pruned on write; maxlen bounds memory.
        self._serve_events: deque[ServeEvent] = deque(maxlen=self._MAX_EVENTS)
```

Add these class-level constants just below the class docstring (above `__init__`):

```python
    # Retention margin (8 days) so the 7 calendar-day window is always fully
    # covered regardless of time-of-day; hard cap bounds worst-case memory.
    _RETENTION_SECONDS: int = 8 * 86400
    _MAX_EVENTS: int = 100_000
```

Add these methods to the class (e.g. after `consume_battery_voltage`):

```python
    def record_serve_event(
        self,
        device_id: str,
        dashboard: str,
        battery_voltage: float | None,
        ts: float | None = None,
    ) -> None:
        """Record one dashboard-served event and prune stale events."""
        if ts is None:
            ts = time.time()
        event = ServeEvent(
            ts=ts,
            device_id=device_id,
            dashboard=dashboard,
            battery_voltage=battery_voltage,
        )
        cutoff: float = ts - self._RETENTION_SECONDS
        with self._lock:
            self._serve_events.append(event)
            while self._serve_events and self._serve_events[0].ts < cutoff:
                self._serve_events.popleft()

    def metrics_snapshot(self, now: float | None = None) -> dict:
        """Return the aggregated /api/metrics payload for the last 7 days."""
        if now is None:
            now = time.time()
        with self._lock:
            events = list(self._serve_events)
        return aggregate_metrics(events, now)

    def reset_metrics(self) -> None:
        """Clear all recorded serve events (used by tests)."""
        with self._lock:
            self._serve_events.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS (existing battery/todo tests plus new `TestMetricsState`).

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/state.py tests/test_state.py
git commit -m "feat: add serve-event ring buffer to ServerState"
```

---

### Task 3: Route on-screen battery percentage through the shared helper

**Files:**
- Modify: `src/trmnl_server/components.py:1181-1196`
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `voltage_to_percent` from `trmnl_server.metrics` (Task 1).
- Produces: no new public interface; behavior-preserving refactor.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_components.py` a regression test pinning the rendered percentage to the shared helper. Add near the top of the file (after existing imports):

```python
from trmnl_server.metrics import voltage_to_percent


class TestBatteryPercentParity(unittest.TestCase):
    """The shared helper must reproduce the legacy inline battery formula."""

    def test_helper_matches_legacy_formula_across_range(self):
        for v in (2.4, 2.7, 3.0, 3.3, 3.7, 3.91, 4.0, 4.2):
            legacy = max(0, min(100, int(round(((v - 2.4) / (4.2 - 2.4)) * 100))))
            self.assertEqual(voltage_to_percent(v), legacy)
```

> If `tests/test_components.py` does not already `import unittest`, add it at the top.

- [ ] **Step 2: Run test to verify it fails (or errors on import)**

Run: `uv run pytest tests/test_components.py::TestBatteryPercentParity -v`
Expected: FAIL/ERROR until the import resolves and Task 1 is present (Task 1 is a dependency; if run after Task 1 this passes immediately — that is fine, it is a pinning regression test).

- [ ] **Step 3: Refactor the implementation**

In `src/trmnl_server/components.py`, find the block at lines ~1181-1196:

```python
        # Render battery percentage
        battery_voltage: float | None = server_state.consume_battery_voltage(device_id) if device_id else None
        if battery_voltage is not None:
            try:
                # Map 2.4V..4.2V to 0..100%
                pct: int = int(round(((battery_voltage - 2.4) / (4.2 - 2.4)) * 100))
                pct = max(0, min(100, pct))
                battery_text: str = f"{pct}%"
```

Replace the formula lines with a call to the shared helper:

```python
        # Render battery percentage
        battery_voltage: float | None = server_state.consume_battery_voltage(device_id) if device_id else None
        if battery_voltage is not None:
            try:
                from .metrics import voltage_to_percent
                pct: int = voltage_to_percent(battery_voltage)
                battery_text: str = f"{pct}%"
```

(Leave the rest of the block — `textbbox`, `draw.text`, the `except` — unchanged.)

- [ ] **Step 4: Run the component tests to verify they pass**

Run: `uv run pytest tests/test_components.py -v`
Expected: PASS, including the new parity test and any existing golden/render tests.

- [ ] **Step 5: Commit**

```bash
git add src/trmnl_server/components.py tests/test_components.py
git commit -m "refactor: use shared voltage_to_percent for on-screen battery"
```

---

### Task 4: Record events on /api/display and serve /api/metrics

**Files:**
- Modify: `src/trmnl_server/api.py` (`_handle_api_display`, add `_handle_api_metrics`, route in `do_GET`)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `server_state.record_serve_event(...)` and `server_state.metrics_snapshot(now)` (Task 2).
- Produces: `GET /api/metrics` → `200 application/json` with the aggregation payload.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py` (before any `if __name__` block):

```python
class TestAPIMetrics(unittest.TestCase):
    """End-to-end tests for serve-event recording and /api/metrics."""

    def setUp(self):
        from trmnl_server.state import server_state
        api._device_indices.clear()
        server_state.reset_metrics()

    def create_handler(self, path, headers=None):
        mock_logger = mock.Mock()
        handler = APICalls.__new__(APICalls)
        handler.logger = mock_logger
        handler.refresh_rate = 600
        handler.path = path
        handler.headers = headers or {}
        handler.client_address = ('127.0.0.1', 12345)
        handler.wfile = BytesIO()
        handler._response_code = None

        def mock_send_response(code):
            handler._response_code = code
        handler.send_response = mock_send_response
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        return handler

    @mock.patch('trmnl_server.api._aligned_refresh_rate', return_value=288)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_display_poll_records_event_with_battery(self, mock_read_config, _vis, _rate):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'morning'}]}],
            'dashboards': [],
        }
        handler = self.create_handler(
            '/api/display',
            {'ID': 'AA:BB:CC:DD:EE:FF', 'Battery-Voltage': '3.9'},
        )
        handler._handle_api_display()

        metrics_handler = self.create_handler('/api/metrics')
        metrics_handler._handle_api_metrics()
        metrics_handler.wfile.seek(0)
        out = json.loads(metrics_handler.wfile.read().decode())

        self.assertEqual(out['dashboards_served']['total'], 1)
        self.assertEqual(
            out['dashboards_served']['by_device']['AA:BB:CC:DD:EE:FF']['count'], 1)
        today = out['battery']['AA:BB:CC:DD:EE:FF']['daily'][-1]
        self.assertEqual(today['voltage'], 3.9)

    @mock.patch('trmnl_server.api.read_config')
    def test_no_dashboard_selected_records_nothing(self, mock_read_config):
        # Unknown device → no dashboard selected → no serve event.
        mock_read_config.return_value = {'devices': [], 'dashboards': []}
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()

        metrics_handler = self.create_handler('/api/metrics')
        metrics_handler._handle_api_metrics()
        metrics_handler.wfile.seek(0)
        out = json.loads(metrics_handler.wfile.read().decode())
        self.assertEqual(out['dashboards_served']['total'], 0)

    @mock.patch('trmnl_server.api._aligned_refresh_rate', return_value=288)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_invalid_battery_recorded_as_null(self, mock_read_config, _vis, _rate):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'morning'}]}],
            'dashboards': [],
        }
        # 5.0V is out of the 2.4–4.2 range → recorded as null.
        handler = self.create_handler(
            '/api/display',
            {'ID': 'AA:BB:CC:DD:EE:FF', 'Battery-Voltage': '5.0'},
        )
        handler._handle_api_display()

        metrics_handler = self.create_handler('/api/metrics')
        metrics_handler._handle_api_metrics()
        metrics_handler.wfile.seek(0)
        out = json.loads(metrics_handler.wfile.read().decode())
        today = out['battery']['AA:BB:CC:DD:EE:FF']['daily'][-1]
        self.assertIsNone(today['voltage'])

    def test_metrics_route_in_do_get(self):
        from trmnl_server.state import server_state
        server_state.record_serve_event('AA:BB:CC:DD:EE:FF', 'morning', 3.9)
        handler = self.create_handler('/api/metrics')
        handler.do_GET()
        self.assertEqual(handler._response_code, 200)
        handler.wfile.seek(0)
        out = json.loads(handler.wfile.read().decode())
        self.assertEqual(out['dashboards_served']['total'], 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py::TestAPIMetrics -v`
Expected: FAIL — `AttributeError: ... has no attribute '_handle_api_metrics'`.

- [ ] **Step 3a: Capture the parsed battery voltage in `_handle_api_display`**

In `src/trmnl_server/api.py`, replace the battery-capture block (lines ~80-88):

```python
        # Capture battery voltage header
        device_id: str | None = self._get_device_id()
        battery_voltage_header: str | None = self.headers.get('Battery-Voltage')
        if battery_voltage_header is not None and device_id is not None:
            try:
                v: float = float(battery_voltage_header)
                server_state.set_battery_voltage(device_id, v)
            except ValueError:
                self.logger.warning("Invalid Battery-Voltage header: %s", battery_voltage_header)
```

with (introduces `battery_voltage_value`, kept only when in the valid 2.4–4.2 range so it matches `set_battery_voltage` semantics and never clamps misleadingly):

```python
        # Capture battery voltage header
        device_id: str | None = self._get_device_id()
        battery_voltage_value: float | None = None
        battery_voltage_header: str | None = self.headers.get('Battery-Voltage')
        if battery_voltage_header is not None and device_id is not None:
            try:
                v: float = float(battery_voltage_header)
                server_state.set_battery_voltage(device_id, v)
                if 2.4 <= v <= 4.2:
                    battery_voltage_value = v
            except ValueError:
                self.logger.warning("Invalid Battery-Voltage header: %s", battery_voltage_header)
```

- [ ] **Step 3b: Record the serve event after a dashboard is selected**

Still in `_handle_api_display`, find the line that logs the selected dashboard (line ~137):

```python
                    self.logger.info("Device %s → dashboard '%s'", label, dashboard_name)
```

Immediately after it, add:

```python
                    server_state.record_serve_event(device_id, dashboard_name, battery_voltage_value)
```

- [ ] **Step 3c: Add the `_handle_api_metrics` handler**

Add this method to `APICalls` (e.g. just after `_handle_api_display`):

```python
    def _handle_api_metrics(self) -> None:
        """Handle /api/metrics endpoint — serve-event & battery stats (7 days)."""
        snapshot = server_state.metrics_snapshot(time.time())
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(snapshot).encode('utf-8'))
```

- [ ] **Step 3d: Route `/api/metrics` in `do_GET`**

In `do_GET`, after the `/api/display` route block (after line ~313), add:

```python
            if path == '/api/metrics':
                self._handle_api_metrics()
                return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (existing API tests plus `TestAPIMetrics`).

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: PASS — all tests across the project.

- [ ] **Step 6: Commit**

```bash
git add src/trmnl_server/api.py tests/test_api.py
git commit -m "feat: record serve events and add /api/metrics endpoint"
```

---

## Documentation

- [ ] **Update CHANGELOG / README if present.** If `CHANGELOG.md` has an `Unreleased` section (recent commits reference changelog entries), add: `- Added /api/metrics endpoint reporting dashboards served (last 7 days, by device id) and per-device daily battery state.` If a README documents endpoints, add a short `GET /api/metrics` entry with the example response from the spec. Commit separately:

```bash
git add CHANGELOG.md README.md
git commit -m "docs: document /api/metrics endpoint"
```

---

## Self-Review Notes (spec coverage)

- "dashboards served, last 7 days, total" → Task 1 `total`, Task 4 recording. ✅
- "broken down by device id" → Task 1 `by_device`, no names. ✅
- "battery states over that period" → Task 1 per-day `daily`, Task 2 storage, Task 4 capture. ✅
- In-memory ring buffer, prune, lock → Task 2. ✅
- Voltage→% reuse, behavior-preserving → Task 1 + Task 3. ✅
- Open JSON no auth → Task 4 route. ✅
- Null-day object format, device key-set parity, battery-from-header-not-cache → Task 1 tests + Task 4 Step 3a. ✅
- Three test levels: unit (Task 1), integration (Task 2), e2e (Task 4). ✅
