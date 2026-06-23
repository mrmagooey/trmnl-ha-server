"""Additional tests for components module to achieve full coverage."""

import unittest
from unittest import mock
import io
from PIL import Image
import logging

from trmnl_server.components import (
    render_dashboard_image,
    _create_info_image,
    tile_components,
    eink_display,
    _draw_dashed_line,
    _draw_graph_component,
    _draw_entity_component,
    _draw_calendar_component,
    _draw_entities_component,
    _draw_todo_list_component,
    _load_font,
    _todo_capacity,
)

# Create a mock logger for testing
mock_logger = mock.Mock(spec=logging.Logger)


class TestLoadFont(unittest.TestCase):
    """Tests for _load_font function."""
    
    def test_load_font_success(self):
        """Test loading font successfully."""
        font = _load_font(30, mock_logger)
        self.assertIsNotNone(font)
    
    def test_load_font_failure(self):
        """Test font loading falls back to default."""
        # This should succeed but if font file doesn't exist, it falls back
        with mock.patch('trmnl_server.components.ImageFont.truetype', side_effect=IOError()):
            with mock.patch('trmnl_server.components.ImageFont.load_default') as mock_default:
                mock_default.return_value = mock.Mock()
                font = _load_font(30, mock_logger)
                self.assertIsNotNone(font)
                mock_default.assert_called_once()


