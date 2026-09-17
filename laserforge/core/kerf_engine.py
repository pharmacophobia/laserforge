"""
LaserForge Kerf Compensation & Pierce Lead-In / Lead-Out Engine.
Provides automatic topological kerf offsets (outward for perimeters, inward for holes),
tangential/arc/perpendicular lead-ins, lead-outs, and overcut path extensions.
"""

import math
from typing import List, Tuple, Optional, Dict, Any, Union
import shapely
from shapely.geometry import Polygon, MultiPolygon, LineString, LinearRing


Point2D = Tuple[float, float]
Path2D = List[Point2D]


class KerfEngine:
    """
    High-precision CAM geometric engine for laser kerf compensation and pierce control.
    """

    @staticmethod
    def is_closed_path(path: Path2D, tol: float = 1e-4) -> bool:
        """Determines if a path forms a closed geometric loop."""
        if len(path) < 3:
            return False
        p0 = path[0]
        pn = path[-1]
        return math.hypot(p0[0] - pn[0], p0[1] - pn[1]) <= tol

    @staticmethod
    def is_clockwise(pts: Path2D) -> bool:
        """
        Returns True if the 2D polygon vertices are ordered clockwise in standard cartesian space.
        Uses the Shoelace / Green's theorem polygon area formula.
        """
        area = 0.0
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            area += (pts[j][0] - pts[i][0]) * (pts[j][1] + pts[i][1])
        return area > 0.0

    @classmethod
    def apply_kerf_to_paths(
        cls,
        paths: List[Path2D],
        kerf_offset: float,
        direction: str = "Auto",
        mitre_limit: float = 5.0
    ) -> List[Dict[str, Any]]:
        """
        Applies directional kerf compensation to a list of vector paths.

        Parameters:
            paths: List of vertex loops [[(x,y), ...], ...]
            kerf_offset: Laser beam width / total kerf in mm (e.g. 0.15mm).
                         The offset distance applied is kerf_offset / 2.0.
            direction: "Auto" (outer perimeters outward, inner holes inward),
                       "Outward" (all paths expanded),
                       "Inward" (all paths shrunk),
                       "Off" / "None" (no offset applied).
            mitre_limit: Mitre ratio limit to avoid extreme spikes on acute corners.

        Returns:
            List of dicts:
              {
                "path": Path2D,
                "is_outer": bool,
                "is_closed": bool,
                "original_path": Path2D
              }
        """
        results: List[Dict[str, Any]] = []
        half_kerf = kerf_offset / 2.0

        if abs(half_kerf) < 1e-5 or direction in ("Off", "None"):
            for p in paths:
                results.append({
                    "path": p,
                    "is_outer": True,
                    "is_closed": cls.is_closed_path(p),
                    "original_path": p
                })
            return results

        # Separate open vs closed paths
        closed_paths: List[Path2D] = []
        open_paths: List[Path2D] = []

        for p in paths:
            if cls.is_closed_path(p):
                closed_paths.append(p)
            else:
                open_paths.append(p)

        # Open paths don't have interior/exterior - preserve without directional offsetting
        for op in open_paths:
            results.append({
                "path": op,
                "is_outer": True,
                "is_closed": False,
                "original_path": op
            })

        if not closed_paths:
            return results

        # Build polygons and classify containment hierarchy (outer vs inner holes)
        shapely_polys = []
        for p in closed_paths:
            try:
                poly = Polygon(p)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.area > 1e-6:
                    shapely_polys.append((poly, p))
            except Exception:
                # If Shapely fails, fallback to raw path
                results.append({
                    "path": p,
                    "is_outer": True,
                    "is_closed": True,
                    "original_path": p
                })

        num_polys = len(shapely_polys)
        is_outer_flags = [True] * num_polys

        # Containment check: a polygon is an inner hole if it is contained inside another polygon
        for i in range(num_polys):
            poly_i, _ = shapely_polys[i]
            container_count = 0
            for j in range(num_polys):
                if i == j:
                    continue
                poly_j, _ = shapely_polys[j]
                # If poly_i is within poly_j
                if poly_j.contains(poly_i):
                    container_count += 1
            # Even containers = outer boundary; Odd containers = hole cutout
            is_outer_flags[i] = (container_count % 2 == 0)

        # Apply buffer offset
        for idx, (poly, orig_p) in enumerate(shapely_polys):
            is_outer = is_outer_flags[idx]

            # Determine signed offset distance
            if direction == "Auto":
                d = half_kerf if is_outer else -half_kerf
            elif direction == "Outward":
                d = half_kerf
            elif direction == "Inward":
                d = -half_kerf
            else:
                d = 0.0

            if abs(d) < 1e-6:
                results.append({
                    "path": orig_p,
                    "is_outer": is_outer,
                    "is_closed": True,
                    "original_path": orig_p
                })
                continue

            try:
                # Buffer with mitre join (join_style=2) to retain sharp corners on cut pieces
                buffered = poly.buffer(d, join_style=shapely.BufferJoinStyle.mitre, mitre_limit=mitre_limit)
                if buffered.is_empty:
                    continue

                if isinstance(buffered, Polygon):
                    buffered_list = [buffered]
                elif isinstance(buffered, MultiPolygon):
                    buffered_list = list(buffered.geoms)
                else:
                    buffered_list = []

                for bp in buffered_list:
                    ext_coords = list(bp.exterior.coords)
                    if len(ext_coords) >= 3:
                        results.append({
                            "path": ext_coords,
                            "is_outer": is_outer,
                            "is_closed": True,
                            "original_path": orig_p
                        })
                    for interior in bp.interiors:
                        int_coords = list(interior.coords)
                        if len(int_coords) >= 3:
                            results.append({
                                "path": int_coords,
                                "is_outer": False,
                                "is_closed": True,
                                "original_path": orig_p
                            })
            except Exception:
                # Fallback to original path if buffering errors
                results.append({
                    "path": orig_p,
                    "is_outer": is_outer,
                    "is_closed": True,
                    "original_path": orig_p
                })

        return results

    @classmethod
    def generate_lead_in(
        cls,
        path: Path2D,
        lead_type: str = "None",
        length: float = 2.0,
        is_outer: bool = True
    ) -> Path2D:
        """
        Generates lead-in pierce coordinates approaching the first vertex of a closed contour.

        Parameters:
            path: Target closed contour path.
            lead_type: "None", "Line", "Arc", or "Perpendicular".
            length: Length/radius of the lead-in in mm.
            is_outer: True if outer perimeter (waste is outside), False if hole (waste is inside).

        Returns:
            List of points representing the lead-in approach [P_pierce, ..., P_entry]
        """
        if lead_type in ("None", "") or length <= 0.0 or len(path) < 2:
            return []

        p0 = path[0]
        p1 = path[1]

        # Vector along entry tangent
        vx = p1[0] - p0[0]
        vy = p1[1] - p0[1]
        v_mag = math.hypot(vx, vy)
        if v_mag < 1e-6:
            return []

        tx = vx / v_mag
        ty = vy / v_mag

        # Normal vector pointing to the left of the tangent (nx, ny) = (-ty, tx)
        # Check winding to know which side is waste
        cw = cls.is_clockwise(path)
        # If CW: left is OUTSIDE (waste for outer, material for hole).
        # If CCW: right is OUTSIDE (waste for outer, material for hole).
        if cw:
            waste_nx = -ty if is_outer else ty
            waste_ny = tx if is_outer else -tx
        else:
            waste_nx = ty if is_outer else -ty
            waste_ny = -tx if is_outer else tx

        if lead_type == "Line":
            # Approach at 45 degree angle from waste into path entry
            ax = -tx + waste_nx
            ay = -ty + waste_ny
            a_mag = math.hypot(ax, ay)
            if a_mag > 1e-6:
                pierce_x = p0[0] + (ax / a_mag) * length
                pierce_y = p0[1] + (ay / a_mag) * length
                return [(pierce_x, pierce_y), p0]
            return [(p0[0] - tx * length, p0[1] - ty * length), p0]

        elif lead_type == "Perpendicular":
            pierce_x = p0[0] + waste_nx * length
            pierce_y = p0[1] + waste_ny * length
            return [(pierce_x, pierce_y), p0]

        elif lead_type == "Arc":
            # Circular 90° arc tangent to (tx, ty) at p0, center located at p0 + length * waste_normal
            cx = p0[0] + waste_nx * length
            cy = p0[1] + waste_ny * length
            # Arc from start angle to p0
            # Center to p0 vector is -waste_normal
            ang_entry = math.atan2(-waste_ny, -waste_nx)
            # Arc sweeps 90 degrees (pi/2)
            # Determine sweep direction so tangent at end matches (tx, ty)
            # Derivative of (cx + r*cos(a), cy + r*sin(a)) is (-r*sin(a), r*cos(a))
            # At ang_entry: (-sin, cos) should match (tx, ty) or (-tx, -ty)
            dot = (-math.sin(ang_entry)) * tx + (math.cos(ang_entry)) * ty
            sweep_sign = 1.0 if dot > 0 else -1.0
            ang_start = ang_entry - sweep_sign * (math.pi / 2.0)

            arc_pts: List[Point2D] = []
            steps = 8
            for s in range(steps + 1):
                cur_ang = ang_start + (ang_entry - ang_start) * (s / steps)
                px = cx + length * math.cos(cur_ang)
                py = cy + length * math.sin(cur_ang)
                arc_pts.append((px, py))
            return arc_pts

        return []

    @classmethod
    def generate_lead_out(
        cls,
        path: Path2D,
        lead_type: str = "None",
        length: float = 2.0,
        is_outer: bool = True
    ) -> Path2D:
        """
        Generates lead-out coordinates exiting the end vertex of a closed contour into waste.
        """
        if lead_type in ("None", "") or length <= 0.0 or len(path) < 2:
            return []

        pn = path[-1]
        pn_prev = path[-2]

        # Vector along exit tangent
        vx = pn[0] - pn_prev[0]
        vy = pn[1] - pn_prev[1]
        v_mag = math.hypot(vx, vy)
        if v_mag < 1e-6:
            return []

        tx = vx / v_mag
        ty = vy / v_mag

        cw = cls.is_clockwise(path)
        if cw:
            waste_nx = -ty if is_outer else ty
            waste_ny = tx if is_outer else -tx
        else:
            waste_nx = ty if is_outer else -ty
            waste_ny = -tx if is_outer else tx

        if lead_type == "Line":
            # Exit at 45 degree angle into waste
            ax = tx + waste_nx
            ay = ty + waste_ny
            a_mag = math.hypot(ax, ay)
            if a_mag > 1e-6:
                exit_x = pn[0] + (ax / a_mag) * length
                exit_y = pn[1] + (ay / a_mag) * length
                return [pn, (exit_x, exit_y)]
            return [pn, (pn[0] + tx * length, pn[1] + ty * length)]

        elif lead_type == "Perpendicular":
            exit_x = pn[0] + waste_nx * length
            exit_y = pn[1] + waste_ny * length
            return [pn, (exit_x, exit_y)]

        elif lead_type == "Arc":
            cx = pn[0] + waste_nx * length
            cy = pn[1] + waste_ny * length
            ang_exit = math.atan2(-waste_ny, -waste_nx)
            dot = (-math.sin(ang_exit)) * tx + (math.cos(ang_exit)) * ty
            sweep_sign = 1.0 if dot > 0 else -1.0
            ang_end = ang_exit + sweep_sign * (math.pi / 2.0)

            arc_pts: List[Point2D] = []
            steps = 8
            for s in range(steps + 1):
                cur_ang = ang_exit + (ang_end - ang_exit) * (s / steps)
                px = cx + length * math.cos(cur_ang)
                py = cy + length * math.sin(cur_ang)
                arc_pts.append((px, py))
            return arc_pts

        return []

    @classmethod
    def apply_overcut(cls, path: Path2D, overcut_dist: float) -> Path2D:
        """
        Extends a closed path past its closing junction by overcut_dist mm along the starting segments.
        Ensures a clean cut separation without tabs.
        """
        if overcut_dist <= 0.0 or len(path) < 3 or not cls.is_closed_path(path):
            return path

        extended = list(path)
        dist_remaining = overcut_dist

        # Trace forward from path[0] to path[1], path[2], etc.
        for i in range(len(path) - 1):
            p_a = path[i]
            p_b = path[i + 1]
            seg_len = math.hypot(p_b[0] - p_a[0], p_b[1] - p_a[1])
            if seg_len <= 1e-6:
                continue

            if dist_remaining <= seg_len:
                ratio = dist_remaining / seg_len
                end_x = p_a[0] + ratio * (p_b[0] - p_a[0])
                end_y = p_a[1] + ratio * (p_b[1] - p_a[1])
                extended.append((end_x, end_y))
                break
            else:
                extended.append(p_b)
                dist_remaining -= seg_len

        return extended
