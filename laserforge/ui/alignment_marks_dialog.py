"""
LaserForge Alignment & Registration Marks Studio Dialog.
Generates 90-degree corner L-marks (corner stops/jigs) and center '+' registration crosshairs
around selected shapes or custom square/rectangular perimeters.
"""

from typing import List, Tuple, Optional, Any
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QComboBox, QRadioButton,
    QButtonGroup, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QFont

from laserforge.core.models import LaserEntity
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.serial_controller import SerialController
from laserforge.config import MachineSettings


class AlignmentMarksPreview(QFrame):
    """Live CAD visualizer showing the workpiece bounds, corner L-ticks, and center crosshair."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #1a1a24; border: 1px solid #333348; border-radius: 4px;")
        self.setMinimumSize(320, 240)

        self.bbox: Tuple[float, float, float, float] = (0.0, 0.0, 100.0, 100.0)
        self.mode: str = "both"  # "corners", "center", "both"
        self.corner_l_len: float = 8.0
        self.center_cross_len: float = 10.0
        self.margin: float = 0.0

    def set_state(
        self,
        bbox: Tuple[float, float, float, float],
        mode: str,
        corner_l_len: float,
        center_cross_len: float,
        margin: float
    ):
        self.bbox = bbox
        self.mode = mode
        self.corner_l_len = corner_l_len
        self.center_cross_len = center_cross_len
        self.margin = margin
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rx1, ry1, rx2, ry2 = self.bbox
        rw = max(1.0, rx2 - rx1)
        rh = max(1.0, ry2 - ry1)

        px1 = rx1 - self.margin
        py1 = ry1 - self.margin
        px2 = rx2 + self.margin
        py2 = ry2 + self.margin
        pw = max(1.0, px2 - px1)
        ph = max(1.0, py2 - py1)

        # Compute preview scaling
        margin_px = 35.0
        avail_w = max(20.0, self.width() - margin_px * 2.0)
        avail_h = max(20.0, self.height() - margin_px * 2.0)
        scale = min(avail_w / pw, avail_h / ph)

        draw_w = pw * scale
        draw_h = ph * scale
        ox = (self.width() - draw_w) / 2.0
        oy = (self.height() + draw_h) / 2.0

        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(ox + (x - px1) * scale, oy - (y - py1) * scale)

        # 1. Draw workpiece design bounding box (subtle dashed cyan)
        sp_bl = to_screen(rx1, ry1)
        sp_tr = to_screen(rx2, ry2)
        src_rect = QRectF(sp_bl, sp_tr).normalized()
        painter.setPen(QPen(QColor("#00bcd4"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor(0, 188, 212, 12)))
        painter.drawRect(src_rect)

        # 2. Draw outer alignment perimeter guide (dashed gray) if margin != 0
        if abs(self.margin) > 0.01:
            p_bl = to_screen(px1, py1)
            p_tr = to_screen(px2, py2)
            painter.setPen(QPen(QColor("#607d8b"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(p_bl, p_tr).normalized())

        # 3. Draw Corner 90° L-Marks
        pen_glow = QPen(QColor(255, 87, 34, 90), 4)
        pen_line = QPen(QColor("#ff5722"), 2, Qt.PenStyle.SolidLine)

        if self.mode in ("corners", "both"):
            t = max(1.0, min(self.corner_l_len, pw / 2.0, ph / 2.0))
            corner_lines = [
                # BL
                (to_screen(px1 + t, py1), to_screen(px1, py1)),
                (to_screen(px1, py1), to_screen(px1, py1 + t)),
                # BR
                (to_screen(px2 - t, py1), to_screen(px2, py1)),
                (to_screen(px2, py1), to_screen(px2, py1 + t)),
                # TR
                (to_screen(px2 - t, py2), to_screen(px2, py2)),
                (to_screen(px2, py2), to_screen(px2, py2 - t)),
                # TL
                (to_screen(px1 + t, py2), to_screen(px1, py2)),
                (to_screen(px1, py2), to_screen(px1, py2 - t)),
            ]
            for p1, p2 in corner_lines:
                painter.setPen(pen_glow)
                painter.drawLine(p1, p2)
                painter.setPen(pen_line)
                painter.drawLine(p1, p2)

        # 4. Draw Center '+' Registration Cross Mark
        pen_cross_glow = QPen(QColor(0, 230, 118, 90), 4)
        pen_cross = QPen(QColor("#00e676"), 2, Qt.PenStyle.SolidLine)

        if self.mode in ("center", "both"):
            cx = (px1 + px2) / 2.0
            cy = (py1 + py2) / 2.0
            hc = max(1.0, min(self.center_cross_len / 2.0, pw / 2.0, ph / 2.0))
            ch1 = to_screen(cx - hc, cy)
            ch2 = to_screen(cx + hc, cy)
            cv1 = to_screen(cx, cy - hc)
            cv2 = to_screen(cx, cy + hc)
            for p1, p2 in [(ch1, ch2), (cv1, cv2)]:
                painter.setPen(pen_cross_glow)
                painter.drawLine(p1, p2)
                painter.setPen(pen_cross)
                painter.drawLine(p1, p2)

        # Dimensions & info overlay
        painter.setFont(QFont("monospace", 8, QFont.Weight.Bold))
        painter.setPen(QColor("#ffa726"))
        dim_str = f"Perimeter: {pw:.1f} × {ph:.1f} mm"
        painter.drawText(10, 18, dim_str)


class AlignmentMarksDialog(QDialog):
    """
    Studio Dialog to generate 90° corner L-marks and center '+' registration cuts.
    Allows live preview, parameter tuning, adding to canvas, or direct laser streaming.
    """

    marks_generated = pyqtSignal(list)  # Emits list of LaserEntity to add to canvas

    def __init__(
        self,
        parent=None,
        target_entities: Optional[List[LaserEntity]] = None,
        all_entities: Optional[List[LaserEntity]] = None,
        settings: Optional[MachineSettings] = None,
        serial_ctrl: Optional[SerialController] = None,
        default_mode: str = "both",  # "corners", "center", "both"
    ):
        super().__init__(parent)
        self.setWindowTitle("Alignment & Registration Marks Studio")
        self.resize(760, 480)

        self.target_entities = target_entities or []
        self.all_entities = all_entities or []
        self.settings = settings or MachineSettings()
        self.serial_ctrl = serial_ctrl

        from laserforge.core.layer_manager import LayerManager
        self.gcode_gen = GCodeGenerator(self.settings, LayerManager())
        self.initial_mode = default_mode

        self._build_ui()
        self._sync_scope_dimensions()
        self._recalculate()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Left Column: Preview and Legends
        left_col = QVBoxLayout()
        self.preview = AlignmentMarksPreview(self)
        left_col.addWidget(self.preview, 1)

        legend_row = QHBoxLayout()
        lbl_legend_l = QLabel("■ 90° Corner L-Marks")
        lbl_legend_l.setStyleSheet("color: #ff5722; font-weight: bold; font-size: 11px;")
        lbl_legend_c = QLabel("■ Center '+' Cross Mark")
        lbl_legend_c.setStyleSheet("color: #00e676; font-weight: bold; font-size: 11px;")
        legend_row.addWidget(lbl_legend_l)
        legend_row.addWidget(lbl_legend_c)
        legend_row.addStretch()
        left_col.addLayout(legend_row)

        info_box = QLabel(
            "<b>Usage Tip:</b><br>"
            "• <b>Corner 90° L-Marks:</b> Acts as precision physical registration corner stops or spoilboard jigs.<br>"
            "• <b>Center '+' Mark:</b> Marks workpiece exact geometric center for visual laser targeting or double-sided engraving."
        )
        info_box.setStyleSheet("background-color: #21212e; color: #b0bec5; font-size: 10px; padding: 6px; border-radius: 4px;")
        info_box.setWordWrap(True)
        left_col.addWidget(info_box)

        main_layout.addLayout(left_col, 1)

        # Right Column: Controls & Configuration
        right_col = QVBoxLayout()

        # 1. Scope / Target Selection
        scope_grp = QGroupBox("1. Target Workpiece Scope")
        scope_layout = QVBoxLayout(scope_grp)

        self.rad_selected = QRadioButton(f"Selected Shapes ({len(self.target_entities)} items)")
        self.rad_all = QRadioButton(f"All Artwork ({len(self.all_entities)} items)")
        self.rad_custom = QRadioButton("Custom Dimensions")

        self.scope_group = QButtonGroup(self)
        self.scope_group.addButton(self.rad_selected)
        self.scope_group.addButton(self.rad_all)
        self.scope_group.addButton(self.rad_custom)

        if self.target_entities:
            self.rad_selected.setChecked(True)
        elif self.all_entities:
            self.rad_all.setChecked(True)
        else:
            self.rad_custom.setChecked(True)

        self.rad_selected.setEnabled(len(self.target_entities) > 0)
        self.rad_all.setEnabled(len(self.all_entities) > 0)

        self.rad_selected.toggled.connect(self._sync_scope_dimensions)
        self.rad_all.toggled.connect(self._sync_scope_dimensions)
        self.rad_custom.toggled.connect(self._sync_scope_dimensions)

        scope_layout.addWidget(self.rad_selected)
        scope_layout.addWidget(self.rad_all)
        scope_layout.addWidget(self.rad_custom)

        # Dimensions Grid
        dim_grid = QGridLayout()
        dim_grid.addWidget(QLabel("X:"), 0, 0)
        self.spin_x = QDoubleSpinBox()
        self.spin_x.setRange(-200.0, 2000.0)
        self.spin_x.setSuffix(" mm")
        self.spin_x.valueChanged.connect(self._recalculate)
        dim_grid.addWidget(self.spin_x, 0, 1)

        dim_grid.addWidget(QLabel("Y:"), 0, 2)
        self.spin_y = QDoubleSpinBox()
        self.spin_y.setRange(-200.0, 2000.0)
        self.spin_y.setSuffix(" mm")
        self.spin_y.valueChanged.connect(self._recalculate)
        dim_grid.addWidget(self.spin_y, 0, 3)

        dim_grid.addWidget(QLabel("Width:"), 1, 0)
        self.spin_w = QDoubleSpinBox()
        self.spin_w.setRange(1.0, 2000.0)
        self.spin_w.setValue(100.0)
        self.spin_w.setSuffix(" mm")
        self.spin_w.valueChanged.connect(self._recalculate)
        dim_grid.addWidget(self.spin_w, 1, 1)

        dim_grid.addWidget(QLabel("Height:"), 1, 2)
        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(1.0, 2000.0)
        self.spin_h.setValue(100.0)
        self.spin_h.setSuffix(" mm")
        self.spin_h.valueChanged.connect(self._recalculate)
        dim_grid.addWidget(self.spin_h, 1, 3)

        scope_layout.addLayout(dim_grid)
        right_col.addWidget(scope_grp)

        # 2. Features & Parameters
        feat_grp = QGroupBox("2. Alignment Marks Geometry")
        feat_grid = QGridLayout(feat_grp)

        feat_grid.addWidget(QLabel("Feature Type:"), 0, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItem("🎯 Both (Corner L's + Center +)", "both")
        self.combo_type.addItem("📐 90° Corner L-Marks Only", "corners")
        self.combo_type.addItem("➕ Center '+' Registration Mark Only", "center")

        if self.initial_mode == "corners":
            self.combo_type.setCurrentIndex(1)
        elif self.initial_mode == "center":
            self.combo_type.setCurrentIndex(2)
        else:
            self.combo_type.setCurrentIndex(0)

        self.combo_type.currentIndexChanged.connect(self._recalculate)
        feat_grid.addWidget(self.combo_type, 0, 1)

        feat_grid.addWidget(QLabel("Corner L Arm Length:"), 1, 0)
        self.spin_l_len = QDoubleSpinBox()
        self.spin_l_len.setRange(2.0, 100.0)
        self.spin_l_len.setValue(8.0)
        self.spin_l_len.setSuffix(" mm")
        self.spin_l_len.valueChanged.connect(self._recalculate)
        feat_grid.addWidget(self.spin_l_len, 1, 1)

        feat_grid.addWidget(QLabel("Center '+' Cross Size:"), 2, 0)
        self.spin_c_len = QDoubleSpinBox()
        self.spin_c_len.setRange(2.0, 100.0)
        self.spin_c_len.setValue(10.0)
        self.spin_c_len.setSuffix(" mm")
        self.spin_c_len.valueChanged.connect(self._recalculate)
        feat_grid.addWidget(self.spin_c_len, 2, 1)

        feat_grid.addWidget(QLabel("Margin / Offset:"), 3, 0)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(-50.0, 100.0)
        self.spin_margin.setValue(0.0)
        self.spin_margin.setSuffix(" mm")
        self.spin_margin.setToolTip("Offset from workpiece edges (+ expands outward, - shrinks inward)")
        self.spin_margin.valueChanged.connect(self._recalculate)
        feat_grid.addWidget(self.spin_margin, 3, 1)

        feat_grid.addWidget(QLabel("Target Layer:"), 4, 0)
        self.combo_layer = QComboBox()
        self.combo_layer.addItem("Layer 12 (Tool / Alignment Guide)", 12)
        self.combo_layer.addItem("Layer 1 (Score / Engrave)", 1)
        self.combo_layer.addItem("Layer 0 (Cut / Perimeter)", 0)
        feat_grid.addWidget(self.combo_layer, 4, 1)

        right_col.addWidget(feat_grp)
        right_col.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        if self.serial_ctrl and self.serial_ctrl.is_connected:
            self.btn_burn_now = QPushButton("🔥 Score / Cut Now")
            self.btn_burn_now.setStyleSheet("background-color: #d84315; color: white; font-weight: bold; padding: 6px;")
            self.btn_burn_now.clicked.connect(self._burn_now)
            btn_layout.addWidget(self.btn_burn_now)

        self.btn_add_canvas = QPushButton("✔ Add to Canvas")
        self.btn_add_canvas.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px;")
        self.btn_add_canvas.clicked.connect(self._add_to_canvas)
        btn_layout.addWidget(self.btn_add_canvas)

        right_col.addLayout(btn_layout)
        main_layout.addLayout(right_col, 1)

    def _sync_scope_dimensions(self):
        ents = []
        if self.rad_selected.isChecked():
            ents = self.target_entities
        elif self.rad_all.isChecked():
            ents = self.all_entities

        if ents:
            bounds_list = [e.get_bounds() for e in ents]
            min_x = min(b[0] for b in bounds_list)
            min_y = min(b[1] for b in bounds_list)
            max_x = max(b[2] for b in bounds_list)
            max_y = max(b[3] for b in bounds_list)

            self.spin_x.blockSignals(True)
            self.spin_y.blockSignals(True)
            self.spin_w.blockSignals(True)
            self.spin_h.blockSignals(True)

            self.spin_x.setValue(min_x)
            self.spin_y.setValue(min_y)
            self.spin_w.setValue(max(1.0, max_x - min_x))
            self.spin_h.setValue(max(1.0, max_y - min_y))

            self.spin_x.blockSignals(False)
            self.spin_y.blockSignals(False)
            self.spin_w.blockSignals(False)
            self.spin_h.blockSignals(False)

        is_custom = self.rad_custom.isChecked()
        self.spin_x.setEnabled(is_custom)
        self.spin_y.setEnabled(is_custom)
        self.spin_w.setEnabled(is_custom)
        self.spin_h.setEnabled(is_custom)

        self._recalculate()

    def _recalculate(self):
        mode = self.combo_type.currentData() or "both"
        self.spin_l_len.setEnabled(mode in ("corners", "both"))
        self.spin_c_len.setEnabled(mode in ("center", "both"))

        x = self.spin_x.value()
        y = self.spin_y.value()
        w = self.spin_w.value()
        h = self.spin_h.value()
        margin = self.spin_margin.value()

        self.preview.set_state(
            bbox=(x, y, x + w, y + h),
            mode=mode,
            corner_l_len=self.spin_l_len.value(),
            center_cross_len=self.spin_c_len.value(),
            margin=margin
        )

    def _get_target_bounds(self) -> Tuple[float, float, float, float]:
        x = self.spin_x.value()
        y = self.spin_y.value()
        w = self.spin_w.value()
        h = self.spin_h.value()
        return (x, y, x + w, y + h)

    def _generate_entities(self) -> List[LaserEntity]:
        bbox = self._get_target_bounds()
        mode_data = self.combo_type.currentData() or "both"
        layer_id = self.combo_layer.currentData()
        if layer_id is None:
            layer_id = 12

        margin = self.spin_margin.value()
        l_len = self.spin_l_len.value()
        c_len = self.spin_c_len.value()

        if mode_data == "corners":
            gen_mode = "corners"
        elif mode_data == "center":
            gen_mode = "center_plus"
        else:
            gen_mode = "corners_and_center"

        return self.gcode_gen.generate_burn_perimeter_entities(
            target=bbox,
            mode=gen_mode,
            margin_mm=margin,
            layer_id=layer_id,
            corner_tick_len_mm=l_len,
            center_cross_len_mm=c_len
        )

    def _add_to_canvas(self):
        entities = self._generate_entities()
        if not entities:
            QMessageBox.warning(self, "No Entities", "Could not generate alignment marks.")
            return

        self.marks_generated.emit(entities)
        self.accept()

    def _burn_now(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Not Connected", "Laser is not connected.")
            return

        bbox = self._get_target_bounds()
        mode_data = self.combo_type.currentData() or "both"
        gen_mode = "corners" if mode_data == "corners" else ("center_plus" if mode_data == "center" else "corners_and_center")

        gcode = self.gcode_gen.generate_burn_perimeter_gcode(
            target=bbox,
            mode=gen_mode,
            margin_mm=self.spin_margin.value(),
            power_pct=15.0,
            speed=1500.0,
            passes=1,
            corner_tick_len_mm=self.spin_l_len.value(),
            center_cross_len_mm=self.spin_c_len.value(),
            air_assist=False
        )

        if not gcode:
            QMessageBox.warning(self, "Error", "Could not generate G-code.")
            return

        res = QMessageBox.question(
            self,
            "Fire Laser",
            f"Are you ready to score/cut the alignment marks directly?\n\nMode: {self.combo_type.currentText()}\nPower: 15% | Speed: 1500 mm/min",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            self.serial_ctrl.start_job(gcode)
            self.accept()
