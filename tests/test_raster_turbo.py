"""
Unit tests for LaserForge Raster Turbo Suite:
- Continuous Inline Power Streaming (G1 S... zero-stutter)
- High-Speed Whitespace Skipping (G0 rapid blank jumping)
- Flood Fill Island Engraving (multi-object local clustering)
- MachineSettings UI persistence
"""

import os
import tempfile
import unittest
import numpy as np
from PIL import Image

from laserforge.config import MachineSettings
from laserforge.core.models import RectEntity, ImageEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.raster_processor import RasterProcessor
from laserforge.core.gcode_generator import GCodeGenerator


class TestRasterTurboSuite(unittest.TestCase):
    def setUp(self):
        self.settings = MachineSettings(
            bed_width=400.0,
            bed_height=400.0,
            rapid_speed=3000.0,
            continuous_inline_streaming=True,
            flood_fill_enabled=True,
            flood_fill_separation_mm=10.0,
            white_space_skip_enabled=True,
            white_space_skip_threshold_mm=5.0
        )
        self.layer_mgr = LayerManager()

    def test_extract_raster_islands_single(self):
        """Single solid shape should yield exactly one island."""
        arr = np.zeros((50, 50), dtype=np.uint8)
        # Draw a small 20x20 burning square in center (val > 0 = burning pixels)
        arr[15:35, 15:35] = 255

        islands = RasterProcessor.extract_raster_islands(
            arr,
            origin_x_mm=10.0,
            origin_y_mm=20.0,
            line_interval_mm=0.1,
            min_separation_mm=5.0
        )

        self.assertEqual(len(islands), 1)
        isl = islands[0]
        # Bounding box of 20x20 pixels with 0.1mm size should be ~2.0mm
        self.assertEqual(isl["sub_array"].shape, (20, 20))
        self.assertAlmostEqual(isl["origin_x_mm"], 10.0 + 15 * 0.1, places=3)
        self.assertAlmostEqual(isl["origin_y_mm"], 20.0 + 15 * 0.1, places=3)
        self.assertAlmostEqual(isl["width_mm"], 2.0, places=3)
        self.assertAlmostEqual(isl["height_mm"], 2.0, places=3)

    def test_extract_raster_islands_separated(self):
        """Two separated shapes beyond separation threshold should yield two distinct islands."""
        arr = np.zeros((50, 150), dtype=np.uint8)
        # Shape 1: cols 10..30 (width 20 px = 2.0 mm)
        arr[15:35, 10:30] = 255
        # Shape 2: cols 110..130 (width 20 px = 2.0 mm, gap is 80 px = 8.0 mm)
        arr[15:35, 110:130] = 255

        # Separation threshold 4.0 mm (< 8.0 mm gap) -> should split into 2 islands
        islands = RasterProcessor.extract_raster_islands(
            arr,
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            line_interval_mm=0.1,
            min_separation_mm=4.0
        )

        self.assertEqual(len(islands), 2)
        # Verify both islands have 20x20 sub_arrays
        self.assertEqual(islands[0]["sub_array"].shape, (20, 20))
        self.assertEqual(islands[1]["sub_array"].shape, (20, 20))

    def test_extract_raster_islands_bridged_by_small_separation(self):
        """Two shapes closer than separation threshold should be grouped into a single island."""
        arr = np.zeros((50, 80), dtype=np.uint8)
        # Gap between shapes is 10 px = 1.0 mm
        arr[15:35, 10:25] = 255
        arr[15:35, 35:50] = 255

        # Separation threshold 2.0 mm (> 1.0 mm gap) -> dilation bridges them
        islands = RasterProcessor.extract_raster_islands(
            arr,
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            line_interval_mm=0.1,
            min_separation_mm=2.0
        )

        self.assertEqual(len(islands), 1)

    def test_continuous_inline_streaming_eliminates_stutter(self):
        """Continuous streaming should not emit per-scanline M5/M4 planner buffer stalls."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img_path = tf.name

        try:
            # Create a 40x20 image with stripes
            im = Image.new("L", (40, 20), 255)
            for y in range(5, 15):
                for x in range(5, 35):
                    if (x + y) % 2 == 0:
                        im.putpixel((x, y), 0)
            im.save(img_path)

            # 1. Generate G-code with continuous inline streaming ON
            s_on = MachineSettings(
                laser_mode="M4",
                use_inline_power=True,
                continuous_inline_streaming=True,
                flood_fill_enabled=False
            )
            gen_on = GCodeGenerator(s_on, self.layer_mgr)
            ent = ImageEntity(image_path=img_path, raw_image_path=img_path, x=10, y=10, width=40, height=20)
            job_on = gen_on.generate_job([ent])

            # 2. Generate G-code with continuous inline streaming OFF (legacy mode)
            s_off = MachineSettings(
                laser_mode="M4",
                use_inline_power=True,
                continuous_inline_streaming=False,
                flood_fill_enabled=False
            )
            gen_off = GCodeGenerator(s_off, self.layer_mgr)
            job_off = gen_off.generate_job([ent])

            # In continuous mode, M5 is not emitted between scanlines
            # Count occurrences of M5 in the generated lines
            m5_on_count = job_on.gcode.count("M5")
            m5_off_count = job_off.gcode.count("M5")

            # Legacy mode emits M5 S0 at every scanline cluster end
            self.assertGreater(m5_off_count, m5_on_count)
            # In continuous mode, only preamble and job end (and island teardown) have M5
            self.assertLessEqual(m5_on_count, 4)
            # Verify inline S power is present
            self.assertIn("G1 X", job_on.gcode)
            self.assertIn(" S0", job_on.gcode)

        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)

    def test_flood_fill_distance_optimization(self):
        """Flood fill on two distant islands should drastically reduce total cut distance and stroke length."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img_path = tf.name

        try:
            # 200x50 image with two 20x20 squares at x=10..30 and x=170..190 (separated by 140 px = 14mm)
            im = Image.new("L", (200, 50), 255)
            for y in range(15, 35):
                for x in range(10, 30):
                    im.putpixel((x, y), 0)
                for x in range(170, 190):
                    im.putpixel((x, y), 0)
            im.save(img_path)

            # With Flood Fill ON
            s_ff_on = MachineSettings(
                laser_mode="M4",
                use_inline_power=True,
                continuous_inline_streaming=True,
                flood_fill_enabled=True,
                flood_fill_separation_mm=2.0
            )
            gen_ff_on = GCodeGenerator(s_ff_on, self.layer_mgr)
            ent = ImageEntity(image_path=img_path, raw_image_path=img_path, x=0, y=0, width=20, height=5)
            job_ff_on = gen_ff_on.generate_job([ent])

            # With Flood Fill OFF and whitespace skip OFF (standard raster sweep)
            s_ff_off = MachineSettings(
                laser_mode="M4",
                use_inline_power=True,
                continuous_inline_streaming=True,
                flood_fill_enabled=False,
                white_space_skip_enabled=False
            )
            gen_ff_off = GCodeGenerator(s_ff_off, self.layer_mgr)
            job_ff_off = gen_ff_off.generate_job([ent])

            # Without flood fill, the laser carriage traverses the entire 20mm width on every scanline (360mm total cut dist)
            # With flood fill, the laser carves island 1 (~2mm wide) and island 2 (~2mm wide) (80mm total cut dist)
            self.assertLess(job_ff_on.total_cut_dist_mm, job_ff_off.total_cut_dist_mm * 0.35)
            self.assertLess(job_ff_on.estimated_time_sec, job_ff_off.estimated_time_sec * 0.35)

        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)

    def test_vector_fill_continuous_streaming(self):
        """Vector fill with continuous streaming should emit G1 S... without scanline M5/M4 halts."""
        lm = LayerManager()
        # Set Layer 0 to Fill mode
        lm.layers[0].mode = "Fill"
        lm.layers[0].line_interval = 1.0

        # Create rectangle for vector fill
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=30.0, height=20.0)

        # 1. Continuous streaming ON
        s_on = MachineSettings(use_inline_power=True, continuous_inline_streaming=True)
        gen_on = GCodeGenerator(s_on, lm)
        job_on = gen_on.generate_job([rect])

        # 2. Continuous streaming OFF
        s_off = MachineSettings(use_inline_power=True, continuous_inline_streaming=False)
        gen_off = GCodeGenerator(s_off, lm)
        job_off = gen_off.generate_job([rect])

        # Continuous streaming should not have M5 after every single fill line
        m5_on_count = job_on.gcode.count("M5")
        m5_off_count = job_off.gcode.count("M5")

        self.assertGreater(m5_off_count, m5_on_count)
        # Should contain inline S power on G1 moves
        self.assertIn("G1 X", job_on.gcode)
        self.assertIn("S300", job_on.gcode)

    def test_fast_whitespace_rapid_speed(self):
        """Configuring custom raster_fast_whitespace_speed should emit that feedrate for blank jumps."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img_path = tf.name

        try:
            im = Image.new("L", (100, 20), 255)
            # Two dots separated by 60 pixels (6mm)
            for y in range(8, 12):
                im.putpixel((10, y), 0)
                im.putpixel((80, y), 0)
            im.save(img_path)

            custom_rapid = 4800.0
            s = MachineSettings(
                laser_mode="M4",
                use_inline_power=True,
                continuous_inline_streaming=True,
                flood_fill_enabled=False,
                white_space_skip_enabled=True,
                white_space_skip_threshold_mm=2.0,
                raster_fast_whitespace_speed=custom_rapid
            )
            gen = GCodeGenerator(s, self.layer_mgr)
            ent = ImageEntity(image_path=img_path, raw_image_path=img_path, x=0, y=0, width=10, height=2)
            job = gen.generate_job([ent])

            # The whitespace skip move should use F4800
            self.assertIn(f"F{custom_rapid:.0f}", job.gcode)

        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)

    def test_machine_settings_dialog_turbo_options(self):
        """Test MachineSettingsDialog loads and persists Raster Turbo Suite options."""
        from PyQt6.QtWidgets import QApplication
        from laserforge.ui.machine_settings_dialog import MachineSettingsDialog

        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

        test_settings = MachineSettings(
            continuous_inline_streaming=False,
            raster_fast_whitespace_speed=7200.0,
            flood_fill_enabled=False,
            flood_fill_separation_mm=18.5
        )

        dlg = MachineSettingsDialog(test_settings)
        try:
            # Verify widgets loaded the settings
            self.assertFalse(dlg.chk_continuous_streaming.isChecked())
            self.assertAlmostEqual(dlg.fast_ws_speed_spin.value(), 7200.0)
            self.assertFalse(dlg.chk_flood_fill.isChecked())
            self.assertAlmostEqual(dlg.flood_fill_sep_spin.value(), 18.5)

            # Mutate widget values
            dlg.chk_continuous_streaming.setChecked(True)
            dlg.fast_ws_speed_spin.setValue(12000.0)
            dlg.chk_flood_fill.setChecked(True)
            dlg.flood_fill_sep_spin.setValue(8.0)

            # Apply
            dlg._apply_settings()

            # Verify persisted into test_settings
            self.assertTrue(test_settings.continuous_inline_streaming)
            self.assertEqual(test_settings.raster_fast_whitespace_speed, 12000.0)
            self.assertTrue(test_settings.flood_fill_enabled)
            self.assertEqual(test_settings.flood_fill_separation_mm, 8.0)
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
