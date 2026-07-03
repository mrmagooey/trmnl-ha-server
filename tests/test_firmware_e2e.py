"""End-to-end test for firmware update delivery — hits the real GitHub API.

No mocking: this test performs a real HTTP round trip through this server's
/api/display and /static/firmware routes, and independently re-fetches the
same GitHub release to verify the served bytes are byte-for-byte correct.

Target repo: cli/cli, not an official TRMNL firmware repo — as of writing,
none of the public TRMNL firmware repos publish binary release assets on
GitHub (their releases all have an empty "assets" list), so there is no real
firmware repo to test against. cli/cli's releases always include a small
"*_checksums.txt" asset, which exercises the identical release-lookup +
asset-download code path a real firmware repo would use. Uses `version:
"latest"` (not a pinned tag) so this test never goes stale.

Kept in its own file, separate from the rest of the (fully mocked) test
suite, since it is the only test here that depends on network access.
"""

import json
import os
import shutil
import socketserver
import tempfile
import threading
import unittest
import urllib.request
from logging import getLogger

from trmnl_server import api
from trmnl_server.server import create_handler_class


class TestFirmwareEndToEnd(unittest.TestCase):
    """Full HTTP round trip: /api/display -> firmware_url -> bytes match GitHub."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.tmp_dir, "cache")

        self.config_path = os.path.join(self.tmp_dir, "config.yaml")
        with open(self.config_path, "w") as f:
            f.write(
                "firmware:\n"
                "  repo: cli/cli\n"
                "  version: latest\n"
                '  asset_pattern: "*_checksums.txt"\n'
                "devices:\n"
                '  - id: "AA:BB:CC:DD:EE:FF"\n'
            )

        self._orig_cache_dir = api.FIRMWARE_CACHE_DIR
        self._orig_config_path = os.environ.get("CONFIG_PATH")
        api.FIRMWARE_CACHE_DIR = self.cache_dir
        os.environ["CONFIG_PATH"] = self.config_path

        Handler = create_handler_class(getLogger("test_firmware_e2e"))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._orig_server_name = api.SERVER_NAME
        api.SERVER_NAME = f"http://127.0.0.1:{self.port}"

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        api.FIRMWARE_CACHE_DIR = self._orig_cache_dir
        api.SERVER_NAME = self._orig_server_name
        if self._orig_config_path is None:
            os.environ.pop("CONFIG_PATH", None)
        else:
            os.environ["CONFIG_PATH"] = self._orig_config_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_display_then_firmware_download_matches_github(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/display",
            headers={"ID": "AA:BB:CC:DD:EE:FF", "FW-Version": "0.0.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            display = json.loads(resp.read().decode())

        self.assertTrue(display["update_firmware"])
        self.assertIsNotNone(display["firmware_url"])
        self.assertIn(f"http://127.0.0.1:{self.port}/static/firmware/", display["firmware_url"])

        with urllib.request.urlopen(display["firmware_url"], timeout=30) as resp:
            served_bytes = resp.read()

        # Independently resolve the same GitHub release to get ground truth.
        with urllib.request.urlopen(
            "https://api.github.com/repos/cli/cli/releases/latest", timeout=30
        ) as resp:
            release = json.loads(resp.read().decode())
        asset = next(a for a in release["assets"] if a["name"].endswith("_checksums.txt"))
        with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as resp:
            expected_bytes = resp.read()

        self.assertEqual(served_bytes, expected_bytes)
        self.assertGreater(len(served_bytes), 0)


if __name__ == "__main__":
    unittest.main()
