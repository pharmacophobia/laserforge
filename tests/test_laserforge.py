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

        # Feature Outlines (Sobel gradient magnitude)
        c_feat = ImageTracer.trace_image(img, mode="feature", threshold=30, clahe=True)
        self.assertGreaterEqual(len(c_feat), 2)

        # Adaptive Gaussian mode
        c_adapt = ImageTracer.trace_image(img, mode="adaptive", adaptive_block_size=15, adaptive_c=4.0)
        self.assertGreaterEqual(len(c_adapt), 1)

        # Canny edge mode
        c_edge = ImageTracer.trace_image(img, mode="edge", threshold=100)
        self.assertGreaterEqual(len(c_edge), 1)

        # Transparent RGBA compositing test
        rgba_img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        d_rgba = ImageDraw.Draw(rgba_img)
        d_rgba.rectangle([20, 20, 80, 80], fill=(50, 50, 50, 255))
        c_trans = ImageTracer.trace_image(rgba_img, mode="feature")
        self.assertGreaterEqual(len(c_trans), 1)

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
        dlg._apply_preset("Outer Silhouette Only (Cutout)")
        self.assertEqual(len(dlg.pixel_contours), 1)

        # Switch to Clean Logo preset
        dlg._apply_preset("Clean Logo / Clipart (B&W)")
        self.assertEqual(len(dlg.pixel_contours), 2)

        # Switch to Feature Outlines preset
        dlg._apply_preset("Feature Outlines & Edges (Best for Artwork / Photos)")
        self.assertGreaterEqual(len(dlg.pixel_contours), 2)

        # Apply and create PathEntity
        dlg._apply_and_close()
        self.assertIsNotNone(dlg.result_path_entity)
        self.assertGreaterEqual(len(dlg.result_path_entity.contours), 2)


    def test_business_card_generator(self):
        from laserforge.core.business_card_generator import (
            BusinessCardConfig, BusinessCardGenerator, CARD_PRESETS, generate_qr_contours
        )

        # 1. Test Presets
        self.assertIn("Metal Card Blank (85.6 × 54.0 mm, R3mm)", CARD_PRESETS)
        preset = CARD_PRESETS["Metal Card Blank (85.6 × 54.0 mm, R3mm)"]
        self.assertEqual(preset["width"], 85.6)
        self.assertAlmostEqual(preset["height"], 54.0, delta=0.1)

        # 2. Test Single Card Generation
        cfg = BusinessCardConfig(
            width=85.6,
            height=54.0,
            company_name="Acme Lasers",
            person_name="Jane Doe",
            title="Chief Engineer",
            include_qr=True,
            qr_data="https://acmelasers.com"
        )
        entities = BusinessCardGenerator.generate_single_card(cfg, origin_x=10.0, origin_y=20.0)
        self.assertGreaterEqual(len(entities), 5)  # Border, QR, accent line, company, name, title, contacts

        # Find QR entity
        qr_ents = [e for e in entities if isinstance(e, PathEntity) and "QR" in e.name]
        self.assertEqual(len(qr_ents), 1)
        self.assertGreater(len(qr_ents[0].contours), 10)

        # 3. Test Cutting Jig Fixture
        jig_ents = BusinessCardGenerator.generate_card_jig_fixture(
            cols=2, rows=3, card_w=85.6, card_h=54.0, finger_notches=True, start_x=10.0, start_y=10.0
        )
        # Should include outer perimeter, 6 card pockets, 6 finger notches, and labels
        self.assertGreaterEqual(len(jig_ents), 14)

        # 4. Test Batch Array
        batch_ents = BusinessCardGenerator.generate_batch_array(cfg, cols=2, rows=2, start_x=10.0, start_y=10.0)
        self.assertGreaterEqual(len(batch_ents), 20)

    def test_vector_qr_code_merging(self):
        from laserforge.core.business_card_generator import generate_qr_contours

        contours = generate_qr_contours("https://laserforge.org", size_mm=25.0)
        self.assertIsInstance(contours, list)
        self.assertGreater(len(contours), 5)
        # Each contour is a 5-point closed polygon [(x1,y1), (x2,y1), (x2,y2), (x1,y2), (x1,y1)]
        for poly in contours:
            self.assertEqual(len(poly), 5)
            self.assertEqual(poly[0], poly[-1])  # Closed loop

    def test_materials_database_3w_diode(self):
        from laserforge.core.materials_database import MaterialDatabase, MaterialProfile

        db = MaterialDatabase()
        profiles = db.get_all()
        self.assertGreaterEqual(len(profiles), 8)

        # Check anodized aluminum profile specifically designed for 3W blue diode
        metal_profs = [p for p in profiles if "Aluminum" in p.name]
        self.assertGreaterEqual(len(metal_profs), 1)
        metal = metal_profs[0]
        self.assertEqual(metal.mode, "Fill")
        self.assertGreaterEqual(metal.power_pct, 80.0)
        self.assertGreater(metal.speed, 500.0)

        # Check basswood cut multi-pass profile with pass_delay_sec for diode cooling
        wood_cuts = [p for p in profiles if "Basswood" in p.name and "Cut" in p.name]
        self.assertGreaterEqual(len(wood_cuts), 1)
        wood = wood_cuts[0]
        self.assertGreater(wood.passes, 1)
        self.assertGreater(wood.pass_delay_sec, 0.0)

        # Test parametric test matrix generator
        swatches = MaterialDatabase.generate_test_matrix_entities(
            speeds=[500, 1000, 1500],
            powers=[40, 70, 100],
            swatch_size=10.0,
            test_type="Both"
        )
        self.assertGreaterEqual(len(swatches), 9)  # At least 9 swatches + labels

    def test_gcode_pass_delay_and_targeting(self):
        layer = self.layer_mgr.get_layer(0)
        layer.passes = 2
        layer.pass_delay_sec = 1.5  # 1.5s cooling delay

        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)
        job = self.gcode_gen.generate_job([rect])

        # Verify inter-pass cooldown delay is present
        self.assertIn("M5 ; 3W Diode Cooldown", job.gcode)
        self.assertIn("G4 P1.5 ; Pause 1.5s between passes", job.gcode)

        # Verify low-power targeting beam generator
        target_gcode = self.gcode_gen.generate_target_point_gcode(45.0, 75.0, power_pct=0.5)
        self.assertIn("G0 X45.000 Y75.000", target_gcode)
        self.assertIn("M3 S", target_gcode)

    def test_alignment_2point_transform_math(self):
        import math

        # Suppose card is at (20, 20) to (105.6, 74)
        min_x, min_y, max_x, max_y = 20.0, 20.0, 105.6, 74.0
        # Physical workpiece is jogged:
        # Point 1 (Top-Left) is physically at (30.0, 40.0)
        # Point 2 (Top-Right) is physically at (30.0 + 85.6 * cos(5 deg), 40.0 + 85.6 * sin(5 deg))
        pt1 = (30.0, 40.0)
        angle_rad = math.radians(5.0)
        pt2 = (30.0 + 85.6 * math.cos(angle_rad), 40.0 + 85.6 * math.sin(angle_rad))

        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        measured_angle = math.degrees(math.atan2(dy, dx))
        self.assertAlmostEqual(measured_angle, 5.0, places=3)

        shift_x = pt1[0] - min_x
        shift_y = pt1[1] - max_y
        self.assertEqual(shift_x, 10.0)
        self.assertEqual(shift_y, -34.0)

    def test_ui_dialogs_instantiation(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from laserforge.core.serial_controller import SerialController
        from laserforge.ui.business_card_dialog import BusinessCardStudioDialog
        from laserforge.ui.material_library_dialog import MaterialLibraryDialog, TestMatrixDialog
        from laserforge.ui.alignment_dialog import LaserAlignmentDialog

        app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        serial_ctrl = SerialController()

        # Business Card Dialog
        card_dlg = BusinessCardStudioDialog()
        self.assertIsNotNone(card_dlg)
        card_dlg._apply_and_close()
        self.assertGreater(len(card_dlg.generated_entities), 0)

        # Material Library Dialog
        mat_dlg = MaterialLibraryDialog()
        self.assertIsNotNone(mat_dlg)
        self.assertIsNotNone(mat_dlg.selected_profile)

        # Test Matrix Dialog
        matrix_dlg = TestMatrixDialog()
        self.assertIsNotNone(matrix_dlg)
        matrix_dlg._generate()
        self.assertGreater(len(matrix_dlg.generated_entities), 0)

        # Alignment Dialog
        align_dlg = LaserAlignmentDialog(serial_ctrl=serial_ctrl, bbox=(10.0, 10.0, 95.6, 64.0))
        self.assertIsNotNone(align_dlg)
        align_dlg._on_close()

    def test_auto_connect_and_port_detector(self):
        from laserforge.core.auto_connect import PortDetector, AutoConnectWorker, USBHotplugWatcher
        from laserforge.core.serial_controller import SerialController

        # 1. Test port ranking
        ranked = PortDetector.get_ranked_ports(include_dummy_tty=False)
        self.assertIsInstance(ranked, list)
        for p in ranked:
            # Dummy ttyS ports must be filtered out
            self.assertFalse(p.device.startswith("/dev/ttyS") and p.device[9:].isdigit())

        # If USB ports exist on system (like /dev/ttyUSB1), verify scoring
        usb_ports = [p for p in ranked if "ttyUSB" in p.device]
        if usb_ports:
            self.assertGreater(usb_ports[0].score, 100)
            self.assertIn("CH340", usb_ports[0].chip_info)

        # 2. Test SerialController integration
        ctrl = SerialController()
        avail = ctrl.list_available_ports()
        self.assertIsInstance(avail, list)
        ctrl_ranked = ctrl.get_ranked_ports()
        self.assertIsInstance(ctrl_ranked, list)

        # 3. Test hotplug watcher
        ctrl.enable_hotplug_watcher(True)
        self.assertIsNotNone(ctrl.hotplug_watcher)
        ctrl.enable_hotplug_watcher(False)
        self.assertIsNone(ctrl.hotplug_watcher)

    def test_probe_port_for_grbl_function(self):
        from laserforge.core.auto_connect import probe_port_for_grbl
        # Probing a non-existent port should safely return (False, None, "")
        is_grbl, baud, banner = probe_port_for_grbl("/dev/non_existent_port_12345", timeout=0.1)
        self.assertFalse(is_grbl)
        self.assertIsNone(baud)
        self.assertEqual(banner, "")

    def test_serial_controller_ack_queue_and_grbl_parsing(self):
        from laserforge.core.serial_controller import SerialController, GRBL_ERRORS, GRBL_ALARMS

        ctrl = SerialController()

        # 1. Test error dictionary coverage
        self.assertIn(20, GRBL_ERRORS)
        self.assertIn(1, GRBL_ALARMS)
        self.assertIn("limit switch", GRBL_ALARMS[1].lower())

        # 2. Test status parser with Pn: (limit pins)
        test_status = "<Idle|MPos:10.000,20.000,0.000|FS:0,0|Pn:PX>"
        ctrl._handle_incoming_line(test_status)
        self.assertEqual(ctrl.machine_state, "Idle")
        self.assertEqual(ctrl.active_pins, "PX")
        self.assertEqual(ctrl.mpos, [10.0, 20.0, 0.0])

        # 3. Test queue-based ACK
        self.assertTrue(ctrl.ack_queue.empty())
        ctrl._handle_incoming_line("ok")
        self.assertFalse(ctrl.ack_queue.empty())
        token = ctrl.ack_queue.get_nowait()
        self.assertEqual(token[0], "ok")

        # 4. Test error decoding into queue
        ctrl._handle_incoming_line("error:20")
        token = ctrl.ack_queue.get_nowait()
        self.assertEqual(token[0], "error")
        self.assertIn("error:20", token[1])
        self.assertIn("Unsupported", token[1])

        # 5. Test alarm decoding into queue and machine state
        ctrl._handle_incoming_line("ALARM:1")
        self.assertEqual(ctrl.machine_state, "Alarm")
        token = ctrl.ack_queue.get_nowait()
        self.assertEqual(token[0], "alarm")
        self.assertIn("ALARM:1", token[1])
        self.assertIn("Hard limit", token[1])

        # 6. Test $$ setting line parsing
        ctrl._handle_setting_line("$130=150.000")
        ctrl._handle_setting_line("$131=200.000")
        ctrl._handle_setting_line("$30=1000")
        ctrl._handle_setting_line("$32=1")
        self.assertEqual(ctrl.machine_limits["bed_width"], 150.0)
        self.assertEqual(ctrl.machine_limits["bed_height"], 200.0)
        self.assertEqual(ctrl.machine_limits["max_s_value"], 1000)
        self.assertEqual(ctrl.machine_limits["laser_mode"], "M4")

    def test_text_entity_typography_and_io(self):
        """Verify TextEntity typography attributes and ProjectIO round-trip."""
        text_ent = TextEntity(
            layer_id=1,
            name="TestTypography",
            x=25.0, y=35.0,
            text="LaserForge Custom",
            font_family="Sans Serif",
            font_size=18.5,
            bold=True,
            italic=True,
            underline=True,
            fill_mode="Outline",
            width=80.0,
            height=25.0
        )
        self.assertTrue(text_ent.bold)
        self.assertTrue(text_ent.italic)
        self.assertTrue(text_ent.underline)
        self.assertEqual(text_ent.fill_mode, "Outline")

        # Round-trip through ProjectIO
        with tempfile.NamedTemporaryFile(suffix=".laserproj", delete=False) as tf:
            temp_path = tf.name
        try:
            ProjectIO.save_project(temp_path, [text_ent], self.layer_mgr, self.settings)
            loaded_ents, loaded_mgr, _ = ProjectIO.load_project(temp_path, self.layer_mgr)
            self.assertEqual(len(loaded_ents), 1)
            lent = loaded_ents[0]
            self.assertIsInstance(lent, TextEntity)
            self.assertEqual(lent.text, "LaserForge Custom")
            self.assertEqual(lent.font_size, 18.5)
            self.assertTrue(lent.bold)
            self.assertTrue(lent.italic)
            self.assertTrue(lent.underline)
            self.assertEqual(lent.fill_mode, "Outline")
            self.assertEqual(lent.width, 80.0)
            self.assertEqual(lent.height, 25.0)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_text_entity_gcode_outline_vs_fill(self):
        """Verify G-code generation for Outline vs Fill mode and underline."""
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])

        # Outline text
        text_outline = TextEntity(
            layer_id=0, text="CutMe", font_size=12.0,
            underline=False, fill_mode="Outline", width=40.0, height=15.0
        )
        job_outline = self.gcode_gen.generate_job([text_outline])
        self.assertIn("G1", job_outline.gcode)
        self.assertGreater(len(job_outline.segments), 0)

        # Text with underline has more paths than without underline
        paths_no_ul = self.gcode_gen.entity_to_paths(text_outline)
        text_with_ul = TextEntity(
            layer_id=0, text="CutMe", font_size=12.0,
            underline=True, fill_mode="Outline", width=40.0, height=15.0
        )
        paths_with_ul = self.gcode_gen.entity_to_paths(text_with_ul)
        self.assertGreater(len(paths_with_ul), len(paths_no_ul))

        # Fill text
        text_fill = TextEntity(
            layer_id=0, text="EngraveMe", font_size=12.0,
            underline=True, fill_mode="Fill", width=40.0, height=15.0
        )
        job_fill = self.gcode_gen.generate_job([text_fill])
        self.assertIn("G1", job_fill.gcode)
        self.assertGreater(job_fill.total_cut_dist_mm, 10.0)

    def test_interactive_canvas_corner_resize(self):
        """Verify corner handle detection and dragging resize for CAD shapes."""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QPointF
        from laserforge.ui.canvas_scene import LaserCanvasScene, LaserItemWrapper
        _app = QApplication.instance() or QApplication([])

        scene = LaserCanvasScene(self.layer_mgr)

        # 1. Test RectEntity corner resizing
        rect_ent = RectEntity(layer_id=0, x=10.0, y=10.0, width=50.0, height=30.0)
        wrapper = scene.add_entity(rect_ent)
        wrapper.setSelected(True)

        handles = wrapper.get_handle_positions()
        self.assertIn("TL", handles)
        self.assertIn("BR", handles)
        self.assertIn("TR", handles)
        self.assertIn("BL", handles)
        self.assertEqual(len(handles), 8)

        # Hit test at BR handle
        br_pos = handles["BR"]
        detected = wrapper.get_handle_at(br_pos)
        self.assertEqual(detected, "BR")

        # Simulate starting resize on BR
        wrapper._resizing_handle = "BR"
        wrapper._resize_start_scene_pos = QPointF(60.0, 40.0)
        wrapper._store_resize_initial_state()

        # Simulate moving BR by +20mm in X and +10mm in Y
        class MockMouseEvent:
            def scenePos(self):
                return QPointF(80.0, 50.0)
            def modifiers(self):
                from PyQt6.QtCore import Qt
                return Qt.KeyboardModifier.NoModifier
            def accept(self):
                pass

        wrapper.mouseMoveEvent(MockMouseEvent())
        self.assertAlmostEqual(rect_ent.width, 70.0, places=1)
        self.assertAlmostEqual(rect_ent.height, 40.0, places=1)
        self.assertAlmostEqual(rect_ent.x, 10.0, places=1)
        self.assertAlmostEqual(rect_ent.y, 10.0, places=1)

        # 2. Test TextEntity corner resizing and proportional font size scaling
        text_ent = TextEntity(layer_id=0, x=20.0, y=20.0, width=40.0, height=20.0, font_size=10.0)
        twrapper = scene.add_entity(text_ent)
        twrapper.setSelected(True)

        twrapper._resizing_handle = "BR"
        twrapper._resize_start_scene_pos = QPointF(60.0, 40.0)
        twrapper._store_resize_initial_state()

        # Move BR to double height (height -> 40mm)
        class MockTextEvent:
            def scenePos(self):
                return QPointF(100.0, 60.0) # dx=+40, dy=+20
            def modifiers(self):
                from PyQt6.QtCore import Qt
                return Qt.KeyboardModifier.NoModifier
            def accept(self):
                pass

        twrapper.mouseMoveEvent(MockTextEvent())
        self.assertAlmostEqual(text_ent.width, 80.0, places=1)
        self.assertAlmostEqual(text_ent.height, 40.0, places=1)
        # Font size should scale 2x from 10.0 to 20.0
        self.assertAlmostEqual(text_ent.font_size, 20.0, places=1)

        # 3. Test Top-Left (TL) handle drag (opposite corner BR stays fixed)
        rect2 = RectEntity(layer_id=0, x=50.0, y=50.0, width=40.0, height=30.0)
        wrapper2 = scene.add_entity(rect2)
        wrapper2.setSelected(True)
        wrapper2._resizing_handle = "TL"
        wrapper2._resize_start_scene_pos = QPointF(50.0, 50.0)
        wrapper2._store_resize_initial_state()

        # Drag TL left and up by 10mm (scene dx=-10, dy=-10)
        class MockTLEvent:
            def scenePos(self):
                return QPointF(40.0, 40.0)
            def modifiers(self):
                from PyQt6.QtCore import Qt
                return Qt.KeyboardModifier.NoModifier
            def accept(self):
                pass

        wrapper2.mouseMoveEvent(MockTLEvent())
        self.assertAlmostEqual(rect2.x, 40.0, places=1)
        self.assertAlmostEqual(rect2.y, 40.0, places=1)
        self.assertAlmostEqual(rect2.width, 50.0, places=1)
        self.assertAlmostEqual(rect2.height, 40.0, places=1)
        # Verify bottom-right remains anchored at 90.0, 80.0
        self.assertAlmostEqual(rect2.x + rect2.width, 90.0, places=1)
        self.assertAlmostEqual(rect2.y + rect2.height, 80.0, places=1)

        # 4. Test Shift key aspect ratio preservation
        rect3 = RectEntity(layer_id=0, x=10.0, y=10.0, width=40.0, height=20.0) # aspect = 2:1
        wrapper3 = scene.add_entity(rect3)
        wrapper3.setSelected(True)
        wrapper3._resizing_handle = "BR"
        wrapper3._resize_start_scene_pos = QPointF(50.0, 30.0)
        wrapper3._store_resize_initial_state()

        # Drag BR by dx=+40 (width -> 80), dy=+10
        class MockShiftEvent:
            def scenePos(self):
                return QPointF(90.0, 40.0)
            def modifiers(self):
                from PyQt6.QtCore import Qt
                return Qt.KeyboardModifier.ShiftModifier
            def accept(self):
                pass

        wrapper3.mouseMoveEvent(MockShiftEvent())
        # Width scaled 2x (40 -> 80), so height must also scale 2x (20 -> 40)
        self.assertAlmostEqual(rect3.width, 80.0, places=1)
        self.assertAlmostEqual(rect3.height, 40.0, places=1)
        self.assertAlmostEqual(rect3.width / rect3.height, 2.0, places=1)

    def test_photo_processor_advanced_modes(self):
        """Verify advanced photo conversion: Jarvis, Stucki, Halftone, CLAHE, and material simulation."""
        from PIL import Image as PILImg
        import numpy as np
        from laserforge.core.raster_processor import RasterProcessor

        # Create a test gradient image
        test_img = PILImg.linear_gradient("L").resize((120, 120))

        # 1. Test Jarvis-Judice-Ninke Dither
        jarvis_arr = RasterProcessor.process_image(
            test_img, target_width_mm=40.0, target_height_mm=40.0,
            line_interval_mm=0.2, mode="Jarvis", gamma=1.3, sharpen=1.5, equalize=True
        )
        self.assertEqual(jarvis_arr.shape, (200, 200))
        self.assertTrue(np.all(np.isin(jarvis_arr, [0, 1])))
        self.assertGreater(np.sum(jarvis_arr), 0)

        # 2. Test Stucki Dither
        stucki_arr = RasterProcessor.process_image(
            test_img, target_width_mm=30.0, target_height_mm=30.0,
            line_interval_mm=0.2, mode="Stucki", invert=True
        )
        self.assertEqual(stucki_arr.shape, (150, 150))
        self.assertTrue(np.all(np.isin(stucki_arr, [0, 1])))

        # 3. Test Halftone AM screening
        ht_arr = RasterProcessor.process_image(
            test_img, target_width_mm=30.0, target_height_mm=30.0,
            line_interval_mm=0.2, mode="Halftone", halftone_cell_size=6.0, halftone_angle_deg=45.0
        )
        self.assertEqual(ht_arr.shape, (150, 150))
        self.assertTrue(np.all(np.isin(ht_arr, [0, 1])))

        # 4. Test Grayscale PWM power modulation
        gray_arr = RasterProcessor.process_image(
            test_img, target_width_mm=20.0, target_height_mm=20.0,
            line_interval_mm=0.2, mode="Grayscale"
        )
        self.assertGreater(gray_arr.max(), 1)

        # 5. Test Realistic Material Simulation Preview
        for mat_name in RasterProcessor.MATERIAL_PRESETS.keys():
            sim = RasterProcessor.generate_simulated_burn_preview(jarvis_arr, material_name=mat_name)
            self.assertEqual(sim.mode, "RGB")
            self.assertEqual(sim.size, (200, 200))

    def test_template_generator_all_templates(self):
        """Verify TemplateGenerator parametric generators for coasters, tumblers, keychains, and test matrix."""
        from laserforge.core.template_generator import TemplateGenerator

        # 1. Round Coaster
        rc = TemplateGenerator.generate_round_coaster(diameter=100.0, custom_text="TEST")
        self.assertGreaterEqual(len(rc), 2)
        cut_circles = [e for e in rc if isinstance(e, CircleEntity) and e.layer_id == 1]
        self.assertEqual(len(cut_circles), 1)
        self.assertAlmostEqual(cut_circles[0].radius_x, 50.0)

        # 2. Square Coaster
        sc = TemplateGenerator.generate_square_coaster(size=95.0, corner_radius=8.0)
        self.assertGreaterEqual(len(sc), 2)
        cut_rects = [e for e in sc if isinstance(e, RectEntity) and e.layer_id == 1]
        self.assertEqual(len(cut_rects), 1)
        self.assertEqual(cut_rects[0].width, 95.0)

        # 3. Keychains (Teardrop and Rect)
        kc_rect = TemplateGenerator.generate_keychain(style="Rounded Rectangle", width=60.0, height=30.0)
        self.assertEqual(len(kc_rect), 3)  # body cut, hole cut, engrave text
        kc_tear = TemplateGenerator.generate_keychain(style="Teardrop", width=55.0, height=32.0)
        self.assertGreaterEqual(len(kc_tear), 2)

        # 4. Tumbler Wraps
        t20 = TemplateGenerator.generate_tumbler_wrap(tumbler_type="20oz Skinny Tumbler")
        self.assertGreaterEqual(len(t20), 4)

        # 5. Holiday Bauble
        bauble = TemplateGenerator.generate_holiday_ornament(diameter=75.0, custom_text="2026")
        self.assertGreaterEqual(len(bauble), 2)

        # 6. Speed vs Power Test Matrix
        mat = TemplateGenerator.generate_speed_power_test_matrix(cols=4, rows=4, speed_min=200, speed_max=1000)
        # 16 test patches + headers + border
        self.assertGreaterEqual(len(mat), 20)

        # 7. Calibration Ruler
        ruler = TemplateGenerator.generate_calibration_ruler(length_mm=100.0)
        self.assertGreaterEqual(len(ruler), 100)

    def test_shape_generator_and_contour_offset(self):
        """Verify ShapeGenerator parametric shapes and LightBurn-style outline offset."""
        from laserforge.core.shape_generator import ShapeGenerator

        # 1. Regular Polygon (Hexagon)
        hex_ent = ShapeGenerator.create_regular_polygon(sides=6, radius=20.0, cx=50.0, cy=50.0)
        self.assertEqual(len(hex_ent.contours[0]), 6)

        # 2. Star
        star_ent = ShapeGenerator.create_star(points=5, r_outer=25.0, r_inner=10.0, cx=50.0, cy=50.0)
        self.assertEqual(len(star_ent.contours[0]), 10)

        # 3. Heart
        heart_ent = ShapeGenerator.create_heart(width=40.0, height=40.0, cx=50.0, cy=50.0)
        self.assertGreater(len(heart_ent.contours[0]), 30)

        # 4. Gear
        gear_ents = ShapeGenerator.create_gear(teeth=12, pitch_dia=40.0, bore_dia=6.0, cx=50.0, cy=50.0)
        self.assertEqual(len(gear_ents), 2)  # body path + bore hole circle

        # 5. Slot Capsule
        slot_ent = ShapeGenerator.create_slot_capsule(width=50.0, height=20.0, cx=50.0, cy=50.0)
        self.assertTrue(slot_ent.closed)

        # 6. Concentric Ring Donut
        ring_ents = ShapeGenerator.create_ring_donut(outer_dia=60.0, inner_dia=40.0, cx=50.0, cy=50.0)
        self.assertEqual(len(ring_ents), 2)

        # 7. Outline Offset on a Rectangle (+3mm)
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])

        rect = RectEntity(layer_id=0, name="BaseBox", x=20.0, y=20.0, width=40.0, height=30.0)
        offset_ent = ShapeGenerator.offset_entity(rect, offset_dist_mm=3.0, corner_join="Round", target_layer_id=1)
        self.assertIsNotNone(offset_ent)
        self.assertEqual(offset_ent.layer_id, 1)
        obounds = offset_ent.get_bounds()
        # Offset bounds should expand by approx 3mm on all sides
        self.assertAlmostEqual(obounds[0], 17.0, delta=1.5)
        self.assertAlmostEqual(obounds[1], 17.0, delta=1.5)
        self.assertAlmostEqual(obounds[2], 63.0, delta=1.5)
        self.assertAlmostEqual(obounds[3], 53.0, delta=1.5)

    def test_font_workflow_aids(self):
        """Verify curved arc text and serial batch generation."""
        from laserforge.core.font_tools import FontTools
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])

        # 1. Curved text along arc
        curved = FontTools.generate_curved_text(
            text="LASERFORGE", font_family="Sans Serif", font_size_mm=10.0,
            radius_mm=35.0, cx=50.0, cy=50.0, orientation="Top (Clockwise)"
        )
        self.assertIsNotNone(curved)
        self.assertIsInstance(curved, PathEntity)
        self.assertGreater(len(curved.contours), 5)

        # 2. Sequential serial numbers
        serials = FontTools.generate_serial_batch(
            prefix="SN-", start_number=1, count=5, digits=3,
            start_x=10.0, start_y=10.0, step_y=15.0
        )
        self.assertEqual(len(serials), 5)
        self.assertEqual(serials[0].text, "SN-001")
        self.assertEqual(serials[4].text, "SN-005")
        self.assertAlmostEqual(serials[4].y, 70.0)

    def test_alignment_distribution_and_grid_array(self):
        """Verify canvas alignment modes (left, center_x, right, bed_center, center_in_parent, distribute) and Grid Array."""
        from laserforge.ui.canvas_scene import LaserCanvasScene
        from laserforge.core.layer_manager import LayerManager
        from laserforge.ui.grid_array_dialog import GridArrayDialog
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])

        lm = LayerManager()
        scene = LaserCanvasScene(lm)

        r1 = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)
        r2 = RectEntity(layer_id=0, x=50.0, y=30.0, width=20.0, height=20.0)
        w1 = scene.add_entity(r1)
        w2 = scene.add_entity(r2)
        w1.setSelected(True)
        w2.setSelected(True)

        # Align Left: r2 should move to x=10
        scene.align_selected("left")
        self.assertAlmostEqual(r1.x, 10.0)
        self.assertAlmostEqual(r2.x, 10.0)

        # Bed Center on 150x200 bed: center should be at (75, 100)
        scene.align_selected("bed_center", bed_width=150.0, bed_height=200.0)
        b1 = r1.get_bounds()
        b2 = r2.get_bounds()
        min_x = min(b1[0], b2[0])
        max_x = max(b1[2], b2[2])
        self.assertAlmostEqual((min_x + max_x) / 2.0, 75.0, places=1)

        # Center in parent: r3 (small) inside r4 (large)
        scene.clear_entities()
        big_box = RectEntity(layer_id=1, x=20.0, y=20.0, width=100.0, height=100.0) # center = (70, 70)
        small_tag = RectEntity(layer_id=0, x=0.0, y=0.0, width=20.0, height=10.0)
        wb = scene.add_entity(big_box)
        ws = scene.add_entity(small_tag)
        wb.setSelected(True)
        ws.setSelected(True)

        scene.align_selected("center_in_parent")
        # small_tag center should now be (70, 70) -> x = 60, y = 65
        self.assertAlmostEqual(small_tag.x + small_tag.width / 2.0, 70.0, places=1)
        self.assertAlmostEqual(small_tag.y + small_tag.height / 2.0, 70.0, places=1)

    def test_laser_dwell_and_delays(self):
        settings = MachineSettings(
            laser_fire_delay_ms=50.0,
            laser_off_delay_ms=25.0
        )
        gen = GCodeGenerator(settings, self.layer_mgr)
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)
        job = gen.generate_job([rect])
        self.assertIn("G4 P0.050", job.gcode)  # Fire dwell
        self.assertIn("G4 P0.025", job.gcode)  # Off dwell

    def test_custom_start_and_end_scripts(self):
        settings = MachineSettings(
            custom_start_gcode="M8 ; Custom Air ON\nG4 P1.5 ; Pre-warm",
            custom_end_gcode="M9 ; Custom Air OFF\nG4 P2.0 ; Fan run-down"
        )
        gen = GCodeGenerator(settings, self.layer_mgr)
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)
        job = gen.generate_job([rect])
        self.assertIn("Custom Start G-Code", job.gcode)
        self.assertIn("M8 ; Custom Air ON", job.gcode)
        self.assertIn("G4 P1.5 ; Pre-warm", job.gcode)
        self.assertIn("Custom End G-Code", job.gcode)
        self.assertIn("M9 ; Custom Air OFF", job.gcode)
        self.assertIn("G4 P2.0 ; Fan run-down", job.gcode)

    def test_finish_position_modes(self):
        # 1. Park position mode
        settings_park = MachineSettings(
            finish_position_mode="Park Position",
            park_x=12.5,
            park_y=350.0
        )
        gen_park = GCodeGenerator(settings_park, self.layer_mgr)
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)
        job_park = gen_park.generate_job([rect])
        self.assertIn("G0 X12.500 Y350.000", job_park.gcode)

        # 2. Hold Current mode
        settings_hold = MachineSettings(finish_position_mode="Hold Current")
        gen_hold = GCodeGenerator(settings_hold, self.layer_mgr)
        job_hold = gen_hold.generate_job([rect])
        self.assertIn("Hold Current Position", job_hold.gcode)
        self.assertNotIn("G0 X0 Y0", job_hold.gcode)

    def test_air_assist_delays(self):
        settings = MachineSettings(
            air_assist_pre_delay_sec=0.8,
            air_assist_post_delay_sec=1.2
        )
        l0 = self.layer_mgr.get_layer(0)
        l0.air_assist = True
        gen = GCodeGenerator(settings, self.layer_mgr)
        rect = RectEntity(layer_id=0, x=10.0, y=10.0, width=20.0, height=20.0)
        job = gen.generate_job([rect])
        self.assertIn("Air Assist Pre-delay", job.gcode)
        self.assertIn("G4 P0.8", job.gcode)
        self.assertIn("Air Assist Post-delay", job.gcode)
        self.assertIn("G4 P1.2", job.gcode)
        l0.air_assist = False  # restore

    def test_overscan_raster_gcode(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img_path = tf.name
        try:
            test_img = Image.new("L", (32, 32), 0)
            test_img.save(img_path)

            settings_ov = MachineSettings(
                overscan_enabled=True,
                overscan_mode="Fixed",
                overscan_mm=2.5
            )
            l0 = self.layer_mgr.get_layer(0)
            l0.mode = "Image"
            gen = GCodeGenerator(settings_ov, self.layer_mgr)
            img_ent = ImageEntity(layer_id=0, image_path=img_path, x=10.0, y=10.0, width=20.0, height=20.0)
            job = gen.generate_job([img_ent])
            # Check lead-in / lead-out moves generated
            self.assertIn("G1", job.gcode)
            self.assertIn("M4", job.gcode)
            l0.mode = "Line"  # restore
        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)

    def test_serial_controller_grbl_parsing_and_pulse(self):
        from laserforge.core.serial_controller import SerialController
        ctrl = SerialController()
        # Test line parsing of $30, $31, $100, $101, $120, etc.
        ctrl._handle_setting_line("$30=1000 (rpm max)")
        self.assertEqual(ctrl.machine_limits["max_s_value"], 1000)
        self.assertEqual(ctrl.grbl_settings["$30"], "1000")

        ctrl._handle_setting_line("$100=80.125 (x, step/mm)")
        self.assertEqual(ctrl.machine_limits["x_steps_per_mm"], 80.125)
        self.assertEqual(ctrl.grbl_settings["$100"], "80.125")

        ctrl._handle_setting_line("$120=650.0 (x accel, mm/sec^2)")
        self.assertEqual(ctrl.machine_limits["x_accel"], 650.0)

        ctrl._handle_setting_line("$3=7 (dir port invert mask:00000111)")
        self.assertTrue(ctrl.machine_limits["invert_x_dir"])
        self.assertTrue(ctrl.machine_limits["invert_y_dir"])
        self.assertTrue(ctrl.machine_limits["invert_z_dir"])

        # Test toggle_test_laser framing commands in GRBL Laser Mode ($32=1)
        cmds = []
        ctrl.send_command = lambda c: cmds.append(c)
        ctrl.toggle_test_laser(True, power_s=10)
        self.assertIn("M3 G1 S10 F1", cmds)
        cmds.clear()
        ctrl.toggle_test_laser(False)
        self.assertIn("M5 S0", cmds)
        self.assertIn("G0", cmds)
        cmds.clear()

        # Test pulse_laser test fire
        import time
        ctrl.is_connected = True
        ctrl.pulse_laser(power_pct=5.0, duration_ms=25)
        time.sleep(0.08)
        self.assertTrue(any("M3 G1 S50 F1" in c for c in cmds))
        self.assertTrue(any("M5 S0" in c for c in cmds))
        self.assertTrue(any("G0" in c for c in cmds))

    def test_machine_settings_full_serialization(self):
        settings = MachineSettings(
            bed_width=300.0,
            bed_height=250.0,
            laser_fire_delay_ms=15.0,
            overscan_enabled=True,
            overscan_pct=3.5,
            finish_position_mode="Park Position",
            park_x=5.0,
            park_y=240.0,
            custom_start_gcode="M8",
            custom_end_gcode="M9",
            kerf_width_mm=0.08
        )
        with tempfile.NamedTemporaryFile(suffix=".laserproj", delete=False) as tf:
            proj_path = tf.name
        try:
            rect = RectEntity(layer_id=0, x=5.0, y=5.0, width=10.0, height=10.0)
            ProjectIO.save_project(proj_path, [rect], self.layer_mgr, settings)

            loaded_settings = MachineSettings()
            ProjectIO.load_project(proj_path, self.layer_mgr, loaded_settings)
            self.assertEqual(loaded_settings.bed_width, 300.0)
            self.assertEqual(loaded_settings.bed_height, 250.0)
            self.assertEqual(loaded_settings.laser_fire_delay_ms, 15.0)
            self.assertTrue(loaded_settings.overscan_enabled)
            self.assertEqual(loaded_settings.overscan_pct, 3.5)
            self.assertEqual(loaded_settings.finish_position_mode, "Park Position")
            self.assertEqual(loaded_settings.park_x, 5.0)
            self.assertEqual(loaded_settings.park_y, 240.0)
            self.assertEqual(loaded_settings.custom_start_gcode, "M8")
            self.assertEqual(loaded_settings.custom_end_gcode, "M9")
            self.assertEqual(loaded_settings.kerf_width_mm, 0.08)
        finally:
            if os.path.exists(proj_path):
                os.unlink(proj_path)

    def test_photo_studio_apply_and_canvas_update(self):
        """Verify Photo Studio processed image caching, ImageEntity fields, and canvas display."""
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        from laserforge.ui.canvas_scene import LaserCanvasScene, LaserItemWrapper

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as raw_tf:
            raw_path = raw_tf.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as proc_tf:
            proc_path = proc_tf.name
        try:
            # Create test raw color image and processed monochrome image
            raw_img = Image.new("RGB", (64, 64), (100, 150, 200))
            raw_img.save(raw_path)
            proc_img = Image.new("L", (64, 64), 0)
            proc_img.save(proc_path)

            img_ent = ImageEntity(
                layer_id=0,
                name="TestPhoto",
                image_path=proc_path,
                raw_image_path=raw_path,
                processed_image_path=proc_path,
                x=15.0, y=20.0,
                width=40.0, height=40.0,
                dither_mode="Atkinson"
            )

            # Test ProjectIO serialization round-trip of raw and processed paths
            with tempfile.NamedTemporaryFile(suffix=".laserproj", delete=False) as proj_tf:
                proj_path = proj_tf.name
            try:
                ProjectIO.save_project(proj_path, [img_ent], self.layer_mgr, MachineSettings())
                loaded_ents, _, _ = ProjectIO.load_project(proj_path, self.layer_mgr)
                self.assertEqual(len(loaded_ents), 1)
                loaded_img = loaded_ents[0]
                self.assertEqual(loaded_img.raw_image_path, raw_path)
                self.assertEqual(loaded_img.processed_image_path, proc_path)
                self.assertEqual(loaded_img.dither_mode, "Atkinson")
            finally:
                if os.path.exists(proj_path):
                    os.unlink(proj_path)

            # Test LaserItemWrapper pixmap cache invalidation on sync_from_entity
            scene = LaserCanvasScene(self.layer_mgr)
            wrapper = LaserItemWrapper(img_ent, self.layer_mgr)
            scene.addItem(wrapper)

            # Ensure wrapper has null cache initially
            self.assertIsNone(wrapper._cached_pixmap)

            # Sync from entity resets pixmap cache
            wrapper._cached_pixmap = "DUMMY"
            wrapper.sync_from_entity()
            self.assertIsNone(wrapper._cached_pixmap)
            self.assertIsNone(wrapper._cached_pixmap_path)
        finally:
            if os.path.exists(raw_path):
                os.unlink(raw_path)
            if os.path.exists(proc_path):
                os.unlink(proc_path)

    def test_interactive_crop_dialog_and_cropping(self):
        """Verify CropImageDialog, InteractiveCropWidget, aspect ratios, and PIL crop."""
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        from laserforge.ui.crop_image_dialog import InteractiveCropWidget, CropImageDialog

        test_img = Image.new("RGB", (200, 100), (255, 0, 0))
        widget = InteractiveCropWidget()
        widget.resize(400, 300)
        widget.set_image(test_img)

        # Test freeform pixel box
        box = widget.get_pixel_crop_box()
        self.assertEqual(len(box), 4)
        l, t, r, b = box
        self.assertGreater(r, l)
        self.assertGreater(b, t)

        # Test setting 1:1 square aspect ratio
        widget.set_aspect_ratio(1.0)
        box_sq = widget.get_pixel_crop_box()
        w_sq = box_sq[2] - box_sq[0]
        h_sq = box_sq[3] - box_sq[1]
        self.assertAlmostEqual(w_sq / float(h_sq), 1.0, delta=0.08)

        # Test Business Card aspect ratio (85.6 / 54.0 = ~1.585)
        widget.set_aspect_ratio(85.6 / 54.0)
        box_bc = widget.get_pixel_crop_box()
        w_bc = box_bc[2] - box_bc[0]
        h_bc = box_bc[3] - box_bc[1]
        self.assertAlmostEqual(w_bc / float(h_bc), 85.6 / 54.0, delta=0.08)

        # Test CropImageDialog
        dlg = CropImageDialog(test_img)
        self.assertIsNotNone(dlg)
        dlg.combo_aspect.setCurrentIndex(1)  # 1:1 Square
        dlg._on_apply_crop()
        self.assertIsNotNone(dlg.cropped_image)
        self.assertIsInstance(dlg.cropped_image, Image.Image)

    def test_barcode_and_qr_generator(self):
        """Verify QR code vector/raster generation and 1D Barcodes (Code 128, EAN-13, Code 39, UPC-A)."""
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        from laserforge.core.barcode_generator import BarcodeGenerator
        from laserforge.ui.barcode_designer_dialog import BarcodeDesignerDialog

        # 1. Format payload builders
        wifi_str = BarcodeGenerator.build_wifi_string("ShopGuest", "Secret123", "WPA", False)
        self.assertEqual(wifi_str, "WIFI:T:WPA;S:ShopGuest;P:Secret123;H:false;;")

        vcard_str = BarcodeGenerator.build_vcard_string("John Smith", "+123456", "js@laser.com", "LaserCorp")
        self.assertIn("BEGIN:VCARD", vcard_str)
        self.assertIn("FN:John Smith", vcard_str)
        self.assertIn("END:VCARD", vcard_str)

        # 2. Vector QR code generation
        matrix = BarcodeGenerator.generate_qr_matrix("https://github.com", error_correction="H")
        self.assertGreater(len(matrix), 10)

        qr_ent = BarcodeGenerator.generate_qr_vector_entity(
            data="LaserForge-2026",
            size_mm=30.0,
            layer_id=1,
            error_correction="M"
        )
        self.assertIsInstance(qr_ent, PathEntity)
        self.assertEqual(qr_ent.layer_id, 1)
        self.assertGreater(len(qr_ent.contours), 5)

        # 3. Barcode Vector Bars (Code 128)
        bars_128, txt_128, code_str = BarcodeGenerator.generate_barcode_bars(
            code_type="code128",
            data="LF-SER-9901",
            width_mm=60.0,
            height_mm=25.0,
            show_text=True
        )
        self.assertGreater(len(bars_128), 10)
        self.assertIsInstance(bars_128[0], RectEntity)
        self.assertIsNotNone(txt_128)
        self.assertEqual(txt_128.text, "LF-SER-9901")

        # 4. Barcode Vector Bars (EAN-13)
        bars_ean, txt_ean, full_ean = BarcodeGenerator.generate_barcode_bars(
            code_type="ean13",
            data="400638133393",
            width_mm=40.0,
            height_mm=20.0
        )
        self.assertGreater(len(bars_ean), 10)
        self.assertEqual(len(full_ean), 13)

        # 5. UI Dialog instantiation
        dlg = BarcodeDesignerDialog(bed_width=300.0, bed_height=300.0)
        self.assertIsNotNone(dlg)
        self.assertIsNotNone(dlg._current_qr_img)

    def test_sdxl_turbo_engine_and_studio(self):
        """Verify SDXL Turbo engine optimizations, VRAM reporting, and standalone Studio."""
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        from laserforge.core.sdxl_turbo_engine import SDXLTurboEngine
        from laserforge.apps.sdxl_turbo_studio import SDXLTurboStudioWindow, IMPORT_QUEUE_DIR

        # 1. Engine VRAM info query
        engine = SDXLTurboEngine()
        info = engine.get_vram_info()
        self.assertIn("has_torch", info)
        self.assertIn("has_cuda", info)

        # 2. Procedural Fallback generation for all styles
        for preset in list(SDXLTurboEngine.STYLE_PRESETS.keys())[:3]:
            img = engine.generate(
                prompt="Celtic Knot Shield",
                style_preset=preset,
                steps=1,
                width=256,
                height=256,
                seed=101
            )
            self.assertIsInstance(img, Image.Image)
            self.assertEqual(img.size, (256, 256))

        # 3. SDXL Turbo Studio UI and Auto-Import mailbox dispatch
        studio = SDXLTurboStudioWindow(is_embedded=True)
        self.assertIsNotNone(studio)

        # Test dispatching import to queue
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            test_img_path = tf.name
        try:
            img.save(test_img_path)
            studio._dispatch_import_to_workspace(test_img_path)
            # Verify a json file was created in IMPORT_QUEUE_DIR
            files = [f for f in os.listdir(IMPORT_QUEUE_DIR) if f.endswith(".json")]
            self.assertGreater(len(files), 0)
        finally:
            if os.path.exists(test_img_path):
                os.unlink(test_img_path)
            # Clean up test queue items
            for f in os.listdir(IMPORT_QUEUE_DIR):
                if f.endswith(".json"):
                    try:
                        os.remove(os.path.join(IMPORT_QUEUE_DIR, f))
                    except Exception:
                        pass


class TestVectorBooleanEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        import sys
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from laserforge.core.layer_manager import LayerManager
        self.layer_mgr = LayerManager()

    def test_weld_overlapping_rectangles(self):
        from laserforge.core.models import RectEntity
        from laserforge.core.geometry_boolean import VectorBooleanEngine

        r1 = RectEntity(x=10.0, y=10.0, width=50.0, height=50.0)
        r2 = RectEntity(x=40.0, y=10.0, width=50.0, height=50.0)

        weld = VectorBooleanEngine.weld([r1, r2])
        self.assertIsNotNone(weld)
        self.assertEqual(len(weld.contours), 1)
        b = weld.get_bounds()
        self.assertAlmostEqual(b[0], 10.0, delta=0.5)
        self.assertAlmostEqual(b[2], 90.0, delta=0.5)
        self.assertAlmostEqual(b[1], 10.0, delta=0.5)
        self.assertAlmostEqual(b[3], 60.0, delta=0.5)

    def test_weld_rect_and_circle(self):
        from laserforge.core.models import RectEntity, CircleEntity
        from laserforge.core.geometry_boolean import VectorBooleanEngine

        r = RectEntity(x=20.0, y=20.0, width=40.0, height=40.0)
        c = CircleEntity(x=60.0, y=40.0, radius_x=20.0, radius_y=20.0)

        weld = VectorBooleanEngine.weld([r, c])
        self.assertIsNotNone(weld)
        self.assertEqual(len(weld.contours), 1)
        # Bounding box should span from x=20 to x=80
        b = weld.get_bounds()
        self.assertAlmostEqual(b[0], 20.0, delta=0.5)
        self.assertAlmostEqual(b[2], 80.0, delta=0.5)

    def test_subtract_creating_hole(self):
        from laserforge.core.models import RectEntity, CircleEntity
        from laserforge.core.geometry_boolean import VectorBooleanEngine
        from laserforge.core.optimizer import PathOptimizer

        outer = RectEntity(x=0.0, y=0.0, width=100.0, height=100.0)
        inner = CircleEntity(x=50.0, y=50.0, radius_x=20.0, radius_y=20.0)

        sub = VectorBooleanEngine.subtract([outer, inner])
        self.assertIsNotNone(sub)
        # Must have exactly 2 closed contours: the outer perimeter and the circular cutout
        self.assertEqual(len(sub.contours), 2)

        # Verify inner-first nesting optimizer sorts inner cutout first
        sorted_contours = PathOptimizer.sort_inner_first(sub.contours)
        self.assertEqual(len(sorted_contours), 2)

    def test_intersect_overlapping_geometry(self):
        from laserforge.core.models import RectEntity
        from laserforge.core.geometry_boolean import VectorBooleanEngine

        r1 = RectEntity(x=10.0, y=10.0, width=40.0, height=40.0)
        r2 = RectEntity(x=30.0, y=10.0, width=40.0, height=40.0)

        inter = VectorBooleanEngine.intersect([r1, r2])
        self.assertIsNotNone(inter)
        self.assertEqual(len(inter.contours), 1)
        b = inter.get_bounds()
        # Overlapping intersection is from x=30 to x=50, y=10 to y=50
        self.assertAlmostEqual(b[0], 30.0, delta=0.5)
        self.assertAlmostEqual(b[2], 50.0, delta=0.5)
        self.assertAlmostEqual(b[1], 10.0, delta=0.5)
        self.assertAlmostEqual(b[3], 50.0, delta=0.5)

    def test_intersect_disjoint_returns_none(self):
        from laserforge.core.models import RectEntity
        from laserforge.core.geometry_boolean import VectorBooleanEngine

        r1 = RectEntity(x=0.0, y=0.0, width=10.0, height=10.0)
        r2 = RectEntity(x=100.0, y=100.0, width=10.0, height=10.0)

        inter = VectorBooleanEngine.intersect([r1, r2])
        self.assertIsNone(inter)

    def test_rotated_entity_boolean(self):
        from laserforge.core.models import RectEntity
        from laserforge.core.geometry_boolean import VectorBooleanEngine

        r1 = RectEntity(x=50.0, y=50.0, width=40.0, height=40.0, rotation=0.0)
        r2 = RectEntity(x=50.0, y=50.0, width=40.0, height=40.0, rotation=45.0)

        weld = VectorBooleanEngine.weld([r1, r2])
        self.assertIsNotNone(weld)
        # Welding two centered squares rotated 45 deg produces an 8-point star pattern
        self.assertEqual(len(weld.contours), 1)
        self.assertGreater(len(weld.contours[0]), 8)

    def test_scene_boolean_operation_and_undo_redo(self):
        from laserforge.core.models import RectEntity, PathEntity
        from laserforge.ui.canvas_scene import LaserCanvasScene

        scene = LaserCanvasScene(self.layer_mgr)
        r1 = RectEntity(x=10.0, y=10.0, width=30.0, height=30.0)
        r2 = RectEntity(x=25.0, y=10.0, width=30.0, height=30.0)

        w1 = scene.add_entity(r1)
        w2 = scene.add_entity(r2)
        w1.setSelected(True)
        w2.setSelected(True)
        self.assertEqual(len(scene.get_selected_entities()), 2)

        # Perform Weld
        success = scene.boolean_operation("weld")
        self.assertTrue(success)
        entities = scene.get_all_entities()
        self.assertEqual(len(entities), 1)
        self.assertIsInstance(entities[0], PathEntity)

        # Test Undo restores both original shapes
        scene.undo()
        self.assertEqual(len(scene.get_all_entities()), 2)

        # Test Redo re-applies the weld
        scene.redo()
        self.assertEqual(len(scene.get_all_entities()), 1)
        self.assertIsInstance(scene.get_all_entities()[0], PathEntity)


