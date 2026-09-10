"""End-to-end coverage for calendar day grouping through render_dashboard_image."""

import logging
import unittest
from datetime import datetime, timezone
from unittest import mock

from PIL import Image, ImageDraw

from trmnl_server.components import render_dashboard_image, _calendar_layout, _draw_spine

mock_logger = mock.Mock(spec=logging.Logger)

# render_dashboard_image's own constants (src/trmnl_server/components.py); the
# calendar tile size a dashboard resolves to, used to compute the same layout
# the real render will settle on before asserting against it.
_WIDTH, _HEIGHT, _TOP_MARGIN = 800, 480, 40
_TILE_W, _TILE_H = _WIDTH, (_HEIGHT - _TOP_MARGIN) // 2  # 2-component dashboard
_SOLO_TILE_W, _SOLO_TILE_H = _WIDTH, _HEIGHT - _TOP_MARGIN  # calendar-only dashboard


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

    # A calendar-only dashboard, for the grouping test below: it wants two
    # full day groups to actually draw (not truncated by the footer), which
    # needs more vertical room than the calendar shares with a sibling in
    # DASHBOARD above.
    DASHBOARD_SOLO = {
        'name': 'cal-solo',
        'title': 'Cal',
        'components': [
            {'type': 'calendar', 'friendly_name': 'Shared Calendar',
             'arguments': {'calendar_id': 'calendar.family', 'days': 2}},
        ],
    }

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    def test_renders_a_grouped_two_day_calendar(self, mock_cal):
        """Two separate day groups render as two separate spines in gutter mode.

        Asserting only the output image size would pass identically whether
        grouping happened or not -- and whether gutter mode was ever reached.
        """
        events = _events([('2024-01-17', 3), ('2024-01-18', 3)])
        mock_cal.return_value = events

        layout = _calendar_layout(list(events), _SOLO_TILE_W, _SOLO_TILE_H, mock_logger)
        self.assertEqual(layout.mode, 'gutter')
        self.assertFalse(layout.footer, "test assumption: both groups fit without truncation")
        self.assertEqual(len(layout.groups), 2, "expected two distinct day groups")

        with mock.patch(
            'trmnl_server.components._draw_spine', side_effect=_draw_spine
        ) as mock_spine:
            img_io = render_dashboard_image(self.DASHBOARD_SOLO, mock_logger)
        img = Image.open(img_io)
        self.assertEqual(img.size, (800, 480))
        # One spine draw per day group actually reached the canvas -- not
        # just decided upon internally.
        spine_labels = {call.args[1] for call in mock_spine.call_args_list}
        self.assertEqual(len(spine_labels), 2, "expected a spine drawn for each day group")

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_a_busy_day_renders_an_overflow_row(self, mock_state, mock_cal):
        """A day too busy to fit renders a "+N more" footer with real ink.

        Asserting only the output image size would pass identically whether
        the footer ever drew at all.
        """
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        events = _events([('2024-01-17', 20)])
        mock_cal.return_value = events

        layout = _calendar_layout(list(events), _TILE_W, _TILE_H, mock_logger)
        self.assertTrue(layout.footer, "test assumption: this fixture overflows")

        drawn_texts = []
        real_text = ImageDraw.ImageDraw.text

        def spy_text(self, xy, text, *args, **kwargs):
            drawn_texts.append(text)
            return real_text(self, xy, text, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, 'text', spy_text):
            img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        self.assertEqual(Image.open(img_io).size, (800, 480))
        self.assertIn(f"+{layout.overflow} more", drawn_texts)

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_an_empty_calendar_still_renders(self, mock_state, mock_cal):
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = []
        img_io = render_dashboard_image(self.DASHBOARD, mock_logger)
        self.assertEqual(Image.open(img_io).size, (800, 480))
