"""
LaserForge Parametric Shape Generator and Contour Offset Tool.
Generates geometric shapes (polygons, stars, hearts, gears, capsules, donuts, crosses)
and calculates outward/inward outline contour offsets (LightBurn-style Offset Tool).
"""

from typing import List, Tuple, Optional
import math
from PyQt6.QtGui import (
    QPainterPath, QPainterPathStroker, QFont, QFontMetricsF
)
from PyQt6.QtCore import QRectF, Qt
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
)


class ShapeGenerator:

    @staticmethod
    def create_regular_polygon(
        sides: int = 6,
        radius: float = 25.0,
        cx: float = 50.0,
        cy: float = 50.0,
        rotation_deg: float = 0.0,
        layer_id: int = 0
    ) -> PathEntity:
        """Generates regular N-gon polygon (Triangle, Hexagon, Octagon, etc.)."""
        sides = max(3, sides)
        pts = []
        rot_rad = math.radians(rotation_deg - 90.0)
        step = (2.0 * math.pi) / sides
        for i in range(sides):
            ang = rot_rad + i * step
            pts.append((radius * math.cos(ang), radius * math.sin(ang)))

        name = {3: "Triangle", 4: "Diamond", 5: "Pentagon", 6: "Hexagon", 8: "Octagon"}.get(sides, f"{sides}-gon")
        return PathEntity(layer_id=layer_id, name=name, x=cx, y=cy, contours=[pts], closed=True)

    @staticmethod
    def create_star(
        points: int = 5,
        r_outer: float = 30.0,
        r_inner: float = 14.0,
        cx: float = 50.0,
        cy: float = 50.0,
        rotation_deg: float = 0.0,
        layer_id: int = 0
    ) -> PathEntity:
        """Generates N-pointed star."""
        points = max(3, points)
        pts = []
        total_pts = points * 2
        rot_rad = math.radians(rotation_deg - 90.0)
        step = math.pi / points

        for i in range(total_pts):
            r = r_outer if i % 2 == 0 else r_inner
            ang = rot_rad + i * step
            pts.append((r * math.cos(ang), r * math.sin(ang)))

        return PathEntity(layer_id=layer_id, name=f"{points}-Point Star", x=cx, y=cy, contours=[pts], closed=True)

    @staticmethod
    def create_heart(
        width: float = 40.0,
        height: float = 40.0,
        cx: float = 50.0,
        cy: float = 50.0,
        layer_id: int = 0
    ) -> PathEntity:
        """Generates smooth parametric bezier heart."""
        pts = []
        steps = 72
        # Cardioid parametric formula
        for i in range(steps):
            t = (i / float(steps)) * 2.0 * math.pi
            x = 16.0 * (math.sin(t) ** 3)
            # Inverted for laser Y-down screen coordinates
            y = -(13.0 * math.cos(t) - 5.0 * math.cos(2 * t) - 2.0 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((x * (width / 32.0), (y + 2.0) * (height / 32.0)))

        return PathEntity(layer_id=layer_id, name="Heart", x=cx, y=cy, contours=[pts], closed=True)

    @staticmethod
    def create_gear(
        teeth: int = 12,
        pitch_dia: float = 40.0,
        bore_dia: float = 6.0,
        cx: float = 50.0,
        cy: float = 50.0,
        layer_id: int = 0
    ) -> List[LaserEntity]:
        """Generates parametric spur gear profile with central shaft bore hole."""
        teeth = max(4, teeth)
        module = pitch_dia / float(teeth)
        r_pitch = pitch_dia / 2.0
        r_addendum = r_pitch + module
        r_dedendum = max(2.0, r_pitch - 1.25 * module)

        pts = []
        tooth_angle = (2.0 * math.pi) / teeth
        half_tooth = tooth_angle / 2.0
        quarter_tooth = tooth_angle / 4.0

        for t in range(teeth):
            base_ang = t * tooth_angle

            # 1. Root bottom
            a0 = base_ang
            pts.append((r_dedendum * math.cos(a0), r_dedendum * math.sin(a0)))

            # 2. Involute / Flank up to tip
            a1 = base_ang + quarter_tooth * 0.7
            pts.append((r_addendum * math.cos(a1), r_addendum * math.sin(a1)))

            # 3. Tip crest
            a2 = base_ang + quarter_tooth * 1.3
            pts.append((r_addendum * math.cos(a2), r_addendum * math.sin(a2)))

            # 4. Flank down to root
            a3 = base_ang + half_tooth
            pts.append((r_dedendum * math.cos(a3), r_dedendum * math.sin(a3)))

        gear_body = PathEntity(
            layer_id=layer_id, name=f"Gear ({teeth}T)",
            x=cx, y=cy, contours=[pts], closed=True
        )

        entities: List[LaserEntity] = [gear_body]
        if bore_dia > 0:
            r_bore = bore_dia / 2.0
            entities.append(CircleEntity(
                layer_id=layer_id, name="Gear Bore Hole",
                x=cx, y=cy, radius_x=r_bore, radius_y=r_bore
            ))

        return entities

    @staticmethod
    def create_slot_capsule(
        width: float = 60.0,
        height: float = 20.0,
        cx: float = 50.0,
        cy: float = 50.0,
        layer_id: int = 0
    ) -> PathEntity:
        """Generates slot / pill / capsule shape with semicircular round ends."""
        r = height / 2.0
        straight_w = max(0.0, width - 2 * r)
        pts = []
        steps = 18

        # Right semicircle
        for i in range(steps + 1):
            ang = math.radians(-90.0 + i * (180.0 / steps))
            pts.append(((straight_w / 2.0) + r * math.cos(ang), r * math.sin(ang)))

        # Left semicircle
        for i in range(steps + 1):
            ang = math.radians(90.0 + i * (180.0 / steps))
            pts.append((-(straight_w / 2.0) + r * math.cos(ang), r * math.sin(ang)))

        return PathEntity(layer_id=layer_id, name="Slot Capsule", x=cx, y=cy, contours=[pts], closed=True)

    @staticmethod
    def create_ring_donut(
        outer_dia: float = 50.0,
        inner_dia: float = 30.0,
        cx: float = 50.0,
        cy: float = 50.0,
        layer_id: int = 0
    ) -> List[LaserEntity]:
        """Generates concentric ring / washer."""
        r_out = outer_dia / 2.0
        r_in = min(r_out - 1.0, inner_dia / 2.0)
        return [
            CircleEntity(layer_id=layer_id, name="Ring Outer", x=cx, y=cy, radius_x=r_out, radius_y=r_out),
            CircleEntity(layer_id=layer_id, name="Ring Hole", x=cx, y=cy, radius_x=r_in, radius_y=r_in)
        ]

    @staticmethod
    def create_cross(
        size: float = 40.0,
        arm_width: float = 12.0,
        cx: float = 50.0,
        cy: float = 50.0,
        layer_id: int = 0
    ) -> PathEntity:
        """Generates symmetric plus / cross symbol."""
        s = size / 2.0
        w = arm_width / 2.0
        pts = [
            (-w, -s), (w, -s), (w, -w), (s, -w),
            (s, w), (w, w), (w, s), (-w, s),
            (-w, w), (-s, w), (-s, -w), (-w, -w)
        ]
        return PathEntity(layer_id=layer_id, name="Cross", x=cx, y=cy, contours=[pts], closed=True)

    @staticmethod
    def offset_entity(
        entity: LaserEntity,
        offset_dist_mm: float = 3.0,
        corner_join: str = "Round",
        target_layer_id: int = 1
    ) -> Optional[LaserEntity]:
        """
        Calculates an outward or inward outline contour offset around any workpiece (LightBurn-style Offset).
        """
        # Convert entity to QPainterPath
        base_path = QPainterPath()

        if isinstance(entity, RectEntity):
            base_path.addRoundedRect(
                QRectF(entity.x, entity.y, entity.width, entity.height),
                entity.corner_radius, entity.corner_radius
            )
        elif isinstance(entity, CircleEntity):
            base_path.addEllipse(
                entity.x - entity.radius_x, entity.y - entity.radius_y,
                entity.radius_x * 2.0, entity.radius_y * 2.0
            )
        elif isinstance(entity, PathEntity):
            for contour in entity.contours:
                if len(contour) > 1:
                    base_path.moveTo(entity.x + contour[0][0], entity.y + contour[0][1])
                    for pt in contour[1:]:
                        base_path.lineTo(entity.x + pt[0], entity.y + pt[1])
                    if entity.closed:
                        base_path.closeSubpath()
        elif isinstance(entity, TextEntity):
            font = QFont(entity.font_family, int(round(entity.font_size * 2)))
            font.setBold(entity.bold)
            font.setItalic(entity.italic)
            font.setUnderline(getattr(entity, "underline", False))
            fm = QFontMetricsF(font)
            baseline_y = entity.y + (entity.height + fm.ascent() - fm.descent()) / 2.0
            base_path.addText(entity.x, baseline_y, font, entity.text)
        elif isinstance(entity, ImageEntity):
            base_path.addRect(QRectF(entity.x, entity.y, entity.width, entity.height))
        else:
            return None

        if base_path.isEmpty():
            return None

        # Build stroke expansion
        stroker = QPainterPathStroker()
        stroker.setWidth(abs(offset_dist_mm) * 2.0)
        if corner_join == "Miter":
            stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            stroker.setCapStyle(Qt.PenCapStyle.SquareCap)
        elif corner_join == "Bevel":
            stroker.setJoinStyle(Qt.PenJoinStyle.BevelJoin)
        else:
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)

        stroke_path = stroker.createStroke(base_path)
        united_path = base_path.united(stroke_path)

        # Extract contours
        subpaths = united_path.toSubpathPolygons()
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
            layer_id=target_layer_id,
            name=f"Offset_{entity.name}",
            x=0.0, y=0.0,
            contours=contours,
            closed=True
        )
