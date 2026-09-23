"""
LaserForge LightBurn Project Importer (.lbrn & .lbrn2).
Parses native LightBurn project files (JSON-based .lbrn2 and XML-based .lbrn)
and imports vector geometries, texts, images, layer cut parameters, and speed/power presets.
"""

from typing import List, Tuple, Dict, Any, Optional
import os
import json
import math
import xml.etree.ElementTree as ET

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity,
    LayerCutSettings
)
from laserforge.core.layer_manager import LayerManager


class LightBurnImporter:
    """Importer for LightBurn .lbrn2 (JSON) and .lbrn (XML) project files."""

    @classmethod
    def import_file(
        cls,
        path: str,
        layer_manager: Optional[LayerManager] = None
    ) -> Tuple[List[LaserEntity], Dict[int, LayerCutSettings]]:
        """
        Imports a LightBurn project file.
        Returns (entities, layer_settings_map).
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        # Check format
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_chars = f.read(512).strip()

        if first_chars.startswith("{"):
            return cls._parse_lbrn2_json(path, layer_manager)
        elif first_chars.startswith("<"):
            return cls._parse_lbrn_xml(path, layer_manager)
        else:
            # Fallback attempt JSON then XML
            try:
                return cls._parse_lbrn2_json(path, layer_manager)
            except Exception:
                return cls._parse_lbrn_xml(path, layer_manager)

    @classmethod
    def _parse_lbrn2_json(
        cls,
        path: str,
        layer_manager: Optional[LayerManager] = None
    ) -> Tuple[List[LaserEntity], Dict[int, LayerCutSettings]]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        layer_settings_map: Dict[int, LayerCutSettings] = {}
        entities: List[LaserEntity] = []

        # 1. Parse CutSettings
        cut_settings = data.get("CutSettings", data.get("cutSettings", []))
        for cs in cut_settings:
            idx = cs.get("Index", cs.get("index", 0))
            color = cs.get("Color", cs.get("color", f"#{idx:02x}{idx:02x}{idx:02x}"))
            speed = float(cs.get("Speed", cs.get("speed", 1000.0)))
            power_max = float(cs.get("Power", cs.get("maxPower", cs.get("power", 80.0))))
            power_min = float(cs.get("MinPower", cs.get("minPower", 20.0)))
            passes = int(cs.get("NumPasses", cs.get("numPasses", cs.get("passes", 1))))
            air = bool(cs.get("AirAssist", cs.get("airAssist", False)))

            # Mode mapping
            raw_mode = str(cs.get("CutMode", cs.get("type", "Cut"))).lower()
            if "fill" in raw_mode and "line" in raw_mode:
                mode = "Fill + Line"
            elif "fill" in raw_mode or "scan" in raw_mode:
                mode = "Fill"
            elif "image" in raw_mode or "photo" in raw_mode:
                mode = "Image"
            else:
                mode = "Line"

            layer_setting = LayerCutSettings(
                layer_id=idx,
                name=f"C{idx:02d}",
                color=color,
                mode=mode,
                speed=speed,
                power_max=power_max,
                power_min=power_min,
                passes=passes,
                air_assist=air
            )
            layer_settings_map[idx] = layer_setting
            if layer_manager:
                layer_manager.set_layer(idx, layer_setting)

        # 2. Parse Shapes
        shapes = data.get("Shapes", data.get("shapes", []))
        cls._parse_shapes_recursive(shapes, entities, layer_settings_map)

        return entities, layer_settings_map

    @classmethod
    def _parse_shapes_recursive(
        cls,
        shapes_list: List[Dict[str, Any]],
        out_entities: List[LaserEntity],
        layer_settings_map: Dict[int, LayerCutSettings]
    ):
        for s in shapes_list:
            stype = str(s.get("Type", s.get("type", ""))).lower()
            lid = int(s.get("Layer", s.get("layer", 0)))
            name = s.get("Name", s.get("name", f"Shape_{len(out_entities) + 1}"))

            if stype in ("group", "itemgroup"):
                children = s.get("Children", s.get("children", []))
                cls._parse_shapes_recursive(children, out_entities, layer_settings_map)

            elif stype in ("rect", "rectangle"):
                x = float(s.get("X", s.get("x", 0.0)))
                y = float(s.get("Y", s.get("y", 0.0)))
                w = float(s.get("Width", s.get("W", s.get("width", 10.0))))
                h = float(s.get("Height", s.get("H", s.get("height", 10.0))))
                radius = float(s.get("Radius", s.get("radius", s.get("CornerRadius", 0.0))))
                rot = float(s.get("Rotation", s.get("rot", 0.0)))
                out_entities.append(RectEntity(
                    layer_id=lid, name=name, x=x, y=y, width=w, height=h,
                    corner_radius=radius, rotation=rot
                ))

            elif stype in ("ellipse", "circle"):
                x = float(s.get("X", s.get("x", 0.0)))
                y = float(s.get("Y", s.get("y", 0.0)))
                rx = float(s.get("Rx", s.get("rx", s.get("RadiusX", s.get("Radius", 10.0)))))
                ry = float(s.get("Ry", s.get("ry", s.get("RadiusY", rx))))
                rot = float(s.get("Rotation", s.get("rot", 0.0)))
                out_entities.append(CircleEntity(
                    layer_id=lid, name=name, x=x, y=y, radius_x=rx, radius_y=ry, rotation=rot
                ))

            elif stype in ("line",):
                x1 = float(s.get("X1", s.get("x1", 0.0)))
                y1 = float(s.get("Y1", s.get("y1", 0.0)))
                x2 = float(s.get("X2", s.get("x2", 10.0)))
                y2 = float(s.get("Y2", s.get("y2", 10.0)))
                out_entities.append(LineEntity(
                    layer_id=lid, name=name, x=x1, y=y1, x2=x2, y2=y2
                ))

            elif stype in ("text",):
                text_content = str(s.get("Text", s.get("text", "")))
                x = float(s.get("X", s.get("x", 0.0)))
                y = float(s.get("Y", s.get("y", 0.0)))
                font_family = str(s.get("Font", s.get("font", "Arial")))
                font_size = float(s.get("Size", s.get("size", s.get("Height", 10.0))))
                bold = bool(s.get("Bold", False))
                italic = bool(s.get("Italic", False))
                out_entities.append(TextEntity(
                    layer_id=lid, name=name, x=x, y=y, text=text_content,
                    font_family=font_family, font_size=font_size, bold=bold, italic=italic
                ))

            elif stype in ("path", "polygon", "polyline"):
                raw_verts = s.get("Verts", s.get("verts", s.get("Points", s.get("points", []))))
                pts = []
                for pt in raw_verts:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        pts.append((float(pt[0]), float(pt[1])))
                    elif isinstance(pt, dict) and "x" in pt and "y" in pt:
                        pts.append((float(pt["x"]), float(pt["y"])))
                if pts:
                    closed = bool(s.get("Closed", s.get("closed", True)))
                    out_entities.append(PathEntity(
                        layer_id=lid, name=name, x=0.0, y=0.0,
                        contours=[pts], closed=closed
                    ))

    @classmethod
    def _parse_lbrn_xml(
        cls,
        path: str,
        layer_manager: Optional[LayerManager] = None
    ) -> Tuple[List[LaserEntity], Dict[int, LayerCutSettings]]:
        import re
        tree = ET.parse(path)
        root = tree.getroot()

        layer_settings_map: Dict[int, LayerCutSettings] = {}
        entities: List[LaserEntity] = []

        # Parse CutSetting XML elements
        for cs in root.findall(".//CutSetting"):
            try:
                idx = int(cs.attrib.get("index", cs.findtext("index") or 0))
                speed = float(cs.attrib.get("speed", cs.findtext("speed") or 1000.0))
                p_max = float(cs.attrib.get("maxPower", cs.findtext("maxPower") or cs.attrib.get("power", 80.0)))
                p_min = float(cs.attrib.get("minPower", cs.findtext("minPower") or 20.0))
                raw_mode = (cs.attrib.get("type") or cs.findtext("type") or "Cut").lower()
                mode = "Fill" if ("fill" in raw_mode or "scan" in raw_mode) else "Line"

                layer_setting = LayerCutSettings(
                    layer_id=idx,
                    name=f"C{idx:02d}",
                    mode=mode,
                    speed=speed,
                    power_max=p_max,
                    power_min=p_min
                )
                layer_settings_map[idx] = layer_setting
                if layer_manager:
                    layer_manager.set_layer(idx, layer_setting)
            except Exception:
                continue

        # Parse Shape XML elements
        for sh in root.findall(".//Shape"):
            stype = (sh.attrib.get("Type") or sh.attrib.get("type") or "").lower()
            lid = int(sh.attrib.get("CutIndex", sh.attrib.get("layer", 0)))
            name = sh.attrib.get("name", f"Shape_{len(entities) + 1}")

            xf = sh.find("XForm")
            xf_text = xf.text.strip() if xf is not None and xf.text else ""
            parts = [float(p) for p in xf_text.split()] if xf_text else []
            tx = parts[4] if len(parts) >= 6 else 0.0
            ty = parts[5] if len(parts) >= 6 else 0.0

            if stype in ("rect", "rectangle"):
                w = float(sh.attrib.get("W", sh.attrib.get("w", sh.attrib.get("width", 10.0))))
                h = float(sh.attrib.get("H", sh.attrib.get("h", sh.attrib.get("height", 10.0))))
                cr = float(sh.attrib.get("Cr", sh.attrib.get("cr", sh.attrib.get("radius", 0.0))))
                x = (tx - w / 2.0) if len(parts) >= 6 else float(sh.attrib.get("x", 0.0))
                y = (ty - h / 2.0) if len(parts) >= 6 else float(sh.attrib.get("y", 0.0))
                entities.append(RectEntity(layer_id=lid, name=name, x=x, y=y, width=w, height=h, corner_radius=cr))

            elif stype in ("circle", "ellipse"):
                rx = float(sh.attrib.get("Rx", sh.attrib.get("rx", sh.attrib.get("r", 10.0))))
                ry = float(sh.attrib.get("Ry", sh.attrib.get("ry", rx)))
                x = tx if len(parts) >= 6 else float(sh.attrib.get("x", 0.0))
                y = ty if len(parts) >= 6 else float(sh.attrib.get("y", 0.0))
                entities.append(CircleEntity(layer_id=lid, name=name, x=x, y=y, radius_x=rx, radius_y=ry))

            elif stype in ("line",):
                vl = sh.findtext("VertList")
                if vl:
                    matches = re.findall(r"V([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?),([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", vl)
                    pts = [(float(mx), float(my)) for mx, my in matches]
                    if len(pts) == 2:
                        entities.append(LineEntity(layer_id=lid, name=name, x=pts[0][0], y=pts[0][1], x2=pts[1][0], y2=pts[1][1]))
                else:
                    x1 = float(sh.attrib.get("x1", 0.0))
                    y1 = float(sh.attrib.get("y1", 0.0))
                    x2 = float(sh.attrib.get("x2", 10.0))
                    y2 = float(sh.attrib.get("y2", 10.0))
                    entities.append(LineEntity(layer_id=lid, name=name, x=x1, y=y1, x2=x2, y2=y2))

            elif stype in ("path", "polygon"):
                vl = sh.findtext("VertList")
                if vl:
                    matches = re.findall(r"V([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?),([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", vl)
                    pts = [(float(mx), float(my)) for mx, my in matches]
                    if len(pts) == 2:
                        entities.append(LineEntity(layer_id=lid, name=name, x=pts[0][0], y=pts[0][1], x2=pts[1][0], y2=pts[1][1]))
                    elif len(pts) > 2:
                        entities.append(PathEntity(layer_id=lid, name=name, x=0.0, y=0.0, contours=[pts], closed=True))
                else:
                    pts = []
                    for v in sh.findall(".//V"):
                        try:
                            pts.append((float(v.attrib.get("x", 0.0)), float(v.attrib.get("y", 0.0))))
                        except Exception:
                            pass
                    if pts:
                        entities.append(PathEntity(layer_id=lid, name=name, x=0.0, y=0.0, contours=[pts], closed=True))

            elif stype in ("text",):
                text_val = sh.attrib.get("Str", sh.attrib.get("text", sh.text or ""))
                font = sh.attrib.get("Font", sh.attrib.get("font", "Arial"))
                h = float(sh.attrib.get("H", sh.attrib.get("h", sh.attrib.get("size", 10.0))))
                bold = sh.attrib.get("Bold", "0") in ("1", "True", "true")
                italic = sh.attrib.get("Italic", "0") in ("1", "True", "true")
                x = tx if len(parts) >= 6 else float(sh.attrib.get("x", 0.0))
                y = ty if len(parts) >= 6 else float(sh.attrib.get("y", 0.0))
                entities.append(TextEntity(layer_id=lid, name=name, x=x, y=y, text=text_val, font_family=font, font_size=h, bold=bold, italic=italic))

            elif stype in ("bitmap", "image"):
                w = float(sh.attrib.get("W", sh.attrib.get("w", 10.0)))
                h = float(sh.attrib.get("H", sh.attrib.get("h", 10.0)))
                img_path = sh.attrib.get("File", sh.attrib.get("file", ""))
                x = (tx - w/2.0) if len(parts) >= 6 else float(sh.attrib.get("x", 0.0))
                y = (ty - h/2.0) if len(parts) >= 6 else float(sh.attrib.get("y", 0.0))
                entities.append(ImageEntity(layer_id=lid, name=name, x=x, y=y, width=w, height=h, image_path=img_path))

        return entities, layer_settings_map
