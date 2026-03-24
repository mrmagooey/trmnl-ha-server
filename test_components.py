"""Additional tests for components module to achieve full coverage."""

import unittest
from unittest import mock
import io
from PIL import Image
import logging

from components import (
    render_dashboard_image,
    _create_info_image,
    tile_components,
    eink_display,
    _draw_graph_component,
    _draw_entity_component,
    _draw_calendar_component,
    _draw_entities_component,
    _draw_todo_list_component,
    _load_font,
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
        with mock.patch('components.ImageFont.truetype', side_effect=IOError()):
            with mock.patch('components.ImageFont.load_default') as mock_default:
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
            "Test Sensor",
            [],  # Empty data
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_draw_graph_single_value(self):
        """Test drawing graph with single value (edge case for min/max)."""
        from datetime import datetime
        
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
        ]
        
        img = _draw_graph_component(
            "Test Sensor",
            data_points,
            400,
            300,
            mock_logger
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
            "Test Sensor",
            data_points,
            400,
            300,
            mock_logger
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
            "A" * 100,  # Very long title
            data_points,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


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
        from models import RenderData
        
        render_data = {
            'type': 'entity',
            'friendly_name': 'Test',
            'data': 'value',
            'large_display': False
        }
        
        with mock.patch('components._draw_entity_component') as mock_draw:
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
        
        with mock.patch('components._draw_entity_component') as mock_draw:
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

    @mock.patch('hass_client.get_entity_state')
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
    
    @mock.patch('hass_client.get_entity_state')
    @mock.patch('state.server_state')
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
    
    @mock.patch('hass_client.get_entity_state')
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
    
    @mock.patch('hass_client._fetch_history')
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
    
    @mock.patch('hass_client._fetch_calendar_events')
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
    
    @mock.patch('hass_client.get_entity_state')
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
    
    @mock.patch('hass_client._fetch_todo_list')
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


if __name__ == '__main__':
    unittest.main()
