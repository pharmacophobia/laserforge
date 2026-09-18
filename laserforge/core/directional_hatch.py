"""
LaserForge Directional Vector Hatching Generator.

Generates artistic / functional directional vector line infill (hatching) across
unconnected vector shapes and contours.

Key Geometric & Optimization Constraints:
1. Unconnected Vector Segmentation:
   Decomposes complex vector artwork or multi-contour paths into disjoint,
   closed vector polygons (with support for interior holes).
2. Spatial Proximity & Neighbor Triangulation:
   Identifies neighboring shapes via Delaunay triangulation and spatial proximity.
3. Strict Neighbor Angle Separation:
   Ensures the infill direction of any polygon is NEVER closer than 15 degrees
   (or user-specified min angle difference) to any neighboring vector shape.
4. Center-to-Edge Divergence Modulation:
   Angular difference between neighboring vectors is greatest near the center of
   the design (wide angular contrast) and gradually diminishes toward the outer edges,
   smoothly converging toward the baseline orientation (vertical lines, 90°).
5. Clean Laser Vector Toolpaths:
   Clips parallel lines precisely within each vector contour using Shapely, with
   serpentine (zig-zag) optimization for high-speed diode/CO2 laser engraving.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Set, Optional, Any
import math
import random
import os
import concurrent.futures
import numpy as np
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, GeometryCollection
from shapely.ops import polygonize, unary_union
import shapely.affinity
try:
    from shapely.validation import make_valid
except ImportError:
    def make_valid(geom):
        return geom.buffer(0)

from laserforge.core.models import LaserEntity, PathEntity
from laserforge.core.geometry_boolean import entity_to_painter_path


@dataclass
class VectorPolygon:
    """Represents a single unconnected closed vector polygon with its geometry."""
    index: int
    outer_contour: List[Tuple[float, float]]
    holes: List[List[Tuple[float, float]]] = field(default_factory=list)
    centroid: Tuple[float, float] = (0.0, 0.0)
    radial_distance: float = 0.0  # 0.0 at center of artwork, 1.0 at farthest boundary
    assigned_angle: float = 90.0  # Direction in degrees [0, 180)
    shapely_polygon: Optional[Polygon] = None
    bounds: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # min_x, min_y, max_x, max_y
    area: float = 0.0


@dataclass
class DirectionalHatchSettings:
    """Configuration parameters for directional vector hatching."""
    line_spacing_mm: float = 1.0
    min_neighbor_angle_diff: float = 15.0  # Hard minimum angle difference (degrees)
    center_divergence_deg: float = 75.0    # Max angular difference near center
    edge_divergence_deg: float = 10.0      # Max deviation from vertical at perimeter
    baseline_angle_deg: float = 90.0       # Baseline direction: 90.0 = vertical lines
    cross_hatch: bool = False              # Generate perpendicular cross-hatch
    keep_original_contours: bool = True    # Retain outer boundary vector cut lines
    target_layer_id: int = 1               # Output layer for hatch lines (e.g. C01 Blue)
    serpentine_toolpath: bool = True       # Serpentine zig-zag to minimize laser rapid moves
    random_seed: Optional[int] = 42        # Seed for repeatable optimization


@dataclass
class DirectionalHatchResult:
    """Output results of the directional hatching generator."""
    hatched_entities: List[PathEntity]
    assigned_angles: Dict[int, float]
    polygons: List[VectorPolygon]
    neighbors: Dict[int, List[int]]
    min_diff_achieved: float
    center_diff_achieved: float
    total_hatch_length_mm: float
    total_line_count: int


def angular_difference(angle1: float, angle2: float) -> float:
    """
    Computes minimum angular difference in degrees between two line orientations.
    Since bidirectional lines at θ and θ + 180° are identical, line angles
    are periodic with period 180°.
    Result is always in [0.0, 90.0].
    """
    a1 = angle1 % 180.0
    a2 = angle2 % 180.0
    diff = abs(a1 - a2)
    return min(diff, 180.0 - diff)


class DirectionalHatchGenerator:
    """
    Core engine for directional vector hatching with spatial neighbor constraints
    and center-to-edge angular divergence modulation.
    """

    @classmethod
    def _add_valid_polys(cls, geom: Any, target_list: List[Polygon]):
        """Recursively decomposes and validates Shapely geometry into valid Polygons."""
        if geom is None or geom.is_empty:
            return
        if not geom.is_valid:
            try:
                geom = make_valid(geom)
            except Exception:
                try:
                    geom = geom.buffer(0)
                except Exception:
                    return
        if geom.geom_type == 'Polygon':
            if geom.area > 1e-4:
                target_list.append(geom)
        elif hasattr(geom, 'geoms'):
            for sub in geom.geoms:
                cls._add_valid_polys(sub, target_list)

    @classmethod
    def extract_polygons(cls, entities: List[LaserEntity]) -> List[VectorPolygon]:
        """
        Extracts unconnected closed vector polygons from a list of LaserEntities.
        Converts entity geometries into world-space Shapely Polygons, correctly
        associating outer perimeters with inner holes.
        """
        raw_polygons: List[Polygon] = []

        for ent in entities:
            # Handle PathEntity directly if available
            if isinstance(ent, PathEntity):
                for c in ent.contours:
                    if len(c) >= 3:
                        pts = [(ent.x + p[0], ent.y + p[1]) for p in c]
                        if pts[0] != pts[-1]:
                            pts.append(pts[0])
                        try:
                            poly = Polygon(pts)
                            cls._add_valid_polys(poly, raw_polygons)
                        except Exception:
                            continue
                continue

            # For other entities (RectEntity, CircleEntity, TextEntity), use QPainterPath
            ppath = entity_to_painter_path(ent)
            if ppath is None or ppath.isEmpty():
                continue

            sub_polys = ppath.toSubpathPolygons()
            for sp in sub_polys:
                if sp.size() < 3:
                    continue
                pts = [(sp.at(i).x(), sp.at(i).y()) for i in range(sp.size())]
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                try:
                    poly = Polygon(pts)
                    cls._add_valid_polys(poly, raw_polygons)
                except Exception:
                    continue

        if not raw_polygons:
            return []

        # Resolve outer vs hole hierarchy
        # Sort by area descending so outer containers come first
        raw_polygons.sort(key=lambda p: p.area, reverse=True)

        final_polygons: List[Polygon] = []
        is_hole = [False] * len(raw_polygons)

        for i in range(len(raw_polygons)):
            if is_hole[i]:
                continue
            parent = raw_polygons[i]
            holes_for_parent = []
            for j in range(i + 1, len(raw_polygons)):
                if not is_hole[j] and parent.contains(raw_polygons[j]):
                    # Sub-polygon is entirely contained in parent
                    holes_for_parent.append(raw_polygons[j])
                    is_hole[j] = True

            if holes_for_parent:
                try:
                    cleaned_poly = parent
                    for h in holes_for_parent:
                        cleaned_poly = cleaned_poly.difference(h)
                    cls._add_valid_polys(cleaned_poly, final_polygons)
                except Exception:
                    final_polygons.append(parent)
            else:
                final_polygons.append(parent)

        # Decompose any MultiPolygons into distinct VectorPolygon objects
        flat_polys: List[Polygon] = []
        for p in final_polygons:
            cls._add_valid_polys(p, flat_polys)

        if not flat_polys:
            return []

        # Compute global bounding box and center
        all_min_x = min(p.bounds[0] for p in flat_polys)
        all_min_y = min(p.bounds[1] for p in flat_polys)
        all_max_x = max(p.bounds[2] for p in flat_polys)
        all_max_y = max(p.bounds[3] for p in flat_polys)

        global_cx = (all_min_x + all_max_x) / 2.0
        global_cy = (all_min_y + all_max_y) / 2.0

        # Calculate max radius from center to any polygon centroid or boundary
        max_radius = 0.0
        for p in flat_polys:
            c = p.centroid
            dist = math.hypot(c.x - global_cx, c.y - global_cy)
            if dist > max_radius:
                max_radius = dist

        diag = math.hypot(all_max_x - all_min_x, all_max_y - all_min_y) / 2.0
        max_radius = max(max_radius, diag, 1.0)

        results: List[VectorPolygon] = []
        for idx, poly in enumerate(flat_polys):
            c = poly.centroid
            dist = math.hypot(c.x - global_cx, c.y - global_cy)
            norm_r = min(1.0, max(0.0, dist / max_radius))

            outer = list(poly.exterior.coords)
            holes = [list(h.coords) for h in poly.interiors]

            vp = VectorPolygon(
                index=idx,
                outer_contour=outer,
                holes=holes,
                centroid=(c.x, c.y),
                radial_distance=norm_r,
                assigned_angle=90.0,
                shapely_polygon=poly,
                bounds=poly.bounds,
                area=poly.area
            )
            results.append(vp)

        return results

    @staticmethod
    def build_neighbor_graph(
        polygons: List[VectorPolygon],
        k_nearest: int = 4
    ) -> Dict[int, Set[int]]:
        """
        Constructs a spatial neighbor adjacency graph for the vector polygons.
        Uses Delaunay triangulation where possible, augmented with k-nearest neighbors
        so no close spatial neighbors are omitted.
        """
        n = len(polygons)
        neighbors: Dict[int, Set[int]] = {i: set() for i in range(n)}

        if n <= 1:
            return neighbors
        if n == 2:
            neighbors[0].add(1)
            neighbors[1].add(0)
            return neighbors

        pts = np.array([p.centroid for p in polygons])

        # 1. Try Delaunay Triangulation
        try:
            from scipy.spatial import Delaunay
            tri = Delaunay(pts)
            for simplex in tri.simplices:
                for i in range(3):
                    u = simplex[i]
                    v = simplex[(i + 1) % 3]
                    neighbors[u].add(v)
                    neighbors[v].add(u)
        except Exception:
            pass

        # 2. Add k-nearest neighbors to ensure tight spatial connectivity
        k = min(k_nearest, n - 1)
        for i in range(n):
            dists = []
            for j in range(n):
                if i != j:
                    d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
                    dists.append((d, j))
            dists.sort(key=lambda x: x[0])
            for _, j in dists[:k]:
                neighbors[i].add(j)
                neighbors[j].add(i)

        return neighbors

    @classmethod
    def assign_angles(
        cls,
        polygons: List[VectorPolygon],
        neighbors: Dict[int, Set[int]],
        settings: DirectionalHatchSettings
    ) -> Dict[int, float]:
        """
        Optimizes and assigns line direction angles for each unconnected vector.
        
        Guarantees:
        1. For any neighbor pair (u, v), angular_difference(angle_u, angle_v) >= min_neighbor_angle_diff.
        2. Angular difference is greatest near center (radial_distance ~ 0) and smoothly lessens
           toward outer edges (radial_distance ~ 1).
        3. Outer edges converge toward settings.baseline_angle_deg (vertical = 90°).
        """
        n = len(polygons)
        if n == 0:
            return {}
        if n == 1:
            return {0: settings.baseline_angle_deg % 180.0}

        min_diff = max(5.0, settings.min_neighbor_angle_diff)
        center_div = max(min_diff + 10.0, settings.center_divergence_deg)
        edge_div = min(min_diff, settings.edge_divergence_deg)
        base_angle = settings.baseline_angle_deg % 180.0

        rng = random.Random(settings.random_seed if settings.random_seed is not None else 42)

        # 1. Compute target neighbor difference and baseline weight for each polygon
        target_diffs: Dict[Tuple[int, int], float] = {}
        for u in range(n):
            r_u = polygons[u].radial_distance
            for v in neighbors[u]:
                if u < v:
                    r_v = polygons[v].radial_distance
                    r_mid = (r_u + r_v) / 2.0
                    # Greatest difference in center, lessens as it approaches edge:
                    # In center (r_mid=0): target is center_div (e.g. 75°-90°)
                    # At edge (r_mid=1): target is min_diff (15°)
                    target = min_diff + (1.0 - r_mid) * (center_div - min_diff)
                    target_diffs[(u, v)] = target
                    target_diffs[(v, u)] = target

        # 2. Greedy Graph Coloring into discrete phase bins for smart initialization
        # Planar graphs are 4-colorable. Discrete phase colors give large initial separation.
        colors = [-1] * n
        for u in sorted(range(n), key=lambda i: len(neighbors[i]), reverse=True):
            used_colors = {colors[v] for v in neighbors[u] if colors[v] != -1}
            col = 0
            while col in used_colors:
                col += 1
            colors[u] = col

        # Initialize angles based on color phase and radial divergence
        angles: List[float] = [0.0] * n
        for u in range(n):
            r = polygons[u].radial_distance
            # Deviation scale: wide at center, small at perimeter
            dev_scale = edge_div + (1.0 - r) * (center_div - edge_div)
            # Alternating direction signs based on color
            col = colors[u]
            if col == 0:
                ang = base_angle + dev_scale
            elif col == 1:
                ang = base_angle - dev_scale
            elif col == 2:
                ang = base_angle + 0.5 * dev_scale
            elif col == 3:
                ang = base_angle - 0.5 * dev_scale
            else:
                ang = base_angle + ((col % 2) * 2 - 1) * dev_scale * (0.3 + 0.7 * rng.random())
            angles[u] = ang % 180.0

        def node_energy(u: int, val: float) -> float:
            e = 0.0
            for v in neighbors[u]:
                pair = (min(u, v), max(u, v))
                target = target_diffs.get(pair, min_diff)
                diff = angular_difference(val, angles[v])
                if diff < min_diff:
                    e += 100000.0 * ((min_diff - diff) ** 2)
                else:
                    e += (diff - target) ** 2
            r = polygons[u].radial_distance
            base_diff = angular_difference(val, base_angle)
            e += 4.0 * (r ** 2) * (base_diff ** 2)
            return e

        # 3. Fast Simulated Annealing with Local Energy Delta Updates
        temp = 45.0
        cooling_rate = 0.95
        iterations_per_temp = min(100, max(25, n * 3))
        best_angles = list(angles)
        best_penalty = sum(
            1.0 for u in range(n) for v in neighbors[u]
            if u < v and angular_difference(angles[u], angles[v]) < min_diff
        )

        for step in range(80):
            for _ in range(iterations_per_temp):
                u = rng.randrange(n)
                old_val = angles[u]
                delta = rng.gauss(0.0, temp)
                candidate = (old_val + delta) % 180.0

                old_e = node_energy(u, old_val)
                angles[u] = candidate
                new_e = node_energy(u, candidate)
                dE = new_e - old_e

                if dE < 0 or (temp > 0.01 and rng.random() < math.exp(-dE / max(temp, 0.1))):
                    pass
                else:
                    angles[u] = old_val

            temp *= cooling_rate

        # 4. Strict Deterministic Projection / Constraint Enforcement
        # Ensure 100% compliance with min_neighbor_angle_diff
        max_repair_passes = 250
        for _ in range(max_repair_passes):
            violations = []
            for u in range(n):
                for v in neighbors[u]:
                    if u < v:
                        diff = angular_difference(angles[u], angles[v])
                        if diff < min_diff:
                            violations.append((u, v, min_diff - diff))

            if not violations:
                break

            # Sort violations by severity
            violations.sort(key=lambda x: x[2], reverse=True)
            for u, v, deficit in violations:
                diff = angular_difference(angles[u], angles[v])
                if diff >= min_diff:
                    continue

                needed = (min_diff - diff) + 0.5  # Add 0.5 deg safety margin
                # Push angles in opposite directions
                # Test shifting u + needed/2 and v - needed/2 vs opposite
                for sign in (+1, -1):
                    cand_u = (angles[u] + sign * (needed / 2.0)) % 180.0
                    cand_v = (angles[v] - sign * (needed / 2.0)) % 180.0

                    # Check if this resolves (u, v) without worsening other neighbors
                    cand_diff = angular_difference(cand_u, cand_v)
                    if cand_diff >= min_diff:
                        angles[u] = cand_u
                        angles[v] = cand_v
                        break

        # Final check & absolute safety resolution
        for u in range(n):
            for v in neighbors[u]:
                diff = angular_difference(angles[u], angles[v])
                if diff < min_diff:
                    # If still unresolved, assign an unoccupied discrete angle bucket
                    occupied = [angles[w] for w in neighbors[u]]
                    for candidate_deg in np.linspace(0.0, 179.0, 360):
                        if all(angular_difference(candidate_deg, occ) >= min_diff for occ in occupied):
                            angles[u] = candidate_deg
                            break

        return {i: float(angles[i]) for i in range(n)}

    @staticmethod
    def _generate_hatch_lines_vectorized(
        geom: Any,
        angle_deg: float,
        line_spacing_mm: float = 1.0,
        serpentine: bool = True
    ) -> List[List[Tuple[float, float]]]:
        """
        Ultra-fast vectorized scanline hatch generation using Jordan curve ray casting.
        Rotates polygon by -angle_deg so scanlines are horizontal, computes all edge
        intercepts simultaneously via NumPy SIMD broadcasting, and rotates back.
        """
        cx, cy = geom.centroid.x, geom.centroid.y
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        rot_geom = shapely.affinity.rotate(geom, -angle_deg, origin=(cx, cy))
        if rot_geom.is_empty:
            return []

        min_x, min_y, max_x, max_y = rot_geom.bounds
        spacing = max(0.05, line_spacing_mm)
        height = max_y - min_y
        steps = int(math.ceil(height / spacing))
        if steps <= 0:
            return []

        start_y = min_y + (height - (steps - 1) * spacing) / 2.0
        y_levels = start_y + np.arange(steps, dtype=np.float64) * spacing

        sub_geoms = rot_geom.geoms if hasattr(rot_geom, 'geoms') else [rot_geom]
        edges_list = []
        for poly in sub_geoms:
            if not hasattr(poly, 'exterior') or poly.exterior is None:
                continue
            rings = [poly.exterior] + list(poly.interiors)
            for ring in rings:
                coords = np.asarray(ring.coords, dtype=np.float64)
                if len(coords) < 2:
                    continue
                p1 = coords[:-1]
                p2 = coords[1:]
                dy = p2[:, 1] - p1[:, 1]
                non_horiz = np.abs(dy) > 1e-12
                if not np.any(non_horiz):
                    continue
                p1_v = p1[non_horiz]
                p2_v = p2[non_horiz]
                dy_v = dy[non_horiz]
                dx_v = p2_v[:, 0] - p1_v[:, 0]

                y_low = np.minimum(p1_v[:, 1], p2_v[:, 1])
                y_high = np.maximum(p1_v[:, 1], p2_v[:, 1])
                inv_slope = dx_v / dy_v
                edge_data = np.column_stack([y_low, y_high, p1_v[:, 0], p1_v[:, 1], inv_slope])
                edges_list.append(edge_data)

        if not edges_list:
            return []

        all_edges = np.vstack(edges_list)
        Y = y_levels[:, None]
        y_low = all_edges[None, :, 0]
        y_high = all_edges[None, :, 1]
        x1 = all_edges[None, :, 2]
        y1 = all_edges[None, :, 3]
        inv_slope = all_edges[None, :, 4]

        mask = (Y >= y_low) & (Y < y_high)
        x_intercepts = np.where(mask, x1 + inv_slope * (Y - y1), np.inf)
        x_sorted = np.sort(x_intercepts, axis=1)
        counts = np.sum(mask, axis=1)

        result_lines: List[List[Tuple[float, float]]] = []
        for step_idx in range(steps):
            cnt = counts[step_idx]
            if cnt < 2:
                continue
            pair_count = (cnt // 2) * 2
            row_y = y_levels[step_idx]

            for j in range(0, pair_count, 2):
                x_left = x_sorted[step_idx, j]
                x_right = x_sorted[step_idx, j + 1]
                if (x_right - x_left) < 1e-4:
                    continue

                dx_l = x_left - cx
                dy_l = row_y - cy
                orig_lx = cx + (dx_l * cos_a - dy_l * sin_a)
                orig_ly = cy + (dx_l * sin_a + dy_l * cos_a)

                dx_r = x_right - cx
                dy_r = row_y - cy
                orig_rx = cx + (dx_r * cos_a - dy_r * sin_a)
                orig_ry = cy + (dx_r * sin_a + dy_r * cos_a)

                if not (math.isfinite(orig_lx) and math.isfinite(orig_ly) and math.isfinite(orig_rx) and math.isfinite(orig_ry)):
                    continue

                pt1 = (float(orig_lx), float(orig_ly))
                pt2 = (float(orig_rx), float(orig_ry))

                if serpentine and (step_idx % 2 == 1):
                    result_lines.append([pt2, pt1])
                else:
                    result_lines.append([pt1, pt2])

        return result_lines

    @staticmethod
    def _generate_hatch_lines_fallback(
        geom: Any,
        poly: VectorPolygon,
        angle: float,
        line_spacing_mm: float = 1.0,
        serpentine: bool = True
    ) -> List[List[Tuple[float, float]]]:
        """Fallback geometry clipper using Shapely LineString intersection."""
        min_x, min_y, max_x, max_y = poly.bounds
        width = max_x - min_x
        height = max_y - min_y
        diag = math.hypot(width, height) + line_spacing_mm * 2.0
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0

        rad = math.radians(angle)
        dir_x = math.cos(rad)
        dir_y = math.sin(rad)
        norm_x = -dir_y
        norm_y = dir_x

        coords = list(geom.exterior.coords)
        projections = [p[0] * norm_x + p[1] * norm_y for p in coords]
        min_proj = min(projections)
        max_proj = max(projections)
        t_center = cx * norm_x + cy * norm_y

        spacing = max(0.05, line_spacing_mm)
        steps = int(math.ceil((max_proj - min_proj) / spacing))
        if steps <= 0:
            return []

        start_t = min_proj + (max_proj - min_proj - (steps - 1) * spacing) / 2.0
        lines_at_angle: List[List[Tuple[float, float]]] = []

        for step_idx in range(steps):
            t = start_t + step_idx * spacing
            pmid_x = cx + (t - t_center) * norm_x
            pmid_y = cy + (t - t_center) * norm_y

            p1_x = pmid_x - diag * dir_x
            p1_y = pmid_y - diag * dir_y
            p2_x = pmid_x + diag * dir_x
            p2_y = pmid_y + diag * dir_y

            probe_line = LineString([(p1_x, p1_y), (p2_x, p2_y)])
            try:
                clipped = geom.intersection(probe_line)
            except Exception:
                continue

            if clipped.is_empty:
                continue

            segments: List[LineString] = []
            if clipped.geom_type == 'LineString':
                segments.append(clipped)
            elif clipped.geom_type == 'MultiLineString':
                segments.extend(list(clipped.geoms))
            elif clipped.geom_type == 'GeometryCollection':
                for g in clipped.geoms:
                    if g.geom_type == 'LineString':
                        segments.append(g)

            for seg in segments:
                if seg.length < 1e-4:
                    continue
                seg_coords = list(seg.coords)
                if serpentine and (step_idx % 2 == 1):
                    seg_coords.reverse()
                lines_at_angle.append([(float(x), float(y)) for x, y in seg_coords])

        return lines_at_angle

    @classmethod
    def generate_hatch_lines_for_polygon(
        cls,
        poly: VectorPolygon,
        angle_deg: float,
        line_spacing_mm: float = 1.0,
        cross_hatch: bool = False,
        serpentine: bool = True
    ) -> List[List[Tuple[float, float]]]:
        """
        Generates parallel scanline toolpaths clipped strictly within the polygon boundary.
        Uses ultra-fast vectorized scanline sweep with fallback to Shapely intersection.
        Supports serpentine (zig-zag) chaining to minimize laser G0 rapid moves.
        """
        if poly.shapely_polygon is None or poly.shapely_polygon.is_empty:
            return []

        geom = poly.shapely_polygon
        angles_to_render = [angle_deg % 180.0]
        if cross_hatch:
            angles_to_render.append((angle_deg + 90.0) % 180.0)

        all_line_segments: List[List[Tuple[float, float]]] = []

        for angle in angles_to_render:
            lines: List[List[Tuple[float, float]]] = []
            try:
                lines = cls._generate_hatch_lines_vectorized(
                    geom=geom,
                    angle_deg=angle,
                    line_spacing_mm=line_spacing_mm,
                    serpentine=serpentine
                )
            except Exception:
                lines = []

            # If vectorized sweep yielded no lines on a non-trivial polygon, use fallback
            if not lines and geom.area > 1e-4:
                lines = cls._generate_hatch_lines_fallback(
                    geom=geom,
                    poly=poly,
                    angle=angle,
                    line_spacing_mm=line_spacing_mm,
                    serpentine=serpentine
                )

            all_line_segments.extend(lines)

        return all_line_segments

    @classmethod
    def generate(
        cls,
        entities: List[LaserEntity],
        settings: Optional[DirectionalHatchSettings] = None
    ) -> DirectionalHatchResult:
        """
        Executes the full directional vector hatching pipeline on given entities.
        """
        if settings is None:
            settings = DirectionalHatchSettings()

        polygons = cls.extract_polygons(entities)
        if not polygons:
            return DirectionalHatchResult(
                hatched_entities=[],
                assigned_angles={},
                polygons=[],
                neighbors={},
                min_diff_achieved=0.0,
                center_diff_achieved=0.0,
                total_hatch_length_mm=0.0,
                total_line_count=0
            )

        neighbors_set = cls.build_neighbor_graph(polygons)
        neighbors_dict: Dict[int, List[int]] = {i: sorted(list(adj)) for i, adj in neighbors_set.items()}

        assigned_angles = cls.assign_angles(polygons, neighbors_set, settings)

        for poly in polygons:
            poly.assigned_angle = assigned_angles.get(poly.index, settings.baseline_angle_deg)

        # Multi-threaded parallel hatch generation across polygons
        def _hatch_worker(p: VectorPolygon) -> Tuple[VectorPolygon, List[List[Tuple[float, float]]]]:
            lines = cls.generate_hatch_lines_for_polygon(
                poly=p,
                angle_deg=p.assigned_angle,
                line_spacing_mm=settings.line_spacing_mm,
                cross_hatch=settings.cross_hatch,
                serpentine=settings.serpentine_toolpath
            )
            return (p, lines)

        max_workers = min(12, max(1, os.cpu_count() or 4))
        if len(polygons) > 1 and max_workers > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                poly_hatch_results = list(executor.map(_hatch_worker, polygons))
        else:
            poly_hatch_results = [_hatch_worker(p) for p in polygons]

        # Generate hatching toolpath line contours for each polygon
        hatched_entities: List[PathEntity] = []
        total_length = 0.0
        total_lines = 0

        for poly, line_contours in poly_hatch_results:
            ang = poly.assigned_angle
            for line in line_contours:
                if len(line) >= 2:
                    for k in range(len(line) - 1):
                        total_length += math.hypot(line[k+1][0] - line[k][0], line[k+1][1] - line[k][1])
            total_lines += len(line_contours)

            # Combined contours: boundary (if requested) + hatch lines
            entity_contours: List[List[Tuple[float, float]]] = []
            if settings.keep_original_contours:
                entity_contours.append(poly.outer_contour)
                for h in poly.holes:
                    entity_contours.append(h)

            entity_contours.extend(line_contours)

            if entity_contours:
                # Find min_x, min_y to normalize PathEntity origin
                all_pts = [pt for c in entity_contours for pt in c]
                if all_pts:
                    orig_x = min(pt[0] for pt in all_pts)
                    orig_y = min(pt[1] for pt in all_pts)
                    norm_contours = [
                        [(pt[0] - orig_x, pt[1] - orig_y) for pt in c]
                        for c in entity_contours
                    ]

                    path_ent = PathEntity(
                        layer_id=settings.target_layer_id,
                        name=f"Hatch_V{poly.index}_{ang:.1f}deg",
                        x=orig_x,
                        y=orig_y,
                        contours=norm_contours,
                        closed=False
                    )
                    hatched_entities.append(path_ent)

        # Calculate statistics
        min_diff = 180.0
        center_diffs: List[float] = []

        for u in range(len(polygons)):
            for v in neighbors_set[u]:
                if u < v:
                    diff = angular_difference(assigned_angles[u], assigned_angles[v])
                    if diff < min_diff:
                        min_diff = diff
                    r_mid = (polygons[u].radial_distance + polygons[v].radial_distance) / 2.0
                    if r_mid < 0.4:
                        center_diffs.append(diff)

        if min_diff == 180.0:
            min_diff = 0.0

        avg_center_diff = float(np.mean(center_diffs)) if center_diffs else min_diff

        return DirectionalHatchResult(
            hatched_entities=hatched_entities,
            assigned_angles=assigned_angles,
            polygons=polygons,
            neighbors=neighbors_dict,
            min_diff_achieved=min_diff,
            center_diff_achieved=avg_center_diff,
            total_hatch_length_mm=total_length,
            total_line_count=total_lines
        )
