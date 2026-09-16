"""
LaserForge Workpiece Alignment & Precision Motor Controller Assistant.
Provides:
1. Two-point corner alignment (Left & Right corners) to automatically rotate, scale,
   and align canvas artwork to crooked physical stock on the machine bed.
2. Built-in precision motor controller with 8-way directional jog pad, micro-stepping
   (0.01 mm to 50 mm), speed control, keyboard arrow navigation, and direct target coordinate dispatch.
3. Automated motor positioning to jump directly to Left Corner, Right Corner, Midpoint,
   or design corners.
4. Interactive real-time visual diagram showing machine bed, design envelope, Left/Right corners,
   measured angle/distance, aligned preview, and live laser head crosshair.
5. Work coordinate zeroing (G10 L20 P1 at Left Corner), edge tracing, low-power visible guide beam,
   momentary spot pulse, continuous framing, and 90° wasteboard corner stop jig generation.
"""

from typing import List, Tuple, Optional
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QSlider, QFrame,
    QMessageBox, QRadioButton, QButtonGroup, QCheckBox, QComboBox,
    QScrollArea, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF, QPointF
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPolygonF, QKeyEvent

from laserforge.core.serial_controller import SerialController
from laserforge.core.models import LaserEntity, RectEntity, LineEntity, TextEntity, PathEntity


