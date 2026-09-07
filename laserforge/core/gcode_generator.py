"""
LaserForge G-Code Generator and CAM Processor.
Translates vector geometries, text, and raster images into standard GRBL/Marlin G-code.
Computes estimated job execution times and exports toolpath vectors for the visual simulation viewer.
"""

from typing import List, Dict, Tuple, Any, Optional
import math
from dataclasses import dataclass
from PIL import Image

from laserforge.config import MachineSettings
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity, LayerCutSettings
)
from laserforge.core.layer_manager import LayerManager
from laserforge.core.optimizer import PathOptimizer
from laserforge.core.raster_processor import RasterProcessor

@dataclass
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

@dataclass
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
            # Defer to text path generator or placeholder box
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

        # Calculate bounding box
        all_x, all_y = [], []

        # Header
        gcode_lines.append("; =================================================")
        gcode_lines.append("; Generated by LaserForge CAD/CAM for GRBL")
        gcode_lines.append("; =================================================")
        gcode_lines.append("G21          ; Set units to millimeters")
        gcode_lines.append("G90          ; Absolute positioning")
        gcode_lines.append("M5           ; Ensure laser is OFF")
        if self.settings.enable_z_moves:
            gcode_lines.append(f"G0 Z0 F{self.settings.rapid_speed:.0f} ; Safe Z")

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

            passes = max(1, layer.passes)
            feed = layer.speed
            s_power = int(round((layer.power_max / 100.0) * max_s))

            for pass_idx in range(passes):
                if passes > 1:
                    gcode_lines.append(f"; Pass {pass_idx + 1}/{passes}")
                    if self.settings.enable_z_moves and layer.z_step != 0:
                        z_val = -(pass_idx * layer.z_step)
                        gcode_lines.append(f"G0 Z{z_val:.3f}")


                # 1. IMAGE MODE
                image_entities = [e for e in group_entities if isinstance(e, ImageEntity)]
                for img_ent in image_entities:
                    if not img_ent.image_path:
                        continue
                    try:
                        pil_img = Image.open(img_ent.image_path)
                        raster_arr = RasterProcessor.process_image(
                            pil_img,
                            target_width_mm=img_ent.width,
                            target_height_mm=img_ent.height,
                            line_interval_mm=layer.line_interval,
                            mode=img_ent.dither_mode,
                            invert=img_ent.invert,
                            contrast=img_ent.contrast,
                            brightness=img_ent.brightness,
                            threshold_val=img_ent.threshold_value
                        )

                        scanlines = RasterProcessor.generate_raster_scanlines(
                            raster_arr,
                            origin_x_mm=img_ent.x,
                            origin_y_mm=img_ent.y,
                            line_interval_mm=layer.line_interval
                        )

                        for line in scanlines:
                            y_val = line["y_mm"]
                            reverse = line["reverse"]
                            all_y.append(y_val)

                            for seg in line["segments"]:
                                x_start, x_end, p_ratio, _ = seg
                                all_x.extend([x_start, x_end])

                                seg_p = int(round((layer.power_max / 100.0) * max_s * p_ratio))

                                # Rapid to start
                                dx = x_start - cur_x
                                dy = y_val - cur_y
                                rap_dist = math.hypot(dx, dy)
                                total_rapid_dist += rap_dist
                                total_time_sec += (rap_dist / self.settings.rapid_speed) * 60.0

                                if rap_dist > 0.01:
                                    gcode_lines.append(f"G0 X{x_start:.3f} Y{y_val:.3f} F{self.settings.rapid_speed:.0f}")
                                    segments.append(ToolpathSegment("rapid", cur_x, cur_y, x_start, y_val, self.settings.rapid_speed, 0, lid, layer.color))
                                    cur_x, cur_y = x_start, y_val

                                # Burn across segment
                                cut_dist = abs(x_end - x_start)
                                total_cut_dist += cut_dist
                                total_time_sec += (cut_dist / feed) * 60.0

                                gcode_lines.append(f"{laser_cmd} S{seg_p}")
                                gcode_lines.append(f"G1 X{x_end:.3f} Y{y_val:.3f} F{feed:.0f}")
                                gcode_lines.append("M5")

                                segments.append(ToolpathSegment("cut", x_start, y_val, x_end, y_val, feed, (seg_p / max_s) * 100.0, lid, layer.color))
                                cur_x, cur_y = x_end, y_val

                    except Exception as e:
                        gcode_lines.append(f"; Error processing image {img_ent.id}: {e}")

                # 2. VECTOR PATHS (Line, Fill, Fill + Line)
                vector_entities = [e for e in group_entities if not isinstance(e, ImageEntity)]
                raw_paths = []
                for vent in vector_entities:
                    raw_paths.extend(self.entity_to_paths(vent))

                if not raw_paths:
                    continue

                # Optimize path order
                optimized_paths = PathOptimizer.optimize_paths(raw_paths, start_pos=(cur_x, cur_y))

                # FILL MODE
                if layer.mode in ("Fill", "Fill + Line"):
                    interval = max(0.02, layer.line_interval)
                    for poly in optimized_paths:
                        fill_segs = self.generate_fill_scanlines(poly, interval)
                        for seg_x1, seg_x2, seg_y in fill_segs:
                            all_x.extend([seg_x1, seg_x2])
                            all_y.append(seg_y)

                            # Rapid to start
                            rap_dist = math.hypot(seg_x1 - cur_x, seg_y - cur_y)
                            total_rapid_dist += rap_dist
                            total_time_sec += (rap_dist / self.settings.rapid_speed) * 60.0

                            gcode_lines.append(f"G0 X{seg_x1:.3f} Y{seg_y:.3f} F{self.settings.rapid_speed:.0f}")
                            segments.append(ToolpathSegment("rapid", cur_x, cur_y, seg_x1, seg_y, self.settings.rapid_speed, 0, lid, layer.color))
                            cur_x, cur_y = seg_x1, seg_y

                            # Cut fill stroke
                            cut_dist = abs(seg_x2 - seg_x1)
                            total_cut_dist += cut_dist
                            total_time_sec += (cut_dist / feed) * 60.0

                            gcode_lines.append(f"{laser_cmd} S{s_power}")
                            gcode_lines.append(f"G1 X{seg_x2:.3f} Y{seg_y:.3f} F{feed:.0f}")
                            gcode_lines.append("M5")

                            segments.append(ToolpathSegment("cut", seg_x1, seg_y, seg_x2, seg_y, feed, layer.power_max, lid, layer.color))
                            cur_x, cur_y = seg_x2, seg_y

                # LINE (VECTOR CUT) MODE
                if layer.mode in ("Line", "Fill + Line"):
                    for path in optimized_paths:
                        if len(path) < 2:
                            continue

                        start_p = path[0]
                        all_x.append(start_p[0])
                        all_y.append(start_p[1])

                        # Rapid to path start
                        rap_dist = math.hypot(start_p[0] - cur_x, start_p[1] - cur_y)
                        total_rapid_dist += rap_dist
                        total_time_sec += (rap_dist / self.settings.rapid_speed) * 60.0

                        if rap_dist > 0.01:
                            gcode_lines.append(f"G0 X{start_p[0]:.3f} Y{start_p[1]:.3f} F{self.settings.rapid_speed:.0f}")
                            segments.append(ToolpathSegment("rapid", cur_x, cur_y, start_p[0], start_p[1], self.settings.rapid_speed, 0, lid, layer.color))
                            cur_x, cur_y = start_p[0], start_p[1]

                        # Laser ON
                        gcode_lines.append(f"{laser_cmd} S{s_power}")

                        # Cut along vertices
                        for pt in path[1:]:
                            all_x.append(pt[0])
                            all_y.append(pt[1])
                            c_dist = math.hypot(pt[0] - cur_x, pt[1] - cur_y)
                            total_cut_dist += c_dist
                            total_time_sec += (c_dist / feed) * 60.0

                            gcode_lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed:.0f}")
                            segments.append(ToolpathSegment("cut", cur_x, cur_y, pt[0], pt[1], feed, layer.power_max, lid, layer.color))
                            cur_x, cur_y = pt[0], pt[1]

                        # Laser OFF
                        gcode_lines.append("M5")

            if layer.air_assist:
                gcode_lines.append(f"{self.settings.air_assist_off_cmd} ; Air Assist OFF")

        # Footer
        gcode_lines.append("\n; --- Job Finished ---")
        gcode_lines.append("M5           ; Laser OFF")
        gcode_lines.append(f"G0 X0 Y0 F{self.settings.rapid_speed:.0f} ; Return to Origin")
        gcode_lines.append("M2           ; End of program\n")

        bbox = (
            min(all_x) if all_x else 0.0,
            min(all_y) if all_y else 0.0,
            max(all_x) if all_x else 0.0,
            max(all_y) if all_y else 0.0
        )

        return GCodeJobResult(
            gcode="\n".join(gcode_lines),
            segments=segments,
            total_cut_dist_mm=total_cut_dist,
            total_rapid_dist_mm=total_rapid_dist,
            estimated_time_sec=total_time_sec,
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

        s_frame = int(round((self.settings.framing_power_pct / 100.0) * self.settings.max_s_value))
        speed = self.settings.framing_speed


        lines = [
            "; --- Bounding Box Framing ---",
            "G21",
            "G90",
            "M5",
            f"G0 X{min_x:.3f} Y{min_y:.3f} F{speed:.0f}",
            f"{self.settings.laser_mode} S{s_frame} ; Framing Beam ON",
            f"G1 X{max_x:.3f} Y{min_y:.3f} F{speed:.0f}",
            f"G1 X{max_x:.3f} Y{max_y:.3f} F{speed:.0f}",
            f"G1 X{min_x:.3f} Y{max_y:.3f} F{speed:.0f}",
            f"G1 X{min_x:.3f} Y{min_y:.3f} F{speed:.0f}",
            "M5 ; Framing Beam OFF",
            "G0 X0 Y0",
        ]
        return "\n".join(lines)
