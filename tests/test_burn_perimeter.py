"""
Unit Tests for LaserForge Burn Perimeter Alignment Tool.
Tests:
- Core G-code generation across all modes (box, box_crosshair, corners, crosshair_only, hull).
- Margin expansion, boundary clamping, and software coordinate mirroring.
- Multi-pass execution, air assist commands, and laser firing parameters.
- Vector CAD entity generation for canvas insertion.
- BurnPerimeterDialog and visual widget initialization and behavior.
"""

import unittest
import os
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.serial_controller import SerialController
from laserforge.core.models import (
    RectEntity, CircleEntity, LineEntity, PathEntity, LaserEntity
)
from laserforge.ui.burn_perimeter_dialog import (
    BurnPerimeterDialog, BurnPerimeterVisualWidget
)

# Ensure single QApplication instance for Qt tests
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestBurnPerimeterGCode(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings(
            bed_width=400.0,
            bed_height=400.0,
            max_s_value=1000,
            laser_mode="M4",
            rapid_speed=3000.0,
            framing_speed=2000.0,
        )
        self.layer_mgr = LayerManager()
        self.generator = GCodeGenerator(self.settings, self.layer_mgr)
        self.test_bbox = (20.0, 30.0, 120.0, 90.0)  # w=100, h=60

    def test_burn_perimeter_box_mode(self):
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="box",
            margin_mm=0.0,
            power_pct=20.0,
            speed=1500.0,
            passes=1
        )
        self.assertIn("G21", gcode)
        self.assertIn("G90", gcode)
        self.assertIn("M4 S200", gcode)  # 20% of 1000 = 200
        self.assertIn("G0 X20.000 Y30.000", gcode)
        self.assertIn("G1 X120.000 Y30.000", gcode)
        self.assertIn("G1 X120.000 Y90.000", gcode)
        self.assertIn("G1 X20.000 Y90.000", gcode)
        self.assertIn("M5", gcode)

    def test_burn_perimeter_with_margin(self):
        margin = 5.0
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="box",
            margin_mm=margin,
            power_pct=10.0,
            speed=2000.0,
            passes=1
        )
        # min_x: 20 - 5 = 15, min_y: 30 - 5 = 25, max_x: 120 + 5 = 125, max_y: 90 + 5 = 95
        self.assertIn("G0 X15.000 Y25.000", gcode)
        self.assertIn("G1 X125.000 Y25.000", gcode)
        self.assertIn("G1 X125.000 Y95.000", gcode)
        self.assertIn("G1 X15.000 Y95.000", gcode)

    def test_burn_perimeter_box_crosshair(self):
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="box_crosshair",
            margin_mm=0.0,
            power_pct=15.0,
            speed=1800.0
        )
        # Center: cx = (20 + 120)/2 = 70, cy = (30 + 90)/2 = 60
        self.assertIn("X70.000", gcode)
        self.assertIn("Y60.000", gcode)
        # Horizontal crosshair: X20->120 at Y60
        self.assertIn("G1 X120.000 Y60.000", gcode)
        # Vertical crosshair: Y30->90 at X70
        self.assertIn("G1 X70.000 Y90.000", gcode)

    def test_burn_perimeter_corners_mode(self):
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="corners",
            margin_mm=0.0,
            corner_tick_len_mm=8.0,
            power_pct=12.0
        )
        # Corner marks should be present (8mm ticks)
        self.assertIn("Corner", gcode)
        # BL tick starts at (28, 30) -> (20, 30) -> (20, 38)
        self.assertIn("X28.000 Y30.000", gcode)
        self.assertIn("X20.000 Y30.000", gcode)
        self.assertIn("X20.000 Y38.000", gcode)
        # BR tick starts at (112, 30) -> (120, 30) -> (120, 38)
        self.assertIn("X112.000 Y30.000", gcode)
        self.assertIn("X120.000 Y30.000", gcode)
        self.assertIn("X120.000 Y38.000", gcode)

    def test_burn_perimeter_crosshair_only(self):
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="crosshair_only",
            margin_mm=0.0,
            power_pct=10.0
        )
        # Center cx=70, cy=60
        self.assertIn("G0 X20.000 Y60.000", gcode)
        self.assertIn("G1 X120.000 Y60.000", gcode)
        self.assertIn("G0 X70.000 Y30.000", gcode)
        self.assertIn("G1 X70.000 Y90.000", gcode)

    def test_burn_perimeter_convex_hull(self):
        # Create triangle shapes
        rect = RectEntity(x=20.0, y=20.0, width=40.0, height=40.0)
        circ = CircleEntity(x=100.0, y=80.0, radius_x=10.0, radius_y=10.0)
        entities = [rect, circ]

        gcode = self.generator.generate_burn_perimeter_gcode(
            target=entities,
            mode="hull",
            margin_mm=0.0,
            power_pct=15.0
        )
        self.assertIn("Perimeter Burn Beam ON", gcode)
        self.assertIn("G1", gcode)
        self.assertIn("M5", gcode)

    def test_multi_pass_burn(self):
        passes = 3
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="box",
            passes=passes,
            power_pct=25.0
        )
        self.assertEqual(gcode.count("; --- Pass 1 of 3 ---"), 1)
        self.assertEqual(gcode.count("; --- Pass 2 of 3 ---"), 1)
        self.assertEqual(gcode.count("; --- Pass 3 of 3 ---"), 1)

    def test_air_assist_toggle(self):
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            air_assist=True
        )
        self.assertIn("M8 ; Air Assist ON", gcode)
        self.assertIn("M9 ; Air Assist OFF", gcode)

    def test_software_mirroring(self):
        self.settings.software_mirror_x = True
        self.settings.software_mirror_y = True
        gcode = self.generator.generate_burn_perimeter_gcode(
            target=self.test_bbox,
            mode="box",
            margin_mm=0.0
        )
        # Bed is 400x400.
        # X: 20 -> 380, 120 -> 280
        # Y: 30 -> 370, 90 -> 310
        self.assertIn("X380.000 Y370.000", gcode)
        self.assertIn("X280.000 Y370.000", gcode)

    def test_invalid_target_handling(self):
        self.assertEqual(self.generator.generate_burn_perimeter_gcode(target=None), "")
        self.assertEqual(self.generator.generate_burn_perimeter_gcode(target=[]), "")
        self.assertEqual(self.generator.generate_burn_perimeter_gcode(target=(100, 100, 50, 50)), "")