class AlignmentVisualWidget(QWidget):
    """
    Interactive real-time visual diagram of the laser bed, design envelope,
    Left Corner (Pt 1), Right Corner (Pt 2), aligned transformation preview,
    and live laser head position.
    """

    point_clicked = pyqtSignal(float, float)  # (x, y) clicked in machine mm

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.bbox: Tuple[float, float, float, float] = (20.0, 20.0, 105.6, 74.0)
        self.bed_width: float = 400.0
        self.bed_height: float = 400.0
        self.pt1: Optional[Tuple[float, float]] = None
        self.pt2: Optional[Tuple[float, float]] = None
        self.laser_pos: Tuple[float, float] = (0.0, 0.0)
        self.angle_deg: float = 0.0
        self.dist_measured: float = 0.0
        self.ref_mode: str = "BL"
        self.auto_scale: bool = False
        self.scale_factor: float = 1.0

        self.setStyleSheet("background-color: #14141a; border: 1px solid #2e2e3e; border-radius: 4px;")

    def update_state(
        self,
        bbox: Tuple[float, float, float, float],
        pt1: Optional[Tuple[float, float]],
        pt2: Optional[Tuple[float, float]],
        laser_pos: Tuple[float, float],
        angle_deg: float,
        dist_measured: float,
        ref_mode: str = "BL",
        auto_scale: bool = False,
        scale_factor: float = 1.0
    ):
        self.bbox = bbox
        self.pt1 = pt1
        self.pt2 = pt2
        self.laser_pos = laser_pos
        self.angle_deg = angle_deg
        self.dist_measured = dist_measured
        self.ref_mode = ref_mode
        self.auto_scale = auto_scale
        self.scale_factor = scale_factor
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = max(10, self.width() - 40)
            h = max(10, self.height() - 40)
            scale = min(w / max(1.0, self.bed_width), h / max(1.0, self.bed_height))
            ox = 20
            # bottom-left origin in bed coordinates
            oy = self.height() - 20
            click_x = (event.pos().x() - ox) / scale
            click_y = (oy - event.pos().y()) / scale
            if 0.0 <= click_x <= self.bed_width and 0.0 <= click_y <= self.bed_height:
                self.point_clicked.emit(click_x, click_y)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor("#14141a"))

        margin = 25
        avail_w = max(10, self.width() - margin * 2)
        avail_h = max(10, self.height() - margin * 2)

        # Calculate bounding display box
        max_bound_x = max(self.bed_width, self.bbox[2], self.pt1[0] if self.pt1 else 0, self.pt2[0] if self.pt2 else 0, self.laser_pos[0])
        max_bound_y = max(self.bed_height, self.bbox[3], self.pt1[1] if self.pt1 else 0, self.pt2[1] if self.pt2 else 0, self.laser_pos[1])
        disp_w = max(100.0, min(self.bed_width, max(200.0, max_bound_x * 1.08)))
        disp_h = max(100.0, min(self.bed_height, max(180.0, max_bound_y * 1.08)))

        scale = min(avail_w / disp_w, avail_h / disp_h)
        ox = margin
        oy = self.height() - margin

        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(ox + x * scale, oy - y * scale)

        # 1. Draw Bed Boundary and Grid
        p_bl = to_screen(0, 0)
        p_tr = to_screen(disp_w, disp_h)
        bed_rect = QRectF(p_bl.x(), p_tr.y(), p_tr.x() - p_bl.x(), p_bl.y() - p_tr.y())

        painter.setPen(QPen(QColor("#2c2c3c"), 1.0))
        painter.setBrush(QColor("#181824"))
        painter.drawRect(bed_rect)

        # Draw grid lines (every 20mm or 50mm depending on scale)
        grid_step = 20.0 if scale > 0.8 else 50.0
        painter.setPen(QPen(QColor("#20202e"), 0.8, Qt.PenStyle.DotLine))
        gx = grid_step
        while gx < disp_w:
            painter.drawLine(to_screen(gx, 0), to_screen(gx, disp_h))
            gx += grid_step
        gy = grid_step
        while gy < disp_h:
            painter.drawLine(to_screen(0, gy), to_screen(disp_w, gy))
            gy += grid_step

        # Origin marker
        p0 = to_screen(0, 0)
        painter.setPen(QPen(QColor("#ff5252"), 1.5))
        painter.drawLine(p0, to_screen(15, 0))
        painter.setPen(QPen(QColor("#69f0ae"), 1.5))
        painter.drawLine(p0, to_screen(0, 15))
        painter.setPen(QPen(QColor("#cfd8dc"), 1.0))
        painter.setFont(QFont("sans-serif", 7))
        painter.drawText(p0 + QPointF(2, -2), "(0,0)")

        # 2. Original Design Envelope (Cyan dashed)
        min_x, min_y, max_x, max_y = self.bbox
        p_des_bl = to_screen(min_x, min_y)
        p_des_tr = to_screen(max_x, max_y)
        des_rect = QRectF(p_des_bl.x(), p_des_tr.y(), p_des_tr.x() - p_des_bl.x(), p_des_bl.y() - p_des_tr.y())

        painter.setPen(QPen(QColor("#00e5ff"), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(0, 229, 255, 18))
        painter.drawRect(des_rect)
        painter.setPen(QColor("#80deea"))
        painter.setFont(QFont("sans-serif", 7))
        painter.drawText(des_rect.topLeft() + QPointF(4, 11), f"Design: {max_x - min_x:.1f} × {max_y - min_y:.1f} mm")

        # 3. Aligned Transformation Preview (Neon Green dashed)
        if self.pt1 and self.pt2:
            # Calculate rotated envelope
            w_des = max_x - min_x
            h_des = max_y - min_y
            s = self.scale_factor if self.auto_scale else 1.0
            rad = math.radians(self.angle_deg)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)

            # Determine reference corner in design
            if self.ref_mode == "TL":
                ref_dx, ref_dy = 0.0, h_des
            elif self.ref_mode == "CL":
                ref_dx, ref_dy = 0.0, h_des / 2.0
            else:  # "BL"
                ref_dx, ref_dy = 0.0, 0.0

            corners_rel = [
                (0.0 - ref_dx, 0.0 - ref_dy),
                (w_des - ref_dx, 0.0 - ref_dy),
                (w_des - ref_dx, h_des - ref_dy),
                (0.0 - ref_dx, h_des - ref_dy)
            ]

            poly = QPolygonF()
            for cx, cy in corners_rel:
                scx = cx * s
                scy = cy * s
                rx = scx * cos_a - scy * sin_a
                ry = scx * sin_a + scy * cos_a
                poly.append(to_screen(self.pt1[0] + rx, self.pt1[1] + ry))

            painter.setPen(QPen(QColor("#76ff03"), 1.4, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(118, 255, 3, 26))
            painter.drawPolygon(poly)

            # 4. Alignment Vector Line connecting Left Corner to Right Corner (Yellow)
            sp1 = to_screen(self.pt1[0], self.pt1[1])
            sp2 = to_screen(self.pt2[0], self.pt2[1])

            painter.setPen(QPen(QColor("#ffd600"), 2.0, Qt.PenStyle.SolidLine))
            painter.drawLine(sp1, sp2)

            # Callout label at midpoint
            mid_pt = QPointF((sp1.x() + sp2.x()) / 2.0, (sp1.y() + sp2.y()) / 2.0)
            painter.setPen(QColor("#fff59d"))
            painter.setFont(QFont("sans-serif", 8, QFont.Weight.Bold))
            painter.drawText(mid_pt + QPointF(-35, -7), f"{self.dist_measured:.1f} mm ({self.angle_deg:+.2f}°)")

        # 5. Point 1 (Left Corner) Target Marker
        if self.pt1:
            sp1 = to_screen(self.pt1[0], self.pt1[1])
            painter.setPen(QPen(QColor("#00e676"), 1.8))
            painter.setBrush(QColor(0, 230, 118, 40))
            painter.drawEllipse(sp1, 7.0, 7.0)
            painter.drawLine(QPointF(sp1.x() - 10, sp1.y()), QPointF(sp1.x() + 10, sp1.y()))
            painter.drawLine(QPointF(sp1.x(), sp1.y() - 10), QPointF(sp1.x(), sp1.y() + 10))
            painter.setPen(QColor("#69f0ae"))
            painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
            painter.drawText(sp1 + QPointF(8, 12), f"L: ({self.pt1[0]:.1f}, {self.pt1[1]:.1f})")

        # 6. Point 2 (Right Corner) Target Marker
        if self.pt2:
            sp2 = to_screen(self.pt2[0], self.pt2[1])
            painter.setPen(QPen(QColor("#ff9100"), 1.8))
            painter.setBrush(QColor(255, 145, 0, 40))
            painter.drawEllipse(sp2, 7.0, 7.0)
            painter.drawLine(QPointF(sp2.x() - 10, sp2.y()), QPointF(sp2.x() + 10, sp2.y()))
            painter.drawLine(QPointF(sp2.x(), sp2.y() - 10), QPointF(sp2.x(), sp2.y() + 10))
            painter.setPen(QColor("#ffb74d"))
            painter.setFont(QFont("sans-serif", 7, QFont.Weight.Bold))
            painter.drawText(sp2 + QPointF(8, 12), f"R: ({self.pt2[0]:.1f}, {self.pt2[1]:.1f})")

        # 7. Live Laser Head Reticle (Bright Red / Glowing)
        sl = to_screen(self.laser_pos[0], self.laser_pos[1])
        painter.setPen(QPen(QColor("#ff1744"), 2.0))
        painter.setBrush(QColor(255, 23, 68, 70))
        painter.drawEllipse(sl, 5.0, 5.0)
        painter.drawLine(QPointF(sl.x() - 12, sl.y()), QPointF(sl.x() + 12, sl.y()))
        painter.drawLine(QPointF(sl.x(), sl.y() - 12), QPointF(sl.x(), sl.y() + 12))
        painter.setPen(QColor("#ff5252"))
        painter.setFont(QFont("monospace", 7, QFont.Weight.Bold))
        painter.drawText(sl + QPointF(8, -4), f"LASER ({self.laser_pos[0]:.1f}, {self.laser_pos[1]:.1f})")

        # Legend
        painter.setFont(QFont("sans-serif", 7))
        painter.setPen(QColor("#90a4ae"))
        painter.drawText(10, self.height() - 6, "Cyan: Design Envelope  |  Green: Left Corner  |  Orange: Right Corner  |  Lime: Aligned  |  Red: Laser")


class JogButton(QPushButton):
    """Square icon/text jog button with consistent styling."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(38, 32)
        self.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))


class LaserAlignmentDialog(QDialog):
    """
    Interactive Workpiece Alignment & Precision Motor Controller Assistant.
    Supports Left/Right 2-point corner alignment, complete motor jog controller,
    automated motor positioning to target spots, and live visual preview.
    """

    # Signals: Overloaded to support both 3-arg legacy and 5-arg extended
    align_canvas_requested = pyqtSignal([float, float, float], [float, float, float, float, str])
    generate_jig_requested = pyqtSignal(float, float)        # (card_w, card_h)
    burn_perimeter_requested = pyqtSignal(tuple)             # (min_x, min_y, max_x, max_y)

    def __init__(
        self,
        serial_ctrl: SerialController,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.serial_ctrl = serial_ctrl
        self.bbox = bbox or (20.0, 20.0, 105.6, 74.0)

        self.setWindowTitle("Workpiece Corner Alignment & Precision Motor Controller")
        self.resize(840, 680)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.current_pos = [0.0, 0.0]
        self.pt1: Optional[Tuple[float, float]] = None
        self.pt2: Optional[Tuple[float, float]] = None
        self.is_framing_continuous = False

        self.step_distance: float = 1.0
        self.jog_speed: float = 2500.0
        self.ref_mode: str = "BL"  # "BL" (Bottom edge), "TL" (Top edge), "CL" (Center line)

        self._init_ui()
        self._connect_signals()

        # Update initial positions and visual widget
        self._update_telemetry()
        self._update_calculations()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # Header Info Banner
        banner = QLabel(
            "<b>🎯 2-Point Corner Alignment:</b> Align your design to physical stock by setting "
            "<b>Left Corner</b> and <b>Right Corner</b>. Use the precision motor controller to jog or jump "
            "directly to target corners!"
        )
        banner.setStyleSheet(
            "background-color: #1e2838; color: #b0bec5; padding: 6px 10px; border-radius: 4px; font-size: 11px;"
        )
        banner.setWordWrap(True)
        root_layout.addWidget(banner)

        # Main Splitter / Two-Column Layout
        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(10)

        # ==========================================
        # LEFT COLUMN: PRECISION MOTOR CONTROLLER
        # ==========================================
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        # 1. Real-Time DRO & State
        dro_box = QGroupBox("Laser Status & Coordinates (DRO)")
        dro_layout = QVBoxLayout(dro_box)
        dro_layout.setSpacing(4)

        dro_top_row = QHBoxLayout()
        self.lbl_status_badge = QLabel("DISCONNECTED")
        self.lbl_status_badge.setStyleSheet(
            "background-color: #37474f; color: #cfd8dc; font-weight: bold; font-size: 10px; padding: 2px 6px; border-radius: 3px;"
        )
        dro_top_row.addWidget(self.lbl_status_badge)

        self.lbl_pos = QLabel("X: 0.00 mm   Y: 0.00 mm")
        self.lbl_pos.setStyleSheet("font-family: monospace; font-size: 14px; font-weight: bold; color: #00e5ff;")
        dro_top_row.addWidget(self.lbl_pos, 1, Qt.AlignmentFlag.AlignRight)
        dro_layout.addLayout(dro_top_row)

        origin_row = QHBoxLayout()
        self.btn_set_zero = QPushButton("⌖ Set Origin (0,0)")
        self.btn_set_zero.setToolTip("Set current physical position as work coordinate (0, 0)")
        self.btn_set_zero.setStyleSheet("font-size: 11px; padding: 3px;")
        self.btn_set_zero.clicked.connect(lambda: self.serial_ctrl.set_zero(True, True, True))
        origin_row.addWidget(self.btn_set_zero)

        self.btn_go_zero = QPushButton("⌂ Go to Origin")
        self.btn_go_zero.setToolTip("Rapid move to work origin (0, 0)")
        self.btn_go_zero.setStyleSheet("font-size: 11px; padding: 3px;")
        self.btn_go_zero.clicked.connect(lambda: self.serial_ctrl.go_to_zero(self.jog_speed))
        origin_row.addWidget(self.btn_go_zero)
        dro_layout.addLayout(origin_row)

        left_col.addWidget(dro_box)

        # 2. Precision Jogging Pad & Multi-Rate Step Control
        jog_box = QGroupBox("Precision Motor Jog Controller")
        jog_layout = QVBoxLayout(jog_box)
        jog_layout.setSpacing(6)

        # Step Selection
        step_row = QHBoxLayout()
        step_row.setSpacing(3)
        step_row.addWidget(QLabel("Step:"))

        self.step_btn_group = QButtonGroup(self)
        step_presets = [("0.01", 0.01), ("0.1", 0.1), ("0.5", 0.5), ("1", 1.0), ("5", 5.0), ("10", 10.0), ("50", 50.0)]
        for label, val in step_presets:
            rb = QRadioButton(label)
            if val == 1.0:
                rb.setChecked(True)
            self.step_btn_group.addButton(rb)
            rb.toggled.connect(lambda chk, v=val: self._on_step_radio_toggled(chk, v))
            step_row.addWidget(rb)

        jog_layout.addLayout(step_row)

        # Custom Step & Speed
        adv_step_row = QHBoxLayout()
        adv_step_row.addWidget(QLabel("Custom:"))
        self.spin_custom_step = QDoubleSpinBox()
        self.spin_custom_step.setRange(0.001, 200.0)
        self.spin_custom_step.setValue(1.0)
        self.spin_custom_step.setSingleStep(0.1)
        self.spin_custom_step.setDecimals(3)
        self.spin_custom_step.setSuffix(" mm")
        self.spin_custom_step.setFixedWidth(78)
        self.spin_custom_step.valueChanged.connect(self._on_custom_step_changed)
        adv_step_row.addWidget(self.spin_custom_step)

        adv_step_row.addSpacing(6)
        adv_step_row.addWidget(QLabel("Speed:"))
        self.spin_jog_speed = QDoubleSpinBox()
        self.spin_jog_speed.setRange(100.0, 10000.0)
        self.spin_jog_speed.setSingleStep(500.0)
        self.spin_jog_speed.setValue(self.jog_speed)
        self.spin_jog_speed.setSuffix(" mm/m")
        self.spin_jog_speed.setFixedWidth(92)
        self.spin_jog_speed.valueChanged.connect(lambda val: setattr(self, "jog_speed", val))
        adv_step_row.addWidget(self.spin_jog_speed)
        jog_layout.addLayout(adv_step_row)

        # 8-Direction Jog Pad Grid
        jog_grid = QGridLayout()
        jog_grid.setSpacing(3)
        jog_grid.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_nw = JogButton("↖")
        self.btn_n  = JogButton("▲")
        self.btn_ne = JogButton("↗")
        self.btn_w  = JogButton("◀")
        self.btn_center_stop = JogButton("⏹")
        self.btn_center_stop.setToolTip("Cancel Jog / Hold")
        self.btn_center_stop.setStyleSheet("background-color: #455a64; color: white;")
        self.btn_e  = JogButton("▶")
        self.btn_sw = JogButton("↙")
        self.btn_s  = JogButton("▼")
        self.btn_se = JogButton("↘")

        self.btn_nw.clicked.connect(lambda: self._jog_step(-1, 1))
        self.btn_n.clicked.connect(lambda: self._jog_step(0, 1))
        self.btn_ne.clicked.connect(lambda: self._jog_step(1, 1))
        self.btn_w.clicked.connect(lambda: self._jog_step(-1, 0))
        self.btn_center_stop.clicked.connect(self._on_jog_stop_clicked)
        self.btn_e.clicked.connect(lambda: self._jog_step(1, 0))
        self.btn_sw.clicked.connect(lambda: self._jog_step(-1, -1))
        self.btn_s.clicked.connect(lambda: self._jog_step(0, -1))
        self.btn_se.clicked.connect(lambda: self._jog_step(1, -1))

        jog_grid.addWidget(self.btn_nw, 0, 0)
        jog_grid.addWidget(self.btn_n,  0, 1)
        jog_grid.addWidget(self.btn_ne, 0, 2)
        jog_grid.addWidget(self.btn_w,  1, 0)
        jog_grid.addWidget(self.btn_center_stop, 1, 1)
        jog_grid.addWidget(self.btn_e,  1, 2)
        jog_grid.addWidget(self.btn_sw, 2, 0)
        jog_grid.addWidget(self.btn_s,  2, 1)
        jog_grid.addWidget(self.btn_se, 2, 2)
        jog_layout.addLayout(jog_grid)

        # Keyboard Navigation Tip
        kb_tip = QLabel("⌨ Use Arrow Keys to jog | Shift=5x, Ctrl=0.1x micro-step")
        kb_tip.setStyleSheet("color: #78909c; font-size: 10px; font-style: italic;")
        kb_tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        jog_layout.addWidget(kb_tip)

        left_col.addWidget(jog_box)

        # 3. Direct Target Coordinate Controller ("Move Motor to...")
        direct_box = QGroupBox("Motor Spot Dispatch Controller")
        direct_layout = QVBoxLayout(direct_box)
        direct_layout.setSpacing(6)

        # Move to (X, Y)
        goto_row = QHBoxLayout()
        goto_row.addWidget(QLabel("X:"))
        self.spin_target_x = QDoubleSpinBox()
        self.spin_target_x.setRange(-1000.0, 2000.0)
        self.spin_target_x.setValue(self.bbox[0])
        self.spin_target_x.setDecimals(2)
        self.spin_target_x.setSuffix(" mm")
        goto_row.addWidget(self.spin_target_x)

        goto_row.addWidget(QLabel("Y:"))
        self.spin_target_y = QDoubleSpinBox()
        self.spin_target_y.setRange(-1000.0, 2000.0)
        self.spin_target_y.setValue(self.bbox[1])
        self.spin_target_y.setDecimals(2)
        self.spin_target_y.setSuffix(" mm")
        goto_row.addWidget(self.spin_target_y)

        self.btn_goto_xy = QPushButton("▶ Go To (X,Y)")
        self.btn_goto_xy.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 3px 8px;")
        self.btn_goto_xy.clicked.connect(self._goto_target_xy)
        goto_row.addWidget(self.btn_goto_xy)
        direct_layout.addLayout(goto_row)

        # Preset Jumps to Design Corners
        presets_label = QLabel("Quick Jump Motor to Design Spots:")
        presets_label.setStyleSheet("color: #cfd8dc; font-size: 10px;")
        direct_layout.addWidget(presets_label)

        jump_row = QHBoxLayout()
        jump_row.setSpacing(4)

        btn_jump_tl = QPushButton("↖ Top-L")
        btn_jump_tl.clicked.connect(lambda: self._target_point(self.bbox[0], self.bbox[3]))
        jump_row.addWidget(btn_jump_tl)

        btn_jump_tr = QPushButton("↗ Top-R")
        btn_jump_tr.clicked.connect(lambda: self._target_point(self.bbox[2], self.bbox[3]))
        jump_row.addWidget(btn_jump_tr)

        btn_jump_bl = QPushButton("↙ Bot-L")
        btn_jump_bl.clicked.connect(lambda: self._target_point(self.bbox[0], self.bbox[1]))
        jump_row.addWidget(btn_jump_bl)

        btn_jump_br = QPushButton("↘ Bot-R")
        btn_jump_br.clicked.connect(lambda: self._target_point(self.bbox[2], self.bbox[1]))
        jump_row.addWidget(btn_jump_br)

        btn_jump_c = QPushButton("🎯 Center")
        btn_jump_c.clicked.connect(lambda: self._target_point((self.bbox[0] + self.bbox[2]) / 2.0, (self.bbox[1] + self.bbox[3]) / 2.0))
        jump_row.addWidget(btn_jump_c)
        direct_layout.addLayout(jump_row)

        left_col.addWidget(direct_box)

        # 4. Target Beam & Pulse Controls
        beam_box = QGroupBox("Targeting Laser Beam & Focus Spot")
        beam_layout = QVBoxLayout(beam_box)
        beam_layout.setSpacing(6)

        beam_row = QHBoxLayout()
        beam_row.addWidget(QLabel("Power:"))
        self.slider_pwr = QSlider(Qt.Orientation.Horizontal)
        self.slider_pwr.setRange(2, 20)  # 0.2% to 2.0%
        self.slider_pwr.setValue(5)       # 0.5%
        self.slider_pwr.valueChanged.connect(self._on_pwr_slider_changed)
        beam_row.addWidget(self.slider_pwr, 1)

        self.lbl_pwr_val = QLabel("0.5%")
        self.lbl_pwr_val.setFixedWidth(38)
        beam_row.addWidget(self.lbl_pwr_val)

        self.btn_fire_toggle = QPushButton("🔦 Laser Dot ON")
        self.btn_fire_toggle.setCheckable(True)
        self.btn_fire_toggle.clicked.connect(self._toggle_fire)
        beam_row.addWidget(self.btn_fire_toggle)

        self.btn_pulse = QPushButton("⚡ Pulse (50ms)")
        self.btn_pulse.setToolTip("Fire a safe 50ms pulse to verify spot position")
        self.btn_pulse.clicked.connect(self._fire_pulse)
        beam_row.addWidget(self.btn_pulse)

        beam_layout.addLayout(beam_row)
        left_col.addWidget(beam_box)

        main_h_layout.addLayout(left_col, 4)

        # ==========================================
        # RIGHT COLUMN: 2-POINT ALIGNMENT & PREVIEW
        # ==========================================
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # 1. Interactive Visual Diagram Widget
        self.visual_widget = AlignmentVisualWidget(self)
        self.visual_widget.point_clicked.connect(self._on_visual_clicked)
        right_col.addWidget(self.visual_widget, 1)

        # 2. Reference Edge Mode & Corner Setup
        corner_box = QGroupBox("Workpiece Reference Corners (Left & Right)")
        corner_layout = QVBoxLayout(corner_box)
        corner_layout.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Reference Edge:"))
        self.combo_ref_mode = QComboBox()
        self.combo_ref_mode.addItem("Bottom Edge (Bottom-Left → Bottom-Right)", "BL")
        self.combo_ref_mode.addItem("Top Edge (Top-Left → Top-Right)", "TL")
        self.combo_ref_mode.addItem("Center Line (Center-Left → Center-Right)", "CL")
        self.combo_ref_mode.currentIndexChanged.connect(self._on_ref_mode_changed)
        mode_row.addWidget(self.combo_ref_mode, 1)
        corner_layout.addLayout(mode_row)

        # Point 1 (Left Corner) Container
        pt1_frame = QFrame()
        pt1_frame.setStyleSheet("background-color: #1a2424; border: 1px solid #004d40; border-radius: 4px; padding: 4px;")
        pt1_layout = QHBoxLayout(pt1_frame)
        pt1_layout.setContentsMargins(6, 4, 6, 4)
        pt1_layout.setSpacing(6)

        lbl_p1_title = QLabel("<b>📍 Left Corner (Pt 1):</b>")
        lbl_p1_title.setStyleSheet("color: #00e676;")
        pt1_layout.addWidget(lbl_p1_title)

        self.spin_p1_x = QDoubleSpinBox()
        self.spin_p1_x.setRange(-1000.0, 2000.0)
        self.spin_p1_x.setDecimals(2)
        self.spin_p1_x.setPrefix("X: ")
        self.spin_p1_x.setSuffix(" mm")
        self.spin_p1_x.valueChanged.connect(self._on_pt1_spins_changed)
        pt1_layout.addWidget(self.spin_p1_x)

        self.spin_p1_y = QDoubleSpinBox()
        self.spin_p1_y.setRange(-1000.0, 2000.0)
        self.spin_p1_y.setDecimals(2)
        self.spin_p1_y.setPrefix("Y: ")
        self.spin_p1_y.setSuffix(" mm")
        self.spin_p1_y.valueChanged.connect(self._on_pt1_spins_changed)
        pt1_layout.addWidget(self.spin_p1_y)

        self.btn_cap1 = QPushButton("📍 Set from Laser")
        self.btn_cap1.setStyleSheet("background-color: #00796b; color: white; font-weight: bold;")
        self.btn_cap1.clicked.connect(self._capture_pt1)
        pt1_layout.addWidget(self.btn_cap1)

        self.btn_drive_pt1 = QPushButton("▶ Drive Motor Here")
        self.btn_drive_pt1.setToolTip("Drive laser head directly to Point 1")
        self.btn_drive_pt1.clicked.connect(self._drive_to_pt1)
        pt1_layout.addWidget(self.btn_drive_pt1)

        corner_layout.addWidget(pt1_frame)

        # Point 2 (Right Corner) Container
        pt2_frame = QFrame()
        pt2_frame.setStyleSheet("background-color: #271f18; border: 1px solid #bf360c; border-radius: 4px; padding: 4px;")
        pt2_layout = QHBoxLayout(pt2_frame)
        pt2_layout.setContentsMargins(6, 4, 6, 4)
        pt2_layout.setSpacing(6)

        lbl_p2_title = QLabel("<b>📍 Right Corner (Pt 2):</b>")
        lbl_p2_title.setStyleSheet("color: #ff9100;")
        pt2_layout.addWidget(lbl_p2_title)

        self.spin_p2_x = QDoubleSpinBox()
        self.spin_p2_x.setRange(-1000.0, 2000.0)
        self.spin_p2_x.setDecimals(2)
        self.spin_p2_x.setPrefix("X: ")
        self.spin_p2_x.setSuffix(" mm")
        self.spin_p2_x.valueChanged.connect(self._on_pt2_spins_changed)
        pt2_layout.addWidget(self.spin_p2_x)

        self.spin_p2_y = QDoubleSpinBox()
        self.spin_p2_y.setRange(-1000.0, 2000.0)
        self.spin_p2_y.setDecimals(2)
        self.spin_p2_y.setPrefix("Y: ")
        self.spin_p2_y.setSuffix(" mm")
        self.spin_p2_y.valueChanged.connect(self._on_pt2_spins_changed)
        pt2_layout.addWidget(self.spin_p2_y)

        self.btn_cap2 = QPushButton("📍 Set from Laser")
        self.btn_cap2.setStyleSheet("background-color: #e65100; color: white; font-weight: bold;")
        self.btn_cap2.clicked.connect(self._capture_pt2)
        pt2_layout.addWidget(self.btn_cap2)

        self.btn_drive_pt2 = QPushButton("▶ Drive Motor Here")
        self.btn_drive_pt2.setToolTip("Drive laser head directly to Point 2")
        self.btn_drive_pt2.clicked.connect(self._drive_to_pt2)
        pt2_layout.addWidget(self.btn_drive_pt2)

        corner_layout.addWidget(pt2_frame)

        # Midpoint & Edge Trace Row
        aux_row = QHBoxLayout()
        self.btn_drive_mid = QPushButton("▶ Drive Motor to Midpoint / Center")
        self.btn_drive_mid.clicked.connect(self._drive_to_midpoint)
        aux_row.addWidget(self.btn_drive_mid)

        self.btn_trace_edge = QPushButton("⛶ Trace Aligned Edge (L → R)")
        self.btn_trace_edge.setToolTip("Drives the laser head slowly from Left Corner to Right Corner with guide beam on")
        self.btn_trace_edge.clicked.connect(self._trace_aligned_edge)
        aux_row.addWidget(self.btn_trace_edge)
        corner_layout.addLayout(aux_row)

        right_col.addWidget(corner_box)

        # 3. Measurement Analysis & Alignment Execution
        exec_box = QGroupBox("Measurement Analysis & Alignment Execution")
        exec_layout = QVBoxLayout(exec_box)
        exec_layout.setSpacing(6)

        self.lbl_calc_result = QLabel("Measured Angle: --  |  Distance: --  |  Scale: 1.000x")
        self.lbl_calc_result.setStyleSheet("color: #ffd54f; font-weight: bold; font-size: 11px;")
        exec_layout.addWidget(self.lbl_calc_result)

        self.lbl_pt1 = QLabel("Pt 1 (Left): Not set")
        self.lbl_pt1.setStyleSheet("color: #80cbc4; font-size: 10px; font-family: monospace;")
        self.lbl_pt2 = QLabel("Pt 2 (Right): Not set")
        self.lbl_pt2.setStyleSheet("color: #ffcc80; font-size: 10px; font-family: monospace;")
        pts_lbl_row = QHBoxLayout()
        pts_lbl_row.addWidget(self.lbl_pt1)
        pts_lbl_row.addWidget(self.lbl_pt2)
        exec_layout.addLayout(pts_lbl_row)

        # Auto Scale Checkbox
        self.chk_auto_scale = QCheckBox("Auto-scale design artwork to match measured physical distance")
        self.chk_auto_scale.setChecked(False)
        self.chk_auto_scale.setToolTip("If enabled, scales the design proportionally to fit the measured corner distance")
        self.chk_auto_scale.toggled.connect(self._update_calculations)
        exec_layout.addWidget(self.chk_auto_scale)

        # Primary Execution Buttons
        btn_row = QHBoxLayout()
        self.btn_apply_align = QPushButton("✨ Align Canvas Artwork to Workpiece")
        self.btn_apply_align.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 8px 12px; border-radius: 4px; font-size: 12px;"
        )
        self.btn_apply_align.clicked.connect(self._apply_2point_alignment)
        btn_row.addWidget(self.btn_apply_align, 2)

        self.btn_set_zero_corner = QPushButton("📍 Set Work Zero at Left Corner")
        self.btn_set_zero_corner.setStyleSheet("background-color: #0277bd; color: white; font-weight: bold; padding: 8px;")
        self.btn_set_zero_corner.clicked.connect(self._set_work_zero_at_left_corner)
        btn_row.addWidget(self.btn_set_zero_corner, 1)
        exec_layout.addLayout(btn_row)

        # Continuous Framing & L-Jig Tools Row
        tools_row = QHBoxLayout()
        self.btn_continuous_frame = QPushButton("⛶ Continuous Framing")
        self.btn_continuous_frame.setCheckable(True)
        self.btn_continuous_frame.clicked.connect(self._toggle_continuous_framing)
        tools_row.addWidget(self.btn_continuous_frame)

        self.btn_burn_perimeter = QPushButton("🔥 Burn Perimeter...")
        self.btn_burn_perimeter.setToolTip("Open Burn Perimeter Tool to score/burn boundary on wasteboard or stock")
        self.btn_burn_perimeter.setStyleSheet("background-color: #d84315; color: white; font-weight: bold; padding: 6px;")
        self.btn_burn_perimeter.clicked.connect(self._open_burn_perimeter_tool)
        tools_row.addWidget(self.btn_burn_perimeter)

        self.btn_gen_jig = QPushButton("📐 90° Corner Stop Jig")
        self.btn_gen_jig.clicked.connect(self._generate_l_jig)
        tools_row.addWidget(self.btn_gen_jig)
        exec_layout.addLayout(tools_row)

        right_col.addWidget(exec_box)

        main_h_layout.addLayout(right_col, 5)
        root_layout.addLayout(main_h_layout, 1)

        # Bottom Close Row
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self._on_close)
        close_row.addWidget(btn_close)
        root_layout.addLayout(close_row)

    def _connect_signals(self):
        self.serial_ctrl.status_updated.connect(self._on_status_updated)
        self.serial_ctrl.connected.connect(lambda _: self._update_connection_ui(True))
        self.serial_ctrl.disconnected.connect(lambda: self._update_connection_ui(False))
        self._update_connection_ui(self.serial_ctrl.is_connected)

    def _update_connection_ui(self, connected: bool):
        if connected:
            self.lbl_status_badge.setText("CONNECTED")
            self.lbl_status_badge.setStyleSheet(
                "background-color: #1b5e20; color: #a5d6a7; font-weight: bold; font-size: 10px; padding: 2px 6px; border-radius: 3px;"
            )
        else:
            self.lbl_status_badge.setText("DISCONNECTED")
            self.lbl_status_badge.setStyleSheet(
                "background-color: #37474f; color: #cfd8dc; font-weight: bold; font-size: 10px; padding: 2px 6px; border-radius: 3px;"
            )

    def _on_status_updated(self, status: dict):
        wpos = status.get("wpos", [0.0, 0.0, 0.0])
        state = status.get("state", "Idle")
        if wpos and len(wpos) >= 2:
            self.current_pos = [wpos[0], wpos[1]]
            self.lbl_pos.setText(f"X: {wpos[0]:.2f} mm   Y: {wpos[1]:.2f} mm")
        elif wpos and len(wpos) == 1:
            self.current_pos = [wpos[0], 0.0]
            self.lbl_pos.setText(f"X: {wpos[0]:.2f} mm   Y: 0.00 mm")
        self.lbl_status_badge.setText(f"{state.upper()}")

        color_map = {
            "IDLE": ("#1b5e20", "#a5d6a7"),
            "RUN":  ("#01579b", "#81d4fa"),
            "HOLD": ("#e65100", "#ffcc80"),
            "ALARM":("#b71c1c", "#ef9a9a")
        }
        bg, fg = color_map.get(state.upper(), ("#37474f", "#cfd8dc"))
        self.lbl_status_badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; font-weight: bold; font-size: 10px; padding: 2px 6px; border-radius: 3px;"
        )

        self._update_telemetry()

    def _update_telemetry(self):
        # Update target inputs if default
        if self.spin_target_x.value() == 0.0 and self.current_pos[0] != 0.0:
            self.spin_target_x.setValue(self.current_pos[0])
            self.spin_target_y.setValue(self.current_pos[1])

        # Push to visual widget
        self._sync_visual_widget()

    def _sync_visual_widget(self):
        calc = self._get_alignment_calculation()
        angle_deg = calc.get("angle_deg", 0.0)
        dist_measured = calc.get("dist_measured", 0.0)
        scale_factor = calc.get("scale_factor", 1.0)

        self.visual_widget.update_state(
            bbox=self.bbox,
            pt1=self.pt1,
            pt2=self.pt2,
            laser_pos=(self.current_pos[0], self.current_pos[1]),
            angle_deg=angle_deg,
            dist_measured=dist_measured,
            ref_mode=self.ref_mode,
            auto_scale=self.chk_auto_scale.isChecked(),
            scale_factor=scale_factor
        )

    # ==========================================
    # MOTOR JOGGING & CONTROLLER ACTIONS
    # ==========================================

    def _on_step_radio_toggled(self, checked: bool, val: float):
        if checked:
            self.step_distance = val
            self.spin_custom_step.blockSignals(True)
            self.spin_custom_step.setValue(val)
            self.spin_custom_step.blockSignals(False)

    def _on_custom_step_changed(self, val: float):
        self.step_distance = val
        for rb in self.step_btn_group.buttons():
            rb.blockSignals(True)
            rb.setChecked(False)
            rb.blockSignals(False)

    def _jog_step(self, dx_dir: float, dy_dir: float):
        """Jogs the laser head safely in physical coordinate space."""
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Jog Motor", "Laser is not connected. Connect in the Laser panel first.")
            return

        dx = dx_dir * self.step_distance
        dy = dy_dir * self.step_distance
        self.serial_ctrl.jog(dx, dy, 0.0, self.jog_speed)

    def _on_jog_stop_clicked(self):
        """Cancels jogging / sends soft hold."""
        if self.serial_ctrl.is_connected:
            self.serial_ctrl.send_command("!")  # GRBL feed hold
            QTimer.singleShot(200, lambda: self.serial_ctrl.send_command("~"))  # Resume

    def _goto_target_xy(self):
        """Dispatches motor directly to numeric Target X and Y."""
        tx = self.spin_target_x.value()
        ty = self.spin_target_y.value()
        self._target_point(tx, ty)

    def _drive_to_pt1(self):
        """Drives motor directly to Left Corner (Pt 1)."""
        if not self.pt1:
            QMessageBox.information(self, "Drive Motor", "Point 1 (Left Corner) is not set yet.")
            return
        self._target_point(self.pt1[0], self.pt1[1])

    def _drive_to_pt2(self):
        """Drives motor directly to Right Corner (Pt 2)."""
        if not self.pt2:
            QMessageBox.information(self, "Drive Motor", "Point 2 (Right Corner) is not set yet.")
            return
        self._target_point(self.pt2[0], self.pt2[1])

    def _drive_to_midpoint(self):
        """Drives motor directly to the midpoint between Left and Right corners."""
        if not self.pt1 or not self.pt2:
            QMessageBox.information(self, "Drive Motor", "Please capture both Left Corner and Right Corner first.")
            return
        mx = (self.pt1[0] + self.pt2[0]) / 2.0
        my = (self.pt1[1] + self.pt2[1]) / 2.0
        self._target_point(mx, my)

    def _target_point(self, target_x: float, target_y: float):
        """Jogs or rapidly positions laser to the given coordinate and projects the low-power targeting beam."""
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Targeting", "Laser is not connected. Connect in the Laser panel first.")
            return

        pct = self.slider_pwr.value() / 10.0
        s_val = max(1, int(round((pct / 100.0) * 1000)))

        gcode_cmds = [
            "G90",
            f"G0 X{target_x:.3f} Y{target_y:.3f} F{self.jog_speed:.0f}",
            f"M3 G1 S{s_val} F1"
        ]
        self.serial_ctrl.send_command("\n".join(gcode_cmds))
        self.btn_fire_toggle.setChecked(True)
        self.btn_fire_toggle.setText("Laser Dot OFF")
        self.btn_fire_toggle.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")

    def _trace_aligned_edge(self):
        """Drives laser head from Left Corner to Right Corner with visible guide beam active."""
        if not self.pt1 or not self.pt2:
            QMessageBox.warning(self, "Trace Edge", "Please capture both Left Corner and Right Corner first.")
            return
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Trace Edge", "Laser is not connected.")
            return

        pct = self.slider_pwr.value() / 10.0
        s_val = max(1, int(round((pct / 100.0) * 1000)))

        cmds = [
            "G90", "G21",
            f"G0 X{self.pt1[0]:.3f} Y{self.pt1[1]:.3f} F{self.jog_speed:.0f}",
            f"M3 G1 S{s_val} F1200",
            f"G1 X{self.pt2[0]:.3f} Y{self.pt2[1]:.3f} F1200",
            "M5 S0", "G0"
        ]
        self.serial_ctrl.send_command("\n".join(cmds))

    # ==========================================
    # KEYBOARD JOGGING NAVIGATION
    # ==========================================

    def keyPressEvent(self, event: QKeyEvent):
        # Pass to normal handler if focused on numeric input
        focused = self.focusWidget()
        if isinstance(focused, (QDoubleSpinBox, QSlider)):
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()
        mult = 1.0
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mult = 5.0
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            mult = 0.1

        dist_mult = mult
        if key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._jog_step(-1 * dist_mult, 0.0)
            event.accept()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._jog_step(1 * dist_mult, 0.0)
            event.accept()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self._jog_step(0.0, 1 * dist_mult)
            event.accept()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self._jog_step(0.0, -1 * dist_mult)
            event.accept()
        else:
            super().keyPressEvent(event)

    # ==========================================
    # TARGETING BEAM & PULSE
    # ==========================================

    def _on_pwr_slider_changed(self, val: int):
        pct = val / 10.0
        self.lbl_pwr_val.setText(f"{pct:.1f}%")
        if self.btn_fire_toggle.isChecked():
            s_val = max(1, int(round((pct / 100.0) * 1000)))
            self.serial_ctrl.toggle_test_laser(True, power_s=s_val)

    def _toggle_fire(self):
        on = self.btn_fire_toggle.isChecked()
        pct = self.slider_pwr.value() / 10.0
        s_val = max(1, int(round((pct / 100.0) * 1000)))
        if on:
            self.btn_fire_toggle.setText("Laser Dot OFF")
            self.btn_fire_toggle.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
            self.serial_ctrl.toggle_test_laser(True, power_s=s_val)
        else:
            self.btn_fire_toggle.setText("Laser Dot ON")
            self.btn_fire_toggle.setStyleSheet("")
            self.serial_ctrl.toggle_test_laser(False)

    def _fire_pulse(self):
        pct = self.slider_pwr.value() / 10.0
        self.serial_ctrl.pulse_laser(power_pct=pct, duration_ms=50)

    def _toggle_continuous_framing(self):
        checked = self.btn_continuous_frame.isChecked()
        if checked:
            if not self.serial_ctrl.is_connected:
                QMessageBox.warning(self, "Framing", "Laser is not connected.")
                self.btn_continuous_frame.setChecked(False)
                return

            pct = self.slider_pwr.value() / 10.0
            s_val = max(1, int(round((pct / 100.0) * 1000)))

            # If 2 points aligned, build oriented continuous framing sequence
            if self.pt1 and self.pt2:
                calc = self._get_alignment_calculation()
                angle_deg = calc.get("angle_deg", 0.0)
                scale = calc.get("scale_factor", 1.0) if self.chk_auto_scale.isChecked() else 1.0
                min_x, min_y, max_x, max_y = self.bbox
                w_des = max_x - min_x
                h_des = max_y - min_y

                if self.ref_mode == "TL":
                    ref_dx, ref_dy = 0.0, h_des
                elif self.ref_mode == "CL":
                    ref_dx, ref_dy = 0.0, h_des / 2.0
                else:
                    ref_dx, ref_dy = 0.0, 0.0

                corners = [
                    (0.0 - ref_dx, 0.0 - ref_dy),
                    (w_des - ref_dx, 0.0 - ref_dy),
                    (w_des - ref_dx, h_des - ref_dy),
                    (0.0 - ref_dx, h_des - ref_dy)
                ]

                rad = math.radians(angle_deg)
                cos_a, sin_a = math.cos(rad), math.sin(rad)
                pts = []
                for cx, cy in corners:
                    scx, scy = cx * scale, cy * scale
                    rx = scx * cos_a - scy * sin_a
                    ry = scx * sin_a + scy * cos_a
                    pts.append((self.pt1[0] + rx, self.pt1[1] + ry))

                lines = ["G90", "G21", f"G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f} F3000", f"M3 G1 S{s_val} F2500"]
                for _ in range(8):
                    for p in pts[1:] + [pts[0]]:
                        lines.append(f"G1 X{p[0]:.3f} Y{p[1]:.3f} F2500")
                lines.append("M5 S0")
                lines.append("G0")
            else:
                min_x, min_y, max_x, max_y = self.bbox
                lines = ["G90", "G21", f"G0 X{min_x:.3f} Y{min_y:.3f} F3000", f"M3 G1 S{s_val} F2500"]
                for _ in range(8):
                    lines.append(f"G1 X{max_x:.3f} Y{min_y:.3f} F2500")
                    lines.append(f"G1 X{max_x:.3f} Y{max_y:.3f} F2500")
                    lines.append(f"G1 X{min_x:.3f} Y{max_y:.3f} F2500")
                    lines.append(f"G1 X{min_x:.3f} Y{min_y:.3f} F2500")
                lines.append("M5 S0")
                lines.append("G0")

            self.btn_continuous_frame.setText("⏹ Stop Continuous Framing")
            self.btn_continuous_frame.setStyleSheet("background-color: #f57f17; color: white; font-weight: bold;")
            self.serial_ctrl.start_job("\n".join(lines))
        else:
            self.serial_ctrl.stop_streaming()
            self.btn_continuous_frame.setText("⛶ Continuous Framing Loop")
            self.btn_continuous_frame.setStyleSheet("")

    # ==========================================
    # CORNER CAPTURE & ALIGNMENT CALCULATIONS
    # ==========================================

    def _on_visual_clicked(self, x: float, y: float):
        """Called when user clicks directly inside the visual layout diagram."""
        self.spin_target_x.setValue(x)
        self.spin_target_y.setValue(y)

    def _on_ref_mode_changed(self, idx: int):
        self.ref_mode = self.combo_ref_mode.currentData() or "BL"
        self._update_calculations()

    def _capture_pt1(self):
        """Captures Left Corner (Pt 1) from live laser machine coordinates."""
        self.pt1 = (self.current_pos[0], self.current_pos[1])
        self.spin_p1_x.blockSignals(True)
        self.spin_p1_y.blockSignals(True)
        self.spin_p1_x.setValue(self.pt1[0])
        self.spin_p1_y.setValue(self.pt1[1])
        self.spin_p1_x.blockSignals(False)
        self.spin_p1_y.blockSignals(False)
        self.lbl_pt1.setText(f"Pt 1 (Left): X {self.pt1[0]:.2f}, Y {self.pt1[1]:.2f}")
        self._update_calculations()

    def _capture_pt2(self):
        """Captures Right Corner (Pt 2) from live laser machine coordinates."""
        self.pt2 = (self.current_pos[0], self.current_pos[1])
        self.spin_p2_x.blockSignals(True)
        self.spin_p2_y.blockSignals(True)
        self.spin_p2_x.setValue(self.pt2[0])
        self.spin_p2_y.setValue(self.pt2[1])
        self.spin_p2_x.blockSignals(False)
        self.spin_p2_y.blockSignals(False)
        self.lbl_pt2.setText(f"Pt 2 (Right): X {self.pt2[0]:.2f}, Y {self.pt2[1]:.2f}")
        self._update_calculations()

    def _on_pt1_spins_changed(self):
        self.pt1 = (self.spin_p1_x.value(), self.spin_p1_y.value())
        self.lbl_pt1.setText(f"Pt 1 (Left): X {self.pt1[0]:.2f}, Y {self.pt1[1]:.2f}")
        self._update_calculations()

    def _on_pt2_spins_changed(self):
        self.pt2 = (self.spin_p2_x.value(), self.spin_p2_y.value())
        self.lbl_pt2.setText(f"Pt 2 (Right): X {self.pt2[0]:.2f}, Y {self.pt2[1]:.2f}")
        self._update_calculations()

    def _calculate_2point(self):
        """Legacy helper matching old API."""
        self._update_calculations()

    def _get_alignment_calculation(self) -> dict:
        if not self.pt1 or not self.pt2:
            return {}

        dx = self.pt2[0] - self.pt1[0]
        dy = self.pt2[1] - self.pt1[1]
        dist_measured = math.hypot(dx, dy)
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        min_x, min_y, max_x, max_y = self.bbox
        expected_w = max(0.001, max_x - min_x)
        scale_factor = dist_measured / expected_w if expected_w > 0 else 1.0
        delta_l = dist_measured - expected_w

        return {
            "dx": dx,
            "dy": dy,
            "dist_measured": dist_measured,
            "expected_w": expected_w,
            "delta_l": delta_l,
            "angle_deg": angle_deg,
            "scale_factor": scale_factor
        }

    def _update_calculations(self):
        calc = self._get_alignment_calculation()
        if not calc:
            self.lbl_calc_result.setText("Measured Angle: --  |  Distance: --  |  Scale: 1.000x")
            self._sync_visual_widget()
            return

        angle_deg = calc["angle_deg"]
        dist = calc["dist_measured"]
        exp_w = calc["expected_w"]
        delta_l = calc["delta_l"]
        scale = calc["scale_factor"]

        self.lbl_calc_result.setText(
            f"Angle: <b>{angle_deg:+.2f}°</b>  |  "
            f"Distance: <b>{dist:.2f} mm</b> (Design: {exp_w:.2f} mm, Δ: {delta_l:+.2f} mm)  |  "
            f"Scale: <b>{scale:.3f}x</b>"
        )

        self._sync_visual_widget()

    def _apply_2point_alignment(self):
        """Rotates and translates the canvas design to match physical workpiece."""
        if not self.pt1 or not self.pt2:
            QMessageBox.warning(self, "Alignment", "Please set both Point 1 (Left Corner) and Point 2 (Right Corner) first.")
            return

        calc = self._get_alignment_calculation()
        angle_deg = calc.get("angle_deg", 0.0)
        scale = calc.get("scale_factor", 1.0) if self.chk_auto_scale.isChecked() else 1.0

        min_x, min_y, max_x, max_y = self.bbox

        # Determine reference corner on design based on ref_mode
        if self.ref_mode == "TL":
            ref_x, ref_y = min_x, max_y
        elif self.ref_mode == "CL":
            ref_x, ref_y = min_x, (min_y + max_y) / 2.0
        else:  # "BL"
            ref_x, ref_y = min_x, min_y

        shift_x = self.pt1[0] - ref_x
        shift_y = self.pt1[1] - ref_y

        # Emit both overloaded versions for maximum compatibility
        try:
            self.align_canvas_requested[float, float, float, float, str].emit(
                angle_deg, shift_x, shift_y, scale, self.ref_mode
            )
        except Exception:
            pass

        try:
            self.align_canvas_requested[float, float, float].emit(
                angle_deg, shift_x, shift_y
            )
        except Exception:
            pass

        QMessageBox.information(
            self, "Artwork Aligned",
            f"Canvas artwork rotated by <b>{angle_deg:+.2f}°</b>, shifted by <b>({shift_x:+.1f}, {shift_y:+.1f}) mm</b>"
            + (f", and scaled by <b>{scale:.3f}x</b>!" if self.chk_auto_scale.isChecked() else "!")
        )

    def _set_work_zero_at_left_corner(self):
        """Sets GRBL work zero (G10 L20 P1 X0 Y0) at Point 1 (Left Corner)."""
        if not self.pt1:
            QMessageBox.warning(self, "Work Zero", "Please capture or enter Point 1 (Left Corner) first.")
            return

        # If laser is not at Point 1, ask user if they want to move there first
        dist = math.hypot(self.current_pos[0] - self.pt1[0], self.current_pos[1] - self.pt1[1])
        if dist > 0.5:
            res = QMessageBox.question(
                self, "Move to Left Corner?",
                f"The laser head is currently {dist:.1f} mm away from Left Corner ({self.pt1[0]:.2f}, {self.pt1[1]:.2f}).\n"
                "Move the laser to Left Corner now and set Work Zero (0,0) there?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                self.serial_ctrl.go_to_pos(self.pt1[0], self.pt1[1], self.jog_speed)
                QTimer.singleShot(500, lambda: self.serial_ctrl.set_zero(True, True, False))
                QMessageBox.information(self, "Work Zero", f"Work Zero (0,0) set at Left Corner ({self.pt1[0]:.2f}, {self.pt1[1]:.2f})!")
                return

        self.serial_ctrl.set_zero(True, True, False)
        QMessageBox.information(self, "Work Zero", f"Work Zero (0,0) set at current Left Corner position!")

    def _generate_l_jig(self):
        min_x, min_y, max_x, max_y = self.bbox
        w = max(40.0, max_x - min_x)
        h = max(30.0, max_y - min_y)
        self.generate_jig_requested.emit(w, h)
        QMessageBox.information(self, "L-Bracket Jig", "90° Alignment Corner Stop placed on canvas (Layer T1)!")

    def _open_burn_perimeter_tool(self):
        target_bbox = self.bbox
        if self.pt1 and self.pt2:
            min_x = min(self.pt1[0], self.pt2[0])
            min_y = min(self.pt1[1], self.pt2[1])
            max_x = max(self.pt1[0], self.pt2[0])
            orig_w = max(1.0, self.bbox[2] - self.bbox[0])
            orig_h = max(1.0, self.bbox[3] - self.bbox[1])
            measured_w = max(1.0, max_x - min_x)
            measured_h = measured_w * (orig_h / orig_w)
            max_y = min_y + measured_h
            target_bbox = (min_x, min_y, max_x, max_y)

        self.burn_perimeter_requested.emit(target_bbox)

        from laserforge.ui.burn_perimeter_dialog import BurnPerimeterDialog
        from laserforge.config import MachineSettings
        from laserforge.core.gcode_generator import GCodeGenerator
        from laserforge.core.layer_manager import LayerManager

        parent_win = self.parent()
        settings = getattr(parent_win, "settings", MachineSettings())
        gcode_gen = getattr(parent_win, "gcode_gen", GCodeGenerator(settings, LayerManager()))
        layer_mgr = getattr(parent_win, "layer_manager", None)

        dlg = BurnPerimeterDialog(
            serial_ctrl=self.serial_ctrl,
            settings=settings,
            gcode_gen=gcode_gen,
            layer_manager=layer_mgr,
            custom_bbox=target_bbox,
            parent=self
        )
        if hasattr(parent_win, "_add_entities_to_canvas"):
            dlg.add_to_canvas_requested.connect(parent_win._add_entities_to_canvas)
        dlg.exec()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def reject(self):
        self._cleanup()
        super().reject()

    def accept(self):
        self._cleanup()
        super().accept()

    def _cleanup(self):
        try:
            if hasattr(self, "btn_fire_toggle") and self.btn_fire_toggle.isChecked():
                self.serial_ctrl.toggle_test_laser(False)
            if hasattr(self, "btn_continuous_frame") and self.btn_continuous_frame.isChecked():
                self.serial_ctrl.stop_streaming()
        except Exception:
            pass
        try:
            self.serial_ctrl.status_updated.disconnect(self._on_status_updated)
        except Exception:
            pass

    def _on_close(self):
        self.close()

