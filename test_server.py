import unittest
from unittest import mock
import io
from PIL import Image
import logging

from components import render_dashboard_image
from hass_client import _fetch_history, get_entity_state, _fetch_calendar_events

# Create a mock logger for testing
mock_logger = mock.Mock(spec=logging.Logger)

class TestServer(unittest.TestCase):
    @mock.patch('hass_client._fetch_history')
    def test_render_dashboard_image(self, mock_fetch_history):
        """
        Tests that render_dashboard_image returns a valid PNG image
        by mocking the history fetch call.
        """
        # Set up mock return values for _fetch_history
        mock_history_1 = [[
            {'state': '21.5', 'last_changed': '2025-11-18T10:00:00+00:00'},
            {'state': '22.0', 'last_changed': '2025-11-18T11:00:00+00:00'},
        ]]
        mock_history_2 = [[
            {'state': '23.0', 'last_changed': '2025-11-18T10:00:00+00:00'},
            {'state': '22.5', 'last_changed': '2025-11-18T11:00:00+00:00'},
        ]]
        mock_fetch_history.side_effect = [mock_history_1, mock_history_2]

        components = [
            {'entity_name': 'sensor.test1', 'friendly_name': 'Test Sensor 1', 'type': 'history_graph'},
            {'entity_name': 'sensor.test2', 'friendly_name': 'Test Sensor 2', 'type': 'history_graph'}
        ]
        dashboard = {
            'name': 'test_dash',
            'title': 'Test Dashboard',
            'components': components
        }

        # Call the function to be tested
        img_io = render_dashboard_image(dashboard, mock_logger)

        # Assertions
        # 1. Check if the function returns a BytesIO object
        self.assertIsInstance(img_io, io.BytesIO)

        # 2. Check if the BytesIO object contains a valid PNG image,
        # is the correct size, and is black and white.
        img_io.seek(0)
        try:
            with Image.open(img_io) as img:
                self.assertEqual(img.format, 'PNG')
                self.assertEqual(img.size, (800, 480))
                self.assertEqual(img.mode, '1')
        except IOError:
            self.fail("The returned object is not a valid PNG image.")
        
        # 3. Check if _fetch_history was called with the correct entity names
        self.assertEqual(mock_fetch_history.call_count, 2)
        mock_fetch_history.assert_any_call(components[0]['entity_name'], mock_logger)
        mock_fetch_history.assert_any_call(components[1]['entity_name'], mock_logger)

    @mock.patch('hass_client._fetch_history')
    def test_render_dashboard_image_no_data(self, mock_fetch_history):
        """
        Tests that render_dashboard_image handles no data gracefully.
        """
        mock_fetch_history.return_value = []

        dashboard = {
            'name': 'test_dash_no_data',
            'title': 'Test Dashboard No Data',
            'components': [
                {'entity_name': 'sensor.test1', 'friendly_name': 'Test Sensor 1', 'type': 'history_graph'},
                {'entity_name': 'sensor.test2', 'friendly_name': 'Test Sensor 2', 'type': 'history_graph'}
            ]
        }

        img_io = render_dashboard_image(dashboard, mock_logger)
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        try:
            with Image.open(img_io) as img:
                self.assertEqual(img.format, 'PNG')
                self.assertEqual(img.size, (800, 480))
        except IOError:
            self.fail("The returned object is not a valid PNG image.")

    @mock.patch('hass_client.get_entity_state')
    def test_render_dashboard_image_entity(self, mock_get_entity_state):
        """
        Tests that render_dashboard_image handles an entity component.
        """
        mock_get_entity_state.return_value = {'state': 'On'}

        dashboard = {
            'name': 'test_dash_entity',
            'title': 'Test Entity',
            'components': [
                {'entity_name': 'binary_sensor.test', 'friendly_name': 'Test Sensor', 'type': 'entity'}
            ]
        }

        img_io = render_dashboard_image(dashboard, mock_logger)

        # Assertions
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        try:
            with Image.open(img_io) as img:
                self.assertEqual(img.format, 'PNG')
                self.assertEqual(img.size, (800, 480))
        except IOError:
            self.fail("The returned object is not a valid PNG image.")
        
        mock_get_entity_state.assert_called_once_with('binary_sensor.test', mock_logger)

    @mock.patch('hass_client._fetch_calendar_events')
    def test_render_dashboard_image_calendar(self, mock_fetch_calendar_events):
        """
        Tests that render_dashboard_image handles a calendar component.
        """
        mock_fetch_calendar_events.return_value = [
            {
                'summary': 'Test Event 1',
                'start': {'dateTime': '2025-11-22T09:00:00+00:00'},
                'end': {'dateTime': '2025-11-22T10:00:00+00:00'}
            }
        ]

        dashboard = {
            'name': 'test_dash_calendar',
            'title': 'Test Calendar',
            'components': [
                {
                    'friendly_name': 'My Test Calendar',
                    'type': 'calendar',
                    'arguments': {
                        'calendar_id': 'calendar.test',
                        'days': 2
                    }
                }
            ]
        }

        img_io = render_dashboard_image(dashboard, mock_logger)

        # Assertions
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        try:
            with Image.open(img_io) as img:
                self.assertEqual(img.format, 'PNG')
                self.assertEqual(img.size, (800, 480))
        except IOError:
            self.fail("The returned object is not a valid PNG image.")
        
        mock_fetch_calendar_events.assert_called_once_with('calendar.test', days=2, logger=mock_logger)

    @mock.patch('hass_client.get_entity_state')
    def test_render_dashboard_image_entities_list(self, mock_get_entity_state):
        """
        Tests that render_dashboard_image handles an entities list component.
        """
        mock_get_entity_state.side_effect = [
            {'state': '21.5'},
            {'state': 'On'}
        ]

        dashboard = {
            'name': 'test_dash_entities',
            'title': 'Test Entities List',
            'components': [
                {
                    'friendly_name': 'Sensor List',
                    'type': 'entities',
                    'entities': [
                        {'entity_name': 'sensor.temp', 'friendly_name': 'Temperature'},
                        {'entity_name': 'binary_sensor.door', 'friendly_name': 'Door'}
                    ]
                }
            ]
        }

        img_io = render_dashboard_image(dashboard, mock_logger)

        # Assertions
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        try:
            with Image.open(img_io) as img:
                self.assertEqual(img.format, 'PNG')
                self.assertEqual(img.size, (800, 480))
        except IOError:
            self.fail("The returned object is not a valid PNG image.")
        
        self.assertEqual(mock_get_entity_state.call_count, 2)
        mock_get_entity_state.assert_any_call('sensor.temp', mock_logger)
        mock_get_entity_state.assert_any_call('binary_sensor.door', mock_logger)

    @mock.patch('hass_client.get_entity_state')
    def test_render_dashboard_image_portrait_mode(self, mock_get_entity_state):
        """
        Tests that render_dashboard_image rotates the image 90 degrees when portrait=True.
        """
        mock_get_entity_state.return_value = {'state': 'On'}

        dashboard = {
            'name': 'test_dash_portrait',
            'title': 'Test Portrait',
            'portrait': True,
            'components': [
                {'entity_name': 'binary_sensor.test', 'friendly_name': 'Test Sensor', 'type': 'entity'}
            ]
        }

        img_io = render_dashboard_image(dashboard, mock_logger)

        # Assertions
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        try:
            with Image.open(img_io) as img:
                self.assertEqual(img.format, 'PNG')
                # In portrait mode, the image should be rotated 90 degrees
                # So dimensions should be 480x800 instead of 800x480
                self.assertEqual(img.size, (480, 800))
        except IOError:
            self.fail("The returned object is not a valid PNG image.")


if __name__ == '__main__':
    unittest.main()
