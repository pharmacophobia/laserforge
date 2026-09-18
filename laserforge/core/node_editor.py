"""
LaserForge Interactive Vector Node Editor & Trim Scissor Engine.
Provides vertex-level CAD manipulation (move, insert, delete, smooth, split/break)
and interactive line trimming / snipping at intersections (Trim Scissor Tool).
"""

import copy
import math
from typing import List, Tuple, Optional, Dict, Any

from shapely.geometry import LineString, MultiLineString, Point, Polygon, MultiPolygon
from shapely.ops import split, unary_union

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity
)

Point2D = Tuple[float, float]


def point_dist(p1: Point2D, p2: Point2D) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def dist_to_segment(p: Point2D, a: Point2D, b: Point2D) -> Tuple[float, Point2D, float]:
    """Returns (distance, projected_point, t) from point p to segment a-b."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    denom = dx * dx + dy * dy
    if denom < 1e-9:
        return point_dist(p, a), a, 0.0
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / denom))
    proj = (a[0] + t * dx, a[1] + t * dy)
    return point_dist(p, proj), proj, t


class NodeEditorEngine:
    """Core mathematical engine for vertex manipulation and line trimming."""

    @staticmethod
    def entity_to_path_entity(entity: LaserEntity) -> PathEntity:
        """Converts basic geometric entities (Rect, Circle, Line) into editable PathEntities."""
        if isinstance(entity, PathEntity):
            return copy.deepcopy(entity)

        base_kwargs = {
            "id": entity.id,
            "layer_id": entity.layer_id,
            "name": entity.name,
            "x": entity.x,
            "y": entity.y,
            "rotation": entity.rotation,
            "locked": entity.locked,
            "override_speed": entity.override_speed,
            "override_power": entity.override_power
        }

        if isinstance(entity, RectEntity):
            w = entity.width
            h = entity.height
            rad = entity.corner_radius
            if rad > 0:
                rad = min(rad, w / 2.0, h / 2.0)
                pts: List[Point2D] = []
                # 4 corners with arcs
                corners = [
                    (w - rad, rad, 0, 90),
                    (rad, rad, 90, 180),
                    (rad, h - rad, 180, 270),
                    (w - rad, h - rad, 270, 360)
                ]
                for cx, cy, start_a, end_a in corners:
                    for ang_deg in range(start_a, end_a + 1, 15):
                        a = math.radians(ang_deg)
                        pts.append((round(cx + rad * math.cos(a), 3), round(cy - rad * math.sin(a), 3)))
                return PathEntity(**base_kwargs, contours=[pts], closed=True)
            else:
                pts = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
                return PathEntity(**base_kwargs, contours=[pts], closed=True)

        elif isinstance(entity, CircleEntity):
            pts = []
            rx = entity.radius_x
            ry = entity.radius_y
            for i in range(36):
                a = math.radians(i * 10)
                pts.append((round(rx * math.cos(a), 3), round(ry * math.sin(a), 3)))
            return PathEntity(**base_kwargs, contours=[pts], closed=True)

        elif isinstance(entity, LineEntity):
            pts = [(0.0, 0.0), (entity.x2 - entity.x, entity.y2 - entity.y)]
            return PathEntity(**base_kwargs, contours=[pts], closed=False)

        # Fallback empty path
        return PathEntity(**base_kwargs, contours=[], closed=False)

    @staticmethod
    def get_world_nodes(path_entity: PathEntity) -> List[Tuple[int, int, float, float]]:
        """Returns list of (contour_idx, node_idx, world_x, world_y)."""
        nodes = []
        for c_idx, contour in enumerate(path_entity.contours):
            for n_idx, (lx, ly) in enumerate(contour):
                wx = path_entity.x + lx
                wy = path_entity.y + ly
                nodes.append((c_idx, n_idx, wx, wy))
        return nodes

    @staticmethod
    def find_node_near(
        path_entity: PathEntity,
        world_x: float,
        world_y: float,
        hit_radius: float = 3.0
    ) -> Optional[Tuple[int, int]]:
        """Finds (contour_idx, node_idx) within hit_radius of given world coordinate."""
        best_match = None
        min_d = hit_radius
        for c_idx, n_idx, wx, wy in NodeEditorEngine.get_world_nodes(path_entity):
            d = math.hypot(world_x - wx, world_y - wy)
            if d < min_d:
                min_d = d
                best_match = (c_idx, n_idx)
        return best_match

    @staticmethod
    def move_node(
        path_entity: PathEntity,
        contour_idx: int,
        node_idx: int,
        new_world_x: float,
        new_world_y: float
    ):
        """Moves vertex to new world coordinate."""
        if 0 <= contour_idx < len(path_entity.contours):
            contour = path_entity.contours[contour_idx]
            if 0 <= node_idx < len(contour):
                local_x = new_world_x - path_entity.x
                local_y = new_world_y - path_entity.y
                contour[node_idx] = (round(local_x, 4), round(local_y, 4))
                path_entity.invalidate_bounds()

    @staticmethod
    def insert_node_near(
        path_entity: PathEntity,
        world_x: float,
        world_y: float,
        max_dist: float = 4.0
    ) -> Optional[Tuple[int, int]]:
        """
        Projects (world_x, world_y) onto the nearest line segment on the path
        and inserts a new vertex node. Returns (contour_idx, new_node_idx).
        """
        best_dist = max_dist
        best_candidate = None

        pt = (world_x - path_entity.x, world_y - path_entity.y)

        for c_idx, contour in enumerate(path_entity.contours):
            n = len(contour)
            if n < 2:
                continue
            seg_count = n if path_entity.closed else (n - 1)
            for i in range(seg_count):
                p1 = contour[i]
                p2 = contour[(i + 1) % n]
                d, proj, t = dist_to_segment(pt, p1, p2)
                if d < best_dist and 0.05 < t < 0.95:
                    best_dist = d
                    best_candidate = (c_idx, i + 1, proj)

        if best_candidate:
            c_idx, insert_idx, new_pt = best_candidate
            path_entity.contours[c_idx].insert(insert_idx, (round(new_pt[0], 4), round(new_pt[1], 4)))
            path_entity.invalidate_bounds()
            return (c_idx, insert_idx)

        return None

    @staticmethod
    def delete_node(
        path_entity: PathEntity,
        contour_idx: int,
        node_idx: int
    ) -> bool:
        """Deletes a node from a contour. Removes contour if collapsed."""
        if 0 <= contour_idx < len(path_entity.contours):
            contour = path_entity.contours[contour_idx]
            if 0 <= node_idx < len(contour):
                contour.pop(node_idx)
                if len(contour) < 2:
                    path_entity.contours.pop(contour_idx)
                path_entity.invalidate_bounds()
                return True
        return False

    @staticmethod
    def smooth_node(
        path_entity: PathEntity,
        contour_idx: int,
        node_idx: int
    ):
        """Laplacian smoothing on node vertex between its two neighbors."""
        if 0 <= contour_idx < len(path_entity.contours):
            contour = path_entity.contours[contour_idx]
            n = len(contour)
            if n > 2:
                prev_p = contour[(node_idx - 1) % n]
                next_p = contour[(node_idx + 1) % n]
                curr_p = contour[node_idx]
                smoothed = (
                    round(0.5 * curr_p[0] + 0.25 * (prev_p[0] + next_p[0]), 4),
                    round(0.5 * curr_p[1] + 0.25 * (prev_p[1] + next_p[1]), 4)
                )
                contour[node_idx] = smoothed
                path_entity.invalidate_bounds()

    @staticmethod
    def break_path_at_node(
        path_entity: PathEntity,
        contour_idx: int,
        node_idx: int
    ):
        """
        If closed: opens path with node_idx becoming start and end.
        If open: splits the contour into two distinct open contours.
        """
        if 0 <= contour_idx < len(path_entity.contours):
            contour = path_entity.contours[contour_idx]
            n = len(contour)
            if n < 2:
                return

            if path_entity.closed:
                # Open path starting and ending at node_idx
                new_contour = contour[node_idx:] + contour[:node_idx] + [contour[node_idx]]
                path_entity.contours[contour_idx] = new_contour
                path_entity.closed = False
            else:
                # Split open path into 2 open contours
                if 0 < node_idx < n - 1:
                    c1 = contour[:node_idx + 1]
                    c2 = contour[node_idx:]
                    path_entity.contours[contour_idx] = c1
                    path_entity.contours.insert(contour_idx + 1, c2)
            path_entity.invalidate_bounds()

    @staticmethod
    def trim_segment_at_point(
        target_entity: PathEntity,
        cutter_entities: List[LaserEntity],
        click_world_x: float,
        click_world_y: float,
        max_click_dist: float = 6.0
    ) -> Optional[PathEntity]:
        """
        Trim Scissor Tool:
        Finds all intersection points between target_entity and cutter_entities.
        Splits target_entity contours into segments at intersections,
        identifies the sub-segment closest to the clicked coordinate, and cuts it out!
        """
        if not target_entity.contours:
            return None

        # Build LineStrings for target contours in world coordinates
        target_lines: List[LineString] = []
        for c in target_entity.contours:
            if len(c) < 2:
                continue
            w_pts = [(target_entity.x + pt[0], target_entity.y + pt[1]) for pt in c]
            if target_entity.closed and len(w_pts) > 2:
                if w_pts[0] != w_pts[-1]:
                    w_pts.append(w_pts[0])
            target_lines.append(LineString(w_pts))

        if not target_lines:
            return None

        # Build geometry for cutters
        cutter_geoms = []
        for ce in cutter_entities:
            if ce.id == target_entity.id:
                continue
            pe = NodeEditorEngine.entity_to_path_entity(ce)
            for c in pe.contours:
                if len(c) >= 2:
                    cw_pts = [(pe.x + pt[0], pe.y + pt[1]) for pt in c]
                    if pe.closed and len(cw_pts) > 2 and cw_pts[0] != cw_pts[-1]:
                        cw_pts.append(cw_pts[0])
                    cutter_geoms.append(LineString(cw_pts))

        if not cutter_geoms:
            return None

        cutters_union = unary_union(cutter_geoms)
        click_pt = Point(click_world_x, click_world_y)

        # Process each target contour
        new_contours: List[List[Point2D]] = []
        trimmed_any = False

        for t_line in target_lines:
            # Find intersections with cutters
            inter = t_line.intersection(cutters_union)
            if inter.is_empty:
                # No intersection, retain contour
                coords = [(round(p[0] - target_entity.x, 4), round(p[1] - target_entity.y, 4)) for p in t_line.coords]
                new_contours.append(coords)
                continue

            # Split t_line with intersections
            split_res = split(t_line, inter)
            segments = []
            if hasattr(split_res, "geoms"):
                segments = list(split_res.geoms)
            else:
                segments = [split_res]

            # Find the segment closest to click_pt
            best_seg_idx = -1
            min_dist = max_click_dist

            for s_idx, seg in enumerate(segments):
                d = seg.distance(click_pt)
                if d < min_dist:
                    min_dist = d
                    best_seg_idx = s_idx

            if best_seg_idx >= 0:
                trimmed_any = True
                # Keep all segments except the clicked one
                for s_idx, seg in enumerate(segments):
                    if s_idx != best_seg_idx and len(seg.coords) >= 2:
                        local_coords = [
                            (round(p[0] - target_entity.x, 4), round(p[1] - target_entity.y, 4))
                            for p in seg.coords
                        ]
                        new_contours.append(local_coords)
            else:
                # Click wasn't close to any segment, retain all
                for seg in segments:
                    if len(seg.coords) >= 2:
                        local_coords = [
                            (round(p[0] - target_entity.x, 4), round(p[1] - target_entity.y, 4))
                            for p in seg.coords
                        ]
                        new_contours.append(local_coords)

        if not trimmed_any:
            return None

        result_entity = copy.deepcopy(target_entity)
        result_entity.contours = new_contours
        result_entity.closed = False  # Trimming breaks closed paths
        result_entity.invalidate_bounds()
        return result_entity
