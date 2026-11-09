"""End-to-end test for the image component — real HTTP on both sides.

A localhost stand-in for Home Assistant serves a mid-grey PNG from the camera
proxy endpoint; this server's /static/<dashboard>.png route is then fetched
over HTTP and the final 1-bit PNG is inspected for a dither pattern.
"""

import http.server
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

HEADER_HEIGHT = 40  # render_dashboard_image's TOP_MARGIN


def _grey_png() -> bytes:
    buf = BytesIO()
    Image.new('L', (320, 240), 128).save(buf, 'PNG')
    return buf.getvalue()


class _FakeHomeAssistant(http.server.BaseHTTPRequestHandler):
    """Serves the PNG at the camera proxy path; fails when server.fail is set."""

    def do_GET(self):
        self.server.paths.append(self.path)
        self.server.auth.append(self.headers.get('Authorization'))
        if self.server.fail or self.path != '/api/camera_proxy/camera.front':
            self.send_response(500)
            self.end_headers()
            return
        body = _grey_png()
        self.send_response(200)
        self.send_header('Content-type', 'image/png')
        self.send_header('Content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def _black_fraction(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    region = img.convert('L').crop(box)
    return sum(1 for p in region.getdata() if p == 0) / (region.width * region.height)


class TestImageComponentEndToEnd(unittest.TestCase):
    """GET /static/<dash>.png -> HA camera proxy -> dithered 1-bit PNG."""

    def setUp(self):
        hass_client.reset_image_cache()
        self.tmp_dir = tempfile.mkdtemp()

        self.ha = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _FakeHomeAssistant)
        self.ha.paths, self.ha.auth, self.ha.fail = [], [], False
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
                "      - dashboard: cam\n"
                "      - dashboard: cam_rotated\n"
                "      - dashboard: cam_untitled\n"
                "dashboards:\n"
                "  - name: cam\n"
                "    title: Cam\n"
                "    components:\n"
                "      - type: image\n"
                "        entity_name: camera.front\n"
                "        friendly_name: Front door\n"
                "  - name: cam_rotated\n"
                "    rotate: 90\n"
                "    components:\n"
                "      - type: image\n"
                "        entity_name: camera.front\n"
                "        friendly_name: Front door\n"
                "  - name: cam_untitled\n"
                "    components:\n"
                "      - type: image\n"
                "        entity_name: camera.front\n"
                "        friendly_name: Front door\n"
                "        hide_title: true\n"
            )
        self._orig_config_path = os.environ.get('CONFIG_PATH')
        os.environ['CONFIG_PATH'] = self.config_path

        Handler = create_handler_class(getLogger('test_image_component_e2e'))
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
        hass_client.reset_image_cache()

    def _get(self, dashboard: str) -> Image.Image:
        url = f"http://127.0.0.1:{self.port}/static/AA-BB-CC-DD-EE-FF/{dashboard}.png"
        with urllib.request.urlopen(url, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            img = Image.open(BytesIO(resp.read()))
            img.load()
        return img

    def test_picture_is_dithered_in_final_png(self):
        """Mid-grey arrives as ~50% black dots in the body; token sent to HA."""
        img = self._get('cam')
        self.assertEqual(img.size, (800, 480))
        self.assertEqual(self.ha.paths, ['/api/camera_proxy/camera.front'])
        self.assertEqual(self.ha.auth, ['Bearer e2e-token'])
        frac = _black_fraction(img, (300, 200, 500, 400))
        self.assertGreater(frac, 0.3)
        self.assertLess(frac, 0.7)

    def test_rotated_dashboard_keeps_dither(self):
        """A rotate: 90 dashboard is 480x800 and the dots survive rotation."""
        img = self._get('cam_rotated')
        self.assertEqual(img.size, (480, 800))
        frac = _black_fraction(img, (100, 250, 300, 550))
        self.assertGreater(frac, 0.3)
        self.assertLess(frac, 0.7)

    def test_hide_title_starts_picture_near_top(self):
        """With hide_title the dithered picture reaches up to just below the header."""
        img = self._get('cam_untitled')
        frac = _black_fraction(img, (300, HEADER_HEIGHT + 15, 500, HEADER_HEIGHT + 45))
        self.assertGreater(frac, 0.3)

    def test_failed_fetch_shows_last_good_picture(self):
        """After HA starts failing, the next render still shows the dithered picture."""
        first = self._get('cam')
        self.ha.fail = True
        second = self._get('cam')
        self.assertEqual(len(self.ha.paths), 2)
        box = (0, HEADER_HEIGHT, 800, 480)
        self.assertEqual(first.crop(box).tobytes(), second.crop(box).tobytes())
