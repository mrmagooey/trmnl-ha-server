"""Tests for hass_client module."""

import logging
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest import mock
from urllib.error import HTTPError, URLError

from PIL import Image

from trmnl_server import hass_client
from trmnl_server.hass_client import (
    _cast_to_numbers,
    _fetch_history,
    _process_history_to_points,
    _select_entity_value,
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

    def test_unavailable_state_becomes_gap_marker(self):
        """An 'unavailable' state produces a (timestamp, None) gap marker instead of being dropped."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'unavailable', 'last_changed': '2025-01-15T11:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-01-15T12:00:00+00:00'},
        ]]

        result = _process_history_to_points(history)

        self.assertEqual(len(result), 3)
        self.assertIsNone(result[1][1])
        self.assertEqual(result[1][0], datetime.fromisoformat('2025-01-15T11:00:00+00:00'))

    def test_unknown_state_becomes_gap_marker(self):
        """An 'unknown' state produces a (timestamp, None) gap marker instead of being dropped."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'unknown', 'last_changed': '2025-01-15T11:00:00+00:00'},
        ]]

        result = _process_history_to_points(history)

        self.assertEqual(len(result), 2)
        self.assertIsNone(result[1][1])

    def test_genuinely_invalid_state_still_dropped(self):
        """A state that is neither numeric nor a known HA gap sentinel is still dropped entirely."""
        history = [[
            {'state': '21.5', 'last_changed': '2025-01-15T10:00:00+00:00'},
            {'state': 'garbled-nonsense', 'last_changed': '2025-01-15T11:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-01-15T12:00:00+00:00'},
        ]]

        result = _process_history_to_points(history)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][1], 21.5)
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


class TestSelectEntityValue(unittest.TestCase):
    def setUp(self):
        self.logger = mock.Mock(spec=logging.Logger)

    def test_no_attribute_returns_state(self):
        state_data = {'state': 'cool', 'attributes': {'current_temperature': 21.5}}
        result = _select_entity_value(state_data, None, 'climate.lr', self.logger)
        self.assertEqual(result, 'cool')

    def test_empty_attribute_returns_state(self):
        state_data = {'state': 'cool', 'attributes': {'current_temperature': 21.5}}
        result = _select_entity_value(state_data, '', 'climate.lr', self.logger)
        self.assertEqual(result, 'cool')

    def test_attribute_present_returns_stringified_value(self):
        state_data = {'state': 'cool', 'attributes': {'current_temperature': 21.5}}
        result = _select_entity_value(state_data, 'current_temperature', 'climate.lr', self.logger)
        self.assertEqual(result, '21.5')

    def test_attribute_missing_warns_and_returns_none(self):
        state_data = {'state': 'cool', 'attributes': {}}
        result = _select_entity_value(state_data, 'current_temperature', 'climate.lr', self.logger)
        self.assertIsNone(result)
        self.logger.warning.assert_called_once_with(mock.ANY, 'current_temperature', 'climate.lr')

    def test_non_scalar_attribute_is_stringified(self):
        forecast = [{'temp': 1}]
        state_data = {'state': 'sunny', 'attributes': {'forecast': forecast}}
        result = _select_entity_value(state_data, 'forecast', 'weather.home', self.logger)
        self.assertEqual(result, str(forecast))

    def test_none_state_data_returns_none(self):
        result = _select_entity_value(None, 'current_temperature', 'climate.lr', self.logger)
        self.assertIsNone(result)

    def test_no_attribute_missing_state_returns_none(self):
        state_data = {'attributes': {}}  # entity present but no 'state' key
        result = _select_entity_value(state_data, None, 'sensor.x', self.logger)
        self.assertIsNone(result)


def _png_bytes(img: "Image.Image") -> bytes:
    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


class _FakeImageResponse:
    """Context-manager stand-in for urlopen's response."""

    def __init__(self, body: bytes):
        self._body = body
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        """Return successive chunks of the body on repeated calls."""
        if n == -1:
            chunk = self._body[self._offset:]
            self._offset = len(self._body)
            return chunk
        if n <= 0:
            return b""
        chunk = self._body[self._offset:self._offset + n]
        self._offset += len(chunk)
        return chunk


