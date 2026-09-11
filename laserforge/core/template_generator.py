"""
LaserForge Project Templates & Calibration Matrix Generator.
Provides instant parametric templates for coasters, tumblers, keychains, tags,
holiday ornaments, signs, and 3W diode laser speed/power calibration test matrices.
"""

from typing import List, Tuple, Dict, Any
import math
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)


class TemplateGenerator:

    @staticmethod
    def generate_round_coaster(
        diameter: float = 100.0,
        inner_border_offset: float = 6.0,
        custom_text: str = "COASTER",
        add_text: bool = True
    ) -> List[LaserEntity]:
        """Generates round coaster with outer cut circle, decorative inner ring, and center text."""
        entities: List[LaserEntity] = []
        r = diameter / 2.0
        # Outer cut perimeter (Layer 1: Cut)
        entities.append(CircleEntity(
            layer_id=1, name="Coaster Cut Perimeter",
            x=r, y=r, radius_x=r, radius_y=r
        ))
        # Inner decorative ring (Layer 0: Engrave)
        if inner_border_offset > 0 and (r - inner_border_offset) > 5.0:
            ir = r - inner_border_offset
            entities.append(CircleEntity(
                layer_id=0, name="Decorative Inner Ring",
                x=r, y=r, radius_x=ir, radius_y=ir
            ))
        # Center text
        if add_text and custom_text.strip():
            font_sz = max(4.0, min(16.0, diameter * 0.12))
            text_w = len(custom_text) * font_sz * 0.65
            entities.append(TextEntity(
                layer_id=0, name="Coaster Text",
                x=r - (text_w / 2.0), y=r - (font_sz / 2.0),
                text=custom_text, font_size=font_sz, bold=True,
                width=text_w, height=font_sz, fill_mode="Fill"
            ))
        return entities

    @staticmethod
    def generate_square_coaster(
        size: float = 95.0,
        corner_radius: float = 8.0,
        inner_offset: float = 5.0,
        custom_text: str = "COASTER",
        add_text: bool = True
    ) -> List[LaserEntity]:
        """Generates square coaster with rounded corners, inner border, and text."""
        entities: List[LaserEntity] = []
        # Outer cut rectangle (Layer 1)
        entities.append(RectEntity(
            layer_id=1, name="Square Coaster Cut",
            x=0.0, y=0.0, width=size, height=size,
            corner_radius=corner_radius
        ))
        # Inner engrave rectangle (Layer 0)
        if inner_offset > 0 and (size - 2 * inner_offset) > 10.0:
            inner_sz = size - 2 * inner_offset
            inner_r = max(0.0, corner_radius - inner_offset)
            entities.append(RectEntity(
                layer_id=0, name="Inner Border",
                x=inner_offset, y=inner_offset,
                width=inner_sz, height=inner_sz,
                corner_radius=inner_r
            ))
        # Center text
        if add_text and custom_text.strip():
            font_sz = max(4.0, min(16.0, size * 0.12))
            text_w = len(custom_text) * font_sz * 0.65
            entities.append(TextEntity(
                layer_id=0, name="Coaster Monogram",
                x=(size / 2.0) - (text_w / 2.0), y=(size / 2.0) - (font_sz / 2.0),
                text=custom_text, font_size=font_sz, bold=True,
                width=text_w, height=font_sz, fill_mode="Fill"
            ))
        return entities

    @staticmethod
    def generate_keychain(
        style: str = "Rounded Rectangle",
        width: float = 60.0,
        height: float = 30.0,
        hole_diameter: float = 4.0,
        hole_margin: float = 4.0,
        custom_text: str = "KEYCHAIN"
    ) -> List[LaserEntity]:
        """Generates a keychain with hole and custom text."""
        entities: List[LaserEntity] = []
        hole_r = hole_diameter / 2.0
        hole_x = hole_margin + hole_r
        hole_y = height / 2.0

        if style == "Teardrop":
            # Teardrop / Tag contour
            contours = []
            pts = []
            steps = 36
            cx, cy = width - (height / 2.0), height / 2.0
            r = height / 2.0
            # Right semi-circle
            for i in range(-9, 10):
                ang = math.radians(i * 10)
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            # Left pointed/rounded tip
            tip_r = hole_margin + hole_r + 2.0
            tip_x = tip_r
            for i in range(9, 28):
                ang = math.radians(i * 10)
                pts.append((tip_x + tip_r * 0.7 * math.cos(ang), cy + tip_r * 0.7 * math.sin(ang)))
            contours.append(pts)
            entities.append(PathEntity(layer_id=1, name="Teardrop Keychain Cut", x=0, y=0, contours=contours, closed=True))
            hole_x = tip_x
        elif style == "Oval":
            rx, ry = width / 2.0, height / 2.0
            entities.append(CircleEntity(layer_id=1, name="Oval Keychain Cut", x=rx, y=ry, radius_x=rx, radius_y=ry))
            hole_x = hole_margin + hole_r
        else:
            # Rounded Rectangle
            entities.append(RectEntity(
                layer_id=1, name="Keychain Cut",
                x=0.0, y=0.0, width=width, height=height,
                corner_radius=min(6.0, height / 3.0)
            ))

        # Hanging hole (Layer 1: Cut)
        entities.append(CircleEntity(
            layer_id=1, name="Hanger Hole",
            x=hole_x, y=hole_y, radius_x=hole_r, radius_y=hole_r
        ))

        # Text (Layer 0: Engrave)
        if custom_text.strip():
            font_sz = max(4.0, min(14.0, height * 0.4))
            avail_w = width - (hole_x + hole_r + 4.0)
            text_w = min(avail_w, len(custom_text) * font_sz * 0.65)
            text_x = (hole_x + hole_r + 4.0) + (avail_w - text_w) / 2.0
            entities.append(TextEntity(
                layer_id=0, name="Keychain Text",
                x=text_x, y=(height / 2.0) - (font_sz / 2.0),
                text=custom_text, font_size=font_sz, bold=True,
                width=text_w, height=font_sz, fill_mode="Fill"
            ))

        return entities

    @staticmethod
    def generate_tumbler_wrap(
        tumbler_type: str = "20oz Skinny Tumbler",
        custom_diameter: float = 73.0,
        custom_height: float = 204.0,
        seam_margin_mm: float = 2.0
    ) -> List[LaserEntity]:
        """
        Calculates flat cylinder unwrap template for rotary or flat engraving.
        Width = pi * diameter.
        """
        if "20oz" in tumbler_type:
            d = 73.0
            h = 204.0
        elif "30oz" in tumbler_type:
            d = 78.0
            h = 240.0
        else:
            d = custom_diameter
            h = custom_height

        circ_w = math.pi * d
        entities: List[LaserEntity] = []

        # Outer wrap boundary (Layer 2: Tool/Guide or Layer 0)
        entities.append(RectEntity(
            layer_id=2, name="Tumbler Outer Perimeter",
            x=0.0, y=0.0, width=circ_w, height=h
        ))

        # Seam overlap guideline
        entities.append(LineEntity(
            layer_id=2, name="Seam Guideline Left",
            x=seam_margin_mm, y=0.0, x2=seam_margin_mm, y2=h
        ))
        entities.append(LineEntity(
            layer_id=2, name="Seam Guideline Right",
            x=circ_w - seam_margin_mm, y=0.0, x2=circ_w - seam_margin_mm, y2=h
        ))

        # Centerline guide
        entities.append(LineEntity(
            layer_id=2, name="Centerline Guide",
            x=circ_w / 2.0, y=0.0, x2=circ_w / 2.0, y2=h
        ))

        # Description label
        label = f"{tumbler_type} (Dia: {d}mm -> Circumference: {circ_w:.1f}mm × {h:.1f}mm)"
        entities.append(TextEntity(
            layer_id=0, name="Wrap Dimensions",
            x=circ_w * 0.1, y=h * 0.45, text=label,
            font_size=8.0, bold=False, width=circ_w * 0.8, height=8.0,
            fill_mode="Outline"
        ))

        return entities

    @staticmethod
    def generate_holiday_ornament(
        style: str = "Christmas Bauble",
        diameter: float = 75.0,
        hanger_hole_dia: float = 4.5,
        custom_text: str = "2026"
    ) -> List[LaserEntity]:
        """Generates round bauble or star ornament with integrated hanging loop."""
        entities: List[LaserEntity] = []
        r = diameter / 2.0
        loop_h = 10.0
        loop_w = 12.0
        loop_r = loop_w / 2.0

        # Construct bauble with top hanging loop as closed PathEntity
        pts = []
        # Main circle from ang=15 to 165
        steps = 48
        for i in range(steps + 1):
            ang = math.radians(20 + i * (320.0 / steps))
            pts.append((r + r * math.cos(ang), r + loop_h + r * math.sin(ang)))

        # Top loop bridge
        pts.append((r + loop_r, loop_h))
        # Top loop arc
        for i in range(12):
            ang = math.radians(0 + i * 15)
            pts.append((r + loop_r * math.cos(ang), loop_r - loop_r * math.sin(ang)))
        pts.append((r - loop_r, loop_h))

        entities.append(PathEntity(
            layer_id=1, name="Ornament Cut Perimeter",
            x=0, y=0, contours=[pts], closed=True
        ))

        # Hanger hole
        entities.append(CircleEntity(
            layer_id=1, name="Hanger Hole",
            x=r, y=loop_r,
            radius_x=hanger_hole_dia / 2.0, radius_y=hanger_hole_dia / 2.0
        ))

        # Engraved center text
        if custom_text.strip():
            font_sz = max(6.0, r * 0.3)
            text_w = len(custom_text) * font_sz * 0.65
            entities.append(TextEntity(
                layer_id=0, name="Ornament Year/Name",
                x=r - (text_w / 2.0), y=(r + loop_h) - (font_sz / 2.0),
                text=custom_text, font_size=font_sz, bold=True,
                width=text_w, height=font_sz, fill_mode="Fill"
            ))

        return entities

    @staticmethod
    def generate_speed_power_test_matrix(
        cols: int = 5,
        rows: int = 5,
        speed_min: float = 200.0,
        speed_max: float = 1200.0,
        power_min: float = 20.0,
        power_max: float = 100.0,
        patch_size: float = 10.0,
        gap: float = 3.0
    ) -> List[LaserEntity]:
        """
        Generates a comprehensive Diode Laser Speed vs. Power Calibration Test Grid.
        Essential for dialing in new materials (wood, leather, acrylic, slate).
        """
        entities: List[LaserEntity] = []
        origin_x = 22.0
        origin_y = 18.0

        speeds = [speed_min + i * (speed_max - speed_min) / max(1, cols - 1) for i in range(cols)]
        powers = [power_min + j * (power_max - power_min) / max(1, rows - 1) for j in range(rows)]

        # Title
        entities.append(TextEntity(
            layer_id=0, name="Title",
            x=origin_x, y=2.0,
            text="3W DIODE SPEED vs POWER TEST MATRIX",
            font_size=4.5, bold=True, width=80.0, height=4.5, fill_mode="Fill"
        ))

        # Column Header Labels (Speed mm/min)
        for c, spd in enumerate(speeds):
            px = origin_x + c * (patch_size + gap)
            entities.append(TextEntity(
                layer_id=0, name=f"Speed_{spd:.0f}",
                x=px, y=10.0,
                text=f"{spd:.0f}",
                font_size=3.5, bold=True, width=patch_size, height=3.5, fill_mode="Outline"
            ))

        # Row Header Labels (Power %)
        for r, pwr in enumerate(powers):
            py = origin_y + r * (patch_size + gap)
            entities.append(TextEntity(
                layer_id=0, name=f"Power_{pwr:.0f}%",
                x=2.0, y=py + (patch_size / 2.0) - 1.5,
                text=f"{pwr:.0f}%",
                font_size=3.5, bold=True, width=16.0, height=3.5, fill_mode="Outline"
            ))

        # Test Patches
        for r, pwr in enumerate(powers):
            py = origin_y + r * (patch_size + gap)
            for c, spd in enumerate(speeds):
                px = origin_x + c * (patch_size + gap)
                entities.append(RectEntity(
                    layer_id=0,
                    name=f"Test_{spd:.0f}mm_{pwr:.0f}pct",
                    x=px, y=py,
                    width=patch_size, height=patch_size
                ))

        # Outer framing border
        total_w = origin_x + cols * (patch_size + gap) + 4.0
        total_h = origin_y + rows * (patch_size + gap) + 4.0
        entities.append(RectEntity(
            layer_id=1, name="Matrix Perimeter Cut",
            x=0.0, y=0.0, width=total_w, height=total_h, corner_radius=3.0
        ))

        return entities

    @staticmethod
    def generate_calibration_ruler(
        length_mm: float = 100.0,
        height_mm: float = 20.0
    ) -> List[LaserEntity]:
        """Generates a precision metric calibration ruler with 1mm and 5mm graduation ticks."""
        entities: List[LaserEntity] = []

        # Outer cut boundary
        entities.append(RectEntity(
            layer_id=1, name="Ruler Body Cut",
            x=0.0, y=0.0, width=length_mm, height=height_mm, corner_radius=2.0
        ))

        # Baseline
        entities.append(LineEntity(
            layer_id=0, name="Ruler Baseline",
            x=0.0, y=height_mm - 2.0, x2=length_mm, y2=height_mm - 2.0
        ))

        # Millimeter and centimeter ticks
        for mm in range(int(length_mm) + 1):
            x = float(mm)
            if mm % 10 == 0:
                tick_h = 7.0
                # Label
                if mm < int(length_mm):
                    entities.append(TextEntity(
                        layer_id=0, name=f"Num_{mm}",
                        x=x - 2.0, y=height_mm - 2.0 - tick_h - 4.5,
                        text=str(mm // 10), font_size=3.5, bold=True,
                        width=6.0, height=3.5, fill_mode="Outline"
                    ))
            elif mm % 5 == 0:
                tick_h = 4.5
            else:
                tick_h = 2.5

            entities.append(LineEntity(
                layer_id=0, name=f"Tick_{mm}",
                x=x, y=height_mm - 2.0, x2=x, y2=height_mm - 2.0 - tick_h
            ))

        return entities
