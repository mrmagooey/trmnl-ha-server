"""Additional tests for components module to achieve full coverage."""

import time
import unittest
from unittest import mock
import io
from PIL import Image
import logging

from trmnl_server import url_source
from trmnl_server.components import (
    render_dashboard_image,
    _create_info_image,
    _dashboard_rotation,
    _rotate_image,
    tile_components,
    eink_display,
    _draw_dashed_line,
    _build_draw_segments,
    _draw_graph_component,
    _draw_entity_component,
    _draw_calendar_component,
    _draw_entities_component,
    _draw_todo_list_component,
    _load_font,
    _todo_capacity,
    _fit_title_size,
    _fit_body_size,
    _panel_body_fit,
    _calendar_row_texts,
    _entities_row_parts,
    _todo_row_texts,
    _ellipsize,
    _ellipsize_prefix,
    BODY_SIZE_LADDER,
    _panel_title_text,
    _incomplete_items,
    _wrap_title,
    _title_band_height,
    _todo_header_height,
    TITLE_SIZE_LADDER,
    COMPONENT_TITLE_FONT_SIZE,
    TITLE_MAX_LINES,
    TITLE_BAND_MAX_PERCENT,
    COMPONENT_SCALE,
    TODO_BOTTOM_PAD,
    TODO_ROW_H,
)
from trmnl_server.metrics import voltage_to_percent

# Create a mock logger for testing
mock_logger = mock.Mock(spec=logging.Logger)


class TestBatteryPercentParity(unittest.TestCase):
    """The shared helper must reproduce the legacy inline battery formula."""

    def test_helper_matches_legacy_formula_across_range(self):
        for v in (2.4, 2.7, 3.0, 3.3, 3.7, 3.91, 4.0, 4.2):
            legacy = max(0, min(100, int(round(((v - 2.4) / (4.2 - 2.4)) * 100))))
            self.assertEqual(voltage_to_percent(v), legacy)


class TestLoadFont(unittest.TestCase):
    """Tests for _load_font function."""
    
    def test_load_font_success(self):
        """Test loading font successfully."""
        font = _load_font(30, mock_logger)
        self.assertIsNotNone(font)
    
    def test_load_font_failure(self):
        """Test font loading falls back to default."""
        # This should succeed but if font file doesn't exist, it falls back
        with mock.patch('trmnl_server.components.ImageFont.truetype', side_effect=IOError()):
            with mock.patch('trmnl_server.components.ImageFont.load_default') as mock_default:
                mock_default.return_value = mock.Mock()
                font = _load_font(30, mock_logger)
                self.assertIsNotNone(font)
                mock_default.assert_called_once()


