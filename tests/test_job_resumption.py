"""
Unit and Integration Tests for LaserForge Mid-Job Resumption & Network Flow Control.
Validates:
1. Modal state reconstruction (coordinates, units, modes, feedrates, laser power).
2. Safe lead-in preamble generation (M5 laser safety, G0 rapid transit, state restore).
3. Percentage to line resolution (line count and distance-based).
4. SerialController streaming and resumption tracking.
5. ResumeJobDialog interactive calculations and UI updates.
"""

import unittest
from unittest.mock import MagicMock, patch
import threading
import time

from PyQt6.QtWidgets import QApplication

from laserforge.core.job_resumer import JobResumer, ModalState, JobAnalysis, ResumedJob
from laserforge.core.serial_controller import SerialController, VirtualGrblSerial
from laserforge.ui.resume_job_dialog import ResumeJobDialog


SAMPLE_GCODE = """
; Header
G21 ; Millimeters
G90 ; Absolute
G17 ; XY Plane
G94 ; Feed per minute
M4 S0 ; Dynamic laser mode
G0 X0.0 Y0.0 ; Rapid home
G0 X10.0 Y20.0 ; Rapid to start
G1 X50.0 Y20.0 F1800 S600 ; Burn line 1
G1 X50.0 Y60.0 S800 ; Burn line 2
G1 X10.0 Y60.0 ; Burn line 3
G1 X10.0 Y20.0 ; Burn line 4
M5 ; Laser off
G0 X0.0 Y0.0 ; Rapid park
"""


