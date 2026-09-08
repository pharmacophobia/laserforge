"""
Unit and integration test suite for LaserForge core subsystems.
"""

import os
import tempfile
import unittest
from PIL import Image

from laserforge.config import MachineSettings
from laserforge.core.models import (
    RectEntity, CircleEntity, LineEntity, TextEntity, ImageEntity, PathEntity
)
from laserforge.core.layer_manager import LayerManager
from laserforge.core.raster_processor import RasterProcessor
from laserforge.core.optimizer import PathOptimizer
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.project_io import ProjectIO


class TestLaserForgeCore(unittest.TestCase):
    def setUp(self):
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0)
        self.layer_mgr = LayerManager()
        self.gcode_gen = GCodeGenerator(self.settings, self.layer_mgr)

    def test_layer_manager(self):
        l0 = self.layer_mgr.get_layer(0)
        self.assertEqual(l0.name, "C00")
        self.assertEqual(l0.mode, "Line")

        l1 = self.layer_mgr.get_layer(1)
        self.assertEqual(l1.name, "C01")
        self.assertEqual(l1.color, "#1E90FF")

    def test_rect_entity_gcode(self):
        rect = RectEntity(layer_id=0, x=10.0, y=20.0, width=50.0, height=30.0)
        job = self.gcode_gen.generate_job([rect])

        self.assertIn("G0 X10.000 Y20.000", job.gcode)
        self.assertIn("G1 X60.000 Y20.000", job.gcode)
        self.assertIn("M5", job.gcode)
        self.assertGreater(job.total_cut_dist_mm, 150.0)
        self.assertGreater(job.estimated_time_sec, 0.0)

    def test_circle_entity_gcode(self):
        circle = CircleEntity(layer_id=1, x=100.0, y=100.0, radius_x=25.0, radius_y=25.0)
        job = self.gcode_gen.generate_job([circle])

        self.assertIn("M4", job.gcode) # Dynamic power
        self.assertGreater(len(job.segments), 10)
        self.assertAlmostEqual(job.bounding_box[0], 75.0, delta=2.0)
        self.assertAlmostEqual(job.bounding_box[2], 125.0, delta=2.0)

    def test_framing_gcode(self):
        rect = RectEntity(layer_id=0, x=50.0, y=50.0, width=100.0, height=80.0)
        frame_gcode = self.gcode_gen.generate_framing_gcode([rect])

        self.assertIn("Bounding Box Framing", frame_gcode)
        self.assertIn("G0 X50.000 Y50.000", frame_gcode)
        self.assertIn("G1 X150.000 Y50.000", frame_gcode)
        self.assertIn("M5", frame_gcode)

    def test_raster_dithering(self):
        # Create a test 64x64 grayscale image
        img = Image.new("L", (64, 64), 128)
        dithered = RasterProcessor.dither_floyd_steinberg(img)
        self.assertEqual(dithered.size, (64, 64))

        # Check scanlines
        scanlines = RasterProcessor.image_to_scanlines(dithered, pixel_size_mm=0.1)
        self.assertIsInstance(scanlines, list)

    def test_project_save_and_load(self):
        rect = RectEntity(layer_id=0, x=15.0, y=25.0, width=40.0, height=35.0)
        circle = CircleEntity(layer_id=2, x=80.0, y=80.0, radius_x=15.0, radius_y=15.0)

        with tempfile.NamedTemporaryFile(suffix=".laserproj", delete=False) as tf:
            temp_path = tf.name

        try:
            machine_dict = {"bed_width": 400.0, "bed_height": 400.0, "origin_corner": "Bottom-Left"}
            ProjectIO.save_project(temp_path, [rect, circle], self.layer_mgr, machine_dict)

            # Reload
            loaded_entities, loaded_layers, loaded_machine = ProjectIO.load_project(temp_path, self.layer_mgr)
            self.assertEqual(len(loaded_entities), 2)
            self.assertEqual(loaded_entities[0].x, 15.0)
            self.assertEqual(loaded_entities[0].width, 40.0)
            self.assertEqual(loaded_entities[1].radius_x, 15.0)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_svg_import(self):
        svg_content = """<svg width="100mm" height="100mm" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
            <rect x="10" y="10" width="80" height="80" />
            <circle cx="50" cy="50" r="20" />
            <line x1="0" y1="0" x2="100" y2="100" />
        </svg>"""
        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False) as tf:
            tf.write(svg_content)
            temp_path = tf.name

        try:
            entities = ProjectIO.import_svg(temp_path, default_layer_id=0)
            self.assertGreaterEqual(len(entities), 3)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_inner_first_nesting_sort(self):
        # Outer box (0,0 to 100,100) and inner box (20,20 to 80,80)
        outer_box = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
        inner_box = [(20.0, 20.0), (80.0, 20.0), (80.0, 80.0), (20.0, 80.0), (20.0, 20.0)]

        sorted_contours = PathOptimizer.sort_inner_first([outer_box, inner_box])
        # Inner box must be first
        self.assertEqual(sorted_contours[0], inner_box)
        self.assertEqual(sorted_contours[1], outer_box)

    def test_tsp_optimization(self):
        c1 = [(10.0, 10.0), (20.0, 10.0)]
        c2 = [(100.0, 100.0), (110.0, 100.0)]
        c3 = [(21.0, 10.0), (30.0, 10.0)]

        optimized = PathOptimizer.optimize_travel_order([c1, c2, c3], start_pos=(0.0, 0.0))
        # Closest to (0,0) is c1, then c3 is right next to c1, then c2 is far away
        self.assertEqual(optimized[0], c1)
        self.assertEqual(optimized[1], c3)
        self.assertEqual(optimized[2], c2)

    def test_multi_pass_generation(self):
        layer = self.layer_mgr.get_layer(0)
        layer.passes = 3
        layer.z_step = 0.5
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)

        job = self.gcode_gen.generate_job([rect])
        self.assertIn("Pass 1/3", job.gcode)
        self.assertIn("Pass 2/3", job.gcode)
        self.assertIn("Pass 3/3", job.gcode)

    def test_image_tracer_to_svg(self):
        from PIL import ImageDraw
        from laserforge.core.image_tracer import ImageTracer

        img = Image.new("RGB", (100, 100), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([20, 20, 80, 80], fill=(0, 0, 0))
        d.ellipse([40, 40, 60, 60], fill=(255, 255, 255))

        contours = ImageTracer.trace_image(img, smoothness=1.0, scale_x=0.5, scale_y=0.5)
        self.assertGreaterEqual(len(contours), 2)

        svg = ImageTracer.contours_to_svg(contours, 50.0, 50.0)
        self.assertIn("<svg", svg)
        self.assertIn("d=\"M", svg)

    def test_image_tracer_file_to_file(self):
        from PIL import ImageDraw
        from laserforge.core.image_tracer import ImageTracer

        img = Image.new("L", (80, 80), 255)
        d = ImageDraw.Draw(img)
        d.rectangle([15, 15, 65, 65], fill=0)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf_in:
            img_path = tf_in.name
            img.save(img_path)

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf_out:
            svg_path = tf_out.name

        try:
            ImageTracer.trace_file_to_svg_file(img_path, svg_path, target_width_mm=60.0)
            self.assertTrue(os.path.exists(svg_path))
            with open(svg_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("<svg", content)
            self.assertIn("width=\"60.00mm\"", content)
        finally:
            if os.path.exists(img_path): os.unlink(img_path)
            if os.path.exists(svg_path): os.unlink(svg_path)

    def test_path_entity_translation_and_bounds(self):
        # A 10x10 triangle in local coordinates
        triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0), (0.0, 0.0)]
        path = PathEntity(layer_id=0, x=50.0, y=70.0, contours=[triangle], closed=True)

        local_bounds = path.get_local_bounds()
        self.assertEqual(local_bounds, (0.0, 0.0, 10.0, 10.0))

        world_bounds = path.get_bounds()
        self.assertEqual(world_bounds, (50.0, 70.0, 60.0, 80.0))

        # Check GCode output includes translated coordinates (50, 70)
        job = self.gcode_gen.generate_job([path])
        self.assertIn("G0 X50.000 Y70.000", job.gcode)
        self.assertIn("G1 X60.000 Y70.000", job.gcode)
        self.assertIn("G1 X55.000 Y80.000", job.gcode)

    def test_image_entity_creation_and_gcode(self):
        # Create a temporary test image
        img = Image.new("RGB", (100, 50), (128, 128, 128))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img_path = tf.name
            img.save(img_path)

        try:
            img_ent = ImageEntity(
                layer_id=0,
                name="test.png",
                x=10.0,
                y=20.0,
                width=80.0,
                height=40.0,
                image_path=img_path,
                dither_mode="Floyd-Steinberg",
                dpi=254.0
            )
            self.assertEqual(img_ent.dpi, 254.0)
            self.assertEqual(img_ent.get_bounds(), (10.0, 20.0, 90.0, 60.0))

            # Test CAM GCode generation from ImageEntity
            job = self.gcode_gen.generate_job([img_ent])
            self.assertGreater(len(job.segments), 0)
            self.assertGreater(job.total_cut_dist_mm, 0.0)
        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)

    def test_image_tracer_modes_and_smoothing(self):
        from PIL import ImageDraw
        import numpy as np
        from laserforge.core.image_tracer import ImageTracer, corner_preserving_smooth

        # 1. Test corner preserving smoothing: 90-degree rectangle corners kept, circle smoothed
        rect = np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0], [0.0, 50.0], [0.0, 0.0]])
        smooth_rect = corner_preserving_smooth(rect, corner_angle_thresh_deg=65.0, iterations=1)
        self.assertEqual(len(smooth_rect), 5)  # Preserved 4 corners + closing point

        # 2. Test Adaptive Mode and Hole Filtering
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([25, 25, 175, 175], fill=(0, 0, 0))
        d.ellipse([60, 60, 140, 140], fill=(255, 255, 255))

        # Standard with holes
        c_all = ImageTracer.trace_image(img, mode="threshold", ignore_holes=False)
        self.assertEqual(len(c_all), 2)

        # Silhouette only (ignore holes)
        c_sil = ImageTracer.trace_image(img, mode="threshold", ignore_holes=True)
        self.assertEqual(len(c_sil), 1)

        # Adaptive Gaussian mode
        c_adapt = ImageTracer.trace_image(img, mode="adaptive", adaptive_block_size=15, adaptive_c=4.0)
        self.assertGreaterEqual(len(c_adapt), 1)

        # Canny edge mode
        c_edge = ImageTracer.trace_image(img, mode="edge", threshold=100)
        self.assertGreaterEqual(len(c_edge), 1)

    def test_trace_image_dialog_presets(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from PIL import Image, ImageDraw
        from laserforge.ui.trace_image_dialog import TraceImageDialog

        app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        img = Image.new("RGB", (160, 160), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([30, 30, 130, 130], fill=(0, 0, 0))
        d.ellipse([50, 50, 110, 110], fill=(255, 255, 255))

        dlg = TraceImageDialog(img, "test_item", initial_width_mm=50.0, initial_height_mm=50.0)
        self.assertGreaterEqual(len(dlg.pixel_contours), 1)

        # Switch to Silhouette preset
        dlg._apply_preset("Outer Silhouette Only (No Holes)")
        self.assertEqual(len(dlg.pixel_contours), 1)

        # Switch to Clean Logo preset
        dlg._apply_preset("Clean Logo / Clipart (Default)")
        self.assertEqual(len(dlg.pixel_contours), 2)

        # Apply and create PathEntity
        dlg._apply_and_close()
        self.assertIsNotNone(dlg.result_path_entity)
        self.assertEqual(len(dlg.result_path_entity.contours), 2)


if __name__ == "__main__":
    unittest.main()


