"""
Unit tests for LaserForge commercial & Phase 1 features:
- Virtual GRBL loopback controller & real-time overrides
- Rubber-band convex-hull contour framing
- Asymmetric X/Y kerf offset compensation
- Centerline / skeleton image vectorization
- Parametric Kerf Test Gauge generation
- Canvas Laser Reticle position indicator
"""

import unittest
import numpy as np
from PIL import Image

from laserforge.core.serial_controller import VirtualGrblSerial, SerialController
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.models import PathEntity
from laserforge.core.kerf_engine import KerfEngine
from laserforge.core.image_tracer import ImageTracer
from laserforge.core.kerf_test_generator import KerfTestGenerator, KerfTestSettings


class TestVirtualGrblController(unittest.TestCase):
    """Test VirtualGrblSerial machine simulator and real-time overrides."""

    def setUp(self):
        self.sim = VirtualGrblSerial(port="VIRTUAL_GRBL")

    def tearDown(self):
        self.sim.close()

    def test_startup_and_status_poll(self):
        self.assertTrue(self.sim.is_open)
        # Read Grbl greeting
        banner = self.sim.read(self.sim.in_waiting)
        self.assertIn(b"Grbl 1.1", banner)

        # Send status poll command '?'
        self.sim.write(b"?")
        status = self.sim.readline().decode()
        self.assertIn("<Idle|MPos:0.000,0.000,0.000", status)
        self.assertIn("Ov:100,100,100", status)

    def test_gcode_execution_and_motion(self):
        self.sim.reset_input_buffer()
        # Execute rapid motion to X50 Y25
        self.sim.write(b"G0 X50 Y25\n")
        resp = self.sim.readline().decode()
        self.assertEqual(resp.strip(), "ok")

        # Check status position updated
        self.sim.write(b"?")
        status = self.sim.readline().decode()
        self.assertIn("MPos:50.000,25.000,0.000", status)

    def test_realtime_overrides(self):
        self.sim.reset_input_buffer()
        # 0x91 is Feed +10%
        self.sim.write(bytes([0x91]))
        self.sim.write(b"?")
        status = self.sim.readline().decode()
        self.assertIn("Ov:110,100,100", status)

        # 0x96 is Rapid 50%
        self.sim.write(bytes([0x96]))
        self.sim.write(b"?")
        status = self.sim.readline().decode()
        self.assertIn("Ov:110,50,100", status)

        # 0x9A is Power +10%
        self.sim.write(bytes([0x9A]))
        self.sim.write(b"?")
        status = self.sim.readline().decode()
        self.assertIn("Ov:110,50,110", status)

        # 0x90 is Feed 100% Reset
        self.sim.write(bytes([0x90]))
        self.sim.write(b"?")
        status = self.sim.readline().decode()
        self.assertIn("Ov:100,50,110", status)


class TestContourFraming(unittest.TestCase):
    """Test rubber-band convex-hull contour framing G-code generation."""

    def setUp(self):
        self.settings = MachineSettings(framing_power_pct=0.5, max_s_value=1000, framing_speed=1800)
        self.layer_manager = LayerManager()
        self.gen = GCodeGenerator(self.settings, self.layer_manager)

    def test_framing_gcode_convex_hull(self):
        # Create an L-shaped entity (3 corners: (0,0), (10,0), (0,20))
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (5.0, 5.0), (5.0, 20.0), (0.0, 20.0)]
        ent = PathEntity(layer_id=0, contours=[pts], closed=True)

        gcode = self.gen.generate_contour_framing_gcode([ent])
        lines = gcode.splitlines()

        # Check header comments and setup
        self.assertTrue(any("Rubber-Band Contour Framing" in l for l in lines))
        self.assertTrue(any("G21" in l for l in lines))
        self.assertTrue(any("G90" in l for l in lines))

        # Check laser power (0.5% of 1000 = S5) and feed F1800
        self.assertTrue(any("S5" in l and ("M3" in l or "M4" in l) for l in lines))
        self.assertTrue(any("F1800" in l for l in lines))

        # Check that laser is turned off at end
        self.assertTrue(lines[-1].startswith("M5"))

    def test_framing_empty_entities(self):
        gcode = self.gen.generate_contour_framing_gcode([])
        self.assertEqual(gcode, "")


