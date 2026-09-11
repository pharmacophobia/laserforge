"""
LaserForge QR Code & Barcode Designer Dialog.
Provides an interactive studio for designing 2D QR codes (URL, Wi-Fi, vCard, SMS, Email)
and 1D Barcodes (Code 128, Code 39, EAN-13, UPC-A, ISBN) with real-time preview,
parametric dimensioning, and direct laser vector or raster export to the canvas.
"""

from typing import Optional, List, Tuple
import os
import time
from PIL import Image

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage, QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QTextEdit, QDoubleSpinBox, QSpinBox,
    QCheckBox, QGroupBox, QTabWidget, QWidget, QSplitter, QStackedWidget,
    QMessageBox, QScrollArea
)

from laserforge.config import LAYER_PALETTE
from laserforge.core.layer_manager import LayerManager
from laserforge.core.models import (
    LaserEntity, RectEntity, PathEntity, TextEntity, ImageEntity
)
from laserforge.core.barcode_generator import BarcodeGenerator


class BarcodeDesignerDialog(QDialog):
    """
    Dedicated studio for parametric QR and Barcode generation.
    Emits entities_generated(List[LaserEntity]) upon acceptance.
    """
    entities_generated = pyqtSignal(list)

    def __init__(
        self,
        parent=None,
        layer_manager: Optional[LayerManager] = None,
        bed_width: float = 400.0,
        bed_height: float = 400.0,
        default_layer_id: int = 0
    ):
        super().__init__(parent)
        self.setWindowTitle("LaserForge QR Code & Barcode Studio")
        self.resize(920, 620)
        self.setMinimumSize(800, 500)

        self.layer_manager = layer_manager
        self.bed_width = bed_width
        self.bed_height = bed_height
        self.active_layer_id = default_layer_id

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._update_preview)

        self._current_qr_img: Optional[Image.Image] = None
        self._current_barcode_img: Optional[Image.Image] = None

        self._init_ui()
        self._on_qr_type_changed(0)
        self._update_preview()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Tab Widget: QR Code vs 1D Barcode
        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(self._build_qr_tab(), "📱  2D QR Code Designer")
        self.main_tabs.addTab(self._build_barcode_tab(), "🏷️  1D Barcode Designer")
        self.main_tabs.currentChanged.connect(lambda _: self._update_preview())
        main_layout.addWidget(self.main_tabs, 1)

        # Bottom Bar: Layer Selection & Insertion
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)

        bottom_bar.addWidget(QLabel("Target Cut/Engrave Layer:"))
        self.combo_layer = QComboBox()
        for p in LAYER_PALETTE:
            self.combo_layer.addItem(f"Layer {p['name']} ({p['label']}) - {p['color']}", p["id"])
        self.combo_layer.setCurrentIndex(self.active_layer_id if self.active_layer_id < len(LAYER_PALETTE) else 0)
        bottom_bar.addWidget(self.combo_layer)

        bottom_bar.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_cancel)

        btn_insert = QPushButton("⚡ Insert into Canvas")
        btn_insert.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 18px;")
        btn_insert.clicked.connect(self._on_insert_clicked)
        bottom_bar.addWidget(btn_insert)

        main_layout.addLayout(bottom_bar)

    # -------------------------------------------------------------------------
    # 2D QR Code Tab
    # -------------------------------------------------------------------------

    def _build_qr_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Left Panel: Controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(450)
        scroll.setMinimumWidth(380)

        ctrl_container = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_container)
        ctrl_layout.setSpacing(8)

        # Content Type Group
        type_grp = QGroupBox("QR Code Content & Payload")
        type_layout = QVBoxLayout(type_grp)

        self.combo_qr_type = QComboBox()
        self.combo_qr_type.addItems([
            "🌐 Website / URL",
            "📝 Plain Text",
            "📶 Wi-Fi Network Credentials",
            "📇 vCard Contact Card",
            "✉️ Email Message",
            "💬 SMS / Phone Number"
        ])
        self.combo_qr_type.currentIndexChanged.connect(self._on_qr_type_changed)
        type_layout.addWidget(self.combo_qr_type)

        # Stacked Payload Editors
        self.stack_qr_inputs = QStackedWidget()

        # 0. URL
        w_url = QWidget()
        l_url = QFormLayout(w_url)
        self.txt_url = QLineEdit("https://github.com")
        self.txt_url.textChanged.connect(self._schedule_update)
        l_url.addRow("URL:", self.txt_url)
        self.stack_qr_inputs.addWidget(w_url)

        # 1. Plain Text
        w_text = QWidget()
        l_text = QVBoxLayout(w_text)
        self.txt_plain = QTextEdit("LaserForge Diode Laser Engraver")
        self.txt_plain.setMaximumHeight(80)
        self.txt_plain.textChanged.connect(self._schedule_update)
        l_text.addWidget(self.txt_plain)
        self.stack_qr_inputs.addWidget(w_text)

        # 2. Wi-Fi
        w_wifi = QWidget()
        l_wifi = QFormLayout(w_wifi)
        self.txt_wifi_ssid = QLineEdit("Shop_WiFi")
        self.txt_wifi_ssid.textChanged.connect(self._schedule_update)
        self.txt_wifi_pass = QLineEdit("LaserEngraver2026")
        self.txt_wifi_pass.textChanged.connect(self._schedule_update)
        self.combo_wifi_auth = QComboBox()
        self.combo_wifi_auth.addItems(["WPA", "WEP", "nopass"])
        self.combo_wifi_auth.currentIndexChanged.connect(self._schedule_update)
        self.chk_wifi_hidden = QCheckBox("Hidden SSID")
        self.chk_wifi_hidden.stateChanged.connect(self._schedule_update)

        l_wifi.addRow("Network SSID:", self.txt_wifi_ssid)
        l_wifi.addRow("Password:", self.txt_wifi_pass)
        l_wifi.addRow("Security:", self.combo_wifi_auth)
        l_wifi.addRow("", self.chk_wifi_hidden)
        self.stack_qr_inputs.addWidget(w_wifi)

        # 3. vCard
        w_vcard = QWidget()
        l_vcard = QFormLayout(w_vcard)
        self.txt_vc_name = QLineEdit("Jane Doe")
        self.txt_vc_name.textChanged.connect(self._schedule_update)
        self.txt_vc_org = QLineEdit("Laser Works LLC")
        self.txt_vc_org.textChanged.connect(self._schedule_update)
        self.txt_vc_title = QLineEdit("Owner & Maker")
        self.txt_vc_title.textChanged.connect(self._schedule_update)
        self.txt_vc_phone = QLineEdit("+1-555-0199")
        self.txt_vc_phone.textChanged.connect(self._schedule_update)
        self.txt_vc_email = QLineEdit("contact@laserworks.com")
        self.txt_vc_email.textChanged.connect(self._schedule_update)
        self.txt_vc_url = QLineEdit("https://laserworks.com")
        self.txt_vc_url.textChanged.connect(self._schedule_update)

        l_vcard.addRow("Full Name:", self.txt_vc_name)
        l_vcard.addRow("Company:", self.txt_vc_org)
        l_vcard.addRow("Title:", self.txt_vc_title)
        l_vcard.addRow("Phone:", self.txt_vc_phone)
        l_vcard.addRow("Email:", self.txt_vc_email)
        l_vcard.addRow("Website:", self.txt_vc_url)
        self.stack_qr_inputs.addWidget(w_vcard)

        # 4. Email
        w_email = QWidget()
        l_email = QFormLayout(w_email)
        self.txt_em_addr = QLineEdit("info@example.com")
        self.txt_em_addr.textChanged.connect(self._schedule_update)
        self.txt_em_subj = QLineEdit("Engraving Inquiry")
        self.txt_em_subj.textChanged.connect(self._schedule_update)
        self.txt_em_body = QLineEdit("Hello, I am interested in custom engraving.")
        self.txt_em_body.textChanged.connect(self._schedule_update)
        l_email.addRow("To Email:", self.txt_em_addr)
        l_email.addRow("Subject:", self.txt_em_subj)
        l_email.addRow("Body:", self.txt_em_body)
        self.stack_qr_inputs.addWidget(w_email)

        # 5. SMS
        w_sms = QWidget()
        l_sms = QFormLayout(w_sms)
        self.txt_sms_phone = QLineEdit("+1-555-0199")
        self.txt_sms_phone.textChanged.connect(self._schedule_update)
        self.txt_sms_msg = QLineEdit("Hello from LaserForge!")
        self.txt_sms_msg.textChanged.connect(self._schedule_update)
        l_sms.addRow("Phone #:", self.txt_sms_phone)
        l_sms.addRow("Message:", self.txt_sms_msg)
        self.stack_qr_inputs.addWidget(w_sms)

        type_layout.addWidget(self.stack_qr_inputs)
        ctrl_layout.addWidget(type_grp)

        # Geometry & Options
        opt_grp = QGroupBox("Laser Dimensions & Error Tolerance")
        opt_layout = QGridLayout(opt_grp)

        opt_layout.addWidget(QLabel("Size (mm):"), 0, 0)
        self.spin_qr_size = QDoubleSpinBox()
        self.spin_qr_size.setRange(8.0, min(self.bed_width, self.bed_height))
        self.spin_qr_size.setValue(25.0)
        self.spin_qr_size.setSingleStep(1.0)
        self.spin_qr_size.setSuffix(" mm")
        self.spin_qr_size.valueChanged.connect(self._schedule_update)
        opt_layout.addWidget(self.spin_qr_size, 0, 1)

        opt_layout.addWidget(QLabel("Error Correction:"), 1, 0)
        self.combo_qr_ec = QComboBox()
        for label, val in BarcodeGenerator.QR_ERROR_LEVELS.items():
            self.combo_qr_ec.addItem(label, val)
        self.combo_qr_ec.setCurrentIndex(3)  # Default "H" (High)
        self.combo_qr_ec.currentIndexChanged.connect(self._schedule_update)
        opt_layout.addWidget(self.combo_qr_ec, 1, 1)

        opt_layout.addWidget(QLabel("Quiet Border:"), 2, 0)
        self.spin_qr_border = QSpinBox()
        self.spin_qr_border.setRange(0, 4)
        self.spin_qr_border.setValue(1)
        self.spin_qr_border.setSuffix(" modules")
        self.spin_qr_border.valueChanged.connect(self._schedule_update)
        opt_layout.addWidget(self.spin_qr_border, 2, 1)

        opt_layout.addWidget(QLabel("Format:"), 3, 0)
        self.combo_qr_output = QComboBox()
        self.combo_qr_output.addItem("⚡ Clean Vector Modules (PathEntity - Fill)", "vector")
        self.combo_qr_output.addItem("🖼️ High-Res Laser Bitmap (ImageEntity)", "raster")
        self.combo_qr_output.currentIndexChanged.connect(self._schedule_update)
        opt_layout.addWidget(self.combo_qr_output, 3, 1)

        ctrl_layout.addWidget(opt_grp)
        ctrl_layout.addStretch(1)

        scroll.setWidget(ctrl_container)
        layout.addWidget(scroll)

        # Right Panel: Preview
        prev_grp = QGroupBox("Interactive Visual Preview")
        prev_layout = QVBoxLayout(prev_grp)
        self.lbl_qr_preview = QLabel()
        self.lbl_qr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_qr_preview.setStyleSheet("background-color: #121216; border-radius: 4px;")
        prev_layout.addWidget(self.lbl_qr_preview, 1)

        self.lbl_qr_info = QLabel("")
        self.lbl_qr_info.setStyleSheet("color: #00e5ff; font-family: monospace; font-size: 11px;")
        self.lbl_qr_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_layout.addWidget(self.lbl_qr_info)

        layout.addWidget(prev_grp, 1)
        return widget

    # -------------------------------------------------------------------------
    # 1D Barcode Tab
    # -------------------------------------------------------------------------

    def _build_barcode_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Left Panel: Controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(450)
        scroll.setMinimumWidth(380)

        ctrl_container = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_container)
        ctrl_layout.setSpacing(8)

        # Barcode Data Group
        data_grp = QGroupBox("Barcode Format & Data")
        data_layout = QFormLayout(data_grp)

        self.combo_bc_type = QComboBox()
        for label, val in BarcodeGenerator.SUPPORTED_BARCODES:
            self.combo_bc_type.addItem(label, val)
        self.combo_bc_type.currentIndexChanged.connect(self._on_bc_type_changed)
        data_layout.addRow("Symbology:", self.combo_bc_type)

        self.txt_bc_data = QLineEdit("LF-2026-ENGRAVE")
        self.txt_bc_data.textChanged.connect(self._schedule_update)
        data_layout.addRow("Encoded Data:", self.txt_bc_data)

        self.lbl_bc_validation = QLabel("")
        self.lbl_bc_validation.setStyleSheet("color: #ffb74d; font-size: 11px; font-style: italic;")
        data_layout.addRow("", self.lbl_bc_validation)

        ctrl_layout.addWidget(data_grp)

        # Dimensions Group
        dim_grp = QGroupBox("Barcode Physical Dimensions")
        dim_layout = QGridLayout(dim_grp)

        dim_layout.addWidget(QLabel("Width (mm):"), 0, 0)
        self.spin_bc_width = QDoubleSpinBox()
        self.spin_bc_width.setRange(15.0, self.bed_width)
        self.spin_bc_width.setValue(50.0)
        self.spin_bc_width.setSingleStep(1.0)
        self.spin_bc_width.setSuffix(" mm")
        self.spin_bc_width.valueChanged.connect(self._schedule_update)
        dim_layout.addWidget(self.spin_bc_width, 0, 1)

        dim_layout.addWidget(QLabel("Height (mm):"), 1, 0)
        self.spin_bc_height = QDoubleSpinBox()
        self.spin_bc_height.setRange(5.0, self.bed_height)
        self.spin_bc_height.setValue(22.0)
        self.spin_bc_height.setSingleStep(1.0)
        self.spin_bc_height.setSuffix(" mm")
        self.spin_bc_height.valueChanged.connect(self._schedule_update)
        dim_layout.addWidget(self.spin_bc_height, 1, 1)

        self.chk_bc_text = QCheckBox("Show Human-Readable Text Below Bars")
        self.chk_bc_text.setChecked(True)
        self.chk_bc_text.stateChanged.connect(self._schedule_update)
        dim_layout.addWidget(self.chk_bc_text, 2, 0, 1, 2)

        dim_layout.addWidget(QLabel("Format:"), 3, 0)
        self.combo_bc_output = QComboBox()
        self.combo_bc_output.addItem("⚡ Precision Vector Bars (RectEntity - Fill/Cut)", "vector")
        self.combo_bc_output.addItem("🖼️ High-Res Laser Bitmap (ImageEntity)", "raster")
        self.combo_bc_output.currentIndexChanged.connect(self._schedule_update)
        dim_layout.addWidget(self.combo_bc_output, 3, 1)

        ctrl_layout.addWidget(dim_grp)
        ctrl_layout.addStretch(1)

        scroll.setWidget(ctrl_container)
        layout.addWidget(scroll)

        # Right Panel: Preview
        prev_grp = QGroupBox("Interactive Barcode Preview")
        prev_layout = QVBoxLayout(prev_grp)
        self.lbl_bc_preview = QLabel()
        self.lbl_bc_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_bc_preview.setStyleSheet("background-color: #121216; border-radius: 4px;")
        prev_layout.addWidget(self.lbl_bc_preview, 1)

        self.lbl_bc_info = QLabel("")
        self.lbl_bc_info.setStyleSheet("color: #00e5ff; font-family: monospace; font-size: 11px;")
        self.lbl_bc_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_layout.addWidget(self.lbl_bc_info)

        layout.addWidget(prev_grp, 1)
        return widget

    # -------------------------------------------------------------------------
    # Logic & Event Handlers
    # -------------------------------------------------------------------------

    def _on_qr_type_changed(self, idx: int):
        self.stack_qr_inputs.setCurrentIndex(idx)
        self._schedule_update()

    def _on_bc_type_changed(self, idx: int):
        code_type = self.combo_bc_type.currentData()
        if code_type in ("ean13", "ean"):
            self.txt_bc_data.setText("123456789012")
            self.lbl_bc_validation.setText("EAN-13 expects 12 or 13 numeric digits")
        elif code_type in ("upca", "upc"):
            self.txt_bc_data.setText("01234567890")
            self.lbl_bc_validation.setText("UPC-A expects 11 or 12 numeric digits")
        elif code_type == "code39":
            self.txt_bc_data.setText("LASER-FORGE")
            self.lbl_bc_validation.setText("Code 39 supports uppercase A-Z, 0-9, and -.$/+%")
        else:
            self.txt_bc_data.setText("LF-SERIAL-1001")
            self.lbl_bc_validation.setText("Code 128 supports all standard ASCII characters")
        self._schedule_update()

    def _get_qr_payload(self) -> str:
        idx = self.combo_qr_type.currentIndex()
        if idx == 0:
            return self.txt_url.text().strip() or "https://github.com"
        elif idx == 1:
            return self.txt_plain.toPlainText().strip() or "LaserForge"
        elif idx == 2:
            return BarcodeGenerator.build_wifi_string(
                self.txt_wifi_ssid.text().strip(),
                self.txt_wifi_pass.text(),
                self.combo_wifi_auth.currentText(),
                self.chk_wifi_hidden.isChecked()
            )
        elif idx == 3:
            return BarcodeGenerator.build_vcard_string(
                self.txt_vc_name.text().strip(),
                self.txt_vc_phone.text().strip(),
                self.txt_vc_email.text().strip(),
                self.txt_vc_org.text().strip(),
                self.txt_vc_title.text().strip(),
                self.txt_vc_url.text().strip()
            )
        elif idx == 4:
            return BarcodeGenerator.build_email_string(
                self.txt_em_addr.text().strip(),
                self.txt_em_subj.text().strip(),
                self.txt_em_body.text().strip()
            )
        elif idx == 5:
            return BarcodeGenerator.build_sms_string(
                self.txt_sms_phone.text().strip(),
                self.txt_sms_msg.text().strip()
            )
        return "LaserForge"

    def _schedule_update(self):
        self._debounce_timer.start()

    def _update_preview(self):
        tab_idx = self.main_tabs.currentIndex()
        if tab_idx == 0:
            self._update_qr_preview()
        else:
            self._update_barcode_preview()

    def _update_qr_preview(self):
        payload = self._get_qr_payload()
        ec = self.combo_qr_ec.currentData() or "H"
        border = self.spin_qr_border.value()
        size_mm = self.spin_qr_size.value()

        try:
            pil_img = BarcodeGenerator.generate_qr_bitmap(
                data=payload,
                size_px=380,
                error_correction=ec,
                border=border
            )
            self._current_qr_img = pil_img

            # Render onto white/black card for contrast
            rgba = pil_img.convert("RGBA")
            qimg = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(qimg)
            self.lbl_qr_preview.setPixmap(pix.scaled(
                min(380, self.lbl_qr_preview.width() or 300),
                min(380, self.lbl_qr_preview.height() or 300),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

            matrix = BarcodeGenerator.generate_qr_matrix(payload, ec, border)
            n = len(matrix)
            cell_mm = size_mm / float(n) if n > 0 else 0
            self.lbl_qr_info.setText(
                f"QR Grid: {n} × {n} modules  |  Size: {size_mm:.1f} × {size_mm:.1f} mm  |  "
                f"Module: {cell_mm:.2f} mm  |  EC: Level {ec}"
            )
        except Exception as e:
            self.lbl_qr_preview.setText(f"Preview error: {e}")
            self.lbl_qr_info.setText("")

    def _update_barcode_preview(self):
        btype = self.combo_bc_type.currentData() or "code128"
        data = self.txt_bc_data.text().strip() or "SAMPLE"
        show_text = self.chk_bc_text.isChecked()
        w_mm = self.spin_bc_width.value()
        h_mm = self.spin_bc_height.value()

        try:
            pil_img = BarcodeGenerator.generate_barcode_bitmap(
                code_type=btype,
                data=data,
                width_px=420,
                height_px=180,
                show_text=show_text
            )
            self._current_barcode_img = pil_img

            rgba = pil_img.convert("RGBA")
            qimg = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(qimg)
            self.lbl_bc_preview.setPixmap(pix.scaled(
                min(420, self.lbl_bc_preview.width() or 350),
                min(220, self.lbl_bc_preview.height() or 200),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

            self.lbl_bc_info.setText(f"Symbology: {btype.upper()}  |  Physical Size: {w_mm:.1f} × {h_mm:.1f} mm")
            self.lbl_bc_validation.setText("✓ Valid barcode data")
            self.lbl_bc_validation.setStyleSheet("color: #66bb6a; font-size: 11px;")
        except Exception as e:
            self.lbl_bc_preview.setText(f"Barcode preview error: {e}")
            self.lbl_bc_validation.setText(f"⚠ Invalid data for {btype}: {e}")
            self.lbl_bc_validation.setStyleSheet("color: #ff5252; font-size: 11px;")

    # -------------------------------------------------------------------------
    # Insertion into Canvas
    # -------------------------------------------------------------------------

    def _on_insert_clicked(self):
        target_layer_id = self.combo_layer.currentData() or 0
        tab_idx = self.main_tabs.currentIndex()

        entities: List[LaserEntity] = []

        if tab_idx == 0:
            # QR Code
            payload = self._get_qr_payload()
            size_mm = self.spin_qr_size.value()
            ec = self.combo_qr_ec.currentData() or "H"
            border = self.spin_qr_border.value()
            out_mode = self.combo_qr_output.currentData()

            cx = (self.bed_width - size_mm) / 2.0
            cy = (self.bed_height - size_mm) / 2.0

            if out_mode == "raster":
                cache_dir = os.path.expanduser("~/.laserforge/cache")
                os.makedirs(cache_dir, exist_ok=True)
                ts = int(time.time() * 1000)
                path = os.path.join(cache_dir, f"qr_{ts}.png")
                qr_img = BarcodeGenerator.generate_qr_bitmap(payload, size_px=800, error_correction=ec, border=border)
                qr_img.save(path)
                entities.append(ImageEntity(
                    layer_id=target_layer_id,
                    name=f"QR_{payload[:8]}",
                    image_path=path,
                    processed_image_path=path,
                    raw_image_path=path,
                    x=cx, y=cy,
                    width=size_mm, height=size_mm
                ))
            else:
                # Vector PathEntity
                ent = BarcodeGenerator.generate_qr_vector_entity(
                    data=payload,
                    size_mm=size_mm,
                    layer_id=target_layer_id,
                    error_correction=ec,
                    border=border,
                    offset_x=cx,
                    offset_y=cy
                )
                entities.append(ent)

        else:
            # 1D Barcode
            btype = self.combo_bc_type.currentData() or "code128"
            data = self.txt_bc_data.text().strip() or "SAMPLE"
            show_text = self.chk_bc_text.isChecked()
            w_mm = self.spin_bc_width.value()
            h_mm = self.spin_bc_height.value()
            out_mode = self.combo_bc_output.currentData()

            cx = (self.bed_width - w_mm) / 2.0
            cy = (self.bed_height - h_mm) / 2.0

            if out_mode == "raster":
                cache_dir = os.path.expanduser("~/.laserforge/cache")
                os.makedirs(cache_dir, exist_ok=True)
                ts = int(time.time() * 1000)
                path = os.path.join(cache_dir, f"barcode_{btype}_{ts}.png")
                bc_img = BarcodeGenerator.generate_barcode_bitmap(
                    code_type=btype, data=data, width_px=900, height_px=int(900 * (h_mm / w_mm)), show_text=show_text
                )
                bc_img.save(path)
                entities.append(ImageEntity(
                    layer_id=target_layer_id,
                    name=f"BC_{btype}_{data[:8]}",
                    image_path=path,
                    processed_image_path=path,
                    raw_image_path=path,
                    x=cx, y=cy,
                    width=w_mm, height=h_mm
                ))
            else:
                try:
                    bars, txt, _ = BarcodeGenerator.generate_barcode_bars(
                        code_type=btype,
                        data=data,
                        width_mm=w_mm,
                        height_mm=h_mm,
                        layer_id=target_layer_id,
                        offset_x=cx,
                        offset_y=cy,
                        show_text=show_text
                    )
                    entities.extend(bars)
                    if txt:
                        entities.append(txt)
                except Exception as e:
                    QMessageBox.critical(self, "Generation Error", f"Failed to generate vector barcode:\n{e}")
                    return

        if not entities:
            QMessageBox.warning(self, "No Entities", "Could not generate workpiece entities.")
            return

        self.entities_generated.emit(entities)
        self.accept()
