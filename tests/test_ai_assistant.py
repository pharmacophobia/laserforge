"""
Unit Tests for LaserForge DeepSeek AI Assistant & Copilot Engine.
Tests:
- Tool definitions and JSON schemas
- Mechanical bed alignment diagnostics (skew, reprojection errors, leveling)
- Camera status and configuration telemetry
- CAD object manipulation (translation, scaling, rotation, undo)
- Workbed alignment and fit-to-bed scaling
- Primitive creation (rect, circle, text)
- Workpiece detection and artwork placement
- Multi-turn tool calling simulation
- Offline heuristic command fallback
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List

from PyQt6.QtWidgets import QApplication
import sys

# Ensure QApplication exists for scene and widget tests
app = QApplication.instance() or QApplication(sys.argv)

from laserforge.config import MachineSettings
from laserforge.core.models import RectEntity, CircleEntity, TextEntity, PathEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.auto_calibration import AutoCalibrationEngine, AutoCalibrationResult, CalibrationPoint
from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
from laserforge.core.ai_assistant import AIAssistantEngine, TOOL_DEFINITIONS
from laserforge.ui.canvas_scene import LaserCanvasScene


class TestAIAssistant(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0)
        self.layer_manager = LayerManager()
        self.scene = LaserCanvasScene(self.layer_manager)
        self.camera_engine = CameraEngine()
        self.auto_calib_engine = AutoCalibrationEngine()

        self.engine = AIAssistantEngine(
            settings=self.settings,
            scene=self.scene,
            camera_engine=self.camera_engine,
            auto_calib_engine=self.auto_calib_engine
        )

    def test_tool_definitions_schema(self):
        """Verifies that all required tools are defined with valid OpenAI function schemas."""
        tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
        expected_tools = [
            "diagnose_bed_alignment",
            "get_camera_status",
            "get_scene_summary",
            "transform_objects",
            "align_objects",
            "fit_to_bed",
            "create_primitive",
            "detect_and_place_on_workpiece"
        ]
        for expected in expected_tools:
            self.assertIn(expected, tool_names)

        # Ensure parameters are object types with property dictionaries
        for t in TOOL_DEFINITIONS:
            fn = t["function"]
            self.assertIn("description", fn)
            self.assertEqual(fn["parameters"]["type"], "object")
            self.assertIsInstance(fn["parameters"]["properties"], dict)

    def test_diagnose_bed_alignment_uncalibrated(self):
        """Checks telemetry when no calibration has been performed yet."""
        if self.camera_engine and self.camera_engine.calibration:
            self.camera_engine.calibration.homography_matrix = None
        res = self.engine.execute_tool("diagnose_bed_alignment", {})
        self.assertTrue(res["success"])
        telemetry = res["telemetry"]
        self.assertFalse(telemetry["calibrated"])
        self.assertTrue(len(telemetry["recommendations"]) > 0)
        self.assertIn("Auto-Calibrate", telemetry["recommendations"][0])

    def test_diagnose_bed_alignment_skew_and_error(self):
        """Tests diagnostic interpretation of gantry skew and RMS reprojection error."""
        mock_result = AutoCalibrationResult(
            success=True,
            reprojection_error_rms_mm=0.92,
            reprojection_error_rms_px=2.76,
            gantry_skew_deg=0.48,
            scale_x=1.04,
            scale_y=0.98,
            quality_score=78.5,
            message="Auto-calibration completed with high skew."
        )
        self.auto_calib_engine.last_result = mock_result

        res = self.engine.execute_tool("diagnose_bed_alignment", {})
        self.assertTrue(res["success"])
        telemetry = res["telemetry"]
        self.assertTrue(telemetry["calibrated"])
        self.assertAlmostEqual(telemetry["gantry_skew_deg"], 0.48)

        # Verify gantry racking warning and recommendations were generated
        diagnostics_text = " ".join(telemetry["diagnostics"])
        recommendations_text = " ".join(telemetry["recommendations"])
        self.assertIn("gantry skew", diagnostics_text.lower())
        self.assertIn("belt tension", recommendations_text.lower())
        self.assertIn("honeycomb", recommendations_text.lower())

    def test_get_camera_status(self):
        """Verifies camera configuration and status retrieval."""
        res = self.engine.execute_tool("get_camera_status", {})
        self.assertTrue(res["success"])
        cam = res["camera"]
        self.assertIn("resolution", cam)
        self.assertIn("lens_distortion_calibrated", cam)
        self.assertIn("bed_homography_aligned", cam)

    def test_get_scene_summary(self):
        """Tests scene object enumeration and bounds reporting."""
        rect = RectEntity(x=20.0, y=30.0, width=50.0, height=40.0)
        circle = CircleEntity(x=100.0, y=100.0, radius_x=15.0, radius_y=15.0)
        self.scene.add_entity(rect)
        self.scene.add_entity(circle)

        res = self.engine.execute_tool("get_scene_summary", {})
        self.assertTrue(res["success"])
        self.assertEqual(res["total_entities"], 2)
        entities = res["entities"]
        types = [e["type"] for e in entities]
        self.assertIn("RectEntity", types)
        self.assertIn("CircleEntity", types)

    def test_transform_objects(self):
        """Tests moving, scaling, and rotating canvas entities via tool calling."""
        rect = RectEntity(x=10.0, y=10.0, width=20.0, height=20.0)
        wrapper = self.scene.add_entity(rect)

        # Move right by 15mm, down by 25mm, scale 2x
        res = self.engine.execute_tool("transform_objects", {
            "target": "all",
            "dx_mm": 15.0,
            "dy_mm": 25.0,
            "scale_factor": 2.0,
            "rotate_deg": 45.0
        })
        self.assertTrue(res["success"])
        self.assertEqual(res["transformed_count"], 1)

        # Check entity was transformed
        self.assertAlmostEqual(rect.width, 40.0)
        self.assertAlmostEqual(rect.height, 40.0)
        self.assertAlmostEqual(rect.rotation, 45.0)

        # Verify undo works
        self.scene.undo()
        entities = self.scene.get_all_entities()
        self.assertEqual(len(entities), 1)
        self.assertAlmostEqual(entities[0].width, 20.0)

    def test_align_objects_bed_center(self):
        """Tests centering objects on the active laser workbed."""
        rect = RectEntity(x=0.0, y=0.0, width=50.0, height=50.0)
        self.scene.add_entity(rect)

        res = self.engine.execute_tool("align_objects", {"mode": "bed_center"})
        self.assertTrue(res["success"])

        # Bed is 400x400, center is (200, 200). For 50x50 rect, (x, y) should be (175, 175)
        self.assertAlmostEqual(rect.x, 175.0)
        self.assertAlmostEqual(rect.y, 175.0)

    def test_fit_to_bed(self):
        """Tests proportional downscaling and centering of oversized artwork."""
        # Create an oversized shape (500x500 mm on a 400x400 mm bed)
        rect = RectEntity(x=0.0, y=0.0, width=500.0, height=500.0)
        self.scene.add_entity(rect)

        res = self.engine.execute_tool("fit_to_bed", {"margin_mm": 10.0, "target": "all"})
        self.assertTrue(res["success"])

        # Usable bed size: 400 - 2*10 = 380mm
        # Expected scale factor = 380 / 500 = 0.76
        self.assertAlmostEqual(res["scale_factor"], 0.76, places=2)
        b = rect.get_bounds()
        self.assertAlmostEqual(b[2] - b[0], 380.0, places=1)
        self.assertAlmostEqual(b[3] - b[1], 380.0, places=1)

    def test_create_primitive(self):
        """Tests creating rectangles, circles, and text entities."""
        res_rect = self.engine.execute_tool("create_primitive", {
            "shape_type": "rect",
            "x": 30.0,
            "y": 40.0,
            "width": 60.0,
            "height": 35.0,
            "layer_id": 1
        })
        self.assertTrue(res_rect["success"])

        res_circle = self.engine.execute_tool("create_primitive", {
            "shape_type": "circle",
            "x": 120.0,
            "y": 120.0,
            "radius": 20.0,
            "layer_id": 2
        })
        self.assertTrue(res_circle["success"])

        res_text = self.engine.execute_tool("create_primitive", {
            "shape_type": "text",
            "x": 50.0,
            "y": 80.0,
            "text": "DeepSeek Cut"
        })
        self.assertTrue(res_text["success"])

        all_ents = self.scene.get_all_entities()
        self.assertEqual(len(all_ents), 3)

    def test_detect_and_place_on_workpiece(self):
        """Tests placing selected artwork inside a detected/simulated workpiece."""
        # Simulated stock is (50, 50, 150, 100), center is (125, 100)
        rect = RectEntity(x=0.0, y=0.0, width=40.0, height=20.0)
        self.scene.add_entity(rect)

        res = self.engine.execute_tool("detect_and_place_on_workpiece", {
            "margin_mm": 5.0,
            "align": "center"
        })
        self.assertTrue(res["success"])
        b = rect.get_bounds()
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0
        self.assertAlmostEqual(cx, 125.0, places=1)
        self.assertAlmostEqual(cy, 100.0, places=1)

    def test_offline_heuristics(self):
        """Tests instant offline command processing without network or API key."""
        rect = RectEntity(x=10.0, y=10.0, width=50.0, height=50.0)
        self.scene.add_entity(rect)

        reply = self.engine.send_prompt("center on bed")
        self.assertIn("bed_center", reply)
        self.assertAlmostEqual(rect.x, 175.0)

        diag_reply = self.engine.send_prompt("diagnose gantry skew and bed alignment")
        self.assertIn("Bed Alignment Telemetry", diag_reply)

    def test_simulated_multi_turn_tool_calling(self):
        """Simulates DeepSeek API responding with a tool call and receiving results."""
        rect = RectEntity(x=0.0, y=0.0, width=100.0, height=100.0)
        self.scene.add_entity(rect)

        # Mock API responses: Turn 1 requests tool call, Turn 2 gives final explanation
        turn1_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "align_objects",
                            "arguments": json_dumps({"mode": "bed_center"})
                        }
                    }]
                }
            }]
        }
        turn2_response = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "I have centered your 100x100mm artwork on the laser bed."
                }
            }]
        }

        # Set fake API key to bypass offline heuristics
        self.settings.ai_api_key = "sk-fake-test-key"

        with patch.object(self.engine, "_http_post_json", side_effect=[turn1_response, turn2_response]):
            reply = self.engine.send_prompt("Please center my shape on the bed.")
            self.assertEqual(reply, "I have centered your 100x100mm artwork on the laser bed.")
            self.assertAlmostEqual(rect.x, 150.0)
            self.assertAlmostEqual(rect.y, 150.0)

    def test_ai_assistant_panel_ui(self):
        """Verifies AIAssistantPanel widget controls and signal integration."""
        from laserforge.ui.ai_assistant_panel import AIAssistantPanel
        panel = AIAssistantPanel(
            settings=self.settings,
            scene=self.scene,
            camera_engine=self.camera_engine
        )
        self.assertIsNotNone(panel.chat_display)
        self.assertIsNotNone(panel.input_edit)
        self.assertIsNotNone(panel.btn_send)

        # Test settings drawer toggle
        self.assertTrue(panel.settings_group.isHidden())
        panel.btn_settings_toggle.setChecked(True)
        panel._toggle_settings()
        self.assertFalse(panel.settings_group.isHidden())

        # Test quick action trigger
        rect = RectEntity(x=0.0, y=0.0, width=50.0, height=50.0)
        self.scene.add_entity(rect)
        panel.trigger_quick_command("center on bed")
        if panel.current_worker:
            panel.current_worker.wait(1000)
        self.assertAlmostEqual(rect.x, 175.0)

    def test_optimize_engrave_time(self):
        """Verifies speed bottleneck detection and automatic layer/canvas optimizations."""
        # Setup layer with small line interval (0.05 mm = 508 DPI)
        layer = self.scene.layer_manager.get_layer(0)
        layer.mode = "Fill"
        layer.line_interval = 0.05

        # Setup tall narrow shape (30mm wide x 150mm tall)
        rect = RectEntity(x=20.0, y=20.0, width=30.0, height=150.0, layer_id=0)
        self.scene.add_entity(rect)

        # Audit only (apply_optimizations=False)
        res_audit = self.engine.execute_tool("optimize_engrave_time", {"apply_optimizations": False})
        self.assertTrue(res_audit["success"])
        self.assertFalse(res_audit["applied"])
        self.assertTrue(res_audit["estimated_time_savings_pct"] >= 40.0)
        self.assertTrue(len(res_audit["bottlenecks_detected"]) >= 2)

        # Apply optimizations
        res_apply = self.engine.execute_tool("optimize_engrave_time", {"apply_optimizations": True})
        self.assertTrue(res_apply["success"])
        self.assertTrue(res_apply["applied"])
        # Check layer line interval was updated
        self.assertAlmostEqual(layer.line_interval, 0.085, places=3)
        # Check artwork was rotated 90 degrees to align with fast X axis
        self.assertAlmostEqual(rect.rotation, 90.0)

    def test_apply_material_preset(self):
        """Verifies searching and applying material presets to layers."""
        res = self.engine.execute_tool("apply_material_preset", {
            "material": "birch plywood",
            "operation": "engrave",
            "layer_id": 0
        })
        self.assertTrue(res["success"])
        preset = res["matched_preset"]
        self.assertIn("Birch", preset["name"])
        layer = self.scene.layer_manager.get_layer(0)
        self.assertEqual(layer.speed, preset["speed"])
        self.assertEqual(layer.power_max, preset["power_pct"])
        self.assertEqual(layer.line_interval, preset["line_interval"])


def json_dumps(d: Dict[str, Any]) -> str:
    import json
    return json.dumps(d)


if __name__ == "__main__":
    unittest.main()
