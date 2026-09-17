"""
LaserForge Holding Tabs & Bridges Engine.
Calculates and inserts structural micro-tabs / bridges along cutting contours
to prevent small cut parts from dropping through honeycomb beds or tipping into laser nozzles.
"""

from typing import List, Tuple, Dict, Any, Optional
import math


class TabEngine:
    """
    Slices closed vector contours into cutting toolpath segments interrupted by uncut bridges (holding tabs).
    """

    @staticmethod
    def polyline_length(pts: List[Tuple[float, float]]) -> float:
        """Returns the total path length of a polyline."""
        if len(pts) < 2:
            return 0.0
        total = 0.0
        for i in range(len(pts) - 1):
            total += math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        return total

    @staticmethod
    def interpolate_point_at_distance(
        pts: List[Tuple[float, float]], target_dist: float
    ) -> Tuple[float, float]:
        """Finds the (x, y) coordinates at a given distance along a polyline."""
        if not pts:
            return (0.0, 0.0)
        if target_dist <= 0.0 or len(pts) == 1:
            return pts[0]

        accum = 0.0
        for i in range(len(pts) - 1):
            p1 = pts[i]
            p2 = pts[i + 1]
            seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if seg_len < 1e-9:
                continue
            if accum + seg_len >= target_dist:
                ratio = (target_dist - accum) / seg_len
                return (p1[0] + ratio * (p2[0] - p1[0]), p1[1] + ratio * (p2[1] - p1[1]))
            accum += seg_len

        return pts[-1]

    @classmethod
    def slice_contour_with_tabs(
        cls,
        contour: List[Tuple[float, float]],
        tab_count: int = 4,
        tab_width: float = 1.0,
        manual_tab_ratios: Optional[List[float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Slices a closed contour into alternating 'cut' and 'tab' segments.

        Parameters:
            contour: Closed polygon points [(x0, y0), (x1, y1), ..., (x0, y0)].
            tab_count: Number of holding tabs to place (if manual_tab_ratios is None).
            tab_width: Width of each uncut bridge in mm.
            manual_tab_ratios: Optional list of relative positions [0.0 ... 1.0] along perimeter.

        Returns:
            List of dicts:
                {"type": "cut", "path": [(x, y), ...]}
                {"type": "tab", "start": (x, y), "end": (x, y), "width": float}
        """
        if len(contour) < 3:
            return [{"type": "cut", "path": contour}]

        # Ensure closed
        pts = list(contour)
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-5:
            pts.append(pts[0])

        total_length = cls.polyline_length(pts)
        if total_length < 1e-3 or tab_width <= 0.0:
            return [{"type": "cut", "path": pts}]

        # Determine tab center locations
        if manual_tab_ratios and len(manual_tab_ratios) > 0:
            centers = sorted([r % 1.0 for r in manual_tab_ratios])
            centers = [c * total_length for c in centers]
        else:
            if tab_count <= 0:
                return [{"type": "cut", "path": pts}]
            # Distribute tabs evenly
            interval = total_length / float(tab_count)
            # Offset first tab by half interval for symmetry
            centers = [(i + 0.5) * interval for i in range(tab_count)]

        # Clamp tab width so tabs don't overlap
        max_allowed_width = (total_length / max(1, len(centers))) * 0.45
        eff_tab_width = min(tab_width, max_allowed_width)
        half_w = eff_tab_width / 2.0

        # Build list of tab exclusion intervals [start_dist, end_dist]
        tab_intervals = []
        for c in centers:
            t_start = c - half_w
            t_end = c + half_w
            tab_intervals.append((t_start, t_end))

        # Re-sample contour with high resolution for precise tab splitting
        # Build cumulative distance mapping for each vertex
        cum_dists = [0.0]
        for i in range(len(pts) - 1):
            seg_len = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            cum_dists.append(cum_dists[-1] + seg_len)

        # Build a list of cut intervals [cut_start, cut_end]
        # Sort intervals
        tab_intervals.sort(key=lambda x: x[0])

        # Create segments
        segments: List[Dict[str, Any]] = []

        # If the first tab starts before 0, wrap around
        current_dist = 0.0
        for t_start, t_end in tab_intervals:
            # Cut segment up to tab start
            if t_start > current_dist + 1e-5:
                cut_path = cls._extract_subpath(pts, cum_dists, current_dist, t_start)
                if len(cut_path) >= 2:
                    segments.append({"type": "cut", "path": cut_path})

            # Tab bridge segment
            p_start = cls.interpolate_point_at_distance(pts, max(0.0, t_start))
            p_end = cls.interpolate_point_at_distance(pts, min(total_length, t_end))
            segments.append({
                "type": "tab",
                "start": p_start,
                "end": p_end,
                "width": eff_tab_width
            })
            current_dist = t_end

        # Final cut segment from last tab to perimeter end
        if current_dist < total_length - 1e-5:
            cut_path = cls._extract_subpath(pts, cum_dists, current_dist, total_length)
            if len(cut_path) >= 2:
                segments.append({"type": "cut", "path": cut_path})

        return segments

    @classmethod
    def _extract_subpath(
        cls,
        pts: List[Tuple[float, float]],
        cum_dists: List[float],
        d_start: float,
        d_end: float
    ) -> List[Tuple[float, float]]:
        """Extracts vertices of pts lying within [d_start, d_end] along cumulative distances."""
        subpath: List[Tuple[float, float]] = []
        p_start = cls.interpolate_point_at_distance(pts, d_start)
        subpath.append(p_start)

        for i in range(len(pts)):
            d = cum_dists[i]
            if d_start < d < d_end:
                subpath.append(pts[i])

        p_end = cls.interpolate_point_at_distance(pts, d_end)
        # Avoid duplicate point if very close
        if math.hypot(p_end[0] - subpath[-1][0], p_end[1] - subpath[-1][1]) > 1e-5:
            subpath.append(p_end)

        return subpath

    @classmethod
    def compute_tab_coordinates(
        cls,
        contour: List[Tuple[float, float]],
        tab_count: int = 4,
        tab_width: float = 1.0,
        manual_tab_ratios: Optional[List[float]] = None
    ) -> List[Tuple[float, float, float, float]]:
        """
        Calculates (center_x, center_y, angle_deg, width) for every holding tab.
        Useful for canvas rendering and interactive previewing.
        """
        if len(contour) < 3:
            return []

        pts = list(contour)
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-5:
            pts.append(pts[0])

        total_length = cls.polyline_length(pts)
        if total_length < 1e-3:
            return []

        if manual_tab_ratios and len(manual_tab_ratios) > 0:
            centers = sorted([r % 1.0 for r in manual_tab_ratios])
            dists = [c * total_length for c in centers]
        else:
            if tab_count <= 0:
                return []
            interval = total_length / float(tab_count)
            dists = [(i + 0.5) * interval for i in range(tab_count)]

        tabs_info = []
        for d in dists:
            cx, cy = cls.interpolate_point_at_distance(pts, d)
            # Sample slight delta to get tangent angle
            p_prev = cls.interpolate_point_at_distance(pts, max(0.0, d - 0.2))
            p_next = cls.interpolate_point_at_distance(pts, min(total_length, d + 0.2))
            dx = p_next[0] - p_prev[0]
            dy = p_next[1] - p_prev[1]
            angle = math.degrees(math.atan2(dy, dx))
            tabs_info.append((cx, cy, angle, tab_width))

        return tabs_info
