"""Simplified tests for api module - removing complex timing tests."""

import unittest
from unittest import mock
from io import BytesIO
import json

import api
from api import APICalls


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
        self.assertEqual(response['api_key'], 'test_token_123')
    
    @mock.patch('config.read_config')
    def test_api_display_basic(self, mock_read_config):
        """Test basic display endpoint functionality."""
        mock_read_config.return_value = {'dashboards': [], 'devices': []}
        handler = self.create_handler('/api/display')
        handler._handle_api_display()
        
        handler.wfile.seek(0)
        response = json.loads(handler.wfile.read().decode())
        
        self.assertEqual(handler._response_code, 200)
        self.assertIn('image_url', response)
        self.assertIn('refresh_rate', response)
    
    def test_get_device_id_from_id_header(self):
        """Test getting device ID from ID header (MAC address)."""
        headers = {'ID': 'AA:BB:CC:DD:EE:FF'}
        handler = self.create_handler('/api/display', headers)

        device_id = handler._get_device_id()

        self.assertEqual(device_id, 'AA:BB:CC:DD:EE:FF')

    def test_get_device_id_from_forwarded_for(self):
        """Test getting device ID from X-Forwarded-For when no ID header."""
        headers = {'X-Forwarded-For': '192.168.1.1, 10.0.0.1'}
        handler = self.create_handler('/api/display', headers)

        device_id = handler._get_device_id()

        self.assertEqual(device_id, '192.168.1.1')

    def test_get_device_id_fallback_to_client_address(self):
        """Test falling back to client_address when no headers present."""
        handler = self.create_handler('/api/display')
        handler.client_address = ('10.0.0.1', 12345)

        device_id = handler._get_device_id()

        self.assertEqual(device_id, '10.0.0.1')
    
    @mock.patch.object(APICalls, '_handle_api_setup')
    def test_get_setup(self, mock_handle_setup):
        """Test GET request to /api/setup."""
        handler = self.create_handler('/api/setup')
        handler.do_GET()
        mock_handle_setup.assert_called_once()
    
    def test_get_not_found(self):
        """Test GET request to unknown endpoint."""
        handler = self.create_handler('/unknown')
        handler.do_GET()
        self.assertEqual(handler._response_code, 404)
    
    def test_post_log(self):
        """Test POST request to /api/log."""
        handler = self.create_handler('/api/log')
        handler.headers = {'Content-Length': '0'}
        handler.rfile = BytesIO(b'')
        handler.do_POST()
        self.assertEqual(handler._response_code, 200)
    
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


if __name__ == '__main__':
    unittest.main()
