"""
LaserForge G-Code Generator and CAM Processor.
Translates vector geometries, text, and raster images into standard GRBL/Marlin G-code.
Computes estimated job execution times and exports toolpath vectors for the visual simulation viewer.
"""

from typing import List, Dict, Tuple, Any, Optional
import math
import os
from dataclasses import dataclass
from PIL import Image

from laserforge.config import MachineSettings
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity, LayerCutSettings
)
from laserforge.core.layer_manager import LayerManager
from laserforge.core.optimizer import PathOptimizer
from laserforge.core.raster_processor import RasterProcessor
from laserforge.core.kerf_engine import KerfEngine
from laserforge.core.rotary_engine import RotaryEngine
from laserforge.core.tab_engine import TabEngine

@dataclass(slots=True)
class ToolpathSegment:
    move_type: str  # "rapid" (G0) or "cut" (G1)
    x1: float
    y1: float
    x2: float
    y2: float
    feedrate: float
    power_pct: float
    layer_id: int
    color: str

@dataclass(slots=True)
class GCodeJobResult:
    gcode: str
    segments: List[ToolpathSegment]
    total_cut_dist_mm: float
    total_rapid_dist_mm: float
    estimated_time_sec: float
    bounding_box: Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)

class GCodeGenerator:

    def __init__(self, settings: MachineSettings, layer_manager: LayerManager):
        self.settings = settings
        self.layer_manager = layer_manager

    def _laser_on_cmd(self, power: int) -> str:
        mode = getattr(self.settings, "laser_mode", "M4")
        if mode == "M106":
            return f"M106 S{power}"
        return f"{mode} S{power}"

    def _laser_off_cmd(self) -> str:
        mode = getattr(self.settings, "laser_mode", "M4")
        if mode == "M106":
            return "M107"
        return "M5"

    def entity_to_paths(self, entity: LaserEntity) -> List[List[Tuple[float, float]]]:
        """Converts an entity into a list of vector point contours (x, y)."""
        paths = []

        if isinstance(entity, RectEntity):
            x, y, w, h = entity.x, entity.y, entity.width, entity.height
            rot_rad = math.radians(entity.rotation)

            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            if rot_rad != 0:
                cx, cy = x + w / 2.0, y + h / 2.0
                pts = [self._rotate_pt(px, py, cx, cy, rot_rad) for px, py in pts]
            paths.append(pts)

        elif isinstance(entity, CircleEntity):
            cx, cy = entity.x, entity.y
            rx, ry = entity.radius_x, entity.radius_y
            num_pts = max(24, int(math.pi * max(rx, ry)))
            pts = []
            rot_rad = math.radians(entity.rotation)
            for i in range(num_pts + 1):
                ang = 2.0 * math.pi * (i % num_pts) / num_pts
                px = cx + rx * math.cos(ang)
                py = cy + ry * math.sin(ang)
                if rot_rad != 0:
                    px, py = self._rotate_pt(px, py, cx, cy, rot_rad)
                pts.append((px, py))
            paths.append(pts)

        elif isinstance(entity, LineEntity):
            paths.append([(entity.x, entity.y), (entity.x2, entity.y2)])

        elif isinstance(entity, PathEntity):
            rot_rad = math.radians(entity.rotation)
            b = entity.get_bounds()
            cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
            for c in entity.contours:
                if len(c) > 1:
                    world_c = []
                    for px, py in c:
                        wx = entity.x + px
                        wy = entity.y + py
                        if rot_rad != 0:
                            wx, wy = self._rotate_pt(wx, wy, cx, cy, rot_rad)
                        world_c.append((wx, wy))
                    paths.append(world_c)

        elif isinstance(entity, TextEntity):
            # Extract real vector font glyph outlines via QPainterPath
            try:
                from PyQt6.QtGui import QPainterPath, QFont, QFontMetricsF
                from PyQt6.QtCore import QPointF
                font = QFont(entity.font_family, max(6, int(round(entity.font_size * 2.835))))
                font.setBold(entity.bold)
                font.setItalic(entity.italic)
                font.setUnderline(getattr(entity, "underline", False))
                fm = QFontMetricsF(font)
                p = QPainterPath()
                # Center text vertically within entity bounding box or place baseline
                baseline_y = entity.y + (entity.height - fm.height()) / 2.0 + fm.ascent()
                p.addText(QPointF(entity.x, baseline_y), font, entity.text)
                rot_rad = math.radians(entity.rotation)
                cx, cy = entity.x + entity.width / 2.0, entity.y + entity.height / 2.0
                found_poly = False
                for poly in p.toSubpathPolygons():
                    poly_pts = [(pt.x(), pt.y()) for pt in poly]
                    if getattr(entity, "is_mirrored_h", False):
                        poly_pts = [(2.0 * cx - px, py) for px, py in poly_pts]
                    if getattr(entity, "is_mirrored_v", False):
                        poly_pts = [(px, 2.0 * cy - py) for px, py in poly_pts]
                    if rot_rad != 0:
                        poly_pts = [self._rotate_pt(px, py, cx, cy, rot_rad) for px, py in poly_pts]
                    if len(poly_pts) > 1:
                        paths.append(poly_pts)
                        found_poly = True
                if not found_poly:
                    x, y, w, h = entity.x, entity.y, entity.width, entity.height
                    paths.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
            except Exception:
                x, y, w, h = entity.x, entity.y, entity.width, entity.height
                paths.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])

        return paths

    def _rotate_pt(self, px: float, py: float, cx: float, cy: float, rad: float) -> Tuple[float, float]:
        dx, dy = px - cx, py - cy
        rx = cx + dx * math.cos(rad) - dy * math.sin(rad)
        ry = cy + dx * math.sin(rad) + dy * math.cos(rad)
        return (rx, ry)

    def generate_fill_scanlines(
        self,
        polygon: List[Tuple[float, float]],
        interval_mm: float
    ) -> List[Tuple[float, float, float]]:
        """Generates optimized horizontal fill scanlines intersecting polygon."""
        if len(polygon) < 3:
            return []

        # Pre-extract valid non-horizontal edges
        edges = []
        n = len(polygon)
        min_y = float("inf")
        max_y = float("-inf")
        for i in range(n):
            p1 = polygon[i]
            p2 = polygon[(i + 1) % n]
            ey1 = min(p1[1], p2[1])
            ey2 = max(p1[1], p2[1])
            min_y = min(min_y, ey1)
            max_y = max(max_y, ey2)
            if ey2 - ey1 > 1e-6:
                edges.append((ey1, ey2, p1, p2))

        scanlines = []
        cur_y = min_y + interval_mm / 2.0
        row = 0

        while cur_y <= max_y:
            intersections = []
            for ey1, ey2, p1, p2 in edges:
                if ey1 <= cur_y < ey2:
                    t = (cur_y - p1[1]) / (p2[1] - p1[1])
                    inter_x = p1[0] + t * (p2[0] - p1[0])
                    intersections.append(inter_x)

            intersections.sort()

            # Fix #2: Deduplicate intersections within epsilon to handle vertices
            # exactly on the scanline (tangent points, horizontal edge endpoints)
            # which can produce spurious duplicate intersection values.
            if len(intersections) > 1:
                deduped = [intersections[0]]
                for ix in intersections[1:]:
                    if abs(ix - deduped[-1]) > 1e-6:
                        deduped.append(ix)
                intersections = deduped

            # Odd count after dedup means a degenerate polygon (e.g. scanline
            # passes through a cusp). Skip this scanline to avoid mismatched pairs.
            if len(intersections) % 2 != 0:
                cur_y += interval_mm
                row += 1
                continue

            reverse = (row % 2 == 1)
            segments = []
            for j in range(0, len(intersections) - 1, 2):
                x1 = intersections[j]
                x2 = intersections[j + 1]
                if reverse:
                    segments.append((x2, x1, cur_y))
                else:
                    segments.append((x1, x2, cur_y))

            if reverse:
                segments.reverse()

            for s in segments:
                scanlines.append(s)

            cur_y += interval_mm
            row += 1

        return scanlines


    def generate_job(self, entities: List[LaserEntity]) -> GCodeJobResult:
        """Translates the canvas entities into complete G-code and visual toolpaths."""
        gcode_lines = []
        segments = []
        total_cut_dist = 0.0
        total_rapid_dist = 0.0
        total_time_sec = 0.0

        cur_x, cur_y = 0.0, 0.0
        job_start_x, job_start_y = 0.0, 0.0
        job_start_captured = False  # Fix #1: track whether we've recorded the real first cut position

        # Calculate bounding box
        all_x, all_y = [], []

        # Header
        gcode_lines.append("; =================================================")
        gcode_lines.append("; Generated by LaserForge CAD/CAM for GRBL")
        gcode_lines.append("; =================================================")
        gcode_lines.append("G21          ; Set units to millimeters")
        gcode_lines.append("G90          ; Absolute positioning")
        gcode_lines.append(f"{self._laser_off_cmd()}          ; Ensure laser is OFF")
        if self.settings.enable_z_moves:
            gcode_lines.append(f"G0 Z0 F{self.settings.rapid_speed:.0f} ; Safe Z")

        # Rotary Axis Telemetry Header
        if getattr(self.settings, "rotary_enabled", False):
            rot_type = getattr(self.settings, "rotary_type", "Roller")
            rot_mode = getattr(self.settings, "rotary_mode", "Software Scaling")
            rot_diam = getattr(self.settings, "rotary_object_diameter", 65.0)
            circ = RotaryEngine.compute_circumference(rot_diam)
            rot_scale = RotaryEngine.calculate_software_scale_factor(self.settings) if rot_mode == "Software Scaling" else 1.0
            gcode_lines.append(f"; --- Rotary Axis Active: {rot_type} ({rot_mode}) ---")
            gcode_lines.append(f"; Workpiece Diameter: {rot_diam:.1f} mm, Circumference: {circ:.1f} mm")
            if rot_mode == "Software Scaling":
                gcode_lines.append(f"; Software Y-Scaling Factor: {rot_scale:.5f}")

        # Custom Start G-Code
        start_script = getattr(self.settings, "custom_start_gcode", "").strip()
        if start_script:
            gcode_lines.append("; --- Custom Start G-Code ---")
            for line in start_script.splitlines():
                cl = line.strip()
                if cl:
                    gcode_lines.append(cl)

        # Group entities by layer
        layer_groups: Dict[int, List[LaserEntity]] = {}
        for ent in entities:
            layer = self.layer_manager.get_layer(ent.layer_id)
            if layer.output_enabled and not layer.is_tool:
                layer_groups.setdefault(ent.layer_id, []).append(ent)

        laser_cmd = self.settings.laser_mode  # M4 or M3
        max_s = self.settings.max_s_value

        # Process each layer in order
        for lid in sorted(layer_groups.keys()):
            layer = self.layer_manager.get_layer(lid)
            group_entities = layer_groups[lid]

            gcode_lines.append(f"\n; --- Layer {layer.name} ({layer.color}) Mode: {layer.mode} ---")
            if layer.air_assist:
                gcode_lines.append(f"{self.settings.air_assist_cmd} ; Air Assist ON")
                pre_delay = getattr(self.settings, "air_assist_pre_delay_sec", 0.0)
                if pre_delay > 0.0:
                    gcode_lines.append(f"G4 P{pre_delay:.1f} ; Air Assist Pre-delay")

            passes = max(1, layer.passes)
            feed = layer.speed
            s_power = int(round((layer.power_max / 100.0) * max_s))

            for pass_idx in range(passes):
                if passes > 1:
                    gcode_lines.append(f"; Pass {pass_idx + 1}/{passes}")
                    if self.settings.enable_z_moves and layer.z_step != 0:
                        z_val = -(pass_idx * layer.z_step)
                        gcode_lines.append(f"G0 Z{z_val:.3f}")
                    if pass_idx > 0 and getattr(layer, "pass_delay_sec", 0.0) > 0.0:
                        delay = layer.pass_delay_sec
                        gcode_lines.append(f"M5 ; 3W Diode Cooldown")
                        gcode_lines.append(f"G4 P{delay:.1f} ; Pause {delay:.1f}s between passes")


                # 1. IMAGE MODE
                image_entities = [e for e in group_entities if isinstance(e, ImageEntity)]
                for img_ent in image_entities:
                    source_img_path = getattr(img_ent, "raw_image_path", "")
                    if not source_img_path or not os.path.exists(source_img_path):
                        source_img_path = img_ent.image_path or getattr(img_ent, "processed_image_path", "")
                    if not source_img_path or not os.path.exists(source_img_path):
                        continue
                    try:
                        pil_img = Image.open(source_img_path)
                        if getattr(img_ent, "is_mirrored_h", False) or getattr(self.settings, "software_mirror_x", False):
                            pil_img = pil_img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                        if getattr(img_ent, "is_mirrored_v", False) or getattr(self.settings, "software_mirror_y", False):
                            pil_img = pil_img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

                        eff_origin_x = (self.settings.bed_width - (img_ent.x + img_ent.width)) if getattr(self.settings, "software_mirror_x", False) else img_ent.x
                        eff_origin_y = (self.settings.bed_height - (img_ent.y + img_ent.height)) if getattr(self.settings, "software_mirror_y", False) else img_ent.y

                        raster_arr = RasterProcessor.process_image(
                            pil_img,
                            target_width_mm=img_ent.width,
                            target_height_mm=img_ent.height,
                            line_interval_mm=layer.line_interval,
                            mode=img_ent.dither_mode,
                            invert=img_ent.invert,
                            contrast=img_ent.contrast,
                            brightness=img_ent.brightness,
                            threshold_val=img_ent.threshold_value,
                            gamma=getattr(img_ent, "gamma", 1.0),
                            sharpen=getattr(img_ent, "sharpen", 0.0),
                            equalize=getattr(img_ent, "equalize", False),
                            white_clip=getattr(img_ent, "white_clip", 255),
                            black_clip=getattr(img_ent, "black_clip", 0),
                            halftone_cell_size=getattr(img_ent, "halftone_cell_size", 6.0),
                            halftone_angle_deg=getattr(img_ent, "halftone_angle_deg", 45.0)
                        )

                        flood_fill_en = getattr(self.settings, "flood_fill_enabled", True)
                        flood_fill_sep = getattr(self.settings, "flood_fill_separation_mm", 12.0)

                        if flood_fill_en:
                            islands = RasterProcessor.extract_raster_islands(
                                raster_arr,
                                origin_x_mm=eff_origin_x,
                                origin_y_mm=eff_origin_y,
                                line_interval_mm=layer.line_interval,
                                min_separation_mm=flood_fill_sep
                            )
                            # Greedy nearest-neighbor ordering of islands
                            ordered_islands = []
                            unvisited = list(islands)
                            curr_pos = (cur_x, cur_y)
                            while unvisited:
                                best_idx = min(
                                    range(len(unvisited)),
                                    key=lambda i: math.hypot(
                                        unvisited[i]["origin_x_mm"] - curr_pos[0],
                                        unvisited[i]["origin_y_mm"] - curr_pos[1]
                                    )
                                )
                                isl = unvisited.pop(best_idx)
                                ordered_islands.append(isl)
                                curr_pos = (isl["origin_x_mm"] + isl["width_mm"], isl["origin_y_mm"] + isl["height_mm"])
                        else:
                            ordered_islands = [{
                                "sub_array": raster_arr,
                                "origin_x_mm": eff_origin_x,
                                "origin_y_mm": eff_origin_y,
                                "width_mm": img_ent.width,
                                "height_mm": img_ent.height
                            }]

                        custom_ws_speed = getattr(self.settings, "raster_fast_whitespace_speed", 0.0)
                        rapid_speed = custom_ws_speed if custom_ws_speed > 100.0 else self.settings.rapid_speed
                        rapid_inv = 60.0 / rapid_speed
                        feed_inv = 60.0 / feed
                        p_scale = (layer.power_max / 100.0) * max_s
                        overscan_en = getattr(self.settings, "overscan_enabled", False)
                        overscan_mode = getattr(self.settings, "overscan_mode", "Acceleration")
                        ov_pct = getattr(self.settings, "overscan_pct", 2.5)
                        ov_fixed = getattr(self.settings, "overscan_mm", 2.0)
                        ov_mult = getattr(self.settings, "overscan_accel_multiplier", 1.2)
                        accel_x = getattr(self.settings, "x_accel", 1000.0)
                        bed_w = getattr(self.settings, "bed_width", 400.0)

                        ws_skip_en = getattr(self.settings, "white_space_skip_enabled", True)
                        ws_threshold = getattr(self.settings, "white_space_skip_threshold_mm", 5.0)

                        fire_dwell = getattr(self.settings, "laser_fire_delay_ms", 0.0)
                        fire_cmd = f"G4 P{fire_dwell / 1000.0:.3f} ; Laser fire dwell" if fire_dwell > 0.0 else ""
                        off_dwell = getattr(self.settings, "laser_off_delay_ms", 0.0)
                        off_cmd = f"G4 P{off_dwell / 1000.0:.3f} ; Laser off dwell" if off_dwell > 0.0 else ""

                        is_m106 = (laser_cmd == "M106")
                        inline_s = getattr(self.settings, "use_inline_power", True) and not is_m106
                        continuous_streaming = getattr(self.settings, "continuous_inline_streaming", True) and inline_s

                        for island_idx, island in enumerate(ordered_islands):
                            scanlines = RasterProcessor.generate_raster_scanlines(
                                island["sub_array"],
                                origin_x_mm=island["origin_x_mm"],
                                origin_y_mm=island["origin_y_mm"],
                                line_interval_mm=layer.line_interval
                            )
                            if not scanlines:
                                continue

                            if inline_s:
                                gcode_lines.append(f"{laser_cmd} ; Dynamic laser mode ON")

                            for line in scanlines:
                                y_val = line["y_mm"]
                                reverse = line["reverse"]
                                raw_line_segs = line["segments"]
                                if not raw_line_segs:
                                    continue

                                all_y.append(y_val)

                                # Cluster segments on this scanline for white-space G0 skipping
                                if ws_skip_en:
                                    clusters = RasterProcessor.cluster_scanline_segments(raw_line_segs, skip_threshold_mm=ws_threshold)
                                else:
                                    clusters = [raw_line_segs]

                                for cluster in clusters:
                                    if not cluster:
                                        continue

                                    c_start_x = cluster[0][0]
                                    c_end_x = cluster[-1][1]
                                    cluster_width = abs(c_end_x - c_start_x)

                                    # Calculate physics-based overscan distance
                                    ov_dist = 0.0
                                    if overscan_en and cluster_width > 0.05:
                                        ov_dist = RasterProcessor.calculate_overscan_distance(
                                            feed_mm_per_min=feed,
                                            accel_mm_per_sec2=accel_x,
                                            mode=overscan_mode,
                                            pct=ov_pct,
                                            fixed_mm=ov_fixed,
                                            cluster_width_mm=cluster_width,
                                            multiplier=ov_mult
                                        )

                                    dir_sign = 1.0 if c_end_x >= c_start_x else -1.0
                                    lead_in_x = c_start_x - (dir_sign * ov_dist)
                                    lead_out_x = c_end_x + (dir_sign * ov_dist)

                                    # Bed boundaries clamping
                                    lead_in_x = max(0.0, min(bed_w, lead_in_x))
                                    lead_out_x = max(0.0, min(bed_w, lead_out_x))

                                    # 1. Rapid directly to lead-in point
                                    rap_dist = math.hypot(lead_in_x - cur_x, y_val - cur_y)
                                    total_rapid_dist += rap_dist
                                    total_time_sec += rap_dist * rapid_inv
                                    if rap_dist > 0.01:
                                        gcode_lines.append(f"G0 X{lead_in_x:.3f} Y{y_val:.3f} F{rapid_speed:.0f}")
                                        segments.append(ToolpathSegment("rapid", cur_x, cur_y, lead_in_x, y_val, rapid_speed, 0, lid, layer.color))
                                        cur_x, cur_y = lead_in_x, y_val
                                    # Fix #1: capture true job start on first cutting move
                                    if not job_start_captured:
                                        job_start_x, job_start_y = cur_x, cur_y
                                        job_start_captured = True

                                    # If not in continuous streaming, toggle laser mode per cluster
                                    if inline_s and not continuous_streaming:
                                        gcode_lines.append(f"{laser_cmd} ; Dynamic laser mode ON")

                                    # 2. Lead-in acceleration with laser OFF
                                    if abs(c_start_x - lead_in_x) > 0.01:
                                        lead_in_dist = abs(c_start_x - lead_in_x)
                                        total_cut_dist += lead_in_dist
                                        total_time_sec += lead_in_dist * feed_inv
                                        if inline_s:
                                            gcode_lines.append(f"G1 X{c_start_x:.3f} Y{y_val:.3f} S0 F{feed:.0f}")
                                        elif is_m106:
                                            gcode_lines.append("M106 S0")
                                            gcode_lines.append(f"G1 X{c_start_x:.3f} Y{y_val:.3f} F{feed:.0f}")
                                        else:
                                            gcode_lines.append(f"G1 X{c_start_x:.3f} Y{y_val:.3f} F{feed:.0f}")
                                        segments.append(ToolpathSegment("lead_in", lead_in_x, y_val, c_start_x, y_val, feed, 0, lid, layer.color))
                                        cur_x = c_start_x

                                    # 3. Burn segments within this cluster
                                    prev_x = c_start_x
                                    for seg_idx, (seg_x1, seg_x2, p_ratio, _) in enumerate(cluster):
                                        all_x.append(seg_x1)
                                        all_x.append(seg_x2)

                                        # Traverse short gap between segments at constant cutting speed with laser OFF (S0)
                                        inter_gap = abs(seg_x1 - prev_x)
                                        if inter_gap > 0.01:
                                            total_cut_dist += inter_gap
                                            total_time_sec += inter_gap * feed_inv
                                            if inline_s:
                                                gcode_lines.append(f"G1 X{seg_x1:.3f} S0")
                                            elif is_m106:
                                                gcode_lines.append("M106 S0")
                                                gcode_lines.append(f"G1 X{seg_x1:.3f} Y{y_val:.3f} F{feed:.0f}")
                                            else:
                                                gcode_lines.append(f"{laser_cmd} S0")
                                                gcode_lines.append(f"G1 X{seg_x1:.3f} Y{y_val:.3f} F{feed:.0f}")
                                            segments.append(ToolpathSegment("glide_gap", prev_x, y_val, seg_x1, y_val, feed, 0, lid, layer.color))
                                            cur_x = seg_x1

                                        # Fire laser and burn segment
                                        seg_p = int(round(p_scale * p_ratio))
                                        seg_len = abs(seg_x2 - seg_x1)
                                        total_cut_dist += seg_len
                                        total_time_sec += seg_len * feed_inv

                                        if inline_s:
                                            gcode_lines.append(f"G1 X{seg_x2:.3f} S{seg_p}")
                                        elif is_m106:
                                            gcode_lines.append(f"M106 S{seg_p}")
                                            if fire_cmd:
                                                gcode_lines.append(fire_cmd)
                                            gcode_lines.append(f"G1 X{seg_x2:.3f} Y{y_val:.3f} F{feed:.0f}")
                                        else:
                                            gcode_lines.append(f"{laser_cmd} S{seg_p}")
                                            if fire_cmd:
                                                gcode_lines.append(fire_cmd)
                                            gcode_lines.append(f"G1 X{seg_x2:.3f} Y{y_val:.3f} F{feed:.0f}")

                                        segments.append(ToolpathSegment("cut", seg_x1, y_val, seg_x2, y_val, feed, (seg_p / max_s) * 100.0, lid, layer.color))
                                        cur_x = seg_x2
                                        prev_x = seg_x2

                                    # 4. Shut laser OFF
                                    if inline_s:
                                        gcode_lines.append("G1 S0")
                                    elif is_m106:
                                        gcode_lines.append("M107")
                                    else:
                                        gcode_lines.append("M5")
                                    if off_cmd:
                                        gcode_lines.append(off_cmd)

                                    # 5. Lead-out deceleration with laser OFF
                                    if abs(lead_out_x - c_end_x) > 0.01:
                                        lead_out_dist = abs(lead_out_x - c_end_x)
                                        total_cut_dist += lead_out_dist
                                        total_time_sec += lead_out_dist * feed_inv
                                        if inline_s:
                                            gcode_lines.append(f"G1 X{lead_out_x:.3f} S0")
                                        else:
                                            gcode_lines.append(f"G1 X{lead_out_x:.3f} Y{y_val:.3f} F{feed:.0f}")
                                        segments.append(ToolpathSegment("lead_out", c_end_x, y_val, lead_out_x, y_val, feed, 0, lid, layer.color))
                                        cur_x = lead_out_x

                                    if inline_s and not continuous_streaming:
                                        gcode_lines.append("M5 S0")

                            if continuous_streaming:
                                gcode_lines.append("G1 S0")
                                gcode_lines.append("M5 S0 ; Continuous Raster Turbo Mode OFF")

                    except Exception as e:
                        gcode_lines.append(f"; Error processing image {img_ent.id}: {e}")

                # 2. VECTOR PATHS (Line, Fill, Fill + Line, Text Modes)
                vector_entities = [e for e in group_entities if not isinstance(e, ImageEntity)]
                raw_fill_paths = []
                raw_fill_meta = []
                raw_line_paths = []
                raw_line_meta = []
                raw_line_closed = []

                for vent in vector_entities:
                    epaths = self.entity_to_paths(vent)
                    if not epaths:
                        continue
                    if getattr(self.settings, "software_mirror_x", False) or getattr(self.settings, "software_mirror_y", False):
                        m_x = getattr(self.settings, "software_mirror_x", False)
                        m_y = getattr(self.settings, "software_mirror_y", False)
                        bw = self.settings.bed_width
                        bh = self.settings.bed_height
                        t_epaths = []
                        for poly in epaths:
                            t_poly = [((bw - px) if m_x else px, (bh - py) if m_y else py) for px, py in poly]
                            t_epaths.append(t_poly)
                        epaths = t_epaths

                    # Check for Rotary software coordinate scaling
                    rot_scale_y = 1.0
                    if getattr(self.settings, "rotary_enabled", False) and getattr(self.settings, "rotary_mode", "Software Scaling") == "Software Scaling":
                        rot_scale_y = RotaryEngine.calculate_software_scale_factor(self.settings)
                    if abs(rot_scale_y - 1.0) > 1e-4:
                        epaths = [[(px, py * rot_scale_y) for px, py in poly] for poly in epaths]

                    # Check for native G2/G3 arc support on CircleEntity (only when not scaled by rotary)
                    arc_data = None
                    if abs(rot_scale_y - 1.0) < 1e-4 and isinstance(vent, CircleEntity) and getattr(self.settings, "enable_arcs", True):
                        rx, ry = vent.radius_x, vent.radius_y
                        if abs(rx - ry) < 1e-3:
                            eff_cx = (self.settings.bed_width - vent.x) if getattr(self.settings, "software_mirror_x", False) else vent.x
                            eff_cy = (self.settings.bed_height - vent.y) if getattr(self.settings, "software_mirror_y", False) else vent.y
                            arc_data = {"cx": eff_cx, "cy": eff_cy, "r": rx}

                    is_closed = getattr(vent, "closed", True) if not isinstance(vent, LineEntity) else False
                    ent_meta = {
                        "entity": vent,
                        "override_speed": getattr(vent, "override_speed", None),
                        "override_power": getattr(vent, "override_power", None),
                        "arc_info": arc_data,
                        "closed": is_closed,
                        "tabs": getattr(vent, "tabs", [])
                    }

                    if isinstance(vent, TextEntity):
                        t_mode = getattr(vent, "fill_mode", "Fill")
                        if t_mode == "Outline":
                            for p in epaths:
                                raw_line_paths.append(p)
                                raw_line_meta.append(ent_meta)
                                raw_line_closed.append(is_closed)
                        elif t_mode == "Fill":
                            for p in epaths:
                                raw_fill_paths.append(p)
                                raw_fill_meta.append(ent_meta)
                            if layer.mode == "Fill + Line":
                                for p in epaths:
                                    raw_line_paths.append(p)
                                    raw_line_meta.append(ent_meta)
                                    raw_line_closed.append(is_closed)
                        else:
                            if layer.mode in ("Fill", "Fill + Line"):
                                for p in epaths:
                                    raw_fill_paths.append(p)
                                    raw_fill_meta.append(ent_meta)
                            if layer.mode in ("Line", "Fill + Line"):
                                for p in epaths:
                                    raw_line_paths.append(p)
                                    raw_line_meta.append(ent_meta)
                                    raw_line_closed.append(is_closed)
                    else:
                        if layer.mode in ("Fill", "Fill + Line"):
                            for p in epaths:
                                raw_fill_paths.append(p)
                                raw_fill_meta.append(ent_meta)
                        if layer.mode in ("Line", "Fill + Line"):
                            for p in epaths:
                                raw_line_paths.append(p)
                                raw_line_meta.append(ent_meta)
                                raw_line_closed.append(is_closed)

                # FILL MODE
                if raw_fill_paths:
                    optimized_fill_paths, optimized_fill_meta = PathOptimizer.optimize_paths(
                        raw_fill_paths, start_pos=(cur_x, cur_y), metadata=raw_fill_meta
                    )
                    interval = max(0.02, layer.line_interval)
                    # Fix #6: F feedrate is modal in GRBL — track and emit only on change
                    current_rapid_feed: float = -1.0
                    current_cut_feed: float = -1.0

                    is_m106 = (laser_cmd == "M106")
                    inline_s = getattr(self.settings, "use_inline_power", True) and not is_m106
                    continuous_streaming = getattr(self.settings, "continuous_inline_streaming", True) and inline_s

                    if continuous_streaming:
                        gcode_lines.append(f"{laser_cmd} S0 ; Fill Turbo Mode ON")

                    for poly, meta in zip(optimized_fill_paths, optimized_fill_meta):
                        # Effective speed and power (per-entity override or layer settings)
                        eff_feed = meta["override_speed"] if (meta and meta.get("override_speed") is not None) else layer.speed
                        eff_p_pct = meta["override_power"] if (meta and meta.get("override_power") is not None) else layer.power_max
                        eff_s_power = int(round((eff_p_pct / 100.0) * max_s))

                        fill_segs = self.generate_fill_scanlines(poly, interval)
                        for seg_x1, seg_x2, seg_y in fill_segs:
                            all_x.extend([seg_x1, seg_x2])
                            all_y.append(seg_y)

                            # Rapid to start
                            rap_dist = math.hypot(seg_x1 - cur_x, seg_y - cur_y)
                            total_rapid_dist += rap_dist
                            total_time_sec += (rap_dist / self.settings.rapid_speed) * 60.0

                            if self.settings.rapid_speed != current_rapid_feed:
                                gcode_lines.append(f"G0 X{seg_x1:.3f} Y{seg_y:.3f} F{self.settings.rapid_speed:.0f}")
                                current_rapid_feed = self.settings.rapid_speed
                            else:
                                gcode_lines.append(f"G0 X{seg_x1:.3f} Y{seg_y:.3f}")
                            segments.append(ToolpathSegment("rapid", cur_x, cur_y, seg_x1, seg_y, self.settings.rapid_speed, 0, lid, layer.color))
                            cur_x, cur_y = seg_x1, seg_y
                            # Fix #1: capture true job start on first cutting move
                            if not job_start_captured:
                                job_start_x, job_start_y = cur_x, cur_y
                                job_start_captured = True

                            # Cut fill stroke
                            cut_dist = abs(seg_x2 - seg_x1)
                            total_cut_dist += cut_dist
                            total_time_sec += (cut_dist / eff_feed) * 60.0

                            if continuous_streaming:
                                if eff_feed != current_cut_feed:
                                    gcode_lines.append(f"G1 X{seg_x2:.3f} Y{seg_y:.3f} S{eff_s_power} F{eff_feed:.0f}")
                                    current_cut_feed = eff_feed
                                else:
                                    gcode_lines.append(f"G1 X{seg_x2:.3f} Y{seg_y:.3f} S{eff_s_power}")
                            else:
                                gcode_lines.append(self._laser_on_cmd(eff_s_power))
                                fire_dwell = getattr(self.settings, "laser_fire_delay_ms", 0.0)
                                if fire_dwell > 0.0:
                                    gcode_lines.append(f"G4 P{fire_dwell / 1000.0:.3f} ; Laser fire dwell")
                                if eff_feed != current_cut_feed:
                                    gcode_lines.append(f"G1 X{seg_x2:.3f} Y{seg_y:.3f} F{eff_feed:.0f}")
                                    current_cut_feed = eff_feed
                                else:
                                    gcode_lines.append(f"G1 X{seg_x2:.3f} Y{seg_y:.3f}")
                                gcode_lines.append(self._laser_off_cmd())
                                off_dwell = getattr(self.settings, "laser_off_delay_ms", 0.0)
                                if off_dwell > 0.0:
                                    gcode_lines.append(f"G4 P{off_dwell / 1000.0:.3f} ; Laser off dwell")

                            segments.append(ToolpathSegment("cut", seg_x1, seg_y, seg_x2, seg_y, eff_feed, eff_p_pct, lid, layer.color))
                            cur_x, cur_y = seg_x2, seg_y

                    if continuous_streaming:
                        gcode_lines.append("M5 S0 ; Fill Turbo Mode OFF")

                # LINE (VECTOR CUT) MODE
                if raw_line_paths:
                    # Apply kerf compensation if configured on this layer
                    kerf_offset = getattr(layer, "kerf_offset", 0.0)
                    kerf_dir = getattr(layer, "kerf_direction", "Auto")
                    if kerf_offset > 0.0 and kerf_dir not in ("Off", "None"):
                        kerf_res = KerfEngine.apply_kerf_to_paths(raw_line_paths, kerf_offset, direction=kerf_dir)
                        comp_paths = []
                        comp_meta = []
                        comp_closed = []
                        for kr, meta in zip(kerf_res, raw_line_meta):
                            comp_paths.append(kr["path"])
                            m_copy = dict(meta)
                            m_copy["is_outer"] = kr["is_outer"]
                            m_copy["closed"] = kr["is_closed"]
                            # Disable raw circular arc substitution so the compensated polygon is traced
                            m_copy["arc_info"] = None
                            comp_meta.append(m_copy)
                            comp_closed.append(kr["is_closed"])
                        raw_line_paths = comp_paths
                        raw_line_meta = comp_meta
                        raw_line_closed = comp_closed

                    optimized_line_paths, optimized_line_meta = PathOptimizer.optimize_paths(
                        raw_line_paths, closed_flags=raw_line_closed, start_pos=(cur_x, cur_y), metadata=raw_line_meta
                    )
                    lead_in_type = getattr(layer, "lead_in_type", "None")
                    lead_in_len = getattr(layer, "lead_in_length", 2.0)
                    lead_out_type = getattr(layer, "lead_out_type", "None")
                    lead_out_len = getattr(layer, "lead_out_length", 2.0)
                    overcut_len = getattr(layer, "overcut_length", 0.0)

                    for path, meta in zip(optimized_line_paths, optimized_line_meta):
                        if len(path) < 2:
                            continue

                        eff_feed = meta["override_speed"] if (meta and meta.get("override_speed") is not None) else layer.speed
                        eff_p_pct = meta["override_power"] if (meta and meta.get("override_power") is not None) else layer.power_max
                        eff_s_power = int(round((eff_p_pct / 100.0) * max_s))

                        is_outer = meta.get("is_outer", True) if meta else True
                        is_closed = meta.get("closed", False) if meta else False

                        # Check if native G2/G3 arc generation is applicable (only when no lead-in/out, kerf, or tabs)
                        arc = meta.get("arc_info") if meta else None
                        tabs_enabled = getattr(layer, "tabs_enabled", False)
                        if arc is not None and lead_in_type in ("None", "") and lead_out_type in ("None", "") and overcut_len <= 0.0 and not tabs_enabled:
                            cx, cy, r = arc["cx"], arc["cy"], arc["r"]
                            start_x, start_y = cx - r, cy
                            all_x.extend([cx - r, cx + r])
                            all_y.extend([cy - r, cy + r])

                            rap_dist = math.hypot(start_x - cur_x, start_y - cur_y)
                            total_rapid_dist += rap_dist
                            total_time_sec += (rap_dist / self.settings.rapid_speed) * 60.0

                            if rap_dist > 0.01:
                                gcode_lines.append(f"G0 X{start_x:.3f} Y{start_y:.3f} F{self.settings.rapid_speed:.0f}")
                                segments.append(ToolpathSegment("rapid", cur_x, cur_y, start_x, start_y, self.settings.rapid_speed, 0, lid, layer.color))
                                cur_x, cur_y = start_x, start_y
                            if not job_start_captured:
                                job_start_x, job_start_y = cur_x, cur_y
                                job_start_captured = True

                            # Laser ON
                            gcode_lines.append(self._laser_on_cmd(eff_s_power))
                            fire_dwell = getattr(self.settings, "laser_fire_delay_ms", 0.0)
                            if fire_dwell > 0.0:
                                gcode_lines.append(f"G4 P{fire_dwell / 1000.0:.3f} ; Laser fire dwell")

                            # Two 180-degree semicircular arcs (G2 clockwise)
                            mid_x, mid_y = cx + r, cy
                            circ_semi_dist = math.pi * r
                            total_cut_dist += circ_semi_dist * 2.0
                            total_time_sec += (circ_semi_dist * 2.0 / eff_feed) * 60.0

                            gcode_lines.append(f"G2 X{mid_x:.3f} Y{mid_y:.3f} I{r:.3f} J0.000 F{eff_feed:.0f}")
                            gcode_lines.append(f"G2 X{start_x:.3f} Y{start_y:.3f} I{-r:.3f} J0.000")

                            # Simulation segments for preview dialog
                            num_sim_pts = max(24, int(math.pi * r))
                            prev_px, prev_py = start_x, start_y
                            for s_i in range(1, num_sim_pts + 1):
                                ang = math.pi - (2.0 * math.pi * s_i / num_sim_pts)
                                px = cx + r * math.cos(ang)
                                py = cy + r * math.sin(ang)
                                segments.append(ToolpathSegment("cut", prev_px, prev_py, px, py, eff_feed, eff_p_pct, lid, layer.color))
                                prev_px, prev_py = px, py
                            cur_x, cur_y = start_x, start_y

                            # Laser OFF
                            gcode_lines.append(self._laser_off_cmd())
                            off_dwell = getattr(self.settings, "laser_off_delay_ms", 0.0)
                            if off_dwell > 0.0:
                                gcode_lines.append(f"G4 P{off_dwell / 1000.0:.3f} ; Laser off dwell")
                            continue

                        # Generate Lead-in / Lead-out / Overcut
                        lead_in_pts = []
                        if is_closed and lead_in_type not in ("None", "") and lead_in_len > 0.0:
                            lead_in_pts = KerfEngine.generate_lead_in(path, lead_type=lead_in_type, length=lead_in_len, is_outer=is_outer)

                        lead_out_pts = []
                        if is_closed and lead_out_type not in ("None", "") and lead_out_len > 0.0:
                            lead_out_pts = KerfEngine.generate_lead_out(path, lead_type=lead_out_type, length=lead_out_len, is_outer=is_outer)

                        cut_path = path
                        if is_closed and overcut_len > 0.0:
                            cut_path = KerfEngine.apply_overcut(path, overcut_dist=overcut_len)

                        # Determine start position (pierce point)
                        initial_pt = lead_in_pts[0] if lead_in_pts else cut_path[0]
                        all_x.append(initial_pt[0])
                        all_y.append(initial_pt[1])

                        # Rapid to initial start
                        rap_dist = math.hypot(initial_pt[0] - cur_x, initial_pt[1] - cur_y)
                        total_rapid_dist += rap_dist
                        total_time_sec += (rap_dist / self.settings.rapid_speed) * 60.0

                        if rap_dist > 0.01:
                            gcode_lines.append(f"G0 X{initial_pt[0]:.3f} Y{initial_pt[1]:.3f} F{self.settings.rapid_speed:.0f}")
                            segments.append(ToolpathSegment("rapid", cur_x, cur_y, initial_pt[0], initial_pt[1], self.settings.rapid_speed, 0, lid, layer.color))
                            cur_x, cur_y = initial_pt[0], initial_pt[1]

                        if not job_start_captured:
                            job_start_x, job_start_y = cur_x, cur_y
                            job_start_captured = True

                        # Laser ON
                        gcode_lines.append(self._laser_on_cmd(eff_s_power))
                        fire_dwell = getattr(self.settings, "laser_fire_delay_ms", 0.0)
                        if fire_dwell > 0.0:
                            gcode_lines.append(f"G4 P{fire_dwell / 1000.0:.3f} ; Laser fire dwell")

                        # Cut Lead-in (if present)
                        if lead_in_pts:
                            for l_pt in lead_in_pts[1:]:
                                all_x.append(l_pt[0])
                                all_y.append(l_pt[1])
                                l_dist = math.hypot(l_pt[0] - cur_x, l_pt[1] - cur_y)
                                total_cut_dist += l_dist
                                total_time_sec += (l_dist / eff_feed) * 60.0
                                gcode_lines.append(f"G1 X{l_pt[0]:.3f} Y{l_pt[1]:.3f} F{eff_feed:.0f}")
                                segments.append(ToolpathSegment("cut", cur_x, cur_y, l_pt[0], l_pt[1], eff_feed, eff_p_pct, lid, layer.color))
                                cur_x, cur_y = l_pt[0], l_pt[1]

                        # Cut along main contour vertices
                        tab_count = getattr(layer, "tab_count", 4)
                        tab_width = getattr(layer, "tab_width", 1.0)
                        tab_power_pct = getattr(layer, "tab_power_pct", 0.0)
                        manual_tabs = meta.get("tabs", []) if meta else []

                        if tabs_enabled and is_closed and (tab_count > 0 or manual_tabs) and tab_width > 0.0:
                            tab_slices = TabEngine.slice_contour_with_tabs(
                                cut_path, tab_count=tab_count, tab_width=tab_width, manual_tab_ratios=manual_tabs
                            )
                            for sl in tab_slices:
                                if sl["type"] == "cut":
                                    s_path = sl["path"]
                                    # Ensure laser is ON for cutting segment
                                    gcode_lines.append(self._laser_on_cmd(eff_s_power))
                                    for pt in s_path[1:]:
                                        all_x.append(pt[0])
                                        all_y.append(pt[1])
                                        c_dist = math.hypot(pt[0] - cur_x, pt[1] - cur_y)
                                        total_cut_dist += c_dist
                                        total_time_sec += (c_dist / eff_feed) * 60.0
                                        gcode_lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{eff_feed:.0f}")
                                        segments.append(ToolpathSegment("cut", cur_x, cur_y, pt[0], pt[1], eff_feed, eff_p_pct, lid, layer.color))
                                        cur_x, cur_y = pt[0], pt[1]
                                elif sl["type"] == "tab":
                                    tab_end = sl["end"]
                                    all_x.append(tab_end[0])
                                    all_y.append(tab_end[1])
                                    t_dist = math.hypot(tab_end[0] - cur_x, tab_end[1] - cur_y)
                                    if tab_power_pct > 0.0:
                                        tab_s = int(round((tab_power_pct / 100.0) * max_s))
                                        gcode_lines.append(self._laser_on_cmd(tab_s))
                                        total_cut_dist += t_dist
                                        total_time_sec += (t_dist / eff_feed) * 60.0
                                        gcode_lines.append(f"G1 X{tab_end[0]:.3f} Y{tab_end[1]:.3f} F{eff_feed:.0f}")
                                        segments.append(ToolpathSegment("cut", cur_x, cur_y, tab_end[0], tab_end[1], eff_feed, tab_power_pct, lid, layer.color))
                                    else:
                                        # Laser OFF across holding bridge
                                        gcode_lines.append(self._laser_off_cmd())
                                        total_rapid_dist += t_dist
                                        total_time_sec += (t_dist / self.settings.rapid_speed) * 60.0
                                        gcode_lines.append(f"G0 X{tab_end[0]:.3f} Y{tab_end[1]:.3f} F{self.settings.rapid_speed:.0f}")
                                        segments.append(ToolpathSegment("rapid", cur_x, cur_y, tab_end[0], tab_end[1], self.settings.rapid_speed, 0, lid, layer.color))
                                    cur_x, cur_y = tab_end[0], tab_end[1]
                        else:
                            start_idx = 0 if lead_in_pts else 1
                            for pt in cut_path[start_idx:]:
                                all_x.append(pt[0])
                                all_y.append(pt[1])
                                c_dist = math.hypot(pt[0] - cur_x, pt[1] - cur_y)
                                total_cut_dist += c_dist
                                total_time_sec += (c_dist / eff_feed) * 60.0

                                gcode_lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{eff_feed:.0f}")
                                segments.append(ToolpathSegment("cut", cur_x, cur_y, pt[0], pt[1], eff_feed, eff_p_pct, lid, layer.color))
                                cur_x, cur_y = pt[0], pt[1]

                        # Cut Lead-out (if present)
                        if lead_out_pts:
                            for lo_pt in lead_out_pts[1:]:
                                all_x.append(lo_pt[0])
                                all_y.append(lo_pt[1])
                                lo_dist = math.hypot(lo_pt[0] - cur_x, lo_pt[1] - cur_y)
                                total_cut_dist += lo_dist
                                total_time_sec += (lo_dist / eff_feed) * 60.0
                                gcode_lines.append(f"G1 X{lo_pt[0]:.3f} Y{lo_pt[1]:.3f} F{eff_feed:.0f}")
                                segments.append(ToolpathSegment("cut", cur_x, cur_y, lo_pt[0], lo_pt[1], eff_feed, eff_p_pct, lid, layer.color))
                                cur_x, cur_y = lo_pt[0], lo_pt[1]

                        # Laser OFF
                        gcode_lines.append(self._laser_off_cmd())
                        off_dwell = getattr(self.settings, "laser_off_delay_ms", 0.0)
                        if off_dwell > 0.0:
                            gcode_lines.append(f"G4 P{off_dwell / 1000.0:.3f} ; Laser off dwell")

            if layer.air_assist:
                post_delay = getattr(self.settings, "air_assist_post_delay_sec", 0.0)
                if post_delay > 0.0:
                    gcode_lines.append(f"G4 P{post_delay:.1f} ; Air Assist Post-delay")
                gcode_lines.append(f"{self.settings.air_assist_off_cmd} ; Air Assist OFF")

        # Footer
        gcode_lines.append("\n; --- Job Finished ---")
        gcode_lines.append(f"{self._laser_off_cmd()}           ; Laser OFF")

        # Custom End G-Code
        end_script = getattr(self.settings, "custom_end_gcode", "").strip()
        if end_script:
            gcode_lines.append("; --- Custom End G-Code ---")
            for line in end_script.splitlines():
                cl = line.strip()
                if cl:
                    gcode_lines.append(cl)

        # Finish position mode
        finish_mode = getattr(self.settings, "finish_position_mode", "Origin")
        if finish_mode == "Job Start":
            gcode_lines.append(f"G0 X{job_start_x:.3f} Y{job_start_y:.3f} F{self.settings.rapid_speed:.0f} ; Return to Job Start")
        elif finish_mode in ("Park Position", "Park"):
            park_x = getattr(self.settings, "park_x", 0.0)
            park_y = getattr(self.settings, "park_y", 0.0)
            gcode_lines.append(f"G0 X{park_x:.3f} Y{park_y:.3f} F{self.settings.rapid_speed:.0f} ; Move to Park Position")
        elif finish_mode == "Hold Current":
            gcode_lines.append("; Hold Current Position")
        else:  # "Origin" or default
            gcode_lines.append(f"G0 X0 Y0 F{self.settings.rapid_speed:.0f} ; Return to Origin")

        gcode_lines.append("M2           ; End of program\n")

        # Bounding Box
        if all_x and all_y:
            bbox = (min(all_x), min(all_y), max(all_x), max(all_y))
        else:
            bbox = (0.0, 0.0, 0.0, 0.0)

        return GCodeJobResult(
            gcode="\n".join(gcode_lines),
            segments=segments,
            total_cut_dist_mm=round(total_cut_dist, 2),
            total_rapid_dist_mm=round(total_rapid_dist, 2),
            estimated_time_sec=round(total_time_sec, 1),
            bounding_box=bbox
        )

    def generate_framing_gcode(self, target: Any) -> str:
        """Generates G-code to trace the bounding box perimeter with visible low-power guide.
        target can be either a 4-tuple bbox (min_x, min_y, max_x, max_y) or a list of LaserEntity.
        """
        if isinstance(target, (tuple, list)) and len(target) == 4 and all(isinstance(v, (int, float)) for v in target):
            min_x, min_y, max_x, max_y = target
        elif isinstance(target, list) and target:
            # List of entities
            boxes = [e.get_bounds() for e in target if hasattr(e, "get_bounds")]
            if not boxes:
                return ""
            min_x = min(b[0] for b in boxes)
            min_y = min(b[1] for b in boxes)
            max_x = max(b[2] for b in boxes)
            max_y = max(b[3] for b in boxes)
        else:
            return ""

        if getattr(self.settings, "software_mirror_x", False):
            min_x, max_x = self.settings.bed_width - max_x, self.settings.bed_width - min_x
        if getattr(self.settings, "software_mirror_y", False):
            min_y, max_y = self.settings.bed_height - max_y, self.settings.bed_height - min_y

        s_frame = int(round((self.settings.framing_power_pct / 100.0) * self.settings.max_s_value))
        speed = self.settings.framing_speed

        lines = [
            "; --- Bounding Box Framing ---",
            "G21",
            "G90",
            self._laser_off_cmd(),
            f"G0 X{min_x:.3f} Y{min_y:.3f} F{speed:.0f}",
            f"{self._laser_on_cmd(s_frame)} ; Framing Beam ON",
            f"G1 X{max_x:.3f} Y{min_y:.3f} F{speed:.0f}",
            f"G1 X{max_x:.3f} Y{max_y:.3f} F{speed:.0f}",
            f"G1 X{min_x:.3f} Y{max_y:.3f} F{speed:.0f}",
            f"G1 X{min_x:.3f} Y{min_y:.3f} F{speed:.0f}",
            f"{self._laser_off_cmd()} ; Framing Beam OFF",
        ]
        return "\n".join(lines)

    def generate_contour_framing_gcode(self, target: Any) -> str:
        """
        Generates G-code to trace the precise 2D convex hull / rubber-band perimeter
        of the target entities with a visible low-power guide beam (0.5%).
        Useful for aligning artwork onto irregular materials and scrap wood.
        """
        if not target or not isinstance(target, list):
            return self.generate_framing_gcode(target)

        # Collect 2D points from all entities
        points = []
        for e in target:
            if hasattr(e, "contours") and e.contours:
                for c in e.contours:
                    for p in c:
                        points.append((e.x + p[0], e.y + p[1]))
            elif hasattr(e, "get_bounds"):
                b = e.get_bounds()
                points.extend([(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])])

        if len(points) < 3:
            return self.generate_framing_gcode(target)

        try:
            import shapely.geometry
            mp = shapely.geometry.MultiPoint(points)
            hull = mp.convex_hull
            if hull.is_empty or hull.geom_type != 'Polygon':
                return self.generate_framing_gcode(target)
            coords = list(hull.exterior.coords)
        except Exception:
            return self.generate_framing_gcode(target)

        if len(coords) < 3:
            return self.generate_framing_gcode(target)

        # Mirroring if configured
        final_coords = []
        for x, y in coords:
            if getattr(self.settings, "software_mirror_x", False):
                x = self.settings.bed_width - x
            if getattr(self.settings, "software_mirror_y", False):
                y = self.settings.bed_height - y
            final_coords.append((x, y))

        s_frame = int(round((self.settings.framing_power_pct / 100.0) * self.settings.max_s_value))
        speed = self.settings.framing_speed

        first_pt = final_coords[0]
        lines = [
            "; --- Rubber-Band Contour Framing ---",
            "G21",
            "G90",
            self._laser_off_cmd(),
            f"G0 X{first_pt[0]:.3f} Y{first_pt[1]:.3f} F{speed:.0f}",
            f"{self._laser_on_cmd(s_frame)} ; Framing Beam ON",
        ]

        for pt in final_coords[1:]:
            lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{speed:.0f}")

        lines.append(f"{self._laser_off_cmd()} ; Framing Beam OFF")
        return "\n".join(lines)

    def generate_target_point_gcode(self, target_x: float, target_y: float, power_pct: float = 0.5) -> str:
        """Generates G-code to jog the laser to target coordinate and project low-power guide dot."""
        if getattr(self.settings, "software_mirror_x", False):
            target_x = self.settings.bed_width - target_x
        if getattr(self.settings, "software_mirror_y", False):
            target_y = self.settings.bed_height - target_y
        s_val = max(1, int(round((power_pct / 100.0) * self.settings.max_s_value)))
        lines = [
            "; --- Visual Laser Targeting ---",
            "G21",
            "G90",
            self._laser_off_cmd(),
            f"G0 X{target_x:.3f} Y{target_y:.3f} F{self.settings.rapid_speed:.0f}",
            f"{'M106 S' + str(s_val) if getattr(self.settings, 'laser_mode', 'M4') == 'M106' else 'M3 S' + str(s_val)} ; Targeting Beam ON",
        ]
        return "\n".join(lines)

    @staticmethod
    def _compute_convex_hull(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Computes the 2D convex hull of a set of 2D points using Monotone Chain algorithm."""
        pts = sorted(set(points))
        if len(pts) <= 2:
            return pts

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        lower = []
        for p in pts:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)

        upper = []
        for p in reversed(pts):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)

        return lower[:-1] + upper[:-1]

    def _resolve_target_bounds(self, target: Any) -> Optional[Tuple[float, float, float, float]]:
        """Extracts (min_x, min_y, max_x, max_y) from a 4-tuple or list of LaserEntities."""
        if isinstance(target, (tuple, list)) and len(target) == 4 and all(isinstance(v, (int, float)) for v in target):
            return float(target[0]), float(target[1]), float(target[2]), float(target[3])
        elif isinstance(target, list) and target:
            boxes = [e.get_bounds() for e in target if hasattr(e, "get_bounds")]
            if not boxes:
                return None
            return (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
        return None

    def generate_burn_perimeter_gcode(
        self,
        target: Any,
        mode: str = "box",
        margin_mm: float = 0.0,
        power_pct: float = 15.0,
        speed: float = 1500.0,
        passes: int = 1,
        corner_tick_len_mm: float = 8.0,
        center_cross_len_mm: float = 10.0,
        air_assist: bool = False,
    ) -> str:
        """
        Generates G-code to burn/score an alignment perimeter or alignment marks for workpiece positioning.

        Modes:
        - "box": Full rectangular bounding boundary.
        - "box_crosshair": Bounding box rectangle plus center alignment crosshairs.
        - "corners": 4 L-shaped corner tick marks (alignment corner stops).
        - "center_plus": Center '+' mark of specified cross length.
        - "corners_and_center": 4 L-shaped corner ticks plus center '+' cross.
        - "crosshair_only": Center crosshair lines spanning the workpiece envelope.
        - "hull": Tight convex hull perimeter around actual vector entities.
        """
        bbox = self._resolve_target_bounds(target)
        if not bbox:
            return ""

        raw_min_x, raw_min_y, raw_max_x, raw_max_y = bbox
        min_x = max(0.0, raw_min_x - margin_mm)
        min_y = max(0.0, raw_min_y - margin_mm)
        max_x = min(self.settings.bed_width, raw_max_x + margin_mm)
        max_y = min(self.settings.bed_height, raw_max_y + margin_mm)

        if min_x >= max_x or min_y >= max_y:
            return ""

        named_polylines: List[Tuple[str, List[Tuple[float, float]]]] = []

        if mode == "hull" and isinstance(target, list) and target:
            all_pts: List[Tuple[float, float]] = []
            for ent in target:
                for path in self.entity_to_paths(ent):
                    all_pts.extend(path)
            hull = self._compute_convex_hull(all_pts) if len(all_pts) >= 3 else []
            if len(hull) >= 3:
                if margin_mm != 0.0:
                    cx = sum(p[0] for p in hull) / len(hull)
                    cy = sum(p[1] for p in hull) / len(hull)
                    expanded: List[Tuple[float, float]] = []
                    for px, py in hull:
                        dx, dy = px - cx, py - cy
                        d = math.hypot(dx, dy)
                        if d > 1e-6:
                            sc = (d + margin_mm) / d
                            expanded.append((
                                max(0.0, min(self.settings.bed_width, cx + dx * sc)),
                                max(0.0, min(self.settings.bed_height, cy + dy * sc))
                            ))
                        else:
                            expanded.append((px, py))
                    hull = expanded
                hull_loop = list(hull) + [hull[0]]
                named_polylines.append(("Convex Hull Perimeter", hull_loop))
            else:
                mode = "box"

        if mode == "box":
            box_poly = [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
                (min_x, min_y)
            ]
            named_polylines.append(("Perimeter Box", box_poly))

        elif mode == "box_crosshair":
            box_poly = [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
                (min_x, min_y)
            ]
            named_polylines.append(("Perimeter Box", box_poly))
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            named_polylines.append(("Horizontal Crosshair", [(min_x, cy), (max_x, cy)]))
            named_polylines.append(("Vertical Crosshair", [(cx, min_y), (cx, max_y)]))

        elif mode == "corners":
            w = max_x - min_x
            h = max_y - min_y
            t = max(1.0, min(corner_tick_len_mm, w / 2.0, h / 2.0))
            # Bottom-Left
            named_polylines.append(("Corner Tick BL", [(min_x + t, min_y), (min_x, min_y), (min_x, min_y + t)]))
            # Bottom-Right
            named_polylines.append(("Corner Tick BR", [(max_x - t, min_y), (max_x, min_y), (max_x, min_y + t)]))
            # Top-Right
            named_polylines.append(("Corner Tick TR", [(max_x - t, max_y), (max_x, max_y), (max_x, max_y - t)]))
            # Top-Left
            named_polylines.append(("Corner Tick TL", [(min_x + t, max_y), (min_x, max_y), (min_x, max_y - t)]))

        elif mode == "center_plus":
            w = max_x - min_x
            h = max_y - min_y
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            half_c = max(1.0, min(center_cross_len_mm / 2.0, w / 2.0, h / 2.0))
            named_polylines.append(("Center Cross H", [(cx - half_c, cy), (cx + half_c, cy)]))
            named_polylines.append(("Center Cross V", [(cx, cy - half_c), (cx, cy + half_c)]))

        elif mode in ("corners_and_center", "corners_plus"):
            w = max_x - min_x
            h = max_y - min_y
            t = max(1.0, min(corner_tick_len_mm, w / 2.0, h / 2.0))
            # 4 Corners
            named_polylines.append(("Corner Tick BL", [(min_x + t, min_y), (min_x, min_y), (min_x, min_y + t)]))
            named_polylines.append(("Corner Tick BR", [(max_x - t, min_y), (max_x, min_y), (max_x, min_y + t)]))
            named_polylines.append(("Corner Tick TR", [(max_x - t, max_y), (max_x, max_y), (max_x, max_y - t)]))
            named_polylines.append(("Corner Tick TL", [(min_x + t, max_y), (min_x, max_y), (min_x, max_y - t)]))
            # Center +
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            half_c = max(1.0, min(center_cross_len_mm / 2.0, w / 2.0, h / 2.0))
            named_polylines.append(("Center Cross H", [(cx - half_c, cy), (cx + half_c, cy)]))
            named_polylines.append(("Center Cross V", [(cx, cy - half_c), (cx, cy + half_c)]))

        elif mode == "crosshair_only":
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            named_polylines.append(("Horizontal Crosshair", [(min_x, cy), (max_x, cy)]))
            named_polylines.append(("Vertical Crosshair", [(cx, min_y), (cx, max_y)]))

        if not named_polylines:
            return ""

        # Map to machine space if software mirroring is enabled
        def _map_pt(px: float, py: float) -> Tuple[float, float]:
            tx = self.settings.bed_width - px if getattr(self.settings, "software_mirror_x", False) else px
            ty = self.settings.bed_height - py if getattr(self.settings, "software_mirror_y", False) else py
            return round(tx, 3), round(ty, 3)

        s_val = max(1, int(round((power_pct / 100.0) * self.settings.max_s_value)))
        laser_on = self._laser_on_cmd(s_val)
        laser_off = self._laser_off_cmd()
        rapid_spd = self.settings.rapid_speed
        fire_delay = getattr(self.settings, "laser_fire_delay_ms", 0.0)
        off_delay = getattr(self.settings, "laser_off_delay_ms", 0.0)
        pass_delay = getattr(self.settings, "pass_delay_sec", 0.0)

        lines: List[str] = [
            "; --- LaserForge Burn Perimeter Alignment ---",
            f"; Mode: {mode} | Margin: {margin_mm:.1f}mm | Power: {power_pct:.1f}% (S{s_val}) | Speed: {speed:.0f} mm/min | Passes: {passes}",
            f"; Workpiece Box: ({min_x:.2f}, {min_y:.2f}) -> ({max_x:.2f}, {max_y:.2f})",
            "G21",
            "G90",
            laser_off,
        ]

        if air_assist:
            lines.append("M8 ; Air Assist ON")

        for p_idx in range(max(1, passes)):
            if p_idx > 0 and pass_delay > 0:
                lines.append(f"G4 P{pass_delay:.2f} ; Cooldown pass delay")
            lines.append(f"; --- Pass {p_idx + 1} of {passes} ---")

            for name, poly in named_polylines:
                if len(poly) < 2:
                    continue
                lines.append(f"; {name}")
                start_x, start_y = _map_pt(poly[0][0], poly[0][1])
                lines.append(f"G0 X{start_x:.3f} Y{start_y:.3f} F{rapid_spd:.0f}")
                lines.append(f"{laser_on} ; Perimeter Burn Beam ON")
                if fire_delay > 0:
                    lines.append(f"G4 P{fire_delay / 1000.0:.3f}")

                for pt in poly[1:]:
                    nx, ny = _map_pt(pt[0], pt[1])
                    lines.append(f"G1 X{nx:.3f} Y{ny:.3f} F{speed:.0f}")

                lines.append(f"{laser_off} ; Perimeter Burn Beam OFF")
                if off_delay > 0:
                    lines.append(f"G4 P{off_delay / 1000.0:.3f}")


        if air_assist:
            lines.append("M9 ; Air Assist OFF")

        lines.append("; --- End Burn Perimeter Alignment ---")
        return "\n".join(lines)

    def generate_burn_perimeter_entities(
        self,
        target: Any,
        mode: str = "box",
        margin_mm: float = 0.0,
        layer_id: int = 12,
        corner_tick_len_mm: float = 8.0,
        center_cross_len_mm: float = 10.0,
    ) -> List[LaserEntity]:
        """
        Creates vector CAD LaserEntities representing the alignment perimeter
        so they can be placed on a guide or tool layer in the canvas.
        """
        bbox = self._resolve_target_bounds(target)
        if not bbox:
            return []

        raw_min_x, raw_min_y, raw_max_x, raw_max_y = bbox
        min_x = max(0.0, raw_min_x - margin_mm)
        min_y = max(0.0, raw_min_y - margin_mm)
        max_x = min(self.settings.bed_width, raw_max_x + margin_mm)
        max_y = min(self.settings.bed_height, raw_max_y + margin_mm)

        if min_x >= max_x or min_y >= max_y:
            return []

        w = max_x - min_x
        h = max_y - min_y
        entities: List[LaserEntity] = []

        if mode == "hull" and isinstance(target, list) and target:
            all_pts: List[Tuple[float, float]] = []
            for ent in target:
                for path in self.entity_to_paths(ent):
                    all_pts.extend(path)
            hull = self._compute_convex_hull(all_pts) if len(all_pts) >= 3 else []
            if len(hull) >= 3:
                if margin_mm != 0.0:
                    cx = sum(p[0] for p in hull) / len(hull)
                    cy = sum(p[1] for p in hull) / len(hull)
                    expanded: List[Tuple[float, float]] = []
                    for px, py in hull:
                        dx, dy = px - cx, py - cy
                        d = math.hypot(dx, dy)
                        if d > 1e-6:
                            sc = (d + margin_mm) / d
                            expanded.append((
                                max(0.0, min(self.settings.bed_width, cx + dx * sc)),
                                max(0.0, min(self.settings.bed_height, cy + dy * sc))
                            ))
                        else:
                            expanded.append((px, py))
                    hull = expanded
                hull_contour = [(p[0] - min_x, p[1] - min_y) for p in hull]
                entities.append(
                    PathEntity(
                        layer_id=layer_id,
                        name=f"Perimeter_Hull_{w:.1f}x{h:.1f}",
                        x=min_x,
                        y=min_y,
                        contours=[hull_contour],
                        closed=True,
                    )
                )
                return entities
            else:
                mode = "box"

        if mode == "box":
            entities.append(
                RectEntity(
                    layer_id=layer_id,
                    name=f"Perimeter_Box_{w:.1f}x{h:.1f}",
                    x=min_x,
                    y=min_y,
                    width=w,
                    height=h,
                )
            )

        elif mode == "box_crosshair":
            entities.append(
                RectEntity(
                    layer_id=layer_id,
                    name=f"Perimeter_Box_{w:.1f}x{h:.1f}",
                    x=min_x,
                    y=min_y,
                    width=w,
                    height=h,
                )
            )
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Perimeter_Crosshair_H",
                    x=min_x,
                    y=cy,
                    x2=max_x,
                    y2=cy,
                )
            )
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Perimeter_Crosshair_V",
                    x=cx,
                    y=min_y,
                    x2=cx,
                    y2=max_y,
                )
            )

        elif mode == "corners":
            t = max(1.0, min(corner_tick_len_mm, w / 2.0, h / 2.0))
            # Bottom-Left
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_BL",
                    x=min_x,
                    y=min_y,
                    contours=[[(t, 0.0), (0.0, 0.0), (0.0, t)]],
                    closed=False,
                )
            )
            # Bottom-Right
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_BR",
                    x=max_x,
                    y=min_y,
                    contours=[[(-t, 0.0), (0.0, 0.0), (0.0, t)]],
                    closed=False,
                )
            )
            # Top-Right
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_TR",
                    x=max_x,
                    y=max_y,
                    contours=[[(-t, 0.0), (0.0, 0.0), (0.0, -t)]],
                    closed=False,
                )
            )
            # Top-Left
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_TL",
                    x=min_x,
                    y=max_y,
                    contours=[[(t, 0.0), (0.0, 0.0), (0.0, -t)]],
                    closed=False,
                )
            )

        elif mode == "center_plus":
            w = max_x - min_x
            h = max_y - min_y
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            half_c = max(1.0, min(center_cross_len_mm / 2.0, w / 2.0, h / 2.0))
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Center_Mark_Plus_H",
                    x=cx - half_c,
                    y=cy,
                    x2=cx + half_c,
                    y2=cy,
                )
            )
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Center_Mark_Plus_V",
                    x=cx,
                    y=cy - half_c,
                    x2=cx,
                    y2=cy + half_c,
                )
            )

        elif mode in ("corners_and_center", "corners_plus"):
            w = max_x - min_x
            h = max_y - min_y
            t = max(1.0, min(corner_tick_len_mm, w / 2.0, h / 2.0))
            # 4 Corners
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_BL",
                    x=min_x,
                    y=min_y,
                    contours=[[(t, 0.0), (0.0, 0.0), (0.0, t)]],
                    closed=False,
                )
            )
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_BR",
                    x=max_x,
                    y=min_y,
                    contours=[[(-t, 0.0), (0.0, 0.0), (0.0, t)]],
                    closed=False,
                )
            )
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_TR",
                    x=max_x,
                    y=max_y,
                    contours=[[(-t, 0.0), (0.0, 0.0), (0.0, -t)]],
                    closed=False,
                )
            )
            entities.append(
                PathEntity(
                    layer_id=layer_id,
                    name="Corner_Tick_TL",
                    x=min_x,
                    y=max_y,
                    contours=[[(t, 0.0), (0.0, 0.0), (0.0, -t)]],
                    closed=False,
                )
            )
            # Center +
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            half_c = max(1.0, min(center_cross_len_mm / 2.0, w / 2.0, h / 2.0))
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Center_Mark_Plus_H",
                    x=cx - half_c,
                    y=cy,
                    x2=cx + half_c,
                    y2=cy,
                )
            )
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Center_Mark_Plus_V",
                    x=cx,
                    y=cy - half_c,
                    x2=cx,
                    y2=cy + half_c,
                )
            )

        elif mode == "crosshair_only":
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Perimeter_Crosshair_H",
                    x=min_x,
                    y=cy,
                    x2=max_x,
                    y2=cy,
                )
            )
            entities.append(
                LineEntity(
                    layer_id=layer_id,
                    name="Perimeter_Crosshair_V",
                    x=cx,
                    y=min_y,
                    x2=cx,
                    y2=max_y,
                )
            )

        return entities

    def generate_corner_l_marks(
        self,
        target: Any,
        tick_len_mm: float = 8.0,
        margin_mm: float = 0.0,
        layer_id: int = 12,
    ) -> List[LaserEntity]:
        """Convenience method: generates 4 corner 90° L-tick alignment marks."""
        return self.generate_burn_perimeter_entities(
            target=target,
            mode="corners",
            margin_mm=margin_mm,
            layer_id=layer_id,
            corner_tick_len_mm=tick_len_mm,
        )

    def generate_center_cross_mark(
        self,
        target: Any,
        cross_len_mm: float = 10.0,
        margin_mm: float = 0.0,
        layer_id: int = 12,
    ) -> List[LaserEntity]:
        """Convenience method: generates a centered '+' registration cross mark."""
        return self.generate_burn_perimeter_entities(
            target=target,
            mode="center_plus",
            margin_mm=margin_mm,
            layer_id=layer_id,
            center_cross_len_mm=cross_len_mm,
        )

    def generate_alignment_marks(
        self,
        target: Any,
        mode: str = "corners_and_center",
        tick_len_mm: float = 8.0,
        cross_len_mm: float = 10.0,
        margin_mm: float = 0.0,
        layer_id: int = 12,
    ) -> List[LaserEntity]:
        """Generates registration / alignment marks (Corners, Center +, or Both)."""
        return self.generate_burn_perimeter_entities(
            target=target,
            mode=mode,
            margin_mm=margin_mm,
            layer_id=layer_id,
            corner_tick_len_mm=tick_len_mm,
            center_cross_len_mm=cross_len_mm,
        )

