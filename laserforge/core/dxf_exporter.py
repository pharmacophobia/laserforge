"""
LaserForge AutoCAD DXF Exporter.
Exports LaserForge vector entities (paths, rects, circles, lines, text)
to standard AutoCAD DXF files (R2010 format) with millimeter units
and LightBurn-compatible layer color mappings.
"""

from typing import List, Tuple, Optional
import os
import math
import ezdxf
from ezdxf.colors import rgb2int

from laserforge.config import LAYER_PALETTE
from laserforge.core.models import (
    LaserEntity, PathEntity, RectEntity, CircleEntity, LineEntity, TextEntity
)


def _hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    hex_clean = hex_str.strip().lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join([c * 2 for c in hex_clean])
    if len(hex_clean) == 6:
        try:
            return (int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16))
        except ValueError:
            pass
    return (0, 0, 0)


class DXFExporter:
    """Exports LaserForge entities to DXF format."""

    @staticmethod
    def export_dxf_file(
        entities: List[LaserEntity],
        filepath: str,
        invert_y_for_cad: bool = True
    ) -> bool:
        """
        Exports a list of LaserForge entities to a standard DXF file.
        In DXF, positive Y points upward by convention.
        """
        if not entities:
            return False

        doc = ezdxf.new("R2010", setup=True)
        doc.header["$INSUNITS"] = 4  # 4 = Millimeters
        msp = doc.modelspace()

        # Build DXF layers from LAYER_PALETTE
        layer_names: dict[int, str] = {}
        for lyr in LAYER_PALETTE:
            lyr_id = lyr["id"]
            name = f"{lyr['name']}_{lyr['label']}".replace(" ", "_")
            layer_names[lyr_id] = name
            rgb = _hex_to_rgb(lyr["color"])
            try:
                dxf_layer = doc.layers.add(name)
                dxf_layer.rgb = rgb
            except Exception:
                pass

        # Calculate design height for Y inversion
        design_max_y = 0.0
        if invert_y_for_cad:
            for e in entities:
                b = e.get_bounds()
                design_max_y = max(design_max_y, b[3])

        def transform_y(y: float) -> float:
            return (design_max_y - y) if invert_y_for_cad else y

        for e in entities:
            lyr_name = layer_names.get(e.layer_id, "0")
            attribs = {"layer": lyr_name}

            if isinstance(e, LineEntity):
                p1 = (e.x, transform_y(e.y))
                p2 = (e.x2, transform_y(e.y2))
                msp.add_line(p1, p2, dxfattribs=attribs)

            elif isinstance(e, CircleEntity):
                center = (e.x, transform_y(e.y))
                # For non-uniform ellipse or standard circle
                if abs(e.radius_x - e.radius_y) < 1e-3:
                    msp.add_circle(center, radius=e.radius_x, dxfattribs=attribs)
                else:
                    # Export ellipse
                    msp.add_ellipse(
                        center,
                        major_axis=(e.radius_x, 0, 0),
                        ratio=max(0.01, e.radius_y / max(0.01, e.radius_x)),
                        dxfattribs=attribs
                    )

            elif isinstance(e, RectEntity):
                rx = e.corner_radius
                if rx <= 0.01:
                    pts = [
                        (e.x, transform_y(e.y)),
                        (e.x + e.width, transform_y(e.y)),
                        (e.x + e.width, transform_y(e.y + e.height)),
                        (e.x, transform_y(e.y + e.height))
                    ]
                    msp.add_lwpolyline(pts, close=True, dxfattribs=attribs)
                else:
                    # Rounded rectangle approximated with line segments
                    steps_arc = 12
                    pts = []
                    # Top-left arc
                    for i in range(steps_arc + 1):
                        ang = math.pi + (i / steps_arc) * (math.pi / 2.0)
                        pts.append((e.x + rx + rx * math.cos(ang), transform_y(e.y + rx - rx * math.sin(ang))))
                    # Top-right arc
                    for i in range(steps_arc + 1):
                        ang = 1.5 * math.pi + (i / steps_arc) * (math.pi / 2.0)
                        pts.append((e.x + e.width - rx + rx * math.cos(ang), transform_y(e.y + rx - rx * math.sin(ang))))
                    # Bottom-right arc
                    for i in range(steps_arc + 1):
                        ang = (i / steps_arc) * (math.pi / 2.0)
                        pts.append((e.x + e.width - rx + rx * math.cos(ang), transform_y(e.y + e.height - rx - rx * math.sin(ang))))
                    # Bottom-left arc
                    for i in range(steps_arc + 1):
                        ang = 0.5 * math.pi + (i / steps_arc) * (math.pi / 2.0)
                        pts.append((e.x + rx + rx * math.cos(ang), transform_y(e.y + e.height - rx - rx * math.sin(ang))))
                    msp.add_lwpolyline(pts, close=True, dxfattribs=attribs)

            elif isinstance(e, PathEntity):
                for contour in e.contours:
                    if len(contour) < 2:
                        continue
                    pts = [(e.x + pt[0], transform_y(e.y + pt[1])) for pt in contour]
                    msp.add_lwpolyline(pts, close=e.closed, dxfattribs=attribs)

            elif isinstance(e, TextEntity):
                insert_pt = (e.x, transform_y(e.y + e.height))
                msp.add_text(
                    e.text,
                    dxfattribs={
                        "layer": lyr_name,
                        "height": max(1.0, e.font_size),
                        "insert": insert_pt
                    }
                )

        doc.saveas(filepath)
        return True