class TestBurnPerimeterEntities(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0)
        self.layer_mgr = LayerManager()
        self.generator = GCodeGenerator(self.settings, self.layer_mgr)
        self.test_bbox = (20.0, 30.0, 120.0, 90.0)

    def test_generate_box_entity(self):
        entities = self.generator.generate_burn_perimeter_entities(
            target=self.test_bbox,
            mode="box",
            margin_mm=2.0,
            layer_id=12
        )
        self.assertEqual(len(entities), 1)
        ent = entities[0]
        self.assertIsInstance(ent, RectEntity)
        self.assertEqual(ent.layer_id, 12)
        self.assertAlmostEqual(ent.x, 18.0)
        self.assertAlmostEqual(ent.y, 28.0)
        self.assertAlmostEqual(ent.width, 104.0)
        self.assertAlmostEqual(ent.height, 64.0)

    def test_generate_box_crosshair_entities(self):
        entities = self.generator.generate_burn_perimeter_entities(
            target=self.test_bbox,
            mode="box_crosshair",
            layer_id=2
        )
        self.assertEqual(len(entities), 3)  # Rect + 2 lines
        self.assertIsInstance(entities[0], RectEntity)
        self.assertIsInstance(entities[1], LineEntity)
        self.assertIsInstance(entities[2], LineEntity)
        self.assertEqual(entities[0].layer_id, 2)
        self.assertEqual(entities[1].layer_id, 2)

    def test_generate_corners_entities(self):
        entities = self.generator.generate_burn_perimeter_entities(
            target=self.test_bbox,
            mode="corners",
            corner_tick_len_mm=10.0,
            layer_id=12
        )
        self.assertEqual(len(entities), 4)
        for ent in entities:
            self.assertIsInstance(ent, PathEntity)
            self.assertFalse(ent.closed)
            self.assertEqual(ent.layer_id, 12)

    def test_generate_crosshair_only_entities(self):
        entities = self.generator.generate_burn_perimeter_entities(
            target=self.test_bbox,
            mode="crosshair_only"
        )
        self.assertEqual(len(entities), 2)
        for ent in entities:
            self.assertIsInstance(ent, LineEntity)


class TestBurnPerimeterUI(unittest.TestCase):

    def setUp(self):
        self.serial_ctrl = SerialController()
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0)
        self.layer_mgr = LayerManager()
        self.gcode_gen = GCodeGenerator(self.settings, self.layer_mgr)
        self.rect = RectEntity(x=30.0, y=40.0, width=80.0, height=50.0)

    def test_visual_widget_render(self):
        widget = BurnPerimeterVisualWidget(bed_width=400.0, bed_height=400.0)
        widget.update_geometry_state(
            source_bbox=(30, 40, 110, 90),
            perimeter_bbox=(28, 38, 112, 92),
            mode="box"
        )
        self.assertEqual(widget.perimeter_bbox, (28, 38, 112, 92))
        self.assertEqual(widget.mode, "box")

    def test_dialog_initialization_and_presets(self):
        dlg = BurnPerimeterDialog(
            serial_ctrl=self.serial_ctrl,
            settings=self.settings,
            gcode_gen=self.gcode_gen,
            layer_manager=self.layer_mgr,
            selected_entities=[self.rect],
            all_entities=[self.rect]
        )
        self.assertIsNotNone(dlg)
        self.assertEqual(dlg.spin_x.value(), 30.0)
        self.assertEqual(dlg.spin_y.value(), 40.0)
        self.assertEqual(dlg.spin_w.value(), 80.0)
        self.assertEqual(dlg.spin_h.value(), 50.0)

        # Test selecting preset
        dlg.combo_presets.setCurrentIndex(2)  # Masking / Blue Tape
        self.assertEqual(dlg.spin_power.value(), 8.0)
        self.assertEqual(dlg.spin_speed.value(), 2500.0)

        # Test G-code build
        gcode = dlg._build_gcode()
        self.assertIn("M4 S80", gcode)  # 8% of 1000 = 80
        self.assertIn("F2500", gcode)

        dlg.close()


if __name__ == "__main__":
    unittest.main()
