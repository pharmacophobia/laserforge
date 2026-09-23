"""
Unit tests for LaserForge Parametric Box & Finger-Joint Enclosure Engine.
"""

import unittest
from laserforge.core.box_engine import BoxEngine, BoxPanel
from laserforge.core.models import PathEntity


class TestBoxEngine(unittest.TestCase):

    def test_generate_6_sided_box(self):
        panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, finger_width=10.0, kerf=0.15, style="6-sided"
        )
        self.assertEqual(len(panels), 6)
        names = [p.name for p in panels]
        self.assertIn("Bottom", names)
        self.assertIn("Top", names)
        self.assertIn("Front", names)
        self.assertIn("Back", names)
        self.assertIn("Left", names)
        self.assertIn("Right", names)

        # Check that all panels have closed outlines with vertices
        for p in panels:
            self.assertGreaterEqual(len(p.outline), 12)
            self.assertEqual(p.outline[0], p.outline[-1])

    def test_generate_open_top_box(self):
        panels = BoxEngine.generate_box(
            width=120.0, depth=90.0, height=50.0, thickness=4.0, style="open-top"
        )
        self.assertEqual(len(panels), 5)
        names = [p.name for p in panels]
        self.assertNotIn("Top", names)
        self.assertIn("Bottom", names)

    def test_generate_sliding_lid_box(self):
        panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, style="sliding-lid"
        )
        self.assertEqual(len(panels), 6)
        names = [p.name for p in panels]
        self.assertIn("Sliding_Lid", names)

        # Left and Right sides should have internal slot cutouts for the lid
        left_panel = next(p for p in panels if p.name == "Left")
        self.assertEqual(len(left_panel.internal_cutouts), 1)

    def test_layout_to_entities(self):
        panels = BoxEngine.generate_box(width=80.0, depth=60.0, height=40.0, thickness=3.0)
        entities = BoxEngine.layout_to_entities(panels, start_x=10.0, start_y=10.0, spacing=5.0)

        # Should produce PathEntity objects and label TextEntities
        path_ents = [e for e in entities if isinstance(e, PathEntity)]
        self.assertEqual(len(path_ents), 6)

        # Verify none of the entities have overlapping start positions
        positions = set((e.x, e.y) for e in path_ents)
        self.assertEqual(len(positions), 6)

    def test_generate_dovetail_box(self):
        """Tests that dovetail joint generation produces valid trapezoidal interlocking panels."""
        panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, finger_width=10.0,
            kerf=0.1, style="6-sided", joint_type="dovetail", dovetail_angle=12.0
        )
        self.assertEqual(len(panels), 6)
        for p in panels:
            self.assertGreaterEqual(len(p.outline), 12)
            self.assertEqual(p.outline[0], p.outline[-1])

        # Verify that dovetail panels have trapezoidal flared vertices (distinct from pure 90° rectangular coords)
        # Compare a standard finger joint panel against a dovetail joint panel
        std_panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, finger_width=10.0,
            kerf=0.1, style="6-sided", joint_type="finger"
        )
        # Front panel outline points should differ between finger and dovetail
        front_dovetail = next(p for p in panels if p.name == "Front")
        front_finger = next(p for p in std_panels if p.name == "Front")
        self.assertNotEqual(front_dovetail.outline, front_finger.outline)

    def test_calculate_dimensions_outer_and_inner(self):
        """Verify dimension calculations for both outer footprint and inner cavity."""
        # Outer mode
        outer_dims = BoxEngine.calculate_dimensions(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, style="6-sided", dimension_mode="outer"
        )
        self.assertEqual(outer_dims["outer_w"], 100.0)
        self.assertEqual(outer_dims["outer_d"], 80.0)
        self.assertEqual(outer_dims["outer_h"], 60.0)
        self.assertEqual(outer_dims["inner_w"], 94.0)  # 100 - 2*3
        self.assertEqual(outer_dims["inner_d"], 74.0)  # 80 - 2*3
        self.assertEqual(outer_dims["inner_h"], 54.0)  # 60 - 2*3

        # Inner mode
        inner_dims = BoxEngine.calculate_dimensions(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, style="6-sided", dimension_mode="inner"
        )
        self.assertEqual(inner_dims["inner_w"], 100.0)
        self.assertEqual(inner_dims["inner_d"], 80.0)
        self.assertEqual(inner_dims["inner_h"], 60.0)
        self.assertEqual(inner_dims["outer_w"], 106.0)  # 100 + 2*3
        self.assertEqual(inner_dims["outer_d"], 86.0)   # 80 + 2*3
        self.assertEqual(inner_dims["outer_h"], 66.0)   # 60 + 2*3

        # Open-top mode only accounts for bottom thickness
        open_dims = BoxEngine.calculate_dimensions(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, style="open-top", dimension_mode="inner"
        )
        self.assertEqual(open_dims["outer_h"], 63.0)  # 60 + 1*3

    def test_generate_box_inner_dimension_mode(self):
        """Verify that dimension_mode='inner' sizes panels to ensure usable interior cavity."""
        panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, style="6-sided", dimension_mode="inner"
        )
        bot = next(p for p in panels if p.name == "Bottom")
        front = next(p for p in panels if p.name == "Front")
        left = next(p for p in panels if p.name == "Left")

        # Outer dimensions should be expanded
        self.assertEqual(bot.width, 106.0)
        self.assertEqual(bot.height, 86.0)
        self.assertEqual(front.width, 106.0)
        self.assertEqual(front.height, 66.0)
        self.assertEqual(left.width, 86.0)
        self.assertEqual(left.height, 66.0)

    def test_tab_slot_complementary_mating(self):
        """Verify that male tabs and female slots have matching segment locations along mating edges."""
        # Bottom edge of front (male) meets bottom panel front edge (female)
        # For a length of 30mm with 10mm fingers (3 divisions: 0-10, 10-20, 20-30):
        # Male should protrude on even segments (0 and 2), stay flush on odd segment (1).
        # Female should indent on even segments (0 and 2), stay flush on odd segment (1).
        male_edge = BoxEngine.generate_finger_edge(
            p_start=(0.0, 0.0), p_end=(30.0, 0.0), normal=(0.0, -1.0),
            length=30.0, thickness=3.0, target_finger_len=10.0, is_male=True, kerf=0.0
        )
        female_edge = BoxEngine.generate_finger_edge(
            p_start=(0.0, 0.0), p_end=(30.0, 0.0), normal=(0.0, -1.0),
            length=30.0, thickness=3.0, target_finger_len=10.0, is_male=False, kerf=0.0
        )

        # In male edge, points with y < 0 (outward in normal (0, -1)) should be in segments 0 and 2
        male_protrusion_x = [pt[0] for pt in male_edge if pt[1] < -1e-4]
        self.assertTrue(any(0.0 <= x <= 10.0 for x in male_protrusion_x))
        self.assertTrue(any(20.0 <= x <= 30.0 for x in male_protrusion_x))
        self.assertFalse(any(10.1 < x < 19.9 for x in male_protrusion_x))

        # In female edge, points with y > 0 (indented in -normal (0, 1)) should be in segments 0 and 2
        female_indent_x = [pt[0] for pt in female_edge if pt[1] > 1e-4]
        self.assertTrue(any(0.0 <= x <= 10.0 for x in female_indent_x))
        self.assertTrue(any(20.0 <= x <= 30.0 for x in female_indent_x))
        self.assertFalse(any(10.1 < x < 19.9 for x in female_indent_x))

    def test_layout_to_entities_adaptive_sheet_width(self):
        """Verify layout handles panels wider than default 400mm without failure or overlapping."""
        panels = BoxEngine.generate_box(width=500.0, depth=350.0, height=150.0, thickness=4.0)
        entities = BoxEngine.layout_to_entities(panels, start_x=10.0, start_y=10.0, spacing=8.0, max_sheet_w=400.0)
        path_ents = [e for e in entities if isinstance(e, PathEntity)]
        self.assertEqual(len(path_ents), 6)
        positions = set((e.x, e.y) for e in path_ents)
        self.assertEqual(len(positions), 6)


