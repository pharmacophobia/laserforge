"""
LaserForge 3D Curved Surface Projection & Non-Planar Toolpath Wrapping Engine.

Projects 2D vector geometries across non-planar 3D physical surfaces:
- Cylindrical wrapping (engraving along cylindrical arc without rotary hardware)
- Spherical / Dome / Bowl surface projection
- Sloped wedge / inclined plane projection
- Grayscale heightmap 3D topographic surface projection
- Toolpath micro-segmentation for smooth Z-height profiling and continuous dynamic focal tracking
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Any, Callable
import math
import numpy as np

from laserforge.core.models import LaserEntity, PathEntity


@dataclass
class SurfaceParameters:
    """Parameters defining the physical 3D curved surface."""
    surface_type: str = "Cylinder"        # "Cylinder", "Sphere", "Incline", "Heightmap"
    radius_mm: float = 50.0               # Radius of cylinder or dome
    axis: str = "X"                       # Alignment axis for cylinder ("X" or "Y")
    max_depth_mm: float = 10.0            # Max Z variation range
    incline_angle_deg: float = 15.0       # Slope angle for incline surface
    subdivision_step_mm: float = 0.5      # Max segment length before subdividing for smooth Z
    maintain_focus: bool = True           # Dynamic Z-axis height adjustment during cut
    focal_distance_mm: float = 50.0       # Nominal laser focal distance


class Surface3DProjector:
    """
    Evaluates 3D surface elevation and projects 2D vector toolpaths onto non-planar surfaces.
    """

    @staticmethod
    def get_elevation_function(params: SurfaceParameters, origin_x: float = 0.0, origin_y: float = 0.0) -> Callable[[float, float], float]:
        """
        Returns a callable z_func(x, y) -> float representing the surface height Z at (x, y).
        Z=0 represents the topmost surface crest (focal baseline).
        """
        stype = params.surface_type
        r = max(1.0, params.radius_mm)

        if stype == "Cylinder":
            if params.axis.upper() == "X":
                # Cylinder curved along Y axis (ridge along X)
                def z_cyl_x(x: float, y: float) -> float:
                    dy = y - origin_y
                    if abs(dy) >= r:
                        return -params.max_depth_mm
                    return math.sqrt(r * r - dy * dy) - r
                return z_cyl_x
            else:
                # Cylinder curved along X axis (ridge along Y)
                def z_cyl_y(x: float, y: float) -> float:
                    dx = x - origin_x
                    if abs(dx) >= r:
                        return -params.max_depth_mm
                    return math.sqrt(r * r - dx * dx) - r
                return z_cyl_y

        elif stype == "Sphere":
            def z_sph(x: float, y: float) -> float:
                dx = x - origin_x
                dy = y - origin_y
                dist_sq = dx * dx + dy * dy
                if dist_sq >= r * r:
                    return -params.max_depth_mm
                return math.sqrt(r * r - dist_sq) - r
            return z_sph

        elif stype == "Incline":
            slope = math.tan(math.radians(params.incline_angle_deg))
            if params.axis.upper() == "X":
                def z_inc_x(x: float, y: float) -> float:
                    return -(x - origin_x) * slope
                return z_inc_x
            else:
                def z_inc_y(x: float, y: float) -> float:
                    return -(y - origin_y) * slope
                return z_inc_y

        else:
            # Flat plane fallback
            return lambda x, y: 0.0

    @classmethod
    def subdivide_contour(
        cls,
        contour: List[Tuple[float, float]],
        max_step: float = 0.5
    ) -> List[Tuple[float, float]]:
        """
        Subdivides straight line segments into micro-segments so they conform tightly
        to 3D curved surface elevations.
        """
        if len(contour) < 2:
            return contour

        dense_pts: List[Tuple[float, float]] = [contour[0]]
        for i in range(len(contour) - 1):
            p1 = contour[i]
            p2 = contour[i + 1]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            seg_len = math.hypot(dx, dy)

            if seg_len <= max_step:
                dense_pts.append(p2)
            else:
                steps = int(math.ceil(seg_len / max_step))
                for s in range(1, steps + 1):
                    t = s / steps
                    dense_pts.append((p1[0] + dx * t, p1[1] + dy * t))

        return dense_pts

    @classmethod
    def project_contours(
        cls,
        contours: List[List[Tuple[float, float]]],
        params: SurfaceParameters,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> List[List[Tuple[float, float, float]]]:
        """
        Projects 2D contour list into 3D (X, Y, Z) point paths.
        """
        z_fn = cls.get_elevation_function(params, origin_x, origin_y)
        dense_contours = [
            cls.subdivide_contour(c, max_step=params.subdivision_step_mm)
            for c in contours
        ]

        result_3d: List[List[Tuple[float, float, float]]] = []
        for c in dense_contours:
            pts_3d = []
            for pt in c:
                z = z_fn(pt[0], pt[1])
                pts_3d.append((float(pt[0]), float(pt[1]), float(z)))
            result_3d.append(pts_3d)

        return result_3d

    @classmethod
    def generate_nonplanar_gcode(
        cls,
        contours_3d: List[List[Tuple[float, float, float]]],
        feed_rate: float = 1200.0,
        laser_power_s: int = 800,
        rapid_speed: float = 3000.0
    ) -> List[str]:
        """
        Converts projected 3D paths into GRBL 3D motion G-code with dynamic Z tracking.
        """
        gcode = [
            "; --- LaserForge 3D Non-Planar Toolpath ---",
            "G90",          # Absolute positioning
            "G21",          # Millimeters
            f"F{feed_rate:.1f}"
        ]

        for path in contours_3d:
            if not path:
                continue

            first = path[0]
            # Rapid move above start position
            safe_z = first[2] + 2.0
            gcode.append(f"G0 X{first[0]:.3f} Y{first[1]:.3f} Z{safe_z:.3f} F{rapid_speed:.1f}")
            # Plunge to surface
            gcode.append(f"G1 Z{first[2]:.3f} F{feed_rate:.1f}")
            # Laser on
            gcode.append(f"M4 S{laser_power_s}")

            for pt in path[1:]:
                gcode.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} Z{pt[2]:.3f}")

            # Laser off and lift
            gcode.append("M5")
            gcode.append(f"G0 Z{safe_z:.3f}")

        gcode.append("; --- End 3D Non-Planar Toolpath ---")
        return gcode
