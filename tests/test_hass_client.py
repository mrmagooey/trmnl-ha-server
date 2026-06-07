"""Tests for hass_client module."""

import logging
import unittest
from datetime import datetime, timezone
from unittest import mock

from trmnl_server.hass_client import (
    _cast_to_numbers,
    _fetch_history,
    _process_history_to_points,
)

mock_logger = mock.Mock(spec=logging.Logger)


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


class TestFetchHistoryWindow(unittest.TestCase):
    """Tests that _fetch_history requests the exact time window."""

    @mock.patch('trmnl_server.hass_client.urlopen')
    def test_builds_windowed_url(self, mock_urlopen):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = b'[[]]'
        mock_urlopen.return_value = cm
        start = datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc)
        with mock.patch('trmnl_server.hass_client.HASS_URL', 'http://hass'), \
             mock.patch('trmnl_server.hass_client.HASS_TOKEN', 'token'):
            _fetch_history('sensor.x', mock_logger, start=start, end=end)
        url = mock_urlopen.call_args[0][0].full_url
        self.assertIn('/api/history/period/2024-01-15T08:00:00Z', url)
        self.assertIn('filter_entity_id=sensor.x', url)
        self.assertIn('end_time=2024-01-15T16:00:00Z', url)


if __name__ == '__main__':
    unittest.main()
