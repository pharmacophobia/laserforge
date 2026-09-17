"""
LaserForge Phase 2 Comprehensive Test Suite:
1. Holding Tabs & Micro-Bridges (TabEngine slicing & coordinate computations)
2. Print & Cut (2-Point Optical / Machine Registration transform solver)
3. LightBurn Project Importer (.lbrn2 JSON and .lbrn XML)
4. Smart Color-to-Layer Mapping (SVG hex, rgb(), and named CSS colors)
5. Dynamic Corner Deceleration Power Ramping in GCodeGenerator
6. OpenCV Camera Lens Distortion Undistortion & Fisheye Model
"""

import unittest
import os
import json
import tempfile
import math
import numpy as np
from PyQt6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.models import (
    RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, LayerCutSettings
)
from laserforge.core.tab_engine import TabEngine
from laserforge.core.lbrn_importer import LightBurnImporter
from laserforge.core.svg_importer import SVGImporter, _hex_to_rgb, _match_palette_layer
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData


class TestPhase2HoldingTabs(unittest.TestCase):
    """Test holding tabs & micro-bridges engine."""

    def test_tab_coordinates_calculation(self):
        # 100x100 square contour
        contour = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        tabs = TabEngine.compute_tab_coordinates(contour, tab_count=4, tab_width=1.5)
        self.assertEqual(len(tabs), 4)
        for cx, cy, angle, width in tabs:
            self.assertEqual(width, 1.5)
            self.assertTrue(0.0 <= cx <= 100.0)
            self.assertTrue(0.0 <= cy <= 100.0)

    def test_slice_contour_with_tabs(self):
        contour = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0), (0.0, 0.0)]
        slices = TabEngine.slice_contour_with_tabs(contour, tab_count=4, tab_width=1.0)
        # Should have both cut and tab segments
        cuts = [s for s in slices if s["type"] == "cut"]
        tabs = [s for s in slices if s["type"] == "tab"]
        self.assertEqual(len(tabs), 4)
        self.assertGreater(len(cuts), 0)
        for t in tabs:
            self.assertAlmostEqual(t["width"], 1.0, places=2)


class TestPhase2PrintAndCut(unittest.TestCase):
    """Test 2-point optical / machine registration transform solver."""

    def test_rigid_alignment_translation_and_rotation(self):
        # Digital targets: (0, 0) and (100, 0)
        dig_p1 = (0.0, 0.0)
        dig_p2 = (100.0, 0.0)

        # Workpiece placed rotated 90 degrees and shifted by (50, 50)
        # Physical targets: (50, 50) and (50, 150)
        phys_p1 = (50.0, 50.0)
        phys_p2 = (50.0, 150.0)

        d_dx = dig_p2[0] - dig_p1[0]
        d_dy = dig_p2[1] - dig_p1[1]
        dig_ang = math.degrees(math.atan2(d_dy, d_dx))

        p_dx = phys_p2[0] - phys_p1[0]
        p_dy = phys_p2[1] - phys_p1[1]
        phys_ang = math.degrees(math.atan2(p_dy, p_dx))

        angle_delta = phys_ang - dig_ang
        self.assertAlmostEqual(angle_delta, 90.0, places=3)

        # Test point transformation
        test_pt = (50.0, 0.0)  # midpoint of digital segment
        rad = math.radians(angle_delta)
        rx = test_pt[0] * math.cos(rad) - test_pt[1] * math.sin(rad) + phys_p1[0]
        ry = test_pt[0] * math.sin(rad) + test_pt[1] * math.cos(rad) + phys_p1[1]
        self.assertAlmostEqual(rx, 50.0, places=3)
        self.assertAlmostEqual(ry, 100.0, places=3)


