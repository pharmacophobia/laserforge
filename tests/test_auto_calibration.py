"""
Unit and Integration Tests for LaserForge Automated Workbed & Camera Coordinate Calibration Engine.

Covers:
1. Data models (CalibrationPoint, AutoCalibrationConfig, AutoCalibrationResult)
2. Computer vision fiducial detectors (ArUco, concentric circles, burn marks, crosshairs, synthetic markers)
3. Canonical geometric sorting and laser bed coordinate matching
4. Homography math, affine decomposition, gantry skew calculation, and reprojection error
5. Bi-directional coordinate mapping (camera_to_laser, laser_to_camera)
6. Parametric G-code toolpath generation and CAD entity generation
7. Interactive UI components (AutoCalibrationDialog, AutoCalibrationVisualWidget, Wizard & MainWindow integration)
"""

import unittest
from unittest.mock import patch
import os
import math
import tempfile
import numpy as np

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

_app = QApplication.instance() or QApplication([])

import cv2
from laserforge.config import MachineSettings
from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
from laserforge.core.auto_calibration import (
    AutoCalibrationEngine, AutoCalibrationConfig, AutoCalibrationResult,
    CalibrationPoint, FiducialDetector
)
from laserforge.ui.auto_calibration_dialog import AutoCalibrationDialog, AutoCalibrationVisualWidget
from laserforge.ui.camera_calibration_wizard import CameraCalibrationWizardDialog
from laserforge.ui.workbed_setup_dialog import WorkbedSetupDialog


class TestAutoCalibrationDataModels(unittest.TestCase):
    """Tests data structures and serialization."""

    def test_calibration_point_dict(self):
        pt = CalibrationPoint(
            camera_point=(150.5, 220.3),
            laser_point_mm=(40.0, 40.0),
            marker_id=0,
            label="P1 (Top-Left)",
            reprojection_error_px=0.25,
            reprojection_error_mm=0.08
        )
        d = pt.to_dict()
        self.assertEqual(d["marker_id"], 0)
        self.assertEqual(d["camera_point"], [150.5, 220.3])
        self.assertEqual(d["laser_point_mm"], [40.0, 40.0])
        self.assertEqual(d["reprojection_error_mm"], 0.08)

    def test_calibration_config_defaults(self):
        cfg = AutoCalibrationConfig()
        self.assertEqual(cfg.bed_width_mm, 400.0)
        self.assertEqual(cfg.bed_height_mm, 400.0)
        self.assertEqual(cfg.fiducial_inset_mm, 40.0)
        self.assertEqual(cfg.pattern_type, "auto")
        self.assertEqual(cfg.scale_px_per_mm, 3.0)
        self.assertTrue(cfg.auto_undistort)

    def test_calibration_result_dict(self):
        res = AutoCalibrationResult(
            success=True,
            quality_score=94.5,
            reprojection_error_rms_mm=0.12,
            gantry_skew_deg=0.04
        )
        d = res.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["quality_score"], 94.5)
        self.assertEqual(d["reprojection_error_rms_mm"], 0.12)
        self.assertEqual(d["gantry_skew_deg"], 0.04)


