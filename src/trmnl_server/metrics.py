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
