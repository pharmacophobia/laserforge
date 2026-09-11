"""
LaserForge Workpiece Alignment & Targeting Assistant.
Provides interactive laser targeting, 4-corner & center jogging with visible low-power guide beam,
continuous framing loop, 2-point rotational & positional workpiece alignment ("Print & Cut"),
and wasteboard physical 90-degree corner stop jig generation.
"""

from typing import List, Tuple, Optional
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QSlider, QFrame,
    QMessageBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from laserforge.core.serial_controller import SerialController
from laserforge.core.models import LaserEntity, RectEntity, LineEntity, TextEntity


class LaserAlignmentDialog(QDialog):
    """Interactive Workpiece Alignment, Targeting & 2-Point Rotation Assistant."""

    align_canvas_requested = pyqtSignal(float, float, float)  # (angle_deg, shift_x, shift_y)
    generate_jig_requested = pyqtSignal(float, float)        # (card_w, card_h)

    def __init__(
        self,
        serial_ctrl: SerialController,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.serial_ctrl = serial_ctrl
        self.bbox = bbox or (0.0, 0.0, 85.6, 54.0)

        self.setWindowTitle("Workpiece Alignment & Laser Targeting Assistant")
        self.resize(560, 640)

        self.current_pos = [0.0, 0.0]
        self.pt1: Optional[Tuple[float, float]] = None
        self.pt2: Optional[Tuple[float, float]] = None
        self.is_framing_continuous = False

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 1. Real-Time Laser Coordinate Header
        head_box = QGroupBox("Laser Position && Status")
        head_layout = QHBoxLayout(head_box)

        self.lbl_pos = QLabel("X: 0.00 mm   Y: 0.00 mm")
        self.lbl_pos.setStyleSheet("font-family: monospace; font-size: 14px; font-weight: bold; color: #00e5ff;")
        head_layout.addWidget(self.lbl_pos, 1)

        self.btn_set_zero = QPushButton("Set Origin (0,0)")
        self.btn_set_zero.setToolTip("Set current physical position as work coordinate (0, 0)")
        self.btn_set_zero.clicked.connect(lambda: self.serial_ctrl.set_zero(True, True, True))
        head_layout.addWidget(self.btn_set_zero)

        layout.addWidget(head_box)

        # 2. Visual Laser Targeting & Corner Jogging Group
        target_group = QGroupBox("Laser Targeting && Bounding Envelope")
        target_layout = QVBoxLayout(target_group)
        target_layout.setSpacing(8)

        min_x, min_y, max_x, max_y = self.bbox
        mid_x = (min_x + max_x) / 2.0
        mid_y = (min_y + max_y) / 2.0
        w = max_x - min_x
        h = max_y - min_y

        info_lbl = QLabel(f"Job Envelope: <b>{w:.1f} × {h:.1f} mm</b> (X: {min_x:.1f}..{max_x:.1f}, Y: {min_y:.1f}..{max_y:.1f})")
        info_lbl.setStyleSheet("color: #cfd8dc; font-size: 11px;")
        target_layout.addWidget(info_lbl)

        # 5-Point Quick Target Grid
        grid_5pt = QGridLayout()
        grid_5pt.setSpacing(6)

        btn_tl = QPushButton("↖ Top-Left")
        btn_tl.clicked.connect(lambda: self._target_point(min_x, max_y))
        grid_5pt.addWidget(btn_tl, 0, 0)

        btn_top = QPushButton("▲ Center-Top")
        btn_top.clicked.connect(lambda: self._target_point(mid_x, max_y))
        grid_5pt.addWidget(btn_top, 0, 1)

        btn_tr = QPushButton("↗ Top-Right")
        btn_tr.clicked.connect(lambda: self._target_point(max_x, max_y))
        grid_5pt.addWidget(btn_tr, 0, 2)

        btn_l = QPushButton("◀ Left")
        btn_l.clicked.connect(lambda: self._target_point(min_x, mid_y))
        grid_5pt.addWidget(btn_l, 1, 0)

        btn_c = QPushButton("🎯 CENTER")
        btn_c.setStyleSheet("background-color: #0277bd; color: white; font-weight: bold; font-size: 11px;")
        btn_c.clicked.connect(lambda: self._target_point(mid_x, mid_y))
        grid_5pt.addWidget(btn_c, 1, 1)

        btn_r = QPushButton("▶ Right")
        btn_r.clicked.connect(lambda: self._target_point(max_x, mid_y))
        grid_5pt.addWidget(btn_r, 1, 2)

        btn_bl = QPushButton("↙ Bottom-Left")
        btn_bl.clicked.connect(lambda: self._target_point(min_x, min_y))
        grid_5pt.addWidget(btn_bl, 2, 0)

        btn_bot = QPushButton("▼ Center-Bottom")
        btn_bot.clicked.connect(lambda: self._target_point(mid_x, min_y))
        grid_5pt.addWidget(btn_bot, 2, 1)

        btn_br = QPushButton("↘ Bottom-Right")
        btn_br.clicked.connect(lambda: self._target_point(max_x, min_y))
        grid_5pt.addWidget(btn_br, 2, 2)

        target_layout.addLayout(grid_5pt)

        # Targeting Laser Power Slider
        pwr_row = QHBoxLayout()
        pwr_row.addWidget(QLabel("Target Beam Power:"))
        self.slider_pwr = QSlider(Qt.Orientation.Horizontal)
        self.slider_pwr.setRange(2, 20)  # 0.2% to 2.0%
        self.slider_pwr.setValue(5)       # 0.5%
        self.slider_pwr.valueChanged.connect(self._on_pwr_slider_changed)
        pwr_row.addWidget(self.slider_pwr, 1)

        self.lbl_pwr_val = QLabel("0.5%")
        self.lbl_pwr_val.setFixedWidth(40)
        pwr_row.addWidget(self.lbl_pwr_val)

        self.btn_fire_toggle = QPushButton("Laser Dot ON")
        self.btn_fire_toggle.setCheckable(True)
        self.btn_fire_toggle.clicked.connect(self._toggle_fire)
        pwr_row.addWidget(self.btn_fire_toggle)
        target_layout.addLayout(pwr_row)

        # Continuous Framing Button
        self.btn_continuous_frame = QPushButton("⛶  Continuous Framing Loop (Low Power)")
        self.btn_continuous_frame.setCheckable(True)
        self.btn_continuous_frame.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_continuous_frame.setToolTip("Traces envelope repeatedly at low power while you position the workpiece")
        self.btn_continuous_frame.clicked.connect(self._toggle_continuous_framing)
        target_layout.addWidget(self.btn_continuous_frame)

        layout.addWidget(target_group)

        # 3. 2-Point Rotational & Positional Alignment ("Print & Cut")
        align_group = QGroupBox("2-Point Workpiece Alignment (Align to Crooked Material)")
        align_layout = QVBoxLayout(align_group)
        align_layout.setSpacing(6)

        align_desc = QLabel(
            "Jog the laser dot to two known corners of your physical card or workpiece. "
            "LaserForge will automatically rotate and shift your canvas design to match the exact physical position!"
        )
        align_desc.setWordWrap(True)
        align_desc.setStyleSheet("color: #b0bec5; font-size: 11px;")
        align_layout.addWidget(align_desc)

        pts_grid = QGridLayout()
        pts_grid.setSpacing(6)

        btn_cap1 = QPushButton("📍 1. Capture Point 1 (Top-Left)")
        btn_cap1.clicked.connect(self._capture_pt1)
        pts_grid.addWidget(btn_cap1, 0, 0)

        self.lbl_pt1 = QLabel("Pt 1: Not set")
        self.lbl_pt1.setStyleSheet("font-family: monospace; color: #80cbc4;")
        pts_grid.addWidget(self.lbl_pt1, 0, 1)

        btn_cap2 = QPushButton("📍 2. Capture Point 2 (Top-Right)")
        btn_cap2.clicked.connect(self._capture_pt2)
        pts_grid.addWidget(btn_cap2, 1, 0)

        self.lbl_pt2 = QLabel("Pt 2: Not set")
        self.lbl_pt2.setStyleSheet("font-family: monospace; color: #80cbc4;")
        pts_grid.addWidget(self.lbl_pt2, 1, 1)

        align_layout.addLayout(pts_grid)

        self.lbl_calc_result = QLabel("Measured Angle: --  |  Distance: --")
        self.lbl_calc_result.setStyleSheet("color: #ffca28; font-weight: bold; font-size: 11px;")
        align_layout.addWidget(self.lbl_calc_result)

        btn_apply_align = QPushButton("✨  Align Canvas Artwork to Measured Workpiece")
        btn_apply_align.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 8px; border-radius: 4px;"
        )
        btn_apply_align.clicked.connect(self._apply_2point_alignment)
        align_layout.addWidget(btn_apply_align)

        layout.addWidget(align_group)

        # 4. Corner Stop L-Bracket Jig Button
        jig_group = QGroupBox("Physical 90° Corner Stop Jig")
        jig_layout = QHBoxLayout(jig_group)
        jig_lbl = QLabel("Generate a laser-cut L-bracket corner stop on your wasteboard for 100% repeatable card placement:")
        jig_lbl.setWordWrap(True)
        jig_lbl.setStyleSheet("font-size: 11px; color: #cfd8dc;")
        jig_layout.addWidget(jig_lbl, 1)

        btn_gen_jig = QPushButton("📐 Place L-Jig on Canvas")
        btn_gen_jig.clicked.connect(self._generate_l_jig)
        jig_layout.addWidget(btn_gen_jig)

        layout.addWidget(jig_group)

        # Close Button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self._on_close)
        layout.addWidget(btn_close)

    def _connect_signals(self):
        self.serial_ctrl.status_updated.connect(self._on_status_updated)

    def _on_status_updated(self, status: dict):
        wpos = status.get("wpos", [0.0, 0.0, 0.0])
        self.current_pos = [wpos[0], wpos[1]]
        self.lbl_pos.setText(f"X: {wpos[0]:.2f} mm   Y: {wpos[1]:.2f} mm")

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

    def _target_point(self, target_x: float, target_y: float):
        """Jogs laser to the given coordinate and projects the low-power targeting beam."""
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Targeting", "Laser is not connected. Connect in the Laser panel first.")
            return

        pct = self.slider_pwr.value() / 10.0
        s_val = max(1, int(round((pct / 100.0) * 1000)))

        gcode_cmds = [
            "G90",
            f"G0 X{target_x:.3f} Y{target_y:.3f} F3000",
            f"M3 S{s_val}"
        ]
        self.serial_ctrl.send_command("\n".join(gcode_cmds))
        self.btn_fire_toggle.setChecked(True)
        self.btn_fire_toggle.setText("Laser Dot OFF")
        self.btn_fire_toggle.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")

    def _toggle_continuous_framing(self):
        checked = self.btn_continuous_frame.isChecked()
        if checked:
            if not self.serial_ctrl.is_connected:
                QMessageBox.warning(self, "Framing", "Laser is not connected.")
                self.btn_continuous_frame.setChecked(False)
                return

            min_x, min_y, max_x, max_y = self.bbox
            pct = self.slider_pwr.value() / 10.0
            s_val = max(1, int(round((pct / 100.0) * 1000)))

            # Build a 10-loop continuous framing sequence
            lines = ["G90", "G21", f"G0 X{min_x:.3f} Y{min_y:.3f} F3000", f"M3 S{s_val}"]
            for _ in range(8):
                lines.append(f"G1 X{max_x:.3f} Y{min_y:.3f} F2500")
                lines.append(f"G1 X{max_x:.3f} Y{max_y:.3f} F2500")
                lines.append(f"G1 X{min_x:.3f} Y{max_y:.3f} F2500")
                lines.append(f"G1 X{min_x:.3f} Y{min_y:.3f} F2500")
            lines.append("M5")

            self.btn_continuous_frame.setText("⏹ Stop Continuous Framing")
            self.btn_continuous_frame.setStyleSheet("background-color: #f57f17; color: white; font-weight: bold;")
            self.serial_ctrl.start_job("\n".join(lines))
        else:
            self.serial_ctrl.stop_streaming()
            self.btn_continuous_frame.setText("⛶  Continuous Framing Loop (Low Power)")
            self.btn_continuous_frame.setStyleSheet("font-weight: bold; padding: 6px;")

    def _capture_pt1(self):
        self.pt1 = (self.current_pos[0], self.current_pos[1])
        self.lbl_pt1.setText(f"X: {self.pt1[0]:.2f}, Y: {self.pt1[1]:.2f}")
        self._calculate_2point()

    def _capture_pt2(self):
        self.pt2 = (self.current_pos[0], self.current_pos[1])
        self.lbl_pt2.setText(f"X: {self.pt2[0]:.2f}, Y: {self.pt2[1]:.2f}")
        self._calculate_2point()

    def _calculate_2point(self):
        if not self.pt1 or not self.pt2:
            return

        dx = self.pt2[0] - self.pt1[0]
        dy = self.pt2[1] - self.pt1[1]
        dist = math.hypot(dx, dy)
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        min_x, min_y, max_x, max_y = self.bbox
        expected_w = max_x - min_x

        self.lbl_calc_result.setText(
            f"Measured Angle: {angle_deg:+.2f}°  |  Distance: {dist:.1f} mm (Expected: {expected_w:.1f} mm)"
        )

    def _apply_2point_alignment(self):
        if not self.pt1 or not self.pt2:
            QMessageBox.warning(self, "Alignment", "Please capture both Point 1 and Point 2 first.")
            return

        dx = self.pt2[0] - self.pt1[0]
        dy = self.pt2[1] - self.pt1[1]
        angle_deg = math.degrees(math.atan2(dy, dx))

        min_x, min_y, max_x, max_y = self.bbox
        shift_x = self.pt1[0] - min_x
        shift_y = self.pt1[1] - max_y

        self.align_canvas_requested.emit(angle_deg, shift_x, shift_y)
        QMessageBox.information(
            self, "Aligned",
            f"Canvas artwork rotated by {angle_deg:+.2f}° and shifted to X: {self.pt1[0]:.1f}, Y: {self.pt1[1]:.1f}!"
        )

    def _generate_l_jig(self):
        min_x, min_y, max_x, max_y = self.bbox
        w = max(40.0, max_x - min_x)
        h = max(30.0, max_y - min_y)
        self.generate_jig_requested.emit(w, h)
        QMessageBox.information(self, "L-Bracket Jig", "90° Alignment Corner Stop placed on canvas (Layer T1)!")

    def _on_close(self):
        if self.btn_fire_toggle.isChecked():
            self.serial_ctrl.toggle_test_laser(False)
        if self.btn_continuous_frame.isChecked():
            self.serial_ctrl.stop_streaming()
        self.accept()
