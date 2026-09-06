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

from trmnl_server.components import render_dashboard_image
from trmnl_server import url_source

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


class _FakeResponse:
    """Minimal stand-in for the object urlopen returns as a context manager."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body


class TestGoldenImages(unittest.TestCase):

    def setUp(self):
        mock_logger.reset_mock()
        from trmnl_server.state import server_state
        server_state.reset_todo_pages()

    @mock.patch('trmnl_server.hass_client._fetch_history')
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
        fixed_now = datetime(2024, 1, 15, 17, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)

        assert_golden(img_io, 'history_graph_dashboard')

    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_stale_tail(self, mock_fetch_history):
        """Entity stopped reporting 12h before now -> long dotted hold tail."""
        mock_fetch_history.return_value = [[
            {'state': '18.0', 'last_changed': '2024-01-15T06:00:00+00:00'},
            {'state': '19.5', 'last_changed': '2024-01-15T08:00:00+00:00'},
            {'state': '21.0', 'last_changed': '2024-01-15T10:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'stale',
            'title': 'Stale Sensor',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Temperature',
                 'type': 'history_graph', 'hours': 24},
            ],
        }
        # Last reading 10:00; now 22:00 -> 12h dotted tail inside a 24h window.
        fixed_now = datetime(2024, 1, 15, 22, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_stale_tail')

    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_gap_then_recovery(self, mock_fetch_history):
        """A gap ('unavailable') mid-series must render as a dashed hold across
        the whole outage, not a smooth solid interpolation between the values
        on either side of it -- the exact regression this plan fixes, pinned
        pixel-for-pixel.

        The readings are chosen so every behaviour is visible inside the plot
        area rather than hidden on an axis: real readings on both sides of the
        gap give solid segments, and the held value (20.0) sits a third of the
        way up a 18.0-24.0 range instead of landing on the min or max where it
        would be indistinguishable from the axis line.
        """
        mock_fetch_history.return_value = [[
            {'state': '18.0', 'last_changed': '2024-01-15T06:00:00+00:00'},
            {'state': '20.0', 'last_changed': '2024-01-15T08:00:00+00:00'},
            {'state': 'unavailable', 'last_changed': '2024-01-15T09:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2024-01-15T13:00:00+00:00'},
            {'state': '24.0', 'last_changed': '2024-01-15T15:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'gap_recovery',
            'title': 'Gap Recovery',
            'components': [
                {'entity_name': 'sensor.temperature', 'friendly_name': 'Temperature',
                 'type': 'history_graph', 'hours': 24},
            ],
        }
        fixed_now = datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_gap_then_recovery')

    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_custom_hours(self, mock_fetch_history):
        """A 6h window with a recent reading renders a short tail."""
        mock_fetch_history.return_value = [[
            {'state': '60', 'last_changed': '2024-01-15T17:00:00+00:00'},
            {'state': '62', 'last_changed': '2024-01-15T18:30:00+00:00'},
            {'state': '59', 'last_changed': '2024-01-15T20:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'recent',
            'title': 'Recent',
            'components': [
                {'entity_name': 'sensor.humidity', 'friendly_name': 'Humidity',
                 'type': 'history_graph', 'hours': 6},
            ],
        }
        fixed_now = datetime(2024, 1, 15, 20, 30, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_custom_hours')

    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_graph_bipolar(self, mock_fetch_history):
        """A zero_baseline graph for data spanning negative to positive values."""
        mock_fetch_history.return_value = [[
            {'state': '-8.0', 'last_changed': '2024-01-15T08:00:00+00:00'},
            {'state': '-3.0', 'last_changed': '2024-01-15T10:00:00+00:00'},
            {'state': '2.0', 'last_changed': '2024-01-15T12:00:00+00:00'},
            {'state': '6.0', 'last_changed': '2024-01-15T14:00:00+00:00'},
            {'state': '-1.0', 'last_changed': '2024-01-15T16:00:00+00:00'},
        ]]
        dashboard = {
            'name': 'netpower',
            'title': 'Net Power',
            'components': [
                {'entity_name': 'sensor.net_power', 'friendly_name': 'Net Power',
                 'type': 'history_graph', 'zero_baseline': True, 'hours': 24},
            ],
        }
        fixed_now = datetime(2024, 1, 15, 17, 0, tzinfo=timezone.utc)
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger, now=fixed_now)
        assert_golden(img_io, 'history_graph_bipolar')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
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

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_entity_unbroken_value_ellipsized(self, mock_get_entity_state):
        """A long value with no spaces is ellipsized, not clipped at the tile edges.

        Word wrapping splits on spaces, so this value cannot be broken; it is
        truncated with a trailing ellipsis instead of overflowing the tile.
        """
        mock_get_entity_state.return_value = {
            'state': '{"nested":{"deep":[1,2,3]},"more":"data","and":"evenmorevalues"}'
        }
        dashboard = {
            'name': 'blob',
            'title': 'Blob',
            'components': [
                {'entity_name': 'sensor.blob', 'friendly_name': 'Raw Feed', 'type': 'entity'},
                {'entity_name': 'sensor.blob', 'friendly_name': 'Raw Feed 2', 'type': 'entity'},
                {'entity_name': 'sensor.blob', 'friendly_name': 'Raw Feed 3', 'type': 'entity'},
                {'entity_name': 'sensor.blob', 'friendly_name': 'Raw Feed 4', 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)

        assert_golden(img_io, 'entity_unbroken_value')

    def test_url_panel(self):
        """A url component renders its extracted value like an entity panel."""
        url_source.reset_cache()
        dashboard = {
            'name': 'url_panel',
            'title': 'URL',
            'components': [
                {
                    'type': 'url',
                    'friendly_name': 'Bitcoin',
                    'url': 'http://e.com/price',
                    'json_path': '.data.amount',
                },
            ],
        }
        with mock.patch.object(
            url_source, 'urlopen', return_value=_FakeResponse(b'{"data": {"amount": "64231"}}')
        ):
            render_dashboard_image(dashboard, mock_logger)  # cold: schedules the fetch
            url_source._wait_for_pending()
            with mock.patch('datetime.datetime', mock_datetime()):
                img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'url_panel')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_title_size_harmonisation(self, mock_get_entity_state):
        """Four panels in a 2x2 grid: the top row shares one title size, the
        bottom row drops to a smaller one because of a long title."""
        mock_get_entity_state.return_value = {'state': '21.5', 'attributes': {}}
        dashboard = {
            'name': 'harmonisation',
            'title': 'Harmonisation',
            'components': [
                {'entity_name': 'sensor.a', 'friendly_name': 'Kitchen', 'type': 'entity'},
                {'entity_name': 'sensor.b', 'friendly_name': 'Hallway', 'type': 'entity'},
                {'entity_name': 'sensor.c', 'friendly_name': 'Study', 'type': 'entity'},
                {'entity_name': 'sensor.d',
                 'friendly_name': 'Extremely Long Living Room Temperature Sensor',
                 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'title_size_harmonisation')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_two_line_title_harmonisation(self, mock_get_entity_state):
        """A row whose long title wraps to two lines, keeping a large font."""
        mock_get_entity_state.return_value = {'state': '21.5', 'attributes': {}}
        dashboard = {
            'name': 'twoline',
            'title': 'Two Line',
            'components': [
                {'entity_name': 'sensor.a', 'friendly_name': 'Kitchen', 'type': 'entity'},
                {'entity_name': 'sensor.b', 'friendly_name': 'Hallway', 'type': 'entity'},
                {'entity_name': 'sensor.c', 'friendly_name': 'Study', 'type': 'entity'},
                {'entity_name': 'sensor.d',
                 'friendly_name': 'Back Garden Soil Moisture Level', 'type': 'entity'},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'two_line_title_harmonisation')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_entity_value_stays_within_tile_bounds(self, mock_get_entity_state):
        """A 3x3 grid of short tiles: no entity value may bleed past its tile.

        Regression test for the value's vertical centring, which used a fixed
        offset tuned for the single-line title layout. On short tiles the
        resolved value font is large enough that the offset under-corrects,
        pushing the value's ink past the tile's (and here, the image's)
        bottom edge -- most visibly in the bottom row.
        """
        mock_get_entity_state.return_value = {'state': '21.5', 'attributes': {}}
        names = [
            'Kitchen', 'Hallway', 'Study',
            'Bedroom', 'Office', 'Garage',
            'Back Garden Soil Moisture Level', 'Attic', 'Basement',
        ]
        dashboard = {
            'name': 'grid9',
            'title': 'Grid',
            'components': [
                {'entity_name': f'sensor.{i}', 'friendly_name': name, 'type': 'entity'}
                for i, name in enumerate(names)
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)

        img_io.seek(0)
        rendered = Image.open(img_io)
        rendered.load()

        # Bottom row's tiles: 3 cols x 266px, tile bottom at y=478 (WIDTH=800,
        # HEIGHT=480, TOP_MARGIN=40, 3x3 grid -> tile_height = (480-40)//3 = 146).
        tile_width = 800 // 3
        tile_bottom = 40 + 146 * 3
        for col in range(3):
            strip = rendered.crop(
                (col * tile_width, tile_bottom - 2, (col + 1) * tile_width, tile_bottom)
            ).convert("L")
            self.assertEqual(
                strip.getextrema()[0], 255,
                f"column {col}'s value ink reached its tile's bottom edge",
            )

        assert_golden(img_io, 'entity_value_bounds_grid')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    @mock.patch('trmnl_server.state.server_state')
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

    @mock.patch('trmnl_server.hass_client.get_entity_state')
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

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_entity_attribute_dashboard(self, mock_get_entity_state):
        """Climate entity displaying current_temperature attribute instead of state."""
        mock_get_entity_state.return_value = {
            'state': 'cool',
            'attributes': {'current_temperature': 21.5},
        }
        dashboard = {
            'name': 'attr',
            'components': [
                {
                    'type': 'entity',
                    'entity_name': 'climate.living_room',
                    'attribute': 'current_temperature',
                    'friendly_name': 'Living Room Temp',
                },
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'entity_attribute_dashboard')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    def test_body_text_size_harmonisation(self, mock_fetch_calendar, mock_get_entity_state):
        """List rows of very different lengths must all render at one size.

        Each row used to run its own shrink-to-fit loop, so a single panel
        could show four rows at four different sizes with the gap between them
        tracking each row's own ink height. Both panels here mix short rows
        with rows far too long for the tile, which is exactly what pulled the
        sizes apart.
        """
        mock_get_entity_state.side_effect = lambda name, logger: {
            'sensor.a': {'state': '21.5', 'attributes': {}},
            'sensor.b': {'state': '19.8', 'attributes': {}},
            'sensor.c': {'state': '20.0', 'attributes': {}},
            'sensor.d': {'state': '12.34', 'attributes': {}},
        }[name]
        mock_fetch_calendar.return_value = [
            {'summary': 'Standup',
             'start': {'dateTime': '2024-01-01T09:00:00+00:00'},
             'end': {'dateTime': '2024-01-01T09:15:00+00:00'}},
            {'summary': 'Quarterly planning review with the wider platform team',
             'start': {'dateTime': '2024-01-02T10:00:00+00:00'},
             'end': {'dateTime': '2024-01-02T12:00:00+00:00'}},
            {'summary': 'Dentist', 'start': {'date': '2024-01-03'}},
        ]
        dashboard = {
            'name': 'bodysize',
            'title': 'Body Size',
            'components': [
                {
                    'type': 'entities',
                    'friendly_name': 'Sensors',
                    'entities': [
                        {'entity_name': 'sensor.a', 'friendly_name': 'Kitchen'},
                        {'entity_name': 'sensor.b',
                         'friendly_name': 'Living Room Temperature'},
                        {'entity_name': 'sensor.c', 'friendly_name': 'Hall'},
                        {'entity_name': 'sensor.d',
                         'friendly_name': 'Back Garden Soil Moisture Sensor'},
                    ],
                },
                {
                    'type': 'calendar',
                    'friendly_name': 'Calendar',
                    'entity_name': 'calendar.home',
                    'arguments': {'calendar_id': 'calendar.home'},
                },
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'body_text_size_harmonisation')

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_row_body_text_size_harmonisation(self, mock_get_entity_state):
        """Four entity-list panels in a 2x2 grid: each row settles on one size.

        The top-left panel has a row far too long for its tile, so its
        row-mate drops to the same rung. The bottom row has no long rows and
        keeps the top rung -- harmonisation is per layout row, exactly as it
        is for titles.
        """
        mock_get_entity_state.side_effect = lambda name, logger: {
            'sensor.short': {'state': '20.0', 'attributes': {}},
            'sensor.long': {'state': '12.34', 'attributes': {}},
        }[name]
        short_rows = [
            {'entity_name': 'sensor.short', 'friendly_name': 'Hall'},
            {'entity_name': 'sensor.short', 'friendly_name': 'Attic'},
        ]
        long_rows = [
            {'entity_name': 'sensor.short', 'friendly_name': 'Kitchen'},
            {'entity_name': 'sensor.long',
             'friendly_name': 'Back Garden Soil Moisture Sensor'},
        ]
        dashboard = {
            'name': 'rowbody',
            'title': 'Row Body',
            'components': [
                {'type': 'entities', 'friendly_name': 'Sensors', 'entities': long_rows},
                {'type': 'entities', 'friendly_name': 'Upstairs', 'entities': short_rows},
                {'type': 'entities', 'friendly_name': 'Garage', 'entities': short_rows},
                {'type': 'entities', 'friendly_name': 'Shed', 'entities': short_rows},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'row_body_text_size_harmonisation')

    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_two_column_overflow(self, mock_fetch_todo):
        """A two-column todo list that overflows to multiple pages (page 0)."""
        mock_fetch_todo.return_value = [
            {'summary': f'Task {i}', 'status': 'needs_action'} for i in range(40)
        ]
        dashboard = {
            'name': 'tasks',
            'title': 'Tasks',
            'components': [
                {'entity_name': 'todo.tasks', 'friendly_name': 'Tasks',
                 'type': 'todo_list', 'columns': 2},
            ],
        }
        with mock.patch('datetime.datetime', mock_datetime()):
            img_io = render_dashboard_image(dashboard, mock_logger)
        assert_golden(img_io, 'todo_two_column_overflow')


if __name__ == '__main__':
    unittest.main()
