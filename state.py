"""Server state management for trmnl-server.

This module provides centralized state management for the server,
replacing global variables with a proper class-based approach.
"""

import threading


class ServerState:
    """Global server state management."""

    def __init__(self) -> None:
        """Initialize server state."""
        self._battery_voltages: dict[str, float] = {}
        self._lock: threading.Lock = threading.Lock()

    def set_battery_voltage(self, device_id: str, voltage: float) -> None:
        """Set battery voltage for a device if within valid range (2.4V to 4.2V)."""
        if 2.4 <= voltage <= 4.2:
            with self._lock:
                self._battery_voltages[device_id] = voltage

    def consume_battery_voltage(self, device_id: str) -> float | None:
        """Get and clear the battery voltage for a device (use once per render)."""
        with self._lock:
            return self._battery_voltages.pop(device_id, None)


# Global state instance
server_state = ServerState()
