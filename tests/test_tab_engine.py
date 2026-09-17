"""
Unit tests for LaserForge Holding Tabs & Bridges Engine.
"""

import unittest
import math
from laserforge.core.tab_engine import TabEngine


class TestTabEngine(unittest.TestCase):

    def test_polyline_length(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        length = TabEngine.polyline_length(pts)
        self.assertAlmostEqual(length, 400.0, places=3)

    def test_interpolate_point_at_distance(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
        pt_50 = TabEngine.interpolate_point_at_distance(pts, 50.0)
        self.assertAlmostEqual(pt_50[0], 50.0, places=3)
        self.assertAlmostEqual(pt_50[1], 0.0, places=3)

        pt_150 = TabEngine.interpolate_point_at_distance(pts, 150.0)
        self.assertAlmostEqual(pt_150[0], 100.0, places=3)
        self.assertAlmostEqual(pt_150[1], 50.0, places=3)

    def test_slice_square_with_4_tabs(self):
        # 100x100 square has perimeter 400mm
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        segments = TabEngine.slice_contour_with_tabs(pts, tab_count=4, tab_width=2.0)

        # Should have cut segments and exactly 4 tab segments
        cuts = [s for s in segments if s["type"] == "cut"]
        tabs = [s for s in segments if s["type"] == "tab"]

        self.assertEqual(len(tabs), 4)
        self.assertGreaterEqual(len(cuts), 4)

        # Verify each tab width is approximately 2.0 mm
        for t in tabs:
            d = math.hypot(t["end"][0] - t["start"][0], t["end"][1] - t["start"][1])
            self.assertAlmostEqual(d, 2.0, places=2)

    def test_manual_tabs(self):
        # Place single tab at 0.5 (halfway around 100x100 square = 200mm = (100, 100))
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        segments = TabEngine.slice_contour_with_tabs(pts, tab_width=1.5, manual_tab_ratios=[0.5])

        tabs = [s for s in segments if s["type"] == "tab"]
        self.assertEqual(len(tabs), 1)
        self.assertAlmostEqual(tabs[0]["width"], 1.5, places=2)

    def test_zero_tabs_returns_full_cut(self):
        pts = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 0.0)]
        segments = TabEngine.slice_contour_with_tabs(pts, tab_count=0)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["type"], "cut")

    def test_gcode_generator_with_holding_tabs(self):
        from laserforge.config import MachineSettings
        from laserforge.core.layer_manager import LayerManager
        from laserforge.core.models import RectEntity
        from laserforge.core.gcode_generator import GCodeGenerator
        from laserforge.core.gcode_validator import GCodeValidator

        settings = MachineSettings()
        lm = LayerManager()
        layer = lm.get_layer(0)
        layer.mode = "Line"
        layer.tabs_enabled = True
        layer.tab_count = 4
        layer.tab_width = 2.0
        layer.tab_power_pct = 0.0  # Full uncut gap

        gen = GCodeGenerator(settings, lm)
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=80.0, height=80.0)
        job = gen.generate_job([rect])

        # Validate G-code format
        validator = GCodeValidator(settings)
        report = validator.validate(job.gcode)
        self.assertTrue(report.is_valid, f"Invalid GCode: {report.issues}")

        # When tabs are enabled, there should be multiple G0 rapid moves during the contour
        # corresponding to the 4 holding tabs
        g0_moves = [l for l in job.gcode.splitlines() if l.strip().startswith("G0 ")]
        self.assertGreaterEqual(len(g0_moves), 4)

        # Also test with tab_power_pct > 0 (skin bridge)
        layer.tab_power_pct = 15.0
        job_bridge = gen.generate_job([rect])
        self.assertIn("S150", job_bridge.gcode)  # 15% of 1000 = S150


if __name__ == "__main__":
    unittest.main()
