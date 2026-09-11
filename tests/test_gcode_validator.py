"""
Unit tests for LaserForge GRBL 1.1 G-Code Validator engine.
"""

import unittest
from laserforge.config import MachineSettings
from laserforge.core.models import RectEntity, CircleEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.gcode_validator import GCodeValidator, ValidationReport, ValidationIssue


class TestGCodeValidator(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0, max_s_value=1000)
        self.validator = GCodeValidator(self.settings)

    def test_valid_generated_laserforge_gcode(self):
        """Standard LaserForge generated G-code must be 100% valid with 0 errors."""
        layer_mgr = LayerManager()
        gcode_gen = GCodeGenerator(self.settings, layer_mgr)
        rect = RectEntity(layer_id=0, x=20.0, y=20.0, width=50.0, height=30.0)
        job = gcode_gen.generate_job([rect])

        report = self.validator.validate(job.gcode)
        self.assertTrue(report.is_valid, f"Expected valid G-code, got errors: {report.errors}")
        self.assertEqual(len(report.errors), 0)
        self.assertGreater(report.motion_count, 0)
        self.assertGreater(report.max_feedrate, 0)
        self.assertTrue(report.laser_off_at_end)

    def test_unsupported_3d_printer_codes(self):
        """Detects Marlin/3D-printer extrusion and temperature commands that break GRBL."""
        bad_gcode = """
        G21 ; Millimeters
        G90 ; Absolute
        M104 S200 ; Hotend temperature (Marlin)
        M140 S60  ; Bed temperature (Marlin)
        G1 X10 Y10 E5.0 F1200 ; Extruder feed
        M106 S255 ; Fan
        M5
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_ERR_20_MARLIN", error_codes)
        self.assertIn("GRBL_ERR_20_EXTRUDER", error_codes)

    def test_modal_group_conflicts(self):
        """Detects multiple conflicting commands from the same modal group in one block."""
        bad_gcode = """
        G21 G90
        G0 G1 X10 Y10 F1000 ; Conflicting motion modes G0 and G1
        M3 M5 S500 ; Conflicting spindle states M3 and M5
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_ERR_21", error_codes)

    def test_duplicate_axis_words(self):
        """Detects duplicate axis words on the same line (GRBL Error 25)."""
        bad_gcode = """
        G21 G90
        G1 X10 X20 Y30 F1000 ; Duplicate X
        M5
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_ERR_25", error_codes)

    def test_missing_feedrate_for_cut(self):
        """G1 move without prior or inline feedrate must trigger GRBL Error 22."""
        bad_gcode = """
        G21 G90
        M4 S500
        G1 X20 Y20 ; No feedrate defined yet
        M5
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_ERR_22", error_codes)

    def test_non_positive_feedrate(self):
        """F0 or negative feedrate must trigger GRBL Error 22."""
        bad_gcode = """
        G21 G90
        G1 X10 Y10 F0 ; Invalid feedrate
        M5
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_ERR_22", error_codes)

    def test_arc_radius_mismatch(self):
        """Arc where start-to-center and end-to-center radii mismatch must trigger GRBL Error 34."""
        bad_gcode = """
        G21 G90
        G0 X0 Y0 F2000
        G2 X20 Y0 I5 J5 F1000 ; End radius is ~15.8mm, start radius is ~7.07mm -> huge mismatch
        M5
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_ERR_34", error_codes)

    def test_out_of_bounds_detection(self):
        """Coordinates exceeding physical bed width or height must trigger OUT_OF_BOUNDS error."""
        bad_gcode = """
        G21 G90
        G0 X10 Y10 F2000
        G1 X450.0 Y50.0 F1000 ; Exceeds 400mm bed_width
        M5
        """
        report = self.validator.validate(bad_gcode, bed_width=400.0, bed_height=400.0)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("OUT_OF_BOUNDS", error_codes)

    def test_laser_not_shut_off(self):
        """Program leaving laser energized at end without M5 or S0 must trigger error."""
        bad_gcode = """
        G21 G90
        M3 S800
        G1 X50 Y50 F1000
        ; Ended without M5 or S0!
        """
        report = self.validator.validate(bad_gcode)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("LASER_NOT_SHUT_OFF", error_codes)

    def test_rapid_burn_hazard_warning(self):
        """G0 rapid move while M3 constant laser power is ON should generate warning."""
        warn_gcode = """
        G21 G90
        M3 S800
        G0 X100 Y100 F3000 ; Rapid move with laser active
        M5
        """
        report = self.validator.validate(warn_gcode)
        # In default non-strict mode, warnings do not make is_valid False
        self.assertTrue(report.is_valid)
        self.assertTrue(report.has_warnings)
        warning_codes = [w.error_code for w in report.warnings]
        self.assertIn("RAPID_MOVE_BURN_HAZARD", warning_codes)

        # In strict mode, warnings make is_valid False
        strict_validator = GCodeValidator(self.settings, strict=True)
        strict_report = strict_validator.validate(warn_gcode)
        self.assertFalse(strict_report.is_valid)

    def test_line_buffer_overflow(self):
        """Lines exceeding GRBL 256 byte serial buffer limit must trigger error."""
        long_line = "G1 X10.0 Y10.0 F1000 " + (" ; padding" * 30)
        report = self.validator.validate(long_line)
        self.assertFalse(report.is_valid)
        error_codes = [err.error_code for err in report.errors]
        self.assertIn("GRBL_BUFFER_OVERFLOW", error_codes)

    def test_repair_gcode_all_issues(self):
        """Auto-repair engine must fix Marlin codes, extruder words, power limits, feedrates, and missing shutoff."""
        bad_gcode = """M104 S200 ; Hotend
M106 S255 ; Fan
G1 X15.0 Y20.0 E1.5 ; Missing F and has E
G1 X100.0 Y100.0 E3.0
M104 S0
M107
G0 X200.0 Y200.0
G1 X300.0 Y300.0 S1500 ; Exceeds max power, no M5 at end
"""
        # Initially invalid with errors
        init_rep = self.validator.validate(bad_gcode)
        self.assertFalse(init_rep.is_valid)
        self.assertGreater(len(init_rep.errors), 0)

        # Execute auto-repair
        repaired, repairs = GCodeValidator.repair_gcode(
            bad_gcode,
            bed_width=400.0,
            bed_height=400.0,
            max_s=1000,
            default_feedrate=1200.0
        )
        self.assertGreater(len(repairs), 0)

        # Repaired code must be 100% valid with 0 errors
        rep_val = self.validator.validate(repaired)
        self.assertTrue(rep_val.is_valid, f"Expected 0 errors after repair, got: {rep_val.errors}")
        self.assertEqual(len(rep_val.errors), 0)
        self.assertTrue(rep_val.laser_off_at_end)

        # Check specific fixes
        self.assertIn("G21", repaired)
        self.assertIn("G90", repaired)
        self.assertNotIn("M104", repaired)
        self.assertNotIn("E1.5", repaired)
        self.assertIn("F1200", repaired)
        self.assertIn("M5 S0", repaired)

    def test_repair_gcode_out_of_bounds_auto_shift(self):
        """Auto-repair engine must shift out-of-bounds artwork into bed limits."""
        oob_gcode = """G21
G90
F1000
M3 S500
G1 X-25.0 Y-10.0
G1 X50.0 Y50.0
M5 S0
"""
        init_rep = self.validator.validate(oob_gcode)
        self.assertFalse(init_rep.is_valid)
        self.assertTrue(any(e.error_code == "OUT_OF_BOUNDS" for e in init_rep.errors))

        repaired, repairs = GCodeValidator.repair_gcode(
            oob_gcode,
            bed_width=400.0,
            bed_height=400.0,
            margin_mm=3.0
        )
        self.assertTrue(any("Shifted artwork" in r for r in repairs))

        rep_val = self.validator.validate(repaired)
        self.assertTrue(rep_val.is_valid)
        self.assertEqual(len(rep_val.errors), 0)
        min_x, min_y, max_x, max_y = rep_val.bounding_box
        self.assertGreaterEqual(min_x, 0.0)
        self.assertGreaterEqual(min_y, 0.0)
        self.assertLessEqual(max_x, 400.0)
        self.assertLessEqual(max_y, 400.0)

    def test_simulate_to_job(self):
        """Simulate G-code string directly into a GCodeJobResult with metrics and segments."""
        gcode = """G21
G90
M3 S1000
G0 X10.0 Y10.0
G1 X60.0 Y10.0 F1200 S1000
G1 X60.0 Y60.0
M5 S0
G0 X0 Y0
"""
        job = GCodeValidator.simulate_to_job(gcode, self.settings)
        self.assertGreater(len(job.segments), 0)
        self.assertAlmostEqual(job.total_cut_dist_mm, 100.0, delta=1.0)
        self.assertGreater(job.total_rapid_dist_mm, 0.0)
        self.assertGreater(job.estimated_time_sec, 0.0)
        self.assertEqual(job.bounding_box[2], 60.0)
        self.assertEqual(job.bounding_box[3], 60.0)

    def test_validation_dialog_repair_mode(self):
        """ValidationDialog must support repaired code inspection and toolpath preview button."""
        import sys
        from PyQt6.QtWidgets import QApplication
        from laserforge.ui.validation_dialog import ValidationDialog

        app = QApplication.instance() or QApplication(sys.argv)
        gcode = "G21\nG90\nG1 X10 Y10 F1000 S500\nM5 S0\n"
        rep = self.validator.validate(gcode)
        sim_job = GCodeValidator.simulate_to_job(gcode, self.settings)

        dlg = ValidationDialog(
            report=rep,
            allow_proceed=True,
            repaired_gcode=gcode,
            repairs_applied=["Shifted artwork into bed envelope", "Prepended G21 header"],
            job_result=sim_job,
            settings=self.settings
        )
        self.assertTrue(dlg.allow_proceed)
        self.assertIsNotNone(dlg.btn_simulate)
        self.assertIsNotNone(dlg.btn_proceed)
        self.assertEqual(dlg.btn_proceed.text(), "🔥 Burn Repaired Code")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
