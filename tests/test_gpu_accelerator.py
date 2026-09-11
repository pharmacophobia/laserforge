"""
Unit tests for LaserForge GPU Hardware Acceleration Subsystem.
Tests CUDA filters, Bayer ordered dithering, distance matrix calculations,
and OpenGL viewport integration.
"""

import sys
import unittest
import numpy as np
from PIL import Image

from laserforge.config import MachineSettings
from laserforge.core.gpu_accelerator import GPUAccelerator, GPUHardwareInfo
from laserforge.core.raster_processor import RasterProcessor


class TestGPUAccelerator(unittest.TestCase):

    def test_hardware_info_detection(self):
        """Hardware info should detect CUDA capabilities on NVIDIA GPU or handle CPU fallback."""
        info = GPUAccelerator.get_hardware_info()
        self.assertIsInstance(info, GPUHardwareInfo)
        if info.cuda_available:
            self.assertTrue(info.cuda_available)
            self.assertIn("RTX", info.device_name)
            self.assertGreater(info.total_vram_gb, 4.0)
            self.assertIn("GPU:", info.summary_short())
        else:
            self.assertFalse(info.cuda_available)
            self.assertIn(info.summary_short(), [
                "⚡ GPU: OpenGL Hardware Accelerated (CPU Compute)",
                "🖥️ CPU Mode: Software Rasterizer"
            ])

    def test_cuda_unsharp_mask(self):
        """CUDA unsharp mask should enhance edges and preserve image shape and range."""
        test_img = (np.random.rand(256, 256) * 255).astype(np.uint8)
        sharp = GPUAccelerator.cuda_unsharp_mask(test_img, amount=1.5, radius=1.5)
        self.assertEqual(sharp.shape, test_img.shape)
        self.assertEqual(sharp.dtype, np.uint8)
        self.assertTrue(np.all(sharp >= 0))
        self.assertTrue(np.all(sharp <= 255))

    def test_cuda_gamma_contrast(self):
        """CUDA gamma and contrast should adjust tones across full range."""
        test_img = np.linspace(0, 255, 256, dtype=np.uint8).reshape(16, 16)
        adjusted = GPUAccelerator.cuda_adjust_gamma_contrast(test_img, gamma=1.8, contrast=1.2)
        self.assertEqual(adjusted.shape, test_img.shape)
        self.assertEqual(adjusted.dtype, np.uint8)

    def test_cuda_ordered_dither(self):
        """Bayer 8x8 ordered dithering on CUDA should produce binary 0/1 array."""
        test_img = (np.random.rand(128, 128) * 255).astype(np.uint8)
        dithered = GPUAccelerator.cuda_ordered_dither(test_img)
        self.assertEqual(dithered.shape, test_img.shape)
        self.assertEqual(dithered.dtype, np.uint8)
        unique_vals = set(np.unique(dithered))
        self.assertTrue(unique_vals.issubset({0, 1}))

    def test_cuda_pairwise_distance_matrix(self):
        """Pairwise distance matrix on CUDA should match Euclidean geometry."""
        pts = np.array([
            [0.0, 0.0],
            [3.0, 4.0],
            [6.0, 8.0]
        ], dtype=np.float32)
        dist_mat = GPUAccelerator.cuda_pairwise_distance_matrix(pts)
        self.assertEqual(dist_mat.shape, (3, 3))
        # Distance between (0,0) and (3,4) is 5.0
        self.assertAlmostEqual(dist_mat[0, 1], 5.0, places=4)
        self.assertAlmostEqual(dist_mat[1, 0], 5.0, places=4)
        self.assertAlmostEqual(dist_mat[0, 0], 0.0, places=4)

    def test_raster_processor_with_ordered_dither(self):
        """RasterProcessor should support the new GPU-accelerated Ordered/Bayer dithering mode."""
        img = Image.new("L", (100, 100), color=128)
        processed = RasterProcessor.process_image(
            img,
            target_width_mm=50.0,
            target_height_mm=50.0,
            line_interval_mm=0.1,
            mode="Ordered (Bayer)",
            sharpen=1.0
        )
        self.assertEqual(processed.shape, (500, 500))
        unique = set(np.unique(processed))
        self.assertTrue(unique.issubset({0, 1}))

    def test_canvas_view_opengl_toggle(self):
        """LaserCanvasView should successfully toggle between OpenGL and software viewports."""
        from PyQt6.QtWidgets import QApplication, QGraphicsScene
        from laserforge.ui.canvas_view import LaserCanvasView

        app = QApplication.instance() or QApplication(sys.argv)
        scene = QGraphicsScene()
        view = LaserCanvasView()
        view.setScene(scene)

        # Should initialize with OpenGL enabled
        self.assertTrue(view.opengl_enabled)

        # Toggle to software viewport
        view.set_opengl_acceleration(False)
        self.assertFalse(view.opengl_enabled)

        # Toggle back to OpenGL viewport
        view.set_opengl_acceleration(True)
        self.assertTrue(view.opengl_enabled)


if __name__ == "__main__":
    unittest.main()
