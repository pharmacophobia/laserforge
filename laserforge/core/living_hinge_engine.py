"""
LaserForge Parametric Living Hinge & Lattice Flex Engine.
Generates laser-cut flexible lattice hinge patterns (straight alternating, wavy sinuous,
diamond honeycomb, and cross-weave) allowing rigid sheet wood and acrylic to bend into smooth curves.
"""

from typing import List, Tuple, Dict, Any, Optional
import math
from dataclasses import dataclass

from laserforge.core.models import PathEntity, LineEntity, RectEntity, LaserEntity


@dataclass
class LivingHingeConfig:
    width: float = 60.0        # Width of hinge zone in mm (along bend direction)
    height: float = 120.0      # Height of hinge zone in mm (length of hinge axis)
    thickness: float = 3.0     # Sheet material thickness in mm
    bend_radius: float = 25.0  # Desired inside bend radius in mm
    bend_angle_deg: float = 90.0  # Desired bend angle (e.g. 90° for corner, 180° for book spine)
    cut_pattern: str = "straight"  # "straight", "wavy", "diamond", "honeycomb"
    cut_length: float = 12.0   # Length of each slit cut in mm
    gap_length: float = 1.8    # Uncut bridge gap between slits in mm
    column_spacing: float = 2.0  # Distance between adjacent slit columns in mm
    layer_id: int = 0          # Target cut layer
    add_border_tabs: bool = False  # Add solid mounting borders on left and right
    border_tab_width: float = 15.0  # Width of solid attachment borders in mm