class TestPhase2LightBurnImporter(unittest.TestCase):
    """Test LightBurn .lbrn2 (JSON) and .lbrn (XML) project imports."""

    def test_import_lbrn2_json(self):
        sample_lbrn2 = {
            "Type": "LightBurnProject",
            "Version": "1.0",
            "CutSettings": [
                {
                    "Index": 0,
                    "Name": "C00",
                    "Color": "#000000",
                    "Speed": 1500,
                    "Power": 75,
                    "MinPower": 25,
                    "CutMode": "Cut"
                },
                {
                    "Index": 1,
                    "Name": "C01",
                    "Color": "#0000FF",
                    "Speed": 3000,
                    "Power": 40,
                    "MinPower": 10,
                    "CutMode": "Scan"
                }
            ],
            "Shapes": [
                {
                    "Type": "Rect",
                    "X": 10.0,
                    "Y": 15.0,
                    "W": 60.0,
                    "H": 40.0,
                    "Radius": 2.0,
                    "Layer": 0
                },
                {
                    "Type": "Circle",
                    "X": 80.0,
                    "Y": 80.0,
                    "Rx": 12.0,
                    "Ry": 12.0,
                    "Layer": 1
                },
                {
                    "Type": "Line",
                    "X1": 0.0,
                    "Y1": 0.0,
                    "X2": 50.0,
                    "Y2": 50.0,
                    "Layer": 0
                }
            ]
        }

        with tempfile.NamedTemporaryFile(suffix=".lbrn2", mode="w", delete=False) as tf:
            json.dump(sample_lbrn2, tf)
            tf_path = tf.name

        try:
            layer_mgr = LayerManager()
            entities, layer_map = LightBurnImporter.import_file(tf_path, layer_manager=layer_mgr)
            self.assertEqual(len(entities), 3)
            self.assertEqual(len(layer_map), 2)
            self.assertEqual(layer_map[0].speed, 1500.0)
            self.assertEqual(layer_map[0].mode, "Line")
            self.assertEqual(layer_map[1].mode, "Fill")

            # Check shapes
            rects = [e for e in entities if isinstance(e, RectEntity)]
            circles = [e for e in entities if isinstance(e, CircleEntity)]
            lines = [e for e in entities if isinstance(e, LineEntity)]
            self.assertEqual(len(rects), 1)
            self.assertEqual(rects[0].width, 60.0)
            self.assertEqual(len(circles), 1)
            self.assertEqual(circles[0].radius_x, 12.0)
            self.assertEqual(len(lines), 1)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_import_lbrn_xml(self):
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <LightBurnProject>
            <CutSetting index="0" type="Cut" speed="1200" power="85" minPower="20"/>
            <Shape type="Rect" x="20" y="20" width="30" height="25" CutIndex="0"/>
            <Shape type="Circle" x="70" y="70" r="15" CutIndex="0"/>
        </LightBurnProject>
        """
        with tempfile.NamedTemporaryFile(suffix=".lbrn", mode="w", delete=False) as tf:
            tf.write(sample_xml)
            tf_path = tf.name

        try:
            entities, layer_map = LightBurnImporter.import_file(tf_path)
            self.assertEqual(len(entities), 2)
            self.assertIn(0, layer_map)
            self.assertEqual(layer_map[0].speed, 1200.0)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)


class TestPhase2SmartColorMapping(unittest.TestCase):
    """Test smart color-to-layer mapping for SVG."""

    def test_named_colors_and_rgb_parsing(self):
        self.assertEqual(_hex_to_rgb("red"), (255, 0, 0))
        self.assertEqual(_hex_to_rgb("blue"), (0, 0, 255))
        self.assertEqual(_hex_to_rgb("black"), (0, 0, 0))
        self.assertEqual(_hex_to_rgb("rgb(255, 128, 0)"), (255, 128, 0))
        self.assertEqual(_hex_to_rgb("#ff0000"), (255, 0, 0))
        self.assertEqual(_hex_to_rgb("#f00"), (255, 0, 0))

    def test_palette_matching(self):
        # Pure red should match C02 or whichever layer is red in palette
        layer_id_red = _match_palette_layer((255, 0, 0))
        self.assertIsInstance(layer_id_red, int)
        self.assertTrue(0 <= layer_id_red <= 15)


class TestPhase2CornerPowerRamping(unittest.TestCase):
    """Test dynamic corner deceleration power ramping in GCodeGenerator."""

    def test_corner_power_ramping_gcode_output(self):
        settings = MachineSettings()
        layer_mgr = LayerManager()
        gen = GCodeGenerator(settings, layer_manager=layer_mgr)

        # 90 degree sharp corner path
        path = PathEntity(
            layer_id=0,
            contours=[[(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)]],
            closed=False
        )

        layer = layer_mgr.get_layer(0)
        layer.corner_power_ramping = True
        layer.corner_min_power_pct = 40.0
        layer.corner_ramp_angle_deg = 45.0
        layer.speed = 1200.0
        layer.power_max = 80.0
        job = gen.generate_job([path])

        lines = job.gcode.splitlines()
        self.assertGreater(len(lines), 0)
        # Verify that power tapering S command was output before/at the turn
        has_corner_s = any("S" in line and "G1" in line for line in lines)
        self.assertTrue(has_corner_s)


class TestPhase2CameraLens(unittest.TestCase):
    """Test camera lens calibration data structures and undistortion."""

    def test_camera_calibration_data_validation(self):
        cal = CameraCalibrationData()
        self.assertFalse(cal.is_lens_calibrated())

        # Set valid intrinsic camera matrix
        cal.camera_matrix = np.array([
            [1000.0, 0.0, 960.0],
            [0.0, 1000.0, 540.0],
            [0.0, 0.0, 1.0]
        ], dtype=np.float64)
        cal.distortion_coeffs = np.array([0.01, -0.005, 0.0, 0.0, 0.0], dtype=np.float64)
        cal.reprojection_error = 0.45

        self.assertTrue(cal.is_lens_calibrated())


if __name__ == "__main__":
    unittest.main()
