"""
LaserForge Galvo & Fiber Laser Marking Engine.
Provides mirror inertia delay compensation, beam wobble generator (circular, figure-8, sinusoidal),
and 360° cylindrical split marking for high-speed fiber laser galvanometers.
"""

from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
import math

from laserforge.core.models import PathEntity, LaserEntity


@dataclass
class GalvoDelays:
    laser_on_delay_us: float = 120.0     # Microseconds: strikes laser after mirror accelerates
    laser_off_delay_us: float = 100.0    # Microseconds: stops laser before mirror decelerates
    mark_delay_us: float = 200.0         # Microseconds: settle time after mark move
    jump_delay_us: float = 250.0         # Microseconds: settle time after non-marking rapid jump
    polygon_delay_us: float = 80.0       # Microseconds: corner dwell for sharp vertices


@dataclass
class WobbleConfig:
    enabled: bool = True
    pattern: str = "circle"              # "circle", "figure8", "sinusoidal"
    amplitude_mm: float = 0.5            # Peak-to-peak oscillation width / diameter in mm
    pitch_mm: float = 0.15               # Distance along path between consecutive wobble loops
    layer_id: int = 0


class GalvoEngine:
    """Galvo mirror delay calculator, rotary band splitter, and beam wobble generator."""

    @staticmethod
    def calculate_timing_overhead(delays: GalvoDelays, mark_moves: int, jump_moves: int, corners: int) -> float:
        """Calculates total galvo settle delay overhead in seconds for a job."""
        total_us = (
            mark_moves * (delays.laser_on_delay_us + delays.laser_off_delay_us + delays.mark_delay_us) +
            jump_moves * delays.jump_delay_us +
            corners * delays.polygon_delay_us
        )
        return total_us / 1_000_000.0

    @classmethod
    def apply_wobble_to_contour(
        cls,
        points: List[Tuple[float, float]],
        cfg: WobbleConfig
    ) -> List[Tuple[float, float]]:
        """
        Applies transverse high-frequency wobble oscillations along a polyline toolpath.
        Expands the beam kerf for metal annealing, deep engraving, or laser welding.
        """
        if not cfg.enabled or len(points) < 2 or cfg.amplitude_mm <= 0 or cfg.pitch_mm <= 0:
            return points

        wobble_points: List[Tuple[float, float]] = []
        radius = cfg.amplitude_mm * 0.5
        traveled_dist = 0.0

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            seg_len = math.hypot(dx, dy)
            if seg_len < 1e-4:
                continue

            # Unit normal (perpendicular) and tangent vectors
            tx = dx / seg_len
            ty = dy / seg_len
            nx = -ty
            ny = tx

            # Subdivide segment by pitch
            num_loops = max(1, int(round(seg_len / cfg.pitch_mm)))
            dt = seg_len / float(num_loops)
            points_per_loop = 12 if cfg.pattern in ("circle", "figure8") else 6

            for loop in range(num_loops):
                base_t = loop * dt
                for step in range(points_per_loop):
                    frac = step / float(points_per_loop)
                    sub_t = base_t + frac * dt
                    # Base position along center axis
                    cx = p1[0] + tx * sub_t
                    cy = p1[1] + ty * sub_t

                    theta = 2.0 * math.pi * frac

                    if cfg.pattern == "circle":
                        # Circular circular helical loop
                        ox = radius * math.cos(theta) * tx + radius * math.sin(theta) * nx
                        oy = radius * math.cos(theta) * ty + radius * math.sin(theta) * ny
                    elif cfg.pattern == "figure8":
                        # Figure-8 lemniscate oscillation
                        ox = radius * math.sin(theta) * tx + radius * math.sin(2 * theta) * nx
                        oy = radius * math.sin(theta) * ty + radius * math.sin(2 * theta) * ny
                    else:
                        # Sinusoidal transverse wave
                        wave = radius * math.sin(theta)
                        ox = wave * nx
                        oy = wave * ny

                    wobble_points.append((cx + ox, cy + oy))

        # Always append end point
        wobble_points.append(points[-1])
        return wobble_points

    @classmethod
    def split_contours_for_rotary(
        cls,
        contours: List[List[Tuple[float, float]]],
        split_width_mm: float = 5.0,
        axis: str = "Y"
    ) -> List[Dict[str, Any]]:
        """
        Splits 2D contours into discrete rotary bands for galvo marking on cylindrical stock.
        Returns a list of bands, each containing the sub-contours within that band and the stepper index coordinate.
        """
        if not contours or split_width_mm <= 0:
            return []

        coord_idx = 1 if axis.upper() == "Y" else 0

        # Find overall bounding range along split axis
        all_coords = [p[coord_idx] for c in contours for p in c]
        if not all_coords:
            return []

        min_val = min(all_coords)
        max_val = max(all_coords)
        total_span = max_val - min_val

        band_count = max(1, int(math.ceil(total_span / split_width_mm)))
        bands = []

        for b in range(band_count):
            b_start = min_val + b * split_width_mm
            b_end = b_start + split_width_mm
            band_center = (b_start + b_end) * 0.5

            band_subcontours = []
            for c in contours:
                for i in range(len(c) - 1):
                    p1 = c[i]
                    p2 = c[i + 1]
                    v1 = p1[coord_idx]
                    v2 = p2[coord_idx]

                    if max(v1, v2) < b_start or min(v1, v2) > b_end:
                        continue

                    if abs(v2 - v1) < 1e-9:
                        if b_start <= v1 <= b_end:
                            band_subcontours.append([p1, p2])
                        continue

                    t_low = (b_start - v1) / (v2 - v1)
                    t_high = (b_end - v1) / (v2 - v1)
                    t_enter = max(0.0, min(t_low, t_high))
                    t_exit = min(1.0, max(t_low, t_high))

                    if t_enter < t_exit:
                        cp1 = (
                            round(p1[0] + t_enter * (p2[0] - p1[0]), 4),
                            round(p1[1] + t_enter * (p2[1] - p1[1]), 4)
                        )
                        cp2 = (
                            round(p1[0] + t_exit * (p2[0] - p1[0]), 4),
                            round(p1[1] + t_exit * (p2[1] - p1[1]), 4)
                        )
                        band_subcontours.append([cp1, cp2])

            if band_subcontours:
                bands.append({
                    "band_index": b,
                    "stepper_coord": round(band_center, 3),
                    "bounds": (round(b_start, 3), round(b_end, 3)),
                    "contours": band_subcontours
                })

        return bands
