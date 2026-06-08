"""Tests for state module."""

import unittest

from trmnl_server.state import ServerState, server_state


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


class TestTodoPagination(unittest.TestCase):
    """Tests for todo-list page rotation state."""

    def test_first_call_returns_zero(self):
        s = ServerState()
        self.assertEqual(s.next_todo_page("k", 3), 0)

    def test_advances_and_wraps(self):
        s = ServerState()
        seen = [s.next_todo_page("k", 3) for _ in range(4)]
        self.assertEqual(seen, [0, 1, 2, 0])

    def test_isolated_by_key(self):
        s = ServerState()
        self.assertEqual(s.next_todo_page("a", 2), 0)
        self.assertEqual(s.next_todo_page("a", 2), 1)
        # Different key has its own counter.
        self.assertEqual(s.next_todo_page("b", 2), 0)

    def test_single_page_never_rotates(self):
        s = ServerState()
        self.assertEqual(s.next_todo_page("k", 1), 0)
        self.assertEqual(s.next_todo_page("k", 1), 0)

    def test_reset_clears(self):
        s = ServerState()
        s.next_todo_page("k", 3)
        s.reset_todo_pages()
        self.assertEqual(s.next_todo_page("k", 3), 0)


if __name__ == '__main__':
    unittest.main()
