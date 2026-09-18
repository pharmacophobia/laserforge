"""
Unit and Integration Tests for LaserForge Common Line Cutting Engine & Studio.
Verifies collinear segment detection, interval overlap calculation, shared seam removal,
cutting distance savings, and CommonLineDialog UI integration.
"""

import unittest
from PyQt6.QtWidgets import QApplication

from laserforge.core.models import RectEntity, LineEntity, PathEntity
from laserforge.core.common_line_engine import (
    CommonLineEngine, segments_collinear_overlap, CommonLineResult
)
from laserforge.ui.common_line_dialog import CommonLineDialog

app = QApplication.instance() or QApplication([])


class TestCommonLineEngine(unittest.TestCase):

    def test_collinear_segment_math(self):
        """Tests segments_collinear_overlap calculation, overlap extraction, and remainders."""
        # Horizontal line from (10, 20) to (50, 20)
        seg1 = ((10.0, 20.0), (50.0, 20.0))
        # Overlapping collinear line from (30, 20) to (70, 20)
        seg2 = ((30.0, 20.0), (70.0, 20.0))

        res = segments_collinear_overlap(seg1, seg2, dist_tol=0.1)
        self.assertIsNotNone(res)
        shared_seg, r1, r2 = res
        # Shared part is from x=30 to x=50
        self.assertAlmostEqual(shared_seg[0][0], 30.0)
        self.assertAlmostEqual(shared_seg[1][0], 50.0)

        # Parallel but offset line (not collinear)
        seg3 = ((10.0, 25.0), (50.0, 25.0))
        self.assertIsNone(segments_collinear_overlap(seg1, seg3, dist_tol=0.1))

        # Perpendicular line (not collinear)
        seg4 = ((20.0, 10.0), (20.0, 50.0))
        self.assertIsNone(segments_collinear_overlap(seg1, seg4, dist_tol=0.1))

    def test_two_touching_rectangles_deduplication(self):
        """Tests that two touching 20x20mm squares have their shared 20mm seam cut once."""
        # Square 1 at (0, 0) to (20, 20)
        sq1 = RectEntity(x=0.0, y=0.0, width=20.0, height=20.0)
        # Square 2 at (20, 0) to (40, 20) - touches sq1 along x=20, y in [0, 20]
        sq2 = RectEntity(x=20.0, y=0.0, width=20.0, height=20.0)

        paths = [
            [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)],
            [(20, 0), (40, 0), (40, 20), (20, 20), (20, 0)]
        ]

        result = CommonLineEngine.optimize_paths(paths, tolerance=0.1)

        # 8 original segments (4 per square)
        self.assertEqual(result.original_segment_count, 8)
        # Exactly 1 shared seam eliminated (x=20 from y=0 to 20)
        self.assertEqual(result.shared_lines_count, 1)
        self.assertEqual(result.optimized_segment_count, 7)
        self.assertAlmostEqual(result.saved_cutting_length_mm, 20.0, places=2)
        self.assertAlmostEqual(result.original_cutting_length_mm, 160.0, places=2)
        self.assertAlmostEqual(result.optimized_cutting_length_mm, 140.0, places=2)

    def test_3x3_grid_array_savings(self):
        """Tests common line cutting optimization on a tightly packed 3x3 grid array."""
        paths = []
        for row in range(3):
            for col in range(3):
                x = col * 20.0
                y = row * 20.0
                paths.append([
                    (x, y), (x + 20.0, y),
                    (x + 20.0, y + 20.0), (x, y + 20.0),
                    (x, y)
                ])

        # 9 squares * 4 sides = 36 segments
        # In a 3x3 grid, there are 2 vertical shared internal seams of length 60mm (6 individual 20mm seams)
        # and 2 horizontal shared internal seams of length 60mm (6 individual 20mm seams)
        # Total shared seams = 12 seams = 240mm saved!
        result = CommonLineEngine.optimize_paths(paths, tolerance=0.1)

        self.assertEqual(result.original_segment_count, 36)
        self.assertEqual(result.shared_lines_count, 12)
        self.assertEqual(result.optimized_segment_count, 24)
        self.assertAlmostEqual(result.saved_cutting_length_mm, 240.0, places=2)
        self.assertAlmostEqual(result.original_cutting_length_mm, 720.0, places=2)
        self.assertAlmostEqual(result.optimized_cutting_length_mm, 480.0, places=2)
        self.assertGreater(len(result.optimized_paths), 0)

    def test_common_line_dialog_ui(self):
        """Verifies CommonLineDialog initialization, telemetry calculation, and signal emission."""
        sq1 = RectEntity(x=0.0, y=0.0, width=25.0, height=25.0)
        sq2 = RectEntity(x=25.0, y=0.0, width=25.0, height=25.0)

        dlg = CommonLineDialog([sq1, sq2], cut_speed_mm_min=1200.0)
        self.assertIsNotNone(dlg.latest_result)
        self.assertEqual(dlg.latest_result.shared_lines_count, 1)
        self.assertAlmostEqual(dlg.latest_result.saved_cutting_length_mm, 25.0, places=2)

        # Test tolerance change
        dlg.spin_tol.setValue(0.2)
        self.assertIsNotNone(dlg.latest_result)

        # Verify apply signal
        emitted_paths = []
        emitted_replace = []

        def on_optimized(paths, replace):
            emitted_paths.extend(paths)
            emitted_replace.append(replace)

        dlg.paths_optimized.connect(on_optimized)
        dlg._apply_and_accept()

        self.assertTrue(len(emitted_paths) > 0)
        self.assertTrue(emitted_replace[0])


if __name__ == "__main__":
    unittest.main()
