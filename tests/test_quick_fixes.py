"""
Unit tests for LaserForge Phase 1 Quick Fixes:
1. Native G2/G3 arc generation for CircleEntity.
2. Per-entity speed and power overrides (Material Test Matrix).
3. Geometric point-in-polygon nesting depth in PathOptimizer.
4. Zero shortcut collisions in MainWindow.
"""

import unittest
import math
from PyQt6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.models import RectEntity, CircleEntity, LineEntity, PathEntity, LayerCutSettings
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.gcode_validator import GCodeValidator
from laserforge.core.optimizer import PathOptimizer, point_in_polygon
from laserforge.core.materials_database import MaterialDatabase
from laserforge.ui.main_window import MainWindow


class TestQuickFixes(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings()
        self.layer_mgr = LayerManager()
        self.gcode_gen = GCodeGenerator(self.settings, self.layer_mgr)
        self.validator = GCodeValidator(self.settings)

    def test_circle_entity_generates_g2_arcs(self):
        """CircleEntity should emit native G2 circular arcs when enable_arcs is True."""
        circle = CircleEntity(layer_id=0, name="Circle_Arc", x=50.0, y=50.0, radius_x=15.0, radius_y=15.0)
        job = self.gcode_gen.generate_job([circle])

        self.assertIn("G2", job.gcode)
        # Verify it validates cleanly with GRBL validator
        report = self.validator.validate(job.gcode)
        self.assertTrue(report.is_valid, f"Validation failed: {report.issues}")
        self.assertEqual(len(report.errors), 0)

        # Count G2 moves: should be exactly 2 semicircular arcs
        g2_count = sum(1 for line in job.gcode.splitlines() if line.strip().startswith("G2 "))
        self.assertEqual(g2_count, 2)

    def test_test_matrix_swatches_have_overrides_and_modulate_power_speed(self):
        """Material test matrix swatches must carry distinct speed/power overrides that appear in G-code."""
        speeds = [400.0, 1200.0]
        powers = [25.0, 75.0]
        entities = MaterialDatabase.generate_test_matrix_entities(
            speeds=speeds, powers=powers, swatch_size=8.0, spacing=2.0, test_type="Fill"
        )

        swatches = [e for e in entities if isinstance(e, RectEntity) and e.name.startswith("Swatch_")]
        self.assertEqual(len(swatches), 4)

        for s in swatches:
            self.assertIsNotNone(s.override_speed)
            self.assertIsNotNone(s.override_power)

        # Configure layer 0 to Fill mode
        self.layer_mgr.get_layer(0).mode = "Fill"
        job = self.gcode_gen.generate_job(swatches)

        # Verify that the generated G-code modulates feedrate and S-power according to the swatches
        # Speeds: 400, 1200
        self.assertIn("F400", job.gcode)
        self.assertIn("F1200", job.gcode)

        # Powers: 25% of 1000 = S250, 75% of 1000 = S750
        self.assertIn("S250", job.gcode)
        self.assertIn("S750", job.gcode)

        # Must validate cleanly
        report = self.validator.validate(job.gcode)
        self.assertTrue(report.is_valid, f"Validation failed: {report.issues}")

    def test_point_in_polygon_and_optimizer_nesting(self):
        """Verify ray-casting point_in_polygon and non-convex containment in PathOptimizer."""
        # L-shaped polygon:
        # (0, 0) -> (40, 0) -> (40, 20) -> (20, 20) -> (20, 40) -> (0, 40) -> (0, 0)
        l_shape = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (20.0, 20.0), (20.0, 40.0), (0.0, 40.0), (0.0, 0.0)]

        # Point inside the solid L
        self.assertTrue(point_in_polygon(10.0, 10.0, l_shape))
        # Point inside the empty notch (30, 30) - within L's bounding box [0..40, 0..40], but outside the polygon
        self.assertFalse(point_in_polygon(30.0, 30.0, l_shape))

        # Notch box located at (25, 25) with size 10x10 (falls inside L's bounding box, but NOT inside L)
        notch_box = [(25.0, 25.0), (35.0, 25.0), (35.0, 35.0), (25.0, 35.0), (25.0, 25.0)]

        # Hole box located at (5, 5) with size 5x5 (truly inside L)
        hole_box = [(5.0, 5.0), (10.0, 5.0), (10.0, 10.0), (5.0, 10.0), (5.0, 5.0)]

        # Optimize paths
        ordered = PathOptimizer.optimize_paths([l_shape, notch_box, hole_box])
        # hole_box MUST be cut before l_shape
        idx_hole = ordered.index(hole_box)
        idx_l = ordered.index(l_shape)
        self.assertLess(idx_hole, idx_l, "Inner hole must be cut before outer L-shape")

    def test_zero_shortcut_collisions_in_main_window(self):
        """MainWindow must have zero duplicate keyboard shortcuts."""
        win = MainWindow()
        shortcuts = {}
        collisions = []
        for act in win.findChildren(type(win.act_new)):
            sc = act.shortcut().toString()
            if sc:
                if sc in shortcuts:
                    collisions.append((sc, act.text(), shortcuts[sc]))
                else:
                    shortcuts[sc] = act.text()
        win.close()
        self.assertEqual(len(collisions), 0, f"Found shortcut collisions: {collisions}")


if __name__ == "__main__":
    unittest.main()
