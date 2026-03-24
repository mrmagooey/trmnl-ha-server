"""Tests for server module."""

import unittest
from unittest import mock
import os
import tempfile
from io import StringIO

from server import setup_logging, create_handler_class, main


class TestSetupLogging(unittest.TestCase):
    """Tests for setup_logging function."""
    
    @mock.patch('server.makedirs')
    @mock.patch('server.path.join')
    @mock.patch('server.getLogger')
    @mock.patch('server.StreamHandler')
    @mock.patch('server.RotatingFileHandler')
    def test_setup_logging_success(self, mock_file_handler, mock_stream_handler,
                                   mock_get_logger, mock_path_join, mock_makedirs):
        """Test successful logging setup."""
        mock_logger = mock.Mock()
        mock_get_logger.return_value = mock_logger
        mock_path_join.return_value = '/logs/log'

        logger = setup_logging()

        self.assertEqual(logger, mock_logger)
        mock_makedirs.assert_called_once_with('/logs', exist_ok=True)
        mock_logger.addHandler.assert_any_call(mock_stream_handler.return_value)
        mock_logger.addHandler.assert_any_call(mock_file_handler.return_value)

    @mock.patch('server.makedirs')
    @mock.patch('server.gettempdir')
    @mock.patch('server.getLogger')
    @mock.patch('server.StreamHandler')
    @mock.patch('server.RotatingFileHandler')
    def test_setup_logging_fallback_to_temp(self, mock_file_handler, mock_stream_handler,
                                            mock_get_logger, mock_gettempdir, mock_makedirs):
        """Test fallback to temp directory when /logs is not accessible."""
        mock_logger = mock.Mock()
        mock_get_logger.return_value = mock_logger
        mock_makedirs.side_effect = OSError("Permission denied")
        mock_gettempdir.return_value = '/tmp'

        logger = setup_logging()

        mock_gettempdir.assert_called_once()


class TestCreateHandlerClass(unittest.TestCase):
    """Tests for create_handler_class function."""
    
    def test_create_handler(self):
        """Test creating handler class with logger."""
        mock_logger = mock.Mock()
        
        Handler = create_handler_class(mock_logger)
        
        # Check that it's a class
        self.assertTrue(isinstance(Handler, type))


class TestMain(unittest.TestCase):
    """Tests for main function."""
    
    @mock.patch('server.setup_logging')
    @mock.patch('server.ArgumentParser')
    @mock.patch('server.socketserver.TCPServer')
    @mock.patch('server.create_handler_class')
    def test_main_success(self, mock_create_handler, mock_tcp_server, 
                         mock_arg_parser, mock_setup_logging):
        """Test successful server startup."""
        mock_logger = mock.Mock()
        mock_setup_logging.return_value = mock_logger
        
        mock_args = mock.Mock()
        mock_args.port = 8000
        mock_parser = mock.Mock()
        mock_parser.parse_args.return_value = mock_args
        mock_arg_parser.return_value = mock_parser
        
        mock_httpd = mock.Mock()
        mock_tcp_server.return_value = mock_httpd
        
        # Mock serve_forever to raise KeyboardInterrupt after first call
        mock_httpd.serve_forever.side_effect = KeyboardInterrupt()
        
        try:
            main()
        except KeyboardInterrupt:
            pass
        
        mock_tcp_server.assert_called_once()
        mock_httpd.serve_forever.assert_called_once()
        mock_httpd.server_close.assert_called_once()
    
    @mock.patch('server.setup_logging')
    @mock.patch('server.ArgumentParser')
    @mock.patch('server.socketserver.TCPServer')
    @mock.patch('server.create_handler_class')
    @mock.patch('server.time.sleep')
    def test_main_retry_on_port_in_use(self, mock_sleep, mock_create_handler, 
                                       mock_tcp_server, mock_arg_parser, mock_setup_logging):
        """Test server retry when port is in use."""
        mock_logger = mock.Mock()
        mock_setup_logging.return_value = mock_logger
        
        mock_args = mock.Mock()
        mock_args.port = 8000
        mock_parser = mock.Mock()
        mock_parser.parse_args.return_value = mock_args
        mock_arg_parser.return_value = mock_parser
        
        # First calls fail, then succeed
        mock_httpd = mock.Mock()
        mock_tcp_server.side_effect = [
            OSError("Port in use"),
            OSError("Port in use"),
            mock_httpd
        ]
        
        # Mock serve_forever to raise KeyboardInterrupt
        mock_httpd.serve_forever.side_effect = KeyboardInterrupt()
        
        try:
            main()
        except KeyboardInterrupt:
            pass
        
        self.assertEqual(mock_tcp_server.call_count, 3)
        mock_logger.warning.assert_called()
    
    @mock.patch('server.setup_logging')
    @mock.patch('server.ArgumentParser')
    @mock.patch('server.socketserver.TCPServer')
    @mock.patch('server.create_handler_class')
    @mock.patch('server.time.sleep')
    def test_main_max_retries_exceeded(self, mock_sleep, mock_create_handler,
                                       mock_tcp_server, mock_arg_parser, mock_setup_logging):
        """Test server giving up after max retries."""
        mock_logger = mock.Mock()
        mock_setup_logging.return_value = mock_logger
        
        mock_args = mock.Mock()
        mock_args.port = 8000
        mock_parser = mock.Mock()
        mock_parser.parse_args.return_value = mock_args
        mock_arg_parser.return_value = mock_parser
        
        # All calls fail
        mock_tcp_server.side_effect = OSError("Port in use")
        
        with self.assertRaises(OSError):
            main()
        
        self.assertEqual(mock_tcp_server.call_count, 8)  # max_attempts
        mock_logger.error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
