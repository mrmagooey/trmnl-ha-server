"""Golden image tests for dashboard rendering.

On first run (or when UPDATE_GOLDEN=1 is set), golden reference images are
generated and saved to the golden/ directory. On subsequent runs the rendered
output is compared pixel-for-pixel against those references.

To regenerate all golden images:
    UPDATE_GOLDEN=1 python -m pytest test_golden.py
"""

import logging
import os
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops

from components import render_dashboard_image

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"

mock_logger = mock.Mock(spec=logging.Logger)


def assert_golden(img_io: BytesIO, name: str) -> None:
    """Compare rendered image against a golden reference.

    Generates the golden file if it does not exist or UPDATE_GOLDEN=1 is set.
    Saves a .diff.png alongside the golden file on mismatch to aid debugging.
    """
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden_path = GOLDEN_DIR / f"{name}.png"

    img_io.seek(0)
    rendered = Image.open(img_io)
    rendered.load()

    if not golden_path.exists() or UPDATE:
        rendered.save(golden_path)
        return

    golden = Image.open(golden_path)
    diff = ImageChops.difference(rendered, golden)
    if diff.getbbox() is not None:
        diff_path = GOLDEN_DIR / f"{name}.diff.png"
        diff.save(diff_path)
        raise AssertionError(
            f"Rendered image differs from golden '{golden_path.name}'. "
            f"Diff saved to {diff_path}. "
            f"Run with UPDATE_GOLDEN=1 to regenerate golden images."
        )


def mock_datetime(time_str: str = "12:00"):
    """Return a mock for datetime.datetime that produces a fixed time string."""
    m = mock.MagicMock()
    m.now.return_value.astimezone.return_value.strftime.return_value = time_str
    return m


class TestGoldenImages(unittest.TestCase):

    def setUp(self):
        mock_logger.reset_mock()

    @mock.patch('hass_client._fetch_history')
    def test_history_graph_dashboard(self, mock_fetch_history):
        """Two history graph components side by side."""
        mock_fetch_history.side_effect = [
            [[
                {'state': '18.0', 'last_changed': '2024-01-15T08:00:00+00:00'},
                {'state': '19.5', 'last_changed': '2024-01-15T10:00:00+00:00'},
                {'state': '21.0', 'last_changed': '2024-01-15T12:00:00+00:00'},
                {'state': '20.5', 'last_changed': '2024-01-15T14:00:00+00:00'},
                {'state': '19.0', 'last_changed': '2024-01-15T16:00:00+00:00'},
            ]],
            [[
                {'state': '55', 'last_changed': '2024-01-15T08:00:00+00:00'},
                {'state': '60', 'last_changed': '2024-01-15T10:00:00+00:00'},
                {'state': '58', 'last_changed': '2024-01-15T12:00:00+00:00'},
                {'state': '62', 'last_changed': '2024-01-15T14:00:00+00:00'},
                {'state': '57', 'last_changed': '2024-01-15T16:00:00+00:00'},
            ]],
        ]
        dashboard = {
            'name': 'lounge',
            'title': 'Lounge',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Temperature', 'type': 'history_graph'},
                {'entity_name': 'sensor.humidity', 'friendly_name': 'Humidity', 'type': 'history_graph'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)

        assert_golden(img_io, 'history_graph_dashboard')

    @mock.patch('hass_client.get_entity_state')
    def test_entity_dashboard(self, mock_get_entity_state):
        """Single entity value displayed large."""
        mock_get_entity_state.return_value = {'state': '21.4'}
        dashboard = {
            'name': 'temp',
            'title': 'Temperature',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Living Room', 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)

        assert_golden(img_io, 'entity_dashboard')

    @mock.patch('hass_client.get_entity_state')
    @mock.patch('state.server_state')
    def test_entity_dashboard_with_battery(self, mock_state, mock_get_entity_state):
        """Entity dashboard with battery percentage in top-right."""
        mock_get_entity_state.return_value = {'state': '21.4'}
        mock_state.consume_battery_voltage.return_value = 3.7
        dashboard = {
            'name': 'temp_battery',
            'title': 'Temperature',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Living Room', 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, 'AA:BB:CC:DD:EE:FF')

        assert_golden(img_io, 'entity_dashboard_with_battery')

    @mock.patch('hass_client.get_entity_state')
    def test_rotated_dashboard(self, mock_get_entity_state):
        """Dashboard rotated -90 degrees produces portrait dimensions."""
        mock_get_entity_state.return_value = {'state': '21.4'}
        dashboard = {
            'name': 'temp_portrait',
            'title': 'Temperature',
            'rotate': -90,
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Living Room', 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)

        img_io.seek(0)
        with Image.open(img_io) as img:
            self.assertEqual(img.size, (480, 800))

        assert_golden(img_io, 'rotated_dashboard')


if __name__ == '__main__':
    unittest.main()
