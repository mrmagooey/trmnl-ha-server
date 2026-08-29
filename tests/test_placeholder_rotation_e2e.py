"""End-to-end test for placeholder rotation — real HTTP, no mocking.

Drives /api/display for a device with nothing scheduled, then fetches the
placeholder image URL the server hands back, exactly as the firmware would.
The device is configured portrait, so the served "no dashboard scheduled"
image must come back rotated rather than landscape (which reads sideways or
upside down on a rotated device).
"""

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

from PIL import Image

from trmnl_server import api
from trmnl_server.server import create_handler_class


class TestPlaceholderRotationEndToEnd(unittest.TestCase):
    """Full HTTP round trip: /api/display -> placeholder image_url -> rotated PNG."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp_dir, "config.yaml")
        with open(self.config_path, "w") as f:
            f.write(
                "devices:\n"
                '  - id: "AA:BB:CC:DD:EE:FF"\n'
                "    rotate: 90\n"
                "    schedule:\n"
                "      - dashboard: morning\n"
                '        start_time: "07:00"\n'
                '        end_time: "07:01"\n'
                "dashboards:\n"
                "  - name: morning\n"
                "    components:\n"
                "      - type: entity\n"
                "        entity_name: sensor.temperature\n"
            )

        self._orig_config_path = os.environ.get("CONFIG_PATH")
        os.environ["CONFIG_PATH"] = self.config_path

        Handler = create_handler_class(getLogger("test_placeholder_rotation_e2e"))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._orig_server_name = api.SERVER_NAME
        api.SERVER_NAME = f"http://127.0.0.1:{self.port}"

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        api.SERVER_NAME = self._orig_server_name
        if self._orig_config_path is None:
            os.environ.pop("CONFIG_PATH", None)
        else:
            os.environ["CONFIG_PATH"] = self._orig_config_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_placeholder_served_rotated_for_rotated_device(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/display",
            headers={"ID": "AA:BB:CC:DD:EE:FF"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            display = json.loads(resp.read().decode())

        self.assertIn("no_dashboard_visible.png", display["image_url"])

        with urllib.request.urlopen(display["image_url"], timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            png_bytes = resp.read()

        with Image.open(BytesIO(png_bytes)) as img:
            self.assertEqual(img.size, (480, 800))


if __name__ == "__main__":
    unittest.main()
