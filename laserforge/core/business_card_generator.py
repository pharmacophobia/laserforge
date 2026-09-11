"""
LaserForge Business Card & Jig Generation Engine.
Provides parametric card geometries (anodized metal blanks, US/EU/JP standards),
vector QR code synthesis, automated layout typography, wasteboard cutting jigs,
and multi-card batch production arrays.
"""

from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass, field
import math

from laserforge.core.models import (
    LaserEntity, RectEntity, LineEntity, CircleEntity, TextEntity, PathEntity
)


# Standard Commercial Business Card Specifications (mm)
CARD_PRESETS = {
    "Metal Card Blank (85.6 × 54.0 mm, R3mm)": {
        "width": 85.6,
        "height": 53.98,
        "corner_radius": 3.0,
        "desc": "Standard anodized aluminum / stainless steel laser engraving card blank (ISO 7810 ID-1 credit card size)."
    },
    "US / North America Standard (88.9 × 50.8 mm / 3.5×2 in)": {
        "width": 88.9,
        "height": 50.8,
        "corner_radius": 0.0,
        "desc": "Traditional North American business card dimension."
    },
    "European Standard (85.0 × 55.0 mm)": {
        "width": 85.0,
        "height": 55.0,
        "corner_radius": 0.0,
        "desc": "Standard European business card dimension."
    },
    "Japanese Standard (91.0 × 55.0 mm)": {
        "width": 91.0,
        "height": 55.0,
        "corner_radius": 0.0,
        "desc": "Standard Japanese Meishi business card dimension."
    }
}


