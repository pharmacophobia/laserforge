"""
LaserForge 3D Relief Engraving & Automated Z-Axis Step-Down Engine.
Generates multi-pass depth-stepping coordinates and heightmap slicing for 3D laser carving.
"""

from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
import numpy as np
from PIL import Image

from laserforge.core.models import PathEntity, LaserEntity, LayerCutSettings


@dataclass
class ZStepConfig:
    total_depth_mm: float = 3.0      # Total target cutting/carving depth in mm
    pass_count: int = 3              # Number of passes
    step_down_mm: float = 1.0        # Depth increment per pass in mm
    retract_z_mm: float = 5.0        # Rapid travel safe clearance height
    initial_z_offset_mm: float = 0.0 # Focal point surface shift


@dataclass
class ReliefCarveConfig:
    width_mm: float = 80.0
    height_mm: float = 80.0
    max_depth_mm: float = 2.0        # Max physical carving depth
    z_slices: int = 5                # Number of discrete Z-level passes
    min_power: float = 10.0
    max_power: float = 90.0
    feedrate_mm_min: float = 1500.0
    line_interval_mm: float = 0.25   # Scanline spacing
    invert_heightmap: bool = False   # True: darker = deeper; False: lighter = deeper
    layer_id: int = 0


class ReliefEngine:
    """Calculates multi-pass Z-table descent and converts heightmaps into 3D laser toolpaths."""

    @staticmethod
    def calculate_pass_z_levels(cfg: ZStepConfig) -> List[float]:
        """
        Computes the Z coordinate for each cutting pass.
        Z moves downwards (negative values in standard CNC coordinates, e.g. Z0 -> Z-1 -> Z-2).
        """
        if cfg.pass_count <= 1:
            return [-(cfg.initial_z_offset_mm)]

        levels = []
        for p in range(cfg.pass_count):
            z = -(cfg.initial_z_offset_mm + p * cfg.step_down_mm)
            levels.append(round(z, 3))
        return levels

    @classmethod
    def generate_relief_scanlines(
        cls,
        image: Image.Image,
        cfg: ReliefCarveConfig,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> Dict[str, Any]:
        """
        Slices a grayscale heightmap image into discrete Z-levels or variable-power scanlines.
        Returns toolpath line segments with (x, y, z, power) tuples.
        """
        # Convert to grayscale 8-bit
        gray = image.convert("L")
        img_w, img_h = gray.size

        # Compute number of horizontal scanlines
        num_lines = max(2, int(round(cfg.height_mm / cfg.line_interval_mm)))
        dy = cfg.height_mm / float(num_lines)

        # Scale image to scanline grid resolution
        samples_per_line = max(10, int(round(cfg.width_mm / cfg.line_interval_mm)))
        dx = cfg.width_mm / float(samples_per_line)

        resampled = gray.resize((samples_per_line, num_lines), Image.Resampling.BILINEAR)
        img_arr = np.array(resampled, dtype=np.float32) / 255.0  # 0.0 to 1.0

        if cfg.invert_heightmap:
            img_arr = 1.0 - img_arr

        # Slices: for each Z slice, generate scanline segments
        slices_data = []
        z_step = cfg.max_depth_mm / float(max(1, cfg.z_slices))

        for s_idx in range(cfg.z_slices):
            target_z = -round((s_idx + 1) * z_step, 3)
            # Threshold for this depth level
            level_thresh = (s_idx + 1) / float(cfg.z_slices)
            
            pass_segments = []
            for y_idx in range(num_lines):
                cur_y = origin_y + y_idx * dy
                row = img_arr[y_idx, :]
                
                # Scan alternating left-to-right / right-to-left for bidirectional efficiency
                is_reverse = (y_idx % 2 == 1)
                indices = range(samples_per_line - 1, -1, -1) if is_reverse else range(samples_per_line)
                
                seg_start = None
                for x_idx in indices:
                    val = row[x_idx]
                    cur_x = origin_x + x_idx * dx
                    
                    if val >= level_thresh:
                        if seg_start is None:
                            seg_start = cur_x
                    else:
                        if seg_start is not None:
                            # End of segment
                            pass_segments.append(((seg_start, cur_y), (cur_x, cur_y)))
                            seg_start = None
                
                if seg_start is not None:
                    last_x = origin_x if is_reverse else (origin_x + cfg.width_mm)
                    pass_segments.append(((seg_start, cur_y), (last_x, cur_y)))

            slices_data.append({
                "slice_index": s_idx,
                "z_depth": target_z,
                "segments": pass_segments
            })

        return {
            "slices": slices_data,
            "total_slices": cfg.z_slices,
            "max_depth_mm": cfg.max_depth_mm,
            "dimensions": (cfg.width_mm, cfg.height_mm),
            "estimated_lines": sum(len(s["segments"]) for s in slices_data)
        }
