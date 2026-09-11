"""
LaserForge Font & Typography Workflow Aids.
Provides tools to accelerate laser text engraving:
- Circular / Arc Text (text on a curved path)
- Sequential Serial Number & Batch Variable Text generation
"""

from typing import List, Tuple, Optional
import math
from PyQt6.QtGui import (
    QFont, QFontMetricsF, QPainterPath, QTransform
)
from laserforge.core.models import (
    LaserEntity, PathEntity, TextEntity
)


class FontTools:

    @staticmethod
    def generate_curved_text(
        text: str = "LASERFORGE",
        font_family: str = "Sans Serif",
        font_size_mm: float = 12.0,
        radius_mm: float = 40.0,
        cx: float = 50.0,
        cy: float = 50.0,
        start_angle_deg: float = 90.0,  # 90 is top
        orientation: str = "Top (Clockwise)",  # "Top (Clockwise)" or "Bottom (Counter-Clockwise)"
        bold: bool = True,
        italic: bool = False,
        spacing_multiplier: float = 1.0,
        layer_id: int = 0
    ) -> Optional[PathEntity]:
        """
        Generates vector text curved along a circular arc of specified radius.
        Returns a closed PathEntity containing all glyph contours.
        """
        if not text.strip():
            return None

        # Scale font for crisp vectorization
        pt_size = int(round(font_size_mm * 3.0))
        font = QFont(font_family, pt_size)
        font.setBold(bold)
        font.setItalic(italic)
        fm = QFontMetricsF(font)

        # Total arc length
        char_widths = [fm.horizontalAdvance(ch) * spacing_multiplier for ch in text]
        total_width = sum(char_widths)
        if radius_mm <= 1.0 or total_width <= 0:
            return None

        # Scale factor from Qt font units to mm
        scale_to_mm = font_size_mm / max(1.0, fm.ascent() + fm.descent())

        total_angle_rad = (total_width * scale_to_mm) / radius_mm

        is_bottom = "bottom" in orientation.lower()

        # Invert angle direction if bottom
        base_center_angle = math.radians(start_angle_deg)
        if is_bottom:
            start_ang = base_center_angle + (total_angle_rad / 2.0)
            dir_sign = -1.0
        else:
            start_ang = base_center_angle - (total_angle_rad / 2.0)
            dir_sign = 1.0

        total_path = QPainterPath()
        cur_ang = start_ang

        for i, ch in enumerate(text):
            ch_w_mm = char_widths[i] * scale_to_mm
            ch_ang_span = ch_w_mm / radius_mm
            mid_ang = cur_ang + dir_sign * (ch_ang_span / 2.0)

            # Center position of character on arc
            px = cx + radius_mm * math.cos(mid_ang)
            py = cy - radius_mm * math.sin(mid_ang)  # Inverted Y for screen coordinates

            # Tangent angle for glyph rotation
            if is_bottom:
                rot_deg = -math.degrees(mid_ang) - 90.0
            else:
                rot_deg = -math.degrees(mid_ang) + 90.0

            ch_path = QPainterPath()
            ch_ascent = fm.ascent() * scale_to_mm
            ch_w_raw = fm.horizontalAdvance(ch) * scale_to_mm
            # Center character horizontally and baseline vertically
            ch_path.addText(-ch_w_raw / 2.0, ch_ascent / 2.0, font, ch)

            trans = QTransform()
            trans.translate(px, py)
            trans.rotate(rot_deg)
            trans.scale(scale_to_mm, scale_to_mm)

            total_path.addPath(trans.map(ch_path))
            cur_ang += dir_sign * ch_ang_span

        # Convert to contours
        subpaths = total_path.toSubpathPolygons()
        if not subpaths:
            return None

        contours = []
        for poly in subpaths:
            pts = [(float(pt.x()), float(pt.y())) for pt in poly]
            if len(pts) > 2:
                contours.append(pts)

        if not contours:
            return None

        return PathEntity(
            layer_id=layer_id,
            name=f"Curved_{text[:10]}",
            x=0.0, y=0.0,
            contours=contours,
            closed=True
        )

    @staticmethod
    def generate_serial_batch(
        prefix: str = "SN-",
        start_number: int = 1,
        count: int = 10,
        digits: int = 3,
        suffix: str = "",
        start_x: float = 10.0,
        start_y: float = 10.0,
        step_x: float = 0.0,
        step_y: float = 12.0,
        font_family: str = "Sans Serif",
        font_size_mm: float = 8.0,
        fill_mode: str = "Fill",
        layer_id: int = 0
    ) -> List[TextEntity]:
        """
        Generates a sequential array of serial number / variable text entities.
        """
        entities: List[TextEntity] = []
        for i in range(count):
            num_val = start_number + i
            num_str = f"{num_val:0{digits}d}"
            full_text = f"{prefix}{num_str}{suffix}"

            x = start_x + (i * step_x)
            y = start_y + (i * step_y)
            w = len(full_text) * font_size_mm * 0.65

            entities.append(TextEntity(
                layer_id=layer_id,
                name=f"Serial_{num_str}",
                x=x, y=y,
                text=full_text,
                font_family=font_family,
                font_size=font_size_mm,
                bold=True,
                width=w, height=font_size_mm,
                fill_mode=fill_mode
            ))

        return entities
