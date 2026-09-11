"""
LaserForge Project Templates & Calibration Studio Dialog.
Provides a comprehensive visual library of ready-to-cut and ready-to-engrave parametric templates:
coasters, drinkware wraps, keychains, tags, ornaments, rulers, and 3W diode calibration test grids.
"""

from typing import List, Optional, Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QWidget, QDoubleSpinBox,
    QLineEdit, QCheckBox, QGroupBox, QSplitter, QMessageBox
)

from laserforge.core.template_generator import TemplateGenerator
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)


class TemplatePreviewWidget(QWidget):
    """Visual 2D canvas preview for generated template entities."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entities: List[LaserEntity] = []
        self.setMinimumSize(320, 320)
        self.setStyleSheet("background-color: #1a1a24; border-radius: 6px;")

    def set_entities(self, entities: List[LaserEntity]):
        self.entities = entities
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw dark background
        painter.fillRect(self.rect(), QColor("#1a1a24"))

        if not self.entities:
            painter.setPen(QColor("#78909c"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a template to preview.")
            return

        # Calculate bounding box of all entities
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for ent in self.entities:
            b = ent.get_bounds()
            min_x = min(min_x, b[0])
            min_y = min(min_y, b[1])
            max_x = max(max_x, b[2])
            max_y = max(max_y, b[3])

        w_mm = max(1.0, max_x - min_x)
        h_mm = max(1.0, max_y - min_y)

        # Scale and fit into widget
        margin = 30.0
        avail_w = max(10.0, self.width() - 2 * margin)
        avail_h = max(10.0, self.height() - 2 * margin)
        scale = min(avail_w / w_mm, avail_h / h_mm)

        center_px_x = self.width() / 2.0
        center_px_y = self.height() / 2.0
        mid_mm_x = (min_x + max_x) / 2.0
        mid_mm_y = (min_y + max_y) / 2.0

        def to_screen(x_mm, y_mm):
            return (
                center_px_x + (x_mm - mid_mm_x) * scale,
                center_px_y + (y_mm - mid_mm_y) * scale
            )

        # Draw grid marks
        painter.setPen(QPen(QColor("#2d2d3d"), 1, Qt.PenStyle.DotLine))
        painter.drawRect(
            int(center_px_x - (w_mm / 2.0) * scale),
            int(center_px_y - (h_mm / 2.0) * scale),
            int(w_mm * scale),
            int(h_mm * scale)
        )

        for ent in self.entities:
            # Color by layer
            if ent.layer_id == 1:
                # Cut: Vivid Red
                pen = QPen(QColor("#ff1744"), 1.8)
            elif ent.layer_id == 2:
                # Guide/Tool: Cyan
                pen = QPen(QColor("#00e5ff"), 1.0, Qt.PenStyle.DashLine)
            else:
                # Engrave: Crisp White/Gold
                pen = QPen(QColor("#ffffff"), 1.4)

            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            if isinstance(ent, RectEntity):
                sx, sy = to_screen(ent.x, ent.y)
                sw = ent.width * scale
                sh = ent.height * scale
                sr = ent.corner_radius * scale
                painter.drawRoundedRect(QRectF(sx, sy, sw, sh), sr, sr)

            elif isinstance(ent, CircleEntity):
                sx, sy = to_screen(ent.x, ent.y)
                srx = ent.radius_x * scale
                sry = ent.radius_y * scale
                painter.drawEllipse(QRectF(sx - srx, sy - sry, srx * 2, sry * 2))

            elif isinstance(ent, LineEntity):
                sx1, sy1 = to_screen(ent.x, ent.y)
                sx2, sy2 = to_screen(ent.x2, ent.y2)
                painter.drawLine(int(sx1), int(sy1), int(sx2), int(sy2))

            elif isinstance(ent, PathEntity):
                for contour in ent.contours:
                    if len(contour) > 1:
                        for i in range(len(contour) - (0 if ent.closed else 1)):
                            p1 = contour[i]
                            p2 = contour[(i + 1) % len(contour)]
                            sx1, sy1 = to_screen(ent.x + p1[0], ent.y + p1[1])
                            sx2, sy2 = to_screen(ent.x + p2[0], ent.y + p2[1])
                            painter.drawLine(int(sx1), int(sy1), int(sx2), int(sy2))

            elif isinstance(ent, TextEntity):
                sx, sy = to_screen(ent.x, ent.y)
                font = QFont("Sans Serif", max(6, int(round(ent.font_size * scale * 0.7))))
                painter.setFont(font)
                painter.drawText(int(sx), int(sy + ent.font_size * scale), ent.text)


class TemplatesStudioDialog(QDialog):
    """Comprehensive templates studio dialog."""
    templates_generated = pyqtSignal(list, bool)  # (entities, replace_canvas)

    def __init__(self, parent=None, bed_width: float = 150.0, bed_height: float = 200.0):
        super().__init__(parent)
        self.setWindowTitle("LaserForge Templates & Calibration Studio")
        self.resize(960, 620)
        self.bed_width = bed_width
        self.bed_height = bed_height
        self.current_entities: List[LaserEntity] = []

        self._init_ui()
        self.list_templates.setCurrentRow(0)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 1. Left List: Templates
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl_lib = QLabel("Template Library")
        lbl_lib.setStyleSheet("font-weight: bold; font-size: 13px; color: #80d8ff;")
        left_layout.addWidget(lbl_lib)

        self.list_templates = QListWidget()
        self.list_templates.setStyleSheet("font-size: 12px; padding: 4px;")

        items = [
            ("🍸 Round Coaster (100mm)", "round_coaster"),
            ("🍸 Square Rounded Coaster (95mm)", "square_coaster"),
            ("🏷 Rounded Rect Keychain", "rect_keychain"),
            ("🏷 Teardrop / Tag Keychain", "teardrop_keychain"),
            ("🥤 20oz Skinny Tumbler Wrap", "tumbler_20oz"),
            ("🥤 30oz Tumbler Wrap", "tumbler_30oz"),
            ("🎄 Christmas Bauble Ornament", "ornament_bauble"),
            ("⚡ Diode Speed vs Power Matrix", "test_matrix"),
            ("📏 100mm Calibration Ruler", "cal_ruler"),
        ]
        for title, key in items:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_templates.addItem(item)

        self.list_templates.currentRowChanged.connect(self._on_template_selected)
        left_layout.addWidget(self.list_templates)
        splitter.addWidget(left_widget)

        # 2. Middle Panel: Parametric Inputs Stack
        self.stack = QStackedWidget()

        # Page 0: Round Coaster
        self.page_round_coaster = self._build_round_coaster_page()
        self.stack.addWidget(self.page_round_coaster)

        # Page 1: Square Coaster
        self.page_square_coaster = self._build_square_coaster_page()
        self.stack.addWidget(self.page_square_coaster)

        # Page 2: Rect Keychain
        self.page_rect_keychain = self._build_keychain_page("Rounded Rectangle")
        self.stack.addWidget(self.page_rect_keychain)

        # Page 3: Teardrop Keychain
        self.page_teardrop_keychain = self._build_keychain_page("Teardrop")
        self.stack.addWidget(self.page_teardrop_keychain)

        # Page 4: 20oz Tumbler
        self.page_tumbler_20oz = self._build_tumbler_page("20oz Skinny Tumbler")
        self.stack.addWidget(self.page_tumbler_20oz)

        # Page 5: 30oz Tumbler
        self.page_tumbler_30oz = self._build_tumbler_page("30oz Tumbler")
        self.stack.addWidget(self.page_tumbler_30oz)

        # Page 6: Bauble Ornament
        self.page_bauble = self._build_bauble_page()
        self.stack.addWidget(self.page_bauble)

        # Page 7: Test Matrix
        self.page_matrix = self._build_matrix_page()
        self.stack.addWidget(self.page_matrix)

        # Page 8: Ruler
        self.page_ruler = self._build_ruler_page()
        self.stack.addWidget(self.page_ruler)

        splitter.addWidget(self.stack)

        # 3. Right Panel: 2D Live Preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        lbl_prev = QLabel("Visual Schematic Preview")
        lbl_prev.setStyleSheet("font-weight: bold; font-size: 13px; color: #69f0ae;")
        right_layout.addWidget(lbl_prev)

        self.preview_widget = TemplatePreviewWidget()
        right_layout.addWidget(self.preview_widget, 1)

        lbl_legend = QLabel("Legend:  🔴 Red = Cut Perimeter   ⚪ White = Engrave   🔵 Cyan = Guide")
        lbl_legend.setStyleSheet("color: #b0bec5; font-size: 10px;")
        right_layout.addWidget(lbl_legend)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        main_layout.addWidget(splitter, 1)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        self.chk_replace_canvas = QCheckBox("Replace existing canvas contents")
        bottom_bar.addWidget(self.chk_replace_canvas)

        bottom_bar.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_cancel)

        btn_generate = QPushButton("✨ Add Template to Canvas")
        btn_generate.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 18px;")
        btn_generate.clicked.connect(self._on_apply)
        bottom_bar.addWidget(btn_generate)

        main_layout.addLayout(bottom_bar)

    # --- Parametric Page Builders ---

    def _build_round_coaster_page(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.addWidget(QLabel("Diameter (mm):"), 0, 0)
        self.rc_dia = QDoubleSpinBox()
        self.rc_dia.setRange(50.0, 200.0)
        self.rc_dia.setValue(100.0)
        self.rc_dia.setSuffix(" mm")
        self.rc_dia.valueChanged.connect(self._update_preview)
        grid.addWidget(self.rc_dia, 0, 1)

        grid.addWidget(QLabel("Inner Ring Margin:"), 1, 0)
        self.rc_margin = QDoubleSpinBox()
        self.rc_margin.setRange(0.0, 30.0)
        self.rc_margin.setValue(6.0)
        self.rc_margin.setSuffix(" mm")
        self.rc_margin.valueChanged.connect(self._update_preview)
        grid.addWidget(self.rc_margin, 1, 1)

        grid.addWidget(QLabel("Center Text / Monogram:"), 2, 0)
        self.rc_text = QLineEdit("LASER")
        self.rc_text.textChanged.connect(self._update_preview)
        grid.addWidget(self.rc_text, 2, 1)

        grid.setRowStretch(3, 1)
        return w

    def _build_square_coaster_page(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.addWidget(QLabel("Size (mm):"), 0, 0)
        self.sc_size = QDoubleSpinBox()
        self.sc_size.setRange(50.0, 200.0)
        self.sc_size.setValue(95.0)
        self.sc_size.setSuffix(" mm")
        self.sc_size.valueChanged.connect(self._update_preview)
        grid.addWidget(self.sc_size, 0, 1)

        grid.addWidget(QLabel("Corner Radius:"), 1, 0)
        self.sc_radius = QDoubleSpinBox()
        self.sc_radius.setRange(0.0, 30.0)
        self.sc_radius.setValue(8.0)
        self.sc_radius.setSuffix(" mm")
        self.sc_radius.valueChanged.connect(self._update_preview)
        grid.addWidget(self.sc_radius, 1, 1)

        grid.addWidget(QLabel("Center Text:"), 2, 0)
        self.sc_text = QLineEdit("FORGE")
        self.sc_text.textChanged.connect(self._update_preview)
        grid.addWidget(self.sc_text, 2, 1)

        grid.setRowStretch(3, 1)
        return w

    def _build_keychain_page(self, style: str) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.addWidget(QLabel("Width (mm):"), 0, 0)
        spin_w = QDoubleSpinBox()
        spin_w.setRange(30.0, 120.0)
        spin_w.setValue(60.0)
        spin_w.setSuffix(" mm")
        spin_w.valueChanged.connect(self._update_preview)
        grid.addWidget(spin_w, 0, 1)

        grid.addWidget(QLabel("Height (mm):"), 1, 0)
        spin_h = QDoubleSpinBox()
        spin_h.setRange(15.0, 80.0)
        spin_h.setValue(30.0)
        spin_h.setSuffix(" mm")
        spin_h.valueChanged.connect(self._update_preview)
        grid.addWidget(spin_h, 1, 1)

        grid.addWidget(QLabel("Custom Name / Text:"), 2, 0)
        txt = QLineEdit("MAKER")
        txt.textChanged.connect(self._update_preview)
        grid.addWidget(txt, 2, 1)

        grid.setRowStretch(3, 1)
        w.spin_w = spin_w
        w.spin_h = spin_h
        w.txt = txt
        w.style = style
        return w

    def _build_tumbler_page(self, tumbler_type: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        lbl = QLabel(f"Calculated circumference and flat wrap layout for {tumbler_type}.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #b0bec5;")
        layout.addWidget(lbl)
        w.tumbler_type = tumbler_type
        layout.addStretch(1)
        return w

    def _build_bauble_page(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.addWidget(QLabel("Diameter (mm):"), 0, 0)
        self.bb_dia = QDoubleSpinBox()
        self.bb_dia.setRange(40.0, 140.0)
        self.bb_dia.setValue(75.0)
        self.bb_dia.setSuffix(" mm")
        self.bb_dia.valueChanged.connect(self._update_preview)
        grid.addWidget(self.bb_dia, 0, 1)

        grid.addWidget(QLabel("Engraved Text:"), 1, 0)
        self.bb_text = QLineEdit("2026")
        self.bb_text.textChanged.connect(self._update_preview)
        grid.addWidget(self.bb_text, 1, 1)

        grid.setRowStretch(2, 1)
        return w

    def _build_matrix_page(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.addWidget(QLabel("Speed Range (mm/min):"), 0, 0)
        h_spd = QHBoxLayout()
        self.mat_s_min = QDoubleSpinBox()
        self.mat_s_min.setRange(100, 3000)
        self.mat_s_min.setValue(200)
        self.mat_s_min.valueChanged.connect(self._update_preview)
        h_spd.addWidget(self.mat_s_min)
        h_spd.addWidget(QLabel("to"))
        self.mat_s_max = QDoubleSpinBox()
        self.mat_s_max.setRange(100, 3000)
        self.mat_s_max.setValue(1200)
        self.mat_s_max.valueChanged.connect(self._update_preview)
        h_spd.addWidget(self.mat_s_max)
        grid.addLayout(h_spd, 0, 1)

        grid.addWidget(QLabel("Power Range (%):"), 1, 0)
        h_pwr = QHBoxLayout()
        self.mat_p_min = QDoubleSpinBox()
        self.mat_p_min.setRange(10, 100)
        self.mat_p_min.setValue(20)
        self.mat_p_min.valueChanged.connect(self._update_preview)
        h_pwr.addWidget(self.mat_p_min)
        h_pwr.addWidget(QLabel("to"))
        self.mat_p_max = QDoubleSpinBox()
        self.mat_p_max.setRange(10, 100)
        self.mat_p_max.setValue(100)
        self.mat_p_max.valueChanged.connect(self._update_preview)
        h_pwr.addWidget(self.mat_p_max)
        grid.addLayout(h_pwr, 1, 1)

        grid.setRowStretch(2, 1)
        return w

    def _build_ruler_page(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.addWidget(QLabel("Ruler Length (mm):"), 0, 0)
        self.rul_len = QDoubleSpinBox()
        self.rul_len.setRange(50.0, 150.0)
        self.rul_len.setValue(100.0)
        self.rul_len.setSuffix(" mm")
        self.rul_len.valueChanged.connect(self._update_preview)
        grid.addWidget(self.rul_len, 0, 1)

        grid.setRowStretch(1, 1)
        return w

    def _on_template_selected(self, row: int):
        self.stack.setCurrentIndex(row)
        self._update_preview()

    def _update_preview(self):
        row = self.list_templates.currentRow()
        ents = []
        if row == 0:
            ents = TemplateGenerator.generate_round_coaster(
                diameter=self.rc_dia.value(),
                inner_border_offset=self.rc_margin.value(),
                custom_text=self.rc_text.text()
            )
        elif row == 1:
            ents = TemplateGenerator.generate_square_coaster(
                size=self.sc_size.value(),
                corner_radius=self.sc_radius.value(),
                custom_text=self.sc_text.text()
            )
        elif row == 2:
            p = self.page_rect_keychain
            ents = TemplateGenerator.generate_keychain(
                style="Rounded Rectangle",
                width=p.spin_w.value(), height=p.spin_h.value(),
                custom_text=p.txt.text()
            )
        elif row == 3:
            p = self.page_teardrop_keychain
            ents = TemplateGenerator.generate_keychain(
                style="Teardrop",
                width=p.spin_w.value(), height=p.spin_h.value(),
                custom_text=p.txt.text()
            )
        elif row == 4:
            ents = TemplateGenerator.generate_tumbler_wrap(tumbler_type="20oz Skinny Tumbler")
        elif row == 5:
            ents = TemplateGenerator.generate_tumbler_wrap(tumbler_type="30oz Tumbler")
        elif row == 6:
            ents = TemplateGenerator.generate_holiday_ornament(
                diameter=self.bb_dia.value(),
                custom_text=self.bb_text.text()
            )
        elif row == 7:
            ents = TemplateGenerator.generate_speed_power_test_matrix(
                cols=5, rows=5,
                speed_min=self.mat_s_min.value(), speed_max=self.mat_s_max.value(),
                power_min=self.mat_p_min.value(), power_max=self.mat_p_max.value()
            )
        elif row == 8:
            ents = TemplateGenerator.generate_calibration_ruler(length_mm=self.rul_len.value())

        self.current_entities = ents
        self.preview_widget.set_entities(ents)

    def _on_apply(self):
        if not self.current_entities:
            self._update_preview()
        if not self.current_entities:
            QMessageBox.warning(self, "No Template", "Could not generate template entities.")
            return

        replace = self.chk_replace_canvas.isChecked()
        self.templates_generated.emit(self.current_entities, replace)
        self.accept()