class TestAsymmetricKerf(unittest.TestCase):
    """Test elliptical / asymmetric X/Y kerf compensation."""

    def test_asymmetric_expansion(self):
        # 20mm x 20mm square: (0,0) to (20,20)
        box = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0)]

        # Kerf: 0.10 mm in X, 0.20 mm in Y (outer offset: +0.05 in X, +0.10 in Y on each side)
        # Expected new width: 20 + 0.10 = 20.10 mm
        # Expected new height: 20 + 0.20 = 20.20 mm
        results = KerfEngine.apply_kerf_to_paths([box], kerf_x=0.10, kerf_y=0.20, direction="Outward")
        self.assertEqual(len(results), 1)

        offset_coords = results[0]["path"]
        xs = [p[0] for p in offset_coords]
        ys = [p[1] for p in offset_coords]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)

        self.assertAlmostEqual(w, 20.10, places=2)
        self.assertAlmostEqual(h, 20.20, places=2)

    def test_symmetric_fallback(self):
        box = [(0.0, 0.0), (30.0, 0.0), (30.0, 30.0), (0.0, 30.0), (0.0, 0.0)]

        results = KerfEngine.apply_kerf_to_paths([box], kerf_x=0.15, kerf_y=0.15, direction="Outward")
        self.assertEqual(len(results), 1)
        offset_coords = results[0]["path"]
        xs = [p[0] for p in offset_coords]
        ys = [p[1] for p in offset_coords]
        self.assertAlmostEqual(max(xs) - min(xs), 30.15, places=2)
        self.assertAlmostEqual(max(ys) - min(ys), 30.15, places=2)


class TestCenterlineTracing(unittest.TestCase):
    """Test centerline / skeleton vectorization."""

    def test_centerline_trace_generates_open_paths(self):
        # Create a black image with a thick white diagonal line
        img = Image.new("L", (100, 100), color=0)
        import PIL.ImageDraw as ImageDraw
        draw = ImageDraw.Draw(img)
        # Draw thick line (width=7) from (15, 15) to (85, 85)
        draw.line([(15, 15), (85, 85)], fill=255, width=7)

        # Trace with centerline
        paths = ImageTracer.trace_centerline(img, threshold=128, min_length_pixels=10.0, smoothness=0.8)

        self.assertGreater(len(paths), 0)
        # Centerline paths should be lists of coordinate points
        for p in paths:
            self.assertGreater(len(p), 1)


class TestKerfTestGenerator(unittest.TestCase):
    """Test automated kerf calibration test matrix & feeler gauge."""

    def test_kerf_gauge_generation(self):
        settings = KerfTestSettings(
            material_thickness_mm=3.0,
            start_kerf_mm=0.06,
            kerf_step_mm=0.02,
            slot_count=5,
            slot_depth_mm=10.0,
            tooth_width_mm=5.0,
            cut_layer_id=0,
            engrave_layer_id=1
        )

        entities = KerfTestGenerator.generate(settings)
        self.assertEqual(len(entities), 4)

        # 1. Gauge Body (Cut layer 0, closed)
        gauge_body = entities[0]
        self.assertEqual(gauge_body.layer_id, 0)
        self.assertTrue(gauge_body.closed)
        b_body = gauge_body.get_bounds()
        w_body = b_body[2] - b_body[0]
        self.assertGreater(w_body, 30.0)

        # 2. Numeric slot labels (Layer 1, unclosed stroke text)
        labels = entities[1]
        self.assertEqual(labels.layer_id, 1)
        self.assertFalse(labels.closed)

        # 3. Feeler Tongue (Cut layer 0, closed)
        tongue = entities[2]
        self.assertEqual(tongue.layer_id, 0)
        self.assertTrue(tongue.closed)
        b_tongue = tongue.get_bounds()
        w_tongue = b_tongue[2] - b_tongue[0]
        # Overall handle width is 15.0mm (tongue_w + 12.0mm)
        self.assertAlmostEqual(w_tongue, 15.0, delta=0.5)
        # Feeler blade tip width is nominal thickness (3.0mm)
        blade_tip_w = tongue.contours[0][1][0] - tongue.contours[0][0][0]
        self.assertAlmostEqual(blade_tip_w, 3.0, delta=0.1)

        # 4. Header title text (Layer 1, unclosed stroke text)
        title = entities[3]
        self.assertEqual(title.layer_id, 1)
        self.assertFalse(title.closed)


if __name__ == "__main__":
    unittest.main()