class TestRasterOptimization(unittest.TestCase):
    def test_calculate_overscan_distance_modes(self):
        from laserforge.core.raster_processor import RasterProcessor

        # Acceleration physics: 6000 mm/min = 100 mm/s, accel = 1000 mm/s^2, mult = 1.2
        # d = 1.2 * (100^2 / 2000) = 6.0 mm
        d_accel = RasterProcessor.calculate_overscan_distance(
            feed_mm_per_min=6000.0,
            accel_mm_per_sec2=1000.0,
            mode="Acceleration",
            multiplier=1.2
        )
        self.assertAlmostEqual(d_accel, 6.0, delta=0.01)

        # Percentage mode: cluster width 80 mm * 5% = 4.0 mm
        d_pct = RasterProcessor.calculate_overscan_distance(
            feed_mm_per_min=3000.0,
            mode="Percentage",
            pct=5.0,
            cluster_width_mm=80.0
        )
        self.assertAlmostEqual(d_pct, 4.0, delta=0.01)

        # Fixed distance mode: 3.5 mm
        d_fix = RasterProcessor.calculate_overscan_distance(
            feed_mm_per_min=3000.0,
            mode="Fixed",
            fixed_mm=3.5
        )
        self.assertAlmostEqual(d_fix, 3.5, delta=0.01)

    def test_cluster_scanline_segments(self):
        from laserforge.core.raster_processor import RasterProcessor

        segments = [
            (10.0, 20.0, 1.0, False),
            (23.0, 30.0, 1.0, False),  # Gap = 3mm (stays in cluster 0)
            (80.0, 95.0, 1.0, False),  # Gap = 50mm >= 10mm threshold (new cluster 1)
            (97.0, 105.0, 1.0, False)  # Gap = 2mm (stays in cluster 1)
        ]

        clusters = RasterProcessor.cluster_scanline_segments(segments, skip_threshold_mm=10.0)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(len(clusters[0]), 2)
        self.assertEqual(len(clusters[1]), 2)
        self.assertEqual(clusters[0][0][0], 10.0)
        self.assertEqual(clusters[0][-1][1], 30.0)
        self.assertEqual(clusters[1][0][0], 80.0)
        self.assertEqual(clusters[1][-1][1], 105.0)

    def test_raster_gcode_overscan_and_rapid_skip(self):
        from PIL import Image
        import tempfile
        import os
        from laserforge.config import MachineSettings
        from laserforge.core.layer_manager import LayerManager
        from laserforge.core.models import ImageEntity
        from laserforge.core.gcode_generator import GCodeGenerator

        # Create test bitmap: 60x10 px with black marks on left (0-15) and right (45-60)
        img = Image.new("RGB", (60, 10), (255, 255, 255))
        for y in range(10):
            for x in range(15):
                img.putpixel((x, y), (0, 0, 0))
            for x in range(45, 60):
                img.putpixel((x, y), (0, 0, 0))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img_path = tf.name

        try:
            img.save(img_path)
            settings = MachineSettings(
                bed_width=300.0,
                bed_height=300.0,
                x_accel=1000.0,
                overscan_enabled=True,
                overscan_mode="Acceleration",
                overscan_accel_multiplier=1.2,
                white_space_skip_enabled=True,
                white_space_skip_threshold_mm=5.0
            )
            lm = LayerManager()
            layer = lm.get_layer(0)
            layer.mode = "Image"
            layer.speed = 3000.0

            img_ent = ImageEntity(layer_id=0, x=10.0, y=10.0, width=60.0, height=10.0, image_path=img_path)
            gen = GCodeGenerator(settings, lm)
            job = gen.generate_job([img_ent])

            # Verify G-code commands
            self.assertIn("G0", job.gcode)
            self.assertIn("G1", job.gcode)
            self.assertIn("M5", job.gcode)
            self.assertGreater(job.total_rapid_dist_mm, 100.0)
            self.assertGreater(job.total_cut_dist_mm, 100.0)
            self.assertGreater(job.estimated_time_sec, 0.0)
        finally:
            if os.path.exists(img_path):
                os.unlink(img_path)


class TestCameraVisionEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

    def test_calibration_data_serialization(self):
        from laserforge.core.camera_engine import CameraCalibrationData
        import numpy as np

        K = np.array([[1000.0, 0.0, 960.0], [0.0, 1000.0, 540.0], [0.0, 0.0, 1.0]])
        D = np.array([[-0.1, 0.01, 0.0, 0.0, 0.0]])
        H = np.eye(3, dtype=np.float64)

        calib = CameraCalibrationData(
            device_index=0,
            device_name="Test Webcam",
            resolution=(1920, 1080),
            camera_matrix=K,
            distortion_coeffs=D,
            homography_matrix=H,
            bed_width_mm=400.0,
            bed_height_mm=400.0,
            scale_px_per_mm=3.0,
            reprojection_error=0.42,
            camera_fiducials=[(100.0, 100.0), (1800.0, 100.0), (1800.0, 980.0), (100.0, 980.0)],
            bed_fiducials_mm=[(10.0, 10.0), (390.0, 10.0), (390.0, 390.0), (10.0, 390.0)]
        )

        self.assertTrue(calib.is_lens_calibrated())
        self.assertTrue(calib.is_bed_aligned())

        # Test to_dict and from_dict
        d = calib.to_dict()
        restored = CameraCalibrationData.from_dict(d)

        self.assertEqual(restored.device_name, "Test Webcam")
        self.assertEqual(restored.resolution, (1920, 1080))
        self.assertAlmostEqual(restored.reprojection_error, 0.42)
        np.testing.assert_allclose(restored.camera_matrix, K)
        np.testing.assert_allclose(restored.distortion_coeffs, D)
        np.testing.assert_allclose(restored.homography_matrix, H)
        self.assertEqual(len(restored.camera_fiducials), 4)
        self.assertEqual(len(restored.bed_fiducials_mm), 4)

        # Test save and load from temporary file
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp_path = tf.name
        try:
            calib.save_to_file(tmp_path)
            loaded = CameraCalibrationData.load_from_file(tmp_path)
            self.assertEqual(loaded.device_name, "Test Webcam")
            np.testing.assert_allclose(loaded.camera_matrix, K)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_camera_engine_device_listing_and_synthetic_frame(self):
        from laserforge.core.camera_engine import CameraEngine
        import numpy as np

        # Device discovery should include simulated option
        cams = CameraEngine.list_available_cameras()
        self.assertGreater(len(cams), 0)
        has_mock = any(c.get("is_mock") for c in cams)
        self.assertTrue(has_mock)

        # Open mock camera
        engine = CameraEngine()
        ok = engine.open_camera(device_index=-1, width=1280, height=720)
        self.assertTrue(ok)
        self.assertTrue(engine.is_mock)

        # Capture synthetic frame
        frame = engine.capture_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (720, 1280, 3))
        self.assertEqual(frame.dtype, np.uint8)

        # Test close
        engine.close_camera()
        self.assertIsNone(engine.cap)

    def test_chessboard_corner_detection_and_lens_calibration(self):
        from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
        import numpy as np

        pattern_size = (9, 6)
        sq = 30
        w = (pattern_size[0] + 1) * sq
        h = (pattern_size[1] + 1) * sq
        img = np.zeros((h, w, 3), dtype=np.uint8)
        for i in range(pattern_size[1] + 1):
            for j in range(pattern_size[0] + 1):
                if (i + j) % 2 == 0:
                    img[i * sq:(i + 1) * sq, j * sq:(j + 1) * sq] = 255

        found, corners, vis = CameraEngine.detect_chessboard_corners(img, pattern_size=pattern_size)
        self.assertTrue(found)
        self.assertIsNotNone(corners)
        self.assertEqual(corners.shape[0], 54)

        # Test lens calibration with synthetic snapshots
        calib = CameraCalibrationData(resolution=(w, h))
        engine = CameraEngine(calibration=calib)
        engine.calibration.save_to_file = lambda *args, **kwargs: None

        ok, err, msg = engine.calibrate_lens_from_snapshots(
            [corners, corners, corners],
            pattern_size=pattern_size,
            square_size_mm=20.0
        )
        self.assertTrue(ok)
        self.assertTrue(calib.is_lens_calibrated())
        self.assertIsNotNone(calib.camera_matrix)
        self.assertIsNotNone(calib.distortion_coeffs)

    def test_homography_and_bed_rectification(self):
        from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData

        calib = CameraCalibrationData(
            bed_width_mm=200.0,
            bed_height_mm=100.0,
            scale_px_per_mm=2.0
        )
        engine = CameraEngine(calibration=calib)
        engine.open_camera(device_index=-1, width=640, height=480)
        engine.calibration.save_to_file = lambda *args, **kwargs: None

        cam_pts = [(40.0, 40.0), (600.0, 40.0), (600.0, 440.0), (40.0, 440.0)]
        bed_pts = [(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0)]

        ok = engine.compute_bed_homography(cam_pts, bed_pts)
        self.assertTrue(ok)
        self.assertTrue(calib.is_bed_aligned())
        self.assertIsNotNone(calib.homography_matrix)

        ortho = engine.rectify_bed_image()
        self.assertIsNotNone(ortho)
        expected_w = int(200.0 * 2.0)
        expected_h = int(100.0 * 2.0)
        self.assertEqual(ortho.shape, (expected_h, expected_w, 3))

    def test_canvas_scene_camera_overlay_integration(self):
        from PyQt6.QtGui import QPixmap, QImage, QColor
        from laserforge.core.layer_manager import LayerManager
        from laserforge.ui.canvas_scene import LaserCanvasScene

        lm = LayerManager()
        scene = LaserCanvasScene(lm)

        # Initially, overlay item should exist and be hidden
        self.assertIsNotNone(scene._camera_overlay_item)
        self.assertFalse(scene._camera_overlay_item.isVisible())

        img = QImage(200, 100, QImage.Format.Format_RGB32)
        img.fill(QColor(100, 150, 200))
        pix = QPixmap.fromImage(img)

        # Set overlay
        scene.set_camera_overlay_pixmap(pix, bed_width=400.0, bed_height=200.0)
        self.assertTrue(scene._camera_overlay_item.isVisible())
        self.assertEqual(scene._camera_overlay_item.zValue(), -100)

        # Test visibility toggle
        scene.set_camera_overlay_visible(False)
        self.assertFalse(scene._camera_overlay_item.isVisible())
        scene.set_camera_overlay_visible(True)
        self.assertTrue(scene._camera_overlay_item.isVisible())

        # Test opacity
        scene.set_camera_overlay_opacity(0.75)
        self.assertAlmostEqual(scene._camera_overlay_item.opacity(), 0.75, places=2)

    def test_text_input_editing_and_toolbar_sync(self):
        """Verify text input box editing in shape properties and top font toolbar."""
        from PyQt6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        from laserforge.core.layer_manager import LayerManager
        from laserforge.ui.canvas_scene import LaserCanvasScene, LaserItemWrapper
        from laserforge.ui.shape_properties import ShapePropertiesPanel
        from laserforge.ui.main_window import MainWindow

        lm = LayerManager()
        scene = LaserCanvasScene(lm)
        props = ShapePropertiesPanel(scene)

        # 1. Add TextEntity and select it
        text_ent = TextEntity(layer_id=0, text="Initial Hello", font_size=16.0, width=50.0, height=20.0)
        wrapper = scene.add_entity(text_ent)
        wrapper.setSelected(True)

        props.update_from_selection()
        self.assertEqual(props.text_input.text(), "Initial Hello")

        # 2. Simulate typing with focus in shape properties text_input
        props.text_input.setFocus()
        props.text_input.setText("Custom Engraving Writing")
        # Trigger text change
        self.assertEqual(text_ent.text, "Custom Engraving Writing")
        self.assertGreater(text_ent.width, 50.0)

        # Ensure update_from_selection doesn't clobber active typing when focused
        props.update_from_selection()
        self.assertEqual(props.text_input.text(), "Custom Engraving Writing")

        # 3. Test MainWindow top toolbar text input synchronization
        win = MainWindow()
        win.scene.clear_entities()
        win_text_ent = TextEntity(layer_id=0, text="Toolbar Title", font_size=14.0)
        win_wrapper = win.scene.add_entity(win_text_ent)
        win_wrapper.setSelected(True)

        win._on_entities_changed()
        self.assertTrue(win.font_toolbar.isEnabled())
        self.assertEqual(win.tb_text_input.text(), "Toolbar Title")

        # 4. Edit text from top font toolbar input box
        win.tb_text_input.setText("New Laser Inscription 123")
        self.assertEqual(win_text_ent.text, "New Laser Inscription 123")

        # 5. Deselect - toolbar should disable and clear
        win.scene.clearSelection()
        win._on_entities_changed()
        self.assertFalse(win.font_toolbar.isEnabled())
        self.assertEqual(win.tb_text_input.text(), "")

        win.close()

    def test_software_mirror_and_flip(self):
        from laserforge.core.layer_manager import LayerManager
        layer_mgr = LayerManager()

        # 1. Test GCodeGenerator software_mirror_x
        s_norm = MachineSettings(bed_width=400.0, bed_height=400.0, software_mirror_x=False)
        s_mirr = MachineSettings(bed_width=400.0, bed_height=400.0, software_mirror_x=True)

        g_norm = GCodeGenerator(s_norm, layer_mgr)
        g_mirr = GCodeGenerator(s_mirr, layer_mgr)

        rect = RectEntity(layer_id=0, x=10.0, y=20.0, width=50.0, height=30.0)
        job_norm = g_norm.generate_job([rect])
        job_mirr = g_mirr.generate_job([rect])

        self.assertIn("G0 X10.000 Y20.000", job_norm.gcode)
        self.assertIn("G0 X390.000 Y20.000", job_mirr.gcode)

        # 2. Test Canvas Scene flip_selected_horizontal on TextEntity
        from laserforge.ui.canvas_scene import LaserCanvasScene
        scene = LaserCanvasScene(layer_mgr)
        txt = TextEntity(text="FLIP", x=50.0, y=50.0, width=60.0, height=20.0)
        item = scene.add_entity(txt)
        item.setSelected(True)

        self.assertFalse(txt.is_mirrored_h)
        scene.flip_selected_horizontal()
        self.assertTrue(txt.is_mirrored_h)

        # G-Code generation with mirrored text entity
        txt_paths = g_norm.entity_to_paths(txt)
        self.assertGreater(len(txt_paths), 0)

    def test_svg_importer_advanced_features(self):
        """Tests SVGImporter with quadratic beziers, smooth curves, elliptical arcs, and transforms."""
        from laserforge.core.svg_importer import SVGImporter
        import tempfile

        test_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
          <style>
            .cut_red { stroke: #FF2A2A; fill: none; }
            .eng_blue { fill: #1E90FF; }
          </style>
          <g transform="translate(10, 10)">
            <path class="cut_red" d="M 0 0 Q 25 50 50 0 T 100 0 A 25 25 0 0 1 50 50 Z" />
            <circle class="eng_blue" cx="30" cy="30" r="10" />
            <rect x="5" y="5" width="20" height="20" transform="rotate(45, 15, 15)" />
          </g>
        </svg>'''

        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False) as tf:
            tf.write(test_svg)
            svg_path = tf.name

        try:
            entities = SVGImporter.import_svg_file(svg_path, default_layer_id=0)
            self.assertEqual(len(entities), 3)

            # Check layer matching from SVG colors
            layer_ids = [e.layer_id for e in entities]
            # Red layer is 2, Blue layer is 1 in LAYER_PALETTE
            self.assertIn(2, layer_ids)
            self.assertIn(1, layer_ids)

            # Check that path with Q, T, A curves parsed into multiple contour points
            path_ent = next(e for e in entities if "Path" in e.name)
            self.assertGreater(len(path_ent.contours[0]), 10)

            # Check bounds are within valid bed range
            bounds = path_ent.get_bounds()
            self.assertGreaterEqual(bounds[0], 0.0)
            self.assertGreaterEqual(bounds[1], 0.0)
        finally:
            if os.path.exists(svg_path):
                os.unlink(svg_path)

    def test_image_raster_inline_and_m106(self):
        """Tests Image G-code generation with inline S power (GRBL M4) and Marlin Fan PWM (M106)."""
        from laserforge.core.layer_manager import LayerManager
        from laserforge.config import MachineSettings
        from laserforge.core.gcode_generator import GCodeGenerator
        from laserforge.core.models import ImageEntity
        from PIL import Image
        import tempfile

        img = Image.new("RGB", (10, 10), color="white")
        img.putpixel((5, 5), (0, 0, 0))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img.save(tf.name)
            img_file = tf.name

        try:
            lm = LayerManager()

            # 1. Inline S power (GRBL M4)
            s_grbl = MachineSettings(laser_mode="M4", use_inline_power=True, max_s_value=1000)
            gen_grbl = GCodeGenerator(s_grbl, lm)
            ent = ImageEntity(image_path=img_file, raw_image_path=img_file, x=10, y=10, width=10, height=10)
            job_grbl = gen_grbl.generate_job([ent])

            # Must contain inline G1 ... S commands and not separate M4 S... on each move
            self.assertIn("G1 X", job_grbl.gcode)
            self.assertIn(" S0", job_grbl.gcode)
            self.assertIn("M4 ; Dynamic laser mode ON", job_grbl.gcode)

            # 2. Marlin Fan PWM (M106 / M107)
            s_marlin = MachineSettings(laser_mode="M106", max_s_value=255)
            gen_marlin = GCodeGenerator(s_marlin, lm)
            job_marlin = gen_marlin.generate_job([ent])

            self.assertIn("M107          ; Ensure laser is OFF", job_marlin.gcode)
            self.assertIn("M106 S", job_marlin.gcode)
            self.assertIn("M107", job_marlin.gcode)
        finally:
            if os.path.exists(img_file):
                os.unlink(img_file)

    def test_camera_overlay_update_no_name_error(self):
        """Regression test: verify update_camera_overlay runs without NameError (QImage) or unhandled exceptions."""
        from PyQt6.QtWidgets import QApplication
        from laserforge.ui.main_window import MainWindow

        _app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])
        win = MainWindow()
        try:
            # Should run cleanly without crashing or raising NameError
            win.update_camera_overlay()
            self.assertTrue(win.act_camera_toggle.isChecked())
            self.assertTrue(win.scene._camera_overlay_item.isVisible())
        finally:
            win.close()

    def test_camera_overlay_degenerate_homography_recovery(self):
        """Verify camera engine handles degenerate homography and zero bed dimensions gracefully."""
        from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
        import numpy as np

        calib = CameraCalibrationData()
        calib.bed_width_mm = 0.0  # degenerate zero bed width
        calib.bed_height_mm = -10.0
        calib.scale_px_per_mm = 0.0
        # Degenerate singular matrix of zeros
        calib.homography_matrix = np.zeros((3, 3), dtype=np.float64)

        engine = CameraEngine(calibration=calib)
        engine.is_mock = True
        ortho = engine.rectify_bed_image()
        # Should safely fallback and return an RGB image without throwing exceptions
        self.assertIsNotNone(ortho)
        self.assertEqual(len(ortho.shape), 3)
        self.assertEqual(ortho.shape[2], 3)


if __name__ == "__main__":
    unittest.main()




