"""
LaserForge Professional DXF Importer.
Parses AutoCAD DXF files (Fusion 360, FreeCAD, AutoCAD, SolidWorks, QCAD)
into native LaserForge vector entities.

Supports:
  - LINE, CIRCLE, ARC, ELLIPSE, SPLINE, LWPOLYLINE, POLYLINE
  - Block references (INSERT) with virtual entity flattening
  - Single-line and Multi-line Text (TEXT, MTEXT)
  - Color-to-layer mapping matching LightBurn standard LAYER_PALETTE
  - Unit scaling (mm, inches, meters) from DXF $INSUNITS header
"""

from typing import List, Tuple, Dict, Optional, Any
import os
import math
import ezdxf
from ezdxf import path
from ezdxf.colors import aci2rgb

from laserforge.config import LAYER_PALETTE, DEFAULT_BED_WIDTH_MM, DEFAULT_BED_HEIGHT_MM
from laserforge.core.models import (
    LaserEntity, PathEntity, RectEntity, CircleEntity, LineEntity, TextEntity
)


def _hex_to_rgb(hex_str: str) -> Optional[Tuple[int, int, int]]:
    hex_clean = hex_str.strip().lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join([c * 2 for c in hex_clean])
    if len(hex_clean) == 6:
        try:
            return (int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16))
        except ValueError:
            return None
    return None


def _match_palette_layer(color_rgb: Tuple[int, int, int], default_id: int = 0) -> int:
    """Finds closest LightBurn layer ID by RGB Euclidean distance."""
    best_id = default_id
    min_dist = float("inf")
    r1, g1, b1 = color_rgb
    for l in LAYER_PALETTE:
        if l.get("is_tool", False):
            continue
        c_rgb = _hex_to_rgb(l["color"])
        if c_rgb:
            r2, g2, b2 = c_rgb
            dist = (r1 - r2)**2 * 0.30 + (g1 - g2)**2 * 0.59 + (b1 - b2)**2 * 0.11
            if dist < min_dist:
                min_dist = dist
                best_id = l["id"]
    return best_id


