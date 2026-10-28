"""Pure aggregation for the /api/metrics endpoint.

No HTTP, no shared state, no I/O — every function here is deterministic given
its inputs, so it is unit-testable in isolation. Day buckets and timestamps use
server local time via datetime.fromtimestamp.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW_DAYS: int = 7

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


@dataclass
class ServeEvent:
    """One dashboard-served event recorded at /api/display poll time."""

    ts: float
    device_id: str
    dashboard: str
    battery_voltage: float | None


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
