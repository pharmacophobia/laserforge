"""
LaserForge Vector Boolean Operations Engine.
Implements 2D Constructive Solid Geometry (CSG) operations on vector entities:
- Weld / Union (A ∪ B ∪ ...)
- Subtract / Difference (A ∖ B ∖ ...)
- Intersect (A ∩ B ∩ ...)
"""

import math
from typing import List, Tuple, Optional, Union
from PyQt6.QtGui import QPainterPath, QTransform, QFont, QFontMetricsF
from PyQt6.QtCore import QRectF, QPointF

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)
from laserforge.core.image_tracer import rdp_simplify_polygon


def entity_to_painter_path(entity: LaserEntity) -> Optional[QPainterPath]:
    """
    Converts a LaserEntity into a world-coordinate QPainterPath,
    accurately accounting for position, size, and rotation.
    Returns None for unsupported or non-vector entities (e.g. ImageEntity).
    """
    path = QPainterPath()

    if isinstance(entity, RectEntity):
        # Rect local bounds: (0, 0, width, height) placed at (entity.x, entity.y)
        path.addRect(QRectF(entity.x, entity.y, entity.width, entity.height))
        if entity.rotation != 0.0:
            cx = entity.x + entity.width / 2.0
            cy = entity.y + entity.height / 2.0
            t = QTransform()
            t.translate(cx, cy)
            t.rotate(entity.rotation)
            t.translate(-cx, -cy)
            path = t.map(path)

    elif isinstance(entity, CircleEntity):
        # Circle local bounds: centered at (0, 0) placed at (entity.x, entity.y)
        rx = entity.radius_x
        ry = entity.radius_y
        path.addEllipse(QRectF(entity.x - rx, entity.y - ry, rx * 2.0, ry * 2.0))
        if entity.rotation != 0.0:
            t = QTransform()
            t.translate(entity.x, entity.y)
            t.rotate(entity.rotation)
            t.translate(-entity.x, -entity.y)
            path = t.map(path)

    elif isinstance(entity, LineEntity):
        # Lines have zero 2D area and cannot participate meaningfully in area CSG
        # operations (union/subtract/intersect). Return None so the caller can warn
        # the user rather than silently producing a 0.1 mm-wide artefact strip.
        return None

    elif isinstance(entity, PathEntity):
        for contour in entity.contours:
            if not contour:
                continue
            path.moveTo(entity.x + contour[0][0], entity.y + contour[0][1])
            for pt in contour[1:]:
                path.lineTo(entity.x + pt[0], entity.y + pt[1])
            if entity.closed:
                path.closeSubpath()

        if entity.rotation != 0.0:
            b = entity.get_bounds()
            cx = (b[0] + b[2]) / 2.0
            cy = (b[1] + b[3]) / 2.0
            t = QTransform()
            t.translate(cx, cy)
            t.rotate(entity.rotation)
            t.translate(-cx, -cy)
            path = t.map(path)

    elif isinstance(entity, TextEntity):
        font = QFont(entity.font_family, max(6, int(round(entity.font_size * 2.835))))
        font.setBold(entity.bold)
        font.setItalic(entity.italic)
        font.setUnderline(getattr(entity, "underline", False))
        fm = QFontMetricsF(font)
        y_offset = entity.y + fm.ascent()
        path.addText(QPointF(entity.x, y_offset), font, entity.text)
        if entity.rotation != 0.0:
            cx = entity.x + entity.width / 2.0
            cy = entity.y + entity.height / 2.0
            t = QTransform()
            t.translate(cx, cy)
            t.rotate(entity.rotation)
            t.translate(-cx, -cy)
            path = t.map(path)

    else:
        return None

    return path


def painter_path_to_contours(
    ppath: QPainterPath, rdp_epsilon: float = 0.02
) -> List[List[Tuple[float, float]]]:
    """
    Extracts individual closed subpath polygon loops from a QPainterPath.
    Optionally runs RDP simplification to eliminate redundant collinear vertices.
    """
    polygons = ppath.toSubpathPolygons()
    contours: List[List[Tuple[float, float]]] = []

    for poly in polygons:
        pts: List[Tuple[float, float]] = []
        for i in range(poly.size()):
            p = poly.at(i)
            pts.append((p.x(), p.y()))

        # Need at least 3 points to form a polygon
        if len(pts) < 3:
            continue

        # Close loop if not already closed
        if pts[0] != pts[-1]:
            pts.append(pts[0])

        if rdp_epsilon > 0.0 and len(pts) > 4:
            pts = rdp_simplify_polygon(pts, epsilon=rdp_epsilon)
            if pts[0] != pts[-1]:
                pts.append(pts[0])

        if len(pts) >= 3:
            contours.append(pts)

    return contours


