"""Simplified tests for api module - removing complex timing tests."""

import unittest
from unittest import mock
from io import BytesIO
import json

from trmnl_server import api
from trmnl_server.api import APICalls


class TestAPISimple(unittest.TestCase):
    """Simple API tests that work reliably."""

    def setUp(self):
        api._device_indices.clear()

    def create_handler(self, path, headers=None):
        """Create a minimal mock handler."""
        mock_logger = mock.Mock()
        handler = APICalls.__new__(APICalls)
        handler.logger = mock_logger
        handler.refresh_rate = 600
        handler.path = path
        handler.headers = headers or {}
        handler.client_address = ('127.0.0.1', 12345)
        handler.wfile = BytesIO()
        handler._response_code = None
        
        def mock_send_response(code):
            handler._response_code = code
        handler.send_response = mock_send_response
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        
        return handler
    
    @mock.patch('secrets.token_urlsafe')
    def test_api_setup(self, mock_token):
        """Test successful setup response."""
        mock_token.return_value = 'test_token_123'
        handler = self.create_handler('/api/setup')
        handler._handle_api_setup()
        
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        
        self.assertEqual(handler._response_code, 200)
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['api_key'], 'test_token_123')
        self.assertIn('filename', response)
        self.assertNotIn('message', response)
    
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_basic(self, mock_read_config):
        """Test basic display endpoint functionality."""
        mock_read_config.return_value = {'dashboards': [], 'devices': []}
        handler = self.create_handler('/api/display')
        handler._handle_api_display()
        
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        
        self.assertEqual(handler._response_code, 200)
        self.assertEqual(response['status'], 0)
        self.assertIn('image_url', response)
        self.assertIsInstance(response['refresh_rate'], str)
        self.assertIn('firmware_url', response)
    
    def test_get_device_id_from_id_header(self):
        """Test getting device ID from ID header (MAC address)."""
        headers = {'ID': 'AA:BB:CC:DD:EE:FF'}
        handler = self.create_handler('/api/display', headers)

        device_id = handler._get_device_id()

        self.assertEqual(device_id, 'AA:BB:CC:DD:EE:FF')

    def test_get_device_id_returns_none_when_no_id_header(self):
        """Test that None is returned when the ID header is absent."""
        handler = self.create_handler('/api/display')

        device_id = handler._get_device_id()

        self.assertIsNone(device_id)
    
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_no_id_header_returns_device_not_found(self, mock_read_config):
        """Test that requests without an ID header get device_not_found image."""
        handler = self.create_handler('/api/display')
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertIn('device_not_found.png', response['image_url'])
        mock_read_config.assert_not_called()

    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_unknown_device_uses_device_id_url(self, mock_read_config):
        """Test that an unknown device gets a personalised /static/device_id/ URL."""
        mock_read_config.return_value = {'devices': [], 'dashboards': []}
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertIn('/static/device_id/AA-BB-CC-DD-EE-FF.png', response['image_url'])

    @mock.patch('trmnl_server.api._aligned_refresh_rate', return_value=288)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_known_device_returns_dashboard_url(self, mock_read_config, _, mock_aligned):
        """A known device with an active entry gets the dashboard URL and a grid-aligned refresh rate."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'morning', 'refresh_rate': 300}]}],
            'dashboards': [],
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()

        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())

        self.assertIn('/static/AA-BB-CC-DD-EE-FF/morning.png', response['image_url'])
        # The response carries the grid-aligned refresh, not the raw interval.
        self.assertEqual(response['refresh_rate'], '288')
        # Alignment is applied using the entry's refresh_rate (300) as the cadence
        # and the entry's start_time (None here) as the grid anchor.
        _now_arg, start_time_arg, effective_rate_arg = mock_aligned.call_args.args
        self.assertIsNone(start_time_arg)
        self.assertEqual(effective_rate_arg, 300)

    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_cycles_through_visible_entries(self, mock_read_config, _):
        """Test that successive calls from the same device rotate through visible dashboards."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [
                {'dashboard': 'first'},
                {'dashboard': 'second'},
            ]}],
            'dashboards': [],
        }
        headers = {'ID': 'AA:BB:CC:DD:EE:FF'}

        handler1 = self.create_handler('/api/display', headers)
        handler1._handle_api_display()
        handler1.wfile.seek(0)
        response1 = json.loads(handler1.wfile.read().decode())

        handler2 = self.create_handler('/api/display', headers)
        handler2._handle_api_display()
        handler2.wfile.seek(0)
        response2 = json.loads(handler2.wfile.read().decode())

        self.assertIn('first.png', response1['image_url'])
        self.assertIn('second.png', response2['image_url'])

    def test_static_device_id_url_restores_colons(self):
        """Test that /static/device_id/ URL decodes hyphens back to colons in the image message."""
        handler = self.create_handler('/static/device_id/AA-BB-CC-DD-EE-FF.png')
        handler._serve_info_image = mock.Mock(return_value=True)

        handler._handle_static_png()

        handler._serve_info_image.assert_called_once_with('Device ID: AA:BB:CC:DD:EE:FF')

    @mock.patch('trmnl_server.api.read_config')
    def test_static_png_device_not_in_schedule_returns_false(self, mock_read_config):
        """Test that a device is denied access to a dashboard not in its schedule."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'other'}]}],
            'dashboards': [],
        }
        handler = self.create_handler('/static/morning.png', {'ID': 'AA:BB:CC:DD:EE:FF'})

        result = handler._handle_static_png()

        self.assertFalse(result)
        handler.logger.warning.assert_called()

    @mock.patch('trmnl_server.api.read_config')
    def test_static_png_unknown_device_returns_false(self, mock_read_config):
        """Test that an unknown device is denied access to any dashboard."""
        mock_read_config.return_value = {'devices': [], 'dashboards': []}
        handler = self.create_handler('/static/morning.png', {'ID': 'AA:BB:CC:DD:EE:FF'})

        result = handler._handle_static_png()

        self.assertFalse(result)
        handler.logger.warning.assert_called()

    @mock.patch.object(APICalls, '_handle_api_setup')
    def test_post_setup(self, mock_handle_setup):
        """Test POST request to /api/setup (TRMNL firmware uses POST)."""
        handler = self.create_handler('/api/setup')
        handler.headers = {'Content-Length': '0'}
        handler.rfile = BytesIO(b'')
        handler.do_POST()
        mock_handle_setup.assert_called_once()

    @mock.patch.object(APICalls, '_handle_api_setup')
    def test_post_setup_with_query_string(self, mock_handle_setup):
        """Test POST to /api/setup with query parameters is routed correctly."""
        handler = self.create_handler('/api/setup?token=abc&mac=AA:BB')
        handler.headers = {'Content-Length': '0'}
        handler.rfile = BytesIO(b'')
        handler.do_POST()
        mock_handle_setup.assert_called_once()
    
    def test_get_not_found(self):
        """Test GET request to unknown endpoint."""
        handler = self.create_handler('/unknown')
        handler.do_GET()
        self.assertEqual(handler._response_code, 404)
    
    def test_post_log(self):
        """Test POST request to /api/log logs at INFO regardless of debug level."""
        handler = self.create_handler('/api/log')
        handler.headers = {'Content-Length': '13', 'Content-Type': 'text/plain'}
        handler.rfile = BytesIO(b'test log body')
        handler.do_POST()
        self.assertEqual(handler._response_code, 200)
        handler.logger.info.assert_called_once()
        log_call_args = handler.logger.info.call_args[0]
        self.assertIn('test log body', log_call_args)
    
    def test_post_not_found(self):
        """Test POST request to unknown endpoint."""
        handler = self.create_handler('/unknown')
        handler.headers = {'Content-Length': '0'}
        handler.rfile = BytesIO(b'')
        handler.do_POST()
        self.assertEqual(handler._response_code, 404)

    def test_get_returns_500_on_unhandled_exception(self):
        """Test that unhandled exceptions in do_GET return 500."""
        handler = self.create_handler('/api/setup')
        handler._handle_api_setup = mock.Mock(side_effect=RuntimeError("boom"))
        handler.do_GET()
        self.assertEqual(handler._response_code, 500)
        handler.logger.exception.assert_called_once()

    def test_post_returns_500_on_unhandled_exception(self):
        """Test that unhandled exceptions in do_POST return 500."""
        handler = self.create_handler('/api/log')
        handler.headers = {'Content-Length': 'not-a-number'}
        handler.rfile = BytesIO(b'')
        handler.do_POST()
        self.assertEqual(handler._response_code, 500)
        handler.logger.exception.assert_called_once()

    @mock.patch('trmnl_server.api._seconds_until_next_visible', return_value=4242)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=False)
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_no_visible_sleeps_until_next(self, mock_read_config, _vis, mock_next):
        """When nothing is scheduled for now, refresh_rate is the time until the next entry."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [
                {'dashboard': 'morning', 'start_time': '07:00', 'end_time': '08:00'},
            ]}],
            'dashboards': [],
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        self.assertIn('no_dashboard_visible.png', response['image_url'])
        self.assertEqual(response['refresh_rate'], '4242')
        mock_next.assert_called_once()
        # The helper must receive the device's own schedule (first positional arg).
        called_schedule = mock_next.call_args.args[0]
        self.assertEqual(called_schedule, [
            {'dashboard': 'morning', 'start_time': '07:00', 'end_time': '08:00'},
        ])

    @mock.patch('trmnl_server.api._seconds_until_next_visible', return_value=None)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=False)
    @mock.patch('trmnl_server.api.read_config')
    def test_api_display_no_visible_none_falls_back_to_default(self, mock_read_config, _vis, mock_next):
        """When nothing becomes visible within the horizon, fall back to the 600s default."""
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [
                {'dashboard': 'morning', 'start_time': '07:00', 'end_time': '08:00'},
            ]}],
            'dashboards': [],
        }
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        self.assertIn('no_dashboard_visible.png', response['image_url'])
        self.assertEqual(response['refresh_rate'], '600')
        mock_next.assert_called_once()


