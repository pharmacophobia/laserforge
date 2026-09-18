"""
LaserForge Common Line Cutting & Coincident Edge De-duplication Engine.
Detects and merges shared adjacent cut lines between tiled or nested parts,
eliminating redundant double cuts, saving 30-50% machine run time, and preventing edge scorch.
"""

from dataclasses import dataclass, field
import math
from typing import List, Tuple, Dict, Any, Optional, Set
import numpy as np

Point2D = Tuple[float, float]
Segment2D = Tuple[Point2D, Point2D]


def point_dist(p1: Point2D, p2: Point2D) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def points_equal(p1: Point2D, p2: Point2D, tol: float = 0.05) -> bool:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) <= tol


def segment_length(seg: Segment2D) -> float:
    return point_dist(seg[0], seg[1])


def project_point_on_line(pt: Point2D, line_p1: Point2D, line_p2: Point2D) -> Tuple[Point2D, float]:
    """Projects pt onto infinite line passing through line_p1, line_p2. Returns (projected_pt, t)."""
    dx = line_p2[0] - line_p1[0]
    dy = line_p2[1] - line_p1[1]
    denom = dx * dx + dy * dy
    if denom < 1e-9:
        return line_p1, 0.0
    t = ((pt[0] - line_p1[0]) * dx + (pt[1] - line_p1[1]) * dy) / denom
    proj = (line_p1[0] + t * dx, line_p1[1] + t * dy)
    return proj, t


def segments_collinear_overlap(
    seg1: Segment2D,
    seg2: Segment2D,
    dist_tol: float = 0.08,
    angle_tol_deg: float = 1.0
) -> Optional[Tuple[Segment2D, List[Segment2D], List[Segment2D]]]:
    """
    Checks if seg1 and seg2 are collinear and overlapping.
    If they overlap:
      Returns (shared_segment, seg1_remainders, seg2_remainders).
    Otherwise returns None.
    """
    len1 = segment_length(seg1)
    len2 = segment_length(seg2)
    if len1 < dist_tol or len2 < dist_tol:
        return None

    # Check angles
    ang1 = math.atan2(seg1[1][1] - seg1[0][1], seg1[1][0] - seg1[0][0])
    ang2 = math.atan2(seg2[1][1] - seg2[0][1], seg2[1][0] - seg2[0][0])

    # Normalize to [0, pi)
    ang1_norm = ang1 % math.pi
    ang2_norm = ang2 % math.pi
    diff_ang = abs(ang1_norm - ang2_norm)
    diff_ang = min(diff_ang, math.pi - diff_ang)
    if diff_ang > math.radians(angle_tol_deg):
        return None

    # Check distance of seg2 endpoints from line seg1
    proj_s2_0, t_s2_0 = project_point_on_line(seg2[0], seg1[0], seg1[1])
    proj_s2_1, t_s2_1 = project_point_on_line(seg2[1], seg1[0], seg1[1])

    if point_dist(seg2[0], proj_s2_0) > dist_tol or point_dist(seg2[1], proj_s2_1) > dist_tol:
        return None

    # Check 1D interval overlap along seg1 parameter t
    # seg1 has t in [0.0, 1.0]
    t2_min = min(t_s2_0, t_s2_1)
    t2_max = max(t_s2_0, t_s2_1)

    t_overlap_start = max(0.0, t2_min)
    t_overlap_end = min(1.0, t2_max)

    overlap_length = (t_overlap_end - t_overlap_start) * len1
    if overlap_length <= dist_tol:
        return None

    # Compute shared segment points
    shared_p1 = (
        seg1[0][0] + t_overlap_start * (seg1[1][0] - seg1[0][0]),
        seg1[0][1] + t_overlap_start * (seg1[1][1] - seg1[0][1])
    )
    shared_p2 = (
        seg1[0][0] + t_overlap_end * (seg1[1][0] - seg1[0][0]),
        seg1[0][1] + t_overlap_end * (seg1[1][1] - seg1[0][1])
    )
    shared_seg = (shared_p1, shared_p2)

    # Compute remainders for seg1
    rem1: List[Segment2D] = []
    if t_overlap_start * len1 > dist_tol:
        rem1.append((seg1[0], shared_p1))
    if (1.0 - t_overlap_end) * len1 > dist_tol:
        rem1.append((shared_p2, seg1[1]))

    # Compute remainders for seg2
    # Convert overlap t to seg2 orientation
    rem2: List[Segment2D] = []
    # If t_s2_0 < t_s2_1, seg2 points in same direction as seg1
    same_dir = (t_s2_0 <= t_s2_1)
    if t2_min < - (dist_tol / len1):
        # seg2 extends before seg1[0]
        ext_p = (seg1[0][0] + t2_min * (seg1[1][0] - seg1[0][0]), seg1[0][1] + t2_min * (seg1[1][1] - seg1[0][1]))
        if same_dir:
            rem2.append((seg2[0], shared_p1))
        else:
            rem2.append((shared_p1, seg2[1]))
    if t2_max > 1.0 + (dist_tol / len1):
        # seg2 extends after seg1[1]
        if same_dir:
            rem2.append((shared_p2, seg2[1]))
        else:
            rem2.append((seg2[0], shared_p2))

    return shared_seg, rem1, rem2


