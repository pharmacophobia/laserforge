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
                    "bold": e.bold, "italic": e.italic, "width": e.width, "height": e.height
                })
            elif isinstance(e, ImageEntity):
                e_dict.update({
                    "image_path": e.image_path, "width": e.width, "height": e.height,
                    "dither_mode": e.dither_mode, "invert": e.invert,
                    "contrast": e.contrast, "brightness": e.brightness,
                    "threshold_value": e.threshold_value
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
                "max_s_value": getattr(machine_settings, "max_s_value", 1000),
                "laser_mode": getattr(machine_settings, "laser_mode", "M4"),
                "rapid_speed": getattr(machine_settings, "rapid_speed", 3000.0)
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
            if hasattr(machine_settings, "bed_width") and "bed_width" in m:
                machine_settings.bed_width = float(m["bed_width"])
            if hasattr(machine_settings, "bed_height") and "bed_height" in m:
                machine_settings.bed_height = float(m["bed_height"])
            if hasattr(machine_settings, "origin_corner") and "origin_corner" in m:
                machine_settings.origin_corner = m["origin_corner"]
            if hasattr(machine_settings, "max_s_value") and "max_s_value" in m:
                machine_settings.max_s_value = int(m["max_s_value"])
            if hasattr(machine_settings, "laser_mode") and "laser_mode" in m:
                machine_settings.laser_mode = m["laser_mode"]

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
                "locked": bool(d.get("locked", False))
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
                    italic=bool(d.get("italic", False)), width=float(d.get("width", 60)), height=float(d.get("height", 20))
                ))
            elif etype == "ImageEntity":
                entities.append(ImageEntity(
                    **base_kwargs, image_path=d.get("image_path", ""), width=float(d.get("width", 80)),
                    height=float(d.get("height", 80)), dither_mode=d.get("dither_mode", "Floyd-Steinberg"),
                    invert=bool(d.get("invert", False)), contrast=float(d.get("contrast", 1.0)),
                    brightness=float(d.get("brightness", 0.0)), threshold_value=int(d.get("threshold_value", 128))
                ))

        return entities, layer_manager, m


    @staticmethod
    def import_svg(filepath: str, default_layer_id: int = 0) -> List[LaserEntity]:
        """Parses an SVG file and converts primitives/paths into LaserForge entities."""
        entities = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            # Strip namespaces
            for elem in root.iter():
                if "}" in elem.tag:
                    elem.tag = elem.tag.split("}", 1)[1]

            for elem in root.iter():
                tag = elem.tag.lower()
                if tag == "rect":
                    x = float(elem.get("x", 0))
                    y = float(elem.get("y", 0))
                    w = float(elem.get("width", 0))
                    h = float(elem.get("height", 0))
                    if w > 0 and h > 0:
                        entities.append(RectEntity(layer_id=default_layer_id, name="SVG Rect", x=x, y=y, width=w, height=h))

                elif tag == "circle":
                    cx = float(elem.get("cx", 0))
                    cy = float(elem.get("cy", 0))
                    r = float(elem.get("r", 0))
                    if r > 0:
                        entities.append(CircleEntity(layer_id=default_layer_id, name="SVG Circle", x=cx, y=cy, radius_x=r, radius_y=r))

                elif tag == "ellipse":
                    cx = float(elem.get("cx", 0))
                    cy = float(elem.get("cy", 0))
                    rx = float(elem.get("rx", 0))
                    ry = float(elem.get("ry", 0))
                    if rx > 0 and ry > 0:
                        entities.append(CircleEntity(layer_id=default_layer_id, name="SVG Ellipse", x=cx, y=cy, radius_x=rx, radius_y=ry))

                elif tag == "line":
                    x1 = float(elem.get("x1", 0))
                    y1 = float(elem.get("y1", 0))
                    x2 = float(elem.get("x2", 0))
                    y2 = float(elem.get("y2", 0))
                    entities.append(LineEntity(layer_id=default_layer_id, name="SVG Line", x=x1, y=y1, x2=x2, y2=y2))

                elif tag in ("polyline", "polygon"):
                    points_str = elem.get("points", "")
                    raw_coords = [float(c) for c in re.findall(r"[-+]?[0-9]*\.?[0-9]+", points_str)]
                    pts = [(raw_coords[i], raw_coords[i+1]) for i in range(0, len(raw_coords) - 1, 2)]
                    if pts:
                        closed = (tag == "polygon")
                        if closed and pts[0] != pts[-1]:
                            pts.append(pts[0])
                        min_x = min(p[0] for p in pts)
                        min_y = min(p[1] for p in pts)
                        norm_pts = [(p[0] - min_x, p[1] - min_y) for p in pts]
                        entities.append(PathEntity(layer_id=default_layer_id, name=f"SVG {tag.capitalize()}", x=min_x, y=min_y, contours=[norm_pts], closed=closed))

                elif tag == "path":
                    d_attr = elem.get("d", "")
                    contours = ProjectIO._parse_svg_path_d(d_attr)
                    if contours:
                        all_pts = [p for c in contours for p in c]
                        if all_pts:
                            min_x = min(p[0] for p in all_pts)
                            min_y = min(p[1] for p in all_pts)
                            norm_contours = [[(p[0] - min_x, p[1] - min_y) for p in c] for c in contours]
                            entities.append(PathEntity(layer_id=default_layer_id, name="SVG Path", x=min_x, y=min_y, contours=norm_contours, closed=True))

        except Exception as e:
            print(f"SVG Import error: {e}")

        return entities

    @staticmethod
    def _parse_svg_path_d(d: str) -> List[List[Tuple[float, float]]]:
        """Simple tokenizer & linearizer for common SVG path commands (M, L, H, V, C, Z)."""
        tokens = re.findall(r"([a-df-zA-DF-Z]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)", d)
        contours = []
        cur_contour = []
        cur_x, cur_y = 0.0, 0.0
        start_x, start_y = 0.0, 0.0

        i = 0
        cur_cmd = "M"

        while i < len(tokens):
            tok = tokens[i]
            if tok.isalpha():
                cur_cmd = tok
                i += 1
            else:
                cmd = cur_cmd
                if cmd in ("M", "m"):
                    px = float(tokens[i])
                    py = float(tokens[i+1])
                    i += 2
                    if cmd == "m":
                        cur_x += px
                        cur_y += py
                    else:
                        cur_x, cur_y = px, py
                    if cur_contour:
                        contours.append(cur_contour)
                        cur_contour = []
                    start_x, start_y = cur_x, cur_y
                    cur_contour.append((cur_x, cur_y))
                    cur_cmd = "l" if cmd == "m" else "L"

                elif cmd in ("L", "l"):
                    px = float(tokens[i])
                    py = float(tokens[i+1])
                    i += 2
                    if cmd == "l":
                        cur_x += px
                        cur_y += py
                    else:
                        cur_x, cur_y = px, py
                    cur_contour.append((cur_x, cur_y))

                elif cmd in ("H", "h"):
                    px = float(tokens[i])
                    i += 1
                    cur_x = cur_x + px if cmd == "h" else px
                    cur_contour.append((cur_x, cur_y))

                elif cmd in ("V", "v"):
                    py = float(tokens[i])
                    i += 1
                    cur_y = cur_y + py if cmd == "v" else py
                    cur_contour.append((cur_x, cur_y))

                elif cmd in ("C", "c"):
                    if i + 5 < len(tokens):
                        x1 = float(tokens[i]); y1 = float(tokens[i+1])
                        x2 = float(tokens[i+2]); y2 = float(tokens[i+3])
                        x3 = float(tokens[i+4]); y3 = float(tokens[i+5])
                        i += 6
                        if cmd == "c":
                            x1 += cur_x; y1 += cur_y
                            x2 += cur_x; y2 += cur_y
                            x3 += cur_x; y3 += cur_y

                        # Linearize cubic bezier into 8 steps
                        for step in range(1, 9):
                            t = step / 8.0
                            bx = ((1-t)**3 * cur_x) + (3*(1-t)**2 * t * x1) + (3*(1-t)*t**2 * x2) + (t**3 * x3)
                            by = ((1-t)**3 * cur_y) + (3*(1-t)**2 * t * y1) + (3*(1-t)*t**2 * y2) + (t**3 * y3)
                            cur_contour.append((bx, by))
                        cur_x, cur_y = x3, y3
                    else:
                        break

                elif cmd in ("Z", "z"):
                    cur_x, cur_y = start_x, start_y
                    cur_contour.append((cur_x, cur_y))
                    contours.append(cur_contour)
                    cur_contour = []
                    i += 1
                else:
                    i += 1

        if cur_contour:
            contours.append(cur_contour)

        return contours