class TestJobResumer(unittest.TestCase):

    def test_sanitize_lines(self):
        """Verifies comment stripping and empty line filtering."""
        lines = JobResumer.sanitize_lines(SAMPLE_GCODE)
        self.assertGreater(len(lines), 5)
        for line in lines:
            self.assertNotIn(";", line)
            self.assertTrue(len(line) > 0)

    def test_analyze_job(self):
        """Verifies spatial bounds, distances, and line counts."""
        analysis = JobResumer.analyze_job(SAMPLE_GCODE)
        self.assertEqual(analysis.total_lines, 13)
        self.assertGreater(analysis.total_cut_distance_mm, 0.0)
        self.assertGreater(analysis.total_rapid_distance_mm, 0.0)
        min_x, min_y, max_x, max_y = analysis.bounding_box
        self.assertAlmostEqual(min_x, 0.0, places=1)
        self.assertAlmostEqual(max_x, 50.0, places=1)
        self.assertAlmostEqual(min_y, 0.0, places=1)
        self.assertAlmostEqual(max_y, 60.0, places=1)

    def test_percentage_to_line_mapping(self):
        """Verifies percentage to line conversions."""
        lines = JobResumer.sanitize_lines(SAMPLE_GCODE)
        total = len(lines)

        idx_0 = JobResumer.get_line_for_percentage(lines, 0.0)
        self.assertEqual(idx_0, 0)

        idx_100 = JobResumer.get_line_for_percentage(lines, 100.0)
        self.assertEqual(idx_100, total - 1)

        idx_50 = JobResumer.get_line_for_percentage(lines, 50.0)
        self.assertAlmostEqual(idx_50, total // 2, delta=1)

        pct = JobResumer.get_percentage_for_line(lines, idx_50)
        self.assertAlmostEqual(pct, (idx_50 / total) * 100.0, places=2)

    def test_modal_state_extraction_midway(self):
        """Verifies exact modal state reconstruction at a given line index."""
        lines = JobResumer.sanitize_lines(SAMPLE_GCODE)
        # Line 7 is "G1 X50.0 Y20.0 F1800 S600"
        # Line 8 is "G1 X50.0 Y60.0 S800"
        # Line 9 is "G1 X10.0 Y60.0" (burn line 3, inherits S800, F1800, M4)
        state = JobResumer.extract_modal_state(lines, target_line_idx=9)

        self.assertEqual(state.line_index, 9)
        self.assertAlmostEqual(state.x, 50.0)
        self.assertAlmostEqual(state.y, 60.0)
        self.assertEqual(state.feedrate, 1800.0)
        self.assertEqual(state.spindle_power, 800.0)
        self.assertEqual(state.laser_mode, "M4")
        self.assertEqual(state.units, "G21")
        self.assertEqual(state.pos_mode, "G90")
        self.assertEqual(state.plane, "G17")
        self.assertTrue(state.is_cutting)

    def test_lead_in_preamble_safety(self):
        """Verifies that M5 is ALWAYS the first safety command before any rapid motion."""
        lines = JobResumer.sanitize_lines(SAMPLE_GCODE)
        state = JobResumer.extract_modal_state(lines, target_line_idx=8)
        preamble = JobResumer.build_lead_in_preamble(state, resume_line=lines[8], rapid_speed=2500.0)

        # M5 must be emitted before G0 rapid transit
        m5_index = -1
        g0_index = -1
        for i, cmd in enumerate(preamble):
            if cmd.startswith("M5"):
                m5_index = i
            elif cmd.startswith("G0 X"):
                g0_index = i

        self.assertNotEqual(m5_index, -1, "M5 safety command missing from preamble")
        self.assertNotEqual(g0_index, -1, "G0 positioning command missing from preamble")
        self.assertLess(m5_index, g0_index, "M5 must be issued BEFORE rapid travel to protect workpiece")

        # Coordinates must match prior state
        self.assertIn(f"X{state.x:.3f}", preamble[g0_index])
        self.assertIn(f"Y{state.y:.3f}", preamble[g0_index])

    def test_build_resumed_job(self):
        """Verifies that full synthesized G-code executes from target line to completion."""
        resumed = JobResumer.build_resumed_job(SAMPLE_GCODE, target_line_idx=8)
        self.assertEqual(resumed.resume_line_index, 8)
        self.assertGreater(len(resumed.preamble_lines), 0)
        self.assertGreater(len(resumed.remaining_lines), 0)
        self.assertIn("; === LaserForge Safe Mid-Job Resumption Preamble ===", resumed.full_gcode)
        self.assertIn("G1 X50.0 Y60.0 S800", resumed.full_gcode)

    def test_resume_at_rapid_move_keeps_laser_off(self):
        """Verifies that resuming on a rapid move (G0) does not power on the laser."""
        lines = JobResumer.sanitize_lines(SAMPLE_GCODE)
        # Line 6 is "G0 X10.0 Y20.0"
        state = JobResumer.extract_modal_state(lines, target_line_idx=6)
        preamble = JobResumer.build_lead_in_preamble(state, resume_line=lines[6])
        preamble_text = "\n".join(preamble)
        self.assertNotIn("M4 S", preamble_text)
        self.assertNotIn("M3 S", preamble_text)


class TestSerialControllerResumption(unittest.TestCase):

    def setUp(self):
        self.ctrl = SerialController()
        # Connect to virtual GRBL controller for in-memory testing
        self.ctrl.connect("VIRTUAL_GRBL", baud=115200)

    def tearDown(self):
        if self.ctrl.is_connected:
            self.ctrl.disconnect()

    def test_last_job_tracking(self):
        """Verifies SerialController records last job G-code and tracks stopped line index."""
        self.ctrl.start_job(SAMPLE_GCODE)
        time.sleep(0.1)
        self.assertEqual(self.ctrl.last_job_gcode, SAMPLE_GCODE)
        self.assertGreater(len(self.ctrl.last_job_lines), 5)

    def test_resume_job_from_position_api(self):
        """Verifies resume_job_from_position successfully synthesizes and starts resumed job."""
        self.ctrl.last_job_gcode = SAMPLE_GCODE
        self.ctrl.last_stopped_line_idx = 7

        success = self.ctrl.resume_job_from_position(line_idx=7)
        self.assertTrue(success)
        self.assertTrue(self.ctrl.is_streaming)
        self.ctrl.stop_streaming()

    def test_network_connection_detection(self):
        """Verifies is_network_connection returns True for tcp:// targets."""
        self.ctrl.port_name = "tcp://laserbridge.local:8088"
        self.assertTrue(self.ctrl.is_network_connection)

        self.ctrl.port_name = "/dev/ttyUSB0"
        self.assertFalse(self.ctrl.is_network_connection)


class TestResumeJobDialog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_initialization_and_sync(self):
        """Verifies that slider, spinboxes, and preamble preview stay synchronized."""
        dlg = ResumeJobDialog(SAMPLE_GCODE, initial_line_idx=5)
        self.assertEqual(dlg.line_spin.value(), 5)
        self.assertGreater(dlg.pct_spin.value(), 0.0)

        # Changing percentage updates line number
        dlg.pct_spin.setValue(75.0)
        self.assertGreater(dlg.line_spin.value(), 5)

        # Changing line number updates percentage
        dlg.line_spin.setValue(2)
        self.assertAlmostEqual(dlg.pct_spin.value(), (2 / dlg.total_lines) * 100.0, places=1)

        # Generated resumed G-code is valid
        resumed_gcode = dlg.get_resumed_gcode()
        self.assertIn("M5", resumed_gcode)
        self.assertIn("G0 X", resumed_gcode)


if __name__ == "__main__":
    unittest.main()
