"""Regression test: the bundled font must resolve to a real, loadable file.

Without this, a wrong NOTO_FONT path would be masked by the IOError ->
load_default() fallback in components._load_font, and the golden tests
(which generate baselines from whatever renders) would not catch it.
"""
import os
import unittest

from PIL import ImageFont

from trmnl_server.components import NOTO_FONT


class TestFontAsset(unittest.TestCase):
    def test_font_path_points_at_existing_file(self):
        """Bundled font file must exist at the path exported by components."""
        self.assertTrue(
            os.path.isfile(NOTO_FONT),
            f"Bundled font not found at {NOTO_FONT}",
        )

    def test_font_loads_without_fallback(self):
        """ImageFont.truetype must succeed and return a FreeTypeFont, not the bitmap fallback."""
        # Must not raise IOError (which would trigger the load_default fallback).
        font = ImageFont.truetype(NOTO_FONT, 20)
        self.assertIsInstance(font, ImageFont.FreeTypeFont)


if __name__ == "__main__":
    unittest.main()