class TestAPIMetrics(unittest.TestCase):
    """End-to-end tests for serve-event recording and /api/metrics."""

    def setUp(self):
        from trmnl_server.state import server_state
        api._device_indices.clear()
        server_state.reset_metrics()

    def create_handler(self, path, headers=None):
        mock_logger = mock.Mock()
        handler = APICalls.__new__(APICalls)
        handler.logger = mock_logger
        handler.refresh_rate = 600
        handler.path = path
        handler.headers = headers or {}
        handler.client_address = ('127.0.0.1', 12345)
        handler.wfile = BytesIO()
        handler._response_code = None

        def mock_send_response(code):
            handler._response_code = code
        handler.send_response = mock_send_response
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        return handler

    @mock.patch('trmnl_server.api._aligned_refresh_rate', return_value=288)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_display_poll_records_event_with_battery(self, mock_read_config, _vis, _rate):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'morning'}]}],
            'dashboards': [],
        }
        handler = self.create_handler(
            '/api/display',
            {'ID': 'AA:BB:CC:DD:EE:FF', 'Battery-Voltage': '3.9'},
        )
        handler._handle_api_display()

        metrics_handler = self.create_handler('/api/metrics')
        metrics_handler._handle_api_metrics()
        metrics_handler.wfile.seek(0)
        out = json.loads(metrics_handler.wfile.read().decode())

        self.assertEqual(out['dashboards_served']['total'], 1)
        self.assertEqual(
            out['dashboards_served']['by_device']['AA:BB:CC:DD:EE:FF']['count'], 1)
        today = out['battery']['AA:BB:CC:DD:EE:FF']['daily'][-1]
        self.assertEqual(today['voltage'], 3.9)

    @mock.patch('trmnl_server.api.read_config')
    def test_no_dashboard_selected_records_nothing(self, mock_read_config):
        # Unknown device → no dashboard selected → no serve event.
        mock_read_config.return_value = {'devices': [], 'dashboards': []}
        handler = self.create_handler('/api/display', {'ID': 'AA:BB:CC:DD:EE:FF'})
        handler._handle_api_display()

        metrics_handler = self.create_handler('/api/metrics')
        metrics_handler._handle_api_metrics()
        metrics_handler.wfile.seek(0)
        out = json.loads(metrics_handler.wfile.read().decode())
        self.assertEqual(out['dashboards_served']['total'], 0)

    @mock.patch('trmnl_server.api._aligned_refresh_rate', return_value=288)
    @mock.patch('trmnl_server.api.is_schedule_entry_visible', return_value=True)
    @mock.patch('trmnl_server.api.read_config')
    def test_invalid_battery_recorded_as_null(self, mock_read_config, _vis, _rate):
        mock_read_config.return_value = {
            'devices': [{'id': 'AA:BB:CC:DD:EE:FF', 'schedule': [{'dashboard': 'morning'}]}],
            'dashboards': [],
        }
        # 5.0V is out of the 2.4–4.2 range → recorded as null.
        handler = self.create_handler(
            '/api/display',
            {'ID': 'AA:BB:CC:DD:EE:FF', 'Battery-Voltage': '5.0'},
        )
        handler._handle_api_display()

        metrics_handler = self.create_handler('/api/metrics')
        metrics_handler._handle_api_metrics()
        metrics_handler.wfile.seek(0)
        out = json.loads(metrics_handler.wfile.read().decode())
        today = out['battery']['AA:BB:CC:DD:EE:FF']['daily'][-1]
        self.assertIsNone(today['voltage'])

    def test_metrics_route_in_do_get(self):
        from trmnl_server.state import server_state
        server_state.record_serve_event('AA:BB:CC:DD:EE:FF', 'morning', 3.9)
        handler = self.create_handler('/api/metrics')
        handler.do_GET()
        self.assertEqual(handler._response_code, 200)
        handler.wfile.seek(0)
        out = json.loads(handler.wfile.read().decode())
        self.assertEqual(out['dashboards_served']['total'], 1)


if __name__ == '__main__':
    unittest.main()