class LivingHingeEngine:
    """Parametric generator for bendable laser-cut living hinges and lattice flex patterns."""

    @classmethod
    def calculate_hinge_width(cls, bend_radius: float, bend_angle_deg: float) -> float:
        """Calculates the theoretical arc length required for a given bend radius and angle: L = R * theta."""
        rad = math.radians(abs(bend_angle_deg))
        return bend_radius * rad

    @classmethod
    def generate_straight_lattice(
        cls,
        width: float,
        height: float,
        cut_length: float = 12.0,
        gap_length: float = 1.8,
        column_spacing: float = 2.0,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> List[List[Tuple[float, float]]]:
        """
        Generates standard alternating straight slit cut paths.
        Odd and even columns have staggered cuts so material bends with zero grain stress.
        """
        if width <= 0 or height <= 0 or column_spacing <= 0:
            return []

        col_count = max(2, int(round(width / column_spacing)))
        actual_col_spacing = width / float(col_count)
        pitch = cut_length + gap_length

        contours: List[List[Tuple[float, float]]] = []

        for c in range(col_count + 1):
            x = origin_x + c * actual_col_spacing
            is_odd = (c % 2 == 1)

            # Stagger offset for alternating columns
            y_offset = pitch / 2.0 if is_odd else 0.0

            cur_y = origin_y - y_offset
            while cur_y < origin_y + height:
                seg_start_y = max(origin_y, cur_y)
                seg_end_y = min(origin_y + height, cur_y + cut_length)

                if seg_end_y - seg_start_y > 1.0:  # Minimum cut length threshold
                    contours.append([(x, seg_start_y), (x, seg_end_y)])

                cur_y += pitch

        return contours

    @classmethod
    def generate_wavy_lattice(
        cls,
        width: float,
        height: float,
        wave_amplitude: float = 1.5,
        wave_wavelength: float = 14.0,
        gap_length: float = 2.0,
        column_spacing: float = 3.0,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> List[List[Tuple[float, float]]]:
        """
        Generates sinuous wavy lattice slit curves providing high torsional flex.
        """
        col_count = max(2, int(round(width / column_spacing)))
        actual_col_spacing = width / float(col_count)

        contours: List[List[Tuple[float, float]]] = []
        steps_per_wave = 16

        for c in range(col_count + 1):
            base_x = origin_x + c * actual_col_spacing
            phase_shift = math.pi if (c % 2 == 1) else 0.0

            y = origin_y
            while y < origin_y + height:
                cut_len = wave_wavelength - gap_length
                sub_y_end = min(origin_y + height, y + cut_len)
                if sub_y_end - y > 1.5:
                    pts = []
                    num_pts = max(4, int(round((sub_y_end - y) / (wave_wavelength / steps_per_wave))))
                    for step in range(num_pts + 1):
                        py = y + (step / float(num_pts)) * (sub_y_end - y)
                        rel_y = py - origin_y
                        px = base_x + wave_amplitude * math.sin((2 * math.pi * rel_y / wave_wavelength) + phase_shift)
                        pts.append((px, py))
                    contours.append(pts)

                y += wave_wavelength

        return contours

    @classmethod
    def generate_diamond_lattice(
        cls,
        width: float,
        height: float,
        cell_size: float = 8.0,
        slit_gap: float = 1.5,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> List[List[Tuple[float, float]]]:
        """
        Generates diamond/honeycomb flex cut pattern for 2-axis deformation.
        """
        cols = max(2, int(round(width / cell_size)))
        rows = max(2, int(round(height / cell_size)))
        dx = width / float(cols)
        dy = height / float(rows)

        contours: List[List[Tuple[float, float]]] = []

        for r in range(rows):
            for c in range(cols):
                cx = origin_x + (c + 0.5) * dx
                cy = origin_y + (r + 0.5) * dy
                hx = dx * 0.42
                hy = dy * 0.42

                # Diamond slit cutout with bridges
                p1 = (cx, cy - hy + slit_gap)
                p2 = (cx + hx - slit_gap, cy)
                p3 = (cx, cy + hy - slit_gap)
                p4 = (cx - hx + slit_gap, cy)

                contours.append([p1, p2])
                contours.append([p2, p3])
                contours.append([p3, p4])
                contours.append([p4, p1])

        return contours

    @classmethod
    def generate_hinge_entities(
        cls,
        cfg: LivingHingeConfig,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> List[LaserEntity]:
        """Generates all cut entities for the living hinge."""
        entities: List[LaserEntity] = []

        # Auto-compute width if specified by bend radius
        eff_width = cfg.width
        if cfg.bend_radius > 0 and cfg.bend_angle_deg > 0:
            rec_width = cls.calculate_hinge_width(cfg.bend_radius, cfg.bend_angle_deg)
            if eff_width <= 0:
                eff_width = rec_width

        hinge_ox = origin_x + (cfg.border_tab_width if cfg.add_border_tabs else 0.0)
        hinge_oy = origin_y

        # Generate internal slit cuts
        if cfg.cut_pattern == "wavy":
            slit_contours = cls.generate_wavy_lattice(
                eff_width, cfg.height, gap_length=cfg.gap_length,
                column_spacing=cfg.column_spacing, origin_x=hinge_ox, origin_y=hinge_oy
            )
        elif cfg.cut_pattern == "diamond":
            slit_contours = cls.generate_diamond_lattice(
                eff_width, cfg.height, cell_size=cfg.cut_length,
                slit_gap=cfg.gap_length, origin_x=hinge_ox, origin_y=hinge_oy
            )
        else:
            # Default straight alternating lattice
            slit_contours = cls.generate_straight_lattice(
                eff_width, cfg.height, cut_length=cfg.cut_length,
                gap_length=cfg.gap_length, column_spacing=cfg.column_spacing,
                origin_x=hinge_ox, origin_y=hinge_oy
            )

        if slit_contours:
            entities.append(PathEntity(
                layer_id=cfg.layer_id,
                name="Living_Hinge_Slits",
                x=0.0,
                y=0.0,
                contours=slit_contours,
                closed=False
            ))

        # Add outer perimeter / solid mounting borders if requested
        if cfg.add_border_tabs:
            total_w = eff_width + cfg.border_tab_width * 2.0
            border_outline = [
                (origin_x, origin_y),
                (origin_x + total_w, origin_y),
                (origin_x + total_w, origin_y + cfg.height),
                (origin_x, origin_y + cfg.height),
                (origin_x, origin_y)
            ]
            entities.append(PathEntity(
                layer_id=cfg.layer_id,
                name="Living_Hinge_Perimeter",
                x=0.0,
                y=0.0,
                contours=[border_outline],
                closed=True
            ))

        return entities
