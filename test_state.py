"""Tests for state module."""

import unittest

from state import ServerState, server_state


class TestServerState(unittest.TestCase):
    """Tests for ServerState class."""

    def test_set_battery_voltage_valid(self):
        state = ServerState()
        state.set_battery_voltage('1.2.3.4', 3.7)
        self.assertEqual(state.consume_battery_voltage('1.2.3.4'), 3.7)

    def test_set_battery_voltage_minimum(self):
        state = ServerState()
        state.set_battery_voltage('1.2.3.4', 2.4)
        self.assertEqual(state.consume_battery_voltage('1.2.3.4'), 2.4)

    def test_set_battery_voltage_maximum(self):
        state = ServerState()
        state.set_battery_voltage('1.2.3.4', 4.2)
        self.assertEqual(state.consume_battery_voltage('1.2.3.4'), 4.2)

    def test_set_battery_voltage_too_low(self):
        state = ServerState()
        state.set_battery_voltage('1.2.3.4', 2.3)
        self.assertIsNone(state.consume_battery_voltage('1.2.3.4'))

    def test_set_battery_voltage_too_high(self):
        state = ServerState()
        state.set_battery_voltage('1.2.3.4', 4.3)
        self.assertIsNone(state.consume_battery_voltage('1.2.3.4'))

    def test_consume_clears_voltage(self):
        state = ServerState()
        state.set_battery_voltage('1.2.3.4', 3.7)
        state.consume_battery_voltage('1.2.3.4')
        self.assertIsNone(state.consume_battery_voltage('1.2.3.4'))

    def test_consume_unknown_ip(self):
        state = ServerState()
        self.assertIsNone(state.consume_battery_voltage('9.9.9.9'))

    def test_voltages_are_per_device(self):
        state = ServerState()
        state.set_battery_voltage('AA:BB:CC:DD:EE:01', 3.5)
        state.set_battery_voltage('AA:BB:CC:DD:EE:02', 4.0)
        self.assertEqual(state.consume_battery_voltage('AA:BB:CC:DD:EE:01'), 3.5)
        self.assertEqual(state.consume_battery_voltage('AA:BB:CC:DD:EE:02'), 4.0)


class TestGlobalServerState(unittest.TestCase):
    """Tests for the global server_state instance."""

    def test_global_instance(self):
        self.assertIsInstance(server_state, ServerState)


if __name__ == '__main__':
    unittest.main()
