"""
Unit tests for LaserForge RotaryEngine (Roller & Chuck kinematics, scaling, and test jog).
"""

import unittest
import math
from laserforge.config import MachineSettings
from laserforge.core.rotary_engine import RotaryEngine


class TestRotaryEngine(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings()
        self.settings.y_steps_per_mm = 80.0
        self.settings.rotary_original_y_steps = 80.0
        self.settings.rotary_steps_per_rev = 3200.0

    def test_circumference_calculation(self):
        circ = RotaryEngine.compute_circumference(65.0)
        self.assertAlmostEqual(circ, math.pi * 65.0, delta=1e-4)

    def test_roller_rotary_steps(self):
        # 3200 steps/rev, 20mm roller diameter -> circ = 20 * pi ~ 62.83185
        # steps/mm = 3200 / (20 * pi) ~ 50.92958
        steps = RotaryEngine.calculate_steps_per_mm(
            rotary_type="Roller",
            object_diameter_mm=65.0,
            steps_per_rev=3200.0,
            roller_diameter_mm=20.0
        )
        expected = 3200.0 / (20.0 * math.pi)
        self.assertAlmostEqual(steps, expected, delta=1e-3)

    def test_chuck_rotary_steps(self):
        # 3200 steps/rev, 65mm object diameter -> circ = 65 * pi ~ 204.2035
        # steps/mm = 3200 / (65 * pi) ~ 15.6706
        steps = RotaryEngine.calculate_steps_per_mm(
            rotary_type="Chuck",
            object_diameter_mm=65.0,
            steps_per_rev=3200.0
        )
        expected = 3200.0 / (65.0 * math.pi)
        self.assertAlmostEqual(steps, expected, delta=1e-3)

    def test_software_scale_factor(self):
        self.settings.rotary_enabled = True
        self.settings.rotary_type = "Chuck"
        self.settings.rotary_object_diameter = 65.0
        self.settings.rotary_original_y_steps = 80.0

        target_steps = 3200.0 / (65.0 * math.pi)  # ~15.67
        expected_scale = target_steps / 80.0  # ~0.19588

        scale = RotaryEngine.calculate_software_scale_factor(self.settings)
        self.assertAlmostEqual(scale, expected_scale, delta=1e-4)

    def test_generate_test_rotation_gcode(self):
        self.settings.rotary_enabled = True
        self.settings.rotary_object_diameter = 50.0
        self.settings.rotary_mode = "Hardware $101"

        gcode = RotaryEngine.generate_test_rotation_gcode(self.settings)
        self.assertIn("G91", gcode)
        self.assertIn("G90", gcode)
        self.assertIn("G0 Y", gcode)

    def test_eeprom_commands(self):
        self.settings.rotary_type = "Roller"
        self.settings.rotary_roller_diameter = 20.0
        cmd_set = RotaryEngine.generate_eeprom_override_command(self.settings)
        cmd_restore = RotaryEngine.generate_eeprom_restore_command(self.settings)

        self.assertTrue(cmd_set.startswith("$101="))
        self.assertEqual(cmd_restore, "$101=80.000")

    def test_gcode_generator_rotary_scaling(self):
        from laserforge.core.layer_manager import LayerManager
        from laserforge.core.models import RectEntity
        from laserforge.core.gcode_generator import GCodeGenerator

        self.settings.rotary_enabled = True
        self.settings.rotary_type = "Chuck"
        self.settings.rotary_mode = "Software Scaling"
        self.settings.rotary_object_diameter = 50.0
        self.settings.rotary_original_y_steps = 80.0
        self.settings.rotary_steps_per_rev = 3200.0

        layer_mgr = LayerManager()
        gen = GCodeGenerator(self.settings, layer_mgr)
        rect = RectEntity(layer_id=0, name="RotaryBox", x=10.0, y=20.0, width=30.0, height=40.0, corner_radius=0.0)
        job = gen.generate_job([rect])

        self.assertIn("Rotary Axis Active", job.gcode)
        self.assertGreater(job.total_cut_dist_mm, 0.0)

    def test_rotary_dialog_lifecycle(self):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            app = QApplication([])

        from laserforge.ui.rotary_dialog import RotaryDialog
        dlg = RotaryDialog(settings=self.settings)
        dlg.spin_diameter.setValue(75.0)
        dlg._recompute_and_update()
        self.assertAlmostEqual(dlg.spin_circumference.value(), 75.0 * math.pi, delta=0.1)
        dlg.close()


if __name__ == "__main__":
    unittest.main()
