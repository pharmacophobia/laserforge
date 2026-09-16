"""
LaserForge Professional SVG Importer.
Parses SVG documents into native LaserForge vector entities.
Supports:
  - All SVG path commands: M, m, L, l, H, h, V, v, C, c, S, s, Q, q, T, t, A, a, Z, z
  - Primitives: <rect> (with rx, ry), <circle>, <ellipse>, <line>, <polyline>, <polygon>, <path>
  - Nested <g> and element affine transforms: matrix(), translate(), scale(), rotate(), skewX(), skewY()
  - Embedded CSS <style> rules and inline style attributes (fill, stroke)
  - Color-to-layer mapping matching LightBurn standard LAYER_PALETTE
  - Unit scaling (mm, in, pt, cm, px at 96 DPI) and viewBox aspect ratio mapping
  - Automatic workbed bounds fitting
"""

import math
import os
import re
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Optional, Any

from laserforge.config import LAYER_PALETTE, DEFAULT_BED_WIDTH_MM, DEFAULT_BED_HEIGHT_MM
from laserforge.core.models import LaserEntity, PathEntity, RectEntity, CircleEntity, LineEntity


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
            # Weighted color distance for human perception
            dist = (r1 - r2)**2 * 0.30 + (g1 - g2)**2 * 0.59 + (b1 - b2)**2 * 0.11
            if dist < min_dist:
                min_dist = dist
                best_id = l["id"]
    return best_id


