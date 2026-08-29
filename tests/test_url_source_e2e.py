"""End-to-end test for the url data source — real HTTP, no mocking.

Serves a JSON body from a real localhost http.server, then drives this
server's /static/<dashboard>.png route to prove the value reaches a rendered
image. Synchronised on the fetch executor via _wait_for_pending() rather than
sleeps, so it cannot flake.
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

from PIL import Image

from trmnl_server import api, url_source
from trmnl_server.server import create_handler_class

# render_dashboard_image's local TOP_MARGIN (src/trmnl_server/components.py)
# — the header band holding a live HH:MM clock, title and battery icon, plus
# a separator line at TOP_MARGIN - 1. Not exported; duplicated here as a
# plain int rather than importing a private constant.
HEADER_HEIGHT = 40


class _CountingUpstreamHandler(http.server.BaseHTTPRequestHandler):
    """Serves a fixed JSON body and counts how many requests it received."""

    def do_GET(self):
        self.server.request_count += 1
        body = b'{"data": {"amount": "64231"}}'
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence request logging


def _panel_area(png_bytes: bytes) -> bytes:
    """Return raw pixels below the header band, which holds a live clock.

    The dashboard header renders the current HH:MM, so a whole-image byte
    comparison would differ across a minute boundary even if the panel
    content were identical. Assumes an unrotated dashboard, so the header
    stays at the top of the image (a rotated dashboard would need to crop a
    different edge).

    Args:
        png_bytes: Raw PNG bytes of a rendered dashboard.

    Returns:
        Raw pixel bytes of the image below the header band.
    """
    img = Image.open(BytesIO(png_bytes))
    return img.crop((0, HEADER_HEIGHT, img.width, img.height)).tobytes()


class TestUrlSourceEndToEnd(unittest.TestCase):
    """Full HTTP round trip: /static/<dashboard>.png -> upstream url -> rendered PNG."""

    def setUp(self):
        url_source.reset_cache()
        self.tmp_dir = tempfile.mkdtemp()

        self.upstream = socketserver.ThreadingTCPServer(
            ("127.0.0.1", 0), _CountingUpstreamHandler
        )
        self.upstream.request_count = 0
        self.upstream_port = self.upstream.server_address[1]
        self.upstream_thread = threading.Thread(
            target=self.upstream.serve_forever, daemon=True
        )
        self.upstream_thread.start()

        self.config_path = os.path.join(self.tmp_dir, "config.yaml")
        with open(self.config_path, "w") as f:
            f.write(
                "devices:\n"
                '  - id: "AA:BB:CC:DD:EE:FF"\n'
                "    schedule:\n"
                "      - dashboard: url_panel\n"
                "dashboards:\n"
                "  - name: url_panel\n"
                "    title: URL\n"
                "    components:\n"
                "      - type: url\n"
                "        friendly_name: Bitcoin\n"
                f'        url: "http://127.0.0.1:{self.upstream_port}/price"\n'
                '        json_path: ".data.amount"\n'
            )

        self._orig_config_path = os.environ.get("CONFIG_PATH")
        os.environ["CONFIG_PATH"] = self.config_path

        Handler = create_handler_class(getLogger("test_url_source_e2e"))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._orig_server_name = api.SERVER_NAME
        api.SERVER_NAME = f"http://127.0.0.1:{self.port}"

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        api.SERVER_NAME = self._orig_server_name
        if self._orig_config_path is None:
            os.environ.pop("CONFIG_PATH", None)
        else:
            os.environ["CONFIG_PATH"] = self._orig_config_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        url_source.reset_cache()

    def test_cold_then_warm_render_reflects_fetched_value(self):
        # Mirrors the real device path: device ID embedded in the URL, as
        # /api/display would hand back, rather than an anonymous request.
        dashboard_url = f"http://127.0.0.1:{self.port}/static/AA-BB-CC-DD-EE-FF/url_panel.png"

        with urllib.request.urlopen(dashboard_url, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            cold_bytes = resp.read()
        self.assertGreater(len(cold_bytes), 0)

        url_source._wait_for_pending()

        with urllib.request.urlopen(dashboard_url, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            warm_bytes = resp.read()
        self.assertGreater(len(warm_bytes), 0)

        # Compare panel pixels only (excludes the header's live clock) so
        # this can't pass merely because two requests straddled a minute
        # boundary — it must be the fetched value that changed the image.
        self.assertNotEqual(
            _panel_area(cold_bytes), _panel_area(warm_bytes),
            "warm render (with fetched value) must differ from the cold 'No data' render",
        )

        # A third render, still cache-served (no new upstream request),
        # must match the warm render's panel exactly. This rules out render
        # nondeterminism as the source of the cold/warm difference above:
        # the panel only changes when the underlying data changes.
        with urllib.request.urlopen(dashboard_url, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            repeat_bytes = resp.read()
        self.assertEqual(
            _panel_area(warm_bytes), _panel_area(repeat_bytes),
            "a stable cache-served value must render identical panel pixels",
        )

        self.assertEqual(
            self.upstream.request_count, 1,
            "the cache should have prevented a second upstream request",
        )


if __name__ == "__main__":
    unittest.main()