class DXFImporter:
    """Parses AutoCAD DXF files into LaserForge entities."""

    # DXF $INSUNITS mapping to millimeter scale factor
    # 1: Inches, 2: Feet, 4: Millimeters, 5: Centimeters, 6: Meters
    INSUNITS_TO_MM = {
        0: 1.0,      # Unitless -> default to mm
        1: 25.4,     # Inches
        2: 304.8,    # Feet
        3: 1609344.0,# Miles
        4: 1.0,      # Millimeters
        5: 10.0,     # Centimeters
        6: 1000.0,   # Meters
        7: 1e-6,     # Kilometers
        8: 25.4e-6,  # Microinches
        9: 25.4e-3,  # Mils
    }

    @staticmethod
    def import_dxf_file(
        filepath: str,
        default_layer_id: int = 0,
        flatten_distance_mm: float = 0.1,
        flip_y: bool = False
    ) -> List[LaserEntity]:
        """
        Parses a DXF file and returns a list of LaserForge entities.
        Entities are scaled to millimeters and positioned accurately.
        """
        if not os.path.exists(filepath):
            return []

        try:
            doc = ezdxf.readfile(filepath)
        except Exception as e:
            raise RuntimeError(f"Failed to read DXF file '{filepath}': {e}")

        # Determine unit scale factor
        unit_scale = 1.0
        try:
            insunits = doc.header.get("$INSUNITS", 4)
            unit_scale = DXFImporter.INSUNITS_TO_MM.get(int(insunits), 1.0)
        except Exception:
            unit_scale = 1.0

        msp = doc.modelspace()
        layer_color_cache: Dict[str, Tuple[int, int, int]] = {}

        def get_entity_rgb(dxf_entity) -> Optional[Tuple[int, int, int]]:
            """Extracts entity or layer RGB color."""
            # 1. Direct true color
            if hasattr(dxf_entity, "rgb") and dxf_entity.rgb is not None:
                return dxf_entity.rgb

            # 2. Entity ACI color
            color_idx = dxf_entity.dxf.get("color", 256)
            if 0 < color_idx < 256:
                try:
                    return aci2rgb(color_idx)
                except Exception:
                    pass

            # 3. ByLayer color
            layer_name = dxf_entity.dxf.get("layer", "0")
            if layer_name in layer_color_cache:
                return layer_color_cache[layer_name]

            try:
                dxf_layer = doc.layers.get(layer_name)
                if dxf_layer:
                    if hasattr(dxf_layer, "rgb") and dxf_layer.rgb is not None:
                        layer_color_cache[layer_name] = dxf_layer.rgb
                        return dxf_layer.rgb
                    layer_aci = abs(dxf_layer.color)
                    if 0 < layer_aci < 256:
                        rgb = aci2rgb(layer_aci)
                        layer_color_cache[layer_name] = rgb
                        return rgb
            except Exception:
                pass

            return None

        def resolve_layer_id(dxf_entity) -> int:
            rgb = get_entity_rgb(dxf_entity)
            if rgb is not None:
                return _match_palette_layer(rgb, default_layer_id)
            return default_layer_id

        entities: List[LaserEntity] = []

        def process_entity(e):
            dxftype = e.dxftype()
            layer_id = resolve_layer_id(e)

            if dxftype == "INSERT":
                # Explode block reference into virtual entities
                try:
                    for sub_e in e.virtual_entities():
                        process_entity(sub_e)
                except Exception:
                    pass
                return

            if dxftype in ("TEXT", "MTEXT"):
                text_str = e.dxf.get("text", "") if dxftype == "TEXT" else getattr(e, "text", "")
                if text_str:
                    # Clean MText formatting codes if present
                    text_clean = text_str.replace("\\P", "\n")
                    import re
                    text_clean = re.sub(r"\\[A-Za-z0-9]+;?", "", text_clean)
                    insert_pt = e.dxf.get("insert", (0, 0, 0))
                    height_mm = float(e.dxf.get("height", 5.0)) * unit_scale
                    x_mm = float(insert_pt[0]) * unit_scale
                    y_mm = float(insert_pt[1]) * unit_scale
                    if flip_y:
                        y_mm = -y_mm

                    entities.append(TextEntity(
                        layer_id=layer_id,
                        name=f"DXF_{e.dxf.get('layer', 'Text')}",
                        x=x_mm,
                        y=y_mm,
                        text=text_clean.strip(),
                        font_size=height_mm
                    ))
                return

            # Geometry paths: CIRCLE, ARC, ELLIPSE, LINE, SPLINE, LWPOLYLINE, POLYLINE
            try:
                p = path.make_path(e)
                raw_pts = list(p.flattening(distance=flatten_distance_mm))
                if len(raw_pts) < 2:
                    return

                scaled_pts = []
                for pt in raw_pts:
                    x = float(pt.x) * unit_scale
                    y = float(pt.y) * unit_scale
                    if flip_y:
                        y = -y
                    scaled_pts.append((x, y))

                # Check if it's a closed loop
                is_closed = (
                    getattr(p, "is_closed", False)
                    or math.hypot(scaled_pts[0][0] - scaled_pts[-1][0], scaled_pts[0][1] - scaled_pts[-1][1]) < 0.05
                )

                # Normalize entity coordinates
                min_x = min(pt[0] for pt in scaled_pts)
                min_y = min(pt[1] for pt in scaled_pts)
                local_contour = [(pt[0] - min_x, pt[1] - min_y) for pt in scaled_pts]

                entities.append(PathEntity(
                    layer_id=layer_id,
                    name=f"DXF_{dxftype}_{e.dxf.get('layer', '')}".strip("_"),
                    x=min_x,
                    y=min_y,
                    contours=[local_contour],
                    closed=is_closed
                ))
            except Exception:
                pass

        for entity in msp:
            process_entity(entity)

        # In DXF, positive Y goes UP, whereas in SVG / Screen graphics positive Y goes DOWN.
        # Normalize so entire design has its top-left at (min_x, min_y) with min_y positive
        if entities:
            all_min_y = float("inf")
            all_max_y = float("-inf")
            for ent in entities:
                b = ent.get_bounds()
                all_min_y = min(all_min_y, b[1])
                all_max_y = max(all_max_y, b[3])

            # Invert Y to match laser bed coordinates (0,0 at top-left or bottom-left)
            total_h = all_max_y - all_min_y
            for ent in entities:
                # Invert around center of bounding box
                ent.y = all_min_y + (all_max_y - (ent.y + (ent.get_bounds()[3] - ent.y)))
                if isinstance(ent, PathEntity):
                    # Invert Y of points
                    inverted_contours = []
                    for c in ent.contours:
                        inv_c = [(pt[0], -pt[1]) for pt in c]
                        # Re-normalize local min_y
                        min_cy = min(p[1] for p in inv_c)
                        inverted_contours.append([(p[0], p[1] - min_cy) for p in inv_c])
                    ent.contours = inverted_contours
                ent.invalidate_bounds()

        return entities
