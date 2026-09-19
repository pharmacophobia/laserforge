"""
LaserForge Optical Print & Cut Studio Dialog.
Provides 2-point optical / machine registration to precisely align digital cut lines
with physical pre-printed materials (UV prints, stickers, pre-engraved plaques).
"""

from typing import List, Tuple, Optional, Any
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QSlider, QFrame,
    QMessageBox, QRadioButton, QButtonGroup, QCheckBox, QComboBox,
    QScrollArea, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF, QPointF
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPolygonF

from laserforge.core.serial_controller import SerialController
from laserforge.core.models import LaserEntity, RectEntity, LineEntity, TextEntity, PathEntity, CircleEntity


class PrintAndCutVisualWidget(QFrame):
    """Live interactive canvas showing digital targets vs physical recorded points."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #121218; border: 1px solid #2e2e3e; border-radius: 4px;")
        self.setMinimumSize(340, 240)

        self.bed_w = 400.0
        self.bed_h = 400.0
        self.dig_p1 = (50.0, 50.0)
        self.dig_p2 = (200.0, 50.0)
        self.phys_p1: Optional[Tuple[float, float]] = None
        self.phys_p2: Optional[Tuple[float, float]] = None
        self.laser_pos: Tuple[float, float] = (0.0, 0.0)
        self.angle_delta: float = 0.0
        self.scale_factor: float = 1.0

    def set_data(
        self,
        dig_p1: Tuple[float, float],
        dig_p2: Tuple[float, float],
        phys_p1: Optional[Tuple[float, float]],
        phys_p2: Optional[Tuple[float, float]],
        laser_pos: Tuple[float, float],
        angle_delta: float,
        scale_factor: float
    ):
        self.dig_p1 = dig_p1
        self.dig_p2 = dig_p2
        self.phys_p1 = phys_p1
        self.phys_p2 = phys_p2
        self.laser_pos = laser_pos
        self.angle_delta = angle_delta
        self.scale_factor = scale_factor
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Coordinate transform from machine (0..bed_w, 0..bed_h) to widget
        pad = 20.0
        w = float(self.width()) - pad * 2
        h = float(self.height()) - pad * 2
        scale = min(w / self.bed_w, h / self.bed_h)

        def to_scr(mx, my):
            # Machine origin bottom-left (Y up) or standard
            sx = pad + mx * scale
            sy = pad + (self.bed_h - my) * scale
            return QPointF(sx, sy)

        # Draw bed boundary
        b_tl = to_scr(0, self.bed_h)
        b_br = to_scr(self.bed_w, 0)
        painter.setPen(QPen(QColor("#334155"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.drawRect(QRectF(b_tl, b_br))

        # Digital Target Line (Cyan)
        sd1 = to_scr(self.dig_p1[0], self.dig_p1[1])
        sd2 = to_scr(self.dig_p2[0], self.dig_p2[1])
        painter.setPen(QPen(QColor("#06b6d4"), 2, Qt.PenStyle.DashDotLine))
        painter.drawLine(sd1, sd2)

        # Digital Points
        for p, lbl in [(sd1, "D1"), (sd2, "D2")]:
            painter.setPen(QPen(QColor("#06b6d4"), 2))
            painter.setBrush(QBrush(QColor(6, 182, 212, 60)))
            painter.drawEllipse(p, 6.0, 6.0)
            painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
            painter.setPen(QColor("#a5f3fc"))
            painter.drawText(p + QPointF(8, -4), lbl)

        # Physical Target Line & Points (Amber / Green)
        if self.phys_p1 and self.phys_p2:
            sp1 = to_scr(self.phys_p1[0], self.phys_p1[1])
            sp2 = to_scr(self.phys_p2[0], self.phys_p2[1])
            painter.setPen(QPen(QColor("#10b981"), 2))
            painter.drawLine(sp1, sp2)

        if self.phys_p1:
            sp1 = to_scr(self.phys_p1[0], self.phys_p1[1])
            painter.setPen(QPen(QColor("#10b981"), 2))
            painter.setBrush(QBrush(QColor(16, 185, 129, 80)))
            painter.drawEllipse(sp1, 7.0, 7.0)
            painter.drawLine(QPointF(sp1.x() - 10, sp1.y()), QPointF(sp1.x() + 10, sp1.y()))
            painter.drawLine(QPointF(sp1.x(), sp1.y() - 10), QPointF(sp1.x(), sp1.y() + 10))
            painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
            painter.setPen(QColor("#6ee7b7"))
            painter.drawText(sp1 + QPointF(8, 12), "P1 (Phys)")

        if self.phys_p2:
            sp2 = to_scr(self.phys_p2[0], self.phys_p2[1])
            painter.setPen(QPen(QColor("#f59e0b"), 2))
            painter.setBrush(QBrush(QColor(245, 158, 11, 80)))
            painter.drawEllipse(sp2, 7.0, 7.0)
            painter.drawLine(QPointF(sp2.x() - 10, sp2.y()), QPointF(sp2.x() + 10, sp2.y()))
            painter.drawLine(QPointF(sp2.x(), sp2.y() - 10), QPointF(sp2.x(), sp2.y() + 10))
            painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
            painter.setPen(QColor("#fde68a"))
            painter.drawText(sp2 + QPointF(8, 12), "P2 (Phys)")

        # Laser Current Head Position
        sl = to_scr(self.laser_pos[0], self.laser_pos[1])
        painter.setPen(QPen(QColor("#ef4444"), 1.8))
        painter.setBrush(QBrush(QColor(239, 68, 68, 80)))
        painter.drawEllipse(sl, 4.0, 4.0)
        painter.drawLine(QPointF(sl.x() - 8, sl.y()), QPointF(sl.x() + 8, sl.y()))
        painter.drawLine(QPointF(sl.x(), sl.y() - 8), QPointF(sl.x(), sl.y() + 8))


class PrintAndCutDialog(QDialog):
    """Studio for 2-Point Optical / Machine Registration."""

    alignment_applied = pyqtSignal(dict)

    def __init__(
        self,
        entities: List[LaserEntity],
        serial_controller: Optional[SerialController] = None,
        bed_size: Tuple[float, float] = (400.0, 400.0),
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Print & Cut Studio (2-Point Optical Registration) 🎯")
        self.setMinimumSize(780, 560)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; }
            QGroupBox { border: 1px solid #334155; border-radius: 6px; margin-top: 10px; font-weight: bold; color: #38bdf8; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #cbd5e1; font-size: 12px; }
            QDoubleSpinBox { background-color: #1e293b; border: 1px solid #475569; border-radius: 4px; color: #f8fafc; padding: 4px; font-size: 12px; }
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 4px; padding: 7px 14px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton#btnRecord { background-color: #059669; }
            QPushButton#btnRecord:hover { background-color: #10b981; }
            QPushButton#btnFrame { background-color: #d97706; }
            QPushButton#btnFrame:hover { background-color: #f59e0b; }
            QPushButton#btnCancel { background-color: #475569; }
            QPushButton#btnCancel:hover { background-color: #64748b; }
        """)

        self.entities = entities
        self.serial = serial_controller
        self.bed_w, self.bed_h = bed_size

        self.phys_p1: Optional[Tuple[float, float]] = None
        self.phys_p2: Optional[Tuple[float, float]] = None
        self.laser_pos: Tuple[float, float] = (0.0, 0.0)

        # Estimate digital registration targets from bounding box
        self._init_digital_targets()
        self._init_ui()

        # Telemetry timer
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._poll_telemetry)
        self.telemetry_timer.start(250)

    def _init_digital_targets(self):
        if not self.entities:
            self.dig_p1 = (30.0, 30.0)
            self.dig_p2 = (150.0, 30.0)
            return

        all_bounds = [e.get_bounds() for e in self.entities]
        min_x = min(b[0] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_x = max(b[2] for b in all_bounds)
        max_y = max(b[3] for b in all_bounds)

        # Default targets: bottom-left and bottom-right of design envelope
        self.dig_p1 = (min_x, min_y)
        self.dig_p2 = (max_x, min_y)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # Left Column: Configuration & Controls
        left_col = QVBoxLayout()

        # Group 1: Digital Targets in Design
        g_dig = QGroupBox("1. Digital Registration Targets (In Artwork)")
        d_layout = QGridLayout(g_dig)

        d_layout.addWidget(QLabel("Target 1 X:"), 0, 0)
        self.spin_d1_x = QDoubleSpinBox()
        self.spin_d1_x.setRange(-1000.0, 2000.0)
        self.spin_d1_x.setValue(self.dig_p1[0])
        self.spin_d1_x.valueChanged.connect(self._recalc_transform)
        d_layout.addWidget(self.spin_d1_x, 0, 1)

        d_layout.addWidget(QLabel("Target 1 Y:"), 0, 2)
        self.spin_d1_y = QDoubleSpinBox()
        self.spin_d1_y.setRange(-1000.0, 2000.0)
        self.spin_d1_y.setValue(self.dig_p1[1])
        self.spin_d1_y.valueChanged.connect(self._recalc_transform)
        d_layout.addWidget(self.spin_d1_y, 0, 3)

        d_layout.addWidget(QLabel("Target 2 X:"), 1, 0)
        self.spin_d2_x = QDoubleSpinBox()
        self.spin_d2_x.setRange(-1000.0, 2000.0)
        self.spin_d2_x.setValue(self.dig_p2[0])
        self.spin_d2_x.valueChanged.connect(self._recalc_transform)
        d_layout.addWidget(self.spin_d2_x, 1, 1)

        d_layout.addWidget(QLabel("Target 2 Y:"), 1, 2)
        self.spin_d2_y = QDoubleSpinBox()
        self.spin_d2_y.setRange(-1000.0, 2000.0)
        self.spin_d2_y.setValue(self.dig_p2[1])
        self.spin_d2_y.valueChanged.connect(self._recalc_transform)
        d_layout.addWidget(self.spin_d2_y, 1, 3)

        left_col.addWidget(g_dig)

        # Group 2: Physical Machine Points
        g_phys = QGroupBox("2. Physical Registration Points (On Machine Bed)")
        p_layout = QGridLayout(g_phys)

        p_layout.addWidget(QLabel("Physical Point 1:"), 0, 0)
        self.lbl_p1 = QLabel("Not Captured")
        self.lbl_p1.setStyleSheet("color: #94a3b8; font-weight: bold;")
        p_layout.addWidget(self.lbl_p1, 0, 1)

        self.btn_rec_p1 = QPushButton("Capture Laser Position as Pt 1")
        self.btn_rec_p1.setObjectName("btnRecord")
        self.btn_rec_p1.clicked.connect(self._record_p1)
        p_layout.addWidget(self.btn_rec_p1, 0, 2)

        p_layout.addWidget(QLabel("Physical Point 2:"), 1, 0)
        self.lbl_p2 = QLabel("Not Captured")
        self.lbl_p2.setStyleSheet("color: #94a3b8; font-weight: bold;")
        p_layout.addWidget(self.lbl_p2, 1, 1)

        self.btn_rec_p2 = QPushButton("Capture Laser Position as Pt 2")
        self.btn_rec_p2.setObjectName("btnRecord")
        self.btn_rec_p2.clicked.connect(self._record_p2)
        p_layout.addWidget(self.btn_rec_p2, 1, 2)

        left_col.addWidget(g_phys)

        # Group 3: Transformation Options
        g_opt = QGroupBox("3. Registration Options")
        o_layout = QVBoxLayout(g_opt)

        self.chk_allow_scale = QCheckBox("Auto-Scale Design to Fit Physical Distance")
        self.chk_allow_scale.setChecked(False)
        self.chk_allow_scale.toggled.connect(self._recalc_transform)
        o_layout.addWidget(self.chk_allow_scale)

        self.lbl_transform_info = QLabel("Rotation: +0.00° | Distance: 0.0 mm | Scale: 1.000x")
        self.lbl_transform_info.setStyleSheet("font-family: monospace; color: #fde047; font-weight: bold;")
        o_layout.addWidget(self.lbl_transform_info)

        left_col.addWidget(g_opt)

        # Group 4: Integrated Motor Jogging
        g_jog = QGroupBox("4. Laser Pointer / Jog Positioning")
        j_layout = QGridLayout(g_jog)

        self.spin_jog_step = QDoubleSpinBox()
        self.spin_jog_step.setRange(0.01, 100.0)
        self.spin_jog_step.setValue(1.0)
        self.spin_jog_step.setSuffix(" mm")

        j_layout.addWidget(QLabel("Step:"), 0, 0)
        j_layout.addWidget(self.spin_jog_step, 0, 1)

        btn_up = QPushButton("▲ Y+")
        btn_up.clicked.connect(lambda: self._jog(0, self.spin_jog_step.value()))
        btn_down = QPushButton("▼ Y-")
        btn_down.clicked.connect(lambda: self._jog(0, -self.spin_jog_step.value()))
        btn_left = QPushButton("◄ X-")
        btn_left.clicked.connect(lambda: self._jog(-self.spin_jog_step.value(), 0))
        btn_right = QPushButton("► X+")
        btn_right.clicked.connect(lambda: self._jog(self.spin_jog_step.value(), 0))

        j_layout.addWidget(btn_up, 1, 1)
        j_layout.addWidget(btn_left, 2, 0)
        j_layout.addWidget(btn_down, 2, 1)
        j_layout.addWidget(btn_right, 2, 2)

        self.btn_pointer = QPushButton("Visible Guide Pointer (0.5%)")
        self.btn_pointer.setCheckable(True)
        self.btn_pointer.toggled.connect(self._toggle_pointer)
        j_layout.addWidget(self.btn_pointer, 3, 0, 1, 3)

        left_col.addWidget(g_jog)
        left_col.addStretch()

        # Action Buttons
        btn_box = QHBoxLayout()
        self.btn_frame = QPushButton("Frame Aligned Perimeter")
        self.btn_frame.setObjectName("btnFrame")
        self.btn_frame.clicked.connect(self._frame_aligned)
        btn_box.addWidget(self.btn_frame)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_align = QPushButton("Align Artwork (Apply)")
        self.btn_align.clicked.connect(self._apply_alignment)
        btn_box.addWidget(self.btn_align)

        left_col.addLayout(btn_box)
        main_layout.addLayout(left_col, 1)

        # Right Column: Live Visual Widget
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("Visual Alignment & Bed Diagram:"))
        self.visual_widget = PrintAndCutVisualWidget()
        self.visual_widget.bed_w = self.bed_w
        self.visual_widget.bed_h = self.bed_h
        right_col.addWidget(self.visual_widget, 1)
        main_layout.addLayout(right_col, 1)

    def _poll_telemetry(self):
        if self.serial and getattr(self.serial, "is_connected", False):
            pos = getattr(self.serial, "wpos", [0.0, 0.0, 0.0])
            self.laser_pos = (pos[0], pos[1])
            self._update_visual()

    def _jog(self, dx: float, dy: float):
        if self.serial and getattr(self.serial, "is_connected", False):
            feed = 3000.0
            self.serial.send_command(f"$J=G91 G21 X{dx:.3f} Y{dy:.3f} F{feed:.0f}")

    def _toggle_pointer(self, enabled: bool):
        if self.serial and getattr(self.serial, "is_connected", False):
            if enabled:
                # 0.5% laser power for framing/targeting
                s_val = int(round(0.005 * 1000))
                self.serial.send_command(f"M3 S{s_val} G1 F100")
            else:
                self.serial.send_command("M5")

    def _record_p1(self):
        self.phys_p1 = self.laser_pos
        self.lbl_p1.setText(f"({self.phys_p1[0]:.2f}, {self.phys_p1[1]:.2f}) mm")
        self.lbl_p1.setStyleSheet("color: #10b981; font-weight: bold;")
        self._recalc_transform()

    def _record_p2(self):
        self.phys_p2 = self.laser_pos
        self.lbl_p2.setText(f"({self.phys_p2[0]:.2f}, {self.phys_p2[1]:.2f}) mm")
        self.lbl_p2.setStyleSheet("color: #f59e0b; font-weight: bold;")
        self._recalc_transform()

    def _recalc_transform(self):
        self.dig_p1 = (self.spin_d1_x.value(), self.spin_d1_y.value())
        self.dig_p2 = (self.spin_d2_x.value(), self.spin_d2_y.value())

        d_dx = self.dig_p2[0] - self.dig_p1[0]
        d_dy = self.dig_p2[1] - self.dig_p1[1]
        dig_dist = math.hypot(d_dx, d_dy)
        dig_ang = math.degrees(math.atan2(d_dy, d_dx))

        if self.phys_p1 and self.phys_p2:
            p_dx = self.phys_p2[0] - self.phys_p1[0]
            p_dy = self.phys_p2[1] - self.phys_p1[1]
            phys_dist = math.hypot(p_dx, p_dy)
            phys_ang = math.degrees(math.atan2(p_dy, p_dx))

            angle_delta = phys_ang - dig_ang
            scale_factor = (phys_dist / max(1e-6, dig_dist)) if self.chk_allow_scale.isChecked() else 1.0
            self.lbl_transform_info.setText(
                f"Rotation: {angle_delta:+.2f}° | Phys Dist: {phys_dist:.1f} mm | Scale: {scale_factor:.4f}x"
            )
        else:
            angle_delta = 0.0
            scale_factor = 1.0
            self.lbl_transform_info.setText(f"Digital Dist: {dig_dist:.1f} mm (Record Pt 1 & 2 to solve)")

        self._update_visual()

    def _update_visual(self):
        d_dx = self.dig_p2[0] - self.dig_p1[0]
        d_dy = self.dig_p2[1] - self.dig_p1[1]
        dig_ang = math.degrees(math.atan2(d_dy, d_dx))

        angle_delta = 0.0
        scale_factor = 1.0
        if self.phys_p1 and self.phys_p2:
            p_dx = self.phys_p2[0] - self.phys_p1[0]
            p_dy = self.phys_p2[1] - self.phys_p1[1]
            phys_ang = math.degrees(math.atan2(p_dy, p_dx))
            angle_delta = phys_ang - dig_ang
            if self.chk_allow_scale.isChecked() and math.hypot(d_dx, d_dy) > 1e-3:
                scale_factor = math.hypot(p_dx, p_dy) / math.hypot(d_dx, d_dy)

        self.visual_widget.set_data(
            self.dig_p1, self.dig_p2, self.phys_p1, self.phys_p2,
            self.laser_pos, angle_delta, scale_factor
        )

    def _apply_alignment(self):
        if not self.phys_p1 or not self.phys_p2:
            QMessageBox.warning(self, "Points Required", "Please capture both Physical Point 1 and Point 2.")
            return

        d_dx = self.dig_p2[0] - self.dig_p1[0]
        d_dy = self.dig_p2[1] - self.dig_p1[1]
        dig_ang = math.degrees(math.atan2(d_dy, d_dx))

        p_dx = self.phys_p2[0] - self.phys_p1[0]
        p_dy = self.phys_p2[1] - self.phys_p1[1]
        phys_ang = math.degrees(math.atan2(p_dy, p_dx))

        angle_delta_deg = phys_ang - dig_ang
        scale_factor = (math.hypot(p_dx, p_dy) / max(1e-6, math.hypot(d_dx, d_dy))) if self.chk_allow_scale.isChecked() else 1.0

        res = {
            "dig_p1": self.dig_p1,
            "phys_p1": self.phys_p1,
            "angle_deg": angle_delta_deg,
            "scale": scale_factor,
        }
        self.alignment_applied.emit(res)
        self.accept()

    def _frame_aligned(self):
        if not self.phys_p1 or not self.phys_p2:
            QMessageBox.warning(self, "Points Required", "Capture both physical points before framing.")
            return

        # Frame with pointer
        if self.serial and getattr(self.serial, "is_connected", False):
            self._toggle_pointer(True)
            feed = 2000.0
            # Move through P1 -> P2 -> P1
            p1 = self.phys_p1
            p2 = self.phys_p2
            self.serial.send_command(f"G1 X{p1[0]:.3f} Y{p1[1]:.3f} F{feed:.0f}")
            self.serial.send_command(f"G1 X{p2[0]:.3f} Y{p2[1]:.3f} F{feed:.0f}")
            self.serial.send_command(f"G1 X{p1[0]:.3f} Y{p1[1]:.3f} F{feed:.0f}")
