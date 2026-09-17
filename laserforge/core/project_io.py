"""
LaserForge Project I/O and SVG Import/Export Engine.
Saves and loads native .laserproj files and parses vector SVG files into native CAD shapes.
"""

import json
import xml.etree.ElementTree as ET
import re
import math
from typing import List, Dict, Any, Tuple, Optional, Union

from laserforge.config import MachineSettings
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity, LayerCutSettings
)
from laserforge.core.layer_manager import LayerManager

class ProjectIO:

    @staticmethod
    def save_project(
        filepath: str,
        entities: List[LaserEntity],
        layer_manager: LayerManager,
        machine_settings: Any = None
    ):
        """Serializes workspace state to JSON format."""
        entities_data = []
        for e in entities:
            e_dict = {
                "type": e.__class__.__name__,
                "id": e.id,
                "layer_id": e.layer_id,
                "name": e.name,
                "x": e.x,
                "y": e.y,
                "rotation": e.rotation,
                "locked": e.locked
            }
            if getattr(e, "override_speed", None) is not None:
                e_dict["override_speed"] = float(e.override_speed)
            if getattr(e, "override_power", None) is not None:
                e_dict["override_power"] = float(e.override_power)
            if isinstance(e, RectEntity):
                e_dict.update({"width": e.width, "height": e.height, "corner_radius": e.corner_radius})
            elif isinstance(e, CircleEntity):
                e_dict.update({"radius_x": e.radius_x, "radius_y": e.radius_y})
            elif isinstance(e, LineEntity):
                e_dict.update({"x2": e.x2, "y2": e.y2})
            elif isinstance(e, PathEntity):
                e_dict.update({"contours": e.contours, "closed": e.closed})
            elif isinstance(e, TextEntity):
                e_dict.update({
                    "text": e.text, "font_family": e.font_family, "font_size": e.font_size,
                    "bold": e.bold, "italic": e.italic, "underline": getattr(e, "underline", False),
                    "fill_mode": getattr(e, "fill_mode", "Fill"),
                    "width": e.width, "height": e.height,
                    "is_mirrored_h": getattr(e, "is_mirrored_h", False),
                    "is_mirrored_v": getattr(e, "is_mirrored_v", False)
                })
            elif isinstance(e, ImageEntity):
                e_dict.update({
                    "image_path": e.image_path,
                    "raw_image_path": getattr(e, "raw_image_path", ""),
                    "processed_image_path": getattr(e, "processed_image_path", ""),
                    "width": e.width, "height": e.height,
                    "dither_mode": e.dither_mode, "invert": e.invert,
                    "contrast": e.contrast, "brightness": e.brightness,
                    "threshold_value": e.threshold_value,
                    "dpi": getattr(e, "dpi", 254.0),
                    "gamma": getattr(e, "gamma", 1.0),
                    "sharpen": getattr(e, "sharpen", 0.0),
                    "equalize": getattr(e, "equalize", False),
                    "white_clip": getattr(e, "white_clip", 255),
                    "black_clip": getattr(e, "black_clip", 0),
                    "halftone_cell_size": getattr(e, "halftone_cell_size", 6.0),
                    "halftone_angle_deg": getattr(e, "halftone_angle_deg", 45.0),
                    "is_mirrored_h": getattr(e, "is_mirrored_h", False),
                    "is_mirrored_v": getattr(e, "is_mirrored_v", False)
                })
            entities_data.append(e_dict)

        layers_data = [l.to_dict() for l in layer_manager.get_all_layers()]

        m_cfg = {}
        if isinstance(machine_settings, dict):
            m_cfg = machine_settings
        elif machine_settings is not None:
            m_cfg = {
                "bed_width": getattr(machine_settings, "bed_width", 400.0),
                "bed_height": getattr(machine_settings, "bed_height", 400.0),
                "origin_corner": getattr(machine_settings, "origin_corner", "Bottom-Left"),
                "software_mirror_x": getattr(machine_settings, "software_mirror_x", False),
                "software_mirror_y": getattr(machine_settings, "software_mirror_y", False),
                "max_s_value": getattr(machine_settings, "max_s_value", 1000),
                "min_s_value": getattr(machine_settings, "min_s_value", 0),
                "laser_mode": getattr(machine_settings, "laser_mode", "M4"),
                "use_inline_power": getattr(machine_settings, "use_inline_power", True),
                "rapid_speed": getattr(machine_settings, "rapid_speed", 3000.0),
                "jog_speed": getattr(machine_settings, "jog_speed", 2000.0),
                "framing_power_pct": getattr(machine_settings, "framing_power_pct", 0.5),
                "framing_speed": getattr(machine_settings, "framing_speed", 2000.0),
                "laser_fire_delay_ms": getattr(machine_settings, "laser_fire_delay_ms", 0.0),
                "laser_off_delay_ms": getattr(machine_settings, "laser_off_delay_ms", 0.0),
                "overscan_enabled": getattr(machine_settings, "overscan_enabled", False),
                "overscan_pct": getattr(machine_settings, "overscan_pct", 2.5),
                "overscan_mode": getattr(machine_settings, "overscan_mode", "Percentage"),
                "overscan_mm": getattr(machine_settings, "overscan_mm", 2.0),
                "kerf_width_mm": getattr(machine_settings, "kerf_width_mm", 0.08),
                "finish_position_mode": getattr(machine_settings, "finish_position_mode", "Origin"),
                "park_x": getattr(machine_settings, "park_x", 0.0),
                "park_y": getattr(machine_settings, "park_y", 0.0),
                "custom_start_gcode": getattr(machine_settings, "custom_start_gcode", ""),
                "custom_end_gcode": getattr(machine_settings, "custom_end_gcode", ""),
                "air_assist_cmd": getattr(machine_settings, "air_assist_cmd", "M8"),
                "air_assist_off_cmd": getattr(machine_settings, "air_assist_off_cmd", "M9"),
                "enable_air_assist_by_default": getattr(machine_settings, "enable_air_assist_by_default", False),
                "air_assist_pre_delay_sec": getattr(machine_settings, "air_assist_pre_delay_sec", 0.0),
                "air_assist_post_delay_sec": getattr(machine_settings, "air_assist_post_delay_sec", 0.0),
            }

        data = {
            "version": "1.0",
            "machine": m_cfg,
            "layers": layers_data,
            "entities": entities_data
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load_project(
        filepath: str,
        layer_manager: LayerManager,
        machine_settings: Optional[Any] = None
    ) -> Tuple[List[LaserEntity], LayerManager, dict]:
        """Loads workspace state from JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Restore machine settings
        m = data.get("machine", {})
        if machine_settings is not None:
            for k, v in m.items():
                if hasattr(machine_settings, k):
                    setattr(machine_settings, k, v)

        # Restore layers
        for l_data in data.get("layers", []):
            layer_manager.set_layer(l_data["layer_id"], LayerCutSettings.from_dict(l_data))


        # Restore entities
        entities = []
        for d in data.get("entities", []):
            etype = d.get("type")
            base_kwargs = {
                "id": d.get("id"),
                "layer_id": d.get("layer_id", 0),
                "name": d.get("name", "Shape"),
                "x": float(d.get("x", 0)),
                "y": float(d.get("y", 0)),
                "rotation": float(d.get("rotation", 0)),
                "locked": bool(d.get("locked", False)),
                "override_speed": float(d["override_speed"]) if d.get("override_speed") is not None else None,
                "override_power": float(d["override_power"]) if d.get("override_power") is not None else None
            }

            if etype == "RectEntity":
                entities.append(RectEntity(**base_kwargs, width=float(d["width"]), height=float(d["height"]), corner_radius=float(d.get("corner_radius", 0))))
            elif etype == "CircleEntity":
                entities.append(CircleEntity(**base_kwargs, radius_x=float(d["radius_x"]), radius_y=float(d["radius_y"])))
            elif etype == "LineEntity":
                entities.append(LineEntity(**base_kwargs, x2=float(d["x2"]), y2=float(d["y2"])))
            elif etype == "PathEntity":
                contours = [[(float(pt[0]), float(pt[1])) for pt in c] for c in d.get("contours", [])]
                entities.append(PathEntity(**base_kwargs, contours=contours, closed=d.get("closed", True)))
            elif etype == "TextEntity":
                entities.append(TextEntity(
                    **base_kwargs, text=d.get("text", ""), font_family=d.get("font_family", "Sans Serif"),
                    font_size=float(d.get("font_size", 20)), bold=bool(d.get("bold", False)),
                    italic=bool(d.get("italic", False)), underline=bool(d.get("underline", False)),
                    fill_mode=d.get("fill_mode", "Fill"),
                    width=float(d.get("width", 60)), height=float(d.get("height", 20)),
                    is_mirrored_h=bool(d.get("is_mirrored_h", False)),
                    is_mirrored_v=bool(d.get("is_mirrored_v", False))
                ))
            elif etype == "ImageEntity":
                entities.append(ImageEntity(
                    **base_kwargs, image_path=d.get("image_path", ""),
                    raw_image_path=d.get("raw_image_path", ""),
                    processed_image_path=d.get("processed_image_path", ""),
                    width=float(d.get("width", 80)),
                    height=float(d.get("height", 80)), dither_mode=d.get("dither_mode", "Floyd-Steinberg"),
                    invert=bool(d.get("invert", False)), contrast=float(d.get("contrast", 1.0)),
                    brightness=float(d.get("brightness", 0.0)), threshold_value=int(d.get("threshold_value", 128)),
                    dpi=float(d.get("dpi", 254.0)),
                    gamma=float(d.get("gamma", 1.0)),
                    sharpen=float(d.get("sharpen", 0.0)),
                    equalize=bool(d.get("equalize", False)),
                    white_clip=int(d.get("white_clip", 255)),
                    black_clip=int(d.get("black_clip", 0)),
                    halftone_cell_size=float(d.get("halftone_cell_size", 6.0)),
                    halftone_angle_deg=float(d.get("halftone_angle_deg", 45.0)),
                    is_mirrored_h=bool(d.get("is_mirrored_h", False)),
                    is_mirrored_v=bool(d.get("is_mirrored_v", False))
                ))

        return entities, layer_manager, m


    @staticmethod
    def import_svg(filepath: str, default_layer_id: int = 0) -> List[LaserEntity]:
        """Parses an SVG file and converts primitives/paths into LaserForge entities."""
        from laserforge.core.svg_importer import SVGImporter
        return SVGImporter.import_svg_file(filepath, default_layer_id=default_layer_id)

    @staticmethod
    def _parse_svg_path_d(d: str) -> List[List[Tuple[float, float]]]:
        """Tokenizer & linearizer for SVG path commands (delegates to SVGImporter)."""
        from laserforge.core.svg_importer import SVGImporter
        return SVGImporter.parse_path_d(d)
