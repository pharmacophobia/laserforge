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


if __name__ == "__main__":
    unittest.main()

