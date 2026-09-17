"""
Unit tests for LaserForge KerfEngine (kerf compensation, lead-in/out, overcuts).
"""

import unittest
import math
from laserforge.core.kerf_engine import KerfEngine


class TestKerfEngine(unittest.TestCase):

    def test_closed_path_detection(self):
        closed_sq = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        open_line = [(0, 0), (10, 0), (10, 10)]
        self.assertTrue(KerfEngine.is_closed_path(closed_sq))
        self.assertFalse(KerfEngine.is_closed_path(open_line))

    def test_kerf_auto_outer_and_inner(self):
        # Outer square: 100x100 from (0,0) to (100,100)
        outer_box = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        # Inner hole: 20x20 from (40,40) to (60,60)
        inner_hole = [(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)]

        kerf = 0.2  # offset = 0.1 mm
        res = KerfEngine.apply_kerf_to_paths([outer_box, inner_hole], kerf_offset=kerf, direction="Auto")

        self.assertEqual(len(res), 2)
        # One outer, one inner
        outer_res = [r for r in res if r["is_outer"]]
        inner_res = [r for r in res if not r["is_outer"]]
        self.assertEqual(len(outer_res), 1)
        self.assertEqual(len(inner_res), 1)

        # Outer box should have grown: bounding box [-0.1, -0.1, 100.1, 100.1]
        out_pts = outer_res[0]["path"]
        min_x = min(p[0] for p in out_pts)
        max_x = max(p[0] for p in out_pts)
        self.assertAlmostEqual(min_x, -0.1, delta=0.01)
        self.assertAlmostEqual(max_x, 100.1, delta=0.01)

        # Inner hole should have shrunk: bounding box [40.1, 40.1, 59.9, 59.9]
        in_pts = inner_res[0]["path"]
        in_min_x = min(p[0] for p in in_pts)
        in_max_x = max(p[0] for p in in_pts)
        self.assertAlmostEqual(in_min_x, 40.1, delta=0.01)
        self.assertAlmostEqual(in_max_x, 59.9, delta=0.01)

    def test_lead_in_generation(self):
        # Outer square CCW
        outer_sq = [(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)]
        # Line lead-in
        lead_line = KerfEngine.generate_lead_in(outer_sq, lead_type="Line", length=3.0, is_outer=True)
        self.assertEqual(len(lead_line), 2)
        self.assertEqual(lead_line[1], (0, 0))
        # Pierce point should be outside (y < 0 or x < 0)
        self.assertTrue(lead_line[0][1] < 0 or lead_line[0][0] < 0)

        # Perpendicular lead-in
        lead_perp = KerfEngine.generate_lead_in(outer_sq, lead_type="Perpendicular", length=2.0, is_outer=True)
        self.assertEqual(len(lead_perp), 2)
        self.assertEqual(lead_perp[1], (0, 0))
        self.assertAlmostEqual(lead_perp[0][1], -2.0, delta=0.05)

        # Arc lead-in
        lead_arc = KerfEngine.generate_lead_in(outer_sq, lead_type="Arc", length=2.0, is_outer=True)
        self.assertTrue(len(lead_arc) >= 4)
        self.assertAlmostEqual(lead_arc[-1][0], 0.0, delta=0.05)
        self.assertAlmostEqual(lead_arc[-1][1], 0.0, delta=0.05)

    def test_lead_out_generation(self):
        outer_sq = [(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)]
        lead_out = KerfEngine.generate_lead_out(outer_sq, lead_type="Perpendicular", length=2.0, is_outer=True)
        self.assertEqual(len(lead_out), 2)
        self.assertEqual(lead_out[0], (0, 0))
        # Exits into waste
        self.assertTrue(lead_out[1][0] < 0 or lead_out[1][1] < 0)

    def test_apply_overcut(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        # Overcut by 2 mm
        overcut_path = KerfEngine.apply_overcut(sq, overcut_dist=2.0)
        self.assertEqual(len(overcut_path), 6)
        self.assertAlmostEqual(overcut_path[-1][0], 2.0, delta=1e-3)
        self.assertAlmostEqual(overcut_path[-1][1], 0.0, delta=1e-3)

    def test_gcode_generation_with_kerf_and_lead_in(self):
        from laserforge.config import MachineSettings
        from laserforge.core.layer_manager import LayerManager
        from laserforge.core.models import RectEntity
        from laserforge.core.gcode_generator import GCodeGenerator

        settings = MachineSettings()
        layer_mgr = LayerManager()
        layer = layer_mgr.get_layer(0)
        layer.kerf_offset = 0.2  # 0.1mm offset
        layer.lead_in_type = "Line"
        layer.lead_in_length = 2.0
        layer.overcut_length = 1.0

        gen = GCodeGenerator(settings, layer_mgr)
        rect = RectEntity(layer_id=0, name="Box", x=10.0, y=10.0, width=50.0, height=40.0, corner_radius=0.0)
        result = gen.generate_job([rect])

        self.assertIn("G1", result.gcode)
        self.assertGreater(result.total_cut_dist_mm, 0.0)
        # Should have cut segments generated
        self.assertTrue(any(s.move_type == "cut" for s in result.segments))


if __name__ == "__main__":
    unittest.main()
