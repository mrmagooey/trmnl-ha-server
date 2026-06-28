# Metrics Endpoint Design

**Date:** 2026-06-28
**Status:** Approved (pending spec review)

## Goal

Add a simple, read-only metrics endpoint that reports, over the **last 7 days**:

1. How many dashboards have been served, in total.
2. That total broken down by device id.
3. Per-device battery state, as the latest voltage and resulting percentage for
   each of the last 7 days.

## Constraints & Context

- The server is a pure stdlib `http.server` application (`src/trmnl_server/`)
  with **no web framework and no database**. It is deliberately stateless.
- Dashboard serves are currently only logged to a rotating log file, never
  recorded structurally.
- Battery voltage is captured per device from the `Battery-Voltage` header on
  `/api/display` into in-memory `ServerState`, and is consumed (cleared) on each
  render. Valid range: 2.4V–4.2V.
- Device identity is the `ID` (MAC) header sent on `/api/display`.
- The device screen already renders a battery percentage in
  `components.py:1186` using a **linear 2.4V–4.2V → 0–100%** mapping, clamped to
  0–100 and rounded to an integer.

## Design Decisions (resolved during brainstorming)

| Decision | Choice |
|---|---|
| History storage | **In-memory ring buffer** in `ServerState`. Lost on restart (accepted). |
| What counts as a "served" event | One successful **`/api/display` poll** (a dashboard was selected). |
| Battery report shape | Per device, **per day** (last 7 days): latest voltage that day + derived percent. |
| Voltage → percent | Reuse the **existing linear 2.4–4.2V** formula, extracted into a shared helper so metrics and the on-screen value never disagree. |
| Endpoint access | **Open JSON, no auth** — consistent with the rest of the server. |
| Output naming | Keyed by device `ID`/MAC only. **No device names** in the output. |
| Empty battery days | Included as `null` (voltage and percent both `null`). |
| Per-device dashboard detail | Just a `count` — no per-dashboard sub-breakdown. |

## Architecture & Data Flow

A single in-memory **event ring buffer** lives in `ServerState`. On every
`/api/display` poll, once a dashboard has been selected, one event is recorded:

```
ServeEvent = { ts: float, device_id: str, dashboard: str, battery_voltage: float | None }
```

This single event stream feeds **both** outputs (dashboard counts and
battery-per-day), giving one source of truth and one capture point. The
`battery_voltage` is taken from the same request that already parses the
`Battery-Voltage` header; the existing consume-on-render path in
`components.py` is left untouched.

**Retention / pruning:**

- Events older than 7 days are pruned on write and on read (time-based, using
  server local time / `time.time()`).
- A generous hard cap (`maxlen`, e.g. 100_000 events) bounds memory as a safety
  net regardless of traffic.

**Concurrency:** all buffer mutations and snapshot reads are guarded by the
existing `ServerState` lock.

**Day bucketing:** uses **server local time**, consistent with how schedules
interpret times. Each day's battery value is the **latest reading in that day**.

## Response Shape

`GET /api/metrics` → `200`, `application/json`:

```jsonc
{
  "window_days": 7,
  "generated_at": "2026-06-28T10:00:00",   // server-local ISO timestamp
  "dashboards_served": {
    "total": 1422,
    "by_device": {
      "AA:BB:CC:DD:EE:FF": { "count": 712 },
      "11:22:33:44:55:66": { "count": 710 }
    }
  },
  "battery": {
    "AA:BB:CC:DD:EE:FF": {
      "daily": [
        { "date": "2026-06-22", "voltage": 4.01, "percent": 89 },
        { "date": "2026-06-23", "voltage": 3.98, "percent": 87 },
        { "date": "2026-06-24", "voltage": null, "percent": null },
        { "date": "2026-06-25", "voltage": 3.95, "percent": 86 },
        { "date": "2026-06-26", "voltage": 3.93, "percent": 85 },
        { "date": "2026-06-27", "voltage": 3.92, "percent": 84 },
        { "date": "2026-06-28", "voltage": 3.91, "percent": 83 }
      ]
    }
  }
}
```

Details:

- `daily` always contains exactly 7 entries, oldest first, one per calendar day
  in the window (today inclusive). Days with no reading have `voltage: null`
  and `percent: null`.
- `percent` is computed by the shared `voltage_to_percent()` helper (linear
  2.4–4.2V, clamped 0–100, rounded to int) — identical to the device screen.
- A device that has produced any event in the window appears in `by_device`
  and/or `battery`. A device with serves but no valid battery readings still
  gets a `daily` array of 7 all-`null` entries.

## Code Surface (small, isolated)

- **`metrics.py` (new)** — pure aggregation: `voltage_to_percent(voltage)` and a
  function that turns a list of `ServeEvent`s + a reference `now` into the JSON
  structure above. No HTTP, no state, no I/O — fully unit-testable.
- **`state.py`** — add the ring buffer plus:
  - `record_serve_event(device_id, dashboard, battery_voltage)`
  - `metrics_snapshot(now)` returning the aggregated dict (delegates to
    `metrics.py`), pruning as it goes. All under the existing lock.
- **`components.py`** — replace the inline formula at line 1186 with a call to
  the shared `voltage_to_percent()`.
- **`api.py`** —
  - In `_handle_api_display()`, after a dashboard is selected, call
    `server_state.record_serve_event(...)`.
  - Add a `/api/metrics` route in `do_GET()` that writes
    `server_state.metrics_snapshot(time.time())` as JSON.

## Error Handling

- Missing/invalid `Battery-Voltage` is already handled upstream; the event is
  still recorded with `battery_voltage = null`.
- A poll with no resolvable device id is not recorded (no key to attribute it
  to).
- `/api/metrics` never fails on empty history — it returns zeroed/empty
  structures (`total: 0`, empty `by_device`, empty `battery`).

## Testing (all three levels)

- **Unit** (`tests/test_metrics.py`) — pure aggregation in `metrics.py`:
  - total count and per-device split,
  - per-day "latest reading wins",
  - 7-day pruning boundary (event exactly at the edge),
  - `voltage_to_percent` including clamping at both ends and rounding,
  - days with no reading rendered as `null`,
  - empty input → zeroed output.
- **Integration** (`tests/test_state.py`) — `ServerState`:
  - record events and assert `metrics_snapshot` output with a controllable
    `now`,
  - pruning of old events,
  - basic thread-safety (concurrent records).
- **E2E** (`tests/test_api.py`) — drive `APICalls` as existing tests do:
  - simulate several `/api/display` polls with `ID` and `Battery-Voltage`
    headers,
  - `GET /api/metrics` and assert the resulting JSON (counts + battery days).

## Out of Scope (YAGNI)

- Persistence across restarts (SQLite / file log).
- Authentication on the endpoint.
- Per-dashboard breakdown, device names, configurable window length.
- Historical battery time-series beyond one latest-per-day reading.
