"""
Comprehensive Unit Tests for LaserForge Phase 1 (Professional Completeness):
  1. DXF Import & Export (ezdxf)
  2. Full Canvas SVG Export
  3. SVG <defs> and <use> Support
  4. Job Cost & Time Estimator
  5. Serial Controller Streaming Guards & Z-Probe
  6. Snap-to-Grid & Alignment Guides
"""

import unittest
import os
import tempfile
import math
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, QRectF
import ezdxf

# Ensure QApplication exists for UI tests
app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.models import (
    RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)
from laserforge.core.dxf_importer import DXFImporter
from laserforge.core.dxf_exporter import DXFExporter
from laserforge.core.svg_exporter import SVGExporter
from laserforge.core.svg_importer import SVGImporter
from laserforge.core.gcode_generator import GCodeJobResult, GCodeGenerator, ToolpathSegment
from laserforge.ui.job_estimator_dialog import JobEstimatorDialog
from laserforge.core.serial_controller import SerialController
from laserforge.ui.canvas_scene import LaserCanvasScene, LaserItemWrapper, GuideLineItem


class TestPhase1(unittest.TestCase):

    def setUp(self):
        self.layer_mgr = LayerManager()
        self.settings = MachineSettings()

    def test_dxf_export_and_import_roundtrip(self):
        """Tests DXF export and re-importing preserves geometries."""
        entities = [
            RectEntity(layer_id=1, name="Box", x=10.0, y=10.0, width=40.0, height=30.0, corner_radius=0.0),
            CircleEntity(layer_id=2, name="Hole", x=50.0, y=50.0, radius_x=12.0, radius_y=12.0),
            LineEntity(layer_id=0, name="Divider", x=0.0, y=0.0, x2=100.0, y2=100.0),
            PathEntity(layer_id=1, name="Shape", x=20.0, y=20.0, contours=[[(0, 0), (20, 0), (10, 15), (0, 0)]], closed=True)
        ]

        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tf:
            dxf_path = tf.name

        try:
            # Export
            export_ok = DXFExporter.export_dxf_file(entities, dxf_path)
            self.assertTrue(export_ok)
            self.assertTrue(os.path.exists(dxf_path))
            self.assertGreater(os.path.getsize(dxf_path), 200)

            # Re-import
            imported = DXFImporter.import_dxf_file(dxf_path)
            self.assertEqual(len(imported), 4)

            # Verify entities have valid bounds
            for ent in imported:
                b = ent.get_bounds()
                w = b[2] - b[0]
                h = b[3] - b[1]
                self.assertGreater(w, 0.0)
                self.assertGreater(h, 0.0)
        finally:
            if os.path.exists(dxf_path):
                os.remove(dxf_path)

    def test_svg_export_full_canvas(self):
        """Tests SVGExporter produces valid SVG with proper layer groupings."""
        entities = [
            RectEntity(layer_id=0, name="Base", x=5.0, y=5.0, width=50.0, height=40.0),
            CircleEntity(layer_id=2, name="Ring", x=60.0, y=60.0, radius_x=10.0, radius_y=10.0),
            TextEntity(layer_id=1, name="Label", x=10.0, y=80.0, text="LaserForge CAD")
        ]

        svg_content = SVGExporter.export_svg_string(entities)
        self.assertIn("<svg", svg_content)
        self.assertIn("</svg>", svg_content)
        self.assertIn("<rect", svg_content)
        self.assertIn("<circle", svg_content)
        self.assertIn("<text", svg_content)
        self.assertIn("LaserForge CAD", svg_content)

        # File export
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
            svg_path = tf.name
        try:
            ok = SVGExporter.export_svg_file(entities, svg_path)
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(svg_path))
            self.assertGreater(os.path.getsize(svg_path), 200)
        finally:
            if os.path.exists(svg_path):
                os.remove(svg_path)

    def test_svg_defs_and_use_import(self):
        """Tests SVGImporter correctly parses <use> elements and suppresses raw <defs>."""
        svg_xml = """<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="200mm" viewBox="0 0 200 200">
  <defs>
    <rect id="widget" x="0" y="0" width="30" height="20" stroke="#000000" fill="none" />
  </defs>
  <use href="#widget" x="10" y="10" />
  <use href="#widget" x="60" y="60" />
</svg>"""

        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False) as tf:
            tf.write(svg_xml)
            svg_path = tf.name

        try:
            imported = SVGImporter.import_svg_file(svg_path)
            # Should import exactly 2 entities (one per <use>), not 3
            self.assertEqual(len(imported), 2)
            for ent in imported:
                b = ent.get_bounds()
                self.assertAlmostEqual(b[2] - b[0], 30.0, delta=1.0)
                self.assertAlmostEqual(b[3] - b[1], 20.0, delta=1.0)
        finally:
            if os.path.exists(svg_path):
                os.remove(svg_path)

    def test_job_cost_estimator_dialog(self):
        """Tests JobEstimatorDialog metrics and cost calculations."""
        segments = [
            ToolpathSegment("rapid", 0, 0, 10, 10, 3000, 0, 0, "#000"),
            ToolpathSegment("cut", 10, 10, 110, 10, 500, 100, 2, "#F00")
        ]
        job = GCodeJobResult(
            gcode="G0 X10 Y10\nG1 X110 Y10 F500 S1000\n",
            segments=segments,
            total_cut_dist_mm=100.0,
            total_rapid_dist_mm=14.14,
            estimated_time_sec=120.0,
            bounding_box=(10.0, 10.0, 110.0, 10.0)
        )

        dlg = JobEstimatorDialog(job)
        # 120 seconds -> 02m 00s
        self.assertEqual(dlg._format_time(120), "02m 00s")
        self.assertEqual(dlg._format_time(3665), "1h 01m 05s")

        # Check total cost calculation
        dlg._calculate_costs()
        cost_text = dlg.lbl_total_cost.text()
        self.assertTrue(cost_text.startswith("$"))
        self.assertGreater(float(cost_text.replace("$", "")), 0.0)

    def test_serial_streaming_guard_and_z_probe(self):
        """Tests SerialController protects against mid-job motor moves and generates Z-probe G-code."""
        ctrl = SerialController()
        # Mock connection
        ctrl.is_connected = True

        commands_sent = []
        ctrl.send_command = lambda cmd: commands_sent.append(cmd)

        # 1. When not streaming, go_to_pos works
        ctrl.is_streaming = False
        ctrl.go_to_pos(50.0, 25.0)
        self.assertEqual(len(commands_sent), 1)
        self.assertIn("G90 G0 X50.000 Y25.000", commands_sent[0])

        # 2. When streaming, go_to_pos is blocked
        ctrl.is_streaming = True
        ctrl.go_to_pos(100.0, 100.0)
        self.assertEqual(len(commands_sent), 1)  # No new command sent

        # 3. When streaming, go_to_zero is blocked
        ctrl.go_to_zero()
        self.assertEqual(len(commands_sent), 1)  # Blocked

        # 4. Z-Probe cycle test
        ctrl.is_streaming = False
        ctrl.probe_z(max_travel_mm=30.0, feed=60.0, plate_thickness_mm=1.5)
        # Should have sent G38.2, G10 L20 P1, G0 Z3.0, G90
        probe_cmds = " ".join(commands_sent)
        self.assertIn("G38.2 Z-30.00 F60", probe_cmds)
        self.assertIn("G10 L20 P1 Z1.500", probe_cmds)
        self.assertIn("G0 Z3.0", probe_cmds)

    def test_snap_to_grid_and_guides(self):
        """Tests LaserCanvasScene grid snapping and alignment guides."""
        scene = LaserCanvasScene(self.layer_mgr)
        rect_ent = RectEntity(x=10.0, y=10.0, width=50.0, height=30.0)
        wrapper = scene.add_entity(rect_ent)

        # Snap to 5mm grid
        scene.set_snap_to_grid(True, grid_size=5.0)
        self.assertTrue(scene.snap_to_grid)
        self.assertEqual(scene.snap_grid_mm, 5.0)

        # Move item to (12.3, 18.7) -> should snap to (10.0, 20.0)
        snapped_pos = wrapper.itemChange(
            LaserItemWrapper.GraphicsItemChange.ItemPositionChange,
            QPointF(12.3, 18.7)
        )
        self.assertEqual(snapped_pos.x(), 10.0)
        self.assertEqual(snapped_pos.y(), 20.0)

        # Alignment guides
        self.assertEqual(len(scene.guides), 0)
        scene.add_guide("horizontal", 50.0)
        scene.add_guide("vertical", 75.0)
        self.assertEqual(len(scene.guides), 2)
        self.assertTrue(scene.guides[0].isVisible())

        # Toggle visibility
        scene.set_guides_visible(False)
        self.assertFalse(scene.guides[0].isVisible())

        # Clear guides
        scene.clear_guides()
        self.assertEqual(len(scene.guides), 0)


if __name__ == "__main__":
    unittest.main()
