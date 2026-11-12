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

    def _render(self) -> Image.Image:
        dashboard = {
            'name': 'tasks', 'title': 'Tasks',
            'components': [{'type': 'todo_list', 'entity_name': 'todo.shop',
                            'friendly_name': 'Shopping'}],
        }
        body = {'changed_states': [], 'service_response': {'todo.shop': {'items': ITEMS}}}
        with mock.patch.object(hass_client, 'urlopen', return_value=_Resp(body)) as m:
            png = render_dashboard_image(dashboard, mock_logger)
        self.assertIn('/api/services/todo/get_items', m.call_args[0][0].full_url)
        return Image.open(png).convert('L')

    def test_items_from_service_response_are_rendered(self):
        """Items from the service response produce ink in the rendered body."""
        rendered = self._render()
        # The tile sits under the header; some ink must exist in the body area.
        body = rendered.crop((0, 40, 800, 480))
        self.assertIsNotNone(ImageChops.invert(body).getbbox())
        self.assertGreater(sum(1 for p in body.getdata() if p == 0), 100)

    def test_different_items_render_differently(self):
        """Changing the service response changes the image (items really drive output)."""
        first = self._render()
        body = {'changed_states': [], 'service_response': {'todo.shop': {'items': []}}}
        dashboard = {
            'name': 'tasks', 'title': 'Tasks',
            'components': [{'type': 'todo_list', 'entity_name': 'todo.shop',
                            'friendly_name': 'Shopping'}],
        }
        with mock.patch.object(hass_client, 'urlopen', return_value=_Resp(body)):
            second = Image.open(render_dashboard_image(dashboard, mock_logger)).convert('L')
        self.assertIsNotNone(ImageChops.difference(first, second).getbbox())
