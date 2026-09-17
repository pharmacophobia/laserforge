"""
Unit and Integration Tests for LaserForge Phase 4:
1. Ruida DSP Controller & .rd Binary Pipeline (UDP client & compiler)
2. Mobile Remote Jogger & Web Pendant (embedded HTTP/REST server)
3. Galvo & Fiber Marking Laser Engine (mirror delays & beam wobble)
4. 3D Relief Engraving & Automated Z-Step Down
5. Automated Material Test Card Generator & Burn Grid Studio
6. UI Integration & Shortcut Non-Collision
"""

import unittest
import math
import os
import json
import urllib.request
from PIL import Image

from PyQt6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.core.models import PathEntity, RectEntity, LineEntity
from laserforge.core.material_test_generator import MaterialTestGenerator, MaterialTestGridConfig
from laserforge.core.relief_engine import ReliefEngine, ZStepConfig, ReliefCarveConfig
from laserforge.core.galvo_engine import GalvoEngine, GalvoDelays, WobbleConfig
from laserforge.core.ruida_engine import RuidaCompiler, RuidaLayerConfig, RuidaUDPClient
from laserforge.core.web_pendant import WebPendantServer
from laserforge.ui.main_window import MainWindow


class TestMaterialTestGenerator(unittest.TestCase):
    def test_grid_generation_and_overrides(self):
        """Material test grid must generate patch entities with per-entity speed and power overrides."""
        cfg = MaterialTestGridConfig(
            min_speed=200.0,
            max_speed=1000.0,
            speed_steps=3,
            min_power=20.0,
            max_power=80.0,
            power_steps=3,
            patch_width=10.0,
            patch_height=10.0,
            test_mode="both",
            include_labels=True,
            include_frame=True
        )

        entities = MaterialTestGenerator.generate_grid(cfg, origin_x=10.0, origin_y=10.0)
        self.assertGreater(len(entities), 9)

        # Check for patch rects with speed & power overrides
        patch_rects = [e for e in entities if isinstance(e, RectEntity) and "TestPatch" in e.name]
        self.assertEqual(len(patch_rects), 9)

        speeds = {p.speed_override for p in patch_rects}
        powers = {p.power_override for p in patch_rects}
        self.assertEqual(len(speeds), 3)
        self.assertEqual(len(powers), 3)
        self.assertIn(200.0, speeds)
        self.assertIn(1000.0, speeds)
        self.assertIn(20.0, powers)
        self.assertIn(80.0, powers)

        # Check for outer cutout frame
        frame_rects = [e for e in entities if isinstance(e, RectEntity) and "Outer_Cutout" in e.name]
        self.assertEqual(len(frame_rects), 1)
        self.assertGreater(frame_rects[0].width, 30.0)


class TestReliefEngine(unittest.TestCase):
    def test_z_step_levels(self):
        """Multi-pass Z levels must increment downwards with correct pass spacing."""
        cfg = ZStepConfig(
            total_depth_mm=4.0,
            pass_count=4,
            step_down_mm=1.0,
            initial_z_offset_mm=0.5
        )
        levels = ReliefEngine.calculate_pass_z_levels(cfg)
        self.assertEqual(len(levels), 4)
        self.assertEqual(levels, [-0.5, -1.5, -2.5, -3.5])

    def test_relief_scanline_slicing(self):
        """Grayscale heightmaps should be sliced into discrete depth levels."""
        # Create a synthetic 100x100 gradient image
        img = Image.linear_gradient("L").resize((100, 100))
        cfg = ReliefCarveConfig(
            width_mm=50.0,
            height_mm=50.0,
            max_depth_mm=2.0,
            z_slices=3,
            line_interval_mm=1.0
        )
        res = ReliefEngine.generate_relief_scanlines(img, cfg)
        self.assertEqual(res["total_slices"], 3)
        self.assertEqual(len(res["slices"]), 3)
        self.assertGreater(res["estimated_lines"], 0)