def generate_qr_contours(
    data: str,
    size_mm: float = 22.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    border: int = 1
) -> List[List[Tuple[float, float]]]:
    """
    Synthesizes a vector QR code as closed polygon contours.
    Merges adjacent horizontal module runs into solid rectangle loops for fast laser engraving.
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=border
        )
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()
    except Exception:
        # Graceful fallback: simple square target marker if qrcode fails
        return [
            [(offset_x, offset_y), (offset_x + size_mm, offset_y),
             (offset_x + size_mm, offset_y + size_mm), (offset_x, offset_y + size_mm),
             (offset_x, offset_y)]
        ]

    n = len(matrix)
    cell_size = size_mm / float(n)
    contours: List[List[Tuple[float, float]]] = []

    # Merge contiguous horizontal runs in each row for clean G-code
    for r in range(n):
        c = 0
        while c < n:
            if matrix[r][c]:
                start_c = c
                while c < n and matrix[r][c]:
                    c += 1
                end_c = c
                x1 = offset_x + start_c * cell_size
                x2 = offset_x + end_c * cell_size
                y1 = offset_y + r * cell_size
                y2 = offset_y + (r + 1) * cell_size
                poly = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
                contours.append(poly)
            else:
                c += 1

    return contours


@dataclass
class BusinessCardConfig:
    width: float = 85.6
    height: float = 54.0
    corner_radius: float = 3.0
    border_mode: str = "guide"  # "guide" (T1 Tool), "cut" (C02 Red), "none"

    # Typography & Info
    company_name: str = "FORGE DYNAMICS"
    person_name: str = "Alex Mercer"
    title: str = "Lead Laser Engineer"
    phone: str = "+1 (555) 382-9104"
    email: str = "alex@forgedynamics.com"
    website: str = "https://forgedynamics.com"
    tagline: str = "Precision Laser Engineering & Fabrication"

    # QR Code
    include_qr: bool = True
    qr_data: str = "https://forgedynamics.com"
    qr_size: float = 24.0
    qr_position: str = "Right"  # "Right", "Left", "Bottom-Right"

    # Layout style
    layout_style: str = "Modern Split"  # "Modern Split", "Centered Classic", "Minimalist"
    artwork_layer_id: int = 0  # C00 Black
    border_layer_id: int = 12  # T1 Tool guide


class BusinessCardGenerator:
    """Core generator for individual business cards, wasteboard fixtures, and production grids."""

    @staticmethod
    def generate_single_card(
        cfg: BusinessCardConfig,
        origin_x: float = 0.0,
        origin_y: float = 0.0
    ) -> List[LaserEntity]:
        """Generates all entities for a single business card at (origin_x, origin_y)."""
        entities: List[LaserEntity] = []

        # 1. Card Perimeter Boundary
        if cfg.border_mode != "none":
            border_layer = 12 if cfg.border_mode == "guide" else 2
            border_name = "Card_Guide_Border" if cfg.border_mode == "guide" else "Card_Cut_Border"
            rect = RectEntity(
                layer_id=border_layer,
                name=border_name,
                x=origin_x,
                y=origin_y,
                width=cfg.width,
                height=cfg.height,
                corner_radius=cfg.corner_radius
            )
            entities.append(rect)

        margin = 4.0
        w = cfg.width
        h = cfg.height

        # 2. QR Code
        qr_placed = False
        qr_x = 0.0
        qr_y = 0.0
        qr_s = min(cfg.qr_size, h - margin * 2)

        if cfg.include_qr and cfg.qr_data:
            if cfg.qr_position == "Right":
                qr_x = origin_x + w - qr_s - margin
                qr_y = origin_y + (h - qr_s) / 2.0
            elif cfg.qr_position == "Left":
                qr_x = origin_x + margin
                qr_y = origin_y + (h - qr_s) / 2.0
            else:  # "Bottom-Right"
                qr_x = origin_x + w - qr_s - margin
                qr_y = origin_y + h - qr_s - margin

            qr_contours = generate_qr_contours(cfg.qr_data, size_mm=qr_s, offset_x=qr_x, offset_y=qr_y)
            qr_ent = PathEntity(
                layer_id=cfg.artwork_layer_id,
                name="Card_QR_Code",
                x=0.0,
                y=0.0,
                contours=qr_contours,
                closed=True
            )
            entities.append(qr_ent)
            qr_placed = True

        # 3. Typography Positioning based on layout style
        text_start_x = origin_x + margin
        avail_text_w = (w - qr_s - margin * 3) if (qr_placed and cfg.qr_position == "Right") else (w - margin * 2)

        if qr_placed and cfg.qr_position == "Left":
            text_start_x = origin_x + qr_s + margin * 2
            avail_text_w = w - qr_s - margin * 3

        if cfg.layout_style == "Centered Classic":
            cx = origin_x + w / 2.0
            y_cursor = origin_y + margin + 4.0

            if cfg.company_name:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Company_Name",
                    x=cx - avail_text_w / 2.0, y=y_cursor,
                    width=avail_text_w, height=5.5,
                    font_size=5.5, bold=True, text=cfg.company_name
                ))
                y_cursor += 7.0

            if cfg.person_name:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Person_Name",
                    x=cx - avail_text_w / 2.0, y=y_cursor,
                    width=avail_text_w, height=4.5,
                    font_size=4.5, bold=True, text=cfg.person_name
                ))
                y_cursor += 5.5

            if cfg.title:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Job_Title",
                    x=cx - avail_text_w / 2.0, y=y_cursor,
                    width=avail_text_w, height=3.2,
                    font_size=3.2, text=cfg.title
                ))
                y_cursor += 5.5

            # Contact lines
            contacts = [c for c in (cfg.phone, cfg.email, cfg.website) if c]
            for c_txt in contacts:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Contact_Line",
                    x=cx - avail_text_w / 2.0, y=y_cursor,
                    width=avail_text_w, height=2.6,
                    font_size=2.6, text=c_txt
                ))
                y_cursor += 3.8

        else:
            # Modern Split (Left text, right QR)
            y_cursor = origin_y + margin + 3.0

            if cfg.company_name:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Company_Name",
                    x=text_start_x, y=y_cursor,
                    width=avail_text_w, height=5.5,
                    font_size=5.5, bold=True, text=cfg.company_name
                ))
                y_cursor += 7.5

            if cfg.tagline:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Company_Tagline",
                    x=text_start_x, y=y_cursor,
                    width=avail_text_w, height=2.4,
                    font_size=2.4, text=cfg.tagline
                ))
                y_cursor += 5.0

            # Subtle accent separator line
            line_y = y_cursor + 1.0
            entities.append(LineEntity(
                layer_id=cfg.artwork_layer_id, name="Accent_Line",
                x=text_start_x, y=line_y,
                x2=text_start_x + min(40.0, avail_text_w), y2=line_y
            ))
            y_cursor += 4.5

            if cfg.person_name:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Person_Name",
                    x=text_start_x, y=y_cursor,
                    width=avail_text_w, height=4.2,
                    font_size=4.2, bold=True, text=cfg.person_name
                ))
                y_cursor += 5.5

            if cfg.title:
                entities.append(TextEntity(
                    layer_id=cfg.artwork_layer_id, name="Job_Title",
                    x=text_start_x, y=y_cursor,
                    width=avail_text_w, height=3.0,
                    font_size=3.0, text=cfg.title
                ))
                y_cursor += 5.0

            contacts = [c for c in (cfg.phone, cfg.email, cfg.website) if c]
            for c_txt in contacts:
                if y_cursor + 3.0 < origin_y + h - margin:
                    entities.append(TextEntity(
                        layer_id=cfg.artwork_layer_id, name="Contact_Line",
                        x=text_start_x, y=y_cursor,
                        width=avail_text_w, height=2.5,
                        font_size=2.5, text=c_txt
                    ))
                    y_cursor += 3.8

        return entities

    @staticmethod
    def generate_card_jig_fixture(
        cols: int = 3,
        rows: int = 2,
        card_w: float = 85.6,
        card_h: float = 54.0,
        corner_radius: float = 3.0,
        spacing_x: float = 6.0,
        spacing_y: float = 6.0,
        finger_notches: bool = True,
        start_x: float = 20.0,
        start_y: float = 20.0,
        jig_layer_id: int = 2  # C02 Red line cut
    ) -> List[LaserEntity]:
        """
        Generates a laser-cuttable card holding fixture (jig) for wasteboard or acrylic.
        Creates exact card pocket cutouts with optional ergonomic thumb release cutouts.
        """
        entities: List[LaserEntity] = []

        total_w = cols * card_w + (cols - 1) * spacing_x
        total_h = rows * card_h + (rows - 1) * spacing_y
        outer_pad = 12.0

        # Outer Jig Mounting Plate Boundary
        outer_plate = RectEntity(
            layer_id=jig_layer_id,
            name="Jig_Outer_Plate",
            x=start_x - outer_pad,
            y=start_y - outer_pad,
            width=total_w + outer_pad * 2.0,
            height=total_h + outer_pad * 2.0,
            corner_radius=4.0
        )
        entities.append(outer_plate)

        # Jig Title Text
        entities.append(TextEntity(
            layer_id=0,
            name="Jig_Label",
            x=start_x,
            y=start_y - outer_pad + 3.0,
            width=total_w,
            height=3.5,
            font_size=3.5,
            bold=True,
            text=f"LaserForge Card Jig ({cols}x{rows}) - Pocket: {card_w} x {card_h} mm"
        ))

        # Card Pockets & Finger Notches
        for r in range(rows):
            for c in range(cols):
                cx = start_x + c * (card_w + spacing_x)
                cy = start_y + r * (card_h + spacing_y)

                # Card Pocket Cutout
                pocket = RectEntity(
                    layer_id=jig_layer_id,
                    name=f"Pocket_R{r+1}_C{c+1}",
                    x=cx,
                    y=cy,
                    width=card_w,
                    height=card_h,
                    corner_radius=corner_radius
                )
                entities.append(pocket)

                # Finger Release Cutout (semi-circle notch at top edge to easily remove cards)
                if finger_notches:
                    notch_r = 6.0
                    notch_cx = cx + card_w / 2.0
                    notch_cy = cy
                    notch = CircleEntity(
                        layer_id=jig_layer_id,
                        name=f"Finger_Notch_R{r+1}_C{c+1}",
                        x=notch_cx,
                        y=notch_cy,
                        radius_x=notch_r,
                        radius_y=notch_r
                    )
                    entities.append(notch)

        return entities

    @staticmethod
    def generate_batch_array(
        cfg: BusinessCardConfig,
        cols: int = 3,
        rows: int = 2,
        spacing_x: float = 6.0,
        spacing_y: float = 6.0,
        start_x: float = 20.0,
        start_y: float = 20.0
    ) -> List[LaserEntity]:
        """Replicates a business card design across an N x M grid matching the jig positions."""
        all_entities: List[LaserEntity] = []

        for r in range(rows):
            for c in range(cols):
                cx = start_x + c * (cfg.width + spacing_x)
                cy = start_y + r * (cfg.height + spacing_y)
                card_items = BusinessCardGenerator.generate_single_card(cfg, origin_x=cx, origin_y=cy)
                all_entities.extend(card_items)

        return all_entities