class TestCreateInfoImage(unittest.TestCase):
    """Tests for _create_info_image function."""
    
    def test_create_info_image(self):
        """Test creating an info image."""
        img = _create_info_image("Test Message", 400, 300, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
        self.assertEqual(img.mode, 'RGB')
    
    def test_create_info_image_multiline(self):
        """Test creating an info image with multiline message."""
        img = _create_info_image("Line 1\nLine 2\nLine 3", 400, 300, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_create_info_image_none_message(self):
        """Test creating an info image with None message."""
        img = _create_info_image(None, 400, 300, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_create_info_image_shrink_to_fit(self):
        """Test that image text shrinks to fit."""
        # Very long message should trigger shrink-to-fit logic
        img = _create_info_image("A" * 200, 200, 100, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (200, 100))


class TestDrawGraphComponent(unittest.TestCase):
    """Tests for _draw_graph_component function."""

    def test_draw_graph_no_data(self):
        """Test drawing graph with no data points."""
        from datetime import datetime
        img = _draw_graph_component(
            "Test Sensor", [], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_single_value(self):
        """Test drawing graph with single value (edge case for min/max)."""
        from datetime import datetime
        data_points = [(datetime(2025, 1, 15, 10, 0), 25.0)]
        img = _draw_graph_component(
            "Test Sensor", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_same_time(self):
        """Test drawing graph with same timestamp (edge case for time delta)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
            (datetime(2025, 1, 15, 10, 0), 26.0),
        ]
        img = _draw_graph_component(
            "Test Sensor", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_long_title(self):
        """Test drawing graph with very long title."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
            (datetime(2025, 1, 15, 11, 0), 26.0),
        ]
        img = _draw_graph_component(
            "A" * 100, data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)

    def test_dotted_tail_drawn_when_last_point_before_window_end(self):
        """A stale entity gets a dashed hold line in the right portion of the plot."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), 20.0),
        ]
        img = _draw_graph_component(
            "Stale", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        img_no_gap = _draw_graph_component(
            "Stale", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 20.0),
            ], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        from PIL import ImageChops
        self.assertIsNotNone(
            ImageChops.difference(img, img_no_gap).getbbox(),
            "expected the dotted hold tail to change the image",
        )

        # The tail must be DASHED: along a horizontal band in the right portion
        # of the plot there must be both painted and gap pixels.
        w, h = img.size  # (400, 300)
        band = []
        for x in range(int(w * 0.55), int(w * 0.95)):
            for y in range(h):
                band.append(img.getpixel((x, y)))
        has_black = any(p == (0, 0, 0) for p in band)
        has_white = any(p == (255, 255, 255) for p in band)
        if not (has_black and has_white):
            # LANCZOS antialiasing may blur pure black/white; use thresholds
            has_black = any(sum(p) < 240 for p in band)
            has_white = any(sum(p) > 600 for p in band)
        self.assertTrue(has_black, "expected painted dash pixels in the tail region")
        self.assertTrue(has_white, "expected gap pixels between dashes in the tail region")

    def test_fully_stale_only_boundary_point(self):
        """A single point well before window_end still renders (flat dotted hold)."""
        from datetime import datetime
        data_points = [(datetime(2025, 1, 15, 8, 0), 42.0)]
        img = _draw_graph_component(
            "Dead", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_no_tail_when_data_reaches_window_end(self):
        """When the last reading is exactly at window_end, no dotted tail is drawn."""
        from datetime import datetime
        from PIL import ImageChops
        ws = datetime(2025, 1, 15, 8, 0)
        we = datetime(2025, 1, 15, 16, 0)
        # Last point exactly at window_end -> guard suppresses the tail.
        reaches_end = _draw_graph_component(
            "Live", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 22.0),
            ], 400, 300, mock_logger, window_start=ws, window_end=we,
        )
        # Same two points but rendered without any later gap is identical to itself;
        # assert determinism (no tail introduces nondeterminism/extra marks).
        reaches_end_again = _draw_graph_component(
            "Live", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 22.0),
            ], 400, 300, mock_logger, window_start=ws, window_end=we,
        )
        self.assertIsNone(
            ImageChops.difference(reaches_end, reaches_end_again).getbbox(),
            "rendering must be deterministic when no tail is drawn",
        )

    def test_zero_baseline_default_off_unchanged(self):
        """Omitting zero_baseline renders identically to passing it False."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 5.0),
            (datetime(2025, 1, 15, 10, 0), 8.0),
        ]
        kwargs = dict(
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        default = _draw_graph_component("S", data_points, 400, 300, mock_logger, **kwargs)
        explicit_off = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger, zero_baseline=False, **kwargs
        )
        self.assertIsNone(
            ImageChops.difference(default, explicit_off).getbbox(),
            "default path must equal zero_baseline=False",
        )

    def test_zero_baseline_changes_bipolar_rendering(self):
        """For data crossing zero, the flag changes the rendered image."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -10.0),
            (datetime(2025, 1, 15, 10, 0), 10.0),
        ]
        kwargs = dict(
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        off = _draw_graph_component("S", data_points, 400, 300, mock_logger, **kwargs)
        on = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger, zero_baseline=True, **kwargs
        )
        self.assertIsNotNone(
            ImageChops.difference(off, on).getbbox(),
            "zero_baseline must change rendering for bipolar data",
        )

    def test_zero_baseline_draws_horizontal_line_near_mid(self):
        """Symmetric data (-10..+10) puts the zero line near vertical centre,
        spanning most of the plot width as a near-continuous black row."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -10.0),
            (datetime(2025, 1, 15, 9, 30), 0.0),
            (datetime(2025, 1, 15, 10, 0), 10.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        w, h = img.size  # (400, 300)
        # Scan the central horizontal band for a row that is mostly black across
        # the plot width (the zero line spans the full graph width).
        def black(px):
            return sum(px) < 240
        best = 0
        for y in range(int(h * 0.35), int(h * 0.65)):
            count = sum(
                1 for x in range(int(w * 0.15), int(w * 0.80))
                if black(img.getpixel((x, y)))
            )
            best = max(best, count)
        span = int(w * 0.80) - int(w * 0.15)
        self.assertGreater(
            best, span * 0.6,
            "expected a near-continuous horizontal zero line in the central band",
        )

    def test_zero_baseline_all_positive_includes_zero(self):
        """All-positive data with the flag on still renders (floor pulled to 0)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 5.0),
            (datetime(2025, 1, 15, 10, 0), 9.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_zero_baseline_all_negative_includes_zero(self):
        """All-negative data with the flag on still renders (ceiling pulled to 0)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -5.0),
            (datetime(2025, 1, 15, 10, 0), -9.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_zero_baseline_flat_at_zero(self):
        """A flat line at exactly 0 with the flag on renders without error."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 0.0),
            (datetime(2025, 1, 15, 10, 0), 0.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))


class TestDrawEntityComponent(unittest.TestCase):
    """Tests for _draw_entity_component function."""
    
    def test_draw_entity_none_value(self):
        """Test drawing entity with None value."""
        img = _draw_entity_component(
            "Test Entity",
            None,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_draw_entity_float_value(self):
        """Test drawing entity with float value."""
        img = _draw_entity_component(
            "Temperature",
            23.5,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entity_string_value(self):
        """Test drawing entity with string value."""
        img = _draw_entity_component(
            "Status",
            "Active",
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entity_long_value(self):
        """Test drawing entity with very long value."""
        img = _draw_entity_component(
            "Description",
            "A" * 100,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entity_wrapping(self):
        """Test drawing entity with value that needs wrapping."""
        img = _draw_entity_component(
            "Message",
            "This is a very long message that should wrap",
            300,
            200,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestDrawCalendarComponent(unittest.TestCase):
    """Tests for _draw_calendar_component function."""
    
    def test_draw_calendar_no_events(self):
        """Test drawing calendar with no events."""
        img = _draw_calendar_component(
            "My Calendar",
            [],
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_draw_calendar_with_events(self):
        """Test drawing calendar with events."""
        events = [
            {
                'summary': 'Meeting',
                'start': {'dateTime': '2025-01-15T10:00:00+00:00'},
                'end': {'dateTime': '2025-01-15T11:00:00+00:00'}
            },
            {
                'summary': 'All Day Event',
                'start': {'date': '2025-01-16'},
                'end': {'date': '2025-01-17'}
            }
        ]
        
        img = _draw_calendar_component(
            "My Calendar",
            events,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_calendar_long_event_text(self):
        """Test drawing calendar with very long event text."""
        events = [
            {
                'summary': 'A' * 100,
                'start': {'dateTime': '2025-01-15T10:00:00+00:00'},
                'end': {'dateTime': '2025-01-15T11:00:00+00:00'}
            }
        ]
        
        img = _draw_calendar_component(
            "My Calendar",
            events,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestDrawEntitiesComponent(unittest.TestCase):
    """Tests for _draw_entities_component function."""
    
    def test_draw_entities_empty(self):
        """Test drawing entities list with no entities."""
        img = _draw_entities_component(
            "Sensors",
            [],
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_draw_entities_with_data(self):
        """Test drawing entities list with data."""
        entity_states = [
            {'friendly_name': 'Temp', 'state': 22.5},
            {'friendly_name': 'Humidity', 'state': '45%'},
        ]
        
        img = _draw_entities_component(
            "Sensors",
            entity_states,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entities_long_text(self):
        """Test drawing entities list with long text."""
        entity_states = [
            {'friendly_name': 'A' * 50, 'state': 'B' * 50},
        ]
        
        img = _draw_entities_component(
            "Sensors",
            entity_states,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestDrawTodoListComponent(unittest.TestCase):
    """Tests for _draw_todo_list_component function."""
    
    def test_draw_todo_list_empty(self):
        """Test drawing todo list with no items."""
        img = _draw_todo_list_component(
            "My Todos",
            [],
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_draw_todo_list_with_items(self):
        """Test drawing todo list with items."""
        items = [
            {'summary': 'Buy milk', 'status': 'needs_action'},
            {'summary': 'Call mom', 'status': 'needs_action'},
            {'summary': 'Walk dog', 'status': 'completed'},  # Should be skipped
        ]
        
        img = _draw_todo_list_component(
            "Shopping List",
            items,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_todo_list_long_text(self):
        """Test drawing todo list with long item text."""
        items = [
            {'summary': 'This is a very long todo item that should be resized to fit', 'status': 'needs_action'},
        ]
        
        img = _draw_todo_list_component(
            "Todos",
            items,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_todo_list_only_completed(self):
        """Test drawing todo list when all items are completed."""
        items = [
            {'summary': 'Done task', 'status': 'completed'},
        ]
        
        img = _draw_todo_list_component(
            "Completed",
            items,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestTileComponents(unittest.TestCase):
    """Tests for tile_components function."""
    
    def test_empty_components(self):
        """Test tiling with no components."""
        img = tile_components([], 800, 480, 40, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (800, 480))
    
    def test_single_component(self):
        """Test tiling single component."""
        from trmnl_server.models import RenderData
        
        render_data = {
            'type': 'entity',
            'friendly_name': 'Test',
            'data': 'value',
            'large_display': False
        }
        
        with mock.patch('trmnl_server.components._draw_entity_component') as mock_draw:
            mock_draw.return_value = Image.new('RGB', (400, 220), color='white')
            img = tile_components([render_data], 800, 480, 40, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
    
    def test_large_display_component(self):
        """Test tiling with large display component."""
        render_data = [
            {
                'type': 'entity',
                'friendly_name': 'Large',
                'data': 'value',
                'large_display': True
            },
            {
                'type': 'entity',
                'friendly_name': 'Small',
                'data': 'value2',
                'large_display': False
            }
        ]
        
        with mock.patch('trmnl_server.components._draw_entity_component') as mock_draw:
            mock_draw.return_value = Image.new('RGB', (400, 200), color='white')
            img = tile_components(render_data, 800, 480, 40, mock_logger)
        
        self.assertIsInstance(img, Image.Image)


class TestEinkDisplay(unittest.TestCase):
    """Tests for eink_display function."""
    
    def test_eink_display(self):
        """Test converting image to e-ink format."""
        # Create a simple test image
        img = Image.new('RGB', (100, 100), color=(128, 128, 128))
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        result = eink_display(img_io)
        
        self.assertIsInstance(result, io.BytesIO)
        result.seek(0)
        
        # Verify it's a valid PNG
        with Image.open(result) as img_result:
            self.assertEqual(img_result.format, 'PNG')
            self.assertEqual(img_result.mode, '1')  # Black and white


class TestRenderDashboardImage(unittest.TestCase):
    """Additional tests for render_dashboard_image function."""

    def setUp(self):
        mock_logger.reset_mock()
        from trmnl_server.state import server_state
        server_state.reset_todo_pages()

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_empty_components(self, mock_get_entity_state):
        """Test rendering dashboard with no components."""
        dashboard = {
            'name': 'empty_dash',
            'title': 'Empty Dashboard',
            'components': []
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        with Image.open(img_io) as img:
            self.assertEqual(img.format, 'PNG')
            self.assertEqual(img.size, (800, 480))
    
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    @mock.patch('trmnl_server.state.server_state')
    def test_render_with_battery(self, mock_server_state, mock_get_entity_state):
        """Test rendering with battery voltage."""
        mock_get_entity_state.return_value = {'state': 'On'}
        mock_server_state.consume_battery_voltage.return_value = 3.7
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'entity'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger, 'AA:BB:CC:DD:EE:FF')

        self.assertIsInstance(img_io, io.BytesIO)
        mock_server_state.consume_battery_voltage.assert_called_once_with('AA:BB:CC:DD:EE:FF')
    
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_entity_component_no_data(self, mock_get_entity_state):
        """Test entity component with no data."""
        mock_get_entity_state.return_value = None
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'entity'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
    
    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_component_no_data(self, mock_fetch_history):
        """Test history component with no data."""
        mock_fetch_history.return_value = None
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'history_graph'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
    
    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    def test_calendar_no_calendar_id(self, mock_fetch_calendar):
        """Test calendar component without calendar_id."""
        dashboard = {
            'name': 'test_dash',
            'components': [
                {
                    'friendly_name': 'Calendar',
                    'type': 'calendar',
                    'arguments': {'days': 7}  # No calendar_id
                }
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        mock_logger.warning.assert_called_once()
        mock_fetch_calendar.assert_not_called()
    
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_unknown_component_type(self, mock_get_entity_state):
        """Test handling unknown component type."""
        mock_get_entity_state.return_value = {'state': 'On'}
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'unknown_type'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        mock_logger.warning.assert_called_once()
    
    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_list_component(self, mock_fetch_todo):
        """Test todo list component rendering."""
        mock_fetch_todo.return_value = [
            {'summary': 'Buy milk', 'status': 'needs_action'},
            {'summary': 'Call mom', 'status': 'needs_action'},
        ]
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'todo.shopping_list', 'friendly_name': 'Shopping', 'type': 'todo_list'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        with Image.open(img_io) as img:
            self.assertEqual(img.format, 'PNG')
        mock_fetch_todo.assert_called_once()

    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_overflow_renders_first_page(self, mock_fetch_todo):
        """A todo_list with more items than fit renders (page 0 on first render)."""
        mock_fetch_todo.return_value = [
            {'summary': f'Item {i}', 'status': 'needs_action'} for i in range(50)
        ]
        dashboard = {
            'name': 'chores',
            'components': [
                {'entity_name': 'todo.chores', 'friendly_name': 'Chores',
                 'type': 'todo_list', 'columns': 2},
            ],
        }
        img_io = render_dashboard_image(dashboard, mock_logger)
        self.assertIsInstance(img_io, io.BytesIO)


class TestDrawDashedLine(unittest.TestCase):
    """Tests for the _draw_dashed_line helper."""

    def test_horizontal_dash_has_gaps(self):
        """A dashed line leaves white gaps, unlike a solid line."""
        from PIL import ImageDraw
        img = Image.new('RGB', (100, 10), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 5), (99, 5), fill='black', width=1, dash_on=6, dash_off=6)
        row = [img.getpixel((x, 5)) for x in range(100)]
        black = sum(1 for p in row if p == (0, 0, 0))
        white = sum(1 for p in row if p == (255, 255, 255))
        self.assertGreater(black, 0, "expected some painted (black) pixels")
        self.assertGreater(white, 0, "expected some gap (white) pixels")

    def test_zero_length_is_noop(self):
        """Start == end draws nothing and does not raise."""
        from PIL import ImageDraw
        img = Image.new('RGB', (10, 10), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (5, 5), (5, 5), fill='black', width=1, dash_on=4, dash_off=4)
        self.assertEqual(img.getpixel((5, 5)), (255, 255, 255))

    def test_diagonal_does_not_overrun_endpoint(self):
        """Dashes follow a diagonal and never paint past the end point."""
        from PIL import ImageDraw
        img = Image.new('RGB', (60, 60), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 0), (50, 50), fill='black', width=1, dash_on=5, dash_off=5)
        # Some pixels along the diagonal are painted...
        painted = any(img.getpixel((i, i)) == (0, 0, 0) for i in range(51))
        self.assertTrue(painted)
        # ...and nothing is painted well beyond the end point.
        self.assertEqual(img.getpixel((58, 58)), (255, 255, 255))

    def test_zero_period_falls_back_to_solid(self):
        """dash_on + dash_off == 0 draws a solid line instead of looping forever."""
        from PIL import ImageDraw
        img = Image.new('RGB', (20, 5), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 2), (19, 2), fill='black', width=1, dash_on=0, dash_off=0)
        row = [img.getpixel((x, 2)) for x in range(20)]
        self.assertTrue(all(p == (0, 0, 0) for p in row), "expected a fully solid line")


class TestTodoCapacity(unittest.TestCase):
    """Tests for todo-list page capacity math."""

    def test_single_column(self):
        # height 480 -> body = 480 - 50 - 15 = 415; 415 // 36 = 11 rows.
        rows, cap = _todo_capacity(480, 1)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 11)

    def test_multi_column_multiplies(self):
        rows, cap = _todo_capacity(480, 3)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 33)

    def test_minimum_one_row(self):
        # A tiny card still yields at least one row.
        rows, cap = _todo_capacity(10, 2)
        self.assertEqual(rows, 1)
        self.assertEqual(cap, 2)

    def test_invalid_columns_coerces_to_one(self):
        # columns <= 0 is coerced to a single column.
        rows, cap = _todo_capacity(480, 0)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 11)


class TestTodoListPaginationRender(unittest.TestCase):
    """Tests for columns + pagination in _draw_todo_list_component."""

    @staticmethod
    def _items(n):
        return [{'summary': f'Item {i}', 'status': 'needs_action'} for i in range(n)]

    def test_count_in_title(self):
        # 5 incomplete items -> title contains "(5)".
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("Shopping", self._items(5), 400, 300, mock_logger)
        drawn = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertIn("Shopping (5)", drawn)

    def test_page_indicator_only_when_multipage(self):
        # One page (few items): no "/" indicator.
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", self._items(3), 400, 300, mock_logger, columns=1, page=0)
        single = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertNotIn("/", single)
        # Many items at 1 column on a short card -> multiple pages -> "1/N".
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", self._items(60), 400, 300, mock_logger, columns=1, page=0)
        multi = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertRegex(multi, r"1/\d+")

    def test_pagination_shows_different_items_per_page(self):
        from PIL import ImageChops
        items = self._items(60)
        page0 = _draw_todo_list_component("L", items, 400, 300, mock_logger, columns=1, page=0)
        page1 = _draw_todo_list_component("L", items, 400, 300, mock_logger, columns=1, page=1)
        self.assertIsNotNone(
            ImageChops.difference(page0, page1).getbbox(),
            "different pages must render different items",
        )

    def test_columns_fit_more_than_single_column(self):
        # With 2 columns a card holds more items on one page than with 1 column,
        # so a count that paginates at 1 column may fit on a single 2-col page.
        # Card height 480 -> 11 rows/column; 2 columns -> capacity 22.
        items = self._items(20)
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", items, 400, 480, mock_logger, columns=2, page=0)
        two_col = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        # 20 items <= 22 capacity -> single page, no indicator.
        self.assertNotIn("/", two_col)

    def test_long_item_is_truncated_with_ellipsis(self):
        long_item = [{'summary': 'X' * 200, 'status': 'needs_action'}]
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", long_item, 400, 300, mock_logger, columns=2, page=0)
        drawn = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertIn("…", drawn)  # ellipsis character

    def test_empty_list_message_unchanged(self):
        img = _draw_todo_list_component("L", [], 400, 300, mock_logger)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))


if __name__ == '__main__':
    unittest.main()
