"""End-to-end test for todo_list — real HTTP on both sides.

A localhost stand-in for Home Assistant implements the todo.get_items service
(POST) and fails every GET; this server's /static/<dashboard>.png route is then
fetched over HTTP and the 1-bit PNG is inspected for the rendered items and a
solid checkbox outline.
"""

import http.server
import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import unittest
import urllib.request
from io import BytesIO
from logging import getLogger
from unittest import mock

from PIL import Image

from trmnl_server import api, hass_client
from trmnl_server.server import create_handler_class
from trmnl_server.state import server_state

GET_ITEMS_PATH = '/api/services/todo/get_items?return_response'


class _FakeHomeAssistant(http.server.BaseHTTPRequestHandler):
    """Answers todo.get_items; every GET (e.g. /api/states/...) is a 500."""

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        self.server.requests.append(
            (self.path, json.loads(body or b'null'), self.headers.get('Authorization'))
        )
        if self.path != GET_ITEMS_PATH:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps({
            'changed_states': [],
            'service_response': {'todo.shop': {'items': [
                {'summary': 'Buy milk', 'status': 'needs_action', 'uid': '1'},
                {'summary': 'Walk dog', 'status': 'needs_action', 'uid': '2'},
                {'summary': 'Old chore', 'status': 'completed', 'uid': '3'},
            ]}},
        }).encode()
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Content-length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.server.gets.append(self.path)
        self.send_response(500)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _solid_runs(img: Image.Image, x: int, min_len: int) -> list[int]:
    """Lengths of black vertical runs of at least min_len pixels in column x."""
    gray = img.convert('L')
    runs: list[int] = []
    run = 0
    for y in range(gray.height + 1):
        if y < gray.height and gray.getpixel((x, y)) == 0:
            run += 1
        else:
            if run >= min_len:
                runs.append(run)
            run = 0
    return runs


class TestTodoListEndToEnd(unittest.TestCase):
    """GET /static/<dash>.png -> HA todo.get_items -> 1-bit PNG."""

    CHECKBOX_INSET = 15  # mirrors _draw_todo_list_component
    CHECKBOX_SIZE = 24

    def setUp(self):
        server_state.reset_todo_pages()
        self.addCleanup(server_state.reset_todo_pages)
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)

        self.ha = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _FakeHomeAssistant)
        self.addCleanup(self.ha.server_close)
        self.ha.requests, self.ha.gets = [], []
        threading.Thread(target=self.ha.serve_forever, daemon=True).start()
        self.addCleanup(self.ha.shutdown)
        self.ha_url = f"http://127.0.0.1:{self.ha.server_address[1]}"
        self._patch_ha(self.ha_url)
        token = mock.patch.object(hass_client, 'HASS_TOKEN', 'e2e-token')
        token.start()
        self.addCleanup(token.stop)

        config_path = os.path.join(tmp_dir, 'config.yaml')
        with open(config_path, 'w') as f:
            f.write(
                "devices:\n"
                '  - id: "AA:BB:CC:DD:EE:FF"\n'
                "    schedule:\n"
                "      - dashboard: shop\n"
                "dashboards:\n"
                "  - name: shop\n"
                "    title: Shop\n"
                "    components:\n"
                "      - type: todo_list\n"
                "        entity_name: todo.shop\n"
                "        friendly_name: Shopping\n"
            )
        env_patch = mock.patch.dict(os.environ, {'CONFIG_PATH': config_path})
        env_patch.start()
        self.addCleanup(env_patch.stop)

        Handler = create_handler_class(getLogger('test_todo_list_e2e'))
        self.httpd = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(self.httpd.server_close)
        self.port = self.httpd.server_address[1]
        server_name = mock.patch.object(api, 'SERVER_NAME', f"http://127.0.0.1:{self.port}")
        server_name.start()
        self.addCleanup(server_name.stop)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)

    def _patch_ha(self, url: str) -> None:
        patcher = mock.patch.object(hass_client, 'HASS_URL', url)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self) -> Image.Image:
        url = f"http://127.0.0.1:{self.port}/static/AA-BB-CC-DD-EE-FF/shop.png"
        with urllib.request.urlopen(url, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            img = Image.open(BytesIO(resp.read()))
            img.load()
        return img

    def test_items_fetched_via_service_and_checkbox_is_solid(self):
        """HA gets one authenticated POST; both outline columns of both checkboxes are solid."""
        img = self._get()
        self.assertEqual(img.mode, '1')
        self.assertEqual(img.size, (800, 480))
        self.assertEqual(
            self.ha.requests, [(GET_ITEMS_PATH, {'entity_id': 'todo.shop'}, 'Bearer e2e-token')]
        )
        self.assertEqual(self.ha.gets, [])

        # Two incomplete items -> two checkboxes. The outline is 2px wide, so
        # both left-edge columns must be solid for the whole checkbox height.
        for x in (self.CHECKBOX_INSET, self.CHECKBOX_INSET + 1):
            runs = _solid_runs(img, x, self.CHECKBOX_SIZE)
            self.assertEqual(len(runs), 2, f"column {x}: expected two solid outlines")

    def test_ha_failure_renders_no_items(self):
        """An unreachable HA renders the same as an empty list: no checkbox ink."""
        with socket.socket() as s:  # bind then close -> a port nothing listens on
            s.bind(('127.0.0.1', 0))
            dead_port = s.getsockname()[1]
        self._patch_ha(f"http://127.0.0.1:{dead_port}")
        img = self._get()
        self.assertEqual(img.size, (800, 480))
        self.assertEqual(_solid_runs(img, self.CHECKBOX_INSET, self.CHECKBOX_SIZE), [])
