"""End-to-end coverage for the calendar minimum body font size.

Drives the full rendering path -- render_dashboard_image, the outermost
interface this batch renderer has -- with mocked Home Assistant calendar data
containing an over-long summary, and asserts the resulting dashboard draws
its calendar rows ellipsized at (or above) the floor size rather than shrunk
to the ladder's overall floor of 16.
"""

import logging
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image, ImageDraw

from trmnl_server.components import (
    render_dashboard_image,
    CALENDAR_MIN_BODY_SIZE,
    BODY_SIZE_LADDER,
    COMPONENT_SCALE,
)

mock_logger = mock.Mock(spec=logging.Logger)


class TestCalendarMinimumBodyFontSizeEndToEnd(unittest.TestCase):
    """A long calendar summary must not drag rendered rows below the floor."""

    def setUp(self):
        mock_logger.reset_mock()
        from trmnl_server.state import server_state
        server_state.reset_todo_pages()

    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    def test_over_long_summary_ellipsizes_at_the_floor_size(self, mock_fetch_calendar):
        mock_fetch_calendar.return_value = [
            {'summary': ('Quarterly planning review with the platform team '
                         'and several other cross-functional stakeholders'),
             'start': {'dateTime': '2024-01-02T10:00:00+00:00'},
             'end': {'dateTime': '2024-01-02T12:00:00+00:00'}},
        ]
        dashboard = {
            'name': 'calendar-only',
            'title': 'Calendar',
            'components': [
                {
                    'type': 'calendar',
                    'friendly_name': 'Calendar',
                    'entity_name': 'calendar.home',
                    'arguments': {'calendar_id': 'calendar.home'},
                },
            ],
        }

        # (size, text) for every string the renderer draws anywhere on the
        # dashboard -- the header clock and dashboard title share the canvas
        # with the calendar panel, so rows are picked out by content below
        # rather than assuming every draw call belongs to the calendar.
        drawn: list[tuple[int | None, str]] = []
        original_text = ImageDraw.ImageDraw.text

        def spying_text(self, xy, text, *args, **kwargs):
            font = kwargs.get('font', args[1] if len(args) > 1 else None)
            size = font.size // COMPONENT_SCALE if font is not None and getattr(
                font, 'size', None) else None
            drawn.append((size, str(text)))
            return original_text(self, xy, text, *args, **kwargs)

        with mock.patch.object(ImageDraw.ImageDraw, 'text', spying_text):
            img_io: BytesIO = render_dashboard_image(dashboard, mock_logger)

        img_io.seek(0)
        img = Image.open(img_io)
        img.load()
        self.assertEqual(img.size, (800, 480))

        # The event row carries the summary text; pick it out by content.
        calendar_rows = [(size, text) for size, text in drawn if 'Quarterly planning' in text]
        self.assertEqual(len(calendar_rows), 1, drawn)
        row_size, row_text = calendar_rows[0]

        self.assertGreaterEqual(row_size, CALENDAR_MIN_BODY_SIZE)
        self.assertLess(row_size, BODY_SIZE_LADDER[0],
                         "the long summary should have shrunk the row below the top rung")
        self.assertIn('…', row_text, "the over-long summary must be ellipsized, not just shrunk")


if __name__ == '__main__':
    unittest.main()