class TestBoxGeneratorDialog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

    def test_dialog_size_adjustment_and_preset_sync(self):
        from laserforge.ui.box_dialog import BoxGeneratorDialog
        from laserforge.config import MachineSettings

        settings = MachineSettings(bed_width=500.0, bed_height=500.0)
        dlg = BoxGeneratorDialog(settings=settings)

        # 1. Select a preset (index 1: Trinket 80x60x40)
        dlg.combo_preset.setCurrentIndex(1)
        self.assertEqual(dlg.spin_w.value(), 80.0)
        self.assertEqual(dlg.spin_d.value(), 60.0)
        self.assertEqual(dlg.spin_h.value(), 40.0)

        # 2. Adjust size: spin_w to 110.0 -> combo_preset should switch to 0 ("Custom Dimensions")
        dlg.spin_w.setValue(110.0)
        self.assertEqual(dlg.combo_preset.currentIndex(), 0)
        self.assertEqual(dlg.spin_w.value(), 110.0)

        # 3. Test Dimension Mode toggle: Inside Dimensions
        dlg.combo_dim_mode.setCurrentIndex(1)  # Inside Dimensions
        self.assertIn("Inside", dlg.lbl_dim_summary.text())
        # Interior is 110.0, exterior should be 110 + 2*3 = 116.0
        bot_panel = next(p for p in dlg._current_panels if p.name == "Bottom")
        self.assertEqual(bot_panel.width, 116.0)

        # 4. Verify apply to bed emits panels_generated
        emitted_entities = []
        dlg.panels_generated.connect(lambda ents: emitted_entities.extend(ents))
        dlg._apply_to_bed()
        self.assertGreater(len(emitted_entities), 0)


if __name__ == "__main__":
    unittest.main()
