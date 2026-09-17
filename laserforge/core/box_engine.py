"""
LaserForge Parametric Box & Finger-Joint Enclosure Engine.
Generates 2D flat interlocking finger-joint panels for laser-cut boxes, cases, and enclosures
with kerf compensation, divider slots, and multiple box styles.
"""

from typing import List, Tuple, Dict, Any, Optional
import math
from dataclasses import dataclass

from laserforge.core.models import PathEntity, TextEntity, LaserEntity


@dataclass
class BoxPanel:
    name: str
    width: float   # Width in mm
    height: float  # Height in mm
    outline: List[Tuple[float, float]]  # Closed polygon coordinates (relative to panel origin)
    internal_cutouts: List[List[Tuple[float, float]]]  # Holes or divider slots


class BoxEngine:
    """
    Parametric generator for interlocking finger-joint laser cut boxes.
    """

    @classmethod
    def generate_finger_edge(
        cls,
        p_start: Tuple[float, float],
        p_end: Tuple[float, float],
        normal: Tuple[float, float],  # Unit outward normal (dx, dy)
        length: float,
        thickness: float,
        target_finger_len: float,
        is_male: bool,
        kerf: float = 0.0,
        joint_type: str = "finger",
        dovetail_angle: float = 10.0
    ) -> List[Tuple[float, float]]:
        """
        Generates finger joint or dovetail joint vertices along a straight edge from p_start to p_end.

        Parameters:
            p_start: Edge start point (x, y)
            p_end: Edge end point (x, y)
            normal: Outward unit normal vector (nx, ny) perpendicular to edge
            length: Edge length in mm
            thickness: Material thickness in mm (depth of tab)
            target_finger_len: Desired width of each individual tab
            is_male: True if edge has protruding tabs, False if indented slots
            kerf: Kerf offset compensation in mm
            joint_type: "finger" (standard 90° box joint) or "dovetail" (angled interlocking pins/tails)
            dovetail_angle: Angle of dovetail slope in degrees (typically 7° - 15°)
        """
        if length <= 0 or target_finger_len <= 0:
            return [p_start, p_end]

        # Determine number of divisions (must be odd so ends are symmetrical)
        n = max(3, int(round(length / target_finger_len)))
        if n % 2 == 0:
            n += 1

        seg_len = length / float(n)
        # Direction vector along edge
        dx = (p_end[0] - p_start[0]) / length
        dy = (p_end[1] - p_start[1]) / length

        # Outward normal
        nx, ny = normal

        pts = [p_start]

        # Dovetail flare delta: delta_x = thickness * tan(radians(dovetail_angle))
        if joint_type == "dovetail":
            rad_ang = math.radians(max(1.0, min(30.0, dovetail_angle)))
            delta_x = thickness * math.tan(rad_ang)
            # Prevent excessive flare that could invert or collide with adjacent tabs
            max_delta = seg_len * 0.35
            delta_x = min(delta_x, max_delta)
        else:
            delta_x = 0.0

        k_half = kerf / 2.0

        for i in range(n):
            dist_start = i * seg_len
            dist_end = (i + 1) * seg_len

            # Base coordinates on the line
            b_s = (p_start[0] + dx * dist_start, p_start[1] + dy * dist_start)
            b_e = (p_start[0] + dx * dist_end, p_start[1] + dy * dist_end)

            is_tab_raised = (i % 2 == 0) if is_male else (i % 2 != 0)

            if is_male:
                if is_tab_raised:
                    # Raised male tab (tail):
                    # Protrudes by thickness + kerf/2 outward (+normal)
                    # For dovetail: flares outward by delta_x at the tip
                    t_h = thickness
                    pt_base_s = (b_s[0] - dx * k_half, b_s[1] - dy * k_half)
                    pt1 = (b_s[0] - dx * (k_half + delta_x) + nx * t_h, b_s[1] - dy * (k_half + delta_x) + ny * t_h)
                    pt2 = (b_e[0] + dx * (k_half + delta_x) + nx * t_h, b_e[1] + dy * (k_half + delta_x) + ny * t_h)
                    pt_base_e = (b_e[0] + dx * k_half, b_e[1] + dy * k_half)
                    pts.extend([pt_base_s, pt1, pt2, pt_base_e])
                else:
                    pts.append(b_e)
            else:
                # Female slot: indented inward (-normal) by thickness
                # For dovetail: expands inward by delta_x at the bottom
                if is_tab_raised:
                    t_h = -thickness
                    pt_base_s = (b_s[0] + dx * k_half, b_s[1] + dy * k_half)
                    pt1 = (b_s[0] - dx * (delta_x - k_half) + nx * t_h, b_s[1] - dy * (delta_x - k_half) + ny * t_h)
                    pt2 = (b_e[0] + dx * (delta_x - k_half) + nx * t_h, b_e[1] + dy * (delta_x - k_half) + ny * t_h)
                    pt_base_e = (b_e[0] - dx * k_half, b_e[1] - dy * k_half)
                    pts.extend([pt_base_s, pt1, pt2, pt_base_e])
                else:
                    pts.append(b_e)

        return pts

    @classmethod
    def generate_panel_outline(
        cls,
        width: float,
        height: float,
        thickness: float,
        target_finger_len: float,
        edge_styles: Dict[str, str],  # {"bottom": "male"|"female"|"flat", "right": ..., "top": ..., "left": ...}
        kerf: float = 0.0,
        joint_type: str = "finger",
        dovetail_angle: float = 10.0
    ) -> List[Tuple[float, float]]:
        """
        Generates the 2D perimeter polyline of a rectangular panel with finger or dovetail joints on its 4 edges.
        Coordinates are relative to panel (0, 0) bottom-left.
        """
        # Corner coordinates:
        # P0: (0, 0)
        # P1: (width, 0)
        # P2: (width, height)
        # P3: (0, height)
        p0 = (0.0, 0.0)
        p1 = (width, 0.0)
        p2 = (width, height)
        p3 = (0.0, height)

        all_pts: List[Tuple[float, float]] = []

        # 1. Bottom Edge: P0 -> P1, normal is (0, -1)
        b_style = edge_styles.get("bottom", "flat")
        if b_style == "flat":
            all_pts.extend([p0, p1])
        else:
            e_pts = cls.generate_finger_edge(
                p0, p1, normal=(0.0, -1.0), length=width, thickness=thickness,
                target_finger_len=target_finger_len, is_male=(b_style == "male"), kerf=kerf,
                joint_type=joint_type, dovetail_angle=dovetail_angle
            )
            all_pts.extend(e_pts)

        # 2. Right Edge: P1 -> P2, normal is (1, 0)
        r_style = edge_styles.get("right", "flat")
        if r_style == "flat":
            all_pts.append(p2)
        else:
            e_pts = cls.generate_finger_edge(
                p1, p2, normal=(1.0, 0.0), length=height, thickness=thickness,
                target_finger_len=target_finger_len, is_male=(r_style == "male"), kerf=kerf,
                joint_type=joint_type, dovetail_angle=dovetail_angle
            )
            all_pts.extend(e_pts[1:])

        # 3. Top Edge: P2 -> P3, normal is (0, 1)
        t_style = edge_styles.get("top", "flat")
        if t_style == "flat":
            all_pts.append(p3)
        else:
            e_pts = cls.generate_finger_edge(
                p2, p3, normal=(0.0, 1.0), length=width, thickness=thickness,
                target_finger_len=target_finger_len, is_male=(t_style == "male"), kerf=kerf,
                joint_type=joint_type, dovetail_angle=dovetail_angle
            )
            all_pts.extend(e_pts[1:])

        # 4. Left Edge: P3 -> P0, normal is (-1, 0)
        l_style = edge_styles.get("left", "flat")
        if l_style == "flat":
            all_pts.append(p0)
        else:
            e_pts = cls.generate_finger_edge(
                p3, p0, normal=(-1.0, 0.0), length=height, thickness=thickness,
                target_finger_len=target_finger_len, is_male=(l_style == "male"), kerf=kerf,
                joint_type=joint_type, dovetail_angle=dovetail_angle
            )
            all_pts.extend(e_pts[1:])

        # Remove consecutive duplicate points
        cleaned = [all_pts[0]]
        for pt in all_pts[1:]:
            if math.hypot(pt[0] - cleaned[-1][0], pt[1] - cleaned[-1][1]) > 1e-4:
                cleaned.append(pt)

        # Ensure closed
        if math.hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) > 1e-4:
            cleaned.append(cleaned[0])

        return cleaned

    @classmethod
    def generate_box(
        cls,
        width: float,
        depth: float,
        height: float,
        thickness: float = 3.0,
        finger_width: float = 10.0,
        kerf: float = 0.15,
        style: str = "6-sided",
        dividers_x: int = 0,
        dividers_y: int = 0,
        joint_type: str = "finger",
        dovetail_angle: float = 10.0
    ) -> List[BoxPanel]:
        """
        Generates all flat panels required to assemble the box.

        Box panels:
        - Bottom: width x depth
        - Front: width x height
        - Back: width x height
        - Left: depth x height
        - Right: depth x height
        - Top: width x depth (for 6-sided or sliding-lid)
        """
        panels: List[BoxPanel] = []

        is_open_top = (style == "open-top")
        is_sliding_lid = (style == "sliding-lid")

        # 1. BOTTOM PANEL: width x depth
        # Bottom receives tabs from Front, Back, Left, Right -> female on all 4 sides
        bot_edges = {"bottom": "female", "right": "female", "top": "female", "left": "female"}
        bot_outline = cls.generate_panel_outline(
            width, depth, thickness, finger_width, bot_edges, kerf=kerf,
            joint_type=joint_type, dovetail_angle=dovetail_angle
        )
        panels.append(BoxPanel(name="Bottom", width=width, height=depth, outline=bot_outline, internal_cutouts=[]))

        # 2. FRONT PANEL: width x height
        # Bottom: male (fits bottom female)
        # Left: male (fits left side female)
        # Right: male (fits right side female)
        # Top: female if closed box, flat if open-top or sliding-lid
        front_top = "female" if (not is_open_top and not is_sliding_lid) else "flat"
        front_edges = {"bottom": "male", "right": "male", "top": front_top, "left": "male"}
        front_outline = cls.generate_panel_outline(
            width, height, thickness, finger_width, front_edges, kerf=kerf,
            joint_type=joint_type, dovetail_angle=dovetail_angle
        )
        panels.append(BoxPanel(name="Front", width=width, height=height, outline=front_outline, internal_cutouts=[]))

        # 3. BACK PANEL: width x height (same joint structure as Front)
        back_outline = cls.generate_panel_outline(
            width, height, thickness, finger_width, front_edges, kerf=kerf,
            joint_type=joint_type, dovetail_angle=dovetail_angle
        )
        panels.append(BoxPanel(name="Back", width=width, height=height, outline=back_outline, internal_cutouts=[]))

        # 4. LEFT PANEL: depth x height
        # Bottom: male (fits bottom female)
        # Left (meets Back): female (receives Back male)
        # Right (meets Front): female (receives Front male)
        # Top: female if closed, flat if open top
        side_top = "female" if (not is_open_top and not is_sliding_lid) else "flat"
        left_edges = {"bottom": "male", "right": "female", "top": side_top, "left": "female"}
        left_outline = cls.generate_panel_outline(
            depth, height, thickness, finger_width, left_edges, kerf=kerf,
            joint_type=joint_type, dovetail_angle=dovetail_angle
        )

        left_cutouts = []
        if is_sliding_lid:
            # Slot for sliding lid: 3mm from top rim, thickness tall, depth long
            slot_y = height - 5.0 - thickness
            left_cutouts.append([
                (thickness, slot_y), (depth - thickness, slot_y),
                (depth - thickness, slot_y + thickness), (thickness, slot_y + thickness),
                (thickness, slot_y)
            ])
        panels.append(BoxPanel(name="Left", width=depth, height=height, outline=left_outline, internal_cutouts=left_cutouts))

        # 5. RIGHT PANEL: depth x height (same joint structure as Left)
        right_outline = cls.generate_panel_outline(
            depth, height, thickness, finger_width, left_edges, kerf=kerf,
            joint_type=joint_type, dovetail_angle=dovetail_angle
        )
        right_cutouts = []
        if is_sliding_lid:
            slot_y = height - 5.0 - thickness
            right_cutouts.append([
                (thickness, slot_y), (depth - thickness, slot_y),
                (depth - thickness, slot_y + thickness), (thickness, slot_y + thickness),
                (thickness, slot_y)
            ])
        panels.append(BoxPanel(name="Right", width=depth, height=height, outline=right_outline, internal_cutouts=right_cutouts))

        # 6. TOP PANEL (if not open-top)
        if not is_open_top:
            if is_sliding_lid:
                # Sliding lid slides into side slots: slightly narrower than width
                lid_w = width - (thickness * 2.0) + (thickness * 1.5)
                lid_d = depth - thickness
                # Flat rectangular lid with finger notch
                lid_outline = [
                    (0.0, 0.0), (lid_w, 0.0), (lid_w, lid_d), (0.0, lid_d), (0.0, 0.0)
                ]
                # Finger notch cutout (15mm circle) near front
                notch_cx, notch_cy = lid_w / 2.0, 15.0
                notch_r = 7.5
                notch = [
                    (notch_cx + notch_r * math.cos(math.radians(a)), notch_cy + notch_r * math.sin(math.radians(a)))
                    for a in range(0, 360, 15)
                ]
                notch.append(notch[0])
                panels.append(BoxPanel(name="Sliding_Lid", width=lid_w, height=lid_d, outline=lid_outline, internal_cutouts=[notch]))
            else:
                # Standard enclosed top: receives tabs from all 4 walls (female on all sides)
                top_edges = {"bottom": "female", "right": "female", "top": "female", "left": "female"}
                top_outline = cls.generate_panel_outline(
                    width, depth, thickness, finger_width, top_edges, kerf=kerf,
                    joint_type=joint_type, dovetail_angle=dovetail_angle
                )
                panels.append(BoxPanel(name="Top", width=width, height=depth, outline=top_outline, internal_cutouts=[]))

        return panels

    @classmethod
    def layout_to_entities(
        cls,
        panels: List[BoxPanel],
        start_x: float = 10.0,
        start_y: float = 10.0,
        spacing: float = 8.0,
        layer_id: int = 0,
        include_labels: bool = True
    ) -> List[LaserEntity]:
        """
        Arranges the generated 2D panels flat side-by-side with spacing and converts them into PathEntities.
        """
        entities: List[LaserEntity] = []
        cur_x = start_x
        cur_y = start_y
        row_max_h = 0.0
        max_sheet_w = 400.0  # wrap to next row if exceeding standard sheet width

        for p in panels:
            # Check row wrapping
            if cur_x + p.width > max_sheet_w and cur_x > start_x:
                cur_x = start_x
                cur_y += row_max_h + spacing
                row_max_h = 0.0

            all_contours = [p.outline]
            if p.internal_cutouts:
                all_contours.extend(p.internal_cutouts)

            ent = PathEntity(
                layer_id=layer_id,
                name=f"Box_{p.name}",
                x=cur_x,
                y=cur_y,
                contours=all_contours,
                closed=True
            )
            entities.append(ent)

            if include_labels:
                lbl = TextEntity(
                    layer_id=layer_id,
                    name=f"Label_{p.name}",
                    x=cur_x + p.width / 2.0 - 10.0,
                    y=cur_y + p.height / 2.0 - 2.5,
                    text=p.name.upper(),
                    font_size=5.0,
                    fill_mode="Outline"
                )
                entities.append(lbl)

            cur_x += p.width + spacing
            if p.height > row_max_h:
                row_max_h = p.height

        return entities