class TestGalvoEngine(unittest.TestCase):
    def test_timing_overhead(self):
        """Delay calculation converts microseconds to seconds accurately."""
        delays = GalvoDelays(
            laser_on_delay_us=100.0,
            laser_off_delay_us=100.0,
            mark_delay_us=200.0,
            jump_delay_us=300.0,
            polygon_delay_us=100.0
        )
        # 10 mark moves, 5 jumps, 8 corners
        # total_us = 10 * (100+100+200) + 5 * 300 + 8 * 100 = 4000 + 1500 + 800 = 6300 us = 0.0063 s
        overhead_sec = GalvoEngine.calculate_timing_overhead(delays, mark_moves=10, jump_moves=5, corners=8)
        self.assertAlmostEqual(overhead_sec, 0.0063, places=5)

    def test_beam_wobble_expansion(self):
        """Applying transverse wobble must generate high-frequency oscillating loop vertices."""
        line = [(0.0, 0.0), (20.0, 0.0)]
        cfg = WobbleConfig(
            enabled=True,
            pattern="circle",
            amplitude_mm=1.0,
            pitch_mm=1.0
        )
        wobble_pts = GalvoEngine.apply_wobble_to_contour(line, cfg)
        self.assertGreater(len(wobble_pts), len(line))
        # Y coordinates should deviate from 0 due to circular transverse oscillation
        max_y = max(abs(p[1]) for p in wobble_pts)
        self.assertGreater(max_y, 0.3)
        self.assertLessEqual(max_y, 0.6)  # radius = amplitude / 2 = 0.5

    def test_rotary_band_splitting(self):
        """Vector contours should be sliced into discrete rotary bands."""
        contour = [(0.0, 0.0), (10.0, 20.0)]
        bands = GalvoEngine.split_contours_for_rotary([contour], split_width_mm=5.0, axis="Y")
        self.assertEqual(len(bands), 4)  # 20mm span / 5mm = 4 bands


class TestRuidaCompiler(unittest.TestCase):
    def test_rd_binary_compilation(self):
        """Compiling vector entities generates a valid Ruida binary stream with header and opcodes."""
        rect = RectEntity(layer_id=0, name="RuidaBox", x=10.0, y=10.0, width=20.0, height=15.0)
        rect.speed_override = 1200.0  # 20 mm/s
        rect.power_override = 35.0

        rd_bytes = RuidaCompiler.compile_paths_to_rd([rect])
        self.assertIsInstance(rd_bytes, bytearray)
        self.assertTrue(rd_bytes.startswith(b"RD6442"))

        # Verify command opcodes present
        self.assertIn(RuidaCompiler.CMD_SET_POWER, rd_bytes)
        self.assertIn(RuidaCompiler.CMD_SET_SPEED, rd_bytes)
        self.assertIn(RuidaCompiler.CMD_RAPID_MOVE, rd_bytes)
        self.assertIn(RuidaCompiler.CMD_CUT_MOVE, rd_bytes)
        self.assertEqual(rd_bytes[-1], RuidaCompiler.CMD_END_JOB)


class TestWebPendantServer(unittest.TestCase):
    def test_pendant_server_lifecycle_and_api(self):
        """Embedded HTTP pendant server starts, serves HTML & JSON status, and stops cleanly."""
        server = WebPendantServer(port=8999, host="127.0.0.1")
        server.get_status_cb = lambda: {"state": "Idle", "x": 12.34, "y": 56.78, "z": 0.0}
        
        ok = server.start()
        self.assertTrue(ok)
        self.assertTrue(server.is_running)

        try:
            # 1. Test GET / (HTML)
            req_html = urllib.request.urlopen("http://127.0.0.1:8999/", timeout=2.0)
            html_content = req_html.read().decode("utf-8")
            self.assertIn("LaserForge Mobile Jogger", html_content)

            # 2. Test GET /api/status (JSON)
            req_status = urllib.request.urlopen("http://127.0.0.1:8999/api/status", timeout=2.0)
            status_json = json.loads(req_status.read().decode("utf-8"))
            self.assertEqual(status_json["state"], "Idle")
            self.assertAlmostEqual(status_json["x"], 12.34, places=2)
        finally:
            server.stop()
            self.assertFalse(server.is_running)


class TestPhase4UIIntegration(unittest.TestCase):
    def test_main_window_has_all_phase4_actions(self):
        """MainWindow must expose all Phase 4 studio actions with unique shortcuts."""
        win = MainWindow()

        # Check all 5 actions exist
        self.assertTrue(hasattr(win, "act_material_test_studio"))
        self.assertTrue(hasattr(win, "act_relief_studio"))
        self.assertTrue(hasattr(win, "act_galvo_studio"))
        self.assertTrue(hasattr(win, "act_ruida_studio"))
        self.assertTrue(hasattr(win, "act_web_pendant"))

        # Verify shortcuts
        self.assertEqual(win.act_material_test_studio.shortcut().toString(), "Ctrl+Alt+M")
        self.assertEqual(win.act_relief_studio.shortcut().toString(), "Ctrl+Alt+Z")
        self.assertEqual(win.act_galvo_studio.shortcut().toString(), "Ctrl+Alt+F")
        self.assertEqual(win.act_ruida_studio.shortcut().toString(), "Ctrl+Alt+R")
        self.assertEqual(win.act_web_pendant.shortcut().toString(), "Ctrl+Alt+W")

        win.close()


if __name__ == "__main__":
    unittest.main()