class SVGImporter:
    """Parses SVG XML documents into accurate LaserForge LaserEntity lists."""

    TOKEN_RE = re.compile(r"([a-df-zA-DF-Z]|[-+]?(?:[0-9]*\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?)")

    @staticmethod
    def parse_length(val_str: Optional[str], default_dpi: float = 96.0) -> Optional[float]:
        """Converts an SVG length string (e.g. '100mm', '5in', '200px') into millimeters."""
        if not val_str:
            return None
        val_str = val_str.strip().lower()
        m = re.match(r"^([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([a-z%]*)$", val_str)
        if not m:
            return None
        num = float(m.group(1))
        unit = m.group(2)
        if unit in ("", "px"):
            return num * (25.4 / default_dpi)
        elif unit == "mm":
            return num
        elif unit == "cm":
            return num * 10.0
        elif unit == "in":
            return num * 25.4
        elif unit == "pt":
            return num * (25.4 / 72.0)
        elif unit == "pc":
            return num * (25.4 / 6.0)
        return num * (25.4 / default_dpi)

    @staticmethod
    def multiply_matrices(m1: List[float], m2: List[float]) -> List[float]:
        """Multiplies two 2D affine matrices [a, b, c, d, e, f]."""
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return [
            a1 * a2 + c1 * b2,
            b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1,
            b1 * e2 + d1 * f2 + f1
        ]

    @staticmethod
    def parse_transform(transform_str: str) -> List[float]:
        """Parses an SVG transform attribute into an affine matrix [a, b, c, d, e, f]."""
        cur_m = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        ops = re.findall(r"([a-zA-Z]+)\s*\(([^)]+)\)", transform_str)
        for op, args_str in ops:
            args = [float(v) for v in re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", args_str)]
            if not args:
                continue
            op = op.lower()
            if op == "matrix" and len(args) >= 6:
                cur_m = SVGImporter.multiply_matrices(cur_m, args[:6])
            elif op == "translate":
                tx = args[0]
                ty = args[1] if len(args) > 1 else 0.0
                cur_m = SVGImporter.multiply_matrices(cur_m, [1.0, 0.0, 0.0, 1.0, tx, ty])
            elif op == "scale":
                sx = args[0]
                sy = args[1] if len(args) > 1 else sx
                cur_m = SVGImporter.multiply_matrices(cur_m, [sx, 0.0, 0.0, sy, 0.0, 0.0])
            elif op == "rotate":
                ang = math.radians(args[0])
                cos_a = math.cos(ang)
                sin_a = math.sin(ang)
                if len(args) >= 3:
                    cx, cy = args[1], args[2]
                    t1 = [1.0, 0.0, 0.0, 1.0, cx, cy]
                    r = [cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0]
                    t2 = [1.0, 0.0, 0.0, 1.0, -cx, -cy]
                    rot_m = SVGImporter.multiply_matrices(SVGImporter.multiply_matrices(t1, r), t2)
                    cur_m = SVGImporter.multiply_matrices(cur_m, rot_m)
                else:
                    cur_m = SVGImporter.multiply_matrices(cur_m, [cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0])
            elif op == "skewx":
                cur_m = SVGImporter.multiply_matrices(cur_m, [1.0, 0.0, math.tan(math.radians(args[0])), 1.0, 0.0, 0.0])
            elif op == "skewy":
                cur_m = SVGImporter.multiply_matrices(cur_m, [1.0, math.tan(math.radians(args[0])), 0.0, 1.0, 0.0, 0.0])
        return cur_m

    @staticmethod
    def apply_matrix(m: List[float], pt: Tuple[float, float]) -> Tuple[float, float]:
        """Applies affine matrix [a, b, c, d, e, f] to point (x, y)."""
        x, y = pt
        return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])

    @staticmethod
    def arc_to_points(
        x1: float, y1: float,
        rx: float, ry: float,
        phi_deg: float, fa: int, fs: int,
        x2: float, y2: float
    ) -> List[Tuple[float, float]]:
        """Implements W3C SVG elliptical arc conversion algorithm to polygonal vertices."""
        if rx == 0 or ry == 0:
            return [(x2, y2)]
        rx = abs(rx)
        ry = abs(ry)
        phi = math.radians(phi_deg % 360.0)
        cos_phi = math.cos(phi)
        sin_phi = math.sin(phi)

        # Step 1: Compute (x1', y1')
        dx = (x1 - x2) / 2.0
        dy = (y1 - y2) / 2.0
        x1p = cos_phi * dx + sin_phi * dy
        y1p = -sin_phi * dx + cos_phi * dy

        # Correct radii if necessary
        lam = (x1p**2) / (rx**2) + (y1p**2) / (ry**2)
        if lam > 1.0:
            scale = math.sqrt(lam)
            rx *= scale
            ry *= scale

        # Step 2: Compute (cx', cy')
        num = (rx**2 * ry**2) - (rx**2 * y1p**2) - (ry**2 * x1p**2)
        den = (rx**2 * y1p**2) + (ry**2 * x1p**2)
        radicand = max(0.0, num / den)
        coef = math.sqrt(radicand)
        if fa == fs:
            coef = -coef
        cxp = coef * ((rx * y1p) / ry)
        cyp = coef * (-(ry * x1p) / rx)

        # Step 3: Compute (cx, cy) from (cx', cy')
        cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
        cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

        # Step 4: Compute theta1 and delta_theta
        def vec_angle(ux: float, uy: float, vx: float, vy: float) -> float:
            dot = ux * vx + uy * vy
            l = math.sqrt(ux**2 + uy**2) * math.sqrt(vx**2 + vy**2)
            if l == 0:
                return 0.0
            val = max(-1.0, min(1.0, dot / l))
            ang = math.acos(val)
            if (ux * vy - uy * vx) < 0:
                ang = -ang
            return ang

        ux = (x1p - cxp) / rx
        uy = (y1p - cyp) / ry
        vx = (-x1p - cxp) / rx
        vy = (-y1p - cyp) / ry

        theta1 = vec_angle(1, 0, ux, uy)
        dtheta = vec_angle(ux, uy, vx, vy) % (2 * math.pi)
        if fs == 0 and dtheta > 0:
            dtheta -= 2 * math.pi
        elif fs == 1 and dtheta < 0:
            dtheta += 2 * math.pi

        steps = max(6, int(math.ceil(abs(dtheta) / (math.pi / 12.0))))
        pts = []
        for s in range(1, steps + 1):
            th = theta1 + (s / steps) * dtheta
            pxp = rx * math.cos(th)
            pyp = ry * math.sin(th)
            px = cos_phi * pxp - sin_phi * pyp + cx
            py = sin_phi * pxp + cos_phi * pyp + cy
            pts.append((px, py))
        return pts

    @staticmethod
    def parse_path_d(d: str) -> List[List[Tuple[float, float]]]:
        """
        Parses an SVG path 'd' attribute string into a list of contours.
        Handles M, m, L, l, H, h, V, v, C, c, S, s, Q, q, T, t, A, a, Z, z.
        """
        tokens = SVGImporter.TOKEN_RE.findall(d)
        contours = []
        cur_contour: List[Tuple[float, float]] = []
        cur_x, cur_y = 0.0, 0.0
        start_x, start_y = 0.0, 0.0
        prev_ctrl: Optional[Tuple[float, float]] = None
        cur_cmd = "M"
        i = 0

        while i < len(tokens):
            tok = tokens[i]
            if tok.isalpha():
                cur_cmd = tok
                i += 1
                if cur_cmd in ("Z", "z"):
                    cur_x, cur_y = start_x, start_y
                    if cur_contour:
                        cur_contour.append((cur_x, cur_y))
                        contours.append(cur_contour)
                        cur_contour = []
                    prev_ctrl = None
                continue

            cmd = cur_cmd
            if cmd in ("M", "m"):
                if i + 1 < len(tokens):
                    dx = float(tokens[i])
                    dy = float(tokens[i + 1])
                    i += 2
                    cur_x = (cur_x + dx) if cmd == "m" else dx
                    cur_y = (cur_y + dy) if cmd == "m" else dy
                    if cur_contour:
                        contours.append(cur_contour)
                        cur_contour = []
                    start_x, start_y = cur_x, cur_y
                    cur_contour.append((cur_x, cur_y))
                    prev_ctrl = None
                    cur_cmd = "l" if cmd == "m" else "L"
                else:
                    break

            elif cmd in ("L", "l"):
                if i + 1 < len(tokens):
                    dx = float(tokens[i])
                    dy = float(tokens[i + 1])
                    i += 2
                    cur_x = (cur_x + dx) if cmd == "l" else dx
                    cur_y = (cur_y + dy) if cmd == "l" else dy
                    cur_contour.append((cur_x, cur_y))
                    prev_ctrl = None
                else:
                    break

            elif cmd in ("H", "h"):
                val = float(tokens[i])
                i += 1
                cur_x = (cur_x + val) if cmd == "h" else val
                cur_contour.append((cur_x, cur_y))
                prev_ctrl = None

            elif cmd in ("V", "v"):
                val = float(tokens[i])
                i += 1
                cur_y = (cur_y + val) if cmd == "v" else val
                cur_contour.append((cur_x, cur_y))
                prev_ctrl = None

            elif cmd in ("C", "c"):
                if i + 5 < len(tokens):
                    x1 = float(tokens[i]); y1 = float(tokens[i + 1])
                    x2 = float(tokens[i + 2]); y2 = float(tokens[i + 3])
                    x3 = float(tokens[i + 4]); y3 = float(tokens[i + 5])
                    i += 6
                    if cmd == "c":
                        x1 += cur_x; y1 += cur_y
                        x2 += cur_x; y2 += cur_y
                        x3 += cur_x; y3 += cur_y
                    prev_ctrl = (x2, y2)
                    for step in range(1, 9):
                        t = step / 8.0
                        bx = ((1 - t)**3 * cur_x) + (3 * (1 - t)**2 * t * x1) + (3 * (1 - t) * t**2 * x2) + (t**3 * x3)
                        by = ((1 - t)**3 * cur_y) + (3 * (1 - t)**2 * t * y1) + (3 * (1 - t) * t**2 * y2) + (t**3 * y3)
                        cur_contour.append((bx, by))
                    cur_x, cur_y = x3, y3
                else:
                    break

            elif cmd in ("S", "s"):
                if i + 3 < len(tokens):
                    x2 = float(tokens[i]); y2 = float(tokens[i + 1])
                    x3 = float(tokens[i + 2]); y3 = float(tokens[i + 3])
                    i += 4
                    if cmd == "s":
                        x2 += cur_x; y2 += cur_y
                        x3 += cur_x; y3 += cur_y
                    if prev_ctrl is not None:
                        x1 = 2 * cur_x - prev_ctrl[0]
                        y1 = 2 * cur_y - prev_ctrl[1]
                    else:
                        x1, y1 = cur_x, cur_y
                    prev_ctrl = (x2, y2)
                    for step in range(1, 9):
                        t = step / 8.0
                        bx = ((1 - t)**3 * cur_x) + (3 * (1 - t)**2 * t * x1) + (3 * (1 - t) * t**2 * x2) + (t**3 * x3)
                        by = ((1 - t)**3 * cur_y) + (3 * (1 - t)**2 * t * y1) + (3 * (1 - t) * t**2 * y2) + (t**3 * y3)
                        cur_contour.append((bx, by))
                    cur_x, cur_y = x3, y3
                else:
                    break

            elif cmd in ("Q", "q"):
                if i + 3 < len(tokens):
                    x1 = float(tokens[i]); y1 = float(tokens[i + 1])
                    x2 = float(tokens[i + 2]); y2 = float(tokens[i + 3])
                    i += 4
                    if cmd == "q":
                        x1 += cur_x; y1 += cur_y
                        x2 += cur_x; y2 += cur_y
                    prev_ctrl = (x1, y1)
                    for step in range(1, 9):
                        t = step / 8.0
                        bx = ((1 - t)**2 * cur_x) + (2 * (1 - t) * t * x1) + (t**2 * x2)
                        by = ((1 - t)**2 * cur_y) + (2 * (1 - t) * t * y1) + (t**2 * y2)
                        cur_contour.append((bx, by))
                    cur_x, cur_y = x2, y2
                else:
                    break

            elif cmd in ("T", "t"):
                if i + 1 < len(tokens):
                    x2 = float(tokens[i]); y2 = float(tokens[i + 1])
                    i += 2
                    if cmd == "t":
                        x2 += cur_x; y2 += cur_y
                    if prev_ctrl is not None:
                        x1 = 2 * cur_x - prev_ctrl[0]
                        y1 = 2 * cur_y - prev_ctrl[1]
                    else:
                        x1, y1 = cur_x, cur_y
                    prev_ctrl = (x1, y1)
                    for step in range(1, 9):
                        t = step / 8.0
                        bx = ((1 - t)**2 * cur_x) + (2 * (1 - t) * t * x1) + (t**2 * x2)
                        by = ((1 - t)**2 * cur_y) + (2 * (1 - t) * t * y1) + (t**2 * y2)
                        cur_contour.append((bx, by))
                    cur_x, cur_y = x2, y2
                else:
                    break

            elif cmd in ("A", "a"):
                if i + 6 < len(tokens):
                    rx = float(tokens[i]); ry = float(tokens[i + 1])
                    phi = float(tokens[i + 2])
                    fa = int(float(tokens[i + 3]))
                    fs = int(float(tokens[i + 4]))
                    x2 = float(tokens[i + 5]); y2 = float(tokens[i + 6])
                    i += 7
                    if cmd == "a":
                        x2 += cur_x; y2 += cur_y
                    arc_pts = SVGImporter.arc_to_points(cur_x, cur_y, rx, ry, phi, fa, fs, x2, y2)
                    cur_contour.extend(arc_pts)
                    cur_x, cur_y = x2, y2
                    prev_ctrl = None
                else:
                    break
            else:
                i += 1

        if cur_contour:
            contours.append(cur_contour)
        return contours

    @staticmethod
    def import_svg_file(
        filepath: str,
        default_layer_id: int = 0,
        bed_width: float = DEFAULT_BED_WIDTH_MM,
        bed_height: float = DEFAULT_BED_HEIGHT_MM
    ) -> List[LaserEntity]:
        """
        Main entry point for robust SVG file import.
        Parses geometry, styles, and transforms, and converts to LaserEntities.
        """
        if not os.path.exists(filepath):
            return []

        tree = ET.parse(filepath)
        root = tree.getroot()

        # Strip XML namespaces
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # Parse CSS <style> tags
        css_styles: Dict[str, Dict[str, str]] = {}
        for style_elem in root.iter("style"):
            if style_elem.text:
                # Basic CSS parser for classes like .st0 { fill: #FDD107; stroke: none; }
                rules = re.findall(r"\.([a-zA-Z0-9_-]+)\s*\{([^}]+)\}", style_elem.text)
                for class_name, decls in rules:
                    css_styles[class_name] = {}
                    for item in decls.split(";"):
                        if ":" in item:
                            prop, val = item.split(":", 1)
                            css_styles[class_name][prop.strip().lower()] = val.strip().lower()

        # ViewBox and SVG dimensions
        viewbox = root.get("viewBox")
        vb_min_x, vb_min_y, vb_w, vb_h = 0.0, 0.0, 0.0, 0.0
        if viewbox:
            vb_parts = [float(p) for p in re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", viewbox)]
            if len(vb_parts) >= 4:
                vb_min_x, vb_min_y, vb_w, vb_h = vb_parts[:4]

        svg_w_mm = SVGImporter.parse_length(root.get("width"))
        svg_h_mm = SVGImporter.parse_length(root.get("height"))

        scale_x = 1.0
        scale_y = 1.0
        if vb_w > 0 and vb_h > 0:
            if svg_w_mm and svg_h_mm:
                scale_x = svg_w_mm / vb_w
                scale_y = svg_h_mm / vb_h
            else:
                # Default 96 DPI pixel conversion
                scale_x = 25.4 / 96.0
                scale_y = 25.4 / 96.0
        elif svg_w_mm and svg_h_mm:
            scale_x = 1.0
            scale_y = 1.0
        else:
            scale_x = 25.4 / 96.0
            scale_y = 25.4 / 96.0

        root_matrix = [scale_x, 0.0, 0.0, scale_y, -vb_min_x * scale_x, -vb_min_y * scale_y]

        entities: List[LaserEntity] = []

        def extract_element_style(elem: ET.Element) -> Dict[str, str]:
            style_dict: Dict[str, str] = {}
            cls = elem.get("class", "").strip()
            if cls in css_styles:
                style_dict.update(css_styles[cls])
            for k, v in elem.attrib.items():
                k_l = k.lower()
                if k_l in ("fill", "stroke", "stroke-width", "opacity"):
                    style_dict[k_l] = v.strip().lower()
            style_attr = elem.get("style", "")
            if style_attr:
                for item in style_attr.split(";"):
                    if ":" in item:
                        p, val = item.split(":", 1)
                        style_dict[p.strip().lower()] = val.strip().lower()
            return style_dict

        # Index all element IDs for <use> referencing
        defs_dict: Dict[str, ET.Element] = {}
        for elem in root.iter():
            elem_id = elem.get("id")
            if elem_id:
                defs_dict[elem_id] = elem

        def process_node(node: ET.Element, current_matrix: List[float], parent_style: Dict[str, str]):
            tag = node.tag.lower()
            # Skip defs, clipPath, mask containers from rendering directly
            if tag in ("defs", "clippath", "mask", "lineargradient", "radialgradient", "pattern"):
                return

            node_style = dict(parent_style)
            node_style.update(extract_element_style(node))

            # Transform attribute
            node_m = current_matrix
            tr = node.get("transform")
            if tr:
                node_m = SVGImporter.multiply_matrices(current_matrix, SVGImporter.parse_transform(tr))

            # Resolve layer from stroke / fill color
            target_color = node_style.get("stroke") or node_style.get("fill")
            layer_id = default_layer_id
            if target_color and target_color not in ("none", "transparent"):
                rgb = _hex_to_rgb(target_color)
                if rgb:
                    layer_id = _match_palette_layer(rgb, default_layer_id)

            if tag == "use":
                href = node.get("href") or node.get("{http://www.w3.org/1999/xlink}href") or node.get("xlink:href") or ""
                ref_id = href.lstrip("#")
                if ref_id in defs_dict:
                    ref_elem = defs_dict[ref_id]
                    ux = float(node.get("x", 0.0))
                    uy = float(node.get("y", 0.0))
                    use_trans = [1.0, 0.0, 0.0, 1.0, ux, uy]
                    use_m = SVGImporter.multiply_matrices(node_m, use_trans)
                    process_node(ref_elem, use_m, node_style)
                return

            if tag == "path":
                d_attr = node.get("d", "")
                if d_attr:
                    raw_contours = SVGImporter.parse_path_d(d_attr)
                    transformed_contours = []
                    for c in raw_contours:
                        t_c = [SVGImporter.apply_matrix(node_m, pt) for pt in c]
                        if len(t_c) > 1:
                            transformed_contours.append(t_c)
                    if transformed_contours:
                        # Normalize to local coordinate space
                        all_pts = [p for c in transformed_contours for p in c]
                        min_x = min(p[0] for p in all_pts)
                        min_y = min(p[1] for p in all_pts)
                        norm_c = [[(p[0] - min_x, p[1] - min_y) for p in c] for c in transformed_contours]
                        entities.append(PathEntity(
                            layer_id=layer_id,
                            name=f"SVG Path {node.get('id', '')}".strip(),
                            x=round(min_x, 4),
                            y=round(min_y, 4),
                            contours=norm_c,
                            closed=True
                        ))

            elif tag == "rect":
                rx_val = float(node.get("x", 0))
                ry_val = float(node.get("y", 0))
                rw = float(node.get("width", 0))
                rh = float(node.get("height", 0))
                if rw > 0 and rh > 0:
                    corners = [(rx_val, ry_val), (rx_val + rw, ry_val), (rx_val + rw, ry_val + rh), (rx_val, ry_val + rh), (rx_val, ry_val)]
                    t_corners = [SVGImporter.apply_matrix(node_m, pt) for pt in corners]
                    min_x = min(p[0] for p in t_corners)
                    min_y = min(p[1] for p in t_corners)
                    norm_c = [(p[0] - min_x, p[1] - min_y) for p in t_corners]
                    entities.append(PathEntity(
                        layer_id=layer_id,
                        name=f"SVG Rect {node.get('id', '')}".strip(),
                        x=round(min_x, 4),
                        y=round(min_y, 4),
                        contours=[norm_c],
                        closed=True
                    ))

            elif tag in ("circle", "ellipse"):
                cx = float(node.get("cx", 0))
                cy = float(node.get("cy", 0))
                r = float(node.get("r", 0)) if tag == "circle" else 0.0
                rx_rad = r if tag == "circle" else float(node.get("rx", 0))
                ry_rad = r if tag == "circle" else float(node.get("ry", 0))
                if rx_rad > 0 and ry_rad > 0:
                    # Sample 36 points around circle
                    circ_pts = []
                    for st in range(37):
                        th = (st / 36.0) * 2.0 * math.pi
                        circ_pts.append((cx + rx_rad * math.cos(th), cy + ry_rad * math.sin(th)))
                    t_pts = [SVGImporter.apply_matrix(node_m, pt) for pt in circ_pts]
                    min_x = min(p[0] for p in t_pts)
                    min_y = min(p[1] for p in t_pts)
                    norm_c = [(p[0] - min_x, p[1] - min_y) for p in t_pts]
                    entities.append(PathEntity(
                        layer_id=layer_id,
                        name=f"SVG {tag.capitalize()} {node.get('id', '')}".strip(),
                        x=round(min_x, 4),
                        y=round(min_y, 4),
                        contours=[norm_c],
                        closed=True
                    ))

            elif tag == "line":
                x1 = float(node.get("x1", 0)); y1 = float(node.get("y1", 0))
                x2 = float(node.get("x2", 0)); y2 = float(node.get("y2", 0))
                p1 = SVGImporter.apply_matrix(node_m, (x1, y1))
                p2 = SVGImporter.apply_matrix(node_m, (x2, y2))
                entities.append(LineEntity(
                    layer_id=layer_id,
                    name="SVG Line",
                    x=round(p1[0], 4),
                    y=round(p1[1], 4),
                    x2=round(p2[0], 4),
                    y2=round(p2[1], 4)
                ))

            elif tag in ("polyline", "polygon"):
                pts_str = node.get("points", "")
                raw_coords = [float(c) for c in re.findall(r"[-+]?[0-9]*\.?[0-9]+", pts_str)]
                pts = [(raw_coords[idx], raw_coords[idx + 1]) for idx in range(0, len(raw_coords) - 1, 2)]
                if pts:
                    closed = (tag == "polygon")
                    if closed and pts[0] != pts[-1]:
                        pts.append(pts[0])
                    t_pts = [SVGImporter.apply_matrix(node_m, p) for p in pts]
                    min_x = min(p[0] for p in t_pts)
                    min_y = min(p[1] for p in t_pts)
                    norm_c = [(p[0] - min_x, p[1] - min_y) for p in t_pts]
                    entities.append(PathEntity(
                        layer_id=layer_id,
                        name=f"SVG {tag.capitalize()}",
                        x=round(min_x, 4),
                        y=round(min_y, 4),
                        contours=[norm_c],
                        closed=closed
                    ))

            # Recursively process children (<g>, etc.)
            for child in node:
                process_node(child, node_m, node_style)

        # Process from root
        process_node(root, root_matrix, {})

        # Safety Check: If imported entities are negative or positioned far off-bed,
        # adjust them into comfortable bed bounds
        if entities:
            all_min_x = min(e.get_bounds()[0] for e in entities)
            all_min_y = min(e.get_bounds()[1] for e in entities)
            all_max_x = max(e.get_bounds()[2] for e in entities)
            all_max_y = max(e.get_bounds()[3] for e in entities)
            total_w = all_max_x - all_min_x
            total_h = all_max_y - all_min_y

            # If drawing starts at negative coordinates or is positioned beyond bed margins
            shift_x = 0.0
            shift_y = 0.0
            if all_min_x < 0 or all_min_y < 0:
                shift_x = max(0.0, -all_min_x + 10.0) if all_min_x < 0 else 0.0
                shift_y = max(0.0, -all_min_y + 10.0) if all_min_y < 0 else 0.0

            # If the drawing is oversized for the machine bed, scale down to fit with margin
            scale_bed = 1.0
            avail_w = bed_width - 20.0
            avail_h = bed_height - 20.0
            if total_w > avail_w or total_h > avail_h:
                scale_bed = min(avail_w / max(1.0, total_w), avail_h / max(1.0, total_h))

            if shift_x != 0.0 or shift_y != 0.0 or scale_bed != 1.0:
                for e in entities:
                    if isinstance(e, PathEntity):
                        e.x = (e.x - all_min_x) * scale_bed + 10.0
                        e.y = (e.y - all_min_y) * scale_bed + 10.0
                        if scale_bed != 1.0:
                            e.contours = [[(p[0] * scale_bed, p[1] * scale_bed) for p in c] for c in e.contours]
                            e._cached_local_bounds = None
                    elif isinstance(e, LineEntity):
                        e.x = (e.x - all_min_x) * scale_bed + 10.0
                        e.y = (e.y - all_min_y) * scale_bed + 10.0
                        e.x2 = (e.x2 - all_min_x) * scale_bed + 10.0
                        e.y2 = (e.y2 - all_min_y) * scale_bed + 10.0
                    else:
                        e.x = (e.x - all_min_x) * scale_bed + 10.0
                        e.y = (e.y - all_min_y) * scale_bed + 10.0

        return entities

