"""Integration test: todo_list rendering path with only urlopen mocked."""

import json
import logging
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image, ImageChops

from trmnl_server import hass_client
from trmnl_server.components import render_dashboard_image
from trmnl_server.state import server_state

mock_logger = mock.Mock(spec=logging.Logger)

ITEMS = [
    {'summary': 'Buy milk', 'status': 'needs_action', 'uid': '1'},
    {'summary': 'Walk dog', 'status': 'needs_action', 'uid': '2'},
    {'summary': 'Done thing', 'status': 'completed', 'uid': '3'},
]


class _Resp:
    """Context-manager stand-in for urlopen's response."""

    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


class TestTodoListRenderIntegration(unittest.TestCase):
    """render_dashboard_image -> _fetch_todo_list -> draw, mocking only urlopen."""

    def setUp(self):
        server_state.reset_todo_pages()
        for patcher in (mock.patch.object(hass_client, 'HASS_URL', 'http://hass'),
                        mock.patch.object(hass_client, 'HASS_TOKEN', 'tok')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _render(self, items: list[dict]) -> Image.Image:
        dashboard = {
            'name': 'tasks', 'title': 'Tasks',
            'components': [{'type': 'todo_list', 'entity_name': 'todo.shop',
                            'friendly_name': 'Shopping'}],
        }
        body = {'changed_states': [], 'service_response': {'todo.shop': {'items': items}}}
        with mock.patch.object(hass_client, 'urlopen', return_value=_Resp(body)) as m:
            png = render_dashboard_image(dashboard, mock_logger)
        self.assertIn('/api/services/todo/get_items', m.call_args[0][0].full_url)
        return Image.open(png).convert('L')

    def test_items_from_service_response_are_rendered(self):
        """Items in the service response change the render versus an empty list."""
        with_items = self._render(ITEMS)
        empty = self._render([])
        self.assertIsNotNone(ImageChops.difference(with_items, empty).getbbox())

    def test_completed_items_are_not_drawn(self):
        """A list holding only completed items renders the same as an empty list."""
        done = [{'summary': 'Old', 'status': 'completed', 'uid': 'x'}]
        self.assertIsNone(ImageChops.difference(self._render(done), self._render([])).getbbox())