class TestFiducialDetector(unittest.TestCase):
    """Tests computer vision detectors for all marker types."""

    def test_detect_synthetic_simulated_fiducials(self):
        cam = CameraEngine()
        cam.is_mock = True
        frame = cam.capture_frame(draw_guides=True)
        self.assertIsNotNone(frame)

        pts = FiducialDetector.detect_synthetic_simulated_fiducials(frame)
        self.assertEqual(len(pts), 4)
        for u, v in pts:
            self.assertGreater(u, 100)
            self.assertGreater(v, 100)

    def test_detect_aruco_markers(self):
        # Create a test canvas with 4 ArUco markers at known positions
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        canvas = np.full((1080, 1920, 3), 240, dtype=np.uint8)

        target_positions = {
            0: (250, 250),
            1: (1650, 250),
            2: (1650, 850),
            3: (250, 850)
        }
        for m_id, (cx, cy) in target_positions.items():
            marker = cv2.aruco.generateImageMarker(dictionary, m_id, 100)
            marker_bgr = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
            canvas[cy - 50:cy + 50, cx - 50:cx + 50] = marker_bgr

        centers, corners = FiducialDetector.detect_aruco(canvas, "DICT_4X4_50")
        self.assertEqual(len(centers), 4)
        for m_id, expected_pt in target_positions.items():
            self.assertIn(m_id, centers)
            det_x, det_y = centers[m_id]
            self.assertAlmostEqual(det_x, expected_pt[0], delta=2.0)
            self.assertAlmostEqual(det_y, expected_pt[1], delta=2.0)

    def test_detect_concentric_circles(self):
        canvas = np.full((600, 800, 3), 255, dtype=np.uint8)
        centers_expected = [(200, 200), (600, 200), (600, 450), (200, 450)]

        for cx, cy in centers_expected:
            # Outer black circle
            cv2.circle(canvas, (cx, cy), 35, (0, 0, 0), 4)
            # Inner black circle
            cv2.circle(canvas, (cx, cy), 15, (0, 0, 0), -1)

        detected = FiducialDetector.detect_concentric_circles(canvas, min_radius=10, max_radius=80)
        self.assertGreaterEqual(len(detected), 4)

    def test_detect_laser_burn_dots(self):
        canvas = np.full((600, 800, 3), 240, dtype=np.uint8)  # Wood tone
        burn_centers = [(150, 150), (650, 150), (650, 450), (150, 450)]
        for cx, cy in burn_centers:
            cv2.circle(canvas, (cx, cy), 12, (20, 15, 10), -1)  # Dark burn

        detected = FiducialDetector.detect_laser_burn_dots(canvas)
        self.assertGreaterEqual(len(detected), 4)


