"""Tests for config module."""

import unittest
from unittest import mock
from datetime import datetime, timedelta
from io import StringIO

from trmnl_server.config import (
    read_config,
    is_schedule_entry_visible,
    _coerce_time,
    find_device,
    _aligned_refresh_rate,
)


class TestReadConfig(unittest.TestCase):
    """Tests for read_config function."""

    def setUp(self):
        self.mock_logger = mock.Mock()

    @mock.patch('trmnl_server.config.open')
    @mock.patch('trmnl_server.config.yaml.safe_load')
    @mock.patch.dict('os.environ', {}, clear=True)
    def test_read_config_success(self, mock_yaml_load, mock_open):
        """Test successful config reading."""
        mock_yaml_load.return_value = {'dashboards': []}

        result = read_config(self.mock_logger)

        self.assertEqual(result, {'dashboards': []})
        mock_open.assert_called_once_with('config.yaml', 'r')

    @mock.patch('trmnl_server.config.open')
    @mock.patch.dict('os.environ', {'CONFIG_PATH': '/custom/config.yaml'}, clear=True)
    def test_read_config_custom_path(self, mock_open):
        """Test reading config from custom path."""
        mock_open.return_value.__enter__.return_value = StringIO('dashboards: []')

        read_config(self.mock_logger)

        mock_open.assert_called_once_with('/custom/config.yaml', 'r')

    @mock.patch('trmnl_server.config.open')
    def test_read_config_file_not_found(self, mock_open):
        """Test handling of missing config file."""
        mock_open.side_effect = FileNotFoundError()

        result = read_config(self.mock_logger)

        self.assertEqual(result, {})
        self.mock_logger.error.assert_called_once()

    @mock.patch('trmnl_server.config.open')
    @mock.patch('trmnl_server.config.yaml.safe_load')
    def test_read_config_yaml_error(self, mock_yaml_load, mock_open):
        """Test handling of YAML parsing error."""
        import yaml
        mock_yaml_load.side_effect = yaml.YAMLError("Invalid YAML")

        result = read_config(self.mock_logger)

        self.assertEqual(result, {})
        self.mock_logger.error.assert_called_once()

    @mock.patch('trmnl_server.config.open')
    @mock.patch('trmnl_server.config.yaml.safe_load')
    def test_read_config_empty_file(self, mock_yaml_load, mock_open):
        """Test handling of empty config file."""
        mock_yaml_load.return_value = None

        result = read_config(self.mock_logger)

        self.assertEqual(result, {})


class TestIsScheduleEntryVisible(unittest.TestCase):
    """Tests for is_schedule_entry_visible function."""

    def setUp(self):
        self.mock_logger = mock.Mock()

    def test_no_visibility_rules(self):
        """Test entry with no time/day rules is always visible."""
        entry = {'dashboard': 'test'}
        now = datetime(2025, 1, 15, 12, 0)  # Wednesday

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_single_day_match(self):
        """Test visibility on matching single day."""
        entry = {'dashboard': 'test', 'days_of_the_week': 'Wednesday'}
        now = datetime(2025, 1, 15, 12, 0)  # Wednesday

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_single_day_no_match(self):
        """Test visibility on non-matching single day."""
        entry = {'dashboard': 'test', 'days_of_the_week': 'Monday'}
        now = datetime(2025, 1, 15, 12, 0)  # Wednesday

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)

    def test_day_range_match(self):
        """Test visibility within day range."""
        entry = {'dashboard': 'test', 'days_of_the_week': 'Monday-Friday'}
        now = datetime(2025, 1, 15, 12, 0)  # Wednesday

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_day_range_no_match(self):
        """Test visibility outside day range."""
        entry = {'dashboard': 'test', 'days_of_the_week': 'Monday-Friday'}
        now = datetime(2025, 1, 12, 12, 0)  # Sunday

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)

    def test_time_same_day_visible(self):
        """Test visibility within same-day time range."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': '09:00',
            'end_time': '17:00',
        }
        now = datetime(2025, 1, 15, 12, 0)  # 12:00

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_time_same_day_not_visible_before(self):
        """Test visibility before same-day time range."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': '09:00',
            'end_time': '17:00',
        }
        now = datetime(2025, 1, 15, 8, 0)  # 08:00

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)

    def test_time_same_day_not_visible_after(self):
        """Test visibility after same-day time range."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': '09:00',
            'end_time': '17:00',
        }
        now = datetime(2025, 1, 15, 18, 0)  # 18:00

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)

    def test_time_overnight_visible(self):
        """Test visibility within overnight time range."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': '22:00',
            'end_time': '06:00',
        }
        now = datetime(2025, 1, 15, 23, 0)  # 23:00

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_time_overnight_visible_early(self):
        """Test visibility within overnight time range (early morning)."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': '22:00',
            'end_time': '06:00',
        }
        now = datetime(2025, 1, 15, 5, 0)  # 05:00

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_time_overnight_not_visible(self):
        """Test visibility outside overnight time range."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': '22:00',
            'end_time': '06:00',
        }
        now = datetime(2025, 1, 15, 12, 0)  # 12:00

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)

    def test_invalid_time_format(self):
        """Test handling of invalid time format."""
        entry = {
            'dashboard': 'test',
            'days_of_the_week': 'Monday-Sunday',
            'start_time': 'invalid',
            'end_time': '17:00',
        }
        now = datetime(2025, 1, 15, 12, 0)

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)
        self.mock_logger.error.assert_called_once()

    def test_invalid_day_name(self):
        """Test handling of invalid day name."""
        entry = {'dashboard': 'test', 'days_of_the_week': 'InvalidDay'}
        now = datetime(2025, 1, 15, 12, 0)  # Wednesday

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)

    def test_integer_time_values(self):
        """Test that YAML-parsed sexagesimal integers are handled correctly."""
        entry = {
            'dashboard': 'test',
            'start_time': 540,   # 9*60 = 09:00
            'end_time': 1020,    # 17*60 = 17:00
        }
        now = datetime(2025, 1, 15, 12, 0)

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertTrue(result)

    def test_integer_time_values_outside_range(self):
        """Test that integer times correctly exclude out-of-range times."""
        entry = {
            'dashboard': 'test',
            'start_time': 540,   # 09:00
            'end_time': 1020,    # 17:00
        }
        now = datetime(2025, 1, 15, 8, 0)

        result = is_schedule_entry_visible(entry, now, self.mock_logger)

        self.assertFalse(result)


