"""
LaserForge QR Code & 1D Barcode Generator Engine.
Generates precision vector contours, module rectangles, and laser raster bitmaps
for 2D QR codes and standard 1D barcodes (Code 128, Code 39, EAN-13, UPC-A, ISBN).
"""

from typing import List, Tuple, Optional, Dict, Any
import os
import time
from PIL import Image
import numpy as np

try:
    import qrcode
    from qrcode.constants import (
        ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
    )
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

try:
    import barcode
    from barcode.writer import ImageWriter
    HAS_BARCODE = True
except ImportError:
    HAS_BARCODE = False

from laserforge.core.models import (
    LaserEntity, RectEntity, PathEntity, TextEntity, ImageEntity
)


class BarcodeGenerator:
    """Parametric vector and raster generator for QR codes and 1D barcodes."""

    SUPPORTED_BARCODES = [
        ("Code 128 (General Alpha-Numeric / Serial)", "code128"),
        ("Code 39 (Industrial / Military)", "code39"),
        ("EAN-13 (Retail Standard - 12/13 digits)", "ean13"),
        ("UPC-A (North American Retail - 11/12 digits)", "upca"),
        ("ISBN-13 (Book Publishing)", "isbn13"),
        ("ITF / Interleaved 2 of 5 (Packaging)", "itf"),
    ]

    QR_ERROR_LEVELS = {
        "L (7% Recovery - Fast)": "L",
        "M (15% Recovery - Standard)": "M",
        "Q (25% Recovery - High)": "Q",
        "H (30% Recovery - Best for Wood/Metal Engraving)": "H",
    }

    # -------------------------------------------------------------------------
    # Format Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def build_wifi_string(ssid: str, password: str = "", auth_type: str = "WPA", hidden: bool = False) -> str:
        """Constructs a standard Wi-Fi QR configuration payload."""
        h = "true" if hidden else "false"
        return f"WIFI:T:{auth_type};S:{ssid};P:{password};H:{h};;"

    @staticmethod
    def build_vcard_string(
        name: str,
        phone: str = "",
        email: str = "",
        org: str = "",
        title: str = "",
        url: str = ""
    ) -> str:
        """Constructs a standard vCard 3.0 electronic business card."""
        lines = [
            "BEGIN:VCARD",
            "VERSION:3.0",
            f"FN:{name}",
            f"N:{name};;;;",
        ]
        if org:
            lines.append(f"ORG:{org}")
        if title:
            lines.append(f"TITLE:{title}")
        if phone:
            lines.append(f"TEL;TYPE=CELL,VOICE:{phone}")
        if email:
            lines.append(f"EMAIL;TYPE=PREF,INTERNET:{email}")
        if url:
            lines.append(f"URL:{url}")
        lines.append("END:VCARD")
        return "\n".join(lines)

    @staticmethod
    def build_sms_string(phone: str, body: str = "") -> str:
        return f"SMSTO:{phone}:{body}"

    @staticmethod
    def build_email_string(email: str, subject: str = "", body: str = "") -> str:
        from urllib.parse import quote
        q_subj = quote(subject)
        q_body = quote(body)
        return f"mailto:{email}?subject={q_subj}&body={q_body}"

    # -------------------------------------------------------------------------
    # QR Code Vector & Raster Generation
    # -------------------------------------------------------------------------

    @classmethod
    def generate_qr_matrix(
        cls,
        data: str,
        error_correction: str = "H",
        border: int = 1
    ) -> List[List[bool]]:
        """Generates boolean 2D matrix of QR code modules."""
        if not HAS_QRCODE:
            raise RuntimeError("The 'qrcode' python package is not installed.")

        ec_map = {
            "L": ERROR_CORRECT_L,
            "M": ERROR_CORRECT_M,
            "Q": ERROR_CORRECT_Q,
            "H": ERROR_CORRECT_H,
        }
        ec_val = ec_map.get(error_correction.upper(), ERROR_CORRECT_H)

        qr = qrcode.QRCode(
            version=None,
            error_correction=ec_val,
            box_size=1,
            border=border
        )
        qr.add_data(data)
        qr.make(fit=True)
        return qr.get_matrix()

    @classmethod
    def generate_qr_vector_contours(
        cls,
        data: str,
        size_mm: float,
        error_correction: str = "H",
        border: int = 1,
        offset_x: float = 0.0,
        offset_y: float = 0.0
    ) -> List[List[Tuple[float, float]]]:
        """
        Synthesizes vector polygon contours of QR code modules.
        Merges adjacent horizontal modules in each row to minimize laser head travel
        and optimize G-code path execution.
        """
        matrix = cls.generate_qr_matrix(data, error_correction, border)
        n = len(matrix)
        if n == 0:
            return []

        cell_size = size_mm / float(n)
        contours: List[List[Tuple[float, float]]] = []

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

    @classmethod
    def generate_qr_vector_entity(
        cls,
        data: str,
        size_mm: float,
        layer_id: int = 0,
        error_correction: str = "H",
        border: int = 1,
        offset_x: float = 0.0,
        offset_y: float = 0.0
    ) -> PathEntity:
        """Returns a single optimized PathEntity representing the entire vector QR code."""
        contours = cls.generate_qr_vector_contours(
            data=data,
            size_mm=size_mm,
            error_correction=error_correction,
            border=border,
            offset_x=offset_x,
            offset_y=offset_y
        )
        return PathEntity(
            layer_id=layer_id,
            name=f"QR_{data[:12]}",
            x=offset_x,
            y=offset_y,
            contours=contours
        )

    @classmethod
    def generate_qr_bitmap(
        cls,
        data: str,
        size_px: int = 600,
        error_correction: str = "H",
        border: int = 2
    ) -> Image.Image:
        """Generates a high-contrast 1-bit PIL image for raster laser engraving."""
        matrix = cls.generate_qr_matrix(data, error_correction, border)
        n = len(matrix)
        arr = np.ones((n, n), dtype=np.uint8) * 255
        for r in range(n):
            for c in range(n):
                if matrix[r][c]:
                    arr[r, c] = 0
        img = Image.fromarray(arr)
        return img.resize((size_px, size_px), Image.Resampling.NEAREST)

    # -------------------------------------------------------------------------
    # 1D Barcode Vector & Raster Generation
    # -------------------------------------------------------------------------

    @classmethod
    def generate_barcode_bars(
        cls,
        code_type: str,
        data: str,
        width_mm: float,
        height_mm: float,
        layer_id: int = 0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        show_text: bool = True,
        text_height_mm: float = 4.0
    ) -> Tuple[List[RectEntity], Optional[TextEntity], str]:
        """
        Generates vector RectEntity bars and optional human-readable TextEntity.
        Returns: (list_of_rect_entities, optional_text_entity, full_code_string).
        """
        if not HAS_BARCODE:
            raise RuntimeError("The 'barcode' (python-barcode) package is not installed.")

        # Clean / prepare data
        cleaned_data = str(data).strip()
        barcode_cls = barcode.get_barcode_class(code_type.lower())

        if code_type.lower() in ("ean13", "ean"):
            # Strip non-digits and pad/truncate to 12 or 13 digits
            digits = "".join(filter(str.isdigit, cleaned_data))[:12]
            digits = digits.ljust(12, "0")
            bc_inst = barcode_cls(digits)
        elif code_type.lower() in ("upca", "upc"):
            digits = "".join(filter(str.isdigit, cleaned_data))[:11]
            digits = digits.ljust(11, "0")
            bc_inst = barcode_cls(digits)
        elif code_type.lower() == "code39":
            cleaned = "".join(c for c in cleaned_data.upper() if c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%")
            if not cleaned:
                cleaned = "SAMPLE"
            bc_inst = barcode_cls(cleaned, add_checksum=False)
        else:
            bc_inst = barcode_cls(cleaned_data)

        full_code = getattr(bc_inst, "get_fullcode", lambda: cleaned_data)()

        # Build raw binary bit sequence ('1' = bar, '0' = space)
        raw_build = bc_inst.build()
        bit_string = "".join(raw_build)
        num_modules = len(bit_string)
        if num_modules == 0:
            return [], None, full_code

        module_width = width_mm / float(num_modules)
        actual_bar_height = max(5.0, height_mm - (text_height_mm + 1.5 if show_text else 0.0))

        # Merge consecutive 1s into bars
        rect_entities: List[RectEntity] = []
        i = 0
        while i < num_modules:
            if bit_string[i] == '1':
                start_i = i
                while i < num_modules and bit_string[i] == '1':
                    i += 1
                run_len = i - start_i
                bx = offset_x + start_i * module_width
                bw = run_len * module_width
                by = offset_y
                rect_entities.append(RectEntity(
                    layer_id=layer_id,
                    name=f"Bar_{start_i}",
                    x=bx,
                    y=by,
                    width=bw,
                    height=actual_bar_height
                ))
            else:
                i += 1

        # Human-readable text entity below the bars
        text_entity = None
        if show_text:
            text_y = offset_y + actual_bar_height + 1.5
            text_entity = TextEntity(
                layer_id=layer_id,
                name=f"Code_Text_{full_code}",
                x=offset_x,
                y=text_y,
                text=str(full_code),
                font_family="Monospace",
                font_size=max(8.0, text_height_mm * 2.8),
                fill_mode="Fill",
                width=width_mm,
                height=text_height_mm
            )

        return rect_entities, text_entity, full_code

    @classmethod
    def generate_barcode_bitmap(
        cls,
        code_type: str,
        data: str,
        width_px: int = 600,
        height_px: int = 250,
        show_text: bool = True
    ) -> Image.Image:
        """Generates a PIL Image barcode with clean typography and crisp bars."""
        if not HAS_BARCODE:
            raise RuntimeError("The 'barcode' package is not installed.")

        cleaned_data = str(data).strip()
        barcode_cls = barcode.get_barcode_class(code_type.lower())

        if code_type.lower() in ("ean13", "ean"):
            digits = "".join(filter(str.isdigit, cleaned_data))[:12].ljust(12, "0")
            bc_inst = barcode_cls(digits, writer=ImageWriter())
        elif code_type.lower() in ("upca", "upc"):
            digits = "".join(filter(str.isdigit, cleaned_data))[:11].ljust(11, "0")
            bc_inst = barcode_cls(digits, writer=ImageWriter())
        elif code_type.lower() == "code39":
            cleaned = "".join(c for c in cleaned_data.upper() if c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%") or "SAMPLE"
            bc_inst = barcode_cls(cleaned, writer=ImageWriter(), add_checksum=False)
        else:
            bc_inst = barcode_cls(cleaned_data, writer=ImageWriter())

        writer_options = {
            "write_text": show_text,
            "font_size": 10,
            "text_distance": 4,
            "quiet_zone": 4,
        }
        rendered = bc_inst.render(writer_options)
        return rendered.resize((width_px, height_px), Image.Resampling.LANCZOS)
