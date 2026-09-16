"""
LaserForge Path Optimizer.
Sorts toolpaths to:
1. Cut inner holes before outer contours.
2. Minimize rapid travel distance using Nearest Neighbor / TSP.
3. Optimize cutting direction.
"""

from typing import List, Tuple
import math
import numpy as np

def point_dist_sq(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return dx * dx + dy * dy

def point_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def polygon_bounds(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    if not pts:
        return (0.0, 0.0, 0.0, 0.0)
    if len(pts) > 64:
        arr = np.asarray(pts, dtype=np.float32)
        return (float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 0].max()), float(arr[:, 1].max()))
    min_x = pts[0][0]
    max_x = min_x
    min_y = pts[0][1]
    max_y = min_y
    for x, y in pts[1:]:
        if x < min_x: min_x = x
        elif x > max_x: max_x = x
        if y < min_y: min_y = y
        elif y > max_y: max_y = y
    return (min_x, min_y, max_x, max_y)

def is_box_inside(inner: Tuple[float, float, float, float], outer: Tuple[float, float, float, float]) -> bool:
    """Checks if bounding box 'inner' is strictly inside bounding box 'outer'."""
    return (inner[0] >= outer[0] - 0.001 and
            inner[1] >= outer[1] - 0.001 and
            inner[2] <= outer[2] + 0.001 and
            inner[3] <= outer[3] + 0.001)

class PathOptimizer:

    @staticmethod
    def optimize_paths(
        paths: List[List[Tuple[float, float]]],
        closed_flags: List[bool] = None,
        start_pos: Tuple[float, float] = (0.0, 0.0)
    ) -> List[List[Tuple[float, float]]]:
        """
        Optimizes cutting order:
        1. Hierarchical inner-first grouping based on bounding box containment.
        2. Nearest-neighbor sorting between disjoint paths.
        """
        if not paths:
            return []

        if closed_flags is None:
            closed_flags = [True] * len(paths)

        # Compute bounding boxes and nesting depth
        items = []
        for i, path in enumerate(paths):
            if not path:
                continue
            bx1, by1, bx2, by2 = polygon_bounds(path)
            area = (bx2 - bx1) * (by2 - by1)
            items.append({
                "index": i,
                "path": path,
                "closed": closed_flags[i] if i < len(closed_flags) else True,
                "bounds": (bx1, by1, bx2, by2),
                "area": area,
                "depth": 0
            })

        # Sort by area ascending so each item is only ever checked against
        # shapes with >= area (items that could enclose it). This halves the
        # number of comparisons versus the naive O(n²) double-loop.
        items.sort(key=lambda i: i["area"])

        # Calculate nesting depth (inner contours have higher depth)
        for idx_a, item_a in enumerate(items):
            if not item_a["closed"]:
                continue
            ax1, ay1, ax2, ay2 = item_a["bounds"]
            a_area = item_a["area"]
            # Only check against items with >= area (they could be enclosing containers)
            for item_b in items[idx_a + 1:]:
                if item_a is item_b or not item_b["closed"]:
                    continue
                bx1, by1, bx2, by2 = item_b["bounds"]
                if ax1 >= bx1 - 0.001 and ay1 >= by1 - 0.001 and ax2 <= bx2 + 0.001 and ay2 <= by2 + 0.001:
                    item_a["depth"] += 1

        # Sort by depth descending (cut deepest inner items first)
        depth_groups = {}
        for item in items:
            d = item["depth"]
            depth_groups.setdefault(d, []).append(item)

        ordered_paths = []
        current_pos = start_pos

        # Process from highest depth (most nested inside) down to 0 (outermost)
        for depth in sorted(depth_groups.keys(), reverse=True):
            group = depth_groups[depth]

            # Nearest-neighbor sort within group
            unvisited = list(group)
            while unvisited:
                best_idx = 0
                best_dist_sq = float("inf")
                should_reverse = False

                cx, cy = current_pos

                for k, candidate in enumerate(unvisited):
                    path = candidate["path"]
                    start_pt = path[0]

                    dx = cx - start_pt[0]
                    dy = cy - start_pt[1]
                    d_start = dx * dx + dy * dy
                    if d_start < best_dist_sq:
                        best_dist_sq = d_start
                        best_idx = k
                        should_reverse = False

                    # If open path, check reverse direction
                    if not candidate["closed"]:
                        end_pt = path[-1]
                        edx = cx - end_pt[0]
                        edy = cy - end_pt[1]
                        d_end = edx * edx + edy * edy
                        if d_end < best_dist_sq:
                            best_dist_sq = d_end
                            best_idx = k
                            should_reverse = True

                chosen = unvisited.pop(best_idx)
                final_path = list(chosen["path"])
                if should_reverse:
                    final_path.reverse()

                ordered_paths.append(final_path)
                current_pos = final_path[-1]

        return ordered_paths

    @staticmethod
    def sort_inner_first(paths: List[List[Tuple[float, float]]]) -> List[List[Tuple[float, float]]]:
        """Sorts contours so inner closed loops come before outer containing loops."""
        return PathOptimizer.optimize_paths(paths, [True] * len(paths))

    @staticmethod
    def optimize_travel_order(
        paths: List[List[Tuple[float, float]]],
        start_pos: Tuple[float, float] = (0.0, 0.0)
    ) -> List[List[Tuple[float, float]]]:
        """Nearest-neighbor travel optimizer minimizing rapid movement distance."""
        return PathOptimizer.optimize_paths(paths, [False] * len(paths), start_pos)

