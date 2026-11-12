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


class TestTodoListEndToEnd(unittest.TestCase):
    """GET /static/<dash>.png -> HA todo.get_items -> 1-bit PNG."""

    def setUp(self):
        server_state.reset_todo_pages()
        self.tmp_dir = tempfile.mkdtemp()

        self.ha = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _FakeHomeAssistant)
        self.ha.requests, self.ha.gets = [], []
        threading.Thread(target=self.ha.serve_forever, daemon=True).start()
        ha_url = f"http://127.0.0.1:{self.ha.server_address[1]}"
        for patcher in (mock.patch.object(hass_client, 'HASS_URL', ha_url),
                        mock.patch.object(hass_client, 'HASS_TOKEN', 'e2e-token')):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.config_path = os.path.join(self.tmp_dir, 'config.yaml')
        with open(self.config_path, 'w') as f:
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
        self._orig_config_path = os.environ.get('CONFIG_PATH')
        os.environ['CONFIG_PATH'] = self.config_path

        Handler = create_handler_class(getLogger('test_todo_list_e2e'))
        self.httpd = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_address[1]
        self._orig_server_name = api.SERVER_NAME
        api.SERVER_NAME = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.ha.shutdown()
        self.ha.server_close()
        api.SERVER_NAME = self._orig_server_name
        if self._orig_config_path is None:
            os.environ.pop('CONFIG_PATH', None)
        else:
            os.environ['CONFIG_PATH'] = self._orig_config_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _get(self) -> Image.Image:
        url = f"http://127.0.0.1:{self.port}/static/AA-BB-CC-DD-EE-FF/shop.png"
        with urllib.request.urlopen(url, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            img = Image.open(BytesIO(resp.read()))
            img.load()
        return img

    def test_items_fetched_via_service_and_checkbox_is_solid(self):
        """HA gets one authenticated POST; two checkboxes are drawn with solid outlines."""
        img = self._get()
        self.assertEqual(img.mode, '1')
        self.assertEqual(img.size, (800, 480))
        self.assertEqual(
            self.ha.requests, [(GET_ITEMS_PATH, {'entity_id': 'todo.shop'}, 'Bearer e2e-token')]
        )
        self.assertEqual(self.ha.gets, [])

        gray = img.convert('L')
        # Find the longest vertical black run in the checkbox left-edge column;
        # a continuous outline is >= 24px tall. Two incomplete items -> two runs.
        runs: list[int] = []
        for x in range(10, 60):
            run = 0
            col_runs = []
            for y in range(gray.height):
                if gray.getpixel((x, y)) == 0:
                    run += 1
                else:
                    if run >= 24:
                        col_runs.append(run)
                    run = 0
            if len(col_runs) >= 2:
                runs = col_runs
                break
        self.assertGreaterEqual(len(runs), 2, "expected two solid checkbox outlines")

    def test_ha_failure_renders_without_items(self):
        """A failing service call renders an empty list rather than erroring."""
        with mock.patch.object(hass_client, 'HASS_URL', 'http://127.0.0.1:1'):
            img = self._get()
        self.assertEqual(img.size, (800, 480))
