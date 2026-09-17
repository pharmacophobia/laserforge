"""
LaserForge Parametric Material Test Card & Calibration Grid Generator.
Generates an automated 2D matrix of test patches varying Speed vs Power,
with single-line Hershey stroke text labels and optional perimeter cutout frame.
"""

from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
import math

from laserforge.core.models import LaserEntity, RectEntity, PathEntity, LineEntity
from laserforge.core.hershey_font import HersheyFont


@dataclass
class MaterialTestGridConfig:
    min_speed: float = 200.0        # mm/min
    max_speed: float = 2000.0       # mm/min
    speed_steps: int = 5            # Number of rows
    min_power: float = 10.0         # Percent (0-100)
    max_power: float = 100.0        # Percent (0-100)
    power_steps: int = 5            # Number of columns
    patch_width: float = 8.0        # mm
    patch_height: float = 8.0       # mm
    patch_gap: float = 2.5          # mm
    test_mode: str = "fill"         # "fill", "cut", "both"
    hatch_interval: float = 0.2     # mm between hatch lines for fill mode
    include_labels: bool = True
    label_font_size: float = 2.8    # mm
    title_text: str = "LaserForge Material Matrix"
    include_frame: bool = True      # Outer perimeter cutout border
    frame_margin: float = 4.0       # mm margin around matrix
    base_layer_id: int = 0          # Target layer for patches
    label_layer_id: int = 0         # Target layer for labels
    frame_layer_id: int = 1         # Target layer for outer frame cutout


class MaterialTestGenerator:
    """Parametric generator for Speed vs Power laser calibration matrices."""

    @classmethod
    def generate_grid(
        cls,
        cfg: MaterialTestGridConfig,
        origin_x: float = 10.0,
        origin_y: float = 10.0
    ) -> List[LaserEntity]:
        entities: List[LaserEntity] = []

        cols = max(1, cfg.power_steps)
        rows = max(1, cfg.speed_steps)

        # Calculate speed values for rows (Y axis) and power values for columns (X axis)
        if cols > 1:
            power_vals = [cfg.min_power + i * (cfg.max_power - cfg.min_power) / (cols - 1) for i in range(cols)]
        else:
            power_vals = [cfg.min_power]

        if rows > 1:
            speed_vals = [cfg.min_speed + j * (cfg.max_speed - cfg.min_speed) / (rows - 1) for j in range(rows)]
        else:
            speed_vals = [cfg.min_speed]

        # Layout margins for labels
        label_margin_left = 22.0 if cfg.include_labels else 2.0
        label_margin_bottom = 12.0 if cfg.include_labels else 2.0
        header_margin_top = 10.0 if (cfg.include_labels and cfg.title_text) else 2.0

        grid_start_x = origin_x + label_margin_left
        grid_start_y = origin_y + label_margin_bottom

        # 1. Generate Test Patches
        for r_idx, speed in enumerate(speed_vals):
            y = grid_start_y + r_idx * (cfg.patch_height + cfg.patch_gap)
            for c_idx, power in enumerate(power_vals):
                x = grid_start_x + c_idx * (cfg.patch_width + cfg.patch_gap)

                patch_name = f"TestPatch_S{int(speed)}_P{int(power)}"

                # Outer border of patch
                rect = RectEntity(
                    layer_id=cfg.base_layer_id,
                    name=patch_name,
                    x=x,
                    y=y,
                    width=cfg.patch_width,
                    height=cfg.patch_height
                )
                # Assign per-entity speed and power overrides
                rect.speed_override = float(speed)
                rect.power_override = float(power)
                entities.append(rect)

                # If fill mode, add internal hatch paths
                if cfg.test_mode in ("fill", "both"):
                    hatch_contours = []
                    hy = y + cfg.hatch_interval
                    while hy < y + cfg.patch_height - (cfg.hatch_interval * 0.5):
                        hatch_contours.append([(x + 0.1, hy), (x + cfg.patch_width - 0.1, hy)])
                        hy += cfg.hatch_interval

                    if hatch_contours:
                        hatch_ent = PathEntity(
                            layer_id=cfg.base_layer_id,
                            name=f"{patch_name}_Hatch",
                            x=0.0,
                            y=0.0,
                            contours=hatch_contours,
                            closed=False
                        )
                        hatch_ent.speed_override = float(speed)
                        hatch_ent.power_override = float(power)
                        entities.append(hatch_ent)

        # 2. Labels (Single-Line Stroke Hershey Text)
        if cfg.include_labels:
            # Power column headers (at bottom of each column)
            for c_idx, power in enumerate(power_vals):
                cx = grid_start_x + c_idx * (cfg.patch_width + cfg.patch_gap)
                lbl_text = f"{int(power)}%"
                lbl_ent = HersheyFont.create_entity(
                    text=lbl_text,
                    x=cx,
                    y=origin_y + 3.0,
                    font_size_mm=cfg.label_font_size,
                    layer_id=cfg.label_layer_id,
                    name=f"Label_P{int(power)}"
                )
                if lbl_ent:
                    entities.append(lbl_ent)

            # Speed row headers (at left of each row)
            for r_idx, speed in enumerate(speed_vals):
                ry = grid_start_y + r_idx * (cfg.patch_height + cfg.patch_gap) + (cfg.patch_height * 0.25)
                lbl_text = f"{int(speed)}"
                lbl_ent = HersheyFont.create_entity(
                    text=lbl_text,
                    x=origin_x + 1.0,
                    y=ry,
                    font_size_mm=cfg.label_font_size,
                    layer_id=cfg.label_layer_id,
                    name=f"Label_S{int(speed)}"
                )
                if lbl_ent:
                    entities.append(lbl_ent)

            # Axis titles
            p_axis_lbl = HersheyFont.create_entity(
                text="POWER %",
                x=grid_start_x,
                y=origin_y + 0.5,
                font_size_mm=cfg.label_font_size * 0.8,
                layer_id=cfg.label_layer_id,
                name="Title_PowerAxis"
            )
            if p_axis_lbl:
                entities.append(p_axis_lbl)

            s_axis_lbl = HersheyFont.create_entity(
                text="SPEED mm/m",
                x=origin_x + 1.0,
                y=grid_start_y + rows * (cfg.patch_height + cfg.patch_gap) + 1.0,
                font_size_mm=cfg.label_font_size * 0.8,
                layer_id=cfg.label_layer_id,
                name="Title_SpeedAxis"
            )
            if s_axis_lbl:
                entities.append(s_axis_lbl)

            # Header title
            if cfg.title_text:
                top_y = grid_start_y + rows * (cfg.patch_height + cfg.patch_gap) + 4.0
                hdr_ent = HersheyFont.create_entity(
                    text=cfg.title_text,
                    x=grid_start_x,
                    y=top_y,
                    font_size_mm=cfg.label_font_size * 1.1,
                    layer_id=cfg.label_layer_id,
                    name="Title_Header"
                )
                if hdr_ent:
                    entities.append(hdr_ent)

        # 3. Outer Frame Cutout
        if cfg.include_frame:
            matrix_w = label_margin_left + cols * (cfg.patch_width + cfg.patch_gap) + cfg.frame_margin
            matrix_h = label_margin_bottom + rows * (cfg.patch_height + cfg.patch_gap) + header_margin_top + cfg.frame_margin
            frame_rect = RectEntity(
                layer_id=cfg.frame_layer_id,
                name="Material_Test_Outer_Cutout",
                x=origin_x - cfg.frame_margin * 0.5,
                y=origin_y - cfg.frame_margin * 0.5,
                width=matrix_w,
                height=matrix_h
            )
            entities.append(frame_rect)

        return entities