class TestFetchEntityImage(unittest.TestCase):
    """Tests for fetch_entity_image."""

    def setUp(self):
        hass_client.reset_image_cache()
        self.logger = mock.Mock(spec=logging.Logger)
        patcher_url = mock.patch.object(hass_client, 'HASS_URL', 'http://hass')
        patcher_token = mock.patch.object(hass_client, 'HASS_TOKEN', 'secret-token')
        patcher_url.start()
        patcher_token.start()
        self.addCleanup(patcher_url.stop)
        self.addCleanup(patcher_token.stop)
        self.addCleanup(hass_client.reset_image_cache)

    def _ok(self, img=None):
        img = img if img is not None else Image.new('RGB', (40, 20), (200, 100, 50))
        return _FakeImageResponse(_png_bytes(img))

    def test_camera_uses_camera_proxy_with_bearer(self):
        """camera.* entities hit /api/camera_proxy with the Bearer token."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            img = hass_client.fetch_entity_image('camera.front', self.logger)
        req = m.call_args.args[0]
        self.assertEqual(req.full_url, 'http://hass/api/camera_proxy/camera.front')
        self.assertEqual(req.get_header('Authorization'), 'Bearer secret-token')
        self.assertEqual(img.mode, 'L')
        self.assertEqual(img.size, (40, 20))

    def test_image_uses_image_proxy(self):
        """image.* entities hit /api/image_proxy."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            hass_client.fetch_entity_image('image.map', self.logger)
        self.assertEqual(m.call_args.args[0].full_url, 'http://hass/api/image_proxy/image.map')

    def test_entity_id_is_url_quoted(self):
        """Characters outside an entity id's normal set are percent-encoded."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            hass_client.fetch_entity_image('camera.a/b c', self.logger)
        self.assertEqual(m.call_args.args[0].full_url, 'http://hass/api/camera_proxy/camera.a%2Fb%20c')

    def test_rejects_other_domains_without_request(self):
        """A non camera/image entity logs an error and never makes a request."""
        with mock.patch.object(hass_client, 'urlopen') as m:
            self.assertIsNone(hass_client.fetch_entity_image('sensor.temp', self.logger))
        m.assert_not_called()
        self.logger.error.assert_called()

    def test_missing_credentials_returns_none(self):
        """No HASS_TOKEN: error logged, no request, None."""
        with mock.patch.object(hass_client, 'HASS_TOKEN', None), \
             mock.patch.object(hass_client, 'urlopen') as m:
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))
        m.assert_not_called()

    def test_timeout_passed_and_fallback_used(self):
        """timeout reaches urlopen; a later timeout serves the last good image."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()) as m:
            first = hass_client.fetch_entity_image('camera.front', self.logger, timeout=7)
        self.assertEqual(m.call_args.kwargs['timeout'], 7)
        with mock.patch.object(hass_client, 'urlopen', side_effect=TimeoutError('slow')):
            second = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertIsNotNone(second)
        self.assertEqual(second.tobytes(), first.tobytes())

    def test_http_error_logs_status_not_token_and_falls_back(self):
        """401 logs status + entity (never the token) and serves the last good image."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            hass_client.fetch_entity_image('camera.front', self.logger)
        err = HTTPError('http://hass/x', 401, 'Unauthorized', {}, None)
        with mock.patch.object(hass_client, 'urlopen', side_effect=err):
            img = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertIsNotNone(img)
        logged = ' '.join(str(a) for c in self.logger.error.call_args_list for a in c.args)
        self.assertIn('401', logged)
        self.assertIn('camera.front', logged)
        self.assertNotIn('secret-token', logged)

    def test_failure_with_no_history_returns_none(self):
        """A URLError before any success yields None."""
        with mock.patch.object(hass_client, 'urlopen', side_effect=URLError('down')):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))

    def test_garbage_bytes_fall_back(self):
        """Undecodable bytes log an error and fall back."""
        with mock.patch.object(hass_client, 'urlopen', return_value=_FakeImageResponse(b'not an image')):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))
        self.logger.error.assert_called()

    def test_oversized_body_rejected(self):
        """A body over IMAGE_MAX_BYTES is rejected without decoding."""
        big = b'x' * (hass_client.IMAGE_MAX_BYTES + 1)
        with mock.patch.object(hass_client, 'urlopen', return_value=_FakeImageResponse(big)):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))

    def test_too_many_pixels_rejected(self):
        """An image whose header exceeds IMAGE_MAX_PIXELS is rejected."""
        with mock.patch.object(hass_client, 'IMAGE_MAX_PIXELS', 100), \
             mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            self.assertIsNone(hass_client.fetch_entity_image('camera.front', self.logger))

    def test_transparent_png_composited_on_white(self):
        """Fully transparent pixels become white, not black."""
        rgba = Image.new('RGBA', (10, 10), (0, 0, 0, 0))
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok(rgba)):
            img = hass_client.fetch_entity_image('image.map', self.logger)
        self.assertEqual(img.getextrema(), (255, 255))

    def test_fallback_is_a_copy(self):
        """Mutating a returned image never corrupts the stored fallback."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            first = hass_client.fetch_entity_image('camera.front', self.logger)
        first.paste(0, (0, 0, 40, 20))
        with mock.patch.object(hass_client, 'urlopen', side_effect=URLError('down')):
            second = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertNotEqual(second.getextrema(), (0, 0))

    def test_timeout_during_read_falls_back(self):
        """TimeoutError during read() falls back to last good image and logs error."""
        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            first = hass_client.fetch_entity_image('camera.front', self.logger)
        self.logger.reset_mock()

        class _TimeoutResponse:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self, n: int = -1) -> bytes:
                raise TimeoutError('timeout during read')

        with mock.patch.object(hass_client, 'urlopen', return_value=_TimeoutResponse()):
            second = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertIsNotNone(second)
        self.assertEqual(second.tobytes(), first.tobytes())
        self.logger.error.assert_called()

    def test_incomplete_read_during_read_falls_back(self):
        """http.client.IncompleteRead during read() falls back and logs error."""
        import http.client

        with mock.patch.object(hass_client, 'urlopen', return_value=self._ok()):
            first = hass_client.fetch_entity_image('camera.front', self.logger)
        self.logger.reset_mock()

        class _IncompleteReadResponse:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self, n: int = -1) -> bytes:
                raise http.client.IncompleteRead(b'')

        with mock.patch.object(hass_client, 'urlopen', return_value=_IncompleteReadResponse()):
            second = hass_client.fetch_entity_image('camera.front', self.logger)
        self.assertIsNotNone(second)
        self.assertEqual(second.tobytes(), first.tobytes())
        self.logger.error.assert_called()

    def test_trickle_exceeding_deadline_returns_none(self):
        """A response that trickles past the deadline returns None and logs error."""
        monotonic_values = [0.0]  # Start at time 0

        def advance_time(*args):
            monotonic_values[0] += 6.0  # Each call advances 6 seconds, exceeding 5s timeout
            return monotonic_values[0]

        class _TrickleResponse:
            def __init__(self):
                self._chunks = [b'x' * 100, b'y' * 100]
                self._chunk_idx = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, n: int = -1) -> bytes:
                if self._chunk_idx >= len(self._chunks):
                    return b''
                chunk = self._chunks[self._chunk_idx]
                self._chunk_idx += 1
                return chunk

        with mock.patch.object(hass_client, 'time') as mock_time, \
             mock.patch.object(hass_client, 'urlopen', return_value=_TrickleResponse()):
            mock_time.monotonic.side_effect = advance_time
            result = hass_client.fetch_entity_image('camera.front', self.logger, timeout=5)

        self.assertIsNone(result)
        # Should log timeout error
        logged = ' '.join(str(a) for c in self.logger.error.call_args_list for a in c.args)
        self.assertIn('Timed out', logged)
        self.assertIn('camera.front', logged)


if __name__ == '__main__':
    unittest.main()