@dataclass
class CommonLineResult:
    original_segment_count: int = 0
    optimized_segment_count: int = 0
    shared_lines_count: int = 0
    saved_cutting_length_mm: float = 0.0
    original_cutting_length_mm: float = 0.0
    optimized_paths: List[List[Point2D]] = field(default_factory=list)

    @property
    def optimized_cutting_length_mm(self) -> float:
        return max(0.0, round(self.original_cutting_length_mm - self.saved_cutting_length_mm, 2))


class CommonLineEngine:
    """
    High-performance toolpath optimizer that scans for overlapping/collinear cut segments
    across multiple closed or open contours and merges coincident lines into a single pass.
    """

    @staticmethod
    def extract_segments(paths: List[List[Point2D]], closed_flags: Optional[List[bool]] = None) -> List[Segment2D]:
        """Converts a list of polyline contours into discrete 2-point directed segments."""
        segments: List[Segment2D] = []
        for idx, path in enumerate(paths):
            if len(path) < 2:
                continue
            is_closed = closed_flags[idx] if (closed_flags and idx < len(closed_flags)) else False
            for i in range(len(path) - 1):
                p1 = path[i]
                p2 = path[i + 1]
                if not points_equal(p1, p2):
                    segments.append((p1, p2))
            if is_closed and len(path) > 2:
                if not points_equal(path[-1], path[0]):
                    segments.append((path[-1], path[0]))
        return segments

    @staticmethod
    def chain_segments(segments: List[Segment2D], tol: float = 0.08) -> List[List[Point2D]]:
        """
        Greedily connects a pool of disconnected line segments into continuous
        polylines and closed loops to minimize rapid G0 travel moves.
        """
        if not segments:
            return []

        remaining = list(segments)
        chains: List[List[Point2D]] = []

        while remaining:
            curr_seg = remaining.pop(0)
            curr_chain = [curr_seg[0], curr_seg[1]]

            extended = True
            while extended:
                extended = False
                head = curr_chain[0]
                tail = curr_chain[-1]

                for i, candidate in enumerate(remaining):
                    c0, c1 = candidate

                    # Connect to tail
                    if points_equal(tail, c0, tol):
                        curr_chain.append(c1)
                        remaining.pop(i)
                        extended = True
                        break
                    elif points_equal(tail, c1, tol):
                        curr_chain.append(c0)
                        remaining.pop(i)
                        extended = True
                        break

                    # Connect to head
                    elif points_equal(head, c1, tol):
                        curr_chain.insert(0, c0)
                        remaining.pop(i)
                        extended = True
                        break
                    elif points_equal(head, c0, tol):
                        curr_chain.insert(0, c1)
                        remaining.pop(i)
                        extended = True
                        break

            chains.append(curr_chain)

        return chains

    @staticmethod
    def deduplicate_common_lines(
        paths: List[List[Point2D]],
        closed_flags: Optional[List[bool]] = None,
        tolerance: float = 0.08
    ) -> CommonLineResult:
        """
        Analyzes all input toolpaths, detects overlapping / coincident edge segments,
        removes redundant passes, and chains the resulting unique edges into optimized paths.
        """
        raw_segments = CommonLineEngine.extract_segments(paths, closed_flags)
        total_orig_len = sum(segment_length(s) for s in raw_segments)

        result = CommonLineResult(
            original_segment_count=len(raw_segments),
            original_cutting_length_mm=round(total_orig_len, 2)
        )

        if len(raw_segments) <= 1:
            result.optimized_paths = paths
            result.optimized_segment_count = len(raw_segments)
            return result

        # Pool of active segments to process
        unprocessed = list(raw_segments)
        unique_segments: List[Segment2D] = []
        shared_count = 0
        saved_length = 0.0

        while unprocessed:
            seg = unprocessed.pop(0)
            merged = False

            for i, target in enumerate(unique_segments):
                overlap_info = segments_collinear_overlap(seg, target, dist_tol=tolerance)
                if overlap_info is not None:
                    shared_seg, rem_seg, rem_target = overlap_info
                    # Replace target with shared segment + remainders
                    unique_segments.pop(i)
                    unique_segments.append(shared_seg)
                    unique_segments.extend(rem_target)
                    unprocessed.extend(rem_seg)

                    shared_len = segment_length(shared_seg)
                    saved_length += shared_len
                    shared_count += 1
                    merged = True
                    break

            if not merged:
                unique_segments.append(seg)

        # Filter out zero-length or sub-tolerance segments
        final_segments = [s for s in unique_segments if segment_length(s) > tolerance]

        # Chain into continuous toolpaths
        optimized_paths = CommonLineEngine.chain_segments(final_segments, tol=tolerance)

        final_cutting_len = sum(
            point_dist(p[i], p[i+1]) for p in optimized_paths for i in range(len(p)-1)
        )

        result.optimized_segment_count = len(final_segments)
        result.shared_lines_count = shared_count
        result.saved_cutting_length_mm = round(total_orig_len - final_cutting_len, 2)
        result.optimized_paths = optimized_paths

        return result

    optimize_paths = deduplicate_common_lines
