"""
Unit tests for LaserForge Single-Line Stroke (Hershey Vector) Font Engine.
"""

import unittest
from laserforge.core.hershey_font import HersheyFont
from laserforge.core.models import PathEntity


class TestHersheyFont(unittest.TestCase):

    def test_render_ascii_text(self):
        text = "ABC 123"
        strokes = HersheyFont.render_text(text, font_size_mm=10.0, x=10.0, y=10.0)
        self.assertGreater(len(strokes), 0)

        # Every stroke should be a polyline with >= 2 points
        for s in strokes:
            self.assertGreaterEqual(len(s), 2)
            # All x coordinates should be around [10.0 ... 60.0]
            for px, py in s:
                self.assertGreaterEqual(px, 9.0)
                self.assertGreaterEqual(py, 4.0)

    def test_create_entity(self):
        text = "SN-2026-99"
        ent = HersheyFont.create_entity(text, x=20.0, y=30.0, font_size_mm=8.0, layer_id=0)
        self.assertIsNotNone(ent)
        self.assertIsInstance(ent, PathEntity)
        self.assertFalse(ent.closed, "Single-line stroke text must have closed=False")
        self.assertGreaterEqual(len(ent.contours), 5)

    def test_multiline_text(self):
        text = "LINE 1\nLINE 2"
        strokes = HersheyFont.render_text(text, font_size_mm=10.0, x=0.0, y=0.0, line_spacing=1.5)
        # Verify second line has greater y coordinates
        min_y_line1 = min(pt[1] for s in strokes[:5] for pt in s)
        max_y_line2 = max(pt[1] for s in strokes[5:] for pt in s)
        self.assertGreater(max_y_line2, min_y_line1 + 10.0)

    def test_empty_string(self):
        strokes = HersheyFont.render_text("", font_size_mm=10.0)
        self.assertEqual(len(strokes), 0)
        ent = HersheyFont.create_entity("", font_size_mm=10.0)
        self.assertIsNone(ent)


if __name__ == "__main__":
    unittest.main()
