"""
LaserForge Automated Kerf Test Gauge Generator.
Generates an interlocking precision test gauge with stepped slot widths and engraved labels
to determine a laser's exact beam kerf on any sheet material in under 60 seconds.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
import math

from laserforge.core.models import LaserEntity, PathEntity, RectEntity
from laserforge.core.hershey_font import HersheyFont


@dataclass
class KerfTestSettings:
    """Settings for parametric kerf test gauge generation."""
    material_thickness_mm: float = 3.0   # Nominal sheet thickness (e.g. 3.0mm acrylic/plywood)
    start_kerf_mm: float = 0.06          # Minimum kerf allowance to test
    kerf_step_mm: float = 0.02           # Step increment between test slots
    slot_count: int = 10                 # Number of test slots (e.g. 0.06 to 0.24 mm)
    slot_depth_mm: float = 12.0          # Depth of each test slot
    tooth_width_mm: float = 6.0          # Spacing / tooth width between slots
    base_height_mm: float = 16.0         # Height of solid base below slots
    margin_x_mm: float = 8.0             # Outer side margins
    cut_layer_id: int = 0                # Layer for perimeter cutting
    engrave_layer_id: int = 1            # Layer for numerical label engraving
    font_size_mm: float = 3.2            # Size of engraved kerf labels


class KerfTestGenerator:
    """
    Parametric CAM generator for laser kerf measurement gauges.
    Produces an interlocking gauge block and mating test feeler tongue.
    """

    @classmethod
    def generate(cls, settings: Optional[KerfTestSettings] = None) -> List[LaserEntity]:
        if settings is None:
            settings = KerfTestSettings()

        t_nom = max(0.5, settings.material_thickness_mm)
        count = max(3, min(25, settings.slot_count))
        slot_depth = max(4.0, settings.slot_depth_mm)
        tooth_w = max(2.0, settings.tooth_width_mm)
        base_h = max(5.0, settings.base_height_mm)
        margin_x = max(4.0, settings.margin_x_mm)
        step = max(0.005, settings.kerf_step_mm)
        k_start = max(0.0, settings.start_kerf_mm)

        # 1. Calculate slot widths: slot_w = t_nom - kerf_val
        # The laser kerf burns away material from both sides of the tongue and slot.
        # A slot designed for kerf K has nominal width (t_nom - K).
        # When cut with real kerf K, the actual physical gap cut will be (t_nom - K) + K = t_nom,
        # perfectly matching the nominal tongue thickness!
        kerf_values = [k_start + i * step for i in range(count)]
        slot_widths = [max(0.2, t_nom - k) for k in kerf_values]

        total_slots_width = sum(slot_widths) + (count - 1) * tooth_w
        comb_width = margin_x * 2.0 + total_slots_width
        comb_height = base_h + slot_depth

        # 2. Build the Comb Perimeter Contour
        # Starting from bottom-left (0, 0)
        comb_pts: List[Tuple[float, float]] = [
            (0.0, 0.0),
            (comb_width, 0.0),
            (comb_width, comb_height),
        ]

        curr_x = comb_width - margin_x
        # Walk along top edge from right to left carving the slots
        for i in reversed(range(count)):
            sw = slot_widths[i]
            # Top right of tooth/slot
            comb_pts.append((curr_x, comb_height))
            # Down into slot
            comb_pts.append((curr_x, base_h))
            # Across slot bottom
            comb_pts.append((curr_x - sw, base_h))
            # Up out of slot
            comb_pts.append((curr_x - sw, comb_height))

            curr_x -= sw
            if i > 0:
                curr_x -= tooth_w

        comb_pts.append((0.0, comb_height))
        comb_pts.append((0.0, 0.0))

        comb_entity = PathEntity(
            layer_id=settings.cut_layer_id,
            name="Kerf_Gauge_Comb",
            x=10.0,
            y=10.0,
            contours=[comb_pts],
            closed=True
        )

        # 3. Generate Engraved Labels for each slot
        label_contours: List[List[Tuple[float, float]]] = []
        curr_x = margin_x
        for i in range(count):
            sw = slot_widths[i]
            k_val = kerf_values[i]
            slot_center_x = 10.0 + curr_x + sw / 2.0
            label_y = 10.0 + (base_h / 2.0) - (settings.font_size_mm / 2.0)

            # Text: e.g. ".14" or "0.14"
            text_str = f"{k_val:.2f}"
            # Render using Hershey single-line stroke font
            chars_paths = HersheyFont.render_text(
                text=text_str,
                font_size_mm=settings.font_size_mm,
                x=0.0,
                y=0.0
            )
            # Center text horizontally below the slot
            if chars_paths:
                all_xs = [pt[0] for path in chars_paths for pt in path]
                if all_xs:
                    text_w = max(all_xs) - min(all_xs)
                    tx_offset = slot_center_x - (text_w / 2.0)
                    for path in chars_paths:
                        shifted = [(tx_offset + pt[0], label_y + pt[1]) for pt in path]
                        label_contours.append(shifted)

            curr_x += sw + tooth_w

        # Also add title text "KERF TEST (mm)" on the base
        title_paths = HersheyFont.render_text(
            text="KERF GAUGE",
            font_size_mm=settings.font_size_mm * 0.9,
            x=10.0 + margin_x,
            y=10.0 + 3.0
        )
        label_contours.extend(title_paths)

        label_entity = PathEntity(
            layer_id=settings.engrave_layer_id,
            name="Kerf_Labels",
            x=0.0,
            y=0.0,
            contours=label_contours,
            closed=False
        )

        # 4. Generate Mating Feeler Tongue (Key)
        # Positioned neatly 8mm above the comb
        tongue_w = t_nom
        tongue_h = slot_depth * 1.5
        handle_w = tongue_w + 12.0
        handle_h = 10.0

        key_x = 10.0 + comb_width + 12.0
        key_y = 10.0

        # T-shaped key handle and feeler blade
        # Width: handle_w, blade height: tongue_h
        kw_half = handle_w / 2.0
        bw_half = tongue_w / 2.0

        blade_pts = [
            (kw_half - bw_half, 0.0),
            (kw_half + bw_half, 0.0),
            (kw_half + bw_half, tongue_h),
            (handle_w, tongue_h),
            (handle_w, tongue_h + handle_h),
            (0.0, tongue_h + handle_h),
            (0.0, tongue_h),
            (kw_half - bw_half, tongue_h),
            (kw_half - bw_half, 0.0)
        ]

        key_entity = PathEntity(
            layer_id=settings.cut_layer_id,
            name="Kerf_Test_Tongue",
            x=key_x,
            y=key_y,
            contours=[blade_pts],
            closed=True
        )

        # Label on key handle: "T: 3.0mm"
        t_label_paths = HersheyFont.render_text(
            text=f"T:{t_nom:.1f}",
            font_size_mm=settings.font_size_mm * 0.9,
            x=key_x + 2.0,
            y=key_y + tongue_h + 3.0
        )
        key_label_entity = PathEntity(
            layer_id=settings.engrave_layer_id,
            name="Tongue_Label",
            x=0.0,
            y=0.0,
            contours=t_label_paths,
            closed=False
        )

        return [comb_entity, label_entity, key_entity, key_label_entity]