class TestAutoCalibrationEngine(unittest.TestCase):
    """Tests geometric point matching, homography solving, and kinematics decomposition."""

    def setUp(self):
        self.cfg = AutoCalibrationConfig(
            bed_width_mm=400.0,
            bed_height_mm=400.0,
            fiducial_inset_mm=40.0,
            scale_px_per_mm=3.0
        )
        self.engine = AutoCalibrationEngine(self.cfg)

    def test_sort_quadrant_points(self):
        # Provide 4 unordered points
        unordered = [
            (1600.0, 900.0),  # BR (P3)
            (300.0, 200.0),   # TL (P1)
            (300.0, 900.0),   # BL (P4)
            (1600.0, 200.0)   # TR (P2)
        ]
        sorted_pts = self.engine.sort_quadrant_points(unordered)
        self.assertEqual(len(sorted_pts), 4)
        self.assertEqual(sorted_pts[0], (300.0, 200.0))   # P1: Top-Left
        self.assertEqual(sorted_pts[1], (1600.0, 200.0))  # P2: Top-Right
        self.assertEqual(sorted_pts[2], (1600.0, 900.0))  # P3: Bottom-Right
        self.assertEqual(sorted_pts[3], (300.0, 900.0))   # P4: Bottom-Left

    def test_match_points_to_laser_bed(self):
        detected = [
            (300.0, 200.0),
            (1600.0, 200.0),
            (1600.0, 900.0),
            (300.0, 900.0)
        ]
        matched = self.engine.match_points_to_laser_bed(detected)
        self.assertEqual(len(matched), 4)
        self.assertEqual(matched[0].laser_point_mm, (40.0, 40.0))
        self.assertEqual(matched[1].laser_point_mm, (360.0, 40.0))
        self.assertEqual(matched[2].laser_point_mm, (360.0, 360.0))
        self.assertEqual(matched[3].laser_point_mm, (40.0, 360.0))

    def test_solve_calibration_accuracy(self):
        matched = [
            CalibrationPoint(camera_point=(300.0, 200.0), laser_point_mm=(40.0, 40.0), marker_id=0, label="P1"),
            CalibrationPoint(camera_point=(1500.0, 200.0), laser_point_mm=(360.0, 40.0), marker_id=1, label="P2"),
            CalibrationPoint(camera_point=(1500.0, 800.0), laser_point_mm=(360.0, 360.0), marker_id=2, label="P3"),
            CalibrationPoint(camera_point=(300.0, 800.0), laser_point_mm=(40.0, 360.0), marker_id=3, label="P4")
        ]
        result = self.engine.solve_calibration(matched)
        self.assertTrue(result.success)
        self.assertIsNotNone(result.homography_matrix)
        self.assertIsNotNone(result.camera_to_laser_matrix)
        self.assertIsNotNone(result.laser_to_camera_matrix)
        self.assertLess(result.reprojection_error_rms_mm, 0.001)
        self.assertGreater(result.quality_score, 80.0)
        self.assertAlmostEqual(result.gantry_skew_deg, 0.0, delta=0.5)

    def test_end_to_end_synthetic_frame_calibration(self):
        cam = CameraEngine()
        cam.is_mock = True
        frame = cam.capture_frame(draw_guides=True)

        res = self.engine.calibrate_from_frame(frame, cam)
        self.assertTrue(res.success)
        self.assertEqual(len(res.points), 4)
        self.assertLess(res.reprojection_error_rms_mm, 0.01)
        self.assertIsNotNone(res.annotated_frame)
        self.assertTrue(cam.calibration.is_bed_aligned())

    def test_bi_directional_coordinate_conversion(self):
        cam = CameraEngine()
        cam.is_mock = True
        frame = cam.capture_frame(draw_guides=True)
        res = self.engine.calibrate_from_frame(frame, cam)
        self.assertTrue(res.success)

        # Test P1 round-trip conversion
        u_orig, v_orig = res.points[0].camera_point
        mapped_laser = self.engine.camera_to_laser(u_orig, v_orig, res)
        self.assertIsNotNone(mapped_laser)
        self.assertAlmostEqual(mapped_laser[0], 40.0, delta=0.1)
        self.assertAlmostEqual(mapped_laser[1], 40.0, delta=0.1)

        mapped_cam = self.engine.laser_to_camera(mapped_laser[0], mapped_laser[1], res)
        self.assertIsNotNone(mapped_cam)
        self.assertAlmostEqual(mapped_cam[0], u_orig, delta=0.1)
        self.assertAlmostEqual(mapped_cam[1], v_orig, delta=0.1)

    def test_save_and_load_applied_calibration(self):
        cam = CameraEngine()
        cam.is_mock = True
        frame = cam.capture_frame(draw_guides=True)
        res = self.engine.calibrate_from_frame(frame, cam)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_path = tf.name

        try:
            cam.calibration.save_to_file(temp_path)
            loaded = CameraCalibrationData.load_from_file(temp_path)
            self.assertTrue(loaded.is_bed_aligned())
            self.assertEqual(len(loaded.camera_fiducials), 4)
            self.assertEqual(len(loaded.bed_fiducials_mm), 4)
            self.assertAlmostEqual(loaded.bed_width_mm, 400.0)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestCalibrationGCodeAndCAD(unittest.TestCase):
    """Tests toolpath emission and vector entity creation."""

    def setUp(self):
        self.engine = AutoCalibrationEngine()

    def test_generate_calibration_gcode(self):
        gcode = self.engine.generate_calibration_gcode(
            bed_width_mm=400.0,
            bed_height_mm=400.0,
            inset_mm=30.0,
            pattern_type="concentric_circle",
            feed_rate=1500.0,
            power_pct=20.0
        )
        self.assertIn("G21", gcode)
        self.assertIn("G90", gcode)
        self.assertIn("M4", gcode)
        self.assertIn("S200", gcode)  # 20% of 1000
        self.assertIn("F1500", gcode)
        self.assertIn("P1_TopLeft", gcode)
        self.assertIn("P4_BottomLeft", gcode)
        self.assertIn("Rapid to parking position", gcode)
        self.assertIn("M2", gcode)

    def test_generate_calibration_crosshair_gcode(self):
        gcode = self.engine.generate_calibration_gcode(pattern_type="crosshair")
        self.assertIn("crosshair", gcode.lower())
        self.assertIn("G1 X", gcode)

    def test_generate_calibration_entities(self):
        ents = self.engine.generate_calibration_entities(layer_id=12)
        self.assertEqual(len(ents), 16)  # 4 fiducials * (2 circles + 2 cross lines) = 16
        for e in ents:
            self.assertEqual(e.layer_id, 12)


