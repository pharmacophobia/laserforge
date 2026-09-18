"""
Unit Tests for LaserForge Phase 5 & Phase 6 Advanced Features:
1. Auto-Focus Z-Probe Cycle Engine (G38.2/G38.3)
2. Interactive Caliper & Dimension Measuring Tool (TOOL_MEASURE)
3. Ultra-Wide Fisheye Lens Calibration & Rectification (cv2.fisheye)
4. 3D Curved Surface Toolpath Projection & Non-Planar G-Code
5. Workshop Audio Chime Engine & Notifications
6. Quick G-Code Macros & UI Integration
"""

import unittest
import os
import math
import numpy as np

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF

_app = QApplication.instance() or QApplication([])

from laserforge.core.models import PathEntity, RectEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.audio_alerts import AudioChimeEngine
from laserforge.core.z_probe_controller import ZProbeEngine, ZProbeSettings
from laserforge.core.fisheye_camera import FisheyeRectifier, FisheyeCalibrationData
from laserforge.core.surface_projector import SurfaceParameters, Surface3DProjector
from laserforge.ui.canvas_scene import LaserCanvasScene, TOOL_MEASURE, TOOL_SELECT
from laserforge.ui.z_probe_dialog import ZProbeStudioDialog
from laserforge.ui.surface_wrap_dialog import SurfaceWrapStudioDialog


class TestPhase5And6Features(unittest.TestCase):

    def test_audio_chime_generation(self):
        """Verify audio chime WAV synthesis and cached paths."""
        wav_path = AudioChimeEngine.get_wav_path("job_complete")
        self.assertTrue(os.path.exists(wav_path))
        self.assertGreater(os.path.getsize(wav_path), 500)

        probe_wav = AudioChimeEngine.get_wav_path("probe_trigger")
        self.assertTrue(os.path.exists(probe_wav))
        self.assertGreater(os.path.getsize(probe_wav), 200)

    def test_z_probe_gcode_and_prb_parsing(self):
        """Verify G38.2 G-code generation and GRBL response line parsing."""
        engine = ZProbeEngine()
        cfg = ZProbeSettings(
            probe_command="G38.2",
            feed_rate_mm_min=100.0,
            max_travel_mm=30.0,
            plate_thickness_mm=12.5,
            focal_offset_mm=2.5,
            retract_distance_mm=4.0
        )
        gcode = engine.generate_probe_gcode(cfg)

        self.assertTrue(any("G38.2 Z-30.000 F100.0" in line for line in gcode))
        self.assertTrue(any("G10 L20 P1 Z15.000" in line for line in gcode))
        self.assertTrue(any("G0 Z4.000" in line for line in gcode))

        # Test [PRB:...] response parsing
        resp = "[PRB:10.000,20.000,-18.450:1]"
        parsed = ZProbeEngine.parse_grbl_prb(resp)
        self.assertIsNotNone(parsed)
        x, y, z, ok = parsed
        self.assertEqual(x, 10.0)
        self.assertEqual(y, 20.0)
        self.assertEqual(z, -18.45)
        self.assertTrue(ok)

    def test_fisheye_rectifier(self):
        """Verify Fisheye camera rectification transforms distorted test frames."""
        calib = FisheyeCalibrationData(
            k1=-0.15, k2=0.04,
            fx=600.0, fy=600.0,
            cx=320.0, cy=240.0
        )
        rectifier = FisheyeRectifier(calib)

        test_img = np.zeros((480, 640, 3), dtype=np.uint8)
        test_img[100:380, 100:540] = 255

        undist = rectifier.undistort(test_img)
        self.assertEqual(undist.shape, (480, 640, 3))
        self.assertIsInstance(undist, np.ndarray)

    def test_surface_projector_3d_elevations(self):
        """Verify non-planar surface evaluations and micro-segmentation."""
        # 1. Cylinder
        p_cyl = SurfaceParameters(surface_type="Cylinder", radius_mm=50.0, axis="X")
        z_fn = Surface3DProjector.get_elevation_function(p_cyl, origin_x=0.0, origin_y=0.0)
        self.assertAlmostEqual(z_fn(0.0, 0.0), 0.0, places=3)
        self.assertLess(z_fn(0.0, 20.0), 0.0)

        # 2. Sphere
        p_sph = SurfaceParameters(surface_type="Sphere", radius_mm=40.0)
        z_sph_fn = Surface3DProjector.get_elevation_function(p_sph, origin_x=0.0, origin_y=0.0)
        self.assertAlmostEqual(z_sph_fn(0.0, 0.0), 0.0, places=3)
        self.assertLess(z_sph_fn(10.0, 10.0), 0.0)

        # 3. Contour subdivision
        raw_line = [(0.0, 0.0), (10.0, 0.0)]
        dense = Surface3DProjector.subdivide_contour(raw_line, max_step=1.0)
        self.assertEqual(len(dense), 11)

        # 4. Non-planar G-code generation
        proj_3d = [[(0.0, 0.0, 0.0), (5.0, 0.0, -1.2), (10.0, 0.0, -3.5)]]
        gcode = Surface3DProjector.generate_nonplanar_gcode(proj_3d, feed_rate=800.0, laser_power_s=500)
        self.assertTrue(any("Z-1.200" in line for line in gcode))
        self.assertTrue(any("M4 S500" in line for line in gcode))
        self.assertTrue(any("M5" in line for line in gcode))

    def test_caliper_measure_tool_in_scene(self):
        """Verify interactive caliper measurement tool in LaserCanvasScene."""
        lm = LayerManager()
        scene = LaserCanvasScene(lm)

        scene.set_active_tool(TOOL_MEASURE)
        self.assertEqual(scene.active_tool, TOOL_MEASURE)

        # Simulate measurement
        scene._measure_p1 = QPointF(10.0, 20.0)
        scene._measure_p2 = QPointF(40.0, 60.0)
        scene._update_measure_display()

        self.assertIsNotNone(scene._measure_group)
        self.assertEqual(len(scene._measure_group.childItems()), 5)

        # Switch tool resets caliper overlay
        scene.set_active_tool(TOOL_SELECT)
        self.assertIsNone(scene._measure_group)

    def test_z_probe_and_surface_wrap_dialogs(self):
        """Verify offscreen instantiation and signal binding of new studios."""
        # 1. ZProbeStudioDialog
        dlg_probe = ZProbeStudioDialog(serial_ctrl=None, settings=None)
        self.assertIsNotNone(dlg_probe.btn_probe)
        self.assertEqual(dlg_probe.spin_plate.value(), 15.0)

        # 2. SurfaceWrapStudioDialog
        rect = RectEntity(x=0.0, y=0.0, width=30.0, height=30.0)
        dlg_wrap = SurfaceWrapStudioDialog(entities=[rect])
        self.assertIsNotNone(dlg_wrap.canvas)
        self.assertGreater(len(dlg_wrap.projected_3d), 0)


if __name__ == "__main__":
    unittest.main()
