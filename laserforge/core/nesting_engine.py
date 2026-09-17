"""
LaserForge 2D Nesting Optimizer Engine.
Provides high-efficiency 2D bin packing, rotational alignment (0°, 90°, 45° steps),
sheet margin clearance, part-to-part spacing, and cavity/hole nesting.
"""

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import shapely
from shapely.geometry import Polygon, MultiPolygon, box
from shapely import affinity

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)

Point2D = Tuple[float, float]


@dataclass
class NestItem:
    """Represents a shape or cluster of shapes to be nested."""
    id: str
    entity: LaserEntity
    polygon: Polygon
    area: float
    orig_x: float
    orig_y: float
    placed_x: float = 0.0
    placed_y: float = 0.0
    rotation_deg: float = 0.0
    nested_in_hole: bool = False


@dataclass
class NestingResult:
    """Output results of a 2D nesting optimization pass."""
    success: bool
    placed_items: List[NestItem]
    unplaced_items: List[NestItem]
    sheet_width: float
    sheet_height: float
    total_parts_area: float
    sheet_area: float
    efficiency_pct: float
    execution_time_ms: float = 0.0


class NestingEngine:
    """
    2D geometric packing and layout optimizer for sheet materials.
    """

    @staticmethod
    def entity_to_polygon(entity: LaserEntity) -> Optional[Polygon]:
        """Converts a LaserEntity into a valid Shapely Polygon."""
        try:
            if isinstance(entity, RectEntity):
                p = box(entity.x, entity.y, entity.x + entity.width, entity.y + entity.height)
                if entity.rotation != 0:
                    p = affinity.rotate(p, entity.rotation, origin='center')
                return p

            elif isinstance(entity, CircleEntity):
                rx, ry = entity.radius_x, entity.radius_y
                cx, cy = entity.x, entity.y
                # Approximate ellipse with 36 points
                pts = []
                for i in range(36):
                    ang = 2.0 * math.pi * i / 36.0
                    px = cx + rx * math.cos(ang)
                    py = cy + ry * math.sin(ang)
                    pts.append((px, py))
                p = Polygon(pts)
                if entity.rotation != 0:
                    p = affinity.rotate(p, entity.rotation, origin='center')
                return p

            elif isinstance(entity, LineEntity):
                # Thin buffered rectangle for open line
                p = box(min(entity.x, entity.x2), min(entity.y, entity.y2),
                        max(entity.x, entity.x2) + 0.1, max(entity.y, entity.y2) + 0.1)
                return p

            elif isinstance(entity, PathEntity):
                if not entity.contours or len(entity.contours[0]) < 3:
                    return None
                ext_pts = [(entity.x + px, entity.y + py) for px, py in entity.contours[0]]
                holes = []
                for hole_c in entity.contours[1:]:
                    if len(hole_c) >= 3:
                        holes.append([(entity.x + px, entity.y + py) for px, py in hole_c])
                p = Polygon(ext_pts, holes)
                if not p.is_valid:
                    p = p.buffer(0)
                if entity.rotation != 0:
                    p = affinity.rotate(p, entity.rotation, origin='center')
                return p

            elif isinstance(entity, TextEntity):
                b = box(entity.x, entity.y, entity.x + entity.width, entity.y + entity.height)
                if entity.rotation != 0:
                    b = affinity.rotate(b, entity.rotation, origin='center')
                return b

        except Exception:
            pass

        return None

    @classmethod
    def nest(
        cls,
        entities: List[LaserEntity],
        sheet_width: float,
        sheet_height: float,
        part_spacing: float = 2.0,
        sheet_margin: float = 5.0,
        rotations: List[float] = None,
        allow_hole_nesting: bool = True
    ) -> NestingResult:
        """
        Packs a list of vector entities onto a target sheet boundary.

        Parameters:
            entities: Laser entities to pack.
            sheet_width: Stock material width in mm.
            sheet_height: Stock material height in mm.
            part_spacing: Minimum clearance gap between adjacent parts (mm).
            sheet_margin: Border padding inside sheet boundaries (mm).
            rotations: Allowed rotation angles in degrees (default [0, 90, 180, 270]).
            allow_hole_nesting: If True, nest smaller parts inside holes of larger parts.

        Returns:
            NestingResult with placed positions, rotations, and packing metrics.
        """
        import time
        t_start = time.perf_counter()

        if rotations is None:
            rotations = [0.0, 90.0, 180.0, 270.0]

        # Convert entities into NestItems
        items: List[NestItem] = []
        for ent in entities:
            poly = cls.entity_to_polygon(ent)
            if poly is not None and poly.area > 1e-4:
                items.append(NestItem(
                    id=ent.id,
                    entity=ent,
                    polygon=poly,
                    area=poly.area,
                    orig_x=ent.x,
                    orig_y=ent.y
                ))

        # Sort items descending by area (largest parts placed first)
        items.sort(key=lambda item: item.area, reverse=True)

        usable_min_x = sheet_margin
        usable_min_y = sheet_margin
        usable_max_x = sheet_width - sheet_margin
        usable_max_y = sheet_height - sheet_margin

        usable_sheet_box = box(usable_min_x, usable_min_y, usable_max_x, usable_max_y)

        placed_items: List[NestItem] = []
        unplaced_items: List[NestItem] = []

        # List of (placed_buffered_poly, NestItem)
        placed_geoms: List[Tuple[Polygon, NestItem]] = []

        # List of available internal hole polygons: [(hole_poly, parent_item)]
        available_holes: List[Tuple[Polygon, NestItem]] = []

        half_spacing = max(0.1, part_spacing / 2.0)

        for item in items:
            placed = False
            best_pos: Optional[Tuple[float, float, float, Polygon]] = None
            best_score = float('inf')  # Minimize y * 1000 + x (Bottom-Left heuristic)

            # 1. Try nesting inside internal holes of already placed shapes (if enabled)
            if allow_hole_nesting and available_holes:
                for hole_poly, parent in available_holes:
                    for rot in rotations:
                        cand = item.polygon
                        if rot != 0:
                            cand = affinity.rotate(cand, rot, origin='center')

                        # Center candidate in hole
                        h_minx, h_miny, h_maxx, h_maxy = hole_poly.bounds
                        c_minx, c_miny, c_maxx, c_maxy = cand.bounds
                        shift_x = (h_minx + h_maxx) / 2.0 - (c_minx + c_maxx) / 2.0
                        shift_y = (h_miny + h_maxy) / 2.0 - (c_miny + c_maxy) / 2.0
                        shifted = affinity.translate(cand, shift_x, shift_y)
                        shifted_buf = shifted.buffer(part_spacing * 0.999)

                        # Must be strictly contained inside the hole
                        if hole_poly.contains(shifted_buf):
                            # Check no overlap with existing placed items
                            collides = False
                            for p_geom, _ in placed_geoms:
                                pb = p_geom.bounds
                                sb = shifted_buf.bounds
                                if not (sb[0] > pb[2] or sb[2] < pb[0] or sb[1] > pb[3] or sb[3] < pb[1]):
                                    if shifted_buf.intersects(p_geom):
                                        collides = True
                                        break
                            if not collides:
                                item.placed_x = item.orig_x + shift_x
                                item.placed_y = item.orig_y + shift_y
                                item.rotation_deg = rot
                                item.nested_in_hole = True
                                placed_items.append(item)
                                placed_geoms.append((shifted, item))
                                placed = True
                                break
                    if placed:
                        break

            if placed:
                continue

            # 2. Main Sheet Bottom-Left-Fill Placement
            # Generate candidate placement points: start at origin and along bounds of placed items
            cand_pts: List[Point2D] = [(usable_min_x, usable_min_y)]
            for p_geom, _ in placed_geoms:
                b = p_geom.bounds
                cand_pts.append((b[2] + part_spacing, usable_min_y))
                cand_pts.append((usable_min_x, b[3] + part_spacing))
                cand_pts.append((b[2] + part_spacing, b[1]))
                cand_pts.append((b[0], b[3] + part_spacing))

            # Deduplicate and sort candidate points by y, then x
            cand_pts = list(set(cand_pts))
            cand_pts.sort(key=lambda pt: (pt[1], pt[0]))

            for rot in rotations:
                cand_geom = item.polygon
                if rot != 0:
                    cand_geom = affinity.rotate(cand_geom, rot, origin='center')

                c_minx, c_miny, c_maxx, c_maxy = cand_geom.bounds
                w = c_maxx - c_minx
                h = c_maxy - c_miny

                # Quick dimension check
                if w > (usable_max_x - usable_min_x) or h > (usable_max_y - usable_min_y):
                    continue

                for cx, cy in cand_pts:
                    # Target top-right bounds
                    tx2 = cx + w
                    ty2 = cy + h
                    if tx2 > usable_max_x or ty2 > usable_max_y:
                        continue

                    # Score heuristic: primary Y (pack tightly to bottom), secondary X (left)
                    score = cy * 10000.0 + cx
                    if score >= best_score:
                        continue

                    # Translate candidate polygon so its min bounds align at (cx, cy)
                    dx = cx - c_minx
                    dy = cy - c_miny
                    shifted = affinity.translate(cand_geom, dx, dy)
                    shifted_buf = shifted.buffer(part_spacing * 0.999)

                    # Collision detection against all placed shapes
                    collides = False
                    for p_geom, _ in placed_geoms:
                        # Fast AABB rejection
                        pb_bounds = p_geom.bounds
                        sb_bounds = shifted_buf.bounds
                        if (sb_bounds[0] > pb_bounds[2] or sb_bounds[2] < pb_bounds[0] or
                            sb_bounds[1] > pb_bounds[3] or sb_bounds[3] < pb_bounds[1]):
                            continue
                        if shifted_buf.intersects(p_geom):
                            collides = True
                            break

                    if not collides:
                        best_score = score
                        best_pos = (dx, dy, rot, shifted)
                        break  # Found best valid candidate point for this rotation

            if best_pos is not None:
                dx, dy, rot, shifted = best_pos
                item.placed_x = item.orig_x + dx
                item.placed_y = item.orig_y + dy
                item.rotation_deg = rot
                placed_items.append(item)
                placed_geoms.append((shifted, item))

                # Collect internal holes from this item for future cavity nesting
                if allow_hole_nesting:
                    shifted_original = affinity.translate(item.polygon, dx, dy)
                    if rot != 0:
                        shifted_original = affinity.rotate(shifted_original, rot, origin='center')
                    if isinstance(shifted_original, Polygon) and shifted_original.interiors:
                        for interior in shifted_original.interiors:
                            hole_poly = Polygon(interior)
                            if hole_poly.area > (part_spacing * 2.0) ** 2:
                                available_holes.append((hole_poly, item))
            else:
                unplaced_items.append(item)

        t_elapsed = (time.perf_counter() - t_start) * 1000.0
        total_parts_area = sum(it.area for it in placed_items)
        sheet_area = sheet_width * sheet_height
        efficiency_pct = (total_parts_area / sheet_area) * 100.0 if sheet_area > 0 else 0.0

        return NestingResult(
            success=len(unplaced_items) == 0,
            placed_items=placed_items,
            unplaced_items=unplaced_items,
            sheet_width=sheet_width,
            sheet_height=sheet_height,
            total_parts_area=total_parts_area,
            sheet_area=sheet_area,
            efficiency_pct=efficiency_pct,
            execution_time_ms=t_elapsed
        )
