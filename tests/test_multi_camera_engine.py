"""
Unit tests for LaserForge Multi-Camera Panoramic Bed Stitching Engine & UI Studio.
Tests:
- CameraSlotConfig & MultiCameraConfig dictionary serialization
- Simulated perspective homography generation for wide-format beds
- Multi-camera frame stitching with all blend modes (LinearFeather, DistanceTransform, MaxPriority, HardSeam)
- Seam contour demarcation rendering
- MultiCameraSetupDialog UI creation and signal propagation (offscreen safe)
"""

import os
import unittest
import numpy as np

from PyQt6.QtWidgets import QApplication
import pytest

from laserforge.core.camera_engine import HAS_CV2, CameraEngine, CameraCalibrationData
from laserforge.core.multi_camera_engine import (
    MultiCameraEngine, MultiCameraConfig, CameraSlotConfig
)
from laserforge.ui.multi_camera_dialog import MultiCameraSetupDialog, PanoramicPreviewWidget


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestMultiCameraEngine(unittest.TestCase):
    """Test suite for MultiCameraEngine core algorithms and configurations."""

    def setUp(self):
        self.config = MultiCameraConfig._create_default_dual_setup()
        self.config.bed_width_mm = 1000.0
        self.config.bed_height_mm = 600.0
        self.config.scale_px_per_mm = 1.0  # 1px per mm for fast test execution
        self.engine = MultiCameraEngine(self.config)

    def test_config_serialization(self):
        d = self.config.to_dict()
        self.assertIn("slots", d)
        self.assertEqual(len(d["slots"]), 2)
        self.assertEqual(d["bed_width_mm"], 1000.0)

        restored = MultiCameraConfig.from_dict(d)
        self.assertEqual(restored.bed_width_mm, 1000.0)
        self.assertEqual(len(restored.slots), 2)
        self.assertEqual(restored.slots[0].slot_id, "cam_left")
        self.assertEqual(restored.slots[1].slot_id, "cam_right")

    def test_slot_engine_initialization_and_homography(self):
        self.assertTrue(self.engine.is_calibrated())
        left_eng = self.engine.get_slot_engine("cam_left")
        self.assertIsNotNone(left_eng)
        self.assertTrue(left_eng.calibration.is_bed_aligned())
        self.assertIsNotNone(left_eng.calibration.homography_matrix)

        right_eng = self.engine.get_slot_engine("cam_right")
        self.assertIsNotNone(right_eng)
        self.assertTrue(right_eng.calibration.is_bed_aligned())

    def test_synthetic_test_pattern(self):
        pattern = self.engine.generate_synthetic_stitched_test_pattern()
        self.assertIsNotNone(pattern)
        self.assertEqual(len(pattern.shape), 3)
        h, w, ch = pattern.shape
        self.assertEqual(w, 1000)
        self.assertEqual(h, 600)
        self.assertEqual(ch, 3)

    @unittest.skipUnless(HAS_CV2, "Requires OpenCV cv2")
    def test_stitching_linear_feather_blend(self):
        self.config.blend_mode = "LinearFeather"
        self.config.feather_overlap_mm = 50.0

        # Create mock captured frames for left and right cameras
        cam_w, cam_h = 1920, 1080
        left_frame = np.full((cam_h, cam_w, 3), (120, 40, 20), dtype=np.uint8)
        right_frame = np.full((cam_h, cam_w, 3), (20, 40, 120), dtype=np.uint8)

        mock_frames = {
            "cam_left": left_frame,
            "cam_right": right_frame
        }

        stitched = self.engine.stitch_orthophoto(frames=mock_frames, draw_seams=False)
        self.assertIsNotNone(stitched)
        h, w, ch = stitched.shape
        self.assertEqual(w, 1000)
        self.assertEqual(h, 600)
        self.assertEqual(ch, 3)
        # Composite should contain valid image data
        self.assertGreater(np.mean(stitched), 0)

    @unittest.skipUnless(HAS_CV2, "Requires OpenCV cv2")
    def test_stitching_all_blend_modes(self):
        cam_w, cam_h = 1920, 1080
        left_frame = np.full((cam_h, cam_w, 3), 100, dtype=np.uint8)
        right_frame = np.full((cam_h, cam_w, 3), 150, dtype=np.uint8)
        mock_frames = {"cam_left": left_frame, "cam_right": right_frame}

        for mode in ["LinearFeather", "DistanceTransform", "MaxPriority", "HardSeam"]:
            self.config.blend_mode = mode
            stitched = self.engine.stitch_orthophoto(frames=mock_frames, draw_seams=True)
            self.assertIsNotNone(stitched)
            self.assertEqual(stitched.shape, (600, 1000, 3))


class TestMultiCameraUI(unittest.TestCase):
    """Test suite for MultiCameraSetupDialog UI controls."""

    def setUp(self):
        self.config = MultiCameraConfig._create_default_dual_setup()
        self.config.bed_width_mm = 500.0
        self.config.bed_height_mm = 300.0
        self.config.scale_px_per_mm = 1.0
        self.engine = MultiCameraEngine(self.config)
        self.dlg = MultiCameraSetupDialog(engine=self.engine)

    def tearDown(self):
        self.dlg.close()

    def test_ui_initialization_and_table(self):
        self.assertEqual(self.dlg.table_slots.rowCount(), 2)
        self.assertEqual(self.dlg.spin_bed_w.value(), 500.0)
        self.assertEqual(self.dlg.spin_bed_h.value(), 300.0)
        self.assertIsNotNone(self.dlg._last_stitched_frame)

    def test_add_and_remove_slot(self):
        initial_count = self.dlg.table_slots.rowCount()
        self.dlg._add_slot()
        self.assertEqual(self.dlg.table_slots.rowCount(), initial_count + 1)

        self.dlg.table_slots.selectRow(self.dlg.table_slots.rowCount() - 1)
        self.dlg._remove_selected_slot()
        self.assertEqual(self.dlg.table_slots.rowCount(), initial_count)

    def test_push_to_canvas_signal(self):
        from unittest.mock import patch
        received_frames = []
        self.dlg.panoramic_stitched_ready.connect(lambda f: received_frames.append(f))
        with patch("PyQt6.QtWidgets.QMessageBox.information"):
            self.dlg._push_to_canvas()
        self.assertEqual(len(received_frames), 1)
        self.assertIsNotNone(received_frames[0])


if __name__ == "__main__":
    unittest.main()
