"""Server state management for trmnl-server.

This module provides centralized state management for the server,
replacing global variables with a proper class-based approach.
"""

import threading
import time
from collections import deque

from .metrics import ServeEvent, aggregate_metrics


class ServerState:
    """Global server state management."""

    # Retention margin (8 days) so the 7 calendar-day window is always fully
    # covered regardless of time-of-day; hard cap bounds worst-case memory.
    _RETENTION_SECONDS: int = 8 * 86400
    _MAX_EVENTS: int = 100_000

    def __init__(self) -> None:
        """Initialize server state."""
        self._battery_voltages: dict[str, float] = {}
        self._todo_pages: dict[str, int] = {}
        self._lock: threading.Lock = threading.Lock()
        # In-memory serve-event ring buffer for /api/metrics. Events older than
        # the retention margin are pruned on write; maxlen bounds memory.
        self._serve_events: deque[ServeEvent] = deque(maxlen=self._MAX_EVENTS)

    def set_battery_voltage(self, device_id: str, voltage: float) -> None:
        """Set battery voltage for a device if within valid range (2.4V to 4.2V)."""
        if 2.4 <= voltage <= 4.2:
            with self._lock:
                self._battery_voltages[device_id] = voltage

    def consume_battery_voltage(self, device_id: str) -> float | None:
        """Get and clear the battery voltage for a device (use once per render)."""
        with self._lock:
            return self._battery_voltages.pop(device_id, None)

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


# Global state instance
server_state = ServerState()
