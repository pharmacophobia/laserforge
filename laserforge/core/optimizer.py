"""
LaserForge Path Optimizer.
Sorts toolpaths to:
1. Cut inner holes before outer contours.
2. Minimize rapid travel distance using Nearest Neighbor / TSP.
3. Optimize cutting direction.
"""

from typing import List, Tuple
import math

def point_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def polygon_bounds(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    min_x = min(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    max_x = max(p[0] for p in pts)
    max_y = max(p[1] for p in pts)
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
            bounds = polygon_bounds(path)
            items.append({
                "index": i,
                "path": path,
                "closed": closed_flags[i] if i < len(closed_flags) else True,
                "bounds": bounds,
                "depth": 0
            })

        # Calculate nesting depth (inner contours have higher depth)
        for i, item_a in enumerate(items):
            for j, item_b in enumerate(items):
                if i != j and item_a["closed"] and item_b["closed"]:
                    if is_box_inside(item_a["bounds"], item_b["bounds"]):
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
                best_dist = float("inf")
                should_reverse = False

                for k, candidate in enumerate(unvisited):
                    path = candidate["path"]
                    start_pt = path[0]
                    end_pt = path[-1]

                    d_start = point_distance(current_pos, start_pt)
                    if d_start < best_dist:
                        best_dist = d_start
                        best_idx = k
                        should_reverse = False

                    # If open path, check reverse direction
                    if not candidate["closed"]:
                        d_end = point_distance(current_pos, end_pt)
                        if d_end < best_dist:
                            best_dist = d_end
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

