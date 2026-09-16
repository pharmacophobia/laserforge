"""
Unit tests for LaserForge Auto Image to SVG Cutout Tool.
Tests silhouette segmentation, offset margins, hole preservation,
hanging loops, standee tabs, and SVG generation.
"""

import unittest
import os
import tempfile
import numpy as np
from PIL import Image, ImageDraw

from laserforge.core.image_cutout import AutoCutoutGenerator, CutoutResult
from laserforge.core.models import ImageEntity, PathEntity
from laserforge.core.shape_generator import ShapeGenerator


class TestImageCutout(unittest.TestCase):

    def setUp(self):
        # Create a test transparent PNG with a circle and an inner hole
        self.img_alpha = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(self.img_alpha)
        draw.ellipse([40, 40, 160, 160], fill=(255, 50, 50, 255))
        draw.ellipse([80, 80, 120, 120], fill=(0, 0, 0, 0))  # Donut hole

        # Create an opaque test image on white background
        self.img_opaque = Image.new("RGB", (200, 200), (255, 255, 255))
        draw_op = ImageDraw.Draw(self.img_opaque)
        draw_op.rectangle([50, 50, 150, 150], fill=(20, 30, 40))

    def test_extract_subject_mask_alpha(self):
        mask = AutoCutoutGenerator.extract_subject_mask(self.img_alpha, bg_mode="alpha")
        self.assertEqual(mask.shape, (200, 200))
        # Center should be 0 (inner hole)
        self.assertEqual(mask[100, 100], 0)
        # Ring should be 255
        self.assertEqual(mask[60, 100], 255)
        # Outer corner should be 0
        self.assertEqual(mask[10, 10], 0)

    def test_extract_subject_mask_auto_border(self):
        mask = AutoCutoutGenerator.extract_subject_mask(self.img_opaque, bg_mode="auto")
        self.assertEqual(mask.shape, (200, 200))
        # Center should be subject (255)
        self.assertEqual(mask[100, 100], 255)
        # Corner should be background (0)
        self.assertEqual(mask[10, 10], 0)

    def test_generate_cutout_with_offset(self):
        # Generate with +2mm offset, no holes (solid backing)
        res = AutoCutoutGenerator.generate_cutout(
            self.img_alpha,
            target_width_mm=100.0,
            offset_mm=2.0,
            keep_interior_holes=False
        )
        self.assertIsInstance(res, CutoutResult)
        self.assertGreater(len(res.contours), 0)
        # Closed outer contour
        self.assertEqual(res.contours[0][0], res.contours[0][-1])
        # Width and height should be positive and roughly match target + 2*offset
        self.assertGreater(res.width_mm, 50.0)
        self.assertGreater(res.height_mm, 50.0)

    def test_generate_cutout_keep_holes(self):
        # Generate with holes kept
        res = AutoCutoutGenerator.generate_cutout(
            self.img_alpha,
            target_width_mm=100.0,
            offset_mm=0.5,
            keep_interior_holes=True,
            min_hole_area_mm2=1.0
        )
        # Should have at least 2 contours (outer perimeter + inner donut hole)
        self.assertGreaterEqual(len(res.contours), 2)
        self.assertTrue(res.has_holes)

    def test_hanging_loop_addition(self):
        # Add a keychain hanging loop
        res = AutoCutoutGenerator.generate_cutout(
            self.img_alpha,
            target_width_mm=80.0,
            offset_mm=2.0,
            add_hanging_loop=True,
            hanging_loop_dia_mm=3.5,
            hanging_loop_collar_mm=2.5
        )
        self.assertIsNotNone(res.hanging_hole_center_mm)
        self.assertGreater(len(res.contours), 1)  # Outer + hanging loop hole

    def test_standee_tab_addition(self):
        # Add a standee tab
        res_no_tab = AutoCutoutGenerator.generate_cutout(
            self.img_alpha, target_width_mm=80.0, offset_mm=1.0, add_standee_tab=False
        )
        res_with_tab = AutoCutoutGenerator.generate_cutout(
            self.img_alpha, target_width_mm=80.0, offset_mm=1.0, add_standee_tab=True,
            standee_tab_w_mm=15.0, standee_tab_h_mm=5.0
        )
        # With tab, height must be taller than without tab
        self.assertGreater(res_with_tab.height_mm, res_no_tab.height_mm + 2.0)

    def test_svg_export_validity(self):
        res = AutoCutoutGenerator.generate_cutout(
            self.img_alpha, target_width_mm=80.0, offset_mm=2.0
        )
        svg_xml = AutoCutoutGenerator.contours_to_svg(
            res.contours,
            bounding_box=res.bounding_box,
            source_img=self.img_alpha,
            embed_image=True,
            target_width_mm=80.0,
            target_height_mm=80.0
        )
        self.assertIn("<svg", svg_xml)
        self.assertIn("</svg>", svg_xml)
        self.assertIn("<path", svg_xml)
        self.assertIn("layer_1_cut", svg_xml)
        self.assertIn("layer_0_engrave", svg_xml)  # Embedded image layer
        self.assertIn("data:image/png;base64,", svg_xml)

        # File export test
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
            temp_path = tf.name
        try:
            AutoCutoutGenerator.export_svg_file(res, temp_path)
            self.assertTrue(os.path.exists(temp_path))
            self.assertGreater(os.path.getsize(temp_path), 50)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_shape_generator_offset_entity_with_image(self):
        # Save temp image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            temp_img_path = tf.name
        try:
            self.img_alpha.save(temp_img_path)
            img_ent = ImageEntity(
                name="TestLogo", x=10.0, y=20.0, width=50.0, height=50.0,
                image_path=temp_img_path
            )
            offset_path = ShapeGenerator.offset_entity(img_ent, offset_dist_mm=2.0, target_layer_id=2)
            self.assertIsNotNone(offset_path)
            self.assertIsInstance(offset_path, PathEntity)
            self.assertEqual(offset_path.layer_id, 2)
            self.assertEqual(offset_path.x, 10.0)
            self.assertEqual(offset_path.y, 20.0)
            self.assertGreater(len(offset_path.contours), 0)
        finally:
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)

    def test_cli_invocation(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            temp_in = tf.name
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf2:
            temp_out = tf2.name
        try:
            self.img_alpha.save(temp_in)
            cmd = f"python3 -m laserforge.core.image_cutout {temp_in} {temp_out} --offset 2.5 --loop"
            code = os.system(cmd)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(temp_out))
            self.assertGreater(os.path.getsize(temp_out), 100)
        finally:
            if os.path.exists(temp_in):
                os.remove(temp_in)
            if os.path.exists(temp_out):
                os.remove(temp_out)


if __name__ == "__main__":
    unittest.main()
