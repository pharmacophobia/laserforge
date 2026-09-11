"""
LaserForge Business Card Studio Dialog.
Interactive design suite for laser-engraved business cards (anodized metal blanks, wood, cardstock),
vector QR code synthesis, automated typography layout, wasteboard cutting jigs, and batch arrays.
"""

from typing import List, Tuple, Optional
import os

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QGroupBox, QTabWidget, QSplitter, QFrame, QMessageBox,
    QFileDialog
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPaintEvent
)

from laserforge.core.models import LaserEntity, RectEntity, LineEntity, TextEntity, PathEntity
from laserforge.core.business_card_generator import (
    CARD_PRESETS, BusinessCardConfig, BusinessCardGenerator
)


class CardPreviewCanvas(QWidget):
    """Real-time 2D interactive preview canvas of the designed business card."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = BusinessCardConfig()
        self.setMinimumSize(420, 280)
        self.setStyleSheet("background-color: #1a1a24; border-radius: 6px;")

    def update_config(self, cfg: BusinessCardConfig):
        self.config = cfg
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#14141e"))

        w_mm = self.config.width
        h_mm = self.config.height

        # Fit card in preview with margin
        margin_px = 30.0
        avail_w = max(50.0, self.width() - margin_px * 2.0)
        avail_h = max(50.0, self.height() - margin_px * 2.0)

        scale = min(avail_w / max(1.0, w_mm), avail_h / max(1.0, h_mm))
        draw_w = w_mm * scale
        draw_h = h_mm * scale

        ox = (self.width() - draw_w) / 2.0
        oy = (self.height() - draw_h) / 2.0

        painter.save()
        painter.translate(ox, oy)
        painter.scale(scale, scale)

        # 1. Card Blank (Dark anodized brushed metal appearance)
        card_rect = QRectF(0, 0, w_mm, h_mm)
        r = self.config.corner_radius
        painter.setBrush(QBrush(QColor("#242630")))
        painter.setPen(QPen(QColor("#3d4254"), 0.8))
        painter.drawRoundedRect(card_rect, r, r)

        # Subtle card inner bevel highlight
        painter.setPen(QPen(QColor("#2e3242"), 0.4))
        painter.drawRoundedRect(QRectF(0.6, 0.6, w_mm - 1.2, h_mm - 1.2), max(0.0, r - 0.5), max(0.0, r - 0.5))

        # 2. Render Card Entities
        card_items = BusinessCardGenerator.generate_single_card(self.config, 0.0, 0.0)

        for ent in card_items:
            if isinstance(ent, RectEntity) and ent.name in ("Card_Guide_Border", "Card_Cut_Border"):
                # Border outline
                stroke_color = QColor("#ff4081") if ent.layer_id == 12 else QColor("#ff2a2a")
                pen = QPen(stroke_color, 0.5, Qt.PenStyle.DashLine if ent.layer_id == 12 else Qt.PenStyle.SolidLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(ent.x, ent.y, ent.width, ent.height), ent.corner_radius, ent.corner_radius)

            elif isinstance(ent, LineEntity):
                pen = QPen(QColor("#00e5ff"), 0.5)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawLine(QPointF(ent.x, ent.y), QPointF(ent.x2, ent.y2))

            elif isinstance(ent, TextEntity):
                painter.setPen(QColor("#f0f4f8"))
                font = QFont("sans-serif")
                font.setPointSizeF(max(1.8, ent.font_size * 0.72))
                font.setBold(ent.bold)
                painter.setFont(font)
                painter.drawText(
                    QRectF(ent.x, ent.y, ent.width, ent.height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    ent.text
                )

            elif isinstance(ent, PathEntity):
                # QR Code
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#00e5ff")))
                for poly in ent.contours:
                    if len(poly) >= 3:
                        poly_q = [QPointF(p[0], p[1]) for p in poly]
                        painter.drawPolygon(poly_q)

        painter.restore()


class BusinessCardStudioDialog(QDialog):
    """Full-featured Business Card Designer, QR synthesizer, and Batch Jig Studio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Business Card Studio & Fixture Generator")
        self.resize(1020, 680)

        self.generated_entities: List[LaserEntity] = []

        self._init_ui()
        self._load_preset("Metal Card Blank (85.6 × 54.0 mm, R3mm)")

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # -------------------------------------------------------------
        # LEFT PANE: Real-time Visual Card Preview & Quick Stats
        # -------------------------------------------------------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        left_layout.addWidget(QLabel("<b>Real-Time Card Preview:</b>"))
        self.preview_canvas = CardPreviewCanvas(self)
        left_layout.addWidget(self.preview_canvas, 1)

        # 3W Laser Tip Banner
        tip_box = QGroupBox("3W Diode Laser Card Production Tip")
        tip_layout = QVBoxLayout(tip_box)
        tip_txt = QLabel(
            "• <b>Anodized Aluminum Blanks</b>: 3W diodes ablate the colored coating instantly "
            "at <b>1200 mm/min, 100% Power</b> in Fill mode (0.08mm interval) revealing brilliant white metal.<br>"
            "• <b>Laser-Cut Jig</b>: Cut a multi-pocket card jig from 2-3mm scrap wood or cardboard once, "
            "tape it to your laser bed, and drop blanks into the pockets for 100% perfect repeat alignment!"
        )
        tip_txt.setWordWrap(True)
        tip_txt.setStyleSheet("color: #b0bec5; font-size: 11px;")
        tip_layout.addWidget(tip_txt)
        left_layout.addWidget(tip_box)

        splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # RIGHT PANE: Tabs for Single Card Designer vs Batch Jig
        # -------------------------------------------------------------
        right_widget = QWidget()
        right_widget.setFixedWidth(460)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(6)

        self.tab_widget = QTabWidget()

        # TAB 1: Card Design & Layout
        tab_design = QWidget()
        design_layout = QVBoxLayout(tab_design)
        design_layout.setSpacing(8)

        # Preset Selector
        preset_group = QGroupBox("Card Specification")
        preset_grid = QGridLayout(preset_group)
        preset_grid.setSpacing(6)

        preset_grid.addWidget(QLabel("Card Blank:"), 0, 0)
        self.combo_presets = QComboBox()
        for p_name in CARD_PRESETS.keys():
            self.combo_presets.addItem(p_name)
        self.combo_presets.addItem("Custom Dimensions")
        self.combo_presets.currentTextChanged.connect(self._on_preset_changed)
        preset_grid.addWidget(self.combo_presets, 0, 1, 1, 3)

        preset_grid.addWidget(QLabel("Width (mm):"), 1, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(20.0, 200.0)
        self.spin_width.setValue(85.6)
        self.spin_width.valueChanged.connect(self._update_preview)
        preset_grid.addWidget(self.spin_width, 1, 1)

        preset_grid.addWidget(QLabel("Height (mm):"), 1, 2)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(20.0, 200.0)
        self.spin_height.setValue(54.0)
        self.spin_height.valueChanged.connect(self._update_preview)
        preset_grid.addWidget(self.spin_height, 1, 3)

        preset_grid.addWidget(QLabel("Corner Radius:"), 2, 0)
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.0, 20.0)
        self.spin_radius.setValue(3.0)
        self.spin_radius.setSuffix(" mm")
        self.spin_radius.valueChanged.connect(self._update_preview)
        preset_grid.addWidget(self.spin_radius, 2, 1)

        preset_grid.addWidget(QLabel("Border:"), 2, 2)
        self.combo_border = QComboBox()
        self.combo_border.addItem("Tool Guide (T1 Pink)", "guide")
        self.combo_border.addItem("Cut Line (C02 Red)", "cut")
        self.combo_border.addItem("None (No Outline)", "none")
        self.combo_border.currentIndexChanged.connect(self._update_preview)
        preset_grid.addWidget(self.combo_border, 2, 3)

        design_layout.addWidget(preset_group)

        # Card Content Info
        info_group = QGroupBox("Card Content && Typography")
        info_grid = QGridLayout(info_group)
        info_grid.setSpacing(4)

        info_grid.addWidget(QLabel("Company / Brand:"), 0, 0)
        self.txt_company = QLineEdit("FORGE DYNAMICS")
        self.txt_company.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_company, 0, 1)

        info_grid.addWidget(QLabel("Tagline:"), 1, 0)
        self.txt_tagline = QLineEdit("Precision Laser Engineering")
        self.txt_tagline.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_tagline, 1, 1)

        info_grid.addWidget(QLabel("Cardholder Name:"), 2, 0)
        self.txt_name = QLineEdit("Alex Mercer")
        self.txt_name.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_name, 2, 1)

        info_grid.addWidget(QLabel("Job Title:"), 3, 0)
        self.txt_title = QLineEdit("Lead Laser Specialist")
        self.txt_title.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_title, 3, 1)

        info_grid.addWidget(QLabel("Phone:"), 4, 0)
        self.txt_phone = QLineEdit("+1 (555) 382-9104")
        self.txt_phone.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_phone, 4, 1)

        info_grid.addWidget(QLabel("Email:"), 5, 0)
        self.txt_email = QLineEdit("alex@forgedynamics.com")
        self.txt_email.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_email, 5, 1)

        info_grid.addWidget(QLabel("Website:"), 6, 0)
        self.txt_web = QLineEdit("https://forgedynamics.com")
        self.txt_web.textChanged.connect(self._update_preview)
        info_grid.addWidget(self.txt_web, 6, 1)

        design_layout.addWidget(info_group)

        # QR Code Group
        qr_group = QGroupBox("Vector QR Code")
        qr_grid = QGridLayout(qr_group)
        qr_grid.setSpacing(4)

        self.chk_qr = QCheckBox("Embed Vector QR Code on Card")
        self.chk_qr.setChecked(True)
        self.chk_qr.toggled.connect(self._update_preview)
        qr_grid.addWidget(self.chk_qr, 0, 0, 1, 2)

        qr_grid.addWidget(QLabel("QR Data / URL:"), 1, 0)
        self.txt_qr_data = QLineEdit("https://forgedynamics.com")
        self.txt_qr_data.textChanged.connect(self._update_preview)
        qr_grid.addWidget(self.txt_qr_data, 1, 1)

        qr_row = QHBoxLayout()
        qr_row.addWidget(QLabel("Size:"))
        self.spin_qr_size = QDoubleSpinBox()
        self.spin_qr_size.setRange(12.0, 45.0)
        self.spin_qr_size.setValue(24.0)
        self.spin_qr_size.setSuffix(" mm")
        self.spin_qr_size.valueChanged.connect(self._update_preview)
        qr_row.addWidget(self.spin_qr_size)

        qr_row.addWidget(QLabel("Pos:"))
        self.combo_qr_pos = QComboBox()
        self.combo_qr_pos.addItems(["Right", "Left", "Bottom-Right"])
        self.combo_qr_pos.currentIndexChanged.connect(self._update_preview)
        qr_row.addWidget(self.combo_qr_pos)
        qr_grid.addLayout(qr_row, 2, 0, 1, 2)

        design_layout.addWidget(qr_group)
        design_layout.addStretch(1)
        self.tab_widget.addTab(tab_design, "1. Card Design")

        # TAB 2: Batch Production & Wasteboard Jig Fixture
        tab_jig = QWidget()
        jig_layout = QVBoxLayout(tab_jig)
        jig_layout.setSpacing(8)

        mode_box = QGroupBox("Production Mode")
        mode_vbox = QVBoxLayout(mode_box)
        self.combo_prod_mode = QComboBox()
        self.combo_prod_mode.addItem("Single Card Centered on Bed")
        self.combo_prod_mode.addItem("Batch Array of Cards (N × M Grid)")
        self.combo_prod_mode.addItem("Laser-Cut Wasteboard Card Jig / Fixture")
        self.combo_prod_mode.addItem("Both: Jig Fixture + Batch Cards")
        mode_vbox.addWidget(self.combo_prod_mode)
        jig_layout.addWidget(mode_box)

        grid_group = QGroupBox("Fixture & Array Dimensions")
        grid_layout = QGridLayout(grid_group)
        grid_layout.setSpacing(6)

        grid_layout.addWidget(QLabel("Columns:"), 0, 0)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 10)
        self.spin_cols.setValue(3)
        grid_layout.addWidget(self.spin_cols, 0, 1)

        grid_layout.addWidget(QLabel("Rows:"), 0, 2)
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 10)
        self.spin_rows.setValue(2)
        grid_layout.addWidget(self.spin_rows, 0, 3)

        grid_layout.addWidget(QLabel("Spacing X:"), 1, 0)
        self.spin_space_x = QDoubleSpinBox()
        self.spin_space_x.setRange(1.0, 50.0)
        self.spin_space_x.setValue(6.0)
        self.spin_space_x.setSuffix(" mm")
        grid_layout.addWidget(self.spin_space_x, 1, 1)

        grid_layout.addWidget(QLabel("Spacing Y:"), 1, 2)
        self.spin_space_y = QDoubleSpinBox()
        self.spin_space_y.setRange(1.0, 50.0)
        self.spin_space_y.setValue(6.0)
        self.spin_space_y.setSuffix(" mm")
        grid_layout.addWidget(self.spin_space_y, 1, 3)

        self.chk_finger_notches = QCheckBox("Add Ergonomic Thumb/Finger Release Cutouts")
        self.chk_finger_notches.setChecked(True)
        self.chk_finger_notches.setToolTip("Adds semi-circle finger cutouts to pop metal cards in & out without scratching")
        grid_layout.addWidget(self.chk_finger_notches, 2, 0, 1, 4)

        jig_layout.addWidget(grid_group)

        self.lbl_jig_summary = QLabel()
        self.lbl_jig_summary.setStyleSheet("color: #00e5ff; font-family: monospace; font-size: 11px;")
        self.spin_cols.valueChanged.connect(self._update_jig_summary)
        self.spin_rows.valueChanged.connect(self._update_jig_summary)
        self.spin_space_x.valueChanged.connect(self._update_jig_summary)
        self.spin_space_y.valueChanged.connect(self._update_jig_summary)
        self._update_jig_summary()
        jig_layout.addWidget(self.lbl_jig_summary)

        jig_layout.addStretch(1)
        self.tab_widget.addTab(tab_jig, "2. Batch && Wasteboard Jig")

        right_layout.addWidget(self.tab_widget)

        # Action Buttons
        btn_apply = QPushButton("✔  Insert onto Canvas")
        btn_apply.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 10px; font-size: 13px; border-radius: 4px;"
        )
        btn_apply.clicked.connect(self._apply_and_close)
        right_layout.addWidget(btn_apply)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        right_layout.addWidget(btn_cancel)

        splitter.addWidget(right_widget)
        main_layout.addWidget(splitter)

    def _on_preset_changed(self, name: str):
        p = CARD_PRESETS.get(name)
        if not p:
            return
        self.spin_width.setValue(p["width"])
        self.spin_height.setValue(p["height"])
        self.spin_radius.setValue(p["corner_radius"])
        self._update_preview()

    def _load_preset(self, name: str):
        self.combo_presets.setCurrentText(name)
        self._on_preset_changed(name)

    def _get_current_config(self) -> BusinessCardConfig:
        return BusinessCardConfig(
            width=self.spin_width.value(),
            height=self.spin_height.value(),
            corner_radius=self.spin_radius.value(),
            border_mode=self.combo_border.currentData() or "guide",
            company_name=self.txt_company.text().strip(),
            tagline=self.txt_tagline.text().strip(),
            person_name=self.txt_name.text().strip(),
            title=self.txt_title.text().strip(),
            phone=self.txt_phone.text().strip(),
            email=self.txt_email.text().strip(),
            website=self.txt_web.text().strip(),
            include_qr=self.chk_qr.isChecked(),
            qr_data=self.txt_qr_data.text().strip(),
            qr_size=self.spin_qr_size.value(),
            qr_position=self.combo_qr_pos.currentText()
        )

    def _update_preview(self):
        cfg = self._get_current_config()
        self.preview_canvas.update_config(cfg)
        self._update_jig_summary()

    def _update_jig_summary(self):
        cols = self.spin_cols.value()
        rows = self.spin_rows.value()
        card_w = self.spin_width.value()
        card_h = self.spin_height.value()
        sx = self.spin_space_x.value()
        sy = self.spin_space_y.value()

        tot_w = cols * card_w + (cols - 1) * sx
        tot_h = rows * card_h + (rows - 1) * sy
        self.lbl_jig_summary.setText(
            f"Batch: {cols * rows} Cards ({cols} cols × {rows} rows)\n"
            f"Fixture Footprint: {tot_w:.1f} × {tot_h:.1f} mm (+24mm rim)"
        )

    def _apply_and_close(self):
        cfg = self._get_current_config()
        mode_idx = self.combo_prod_mode.currentIndex()

        entities: List[LaserEntity] = []

        if mode_idx == 0:
            # Single card
            entities = BusinessCardGenerator.generate_single_card(cfg, origin_x=50.0, origin_y=50.0)
        elif mode_idx == 1:
            # Batch array only
            entities = BusinessCardGenerator.generate_batch_array(
                cfg,
                cols=self.spin_cols.value(),
                rows=self.spin_rows.value(),
                spacing_x=self.spin_space_x.value(),
                spacing_y=self.spin_space_y.value(),
                start_x=30.0,
                start_y=30.0
            )
        elif mode_idx == 2:
            # Laser-cut wasteboard fixture jig only
            entities = BusinessCardGenerator.generate_card_jig_fixture(
                cols=self.spin_cols.value(),
                rows=self.spin_rows.value(),
                card_w=cfg.width,
                card_h=cfg.height,
                corner_radius=cfg.corner_radius,
                spacing_x=self.spin_space_x.value(),
                spacing_y=self.spin_space_y.value(),
                finger_notches=self.chk_finger_notches.isChecked(),
                start_x=30.0,
                start_y=30.0
            )
        else:
            # Both jig and cards
            jig_items = BusinessCardGenerator.generate_card_jig_fixture(
                cols=self.spin_cols.value(),
                rows=self.spin_rows.value(),
                card_w=cfg.width,
                card_h=cfg.height,
                corner_radius=cfg.corner_radius,
                spacing_x=self.spin_space_x.value(),
                spacing_y=self.spin_space_y.value(),
                finger_notches=self.chk_finger_notches.isChecked(),
                start_x=30.0,
                start_y=30.0
            )
            card_items = BusinessCardGenerator.generate_batch_array(
                cfg,
                cols=self.spin_cols.value(),
                rows=self.spin_rows.value(),
                spacing_x=self.spin_space_x.value(),
                spacing_y=self.spin_space_y.value(),
                start_x=30.0,
                start_y=30.0
            )
            entities = jig_items + card_items

        self.generated_entities = entities
        self.accept()
