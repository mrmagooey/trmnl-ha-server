"""End-to-end coverage for calendar day grouping through render_dashboard_image."""

import logging
import unittest
from datetime import datetime, timezone
from unittest import mock

from PIL import Image

from trmnl_server.components import render_dashboard_image

mock_logger = mock.Mock(spec=logging.Logger)


def _events(spec):
    out = []
    for day, count in spec:
        for i in range(count):
            # (9 + i) wraps at 24 instead of overflowing: an unwrapped hour
            # goes out of range as soon as a day carries more than 15
            # events (9+15 == 24), which the busy-day overflow test below
            # relies on.
            hour = (9 + i) % 24
            out.append({
                'summary': f'Event {i} with a reasonably long summary line',
                'start': {'dateTime': f'{day}T{hour:02d}:00:00+00:00'},
                'end': {'dateTime': f'{day}T{hour:02d}:30:00+00:00'},
            })
    return out


class TestCalendarGroupingEndToEnd(unittest.TestCase):

    DASHBOARD = {
        'name': 'cal',
        'title': 'Cal',
        'components': [
            {'type': 'calendar', 'friendly_name': 'Shared Calendar',
             'arguments': {'calendar_id': 'calendar.family', 'days': 2}},
            {'type': 'entity', 'friendly_name': 'Temp',
             'entity_name': 'sensor.t'},
        ],
    }

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_renders_a_grouped_two_day_calendar(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = _events([('2024-01-17', 3), ('2024-01-18', 3)])
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        img = Image.open(img_io)
        self.assertEqual(img.size, (800, 480))

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_a_busy_day_renders_an_overflow_row(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = _events([('2024-01-17', 20)])
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        self.assertEqual(Image.open(img_io).size, (800, 480))

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_an_empty_calendar_still_renders(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = []
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        self.assertEqual(Image.open(img_io).size, (800, 480))