def contours_to_path_entity(
    contours: List[List[Tuple[float, float]]],
    layer_id: int = 0,
    name: str = "Boolean Path"
) -> Optional[PathEntity]:
    """
    Constructs a normalized PathEntity from a list of world-coordinate contours.
    """
    if not contours:
        return None

    min_x = float("inf")
    min_y = float("inf")
    for c in contours:
        for x, y in c:
            if x < min_x: min_x = x
            if y < min_y: min_y = y

    if math.isinf(min_x):
        return None

    # Normalize relative to (min_x, min_y)
    norm_contours = [
        [(x - min_x, y - min_y) for x, y in c]
        for c in contours
    ]

    return PathEntity(
        layer_id=layer_id,
        name=name,
        x=min_x,
        y=min_y,
        rotation=0.0,
        contours=norm_contours,
        closed=True
    )


class VectorBooleanEngine:
    """
    Core engine providing 2D CSG operations for LaserForge.
    """

    @staticmethod
    def weld(entities: List[LaserEntity], name: Optional[str] = None, rdp_epsilon: float = 0.02) -> Optional[PathEntity]:
        """
        Combines (unites) multiple vector entities into a single perimeter.
        Eliminates interior cut lines between overlapping shapes.
        """
        if not entities:
            return None

        valid_paths: List[Tuple[LaserEntity, QPainterPath]] = []
        for ent in entities:
            p = entity_to_painter_path(ent)
            if p and not p.isEmpty():
                valid_paths.append((ent, p))

        if not valid_paths:
            return None

        result_path = valid_paths[0][1]
        for _, p in valid_paths[1:]:
            result_path = result_path.united(p)

        contours = painter_path_to_contours(result_path, rdp_epsilon=rdp_epsilon)
        out_name = name or f"Weld ({valid_paths[0][0].name})"
        return contours_to_path_entity(contours, layer_id=valid_paths[0][0].layer_id, name=out_name)

    @staticmethod
    def subtract(entities: List[LaserEntity], name: Optional[str] = None, rdp_epsilon: float = 0.02) -> Optional[PathEntity]:
        """
        Subtracts all subsequent shapes from the first (base) shape (A ∖ B ∖ C ...).
        Used for cutouts, holes, and cookie-cutter carving.
        """
        if len(entities) < 2:
            return None

        base_ent = entities[0]
        base_path = entity_to_painter_path(base_ent)
        if not base_path or base_path.isEmpty():
            return None

        result_path = base_path
        for ent in entities[1:]:
            p = entity_to_painter_path(ent)
            if p and not p.isEmpty():
                result_path = result_path.subtracted(p)

        contours = painter_path_to_contours(result_path, rdp_epsilon=rdp_epsilon)
        out_name = name or f"Subtract ({base_ent.name})"
        return contours_to_path_entity(contours, layer_id=base_ent.layer_id, name=out_name)

    @staticmethod
    def intersect(entities: List[LaserEntity], name: Optional[str] = None, rdp_epsilon: float = 0.02) -> Optional[PathEntity]:
        """
        Computes the intersection of all selected shapes (A ∩ B ∩ C ...).
        Retains only areas shared by all shapes.
        """
        if len(entities) < 2:
            return None

        base_ent = entities[0]
        base_path = entity_to_painter_path(base_ent)
        if not base_path or base_path.isEmpty():
            return None

        result_path = base_path
        for ent in entities[1:]:
            p = entity_to_painter_path(ent)
            if not p or p.isEmpty():
                return None
            result_path = result_path.intersected(p)
            if result_path.isEmpty():
                return None

        contours = painter_path_to_contours(result_path, rdp_epsilon=rdp_epsilon)
        out_name = name or f"Intersect ({base_ent.name})"
        return contours_to_path_entity(contours, layer_id=base_ent.layer_id, name=out_name)
