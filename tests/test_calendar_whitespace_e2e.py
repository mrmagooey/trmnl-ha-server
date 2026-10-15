"""End-to-end coverage for calendar whitespace (separator and footer accounting).

Drives render_dashboard_image with the reported scenario: a large_display
calendar above four entity cards and ten events over seven days. The calendar
used to reserve a separator for every hidden day group and a whole row for
the "+N more" footer, drawing 2 rows with ~65px of blank space below.
"""

import logging
import unittest
from unittest import mock

from PIL import Image, ImageDraw

from trmnl_server.components import render_dashboard_image

mock_logger = mock.Mock(spec=logging.Logger)

_TOP_MARGIN = 40
_TILE_H = (480 - _TOP_MARGIN) // 2  # large_display calendar occupies half the height
_DAYS = [17, 17, 18, 19, 19, 20, 21, 22, 23, 23]


class TestCalendarWhitespaceEndToEnd(unittest.TestCase):
    """The reported dashboard must fill its calendar panel with events."""

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_large_calendar_draws_four_rows_and_a_tight_footer(self, mock_state, mock_cal):
        """Four event rows plus "+6 more" are drawn and the foot gap is small."""
        mock_state.return_value = {'state': '20.0', 'friendly_name': 'Temp'}
        mock_cal.return_value = [
            {'summary': f'Meeting {i}',
             'start': {'dateTime': f'2024-01-{d}T{9 + i % 2:02d}:00:00+00:00'},
             'end': {'dateTime': f'2024-01-{d}T{9 + i % 2:02d}:30:00+00:00'}}
            for i, d in enumerate(_DAYS)
        ]
        dashboard = {
            'name': 'calwhitespace',
            'title': 'Cal',
            'components': [
                {'type': 'calendar', 'friendly_name': 'Calendar',
                 'entity_name': 'calendar.home', 'large_display': True,
                 'arguments': {'calendar_id': 'calendar.home'}},
            ] + [
                {'type': 'entity', 'friendly_name': n, 'entity_name': 'sensor.t'}
                for n in ('A', 'B', 'C', 'D')
            ],
        }

        drawn: list[str] = []
        real_text = ImageDraw.ImageDraw.text

        def spy_text(self, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return real_text(self, xy, text, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, 'text', spy_text):
            img_io = render_dashboard_image(dashboard, mock_logger)

        rows = [t for t in drawn if 'Meeting' in t]
        self.assertEqual(len(rows), 4, drawn)
        self.assertIn('+6 more', drawn)

        # Lowest ink in the calendar panel (the footer text) vs the panel's
        # bottom edge. Columns are limited to the text area, clear of any
        # panel border at the edges.
        img = Image.open(img_io).convert('L')
        panel_bottom = _TOP_MARGIN + _TILE_H
        px = img.load()
        ink_bottom = max(
            y for y in range(_TOP_MARGIN, panel_bottom)
            if any(px[x, y] < 200 for x in range(30, 400))
        )
        self.assertLessEqual(
            panel_bottom - ink_bottom, 20,
            f"{panel_bottom - ink_bottom}px of blank space under the footer",
        )


if __name__ == '__main__':
    unittest.main()
