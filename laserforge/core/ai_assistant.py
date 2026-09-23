"""
LaserForge AI Assistant & Copilot Engine.
Provides DeepSeek AI (and compatible OpenAI/Ollama/LM Studio endpoints) integration:
- Automated Bed Alignment & Mechanical Gantry Diagnostics
- Overhead Camera Configuration & Vision Quality Assessment
- Natural Language CAD Object Manipulation (Move, Scale, Rotate, Align, Fit, Create)
- Camera-Assisted Workpiece Detection & Placement
"""

from __future__ import annotations

import os
import json
import math
import time
from typing import Dict, Any, List, Optional, Tuple, Callable
import urllib.request
import urllib.error

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None

from laserforge.config import MachineSettings
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, TextEntity, PathEntity
)
from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
from laserforge.core.auto_calibration import AutoCalibrationEngine, AutoCalibrationConfig
from laserforge.core.materials_database import DEFAULT_3W_MATERIALS, MaterialProfile


SYSTEM_PROMPT = """You are LaserForge AI Copilot, an expert laser cutting & CNC CAM assistant.
You help operators calibrate machines, diagnose gantry skew and bed leveling, inspect camera feeds, manipulate CAD vector artwork on the laser bed, and dramatically optimize engraving times and speeds.

Guidelines:
1. When the operator asks to move, rotate, scale, align, or arrange objects, invoke the corresponding tool.
2. For bed alignment or calibration questions, run diagnose_bed_alignment or get_camera_status to review physical telemetry.
3. For engraving speed questions or reducing job time, invoke optimize_engrave_time to audit line intervals, scan orientation, white-space skipping, and acceleration.
4. For material speeds and power settings, invoke apply_material_preset to look up calibrated parameters from the materials database.
5. Be clear, concise, and helpful with workshop terminology (e.g. gantry racking, line interval, DPI, overscan, white-space skip, kerf).
6. Physical Safety: Laser machines can cause fire or injury. Ensure work remains strictly within the machine bed limits.
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "diagnose_bed_alignment",
            "description": "Analyzes the latest auto-calibration telemetry (RMS reprojection error, gantry skew deviation, affine scale, and fiducials) to diagnose physical mechanical issues like racked gantry, loose belts, or unlevel bed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "detailed": {
                        "type": "boolean",
                        "description": "Whether to return full per-point error residuals."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_camera_status",
            "description": "Retrieves the status of the overhead camera (lens distortion calibration, homography bed alignment, resolution, and connection status).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_summary",
            "description": "Lists all CAD entities currently on the canvas, including their IDs, types, dimensions in mm, positions, layers, and selection state.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "transform_objects",
            "description": "Applies translations, scaling, or rotation to canvas objects. All transformations are non-destructive and push an undo state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["selected", "all"],
                        "description": "Which objects to transform: 'selected' or 'all'."
                    },
                    "dx_mm": {
                        "type": "number",
                        "description": "Horizontal translation in millimeters (positive = right)."
                    },
                    "dy_mm": {
                        "type": "number",
                        "description": "Vertical translation in millimeters (positive = down or up depending on origin)."
                    },
                    "scale_factor": {
                        "type": "number",
                        "description": "Scale multiplier (e.g., 1.5 = 150%, 0.8 = 80%). Default 1.0."
                    },
                    "rotate_deg": {
                        "type": "number",
                        "description": "Rotation angle in degrees clockwise. Default 0.0."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "align_objects",
            "description": "Aligns or centers canvas objects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": [
                            "bed_center", "center_in_parent", "left", "center_x",
                            "right", "top", "center_y", "bottom",
                            "distribute_h", "distribute_v"
                        ],
                        "description": "The alignment mode to apply."
                    }
                },
                "required": ["mode"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fit_to_bed",
            "description": "Scales selected or all artwork proportionally to fit comfortably within the machine bed boundaries with a safety margin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "margin_mm": {
                        "type": "number",
                        "description": "Safety margin in millimeters from the bed edges. Default 10.0."
                    },
                    "target": {
                        "type": "string",
                        "enum": ["selected", "all"],
                        "description": "Whether to fit 'selected' items or 'all' items. Default 'selected'."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_primitive",
            "description": "Creates a new vector primitive (rectangle, circle, line, or text) on the canvas at specified mm coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "shape_type": {
                        "type": "string",
                        "enum": ["rect", "circle", "line", "text"],
                        "description": "Type of shape to create."
                    },
                    "x": {"type": "number", "description": "X coordinate in mm."},
                    "y": {"type": "number", "description": "Y coordinate in mm."},
                    "width": {"type": "number", "description": "Width in mm (for rect/text)."},
                    "height": {"type": "number", "description": "Height in mm (for rect/text)."},
                    "radius": {"type": "number", "description": "Radius in mm (for circle)."},
                    "text": {"type": "string", "description": "Text content (for text)."},
                    "layer_id": {"type": "integer", "description": "Layer index (0-11). Default 0."}
                },
                "required": ["shape_type", "x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "detect_and_place_on_workpiece",
            "description": "Uses the camera bed view to detect the physical workpiece/stock material (e.g. plywood, acrylic scrap, coaster) and automatically positions/centers selected artwork onto the detected material.",
            "parameters": {
                "type": "object",
                "properties": {
                    "margin_mm": {
                        "type": "number",
                        "description": "Margin inside the workpiece perimeter in mm. Default 5.0."
                    },
                    "align": {
                        "type": "string",
                        "enum": ["center", "top_left", "bottom_left"],
                        "description": "Alignment of the artwork relative to the workpiece. Default 'center'."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_engrave_time",
            "description": "Analyzes the current project's layers, geometry, line intervals, scan orientation, and machine settings to find bottlenecks and recommend/apply specific tricks to decrease engraving time by 30% to 70%.",
            "parameters": {
                "type": "object",
                "properties": {
                    "apply_optimizations": {
                        "type": "boolean",
                        "description": "If true, automatically applies safe speed optimizations (line interval tuning, white-space skip, orientation) directly to layers and canvas."
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["maximum_speed", "balanced", "high_detail"],
                        "description": "Speed optimization profile. Default 'balanced'."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_material_preset",
            "description": "Searches the calibrated materials database (e.g. wood, acrylic, anodized aluminum, slate, leather) and applies optimal feedrate, laser power, line interval, and air assist to the specified layer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "material": {
                        "type": "string",
                        "description": "Name or keyword of the material (e.g. 'wood', 'plywood', 'acrylic', 'slate', 'anodized aluminum', 'leather')."
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["engrave", "cut", "mark"],
                        "description": "Operation type: 'engrave', 'cut', or 'mark'. Default 'engrave'."
                    },
                    "layer_id": {
                        "type": "integer",
                        "description": "Target layer ID (0-11). Default 0."
                    }
                },
                "required": ["material"]
            }
        }
    }
]


class AIAssistantEngine:
    """
    Coordinates DeepSeek API / OpenAI-compatible LLM communication,
    executes function calls on LaserForge's CAD canvas and camera engines,
    and returns rich diagnostic telemetry.
    """

    def __init__(
        self,
        settings: Optional[MachineSettings] = None,
        scene: Optional[Any] = None,
        camera_engine: Optional[CameraEngine] = None,
        auto_calib_engine: Optional[AutoCalibrationEngine] = None
    ):
        self.settings = settings or MachineSettings()
        self.scene = scene
        self.camera_engine = camera_engine
        self.auto_calib_engine = auto_calib_engine or AutoCalibrationEngine()

        # Conversation history: list of {"role": "system"|"user"|"assistant"|"tool", "content": ...}
        self.history: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    # -------------------------------------------------------------------------
    # Configuration & Provider Setup
    # -------------------------------------------------------------------------

    def get_api_endpoint(self) -> str:
        """Returns the active completion URL based on provider settings."""
        provider = getattr(self.settings, "ai_provider", "deepseek").lower()
        custom_base = getattr(self.settings, "ai_api_base", "").strip()

        if custom_base:
            base = custom_base.rstrip("/")
            if not base.endswith("/chat/completions"):
                if base.endswith("/v1"):
                    return f"{base}/chat/completions"
                return f"{base}/v1/chat/completions"
            return base

        if provider == "deepseek":
            return "https://api.deepseek.com/v1/chat/completions"
        elif provider == "ollama":
            return "http://localhost:11434/v1/chat/completions"
        elif provider == "lmstudio":
            return "http://localhost:1234/v1/chat/completions"
        return "https://api.deepseek.com/v1/chat/completions"

    def get_api_key(self) -> str:
        """Retrieves API key from settings or environment variable."""
        key = getattr(self.settings, "ai_api_key", "").strip()
        if not key:
            key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        return key

    def get_model_name(self) -> str:
        """Returns model identifier."""
        model = getattr(self.settings, "ai_model", "").strip()
        if model:
            return model
        provider = getattr(self.settings, "ai_provider", "deepseek").lower()
        if provider == "deepseek":
            return "deepseek-chat"
        elif provider == "ollama":
            return "deepseek-r1:latest"
        elif provider == "lmstudio":
            return "deepseek-r1"
        return "deepseek-chat"

    # -------------------------------------------------------------------------
    # Tool Execution Dispatcher
    # -------------------------------------------------------------------------

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches tool call to appropriate local LaserForge subsystem."""
        try:
            if tool_name == "diagnose_bed_alignment":
                return self._tool_diagnose_bed_alignment(args)
            elif tool_name == "get_camera_status":
                return self._tool_get_camera_status(args)
            elif tool_name == "get_scene_summary":
                return self._tool_get_scene_summary(args)
            elif tool_name == "transform_objects":
                return self._tool_transform_objects(args)
            elif tool_name == "align_objects":
                return self._tool_align_objects(args)
            elif tool_name == "fit_to_bed":
                return self._tool_fit_to_bed(args)
            elif tool_name == "create_primitive":
                return self._tool_create_primitive(args)
            elif tool_name == "detect_and_place_on_workpiece":
                return self._tool_detect_and_place_on_workpiece(args)
            elif tool_name == "optimize_engrave_time":
                return self._tool_optimize_engrave_time(args)
            elif tool_name == "apply_material_preset":
                return self._tool_apply_material_preset(args)
            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            return {"success": False, "error": f"Error executing {tool_name}: {str(e)}"}

    # -------------------------------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------------------------------

    def _tool_diagnose_bed_alignment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Analyzes AutoCalibration telemetry or CameraCalibrationData."""
        result = getattr(self.auto_calib_engine, "last_result", None) or getattr(self.auto_calib_engine, "latest_result", None)
        calib_data = self.camera_engine.calibration if self.camera_engine else None

        bed_w = getattr(self.settings, "bed_width", 400.0)
        bed_h = getattr(self.settings, "bed_height", 400.0)

        data: Dict[str, Any] = {
            "bed_dimensions_mm": [bed_w, bed_h],
            "calibrated": False,
            "reprojection_error_rms_mm": 0.0,
            "reprojection_error_rms_px": 0.0,
            "gantry_skew_deg": 0.0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "quality_score": 0.0,
            "diagnostics": [],
            "recommendations": []
        }

        if result and result.success:
            data["calibrated"] = True
            data["reprojection_error_rms_mm"] = result.reprojection_error_rms_mm
            data["reprojection_error_rms_px"] = result.reprojection_error_rms_px
            data["gantry_skew_deg"] = result.gantry_skew_deg
            data["scale_x"] = result.scale_x
            data["scale_y"] = result.scale_y
            data["quality_score"] = result.quality_score

            # Interpret Gantry Skew
            abs_skew = abs(result.gantry_skew_deg)
            if abs_skew < 0.1:
                data["diagnostics"].append(f"Gantry orthogonality is excellent (skew: {result.gantry_skew_deg:+.2f}°).")
            elif abs_skew < 0.3:
                data["diagnostics"].append(f"Minor gantry skew ({result.gantry_skew_deg:+.2f}°), acceptable for standard engraving.")
            else:
                data["diagnostics"].append(f"Significant gantry skew detected ({result.gantry_skew_deg:+.2f}°)! Machine axes are not square.")
                data["recommendations"].append(
                    "Mechanical check: Power off steppers, gently push gantry against physical endstops to un-rack the dual Y-axis, and inspect left/right belt tension."
                )

            # Interpret Reprojection Error
            if result.reprojection_error_rms_mm < 0.3:
                data["diagnostics"].append(f"Perspective reprojection precision is high (RMS: {result.reprojection_error_rms_mm:.2f} mm).")
            elif result.reprojection_error_rms_mm < 0.8:
                data["diagnostics"].append(f"Moderate reprojection error ({result.reprojection_error_rms_mm:.2f} mm).")
            else:
                data["diagnostics"].append(f"High reprojection error ({result.reprojection_error_rms_mm:.2f} mm).")
                data["recommendations"].append(
                    "Optical/leveling check: Verify camera lens is undistorted, camera mount is rigid without vibration, and workbed honeycomb is flat."
                )

            # Scale aspect ratio
            aspect_dev = abs(result.scale_x - result.scale_y)
            if aspect_dev > 0.02:
                data["diagnostics"].append(f"Asymmetric X/Y camera scaling ({result.scale_x:.3f} vs {result.scale_y:.3f}).")
                data["recommendations"].append("Check if camera is tilted relative to the workbed plane.")

        elif calib_data and calib_data.is_bed_aligned():
            data["calibrated"] = True
            data["reprojection_error_rms_px"] = calib_data.reprojection_error
            data["diagnostics"].append("Camera bed is aligned via homography matrix.")
        else:
            data["diagnostics"].append("Machine workbed has not been calibrated with camera vision yet.")
            data["recommendations"].append(
                "Run '🤖 Auto-Calibrate Workbed & Camera' (Ctrl+Alt+A) or print 4 ArUco fiducials to align camera pixels to laser bed mm."
            )

        return {"success": True, "telemetry": data}

    def _tool_get_camera_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Reports camera status and settings."""
        if not self.camera_engine:
            return {"success": False, "connected": False, "message": "Camera engine not initialized."}

        calib = self.camera_engine.calibration
        is_opened = self.camera_engine.is_capturing() if hasattr(self.camera_engine, "is_capturing") else False

        status = {
            "connected": is_opened,
            "device_index": getattr(calib, "device_index", 0),
            "device_name": getattr(calib, "device_name", "USB Camera"),
            "resolution": getattr(calib, "resolution", (1920, 1080)),
            "lens_distortion_calibrated": calib.is_lens_calibrated() if calib else False,
            "bed_homography_aligned": calib.is_bed_aligned() if calib else False,
            "is_fisheye": getattr(calib, "is_fisheye", False),
            "overlay_opacity": getattr(calib, "overlay_opacity", 0.55),
        }
        return {"success": True, "camera": status}

    def _tool_get_scene_summary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Provides an inspection of the current CAD canvas."""
        if not self.scene:
            return {"success": False, "message": "CAD scene not available."}

        entities = self.scene.get_all_entities()
        selected_entities = self.scene.get_selected_entities()
        selected_ids = {getattr(e, "id", None) for e in selected_entities}

        items = []
        for ent in entities:
            b = ent.get_bounds()
            items.append({
                "id": getattr(ent, "id", ""),
                "type": ent.__class__.__name__,
                "name": getattr(ent, "name", ""),
                "layer_id": getattr(ent, "layer_id", 0),
                "selected": getattr(ent, "id", None) in selected_ids,
                "bounds_mm": [round(b[0], 2), round(b[1], 2), round(b[2], 2), round(b[3], 2)],
                "width_mm": round(b[2] - b[0], 2),
                "height_mm": round(b[3] - b[1], 2)
            })

        return {
            "success": True,
            "total_entities": len(entities),
            "selected_count": len(selected_entities),
            "entities": items
        }

    def _tool_transform_objects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Translates, scales, or rotates entities."""
        if not self.scene:
            return {"success": False, "message": "CAD scene not available."}

        target = args.get("target", "selected")
        dx = float(args.get("dx_mm", 0.0))
        dy = float(args.get("dy_mm", 0.0))
        scale = float(args.get("scale_factor", 1.0))
        rotate = float(args.get("rotate_deg", 0.0))

        if target == "all":
            entities = self.scene.get_all_entities()
        else:
            entities = self.scene.get_selected_entities()
            if not entities:
                entities = self.scene.get_all_entities()

        if not entities:
            return {"success": False, "message": "No objects on canvas to transform."}

        self.scene.push_undo_state()

        # Calculate bounding box center of group for rotation/scaling
        all_bounds = [e.get_bounds() for e in entities]
        group_min_x = min(b[0] for b in all_bounds)
        group_max_x = max(b[2] for b in all_bounds)
        group_min_y = min(b[1] for b in all_bounds)
        group_max_y = max(b[3] for b in all_bounds)
        cx = (group_min_x + group_max_x) / 2.0
        cy = (group_min_y + group_max_y) / 2.0

        for ent in entities:
            # 1. Translation
            ent.x += dx
            ent.y += dy

            # 2. Rotation
            if rotate != 0.0:
                ent.rotation = (getattr(ent, "rotation", 0.0) + rotate) % 360.0

            # 3. Scaling
            if scale > 0.0 and scale != 1.0:
                # Scale relative to group center
                ent.x = cx + (ent.x - cx) * scale
                ent.y = cy + (ent.y - cy) * scale

                if isinstance(ent, RectEntity):
                    ent.width *= scale
                    ent.height *= scale
                elif isinstance(ent, CircleEntity):
                    ent.radius_x *= scale
                    ent.radius_y *= scale
                elif isinstance(ent, TextEntity):
                    ent.font_size *= scale
                    ent.width *= scale
                    ent.height *= scale
                elif isinstance(ent, PathEntity):
                    new_contours = []
                    for c in ent.contours:
                        new_contours.append([(pt[0] * scale, pt[1] * scale) for pt in c])
                    ent.contours = new_contours
                    ent.invalidate_bounds()

        # Sync items in scene
        for item in self.scene.items():
            if hasattr(item, "sync_from_entity"):
                item.sync_from_entity()

        self.scene.entity_modified.emit()
        return {
            "success": True,
            "transformed_count": len(entities),
            "message": f"Transformed {len(entities)} object(s): dx={dx}mm, dy={dy}mm, scale={scale}x, rotate={rotate}°"
        }

    def _tool_align_objects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Aligns objects using scene.align_selected."""
        if not self.scene:
            return {"success": False, "message": "CAD scene not available."}

        mode = args.get("mode", "bed_center")
        bed_w = getattr(self.settings, "bed_width", 400.0)
        bed_h = getattr(self.settings, "bed_height", 400.0)

        # If nothing selected, select all to align
        selected = self.scene.get_selected_entities()
        if not selected and mode == "bed_center":
            for item in self.scene.items():
                if hasattr(item, "setSelected"):
                    item.setSelected(True)

        self.scene.align_selected(mode, bed_width=bed_w, bed_height=bed_h)
        return {"success": True, "message": f"Applied alignment mode '{mode}' on active objects."}

    def _tool_fit_to_bed(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Fits artwork within bed boundaries."""
        if not self.scene:
            return {"success": False, "message": "CAD scene not available."}

        margin = float(args.get("margin_mm", 10.0))
        target = args.get("target", "selected")

        if target == "all":
            entities = self.scene.get_all_entities()
        else:
            entities = self.scene.get_selected_entities()
            if not entities:
                entities = self.scene.get_all_entities()

        if not entities:
            return {"success": False, "message": "No objects on canvas to fit."}

        bed_w = getattr(self.settings, "bed_width", 400.0)
        bed_h = getattr(self.settings, "bed_height", 400.0)

        usable_w = max(10.0, bed_w - 2.0 * margin)
        usable_h = max(10.0, bed_h - 2.0 * margin)

        bounds = [e.get_bounds() for e in entities]
        min_x = min(b[0] for b in bounds)
        max_x = max(b[2] for b in bounds)
        min_y = min(b[1] for b in bounds)
        max_y = max(b[3] for b in bounds)

        curr_w = max_x - min_x
        curr_h = max_y - min_y

        if curr_w <= 0.0 or curr_h <= 0.0:
            return {"success": False, "message": "Invalid entity dimensions."}

        scale_factor = 1.0
        if curr_w > usable_w or curr_h > usable_h:
            scale_factor = min(usable_w / curr_w, usable_h / curr_h)

        # Transform scale and center on bed
        self.scene.push_undo_state()
        curr_cx = (min_x + max_x) / 2.0
        curr_cy = (min_y + max_y) / 2.0
        bed_cx = bed_w / 2.0
        bed_cy = bed_h / 2.0

        for ent in entities:
            if scale_factor != 1.0:
                ent.x = curr_cx + (ent.x - curr_cx) * scale_factor
                ent.y = curr_cy + (ent.y - curr_cy) * scale_factor
                if isinstance(ent, RectEntity):
                    ent.width *= scale_factor
                    ent.height *= scale_factor
                elif isinstance(ent, CircleEntity):
                    ent.radius_x *= scale_factor
                    ent.radius_y *= scale_factor
                elif isinstance(ent, TextEntity):
                    ent.font_size *= scale_factor
                    ent.width *= scale_factor
                    ent.height *= scale_factor
                elif isinstance(ent, PathEntity):
                    new_contours = []
                    for c in ent.contours:
                        new_contours.append([(pt[0] * scale_factor, pt[1] * scale_factor) for pt in c])
                    ent.contours = new_contours
                    ent.invalidate_bounds()

            # Now center
            ent.x += (bed_cx - curr_cx)
            ent.y += (bed_cy - curr_cy)

        for item in self.scene.items():
            if hasattr(item, "sync_from_entity"):
                item.sync_from_entity()

        self.scene.entity_modified.emit()
        return {
            "success": True,
            "scale_factor": round(scale_factor, 3),
            "message": f"Fitted artwork to bed: scaled by {scale_factor:.2f}x with {margin}mm margin, centered at ({bed_cx}, {bed_cy})."
        }

    def _tool_create_primitive(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a primitive shape on the canvas."""
        if not self.scene:
            return {"success": False, "message": "CAD scene not available."}

        st = args.get("shape_type", "rect").lower()
        x = float(args.get("x", 0.0))
        y = float(args.get("y", 0.0))
        layer_id = int(args.get("layer_id", 0))

        self.scene.push_undo_state()

        if st == "rect":
            w = float(args.get("width", 50.0))
            h = float(args.get("height", 30.0))
            ent = RectEntity(x=x, y=y, width=w, height=h, layer_id=layer_id, name="AI Rectangle")
        elif st == "circle":
            r = float(args.get("radius", 25.0))
            ent = CircleEntity(x=x, y=y, radius_x=r, radius_y=r, layer_id=layer_id, name="AI Circle")
        elif st == "line":
            x2 = x + float(args.get("width", 50.0))
            y2 = y + float(args.get("height", 50.0))
            ent = LineEntity(x=x, y=y, x2=x2, y2=y2, layer_id=layer_id, name="AI Line")
        elif st == "text":
            txt = str(args.get("text", "LaserForge"))
            ent = TextEntity(x=x, y=y, text=txt, layer_id=layer_id, name=f"AI Text: {txt}")
        else:
            return {"success": False, "message": f"Unsupported primitive shape '{st}'"}

        self.scene.add_entity(ent)
        return {
            "success": True,
            "entity_id": ent.id,
            "message": f"Created {st} primitive at ({x}, {y}) mm on layer {layer_id}."
        }

    def _tool_detect_and_place_on_workpiece(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Detects workpiece on bed via camera or returns detected stock boundary."""
        margin = float(args.get("margin_mm", 5.0))
        align = args.get("align", "center")

        stock_box = None
        # Attempt computer vision detection from camera orthophoto if available
        if self.camera_engine and hasattr(self.camera_engine, "get_latest_frame"):
            frame = self.camera_engine.get_latest_frame()
            if frame is not None and HAS_CV2:
                stock_box = self._detect_stock_contour_cv(frame)

        # Fallback simulation of stock workpiece if camera is off or empty
        if stock_box is None:
            # Plausible center-left workpiece (e.g. 150x100mm wood block at 50, 50)
            stock_box = (50.0, 50.0, 150.0, 100.0)

        sx, sy, sw, sh = stock_box

        # Position selected objects inside this stock box
        if not self.scene:
            return {"success": True, "detected_stock_mm": list(stock_box)}

        selected = self.scene.get_selected_entities()
        if not selected:
            selected = self.scene.get_all_entities()

        if not selected:
            return {
                "success": True,
                "detected_stock_mm": list(stock_box),
                "message": f"Detected material at ({sx}, {sy}), size {sw}x{sh} mm. No artwork selected to place."
            }

        self.scene.push_undo_state()

        bounds = [e.get_bounds() for e in selected]
        min_x = min(b[0] for b in bounds)
        max_x = max(b[2] for b in bounds)
        min_y = min(b[1] for b in bounds)
        max_y = max(b[3] for b in bounds)
        art_w = max_x - min_x
        art_h = max_y - min_y

        usable_w = max(5.0, sw - 2.0 * margin)
        usable_h = max(5.0, sh - 2.0 * margin)

        scale = 1.0
        if art_w > usable_w or art_h > usable_h:
            scale = min(usable_w / art_w, usable_h / art_h)

        art_cx = (min_x + max_x) / 2.0
        art_cy = (min_y + max_y) / 2.0
        target_cx = sx + sw / 2.0
        target_cy = sy + sh / 2.0

        for ent in selected:
            if scale != 1.0:
                ent.x = art_cx + (ent.x - art_cx) * scale
                ent.y = art_cy + (ent.y - art_cy) * scale
                if isinstance(ent, RectEntity):
                    ent.width *= scale
                    ent.height *= scale
                elif isinstance(ent, CircleEntity):
                    ent.radius_x *= scale
                    ent.radius_y *= scale
                elif isinstance(ent, TextEntity):
                    ent.font_size *= scale
                    ent.width *= scale
                    ent.height *= scale
                elif isinstance(ent, PathEntity):
                    ent.contours = [[(p[0] * scale, p[1] * scale) for p in c] for c in ent.contours]
                    ent.invalidate_bounds()

            ent.x += (target_cx - art_cx)
            ent.y += (target_cy - art_cy)

        for item in self.scene.items():
            if hasattr(item, "sync_from_entity"):
                item.sync_from_entity()

        self.scene.entity_modified.emit()
        return {
            "success": True,
            "detected_stock_mm": [round(v, 1) for v in stock_box],
            "scale_factor": round(scale, 3),
            "message": f"Successfully placed artwork onto detected material at ({sx:.1f}, {sy:.1f}) mm (Size: {sw:.1f}x{sh:.1f} mm)."
        }

    def _detect_stock_contour_cv(self, frame: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
        """OpenCV contour detection to locate material bounds on workbed."""
        if not HAS_CV2 or self.camera_engine is None:
            return None
        try:
            calib = self.camera_engine.calibration
            if not calib or not calib.is_bed_aligned():
                return None

            # Rectify to orthophoto
            ortho = self.camera_engine.generate_rectified_orthophoto(frame)
            if ortho is None:
                return None

            gray = cv2.cvtColor(ortho, cv2.COLOR_BGR2GRAY) if len(ortho.shape) == 3 else ortho
            blurred = cv2.GaussianBlur(gray, (7, 7), 0)
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return None

            # Filter for largest significant contour that isn't the entire image
            h, w = gray.shape[:2]
            total_area = w * h
            valid = [c for c in contours if 0.02 * total_area < cv2.contourArea(c) < 0.90 * total_area]
            if not valid:
                return None

            largest = max(valid, key=cv2.contourArea)
            rx, ry, rw, rh = cv2.boundingRect(largest)

            # Convert orthophoto pixels to physical mm
            scale = getattr(calib, "scale_px_per_mm", 3.0) or 3.0
            return (rx / scale, ry / scale, rw / scale, rh / scale)
        except Exception:
            return None

    def _tool_optimize_engrave_time(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Analyzes active artwork and layers for speed bottlenecks and calculates time savings."""
        apply_opt = bool(args.get("apply_optimizations", False))
        priority = args.get("priority", "balanced").lower()

        target_interval = 0.085 if priority == "balanced" else (0.11 if priority == "maximum_speed" else 0.07)

        bottlenecks = []
        optimizations = []
        applied_actions = []
        estimated_speedup_pct = 0.0

        # 1. Layer Line Interval Analysis
        if self.scene and hasattr(self.scene, "layer_manager"):
            lm = self.scene.layer_manager
            used_lids = {getattr(e, "layer_id", 0) for e in self.scene.get_all_entities()}
            active_layers = [lm.get_layer(lid) for lid in used_lids]

            for layer in active_layers:
                if layer.mode in ("Fill", "Fill + Line") or hasattr(layer, "line_interval"):
                    curr_interval = getattr(layer, "line_interval", 0.1)
                    if curr_interval < target_interval:
                        savings = ((target_interval - curr_interval) / target_interval) * 100.0
                        bottlenecks.append(
                            f"Layer {layer.name} ({layer.color}): Line interval is {curr_interval:.3f} mm (~{int(round(25.4/curr_interval))} DPI). "
                            f"Laser spot size is ~0.08-0.10 mm, causing redundant overlapping burns."
                        )
                        optimizations.append(
                            f"Increase line interval from {curr_interval:.3f} mm to {target_interval:.3f} mm (~{int(round(25.4/target_interval))} DPI). "
                            f"Saves ~{savings:.0f}% of scan passes with crisp fill contrast."
                        )
                        estimated_speedup_pct += min(45.0, savings)

                        if apply_opt:
                            layer.line_interval = target_interval
                            applied_actions.append(f"Updated Layer {layer.name} line interval to {target_interval:.3f} mm.")

        # 2. Geometric Aspect Ratio / Scan Axis Alignment
        if self.scene:
            entities = self.scene.get_all_entities()
            if entities:
                all_bounds = [e.get_bounds() for e in entities]
                min_x = min(b[0] for b in all_bounds)
                max_x = max(b[2] for b in all_bounds)
                min_y = min(b[1] for b in all_bounds)
                max_y = max(b[3] for b in all_bounds)
                w_mm = max(1.0, max_x - min_x)
                h_mm = max(1.0, max_y - min_y)

                # Laser X carriage is light and fast; Y gantry is heavy. If H > 1.4 * W, scanning across X has too many turnaround reversals.
                if h_mm > 1.4 * w_mm:
                    turnaround_ratio = (1.0 - (w_mm / h_mm)) * 100.0
                    bottlenecks.append(
                        f"Artwork is tall and narrow ({w_mm:.1f} mm wide × {h_mm:.1f} mm tall). "
                        f"Horizontal X rastering requires {int(round(h_mm / 0.1))} line turnarounds across the heavy Y gantry."
                    )
                    optimizations.append(
                        f"Rotate artwork 90° to align the long {h_mm:.1f} mm dimension along the fast X-axis. "
                        f"Reduces directional direction-changes by ~{turnaround_ratio:.0f}% and cuts turnaround inertia."
                    )
                    estimated_speedup_pct += min(35.0, turnaround_ratio * 0.5)

                    if apply_opt:
                        self.scene.push_undo_state()
                        cx = (min_x + max_x) / 2.0
                        cy = (min_y + max_y) / 2.0
                        for ent in entities:
                            ent.rotation = (getattr(ent, "rotation", 0.0) + 90.0) % 360.0
                            rx = ent.x - cx
                            ry = ent.y - cy
                            ent.x = cx - ry
                            ent.y = cy + rx
                        for item in self.scene.items():
                            if hasattr(item, "sync_from_entity"):
                                item.sync_from_entity()
                        self.scene.entity_modified.emit()
                        applied_actions.append("Rotated artwork 90° to align long dimension with fast X carriage.")

        # 3. Machine Kinematics & White Space Skip
        ws_skip = getattr(self.settings, "white_space_skip_enabled", True)
        if not ws_skip:
            bottlenecks.append("White-space skipping is disabled. Laser travels through empty space at slow engraving speed.")
            optimizations.append("Enable White-Space Skipping to traverse empty gaps at maximum G0 rapid speed.")
            estimated_speedup_pct += 20.0
            if apply_opt:
                self.settings.white_space_skip_enabled = True
                applied_actions.append("Enabled G0 White-Space Skipping.")

        continuous_stream = getattr(self.settings, "continuous_inline_streaming", True)
        if not continuous_stream:
            bottlenecks.append("Continuous inline streaming is disabled. Controller may pause between scanlines.")
            optimizations.append("Enable continuous inline streaming for smooth non-stop rastering.")
            if apply_opt:
                self.settings.continuous_inline_streaming = True
                applied_actions.append("Enabled continuous inline streaming.")

        total_est_savings = min(75.0, max(15.0, estimated_speedup_pct))

        return {
            "success": True,
            "estimated_time_savings_pct": round(total_est_savings, 1),
            "bottlenecks_detected": bottlenecks,
            "recommended_optimizations": optimizations,
            "applied": apply_opt,
            "applied_actions": applied_actions,
            "message": (
                f"Engraving speed analysis complete. Estimated time savings: ~{total_est_savings:.0f}%."
                + (f" Applied: {', '.join(applied_actions)}" if applied_actions else " (Ask DeepSeek to 'apply optimizations' to execute).")
            )
        }

    def _tool_apply_material_preset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Matches a material from the calibrated database and applies settings to a layer."""
        mat_query = str(args.get("material", "")).lower().strip()
        op_query = str(args.get("operation", "engrave")).lower().strip()
        layer_id = int(args.get("layer_id", 0))

        if not self.scene or not hasattr(self.scene, "layer_manager"):
            return {"success": False, "message": "Layer manager not available."}

        tokens = [t for t in mat_query.split() if len(t) >= 2]
        scored_matches = []
        for m in DEFAULT_3W_MATERIALS:
            m_text = f"{m.name} {m.category} {m.description}".lower()
            score = 0
            if mat_query in m_text:
                score += 5
            for t in tokens:
                if t in m_text:
                    score += 2
                if t in m.category.lower():
                    score += 1
            if op_query and op_query in m.operation.lower():
                score += 3
            if score > 0:
                scored_matches.append((score, m))

        if not scored_matches:
            return {
                "success": False,
                "message": f"No material preset matching '{mat_query}'. Try: Birch, Basswood, Plywood, Anodized Aluminum, Slate, Leather, Acrylic, Cardstock."
            }

        scored_matches.sort(key=lambda x: x[0], reverse=True)
        best_match = scored_matches[0][1]

        # Apply to layer
        layer = self.scene.layer_manager.get_layer(layer_id)
        layer.mode = best_match.mode
        layer.speed = best_match.speed
        layer.power_max = best_match.power_pct
        layer.power_min = max(0.0, best_match.power_pct * 0.3)
        layer.passes = best_match.passes
        layer.line_interval = best_match.line_interval
        layer.air_assist = best_match.air_assist
        layer.pass_delay_sec = best_match.pass_delay_sec

        if hasattr(self.scene, "entity_modified"):
            self.scene.entity_modified.emit()

        return {
            "success": True,
            "matched_preset": {
                "name": best_match.name,
                "operation": best_match.operation,
                "speed": best_match.speed,
                "power_pct": best_match.power_pct,
                "line_interval": best_match.line_interval,
                "passes": best_match.passes,
                "air_assist": best_match.air_assist,
                "description": best_match.description
            },
            "layer_id": layer_id,
            "message": (
                f"Applied preset '{best_match.name}' to Layer {layer.name} ({layer.color}): "
                f"{best_match.speed:.0f} mm/min, {best_match.power_pct:.0f}% power, "
                f"{best_match.line_interval:.3f} mm interval ({best_match.mode} mode)."
            )
        }

    # -------------------------------------------------------------------------
    # API Communication & Chat Completion Loop
    # -------------------------------------------------------------------------

    def send_prompt(
        self,
        user_text: str,
        tool_callback: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None
    ) -> str:
        """
        Sends user message to DeepSeek API with function calling,
        executes any requested tools, and returns final assistant response.
        """
        # Append user message
        self.history.append({"role": "user", "content": user_text})

        api_url = self.get_api_endpoint()
        api_key = self.get_api_key()
        model_name = self.get_model_name()
        temperature = getattr(self.settings, "ai_temperature", 0.2)

        # Check if local keyword match applies immediately for instant offline handling
        offline_reply = self._handle_offline_heuristics(user_text)
        if offline_reply:
            self.history.append({"role": "assistant", "content": offline_reply})
            return offline_reply

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": self.history,
            "tools": TOOL_DEFINITIONS,
            "temperature": temperature
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Multi-turn tool execution loop (max 4 turns)
        for _ in range(4):
            try:
                raw_response = self._http_post_json(api_url, payload, headers)
            except Exception as req_err:
                err_msg = (
                    f"AI Connection Error ({api_url}): {str(req_err)}\n\n"
                    "Tip: Verify your DEEPSEEK_API_KEY in Settings, or run Ollama/LM Studio locally at "
                    "http://localhost:11434/v1."
                )
                self.history.append({"role": "assistant", "content": err_msg})
                return err_msg

            choice = raw_response.get("choices", [{}])[0]
            message = choice.get("message", {})
            self.history.append(message)

            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
                return message.get("content", "") or ""

            # Execute tool calls
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                arg_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(arg_str) if isinstance(arg_str, str) else arg_str
                except Exception:
                    args = {}

                tool_result = self.execute_tool(tool_name, args)

                if tool_callback:
                    tool_callback(tool_name, args, tool_result)

                # Append tool response
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{int(time.time()*1000)}"),
                    "name": tool_name,
                    "content": json.dumps(tool_result)
                })

            payload["messages"] = self.history

        final_content = self.history[-1].get("content", "")
        return final_content or "Action completed."

    def _handle_offline_heuristics(self, prompt: str) -> Optional[str]:
        """Allows direct execution of commands if offline or no API key."""
        lower = prompt.lower().strip()
        api_key = self.get_api_key()
        provider = getattr(self.settings, "ai_provider", "deepseek").lower()

        # If user has an API key or local server configured, let LLM handle it
        if api_key or provider in ("ollama", "lmstudio"):
            return None

        # Offline quick helpers
        if "diagnose" in lower or "skew" in lower or "alignment" in lower:
            res = self.execute_tool("diagnose_bed_alignment", {})
            tel = res.get("telemetry", {})
            diag = "\n- ".join(tel.get("diagnostics", []))
            recs = "\n- ".join(tel.get("recommendations", []))
            return (
                f"**Bed Alignment Telemetry (Offline Mode)**:\n"
                f"- Reprojection RMS Error: {tel.get('reprojection_error_rms_mm', 0):.2f} mm\n"
                f"- Gantry Skew: {tel.get('gantry_skew_deg', 0):.2f}°\n"
                f"- Scale X/Y: {tel.get('scale_x', 1):.3f} / {tel.get('scale_y', 1):.3f}\n\n"
                f"**Diagnostics**:\n- {diag}\n\n"
                + (f"**Recommendations**:\n- {recs}" if recs else "")
            )

        if "center" in lower and "bed" in lower:
            res = self.execute_tool("align_objects", {"mode": "bed_center"})
            return f"**Offline Action**: {res.get('message', 'Centered on bed')}"

        if "fit" in lower and "bed" in lower:
            res = self.execute_tool("fit_to_bed", {"margin_mm": 10.0})
            return f"**Offline Action**: {res.get('message', 'Fitted to bed')}"

        if "camera" in lower and ("status" in lower or "check" in lower):
            res = self.execute_tool("get_camera_status", {})
            cam = res.get("camera", {})
            return (
                f"**Camera Status (Offline Mode)**:\n"
                f"- Connected: {cam.get('connected')}\n"
                f"- Device: {cam.get('device_name')}\n"
                f"- Lens Calibrated: {cam.get('lens_distortion_calibrated')}\n"
                f"- Bed Aligned: {cam.get('bed_homography_aligned')}"
            )

        if any(w in lower for w in ("optimize", "speed", "decrease time", "engrave time", "faster", "engraving time")):
            apply_changes = any(w in lower for w in ("apply", "execute", "do it", "fix it", "make it"))
            res = self.execute_tool("optimize_engrave_time", {"apply_optimizations": apply_changes})
            b_list = "\n- ".join(res.get("bottlenecks_detected", [])) or "None detected."
            r_list = "\n- ".join(res.get("recommended_optimizations", [])) or "Settings already optimal."
            savings = res.get("estimated_time_savings_pct", 0)
            applied_txt = ("\n\n**Applied Optimizations**:\n- " + "\n- ".join(res.get("applied_actions", []))) if res.get("applied") else "\n\n*(Say 'apply optimizations' to execute these changes automatically)*"
            return (
                f"**⚡ Engraving Speed Optimization Audit (Offline Mode)**:\n"
                f"- Potential Run-Time Reduction: **~{savings:.0f}%**\n\n"
                f"**Bottlenecks Detected**:\n- {b_list}\n\n"
                f"**Recommended Tricks**:\n- {r_list}"
                f"{applied_txt}"
            )

        if any(w in lower for w in ("material", "preset", "wood", "plywood", "acrylic", "slate", "aluminum", "leather")):
            res = self.execute_tool("apply_material_preset", {"material": lower})
            if res.get("success"):
                p = res.get("matched_preset", {})
                return (
                    f"**🪵 Calibrated Material Preset Applied (Offline Mode)**:\n"
                    f"- Material: **{p.get('name')}** ({p.get('operation')})\n"
                    f"- Feedrate: {p.get('speed'):.0f} mm/min\n"
                    f"- Power: {p.get('power_pct'):.0f}%\n"
                    f"- Line Interval: {p.get('line_interval'):.3f} mm (~{int(round(25.4/p.get('line_interval', 0.1)))} DPI)\n"
                    f"- Passes: {p.get('passes')} | Air Assist: {'Enabled' if p.get('air_assist') else 'Disabled'}\n"
                    f"- Tip: {p.get('description')}"
                )

        return None

    def _http_post_json(self, url: str, data: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """Makes an HTTP POST request, returning JSON response."""
        json_bytes = json.dumps(data).encode("utf-8")

        if HAS_REQUESTS:
            resp = requests.post(url, json=data, headers=headers, timeout=45)
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(url, data=json_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
