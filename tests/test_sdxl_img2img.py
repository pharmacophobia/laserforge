"""
Tests for SDXL Turbo Image-to-Image (img2img) photo modification feature.
Tests core procedural fallback, img2img pipeline invocation, strength scaling,
and SDXL Turbo Studio UI integration.
"""

import os
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from laserforge.core.sdxl_turbo_engine import SDXLTurboEngine, modify_image_procedurally
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


class TestSDXLImg2ImgEngine(unittest.TestCase):
    """Verifies core img2img logic and procedural fallback."""

    def setUp(self):
        self.engine = SDXLTurboEngine()
        # Create a test input image
        self.test_img = Image.new("RGB", (256, 256), color=(180, 120, 80))
        draw = ImageDraw.Draw(self.test_img)
        draw.rectangle([60, 60, 196, 196], fill=(50, 50, 200), outline=(255, 255, 255), width=4)
        draw.ellipse([80, 80, 176, 176], fill=(255, 200, 50))

        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_img_path = os.path.join(self.temp_dir.name, "source_photo.png")
        self.test_img.save(self.test_img_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_modify_image_procedurally_laser_relief(self):
        """Checks procedural fallback generates valid restyled image with matching dimensions."""
        result = modify_image_procedurally(
            self.test_img,
            prompt="woodcut engraving of an owl",
            style_preset="Woodcut Relief",
            strength=0.65,
            width=256,
            height=256
        )
        self.assertIsInstance(result, Image.Image)
        self.assertEqual(result.size, (256, 256))
        self.assertEqual(result.mode, "RGB")

    def test_modify_image_procedurally_strengths(self):
        """Tests that different transformation strengths generate distinct images."""
        res_subtle = modify_image_procedurally(
            self.test_img,
            prompt="laser line art",
            style_preset="Fine Laser Line Art",
            strength=0.20,
            width=256,
            height=256
        )
        res_creative = modify_image_procedurally(
            self.test_img,
            prompt="laser line art",
            style_preset="Fine Laser Line Art",
            strength=0.90,
            width=256,
            height=256
        )
        self.assertEqual(res_subtle.size, (256, 256))
        self.assertEqual(res_creative.size, (256, 256))
        # Image bytes should differ because strength blends differ
        self.assertNotEqual(res_subtle.tobytes(), res_creative.tobytes())

    def test_generate_with_init_image(self):
        """Tests engine.generate() with an init_image and strength."""
        out = self.engine.generate(
            prompt="Intricate lion head cameo",
            init_image=self.test_img,
            strength=0.75,
            steps=1,
            guidance_scale=0.0,
            width=256,
            height=256,
            seed=42,
            style_preset="Slate Cameo"
        )
        self.assertIsInstance(out, Image.Image)
        self.assertEqual(out.size, (256, 256))


class TestSDXLTurboStudioUI(unittest.TestCase):
    """Verifies SDXLTurboStudioWindow UI interactions and Img2Img features."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from laserforge.apps.sdxl_turbo_studio import SDXLTurboStudioWindow
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_img = Image.new("RGB", (320, 240), color=(100, 150, 200))
        self.test_img_path = os.path.join(self.temp_dir.name, "ui_test_input.png")
        self.test_img.save(self.test_img_path)

        self.window = SDXLTurboStudioWindow(is_embedded=True)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.temp_dir.cleanup()

    def test_mode_switch(self):
        """Tests toggling between Text2Img and Img2Img modes."""
        self.assertFalse(self.window.is_img2img_mode)
        self.assertTrue(self.window.photo_grp.isHidden())

        # Switch to img2img
        self.window._set_mode(True)
        self.assertTrue(self.window.is_img2img_mode)
        self.assertFalse(self.window.photo_grp.isHidden())
        self.assertIn("Modify Photo", self.window.btn_generate.text())

        # Switch back to text2img
        self.window._set_mode(False)
        self.assertFalse(self.window.is_img2img_mode)
        self.assertTrue(self.window.photo_grp.isHidden())
        self.assertIn("Generate Artwork", self.window.btn_generate.text())

    def test_load_input_photo(self):
        """Tests loading an input photo updates labels, thumbnail, and auto-switches mode."""
        self.window.load_input_photo(self.test_img_path)
        self.assertTrue(self.window.is_img2img_mode)
        self.assertEqual(self.window.input_photo_path, self.test_img_path)
        self.assertIn("320 × 240 px", self.window.lbl_photo_dims.text())
        self.assertFalse(self.window.lbl_photo_thumb.pixmap().isNull())

    def test_strength_slider_spinbox_sync(self):
        """Tests that the strength slider and spinbox sync and update description."""
        self.window.slider_strength.setValue(40)
        self.assertAlmostEqual(self.window.spin_strength.value(), 0.40, places=2)
        self.assertIn("Balanced", self.window.lbl_strength_desc.text())

        self.window.spin_strength.setValue(0.20)
        self.assertEqual(self.window.slider_strength.value(), 20)
        self.assertIn("Subtle", self.window.lbl_strength_desc.text())

        self.window.spin_strength.setValue(0.85)
        self.assertEqual(self.window.slider_strength.value(), 85)
        self.assertIn("Creative", self.window.lbl_strength_desc.text())

    def test_use_result_as_next_input(self):
        """Tests the iterative modification button 'Use Result as Next Input'."""
        gen_img_path = os.path.join(self.temp_dir.name, "gen_result.png")
        gen_img = Image.new("RGB", (512, 512), color=(20, 200, 50))
        gen_img.save(gen_img_path)

        self.window.last_generated_path = gen_img_path
        self.window._on_use_result_as_input()

        self.assertEqual(self.window.input_photo_path, gen_img_path)
        self.assertTrue(self.window.is_img2img_mode)
        self.assertIn("512 × 512 px", self.window.lbl_photo_dims.text())

    def test_preview_modes(self):
        """Tests switching between Modified Result, Original Photo, and Side-by-Side."""
        self.window.load_input_photo(self.test_img_path)

        gen_img_path = os.path.join(self.temp_dir.name, "gen_result2.png")
        gen_img = Image.new("RGB", (512, 512), color=(200, 20, 50))
        gen_img.save(gen_img_path)
        self.window.last_generated_path = gen_img_path

        # Test all 3 view modes
        self.window._set_preview_view("result")
        self.assertEqual(self.window.preview_view_mode, "result")
        self.assertFalse(self.window.lbl_preview.pixmap().isNull())

        self.window._set_preview_view("input")
        self.assertEqual(self.window.preview_view_mode, "input")
        self.assertFalse(self.window.lbl_preview.pixmap().isNull())

        self.window._set_preview_view("split")
        self.assertEqual(self.window.preview_view_mode, "split")
        self.assertFalse(self.window.lbl_preview.pixmap().isNull())


if __name__ == "__main__":
    unittest.main()