class TestCoerceTime(unittest.TestCase):
    """Tests for _coerce_time helper."""

    def test_integer_converts_to_hhmm(self):
        self.assertEqual(_coerce_time(360), "06:00")   # 6*60

    def test_integer_with_minutes(self):
        self.assertEqual(_coerce_time(570), "09:30")   # 9*60+30

    def test_midnight(self):
        self.assertEqual(_coerce_time(0), "00:00")

    def test_string_passthrough(self):
        self.assertEqual(_coerce_time("09:00"), "09:00")

    def test_string_with_leading_zero(self):
        self.assertEqual(_coerce_time("06:00"), "06:00")


class TestFindDevice(unittest.TestCase):
    """Tests for find_device helper."""

    def test_finds_matching_device(self):
        devices = [{'id': 'AA:BB'}, {'id': 'CC:DD'}]
        result = find_device(devices, 'CC:DD')
        self.assertEqual(result, {'id': 'CC:DD'})

    def test_returns_none_when_not_found(self):
        devices = [{'id': 'AA:BB'}]
        result = find_device(devices, 'ZZ:ZZ')
        self.assertIsNone(result)

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(find_device([], 'AA:BB'))


class TestAlignedRefreshRate(unittest.TestCase):
    """Tests for _aligned_refresh_rate (drift-free schedule alignment)."""

    def test_on_grid_returns_full_interval(self):
        # 07:05:00 is exactly on the 07:00 + k*60 grid -> next point is a full R away.
        now = datetime(2025, 1, 1, 7, 5, 0)
        self.assertEqual(_aligned_refresh_rate(now, "07:00", 60), 60)

    def test_just_past_grid_returns_remaining(self):
        # 3s past a grid point -> 57s until the next one.
        now = datetime(2025, 1, 1, 7, 5, 3)
        self.assertEqual(_aligned_refresh_rate(now, "07:00", 60), 57)

    def test_imminent_grid_is_floored_by_one_interval(self):
        # 1s before the next grid point is below MIN -> skip to the following one.
        now = datetime(2025, 1, 1, 7, 5, 59)
        self.assertEqual(_aligned_refresh_rate(now, "07:00", 60), 61)

    def test_no_start_time_anchors_to_midnight(self):
        # 250s after midnight, R=300 -> 50s until the next 300s grid point.
        now = datetime(2025, 1, 1, 0, 4, 10)
        self.assertEqual(_aligned_refresh_rate(now, None, 300), 50)

    def test_invalid_start_time_falls_back_to_midnight(self):
        now = datetime(2025, 1, 1, 0, 4, 10)
        self.assertEqual(_aligned_refresh_rate(now, "not-a-time", 300), 50)

    def test_overnight_window_anchors_to_window_start(self):
        # start 23:00, now 00:32 next day, R=210 (does not divide a day): the grid
        # is anchored to the window start (yesterday 23:00), giving 150s remaining.
        now = datetime(2025, 1, 2, 0, 32, 0)
        self.assertEqual(_aligned_refresh_rate(now, "23:00", 210), 150)

    def test_non_positive_rate_returns_unchanged(self):
        now = datetime(2025, 1, 1, 7, 0, 0)
        self.assertEqual(_aligned_refresh_rate(now, None, 0), 0)

    def test_tiny_rate_loops_up_to_floor(self):
        # R=1, 0.5s past midnight -> remaining 0.5 -> loops to >= MIN_REFRESH_SECONDS.
        now = datetime(2025, 1, 1, 0, 0, 0, 500000)
        self.assertEqual(_aligned_refresh_rate(now, None, 1), 5)

    def test_alignment_is_drift_free_across_cycles(self):
        # Device wakes `delay` seconds late each cycle (render + e-ink + network).
        # Aligned sleeps keep wake times pinned to the grid: the offset stays at
        # `delay` instead of growing every refresh.
        R = 60
        delay = 3
        anchor = datetime(2025, 1, 1, 7, 0, 0)
        now = anchor
        for _ in range(10):
            sleep = _aligned_refresh_rate(now, "07:00", R)
            now = now + timedelta(seconds=sleep + delay)
            offset = (now - anchor).total_seconds() % R
            self.assertLessEqual(
                offset, delay,
                f"wake drifted to offset {offset}s (should stay <= {delay}s)",
            )


if __name__ == '__main__':
    unittest.main()
