"""Tests for hass_client module."""

import unittest
from datetime import datetime

from hass_client import (
    _cast_to_numbers,
    _process_history_to_points,
)


class TestCastToNumbers(unittest.TestCase):
    """Tests for _cast_to_numbers function."""
    
    def test_cast_integer(self):
        """Test casting integer string."""
        result = _cast_to_numbers("42")
        self.assertEqual(result, 42)
        self.assertIsInstance(result, int)
    
    def test_cast_float(self):
        """Test casting float string."""
        result = _cast_to_numbers("3.14")
        self.assertEqual(result, 3.14)
        self.assertIsInstance(result, float)
    
    def test_cast_string(self):
        """Test casting non-numeric string."""
        result = _cast_to_numbers("hello")
        self.assertEqual(result, "hello")
        self.assertIsInstance(result, str)
    
    def test_cast_mixed_string(self):
        """Test casting mixed alphanumeric string."""
        result = _cast_to_numbers("12abc")
        self.assertEqual(result, "12abc")


class TestProcessHistoryToPoints(unittest.TestCase):
    """Tests for _process_history_to_points function."""
    
    def test_empty_history(self):
        """Test processing empty history."""
        result = _process_history_to_points(None)
        self.assertEqual(result, [])
    
    def test_empty_inner_list(self):
        """Test processing history with empty inner list."""
        result = _process_history_to_points([[]])
        self.assertEqual(result, [])
    
    def test_valid_data(self):
        """Test processing valid history data."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-01-15T11:00:00+00:00'},
        ]]
        
        result = _process_history_to_points(history)
        
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0][0], datetime)
        self.assertEqual(result[0][1], 21.5)
    
    def test_invalid_state_value(self):
        """Test skipping invalid state values."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'invalid', 'last_changed': '2025-01-15T11:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-01-15T12:00:00+00:00'},
        ]]
        
        result = _process_history_to_points(history)
        
        self.assertEqual(len(result), 2)
    
    def test_sorts_by_timestamp(self):
        """Test that results are sorted by timestamp."""
        history = [[
            {'state': '22.0', 'last_changed': '2025-01-15T12:00:00+00:00'},
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
        ]]
        
        result = _process_history_to_points(history)
        
        self.assertEqual(result[0][1], 21.5)  # Earlier value first
        self.assertEqual(result[1][1], 22.0)


if __name__ == '__main__':
    unittest.main()