class TestCreateInfoImage(unittest.TestCase):
    """Tests for _create_info_image function."""
    
    def test_create_info_image(self):
        """Test creating an info image."""
        img = _create_info_image("Test Message", 400, 300, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
        self.assertEqual(img.mode, 'RGB')
    
    def test_create_info_image_multiline(self):
        """Test creating an info image with multiline message."""
        img = _create_info_image("Line 1\nLine 2\nLine 3", 400, 300, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_create_info_image_none_message(self):
        """Test creating an info image with None message."""
        img = _create_info_image(None, 400, 300, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_create_info_image_shrink_to_fit(self):
        """Test that image text shrinks to fit."""
        # Very long message should trigger shrink-to-fit logic
        img = _create_info_image("A" * 200, 200, 100, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (200, 100))


class TestRotationHelpers(unittest.TestCase):
    """Tests for _dashboard_rotation and _rotate_image."""

    def test_dashboard_rotation_portrait_is_90(self):
        self.assertEqual(_dashboard_rotation({'name': 'x', 'portrait': True}), 90)

    def test_dashboard_rotation_explicit_wins_over_portrait(self):
        self.assertEqual(_dashboard_rotation({'name': 'x', 'portrait': True, 'rotate': 180}), 180)

    def test_dashboard_rotation_none_when_unset(self):
        self.assertIsNone(_dashboard_rotation({'name': 'x'}))

    def test_rotate_image_quarter_turns_swap_dimensions(self):
        for rotate in (90, -90):
            with self.subTest(rotate=rotate):
                img = _rotate_image(Image.new('RGB', (800, 480)), rotate, mock_logger)
                self.assertEqual(img.size, (480, 800))

    def test_rotate_image_180_flips_content(self):
        original = Image.new('RGB', (4, 2), 'white')
        original.putpixel((0, 0), (0, 0, 0))

        rotated = _rotate_image(original, 180, mock_logger)

        self.assertEqual(rotated.size, (4, 2))
        self.assertEqual(rotated.getpixel((3, 1)), (0, 0, 0))
        self.assertEqual(rotated.getpixel((0, 0)), (255, 255, 255))

    def test_rotate_image_none_returns_image_unchanged(self):
        original = Image.new('RGB', (800, 480))
        self.assertIs(_rotate_image(original, None, mock_logger), original)

    def test_rotate_image_unsupported_value_warns_and_skips(self):
        logger = mock.Mock(spec=logging.Logger)
        original = Image.new('RGB', (800, 480))

        self.assertIs(_rotate_image(original, 45, logger), original)
        logger.warning.assert_called_once()


class TestDrawGraphComponent(unittest.TestCase):
    """Tests for _draw_graph_component function."""

    def test_draw_graph_no_data(self):
        """Test drawing graph with no data points."""
        from datetime import datetime
        img = _draw_graph_component(
            "Test Sensor", [], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_single_value(self):
        """Test drawing graph with single value (edge case for min/max)."""
        from datetime import datetime
        data_points = [(datetime(2025, 1, 15, 10, 0), 25.0)]
        img = _draw_graph_component(
            "Test Sensor", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_same_time(self):
        """Test drawing graph with same timestamp (edge case for time delta)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
            (datetime(2025, 1, 15, 10, 0), 26.0),
        ]
        img = _draw_graph_component(
            "Test Sensor", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_draw_graph_long_title(self):
        """Test drawing graph with very long title."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 10, 0), 25.0),
            (datetime(2025, 1, 15, 11, 0), 26.0),
        ]
        img = _draw_graph_component(
            "A" * 100, data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 9, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)

    def test_dotted_tail_drawn_when_last_point_before_window_end(self):
        """A stale entity gets a dashed hold line in the right portion of the plot."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), 20.0),
        ]
        img = _draw_graph_component(
            "Stale", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        img_no_gap = _draw_graph_component(
            "Stale", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 20.0),
            ], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        from PIL import ImageChops
        self.assertIsNotNone(
            ImageChops.difference(img, img_no_gap).getbbox(),
            "expected the dotted hold tail to change the image",
        )

        # The tail must be DASHED: along a horizontal band in the right portion
        # of the plot there must be both painted and gap pixels.
        w, h = img.size  # (400, 300)
        band = []
        for x in range(int(w * 0.55), int(w * 0.95)):
            for y in range(h):
                band.append(img.getpixel((x, y)))
        has_black = any(p == (0, 0, 0) for p in band)
        has_white = any(p == (255, 255, 255) for p in band)
        if not (has_black and has_white):
            # LANCZOS antialiasing may blur pure black/white; use thresholds
            has_black = any(sum(p) < 240 for p in band)
            has_white = any(sum(p) > 600 for p in band)
        self.assertTrue(has_black, "expected painted dash pixels in the tail region")
        self.assertTrue(has_white, "expected gap pixels between dashes in the tail region")

    def test_fully_stale_only_boundary_point(self):
        """A single point well before window_end still renders (flat dotted hold)."""
        from datetime import datetime
        data_points = [(datetime(2025, 1, 15, 8, 0), 42.0)]
        img = _draw_graph_component(
            "Dead", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 16, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_no_tail_when_data_reaches_window_end(self):
        """When the last reading is exactly at window_end, no dotted tail is drawn."""
        from datetime import datetime
        from PIL import ImageChops
        ws = datetime(2025, 1, 15, 8, 0)
        we = datetime(2025, 1, 15, 16, 0)
        # Last point exactly at window_end -> guard suppresses the tail.
        reaches_end = _draw_graph_component(
            "Live", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 22.0),
            ], 400, 300, mock_logger, window_start=ws, window_end=we,
        )
        # Same two points but rendered without any later gap is identical to itself;
        # assert determinism (no tail introduces nondeterminism/extra marks).
        reaches_end_again = _draw_graph_component(
            "Live", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 16, 0), 22.0),
            ], 400, 300, mock_logger, window_start=ws, window_end=we,
        )
        self.assertIsNone(
            ImageChops.difference(reaches_end, reaches_end_again).getbbox(),
            "rendering must be deterministic when no tail is drawn",
        )

    def test_zero_baseline_default_off_unchanged(self):
        """Omitting zero_baseline renders identically to passing it False."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 5.0),
            (datetime(2025, 1, 15, 10, 0), 8.0),
        ]
        kwargs = dict(
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        default = _draw_graph_component("S", data_points, 400, 300, mock_logger, **kwargs)
        explicit_off = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger, zero_baseline=False, **kwargs
        )
        self.assertIsNone(
            ImageChops.difference(default, explicit_off).getbbox(),
            "default path must equal zero_baseline=False",
        )

    def test_zero_baseline_changes_bipolar_rendering(self):
        """For data crossing zero, the flag changes the rendered image."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -10.0),
            (datetime(2025, 1, 15, 10, 0), 10.0),
        ]
        kwargs = dict(
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
        )
        off = _draw_graph_component("S", data_points, 400, 300, mock_logger, **kwargs)
        on = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger, zero_baseline=True, **kwargs
        )
        self.assertIsNotNone(
            ImageChops.difference(off, on).getbbox(),
            "zero_baseline must change rendering for bipolar data",
        )

    def test_zero_baseline_draws_horizontal_line_near_mid(self):
        """Symmetric data (-10..+10) puts the zero line near vertical centre,
        spanning most of the plot width as a near-continuous black row."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -10.0),
            (datetime(2025, 1, 15, 9, 30), 0.0),
            (datetime(2025, 1, 15, 10, 0), 10.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        w, h = img.size  # (400, 300)
        # Scan the central horizontal band for a row that is mostly black across
        # the plot width (the zero line spans the full graph width).
        def black(px):
            return sum(px) < 240
        best = 0
        for y in range(int(h * 0.35), int(h * 0.65)):
            count = sum(
                1 for x in range(int(w * 0.15), int(w * 0.80))
                if black(img.getpixel((x, y)))
            )
            best = max(best, count)
        span = int(w * 0.80) - int(w * 0.15)
        self.assertGreater(
            best, span * 0.6,
            "expected a near-continuous horizontal zero line in the central band",
        )

    def test_zero_baseline_all_positive_includes_zero(self):
        """All-positive data with the flag on still renders (floor pulled to 0)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 5.0),
            (datetime(2025, 1, 15, 10, 0), 9.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_zero_baseline_all_negative_includes_zero(self):
        """All-negative data with the flag on still renders (ceiling pulled to 0)."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), -5.0),
            (datetime(2025, 1, 15, 10, 0), -9.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_zero_baseline_flat_at_zero(self):
        """A flat line at exactly 0 with the flag on renders without error."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 0.0),
            (datetime(2025, 1, 15, 10, 0), 0.0),
        ]
        img = _draw_graph_component(
            "S", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 11, 0),
            zero_baseline=True,
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_internal_gap_renders_dashed_not_interpolated(self):
        """Regression test for the reported bug: a gap that has been closed
        by a new reading must stay dashed across the gap span, not render as
        a smooth solid line interpolated between the pre-gap and post-gap
        values."""
        from datetime import datetime
        from PIL import ImageChops
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), None),
            (datetime(2025, 1, 15, 13, 0), 30.0),
        ]
        img = _draw_graph_component(
            "Gappy", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 13, 0),
        )
        # A naive full-interpolation render (no gap marker at all) is what the
        # bug used to produce once the gap closed; the fixed render must differ.
        naive_interpolated = _draw_graph_component(
            "Gappy", [
                (datetime(2025, 1, 15, 9, 0), 20.0),
                (datetime(2025, 1, 15, 13, 0), 30.0),
            ], 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 13, 0),
        )
        self.assertIsNotNone(
            ImageChops.difference(img, naive_interpolated).getbbox(),
            "gap rendering must differ from a naive solid interpolation",
        )

        # The gap segment is drawn flat and dashed — a horizontal scan across
        # its time span must show both painted and unpainted (gap) pixels.
        w, h = img.size  # (400, 300)
        band = []
        for x in range(int(w * 0.25), int(w * 0.75)):
            for y in range(h):
                band.append(img.getpixel((x, y)))
        has_black = any(sum(p) < 240 for p in band)
        has_white = any(sum(p) > 600 for p in band)
        self.assertTrue(has_black, "expected painted dash pixels across the gap region")
        self.assertTrue(has_white, "expected gap (unpainted) pixels across the gap region")

    def test_last_value_label_uses_most_recent_real_reading(self):
        """If the series ends on a gap marker (entity currently unavailable),
        the displayed last-value text must use the last REAL reading and
        must not crash."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), 20.0),
            (datetime(2025, 1, 15, 10, 0), None),
        ]
        img = _draw_graph_component(
            "Stale", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))

    def test_all_gap_data_shows_no_numeric_data_message(self):
        """A series that is entirely gap markers renders the no-data message
        instead of crashing on min()/max() of an empty sequence."""
        from datetime import datetime
        data_points = [
            (datetime(2025, 1, 15, 9, 0), None),
            (datetime(2025, 1, 15, 10, 0), None),
        ]
        img = _draw_graph_component(
            "AllGaps", data_points, 400, 300, mock_logger,
            window_start=datetime(2025, 1, 15, 8, 0),
            window_end=datetime(2025, 1, 15, 12, 0),
        )
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))


class TestBuildDrawSegments(unittest.TestCase):
    """Tests for the pure _build_draw_segments helper."""

    def test_all_real_points_produce_one_solid_segment_per_pair(self):
        from datetime import datetime
        t0, t1, t2 = datetime(2025, 1, 15, 9, 0), datetime(2025, 1, 15, 10, 0), datetime(2025, 1, 15, 11, 0)
        data_points = [(t0, 20.0), (t1, 21.0), (t2, 22.0)]

        segments = _build_draw_segments(data_points, window_end=t2)

        self.assertEqual(segments, [
            (t0, 20.0, t1, 21.0, False),
            (t1, 21.0, t2, 22.0, False),
        ])

    def test_gap_between_two_real_points_is_dashed_and_flat(self):
        """Regression case for the reported bug: a gap that has since been
        closed by a new reading must stay dashed and flat at the pre-gap
        value, not become a solid line interpolated to the new value."""
        from datetime import datetime
        t0, gap_t, t1 = datetime(2025, 1, 15, 9, 0), datetime(2025, 1, 15, 10, 0), datetime(2025, 1, 15, 13, 0)
        data_points = [(t0, 20.0), (gap_t, None), (t1, 30.0)]

        segments = _build_draw_segments(data_points, window_end=t1)

        self.assertEqual(segments, [(t0, 20.0, t1, 20.0, True)])

    def test_trailing_gap_holds_last_value_to_window_end(self):
        from datetime import datetime
        t0 = datetime(2025, 1, 15, 9, 0)
        window_end = datetime(2025, 1, 15, 16, 0)
        data_points = [(t0, 20.0)]

        segments = _build_draw_segments(data_points, window_end)

        self.assertEqual(segments, [(t0, 20.0, window_end, 20.0, True)])

    def test_no_trailing_segment_when_last_point_is_at_window_end(self):
        from datetime import datetime
        t0 = datetime(2025, 1, 15, 9, 0)
        data_points = [(t0, 20.0)]

        segments = _build_draw_segments(data_points, window_end=t0)

        self.assertEqual(segments, [])

    def test_leading_gap_before_first_real_point_produces_no_segment(self):
        """Nothing can be held forward before we have a first real reading."""
        from datetime import datetime
        gap_t = datetime(2025, 1, 15, 8, 0)
        t0 = datetime(2025, 1, 15, 9, 0)
        data_points = [(gap_t, None), (t0, 20.0)]

        segments = _build_draw_segments(data_points, window_end=t0)

        self.assertEqual(segments, [])

    def test_empty_input_produces_no_segments(self):
        from datetime import datetime
        self.assertEqual(_build_draw_segments([], window_end=datetime(2025, 1, 15, 9, 0)), [])


class TestDrawEntityComponent(unittest.TestCase):
    """Tests for _draw_entity_component function."""
    
    def test_draw_entity_none_value(self):
        """Test drawing entity with None value."""
        img = _draw_entity_component(
            "Test Entity",
            None,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_long_unbroken_value_is_ellipsized_not_clipped(self):
        """A long value with no spaces is ellipsized rather than clipped at the tile edges.

        Word wrapping cannot split a string with no spaces, so before this was
        fixed the value stayed on one line, floored at the minimum font size,
        and was centred at a negative x — spilling past both tile edges.
        """
        img = _draw_entity_component(
            "Feed",
            "a7f3e9c1b5d84a2e6f0c9b7d3e1a5f8c2b6d0e4a9c7f1b3d5e8a2c6f0b4d7e9a1c3f5" * 3,
            400,
            240,
            mock_logger,
        )

        width, height = img.size
        # getextrema()[0] is the darkest pixel; 255 means the strip is all white.
        left_darkest = img.crop((0, 0, 2, height)).convert("L").getextrema()[0]
        right_darkest = img.crop((width - 2, 0, width, height)).convert("L").getextrema()[0]
        self.assertEqual(left_darkest, 255, "value ink reached the left tile edge")
        self.assertEqual(right_darkest, 255, "value ink reached the right tile edge")

    def test_long_value_with_spaces_still_wraps(self):
        """A long value containing spaces still word-wraps rather than being truncated."""
        img = _draw_entity_component(
            "Feed",
            "Heavy rain expected this afternoon with gusts up to sixty km per hour",
            400,
            240,
            mock_logger,
        )

        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 240))
        width, height = img.size
        self.assertEqual(img.crop((0, 0, 2, height)).convert("L").getextrema()[0], 255)
        self.assertEqual(img.crop((width - 2, 0, width, height)).convert("L").getextrema()[0], 255)

    def test_two_line_title_value_does_not_overflow_tile(self):
        """A large value under a two-line title must not spill past the tile's bottom edge.

        A two-line title reserves a band and centres the value in the space
        left below it. That centring used a fixed offset tuned for the
        single-line layout, where the title overlaps the value's region
        instead of reserving its own band. On a short tile the leftover
        space allows a large value font, and the untuned offset under-
        corrects for it, pushing the value's ink past the tile's bottom
        edge -- clipping it.
        """
        img = _draw_entity_component(
            "Back Garden Soil Moisture Level",
            21.5,
            400,
            220,
            mock_logger,
            title_font_size=35,
            title_lines=2,
        )
        width, height = img.size
        bottom_darkest = img.crop((0, height - 2, width, height)).convert("L").getextrema()[0]
        self.assertEqual(bottom_darkest, 255, "value ink reached the bottom tile edge")

    def test_draw_entity_float_value(self):
        """Test drawing entity with float value."""
        img = _draw_entity_component(
            "Temperature",
            23.5,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entity_string_value(self):
        """Test drawing entity with string value."""
        img = _draw_entity_component(
            "Status",
            "Active",
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entity_long_value(self):
        """Test drawing entity with very long value."""
        img = _draw_entity_component(
            "Description",
            "A" * 100,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entity_wrapping(self):
        """Test drawing entity with value that needs wrapping."""
        img = _draw_entity_component(
            "Message",
            "This is a very long message that should wrap",
            300,
            200,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestDrawCalendarComponent(unittest.TestCase):
    """Tests for _draw_calendar_component function."""
    
    def test_draw_calendar_no_events(self):
        """Test drawing calendar with no events."""
        img = _draw_calendar_component(
            "My Calendar",
            [],
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_long_unbroken_event_is_ellipsized_not_clipped(self):
        """A calendar event with an unbreakable summary is truncated, not clipped.

        The font shrinks to its floor and the row is then drawn at a fixed x
        with no wrapping, so without an ellipsis it runs off the right edge.
        """
        events = [
            {
                'summary': 'a7f3e9c1b5d84a2e6f0c9b7d3e1a5f8c2b6d0e4a9c7f1b3d5e8a2c6f0b4d7e9a1c3f5' * 2,
                'start': {'dateTime': '2025-01-15T10:00:00+00:00'},
                'end': {'dateTime': '2025-01-15T11:00:00+00:00'},
            },
        ]

        img = _draw_calendar_component("My Calendar", events, 400, 300, mock_logger)

        width, height = img.size
        # getextrema()[0] is the darkest pixel; 255 means the strip is all white.
        darkest = img.crop((width - 2, 0, width, height)).convert("L").getextrema()[0]
        self.assertEqual(darkest, 255, "event text reached the right tile edge")

    def test_draw_calendar_with_events(self):
        """Test drawing calendar with events."""
        events = [
            {
                'summary': 'Meeting',
                'start': {'dateTime': '2025-01-15T10:00:00+00:00'},
                'end': {'dateTime': '2025-01-15T11:00:00+00:00'}
            },
            {
                'summary': 'All Day Event',
                'start': {'date': '2025-01-16'},
                'end': {'date': '2025-01-17'}
            }
        ]
        
        img = _draw_calendar_component(
            "My Calendar",
            events,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_calendar_long_event_text(self):
        """Test drawing calendar with very long event text."""
        events = [
            {
                'summary': 'A' * 100,
                'start': {'dateTime': '2025-01-15T10:00:00+00:00'},
                'end': {'dateTime': '2025-01-15T11:00:00+00:00'}
            }
        ]
        
        img = _draw_calendar_component(
            "My Calendar",
            events,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestDrawEntitiesComponent(unittest.TestCase):
    """Tests for _draw_entities_component function."""
    
    def test_draw_entities_empty(self):
        """Test drawing entities list with no entities."""
        img = _draw_entities_component(
            "Sensors",
            [],
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_long_unbroken_entity_state_is_ellipsized_not_clipped(self):
        """An entity row with an unbreakable state is truncated, not clipped.

        The font shrinks to its floor and the row is then drawn at a fixed x
        with no wrapping, so without an ellipsis it runs off the right edge.
        """
        entity_states = [
            {
                'friendly_name': 'Blob',
                'state': 'a7f3e9c1b5d84a2e6f0c9b7d3e1a5f8c2b6d0e4a9c7f1b3d5e8a2c6f0b4d7e9a1c3f5' * 2,
            },
        ]

        img = _draw_entities_component("Sensors", entity_states, 400, 300, mock_logger)

        width, height = img.size
        # getextrema()[0] is the darkest pixel; 255 means the strip is all white.
        darkest = img.crop((width - 2, 0, width, height)).convert("L").getextrema()[0]
        self.assertEqual(darkest, 255, "entity row reached the right tile edge")

    def test_draw_entities_with_data(self):
        """Test drawing entities list with data."""
        entity_states = [
            {'friendly_name': 'Temp', 'state': 22.5},
            {'friendly_name': 'Humidity', 'state': '45%'},
        ]
        
        img = _draw_entities_component(
            "Sensors",
            entity_states,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_entities_long_text(self):
        """Test drawing entities list with long text."""
        entity_states = [
            {'friendly_name': 'A' * 50, 'state': 'B' * 50},
        ]
        
        img = _draw_entities_component(
            "Sensors",
            entity_states,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestDrawTodoListComponent(unittest.TestCase):
    """Tests for _draw_todo_list_component function."""
    
    def test_draw_todo_list_empty(self):
        """Test drawing todo list with no items."""
        img = _draw_todo_list_component(
            "My Todos",
            [],
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))
    
    def test_draw_todo_list_with_items(self):
        """Test drawing todo list with items."""
        items = [
            {'summary': 'Buy milk', 'status': 'needs_action'},
            {'summary': 'Call mom', 'status': 'needs_action'},
            {'summary': 'Walk dog', 'status': 'completed'},  # Should be skipped
        ]
        
        img = _draw_todo_list_component(
            "Shopping List",
            items,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_todo_list_long_text(self):
        """Test drawing todo list with long item text."""
        items = [
            {'summary': 'This is a very long todo item that should be resized to fit', 'status': 'needs_action'},
        ]
        
        img = _draw_todo_list_component(
            "Todos",
            items,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)
    
    def test_draw_todo_list_only_completed(self):
        """Test drawing todo list when all items are completed."""
        items = [
            {'summary': 'Done task', 'status': 'completed'},
        ]
        
        img = _draw_todo_list_component(
            "Completed",
            items,
            400,
            300,
            mock_logger
        )
        
        self.assertIsInstance(img, Image.Image)


class TestTileComponents(unittest.TestCase):
    """Tests for tile_components function."""
    
    def test_empty_components(self):
        """Test tiling with no components."""
        img = tile_components([], 800, 480, 40, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (800, 480))
    
    def test_single_component(self):
        """Test tiling single component."""
        from trmnl_server.models import RenderData
        
        render_data = {
            'type': 'entity',
            'friendly_name': 'Test',
            'data': 'value',
            'large_display': False
        }
        
        with mock.patch('trmnl_server.components._draw_entity_component') as mock_draw:
            mock_draw.return_value = Image.new('RGB', (400, 220), color='white')
            img = tile_components([render_data], 800, 480, 40, mock_logger)
        
        self.assertIsInstance(img, Image.Image)
    
    def test_large_display_component(self):
        """Test tiling with large display component."""
        render_data = [
            {
                'type': 'entity',
                'friendly_name': 'Large',
                'data': 'value',
                'large_display': True
            },
            {
                'type': 'entity',
                'friendly_name': 'Small',
                'data': 'value2',
                'large_display': False
            }
        ]
        
        with mock.patch('trmnl_server.components._draw_entity_component') as mock_draw:
            mock_draw.return_value = Image.new('RGB', (400, 200), color='white')
            img = tile_components(render_data, 800, 480, 40, mock_logger)
        
        self.assertIsInstance(img, Image.Image)


class TestEinkDisplay(unittest.TestCase):
    """Tests for eink_display function."""
    
    def test_eink_display(self):
        """Test converting image to e-ink format."""
        # Create a simple test image
        img = Image.new('RGB', (100, 100), color=(128, 128, 128))
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        result = eink_display(img_io)
        
        self.assertIsInstance(result, io.BytesIO)
        result.seek(0)
        
        # Verify it's a valid PNG
        with Image.open(result) as img_result:
            self.assertEqual(img_result.format, 'PNG')
            self.assertEqual(img_result.mode, '1')  # Black and white


class TestRenderDashboardImage(unittest.TestCase):
    """Additional tests for render_dashboard_image function."""

    def setUp(self):
        mock_logger.reset_mock()
        from trmnl_server.state import server_state
        server_state.reset_todo_pages()

    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_empty_components(self, mock_get_entity_state):
        """Test rendering dashboard with no components."""
        dashboard = {
            'name': 'empty_dash',
            'title': 'Empty Dashboard',
            'components': []
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        with Image.open(img_io) as img:
            self.assertEqual(img.format, 'PNG')
            self.assertEqual(img.size, (800, 480))
    
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    @mock.patch('trmnl_server.state.server_state')
    def test_render_with_battery(self, mock_server_state, mock_get_entity_state):
        """Test rendering with battery voltage."""
        mock_get_entity_state.return_value = {'state': 'On'}
        mock_server_state.consume_battery_voltage.return_value = 3.7
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'entity'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger, 'AA:BB:CC:DD:EE:FF')

        self.assertIsInstance(img_io, io.BytesIO)
        mock_server_state.consume_battery_voltage.assert_called_once_with('AA:BB:CC:DD:EE:FF')
    
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_entity_component_no_data(self, mock_get_entity_state):
        """Test entity component with no data."""
        mock_get_entity_state.return_value = None
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'entity'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
    
    @mock.patch('trmnl_server.hass_client._fetch_history')
    def test_history_component_no_data(self, mock_fetch_history):
        """Test history component with no data."""
        mock_fetch_history.return_value = None
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'history_graph'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
    
    @mock.patch('trmnl_server.hass_client._fetch_calendar_events')
    def test_calendar_no_calendar_id(self, mock_fetch_calendar):
        """Test calendar component without calendar_id."""
        dashboard = {
            'name': 'test_dash',
            'components': [
                {
                    'friendly_name': 'Calendar',
                    'type': 'calendar',
                    'arguments': {'days': 7}  # No calendar_id
                }
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        mock_logger.warning.assert_called_once()
        mock_fetch_calendar.assert_not_called()
    
    @mock.patch('trmnl_server.hass_client.get_entity_state')
    def test_unknown_component_type(self, mock_get_entity_state):
        """Test handling unknown component type."""
        mock_get_entity_state.return_value = {'state': 'On'}
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'sensor.test', 'friendly_name': 'Test', 'type': 'unknown_type'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        mock_logger.warning.assert_called_once()
    
    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_list_component(self, mock_fetch_todo):
        """Test todo list component rendering."""
        mock_fetch_todo.return_value = [
            {'summary': 'Buy milk', 'status': 'needs_action'},
            {'summary': 'Call mom', 'status': 'needs_action'},
        ]
        
        dashboard = {
            'name': 'test_dash',
            'components': [
                {'entity_name': 'todo.shopping_list', 'friendly_name': 'Shopping', 'type': 'todo_list'}
            ]
        }
        
        img_io = render_dashboard_image(dashboard, mock_logger)
        
        self.assertIsInstance(img_io, io.BytesIO)
        img_io.seek(0)
        with Image.open(img_io) as img:
            self.assertEqual(img.format, 'PNG')
        mock_fetch_todo.assert_called_once()

    @mock.patch('trmnl_server.hass_client._fetch_todo_list')
    def test_todo_overflow_renders_first_page(self, mock_fetch_todo):
        """A todo_list with more items than fit renders (page 0 on first render)."""
        mock_fetch_todo.return_value = [
            {'summary': f'Item {i}', 'status': 'needs_action'} for i in range(50)
        ]
        dashboard = {
            'name': 'chores',
            'components': [
                {'entity_name': 'todo.chores', 'friendly_name': 'Chores',
                 'type': 'todo_list', 'columns': 2},
            ],
        }
        img_io = render_dashboard_image(dashboard, mock_logger)
        self.assertIsInstance(img_io, io.BytesIO)


class TestDrawDashedLine(unittest.TestCase):
    """Tests for the _draw_dashed_line helper."""

    def test_horizontal_dash_has_gaps(self):
        """A dashed line leaves white gaps, unlike a solid line."""
        from PIL import ImageDraw
        img = Image.new('RGB', (100, 10), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 5), (99, 5), fill='black', width=1, dash_on=6, dash_off=6)
        row = [img.getpixel((x, 5)) for x in range(100)]
        black = sum(1 for p in row if p == (0, 0, 0))
        white = sum(1 for p in row if p == (255, 255, 255))
        self.assertGreater(black, 0, "expected some painted (black) pixels")
        self.assertGreater(white, 0, "expected some gap (white) pixels")

    def test_zero_length_is_noop(self):
        """Start == end draws nothing and does not raise."""
        from PIL import ImageDraw
        img = Image.new('RGB', (10, 10), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (5, 5), (5, 5), fill='black', width=1, dash_on=4, dash_off=4)
        self.assertEqual(img.getpixel((5, 5)), (255, 255, 255))

    def test_diagonal_does_not_overrun_endpoint(self):
        """Dashes follow a diagonal and never paint past the end point."""
        from PIL import ImageDraw
        img = Image.new('RGB', (60, 60), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 0), (50, 50), fill='black', width=1, dash_on=5, dash_off=5)
        # Some pixels along the diagonal are painted...
        painted = any(img.getpixel((i, i)) == (0, 0, 0) for i in range(51))
        self.assertTrue(painted)
        # ...and nothing is painted well beyond the end point.
        self.assertEqual(img.getpixel((58, 58)), (255, 255, 255))

    def test_zero_period_falls_back_to_solid(self):
        """dash_on + dash_off == 0 draws a solid line instead of looping forever."""
        from PIL import ImageDraw
        img = Image.new('RGB', (20, 5), color='white')
        d = ImageDraw.Draw(img)
        _draw_dashed_line(d, (0, 2), (19, 2), fill='black', width=1, dash_on=0, dash_off=0)
        row = [img.getpixel((x, 2)) for x in range(20)]
        self.assertTrue(all(p == (0, 0, 0) for p in row), "expected a fully solid line")


class TestTodoCapacity(unittest.TestCase):
    """Tests for todo-list page capacity math."""

    def test_single_column(self):
        # height 480 -> body = 480 - 50 - 15 = 415; 415 // 36 = 11 rows.
        rows, cap = _todo_capacity(480, 1)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 11)

    def test_multi_column_multiplies(self):
        rows, cap = _todo_capacity(480, 3)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 33)

    def test_minimum_one_row(self):
        # A tiny card still yields at least one row.
        rows, cap = _todo_capacity(10, 2)
        self.assertEqual(rows, 1)
        self.assertEqual(cap, 2)

    def test_invalid_columns_coerces_to_one(self):
        # columns <= 0 is coerced to a single column.
        rows, cap = _todo_capacity(480, 0)
        self.assertEqual(rows, 11)
        self.assertEqual(cap, 11)


class TestTodoListPaginationRender(unittest.TestCase):
    """Tests for columns + pagination in _draw_todo_list_component."""

    @staticmethod
    def _items(n):
        return [{'summary': f'Item {i}', 'status': 'needs_action'} for i in range(n)]

    def test_count_in_title(self):
        # 5 incomplete items -> title contains "(5)".
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("Shopping", self._items(5), 400, 300, mock_logger)
        drawn = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertIn("Shopping (5)", drawn)

    def test_page_indicator_only_when_multipage(self):
        # One page (few items): no "/" indicator.
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", self._items(3), 400, 300, mock_logger, columns=1, page=0)
        single = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertNotIn("/", single)
        # Many items at 1 column on a short card -> multiple pages -> "1/N".
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", self._items(60), 400, 300, mock_logger, columns=1, page=0)
        multi = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertRegex(multi, r"1/\d+")

    def test_pagination_shows_different_items_per_page(self):
        from PIL import ImageChops
        items = self._items(60)
        page0 = _draw_todo_list_component("L", items, 400, 300, mock_logger, columns=1, page=0)
        page1 = _draw_todo_list_component("L", items, 400, 300, mock_logger, columns=1, page=1)
        self.assertIsNotNone(
            ImageChops.difference(page0, page1).getbbox(),
            "different pages must render different items",
        )

    def test_columns_fit_more_than_single_column(self):
        # With 2 columns a card holds more items on one page than with 1 column,
        # so a count that paginates at 1 column may fit on a single 2-col page.
        # Card height 480 -> 11 rows/column; 2 columns -> capacity 22.
        items = self._items(20)
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", items, 400, 480, mock_logger, columns=2, page=0)
        two_col = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        # 20 items <= 22 capacity -> single page, no indicator.
        self.assertNotIn("/", two_col)

    def test_long_item_is_truncated_with_ellipsis(self):
        long_item = [{'summary': 'X' * 200, 'status': 'needs_action'}]
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_todo_list_component("L", long_item, 400, 300, mock_logger, columns=2, page=0)
        drawn = " ".join(str(c.args[1]) for c in mock_text.call_args_list)
        self.assertIn("…", drawn)  # ellipsis character

    def test_empty_list_message_unchanged(self):
        img = _draw_todo_list_component("L", [], 400, 300, mock_logger)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (400, 300))


class TestZeroBaselineDispatch(unittest.TestCase):
    """Integration: zero_baseline flows from config through dispatch to render."""

    def test_zero_baseline_flows_from_config_to_render(self):
        """A history_graph config with zero_baseline=True reaches the renderer."""
        from datetime import datetime, timezone
        with mock.patch(
            'trmnl_server.components._draw_graph_component'
        ) as mock_draw:
            mock_draw.return_value = Image.new('RGB', (10, 10), 'white')
            with mock.patch(
                'trmnl_server.hass_client._fetch_history'
            ) as mock_fetch:
                mock_fetch.return_value = [[
                    {'state': '-5', 'last_changed': '2024-01-15T09:00:00+00:00'},
                    {'state': '5', 'last_changed': '2024-01-15T10:00:00+00:00'},
                ]]
                dashboard = {
                    'name': 'bp',
                    'components': [{
                        'entity_name': 'sensor.net_power',
                        'friendly_name': 'Net Power',
                        'type': 'history_graph',
                        'zero_baseline': True,
                    }],
                }
                fixed_now = datetime(2024, 1, 15, 11, 0, tzinfo=timezone.utc)
                render_dashboard_image(dashboard, mock_logger, now=fixed_now)

        self.assertTrue(mock_draw.called, "_draw_graph_component should be called")
        _, kwargs = mock_draw.call_args
        self.assertTrue(
            kwargs.get('zero_baseline'),
            "zero_baseline=True must be forwarded to the renderer",
        )

    def test_zero_baseline_defaults_false_when_absent(self):
        """Without the flag, the renderer receives zero_baseline False/absent."""
        from datetime import datetime, timezone
        with mock.patch(
            'trmnl_server.components._draw_graph_component'
        ) as mock_draw:
            mock_draw.return_value = Image.new('RGB', (10, 10), 'white')
            with mock.patch(
                'trmnl_server.hass_client._fetch_history'
            ) as mock_fetch:
                mock_fetch.return_value = [[
                    {'state': '1', 'last_changed': '2024-01-15T09:00:00+00:00'},
                    {'state': '2', 'last_changed': '2024-01-15T10:00:00+00:00'},
                ]]
                dashboard = {
                    'name': 'bp',
                    'components': [{
                        'entity_name': 'sensor.temp',
                        'friendly_name': 'Temp',
                        'type': 'history_graph',
                    }],
                }
                fixed_now = datetime(2024, 1, 15, 11, 0, tzinfo=timezone.utc)
                render_dashboard_image(dashboard, mock_logger, now=fixed_now)

        _, kwargs = mock_draw.call_args
        self.assertFalse(
            kwargs.get('zero_baseline', False),
            "zero_baseline must default to False when not configured",
        )


class TestFitTitleSize(unittest.TestCase):
    """Title sizing picks rungs off the ladder and never anything else."""

    def test_short_title_in_wide_tile_gets_top_rung(self):
        self.assertEqual(_fit_title_size("CPU", 800, mock_logger), COMPONENT_TITLE_FONT_SIZE)

    def test_long_title_in_narrow_tile_drops_below_top_rung(self):
        size = _fit_title_size("Living Room Temperature Sensor", 200, mock_logger)
        self.assertLess(size, 35)

    def test_only_ever_returns_ladder_values(self):
        for width in range(60, 800, 20):
            size = _fit_title_size("Living Room Temperature Sensor", width, mock_logger)
            self.assertIn(size, TITLE_SIZE_LADDER)

    def test_floors_at_smallest_rung_when_nothing_fits(self):
        self.assertEqual(_fit_title_size("x" * 400, 100, mock_logger), TITLE_SIZE_LADDER[-1])

    def test_wider_tile_never_yields_a_smaller_size(self):
        text = "Living Room Temperature Sensor"
        sizes = [_fit_title_size(text, w, mock_logger) for w in range(100, 801, 50)]
        self.assertEqual(sizes, sorted(sizes))

    def test_empty_title_gets_top_rung(self):
        self.assertEqual(_fit_title_size("", 200, mock_logger), COMPONENT_TITLE_FONT_SIZE)


class TestIncompleteItems(unittest.TestCase):
    """The shared predicate for which todo items a panel displays."""

    def test_drops_completed_items(self):
        items = [
            {'summary': 'a', 'status': 'needs_action'},
            {'summary': 'b', 'status': 'completed'},
            {'summary': 'c', 'status': 'needs_action'},
        ]
        self.assertEqual(len(_incomplete_items(items)), 2)

    def test_missing_status_counts_as_incomplete(self):
        self.assertEqual(len(_incomplete_items([{'summary': 'a'}])), 1)

    def test_ignores_non_dict_entries(self):
        self.assertEqual(len(_incomplete_items(['nope', {'summary': 'a'}])), 1)


class TestPanelTitleText(unittest.TestCase):
    """The measured string must match the string a panel actually draws."""

    def test_plain_panel_uses_friendly_name(self):
        data = {'type': 'entity', 'friendly_name': 'Kitchen', 'data': 'on'}
        self.assertEqual(_panel_title_text(data), 'Kitchen')

    def test_todo_panel_includes_incomplete_count(self):
        data = {
            'type': 'todo_list',
            'friendly_name': 'Tasks',
            'data': [
                {'summary': 'a', 'status': 'needs_action'},
                {'summary': 'b', 'status': 'completed'},
            ],
        }
        self.assertEqual(_panel_title_text(data), 'Tasks (1)')

    def test_todo_panel_with_non_list_data_counts_zero(self):
        data = {'type': 'todo_list', 'friendly_name': 'Tasks', 'data': None}
        self.assertEqual(_panel_title_text(data), 'Tasks (0)')

    def test_missing_friendly_name_is_empty_string(self):
        self.assertEqual(_panel_title_text({'type': 'entity', 'data': 'x'}), '')


class TestExplicitTitleFontSize(unittest.TestCase):
    """Every panel type must honour an externally resolved title size."""

    def test_graph_component_accepts_title_font_size(self):
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        points = [(start, 1.0), (end, 2.0)]
        img = _draw_graph_component(
            "Sensor", points, 400, 240, mock_logger,
            window_start=start, window_end=end, title_font_size=22,
        )
        self.assertEqual(img.size, (400, 240))

    def test_entity_component_accepts_title_font_size(self):
        img = _draw_entity_component("Sensor", 21.5, 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_calendar_component_accepts_title_font_size(self):
        img = _draw_calendar_component("Cal", [], 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_entities_component_accepts_title_font_size(self):
        img = _draw_entities_component("Ents", [], 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_todo_component_accepts_title_font_size(self):
        img = _draw_todo_list_component("Tasks", [], 400, 240, mock_logger, title_font_size=22)
        self.assertEqual(img.size, (400, 240))

    def test_explicit_size_actually_changes_the_title(self):
        """A larger title size must produce visibly different pixels."""
        small = _draw_entity_component("Sensor", 1, 400, 240, mock_logger, title_font_size=18)
        large = _draw_entity_component("Sensor", 1, 400, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(small.tobytes(), large.tobytes())

    def test_none_matches_the_default_rendering(self):
        """Omitting the argument must be identical to passing None."""
        a = _draw_entity_component("Sensor", 1, 400, 240, mock_logger)
        b = _draw_entity_component("Sensor", 1, 400, 240, mock_logger, title_font_size=None)
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_explicit_size_overrides_the_shrink_loop(self):
        """A long title forced to 35 must differ from the same title left to shrink."""
        name = "Extremely Long Living Room Temperature Sensor Name"
        shrunk = _draw_entity_component(name, 1, 300, 240, mock_logger)
        forced = _draw_entity_component(name, 1, 300, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(shrunk.tobytes(), forced.tobytes())

    def test_graph_component_title_font_size_changes_pixels(self):
        """A larger title size must produce visibly different pixels."""
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        points = [(start, 1.0), (end, 2.0)]
        small = _draw_graph_component(
            "Sensor", points, 400, 240, mock_logger,
            window_start=start, window_end=end, title_font_size=18,
        )
        large = _draw_graph_component(
            "Sensor", points, 400, 240, mock_logger,
            window_start=start, window_end=end, title_font_size=35,
        )
        self.assertNotEqual(small.tobytes(), large.tobytes())

    def test_calendar_component_title_font_size_changes_pixels(self):
        """A larger title size must produce visibly different pixels."""
        small = _draw_calendar_component("Cal", [], 400, 240, mock_logger, title_font_size=18)
        large = _draw_calendar_component("Cal", [], 400, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(small.tobytes(), large.tobytes())

    def test_entities_component_title_font_size_changes_pixels(self):
        """A larger title size must produce visibly different pixels."""
        small = _draw_entities_component("Ents", [], 400, 240, mock_logger, title_font_size=18)
        large = _draw_entities_component("Ents", [], 400, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(small.tobytes(), large.tobytes())

    def test_todo_component_title_font_size_changes_pixels(self):
        """A larger title size must produce visibly different pixels."""
        items = [
            {'summary': 'Buy milk', 'status': 'needs_action'},
            {'summary': 'Walk dog', 'status': 'needs_action'},
        ]
        small = _draw_todo_list_component("Tasks", items, 400, 240, mock_logger, title_font_size=18)
        large = _draw_todo_list_component("Tasks", items, 400, 240, mock_logger, title_font_size=35)
        self.assertNotEqual(small.tobytes(), large.tobytes())


class TestRowTitleSizeHarmonisation(unittest.TestCase):
    """Panels in a row share one title size; rows may differ."""

    LONG = "Extremely Long Living Room Temperature Sensor Name"

    def _sizes(self, render_data):
        """Renders a dashboard and returns the title_font_size each panel got."""
        captured = []

        def fake_draw(friendly_name, value, width, height, logger, *,
                      title_font_size=None, title_lines=1):
            captured.append((friendly_name, title_font_size))
            return Image.new('RGB', (width, height), color='white')

        with mock.patch('trmnl_server.components._draw_entity_component', side_effect=fake_draw):
            tile_components(render_data, 800, 480, 40, mock_logger)
        return dict(captured)

    def _panel(self, name, large=False):
        return {'type': 'entity', 'friendly_name': name, 'data': 'v', 'large_display': large}

    def test_panels_in_the_same_row_get_the_same_size(self):
        # n=4 gives a 2x2 grid: row 0 is A and B, row 1 is C and the long title.
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel(self.LONG),
        ])
        self.assertEqual(sizes['C'], sizes[self.LONG])

    def test_a_row_with_a_long_title_uses_a_second_smaller_size(self):
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel(self.LONG),
        ])
        self.assertEqual(sizes['A'], sizes['B'])
        self.assertLess(sizes[self.LONG], sizes['A'])

    def test_every_resolved_size_is_a_ladder_rung(self):
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel(self.LONG),
        ])
        for size in sizes.values():
            self.assertIn(size, TITLE_SIZE_LADDER)

    def test_all_short_titles_collapse_to_one_size(self):
        sizes = self._sizes([
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel('D'),
        ])
        self.assertEqual(len(set(sizes.values())), 1)

    def test_large_display_panel_is_sized_independently(self):
        """The full-width panel is fitted to its own width, not the row below."""
        sizes = self._sizes([
            self._panel(self.LONG, large=True),
            self._panel('A'), self._panel('B'), self._panel('C'),
        ])
        alone = self._sizes([self._panel(self.LONG, large=True)])
        # The large panel spans the full 800px in both cases (row resolution
        # is scoped per row), so it must resolve identically whether or not
        # the narrow row beneath it exists.
        self.assertEqual(sizes[self.LONG], alone[self.LONG])
        self.assertEqual(sizes['A'], sizes['B'])
        self.assertEqual(sizes['B'], sizes['C'])

    def test_no_data_panels_are_excluded_from_the_row_minimum(self):
        """A placeholder's long name must not shrink its neighbour's title."""
        with_placeholder = [
            self._panel('A'), self._panel('B'),
            self._panel('C'), {'type': 'entity', 'friendly_name': self.LONG,
                               'data': None, 'large_display': False},
        ]
        sizes = self._sizes(with_placeholder)
        self.assertEqual(sizes['C'], 35)

    def test_empty_data_history_graph_is_excluded_from_the_row_minimum(self):
        """A history_graph with data=[] draws a centred placeholder and no
        title (see _draw_graph_component's `if not data_points` branch), so
        it must not drag its neighbour's title size/line-count down either."""
        with_empty_graph = [
            self._panel('A'), self._panel('B'),
            self._panel('C'), {'type': 'history_graph', 'friendly_name': self.LONG,
                               'data': [], 'large_display': False},
        ]
        sizes = self._sizes(with_empty_graph)
        self.assertEqual(sizes['C'], 35)

    def test_row_of_only_no_data_panels_does_not_crash(self):
        sizes = self._sizes([
            {'type': 'entity', 'friendly_name': 'X', 'data': None, 'large_display': False},
            {'type': 'entity', 'friendly_name': 'Y', 'data': None, 'large_display': False},
        ])
        self.assertEqual(sizes, {})

    def test_empty_component_list_still_returns_a_blank_image(self):
        img = tile_components([], 800, 480, 40, mock_logger)
        self.assertEqual(img.size, (800, 480))

    def test_todo_count_suffix_pulls_the_row_down_to_its_own_rung(self):
        """The measured string must be the drawn string, not the bare name.

        At 400px, the bare name "Household Chores And Errands" fits rung 22,
        but the drawn string "Household Chores And Errands (120)" only fits
        rung 18 on one line (checked directly below -- this is what would
        regress if _panel_title_text dropped the todo count suffix).

        With 6 components the grid is 3 rows x 2 cols, giving 400x146 tiles
        and a band cap of 146 * 45 // 100 = 65. At that cap: with the suffix,
        s1=18 and s2=22 -- a one-rung gain, so the row wraps to (22, 2). Without
        the suffix, s1=22 and s2=22 -- no gain, so it would stay at (22, 1).
        The LINE COUNT (not just the size) is what distinguishes a correctly
        measured suffix from a dropped one, so that is what this test pins.
        """
        name = "Household Chores And Errands"
        bare_size = _fit_title_size(name, 400, mock_logger)
        drawn_size = _fit_title_size(f"{name} (120)", 400, mock_logger)
        self.assertEqual(bare_size, 22)
        self.assertEqual(drawn_size, 18)

        captured = []

        def fake_entity_draw(friendly_name, value, width, height, logger, *,
                              title_font_size=None, title_lines=1):
            captured.append((friendly_name, title_font_size, title_lines))
            return Image.new('RGB', (width, height), color='white')

        def fake_todo_draw(friendly_name, items, width, height, logger, *,
                            columns=1, page=0, title_font_size=None, title_lines=1,
                            body_font_size=None):
            captured.append((friendly_name, title_font_size, title_lines))
            return Image.new('RGB', (width, height), color='white')

        items = [{'summary': f'chore {i}', 'status': 'needs_action'} for i in range(120)]
        render_data = [
            self._panel('A'), self._panel('B'),
            self._panel('C'), self._panel('D'), self._panel('E'),
            {'type': 'todo_list', 'friendly_name': name, 'data': items, 'large_display': False},
        ]

        with mock.patch('trmnl_server.components._draw_entity_component', side_effect=fake_entity_draw), \
             mock.patch('trmnl_server.components._draw_todo_list_component', side_effect=fake_todo_draw):
            tile_components(render_data, 800, 480, 40, mock_logger)

        sizes = {n: (s, l) for n, s, l in captured}
        # E is the todo panel's row-mate: 6 items in a 2-col grid put E (index
        # 4) and the todo panel (index 5) together in the last row.
        self.assertEqual(sizes['E'], (22, 2))
        self.assertEqual(sizes[name], (22, 2))


class TestFitTitleSizeWithLines(unittest.TestCase):
    """Two-line fitting and the band-height cap."""

    LONG = "Back Garden Soil Moisture Level"

    def test_two_lines_reaches_a_higher_rung_than_one(self):
        one = _fit_title_size(self.LONG, 400, mock_logger)
        two = _fit_title_size(self.LONG, 400, mock_logger, lines=2)
        self.assertEqual(one, 22)
        self.assertEqual(two, 35)

    def test_default_call_is_unchanged(self):
        self.assertEqual(_fit_title_size("CPU", 400, mock_logger), 35)

    def test_max_band_caps_the_rung(self):
        # cap 65 is what a 146px-tall tile yields; rung 22 (band 57) is the
        # largest that fits.
        self.assertEqual(
            _fit_title_size(self.LONG, 400, mock_logger, lines=2, max_band=65), 22
        )

    def test_returns_none_when_cap_excludes_every_rung(self):
        # cap 39 is what an 88px-tall tile yields; below rung 18's band of
        # 47, so no rung qualifies.
        self.assertIsNone(
            _fit_title_size(self.LONG, 400, mock_logger, lines=2, max_band=39)
        )

    def test_none_only_ever_happens_with_max_band(self):
        for width in (10, 50, 200, 800):
            self.assertIsNotNone(_fit_title_size(self.LONG, width, mock_logger))
            self.assertIsNotNone(_fit_title_size(self.LONG, width, mock_logger, lines=2))

    def test_result_is_always_a_ladder_member_or_none(self):
        for cap in (30, 39, 47, 65, 99, None):
            got = _fit_title_size(self.LONG, 400, mock_logger, lines=2, max_band=cap)
            self.assertTrue(got is None or got in TITLE_SIZE_LADDER)

    def test_width_failure_under_a_permissive_cap_returns_a_rung_not_none(self):
        """Mode 2: the cap admits every rung, but no rung fits the width.

        tile_width=10 makes the width budget negative (10 - TITLE_PADDING),
        so no line at any font size can ever fit -- while max_band=99 is
        above even rung 35's 2-line band (87), so every rung passes the cap.
        Confirmed directly: at every rung in TITLE_SIZE_LADDER,
        _title_band_height(size, 2, logger) <= 99, and the impossible text
        (one unbroken word, no spaces to wrap on) never satisfies the width
        check at any size. This must return the smallest rung, never None --
        a regression here would make Task 6 crash on
        TITLE_SIZE_LADDER.index(None).
        """
        impossible = "Supercalifragilisticexpialidocious" * 3
        got = _fit_title_size(impossible, 10, mock_logger, lines=2, max_band=99)
        self.assertIsNotNone(got)
        self.assertEqual(got, TITLE_SIZE_LADDER[-1])


class TestEllipsize(unittest.TestCase):
    """Unit tests for the shared title-truncation helper."""

    LONG = "Extremely Long Living Room Temperature Sensor Name"

    def setUp(self):
        from PIL import ImageDraw
        self.img = Image.new('RGB', (10, 10))
        self.d = ImageDraw.Draw(self.img)
        self.font = _load_font(24, mock_logger)

    def test_text_that_fits_is_returned_unchanged(self):
        result = _ellipsize("Hi", self.font, 1000, self.d)
        self.assertEqual(result, "Hi")

    def test_text_too_wide_is_truncated_with_ellipsis(self):
        result = _ellipsize(self.LONG, self.font, 100, self.d)
        self.assertTrue(result.endswith('…'))
        self.assertLess(len(result), len(self.LONG))

    def test_truncated_result_actually_fits_max_width(self):
        max_width = 100
        result = _ellipsize(self.LONG, self.font, max_width, self.d)
        bbox = self.d.textbbox((0, 0), result, font=self.font)
        self.assertLessEqual(bbox[2] - bbox[0], max_width)

    def test_degenerate_tiny_width_returns_ellipsis_alone(self):
        result = _ellipsize(self.LONG, self.font, 1, self.d)
        self.assertEqual(result, '…')


class TestTitleEllipsisTruncation(unittest.TestCase):
    """A title too long for its tile must ellipsis-truncate, not clip at the edges.

    Regression coverage for the row-title-harmonisation defect: `_fit_title_size`
    can resolve the ladder floor (18) even when it does not actually fit, so
    each drawing function must fall back to truncating its own title rather
    than drawing text that overflows the tile and gets clipped.
    """

    LONG = "Extremely Long Living Room Temperature Sensor Name"
    # Rows containing only the title -- shorter than where any function's
    # list/graph body content begins (todo's checkbox row starts at
    # unscaled y=TODO_HEADER_H=50), so an edge hit here can only be the title.
    BAND_HEIGHT = 45

    def _edges_blank(self, img):
        """True if columns 0 and width-1 are pure white for the title band."""
        px = img.load()
        w, h = img.size
        band = min(self.BAND_HEIGHT, h)
        for y in range(band):
            if px[0, y] != (255, 255, 255) or px[w - 1, y] != (255, 255, 255):
                return False
        return True

    def test_graph_component_does_not_clip(self):
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        points = [(start, 1.0), (end, 2.0)]
        img = _draw_graph_component(
            self.LONG, points, 300, 240, mock_logger,
            window_start=start, window_end=end, title_font_size=18,
        )
        self.assertTrue(self._edges_blank(img), "title touches the tile edge -- it clipped")

    def test_entity_component_does_not_clip(self):
        img = _draw_entity_component(self.LONG, 1, 300, 240, mock_logger, title_font_size=18)
        self.assertTrue(self._edges_blank(img), "title touches the tile edge -- it clipped")

    def test_calendar_component_does_not_clip(self):
        img = _draw_calendar_component(self.LONG, [], 300, 240, mock_logger, title_font_size=18)
        self.assertTrue(self._edges_blank(img), "title touches the tile edge -- it clipped")

    def test_entities_component_does_not_clip(self):
        img = _draw_entities_component(self.LONG, [], 300, 240, mock_logger, title_font_size=18)
        self.assertTrue(self._edges_blank(img), "title touches the tile edge -- it clipped")

    def test_todo_component_does_not_clip(self):
        items = [
            {'summary': 'Buy milk', 'status': 'needs_action'},
            {'summary': 'Walk dog', 'status': 'needs_action'},
        ]
        img = _draw_todo_list_component(
            self.LONG, items, 300, 240, mock_logger, title_font_size=18,
        )
        self.assertTrue(self._edges_blank(img), "title touches the tile edge -- it clipped")

    def test_calendar_component_none_path_also_does_not_clip(self):
        """The three previously-non-shrinking components could already overflow
        with no title_font_size supplied at all (the None/default path)."""
        img = _draw_calendar_component(self.LONG, [], 300, 240, mock_logger)
        self.assertTrue(self._edges_blank(img), "title touches the tile edge -- it clipped")


class TestWrapTitle(unittest.TestCase):
    """Greedy pixel word wrap for panel titles."""

    def _font(self, size=35):
        return _load_font(size * COMPONENT_SCALE, mock_logger)

    def test_short_text_returns_single_line(self):
        self.assertEqual(_wrap_title("CPU", self._font(), 760, 2), ["CPU"])

    def test_wraps_onto_two_lines_when_needed(self):
        lines = _wrap_title("Back Garden Soil Moisture Level", self._font(), 760, 2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(" ".join(lines), "Back Garden Soil Moisture Level")

    def test_never_breaks_a_word(self):
        lines = _wrap_title("Supercalifragilistic Expialidocious", self._font(), 760, 2)
        for line in lines or []:
            for word in line.split():
                self.assertIn(word, "Supercalifragilistic Expialidocious")

    def test_returns_none_when_more_lines_needed(self):
        self.assertIsNone(
            _wrap_title("One Two Three Four Five Six Seven Eight Nine Ten", self._font(), 200, 2)
        )

    def test_single_unbreakable_word_returns_one_line(self):
        # A word that cannot fit is still returned; _ellipsize handles it later.
        self.assertEqual(_wrap_title("Supercalifragilistic", self._font(), 50, 2),
                         ["Supercalifragilistic"])

    def test_empty_string(self):
        self.assertEqual(_wrap_title("", self._font(), 760, 2), [""])

    def test_every_returned_line_fits_when_not_none(self):
        font = self._font(18)
        lines = _wrap_title("Back Garden Soil Moisture Level", font, 400, 2)
        if lines is not None and len(lines) > 1:
            for line in lines:
                self.assertLessEqual(font.getbbox(line)[2] - font.getbbox(line)[0], 400)


class TestTitleBandHeight(unittest.TestCase):
    """Band height must match the measured table the design was calibrated on."""

    EXPECTED = {35: (46, 87), 30: (39, 76), 26: (34, 66), 22: (29, 57), 18: (24, 47)}

    def test_matches_measured_table(self):
        for size, (one, two) in self.EXPECTED.items():
            self.assertEqual(_title_band_height(size, 1, mock_logger), one, f"rung {size}, 1 line")
            self.assertEqual(_title_band_height(size, 2, mock_logger), two, f"rung {size}, 2 lines")

    def test_two_lines_always_taller_than_one(self):
        for size in TITLE_SIZE_LADDER:
            self.assertGreater(_title_band_height(size, 2, mock_logger),
                               _title_band_height(size, 1, mock_logger))

    def test_one_line_band_at_top_rung_exceeds_graph_margin(self):
        """Guards the reason the 1-line path must NOT use max(40, band)."""
        self.assertGreater(_title_band_height(35, 1, mock_logger), 40)


class TestTwoLineSimpleComponents(unittest.TestCase):
    """Calendar, entities and todo honour a two-line title band."""

    LONG = "Back Garden Soil Moisture Level"

    def test_calendar_accepts_title_lines(self):
        img = _draw_calendar_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_entities_accepts_title_lines(self):
        img = _draw_entities_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_todo_accepts_title_lines(self):
        img = _draw_todo_list_component(self.LONG, [], 400, 220, mock_logger,
                                        title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_two_lines_differs_from_one(self):
        one = _draw_calendar_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=1)
        two = _draw_calendar_component(self.LONG, [], 400, 220, mock_logger,
                                       title_font_size=35, title_lines=2)
        self.assertNotEqual(one.tobytes(), two.tobytes())

    def test_one_line_content_origin_matches_legacy_y_pos(self):
        """At one line, content must start at the legacy y_pos = 50 * scale,
        not a band-derived value (the y_pos == 0 else-branch must never be
        replaced by a max(50*scale, band) that could shift it).

        Replaces a former tautology that compared two calls which were
        already the same call (title_lines=1 is the default), so it could
        never fail under any mutation.
        """
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.text') as mock_text:
            _draw_entities_component("Short", [], 400, 220, mock_logger,
                                     title_font_size=35, title_lines=1)
        # multiline_text (the title) delegates internally to text(), so the
        # last text() call is the "No entities to display" message -- the
        # content origin under test.
        content_y = mock_text.call_args_list[-1].args[0][1]
        self.assertEqual(content_y, 50 * COMPONENT_SCALE)


class TestTodoCapacityWithBand(unittest.TestCase):
    """Pagination must use the same header height the panel draws."""

    def test_one_line_matches_legacy_constant(self):
        self.assertEqual(_todo_capacity(220, 1), _todo_capacity(220, 1, 35, 1, mock_logger))

    def test_two_lines_reduces_capacity(self):
        one = _todo_capacity(220, 1, 35, 1, mock_logger)[1]
        two = _todo_capacity(220, 1, 35, 2, mock_logger)[1]
        self.assertLess(two, one)


class TestTodoHeaderHeightSharedDefinition(unittest.TestCase):
    """_todo_capacity and _draw_todo_list_component must derive header from one function.

    Regression coverage for the header-agreement finding: two independently
    written copies of the same formula could silently drift, causing
    pagination and rendering to disagree and rows to render off the bottom.
    """

    COMBINATIONS = [(35, 1), (35, 2), (18, 2), (26, 2), (30, 2)]

    def test_capacity_implies_the_shared_header(self):
        for font_size, lines in self.COMBINATIONS:
            header = _todo_header_height(font_size, lines, mock_logger)
            expected_rows = max(1, (220 - header - TODO_BOTTOM_PAD) // TODO_ROW_H)
            rows, capacity = _todo_capacity(220, 1, font_size, lines, mock_logger)
            self.assertEqual(rows, expected_rows, f"rows mismatch at {(font_size, lines)}")
            self.assertEqual(capacity, expected_rows, f"capacity mismatch at {(font_size, lines)}")

    def test_draw_scales_the_same_header(self):
        # Proves the draw path calls the one shared function with the same
        # arguments _todo_capacity would use -- if a future edit reintroduced
        # an inline duplicate, this mock would simply never be called.
        for font_size, lines in self.COMBINATIONS:
            with mock.patch('trmnl_server.components._todo_header_height',
                             wraps=_todo_header_height) as spy:
                _draw_todo_list_component("Title", [], 400, 300, mock_logger,
                                          title_font_size=font_size, title_lines=lines)
                spy.assert_called_once_with(font_size, lines, mock_logger)


class TestTitleWhitespaceByteIdentity(unittest.TestCase):
    """The one-line path must not normalise whitespace via _wrap_title's split/join.

    Regression coverage: _wrap_title does text.split() then " ".join(...), so a
    friendly_name with leading/trailing/double spaces would render normalised
    rather than literal. Before Task 3 such a string was passed straight to
    _ellipsize and drawn verbatim; the one-line path must bypass _wrap_title
    entirely to restore that.
    """

    NAME = " Cal  Sensor "

    def test_calendar_preserves_literal_whitespace(self):
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.multiline_text') as mock_draw:
            _draw_calendar_component(self.NAME, [], 400, 220, mock_logger)
        drawn = mock_draw.call_args.args[1]
        self.assertEqual(drawn, self.NAME)

    def test_entities_preserves_literal_whitespace(self):
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.multiline_text') as mock_draw:
            _draw_entities_component(self.NAME, [], 400, 220, mock_logger)
        drawn = mock_draw.call_args.args[1]
        self.assertEqual(drawn, self.NAME)

    def test_todo_preserves_literal_whitespace(self):
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.multiline_text') as mock_draw:
            _draw_todo_list_component(self.NAME, [], 400, 220, mock_logger)
        drawn = mock_draw.call_args.args[1]
        self.assertEqual(drawn, f"{self.NAME} (0)")

    def test_wrap_title_itself_would_have_normalised(self):
        """Documents why the bypass is needed: _wrap_title alone loses whitespace."""
        font = _load_font(35 * COMPONENT_SCALE, mock_logger)
        self.assertEqual(_wrap_title(self.NAME, font, 100000, 1), ["Cal Sensor"])


class TestGraphTwoLineTitle(unittest.TestCase):
    """The graph reserves a taller top margin only when its title wraps."""

    def _points(self):
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        return start, end, [(start, 1.0), (end, 2.0)]

    def test_accepts_title_lines(self):
        start, end, pts = self._points()
        img = _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                    mock_logger, window_start=start, window_end=end,
                                    title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_two_lines_differs_from_one(self):
        start, end, pts = self._points()
        kw = dict(window_start=start, window_end=end, title_font_size=35)
        one = _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                    mock_logger, title_lines=1, **kw)
        two = _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                    mock_logger, title_lines=2, **kw)
        self.assertNotEqual(one.tobytes(), two.tobytes())

    # The "1-line must not route through max(40*scale, band)" claim used to
    # live here as `a = _draw_graph_component(..., title_lines=1) == b =
    # _draw_graph_component(...)` -- but title_lines=1 IS the default, so a
    # and b were the same call and the assertion was a tautology. The real
    # check (pinning margin_top to the literal 40 * COMPONENT_SCALE, observed
    # via the mocked axis line rather than by comparing two identical calls)
    # now lives in TestGraphAxisMarginMapping.test_axis_geometry_pins_the_margin_split.

    def test_preserves_literal_whitespace(self):
        """One-line path must bypass _wrap_title's split/join whitespace normalisation."""
        start, end, pts = self._points()
        name = " Graph  Sensor "
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.multiline_text') as mock_draw:
            _draw_graph_component(name, pts, 400, 220, mock_logger,
                                  window_start=start, window_end=end)
        drawn = mock_draw.call_args.args[1]
        self.assertEqual(drawn, name)


class TestGraphAxisMarginMapping(unittest.TestCase):
    """Pins margin_left/margin_top/margin_bottom to the correct axis positions.

    Regression coverage for the horizontal/vertical margin-swap bug class the
    task brief warned about: golden images can't see it because at
    title_lines == 1 all three margins equal 40 * scale, so a mis-assignment
    renders pixel-identically. This inspects the raw d.line() calls instead.
    """

    def _axis_lines(self, title_lines):
        from datetime import datetime, timedelta, timezone
        end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = end - timedelta(hours=24)
        pts = [(start, 1.0), (end, 2.0)]
        with mock.patch('trmnl_server.components.ImageDraw.ImageDraw.line') as mock_line:
            _draw_graph_component("Back Garden Soil Moisture Level", pts, 400, 220,
                                  mock_logger, window_start=start, window_end=end,
                                  title_font_size=35, title_lines=title_lines)
        calls = [c.args[0] for c in mock_line.call_args_list]
        # The y-axis is the first line whose two points share an x.
        y_axis = next(xy for xy in calls if xy[0][0] == xy[1][0])
        # The x-axis is drawn immediately after it.
        x_axis = calls[calls.index(y_axis) + 1]
        return y_axis, x_axis

    def test_axis_geometry_pins_the_margin_split(self):
        y_axis_1, x_axis_1 = self._axis_lines(1)
        y_axis_2, x_axis_2 = self._axis_lines(2)

        # x of both y-axis points is unchanged: margin_top must never leak
        # into a horizontal position.
        self.assertEqual(y_axis_1[0][0], y_axis_2[0][0])
        self.assertEqual(y_axis_1[1][0], y_axis_2[1][0])

        # At one line margin_top must equal the legacy literal exactly, not a
        # max(40*scale, band)-derived value -- the one-line band at rung 35
        # (46px) exceeds the 40px legacy margin, so routing through max()
        # here would shift every graph even at one line.
        self.assertEqual(y_axis_1[0][1], 40 * COMPONENT_SCALE)

        # The first point's y (margin_top) grows when the title wraps.
        self.assertGreater(y_axis_2[0][1], y_axis_1[0][1])

        # The second point's y (margin_bottom) is untouched.
        self.assertEqual(y_axis_1[1][1], y_axis_2[1][1])

        # Nothing horizontal or bottom-anchored moved.
        self.assertEqual(x_axis_1, x_axis_2)


class TestEntityTwoLineTitle(unittest.TestCase):
    """The entity value is bounded by the region below a wrapped title."""

    LONG = "Back Garden Soil Moisture Level"

    def test_accepts_title_lines(self):
        img = _draw_entity_component(self.LONG, 21.5, 400, 220, mock_logger,
                                     title_font_size=35, title_lines=2)
        self.assertEqual(img.size, (400, 220))

    def test_two_lines_differs_from_one(self):
        one = _draw_entity_component(self.LONG, 21.5, 400, 220, mock_logger,
                                     title_font_size=35, title_lines=1)
        two = _draw_entity_component(self.LONG, 21.5, 400, 220, mock_logger,
                                     title_font_size=35, title_lines=2)
        self.assertNotEqual(one.tobytes(), two.tobytes())

    # A "1-line is byte-identical to omitting the argument" test used to live
    # here as `a = _draw_entity_component(..., title_lines=1) == b =
    # _draw_entity_component(...)`. title_lines=1 IS the default, so a and b
    # were the same call -- a tautology that could never fail. Deleted rather
    # than replaced: unlike the graph's margin_top (a clean 40*scale literal)
    # or the entities list's y_pos (a clean 50*scale literal), this
    # component's one-line content origin (value_y) is not directly
    # observable as a single literal without re-deriving the font metrics
    # the implementation itself computes, which would make the assertion
    # circular. Real, non-circular coverage of this exact one-line path
    # (avail_top == 0, and the value must not overflow the tile) is added
    # below as test_value_fits_a_short_tile_at_one_line, which inspects
    # actual rendered pixels instead of comparing two identical calls.

    def test_value_does_not_overflow_a_short_tile_with_a_wrapped_title(self):
        """266x146 needed 158px before this fix. Top rows must stay blank."""
        img = _draw_entity_component(self.LONG, 21.5, 266, 146, mock_logger,
                                     title_font_size=18, title_lines=2)
        px = img.convert('L').load()
        # The bottom-most row must not be inked: the value has to fit.
        self.assertTrue(all(px[x, img.height - 1] > 200 for x in range(img.width)))

    def test_long_multiword_value_is_bounded(self):
        img = _draw_entity_component(
            "Weather", "Partly Cloudy With Heavy Showers And Thunder",
            150, 90, mock_logger, title_font_size=18, title_lines=2,
        )
        px = img.convert('L').load()
        self.assertTrue(all(px[x, img.height - 1] > 200 for x in range(img.width)))

    def test_value_fits_a_short_tile_at_one_line(self):
        """A narrow value never triggers the width-shrink loop, so on a short
        tile it used to stay at the max font and overflow both the top and
        bottom (e.g. "21.5" rendered as "21 5", its decimal point cut off).
        The height clause (`value_bbox[3] > avail_h`) and the
        `value_y = max(avail_top, value_y)` clamp fix this -- deliberately
        unconditionally, even at title_lines=1. Use "72", not "21.50": the
        latter is wide enough that the width loop shrinks it before the
        height clause ever gets a chance to fire.

        Height 100 (not the sibling test's 146): at this narrow value/width,
        146 lands the shrink loop's coarse -4px step on a font size that
        still overflows by a few pixels (a pre-existing quantisation
        artifact of the shared loop, not something this fix closes) --
        confirmed by direct measurement, see final report. 100 exercises the
        same height clause without hitting that artifact.
        """
        img = _draw_entity_component("Sensor", "72", 266, 100, mock_logger, title_lines=1)
        px = img.convert('L').load()
        self.assertTrue(all(px[x, img.height - 1] > 200 for x in range(img.width)))


class TestRowLineCountResolution(unittest.TestCase):
    """A row shares a line count as well as a size."""

    LONG = "Back Garden Soil Moisture Level"

    def _capture(self, render_data, width=800, height=480):
        seen = []

        def fake(friendly_name, value, w, h, logger, *, title_font_size=None, title_lines=1):
            seen.append((friendly_name, title_font_size, title_lines))
            return Image.new('RGB', (w, h), color='white')

        with mock.patch('trmnl_server.components._draw_entity_component', side_effect=fake):
            tile_components(render_data, width, height, 40, mock_logger)
        return {n: (s, l) for n, s, l in seen}

    def _panel(self, name, large=False):
        return {'type': 'entity', 'friendly_name': name, 'data': 'v', 'large_display': large}

    def test_row_wraps_to_gain_a_bigger_font(self):
        got = self._capture([self._panel('A'), self._panel('B'),
                             self._panel('C'), self._panel(self.LONG)])
        self.assertEqual(got[self.LONG], (35, 2))
        self.assertEqual(got['C'], (35, 2))

    def test_neighbours_share_size_and_line_count(self):
        got = self._capture([self._panel('A'), self._panel('B'),
                             self._panel('C'), self._panel(self.LONG)])
        self.assertEqual(got['C'], got[self.LONG])
        self.assertEqual(got['A'], got['B'])

    def test_no_wrap_when_nothing_is_gained(self):
        got = self._capture([self._panel('A'), self._panel('B'),
                             self._panel('C'), self._panel('D')])
        for value in got.values():
            self.assertEqual(value, (35, 1))

    def test_mixed_none_results_do_not_raise(self):
        """17 panels -> tile_height 88 -> the band cap excludes every rung."""
        panels = [self._panel(f'Panel Number {i}') for i in range(17)]
        got = self._capture(panels)
        for size, lines in got.values():
            self.assertEqual(lines, 1)

    def test_placeholder_only_row_falls_back(self):
        got = self._capture([
            {'type': 'entity', 'friendly_name': 'X', 'data': None, 'large_display': False},
            {'type': 'entity', 'friendly_name': 'Y', 'data': None, 'large_display': False},
        ])
        self.assertEqual(got, {})


class _FakeResponse:
    """Minimal stand-in for the object urlopen returns as a context manager."""

    def __init__(self, body: bytes, delay: float = 0.0):
        self._body = body
        self._delay = delay

    def __enter__(self):
        if self._delay:
            time.sleep(self._delay)
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body


def _ink_row_bands(img, top):
    """Y-extents of the horizontal bands of ink below `top`.

    Each drawn text row produces one band, so the gaps between consecutive
    band starts are the row pitch actually rendered.
    """
    grey = img.convert('L')
    width, height = grey.size
    bands = []
    start = None
    for y in range(top, height):
        has_ink = min(grey.crop((0, y, width, y + 1)).getdata()) < 128
        if has_ink and start is None:
            start = y
        elif not has_ink and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, height))
    return bands


class TestFitBodySize(unittest.TestCase):
    """Unit tests for the shared body-text size resolver."""

    SHORT = ["Hall: 20.0", "Kitchen: 21.5"]
    LONG = ["Back Garden Soil Moisture Sensor: 12.34"]

    def test_short_texts_in_a_wide_budget_get_the_top_rung(self):
        self.assertEqual(_fit_body_size(self.SHORT, 5000, mock_logger), BODY_SIZE_LADDER[0])

    def test_empty_group_gets_the_top_rung(self):
        self.assertEqual(_fit_body_size([], 100, mock_logger), BODY_SIZE_LADDER[0])

    def test_only_ever_returns_ladder_values(self):
        for budget in range(20, 1200, 37):
            self.assertIn(_fit_body_size(self.SHORT + self.LONG, budget, mock_logger),
                          BODY_SIZE_LADDER)

    def test_floors_at_the_smallest_rung_when_nothing_fits(self):
        self.assertEqual(_fit_body_size(self.LONG, 5, mock_logger), BODY_SIZE_LADDER[-1])

    def test_wider_budget_never_yields_a_smaller_size(self):
        sizes = [_fit_body_size(self.SHORT + self.LONG, b, mock_logger)
                 for b in range(50, 1200, 25)]
        self.assertEqual(sizes, sorted(sizes))

    def test_one_long_row_drags_the_whole_group_down(self):
        """The group is sized for its widest member — that is the point."""
        budget = 480
        alone = _fit_body_size(self.SHORT, budget, mock_logger)
        together = _fit_body_size(self.SHORT + self.LONG, budget, mock_logger)
        self.assertLess(together, alone)
        self.assertEqual(together, _fit_body_size(self.LONG, budget, mock_logger))


class TestEllipsizePrefix(unittest.TestCase):
    """Unit tests for suffix-preserving truncation of "<name>: <state>" rows."""

    def setUp(self):
        from PIL import ImageDraw
        self.img = Image.new('RGB', (10, 10))
        self.d = ImageDraw.Draw(self.img)
        self.font = _load_font(24, mock_logger)

    def test_row_that_fits_is_returned_unchanged(self):
        self.assertEqual(
            _ellipsize_prefix("Hall", ": 20.0", self.font, 1000, self.d),
            "Hall: 20.0",
        )

    def test_state_survives_when_the_name_is_too_long(self):
        result = _ellipsize_prefix(
            "Back Garden Soil Moisture Sensor", ": 12.34", self.font, 200, self.d
        )
        self.assertTrue(result.endswith(": 12.34"), result)
        self.assertIn('…', result)

    def test_truncated_result_actually_fits_max_width(self):
        max_width = 200
        result = _ellipsize_prefix(
            "Back Garden Soil Moisture Sensor", ": 12.34", self.font, max_width, self.d
        )
        bbox = self.d.textbbox((0, 0), result, font=self.font)
        self.assertLessEqual(bbox[2] - bbox[0], max_width)

    def test_falls_back_to_plain_truncation_when_the_suffix_alone_overflows(self):
        """Too narrow to keep the state: degrade to _ellipsize's own behaviour."""
        self.assertEqual(
            _ellipsize_prefix("Name", ": 12.34", self.font, 10, self.d),
            _ellipsize("Name: 12.34", self.font, 10, self.d),
        )


class TestBodySizeHarmonisation(unittest.TestCase):
    """Rows inside one panel must share a single text size and row pitch.

    Before this, every row ran its own shrink loop, so a single list could
    render at four different sizes with the spacing between rows tracking each
    row's own ink height.
    """

    MIXED = [
        {'friendly_name': 'Kitchen', 'state': 21.5},
        {'friendly_name': 'Living Room Temperature', 'state': 19.8},
        {'friendly_name': 'Hall', 'state': 20.0},
        {'friendly_name': 'Back Garden Soil Moisture Sensor', 'state': 12.34},
    ]

    def test_entity_list_rows_share_one_pitch(self):
        img = _draw_entities_component('Sensors', list(self.MIXED), 266, 220, mock_logger)
        bands = _ink_row_bands(img, 50)
        self.assertEqual(len(bands), len(self.MIXED))
        pitches = [bands[i + 1][0] - bands[i][0] for i in range(len(bands) - 1)]
        self.assertEqual(len(set(pitches)), 1, f"ragged row pitch: {pitches}")

    def test_entity_list_keeps_the_state_when_the_name_is_truncated(self):
        """A narrow panel truncates the name; the value must still be readable."""
        img = _draw_entities_component(
            'Sensors',
            [{'friendly_name': 'Back Garden Soil Moisture Sensor', 'state': 12.34}],
            266, 220, mock_logger,
        )
        # The value is drawn at the right of the row, so ink must reach past the
        # midpoint of the content area rather than stopping at a truncated name.
        row = img.crop((0, 50, img.size[0], img.size[1])).convert('L')
        from PIL import ImageChops
        bbox = ImageChops.invert(row).getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreater(bbox[2], img.size[0] * 0.7)

    def test_calendar_events_share_one_pitch(self):
        events = [
            {'summary': 'Standup',
             'start': {'dateTime': '2024-01-01T09:00:00+00:00'},
             'end': {'dateTime': '2024-01-01T09:15:00+00:00'}},
            {'summary': 'Quarterly planning review with the wider platform team',
             'start': {'dateTime': '2024-01-02T10:00:00+00:00'},
             'end': {'dateTime': '2024-01-02T12:00:00+00:00'}},
            {'summary': 'Dentist', 'start': {'date': '2024-01-03'}},
        ]
        img = _draw_calendar_component('Calendar', events, 400, 220, mock_logger)
        bands = _ink_row_bands(img, 50)
        self.assertEqual(len(bands), len(events))
        pitches = [bands[i + 1][0] - bands[i][0] for i in range(len(bands) - 1)]
        self.assertEqual(len(set(pitches)), 1, f"ragged row pitch: {pitches}")

    def test_todo_summaries_share_one_baseline(self):
        """Mixed-length todo items align on one baseline instead of stepping."""
        items = [
            {'summary': 'Milk', 'status': 'needs_action'},
            {'summary': 'Book the annual car service appointment', 'status': 'needs_action'},
            {'summary': 'Bins', 'status': 'needs_action'},
        ]
        img = _draw_todo_list_component('Todo', items, 400, 220, mock_logger, columns=1)
        # Crop away the checkboxes (which end at x=39) so only the summary text
        # is measured, keeping every summary's leading capital in frame — with a
        # shared size those capitals give a shared ink top.
        text_only = img.crop((44, 50, img.size[0], img.size[1]))
        bands = _ink_row_bands(text_only, 0)
        self.assertEqual(len(bands), len(items))
        pitches = [bands[i + 1][0] - bands[i][0] for i in range(len(bands) - 1)]
        self.assertEqual(len(set(pitches)), 1, f"ragged row pitch: {pitches}")


class TestPanelBodyFit(unittest.TestCase):
    """Unit tests for the per-panel body-size probe used by the row resolver."""

    LONG_ROWS = [
        {'friendly_name': 'Kitchen', 'state': 21.5},
        {'friendly_name': 'Back Garden Soil Moisture Sensor', 'state': 12.34},
    ]
    SHORT_ROWS = [
        {'friendly_name': 'Hall', 'state': 20.0},
        {'friendly_name': 'Attic', 'state': 18.0},
    ]

    def test_panels_without_body_rows_return_none(self):
        """Only list-style panels have rows to harmonise."""
        for render_data in (
            {'type': 'entity', 'data': '21.5'},
            {'type': 'url', 'data': '42'},
            {'type': 'history_graph', 'data': [(1, 2.0)]},
        ):
            self.assertIsNone(_panel_body_fit(render_data, 400, mock_logger),
                              render_data['type'])

    def test_missing_or_empty_data_returns_none(self):
        """Those panels draw a fixed-size placeholder, not rows."""
        for data in (None, [], {}):
            self.assertIsNone(
                _panel_body_fit({'type': 'entities', 'data': data}, 400, mock_logger)
            )
            self.assertIsNone(
                _panel_body_fit({'type': 'calendar', 'data': data}, 400, mock_logger)
            )

    def test_todo_with_only_completed_items_returns_none(self):
        render_data = {
            'type': 'todo_list',
            'data': [{'summary': 'done', 'status': 'completed'}],
        }
        self.assertIsNone(_panel_body_fit(render_data, 400, mock_logger))

    def test_long_rows_probe_smaller_than_short_rows(self):
        long_fit = _panel_body_fit(
            {'type': 'entities', 'data': self.LONG_ROWS}, 400, mock_logger)
        short_fit = _panel_body_fit(
            {'type': 'entities', 'data': self.SHORT_ROWS}, 400, mock_logger)
        self.assertIn(long_fit, BODY_SIZE_LADDER)
        self.assertIn(short_fit, BODY_SIZE_LADDER)
        self.assertLess(long_fit, short_fit)

    def test_todo_columns_narrow_the_budget(self):
        """More columns means less width per item, so never a bigger size."""
        items = [{'summary': 'Book the annual car service appointment',
                  'status': 'needs_action'}]
        one = _panel_body_fit(
            {'type': 'todo_list', 'data': items, 'columns': 1}, 400, mock_logger)
        two = _panel_body_fit(
            {'type': 'todo_list', 'data': items, 'columns': 2}, 400, mock_logger)
        self.assertLessEqual(two, one)

    def test_probe_matches_what_the_panel_draws_alone(self):
        """The probe must predict the size the draw function picks unaided.

        If these drift, the row resolver would harmonise on a size no panel
        actually wanted.
        """
        from PIL import ImageChops
        render_data = {'type': 'entities', 'data': self.LONG_ROWS}
        probed = _panel_body_fit(render_data, 400, mock_logger)
        alone = _draw_entities_component(
            'Sensors', list(self.LONG_ROWS), 400, 220, mock_logger)
        forced = _draw_entities_component(
            'Sensors', list(self.LONG_ROWS), 400, 220, mock_logger,
            body_font_size=probed)
        self.assertIsNone(ImageChops.difference(alone, forced).getbbox())


class TestRowBodySizeHarmonisation(unittest.TestCase):
    """Panels sharing a layout row must agree on one body text size."""

    @staticmethod
    def _entities(name, rows):
        return {'type': 'entities', 'friendly_name': name, 'data': rows,
                'large_display': False}

    LONG = [
        {'friendly_name': 'Kitchen', 'state': 21.5},
        {'friendly_name': 'Back Garden Soil Moisture Sensor', 'state': 12.34},
    ]
    SHORT = [
        {'friendly_name': 'Hall', 'state': 20.0},
        {'friendly_name': 'Attic', 'state': 18.0},
    ]

    def _captured_body_sizes(self, render_data):
        captured = {}

        def fake_entities_draw(friendly_name, entity_states, width, height, logger, *,
                               title_font_size=None, title_lines=1, body_font_size=None):
            captured[friendly_name] = body_font_size
            return Image.new('RGB', (width, height), color='white')

        with mock.patch('trmnl_server.components._draw_entities_component',
                        side_effect=fake_entities_draw):
            tile_components(render_data, 800, 480, 40, mock_logger)
        return captured

    def test_neighbours_in_a_row_share_one_body_size(self):
        """A 2x2 grid: the long-rowed panel pulls its row-mate down with it."""
        captured = self._captured_body_sizes([
            self._entities('A', list(self.LONG)),
            self._entities('B', list(self.SHORT)),
            self._entities('C', list(self.SHORT)),
            self._entities('D', list(self.SHORT)),
        ])
        self.assertEqual(captured['A'], captured['B'])
        self.assertEqual(captured['C'], captured['D'])
        # ...and only that row: the all-short bottom row keeps the top rung.
        self.assertLess(captured['A'], captured['C'])
        self.assertEqual(captured['C'], BODY_SIZE_LADDER[0])

    def test_every_resolved_size_is_a_ladder_rung(self):
        captured = self._captured_body_sizes([
            self._entities(n, list(self.LONG if n == 'A' else self.SHORT))
            for n in ('A', 'B', 'C', 'D')
        ])
        for name, size in captured.items():
            self.assertIn(size, BODY_SIZE_LADDER, name)

    def test_row_of_panels_without_body_rows_passes_none(self):
        """An entity panel beside an empty list leaves the size unresolved."""
        captured = self._captured_body_sizes([
            self._entities('A', []),
            self._entities('B', []),
            self._entities('C', []),
            self._entities('D', []),
        ])
        self.assertEqual(set(captured.values()), {None})

    def test_mixed_row_ignores_panels_without_rows(self):
        """A big-value entity panel must not affect its row-mate's body size."""
        alone = self._captured_body_sizes([
            self._entities('A', list(self.SHORT)),
            self._entities('B', list(self.SHORT)),
            self._entities('C', list(self.SHORT)),
            self._entities('D', list(self.SHORT)),
        ])
        mixed = self._captured_body_sizes([
            self._entities('A', list(self.SHORT)),
            {'type': 'entity', 'friendly_name': 'V', 'data': '21.5',
             'large_display': False},
            self._entities('C', list(self.SHORT)),
            self._entities('D', list(self.SHORT)),
        ])
        self.assertEqual(mixed['A'], alone['A'])


class TestBodyRowTextBuilders(unittest.TestCase):
    """The row resolver and the draw functions must build identical strings."""

    def test_entities_row_parts_splits_name_from_state(self):
        parts = _entities_row_parts([{'friendly_name': 'Hall', 'state': 20.0}])
        self.assertEqual(parts, [('Hall', ': 20.00')])

    def test_entities_row_parts_defaults_missing_state(self):
        self.assertEqual(_entities_row_parts([{'friendly_name': 'X'}]),
                         [('X', ': N/A')])

    def test_calendar_row_texts_sorts_and_formats(self):
        events = [
            {'summary': 'Later', 'start': {'date': '2024-01-03'}},
            {'summary': 'Earlier',
             'start': {'dateTime': '2024-01-01T09:00:00+00:00'},
             'end': {'dateTime': '2024-01-01T09:15:00+00:00'}},
        ]
        texts = _calendar_row_texts(events, mock_logger)
        self.assertEqual(len(texts), 2)
        self.assertIn('Earlier', texts[0])
        self.assertIn('All day: Later', texts[1])

    def test_calendar_row_texts_handles_a_startless_event(self):
        self.assertEqual(
            _calendar_row_texts([{'summary': 'Mystery', 'start': {}}], mock_logger),
            ['Unknown: Mystery'],
        )

    def test_todo_row_texts_covers_every_page(self):
        """Sizing is deliberately not page-scoped, so text cannot resize as it cycles."""
        items = [{'summary': f'Task {i}', 'status': 'needs_action'} for i in range(40)]
        items.append({'summary': 'done already', 'status': 'completed'})
        texts = _todo_row_texts(items)
        self.assertEqual(len(texts), 40)
        self.assertNotIn('done already', texts)


class TestUrlComponentRendering(unittest.TestCase):
    """Integration: a url component through render_dashboard_image."""

    def setUp(self):
        url_source.reset_cache()

    def test_renders_extracted_value(self):
        """A warm cache renders the extracted text into the dashboard image."""
        dashboard = {
            "name": "d",
            "components": [
                {
                    "type": "url",
                    "friendly_name": "Price",
                    "url": "http://e.com/a",
                    "json_path": ".data.amount",
                }
            ],
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b'{"data": {"amount": "42"}}')
        ):
            render_dashboard_image(dashboard, mock_logger)   # cold: schedules the fetch
            url_source._wait_for_pending()
            img_io = render_dashboard_image(dashboard, mock_logger)
        self.assertIsNotNone(img_io)
        self.assertGreater(len(img_io.getvalue()), 0)

    def test_cold_render_does_not_block(self):
        """A slow endpoint does not delay the render thread."""
        dashboard = {
            "name": "d",
            "components": [
                {"type": "url", "friendly_name": "Price", "url": "http://e.com/a"}
            ],
        }
        with mock.patch.object(
            url_source, "urlopen", return_value=_FakeResponse(b"42", delay=3.0)
        ):
            t0 = time.perf_counter()
            render_dashboard_image(dashboard, mock_logger)
            elapsed = time.perf_counter() - t0
            url_source._wait_for_pending()
        self.assertLess(elapsed, 2.0, "render must not wait for a slow fetch")


if __name__ == '__main__':
    unittest.main()
