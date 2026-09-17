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


class TestAlignmentMarksGenerator(unittest.TestCase):
    """Test 90° corner L-marks and center '+' registration marks generation."""

    def setUp(self):
        self.settings = MachineSettings(bed_width=300, bed_height=200)
        self.layer_manager = LayerManager()
        self.gcode_gen = GCodeGenerator(self.settings, self.layer_manager)
        self.target_bbox = (20.0, 30.0, 120.0, 130.0)  # 100x100mm box at (20, 30)

    def test_corner_l_marks_generation(self):
        """Corner L-marks should create 4 unclosed 90° tick marks at the 4 corners."""
        marks = self.gcode_gen.generate_corner_l_marks(
            target=self.target_bbox,
            tick_len_mm=8.0,
            margin_mm=0.0,
            layer_id=12
        )
        self.assertEqual(len(marks), 4)

        names = [m.name for m in marks]
        self.assertIn("Corner_Tick_BL", names)
        self.assertIn("Corner_Tick_BR", names)
        self.assertIn("Corner_Tick_TR", names)
        self.assertIn("Corner_Tick_TL", names)

        for m in marks:
            self.assertEqual(m.layer_id, 12)
            self.assertFalse(m.closed)
            self.assertEqual(len(m.contours), 1)
            pts = m.contours[0]
            self.assertEqual(len(pts), 3)  # L-shape: arm 1, corner vertex (0,0), arm 2
            # Middle vertex is relative (0,0)
            self.assertEqual(pts[1], (0.0, 0.0))

        # Bottom Left: absolute origin is (20, 30), arms along +X and +Y
        bl = next(m for m in marks if m.name == "Corner_Tick_BL")
        self.assertEqual(bl.x, 20.0)
        self.assertEqual(bl.y, 30.0)
        self.assertEqual(bl.contours[0], [(8.0, 0.0), (0.0, 0.0), (0.0, 8.0)])

        # Top Right: absolute origin is (120, 130), arms along -X and -Y
        tr = next(m for m in marks if m.name == "Corner_Tick_TR")
        self.assertEqual(tr.x, 120.0)
        self.assertEqual(tr.y, 130.0)
        self.assertEqual(tr.contours[0], [(-8.0, 0.0), (0.0, 0.0), (0.0, -8.0)])

    def test_center_cross_mark_generation(self):
        """Center cross mark should create two intersecting lines at the exact geometric center."""
        marks = self.gcode_gen.generate_center_cross_mark(
            target=self.target_bbox,
            cross_len_mm=10.0,
            margin_mm=0.0,
            layer_id=12
        )
        self.assertEqual(len(marks), 2)
        h_line = next(m for m in marks if m.name == "Center_Mark_Plus_H")
        v_line = next(m for m in marks if m.name == "Center_Mark_Plus_V")

        # Center of (20, 30) -> (120, 130) is cx=70.0, cy=80.0
        # Horizontal line: X from 65 to 75, Y = 80
        self.assertAlmostEqual(h_line.x, 65.0)
        self.assertAlmostEqual(h_line.x2, 75.0)
        self.assertAlmostEqual(h_line.y, 80.0)
        self.assertAlmostEqual(h_line.y2, 80.0)

        # Vertical line: X = 70, Y from 75 to 85
        self.assertAlmostEqual(v_line.x, 70.0)
        self.assertAlmostEqual(v_line.x2, 70.0)
        self.assertAlmostEqual(v_line.y, 75.0)
        self.assertAlmostEqual(v_line.y2, 85.0)

    def test_combined_alignment_marks(self):
        """Combined mode generates 4 corner ticks + 2 center cross lines = 6 entities."""
        marks = self.gcode_gen.generate_alignment_marks(
            target=self.target_bbox,
            mode="corners_and_center",
            tick_len_mm=8.0,
            cross_len_mm=10.0,
            layer_id=1
        )
        self.assertEqual(len(marks), 6)
        corner_count = sum(1 for m in marks if "Corner_Tick" in m.name)
        cross_count = sum(1 for m in marks if "Center_Mark_Plus" in m.name)
        self.assertEqual(corner_count, 4)
        self.assertEqual(cross_count, 2)
        for m in marks:
            self.assertEqual(m.layer_id, 1)

    def test_alignment_marks_gcode_emission(self):
        """G-code generator must generate valid laser scoring paths for center_plus and corners_and_center."""
        # Test center_plus G-code
        gcode_plus = self.gcode_gen.generate_burn_perimeter_gcode(
            target=self.target_bbox,
            mode="center_plus",
            power_pct=15.0,
            speed=1500.0,
            center_cross_len_mm=10.0
        )
        self.assertIn("Center Cross H", gcode_plus)
        self.assertIn("Center Cross V", gcode_plus)
        self.assertIn("G1", gcode_plus)
        self.assertIn("X65.000", gcode_plus)
        self.assertIn("X75.000", gcode_plus)
        self.assertIn("Y75.000", gcode_plus)
        self.assertIn("Y85.000", gcode_plus)

        # Test corners_and_center G-code
        gcode_both = self.gcode_gen.generate_burn_perimeter_gcode(
            target=self.target_bbox,
            mode="corners_and_center",
            power_pct=12.0,
            speed=1200.0,
            corner_tick_len_mm=8.0,
            center_cross_len_mm=10.0
        )
        self.assertIn("Corner Tick BL", gcode_both)
        self.assertIn("Center Cross H", gcode_both)


if __name__ == "__main__":
    unittest.main()