class TestAutoCalibrationUI(unittest.TestCase):
    """Tests UI dialogs and widgets."""

    def setUp(self):
        self.cam = CameraEngine()
        self.cam.is_mock = True
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0)

    def test_visual_widget_rendering(self):
        widget = AutoCalibrationVisualWidget()
        frame = self.cam.capture_frame(draw_guides=True)
        widget.set_display_frame(frame)
        self.assertIsNotNone(widget.pixmap())
        self.assertFalse(widget.pixmap().isNull())

    def test_auto_calibration_dialog_lifecycle(self):
        dlg = AutoCalibrationDialog(camera_engine=self.cam, settings=self.settings)
        # The test camera is a simulated/mock engine; acknowledge that so the
        # "no real camera connected" guard does not block the lifecycle test.
        dlg._allow_mock_calibration = True
        try:
            self.assertIn("Auto-Calibration Studio", dlg.windowTitle())
            self.assertFalse(dlg.btn_apply.isEnabled())

            # Trigger auto-detect
            dlg._run_auto_detect_and_align()
            self.assertIsNotNone(dlg.current_result)
            self.assertTrue(dlg.current_result.success)
            self.assertTrue(dlg.btn_apply.isEnabled())
            self.assertIn("RMS", dlg.lbl_rms.text())
            self.assertIn("Skew", dlg.lbl_skew.text())

            # Test residual table rows
            self.assertEqual(dlg.table_residuals.rowCount(), 4)
            self.assertEqual(dlg.table_residuals.item(0, 0).text(), "P1")
        finally:
            dlg.close()

    def test_wizard_step3_auto_detect_button(self):
        wiz = CameraCalibrationWizardDialog(self.cam, bed_width_mm=400.0, bed_height_mm=400.0)
        try:
            self.assertTrue(hasattr(wiz, "btn_auto_detect"))
            self.assertTrue(hasattr(wiz, "btn_auto_studio"))
            # Trigger auto-detect in wizard with mocked message box
            with patch("PyQt6.QtWidgets.QMessageBox.information"):
                wiz._on_auto_detect_step3_points()
            self.assertEqual(len(wiz.picked_points), 4)
            self.assertEqual(len(wiz.point_picker.points), 4)
            self.assertIn("Auto-detected 4 markers", wiz.lbl_picker_status.text())
        finally:
            wiz.close()

    def test_workbed_setup_dialog_auto_calib_integration(self):
        from laserforge.core.layer_manager import LayerManager
        from laserforge.ui.canvas_scene import LaserCanvasScene
        scene = LaserCanvasScene(LayerManager())
        dlg = WorkbedSetupDialog(settings=self.settings, scene=scene)
        try:
            self.assertTrue(hasattr(dlg, "btn_open_auto_calib"))
            self.assertIn("Auto-Calibration Studio", dlg.btn_open_auto_calib.text())
        finally:
            dlg.close()

    def test_main_window_action_registered(self):
        from laserforge.ui.main_window import MainWindow
        win = MainWindow(start_tutorial=False)
        try:
            self.assertTrue(hasattr(win.actions, "auto_calibrate"))
            self.assertEqual(win.actions.auto_calibrate.shortcut().toString(), "Ctrl+Alt+A")
            self.assertTrue(hasattr(win, "open_auto_calibration_dialog"))
        finally:
            try:
                win.serial_ctrl.disconnect()
            except Exception:
                pass
            win.close()


if __name__ == "__main__":
    unittest.main()
