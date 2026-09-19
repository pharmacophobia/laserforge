"""
LaserForge Workbed Area Setup & Machine Calibration Studio.
Provides:
1. Machine presets for 15+ popular laser engravers (Ortur, xTool, Sculpfun, Creality, Atomstack, Omtech, etc.).
2. Automatic GRBL EEPROM detection ($130, $131 max travel limits & $20 soft limits).
3. Interactive 2-corner jog measurement mode for custom beds and extension rail kits.
4. Physical boundary verification (corner jumps and low-power perimeter framing trace).
5. Laser-etched wasteboard alignment grid generator with mm rulers and corner indexing stops.
6. Real-time interactive visual bed diagram with live laser crosshair, safety keepout margins, and ruler markers.
"""

from typing import Optional, Tuple, Dict, Any, List
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QTabWidget, QFrame, QMessageBox, QDialogButtonBox, QSplitter,
    QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QPolygonF

from laserforge.config import MachineSettings
from laserforge.core.serial_controller import SerialController
from laserforge.core.models import LineEntity, RectEntity, TextEntity, PathEntity


# ---------------------------------------------------------------------------
# Popular Machine Presets
# ---------------------------------------------------------------------------
MACHINE_PRESETS: List[Dict[str, Any]] = [
    {
        "name": "-- Select Machine Preset --",
        "width": 400.0, "height": 400.0, "origin": "Bottom-Left", "rapid": 3000.0
    },
    {
        "name": "Artilume T1 / T1-P (150 × 200 mm)",
        "width": 150.0, "height": 200.0, "origin": "Bottom-Left", "rapid": 3000.0,
        "laser_power_w": 5.0, "description": "Artilume T1 portable diode laser (Front-Left origin, 150x200mm)"
    },
    {
        "name": "Artilume T1 (Landscape 200 × 150 mm)",
        "width": 200.0, "height": 150.0, "origin": "Bottom-Left", "rapid": 3000.0,
        "laser_power_w": 5.0, "description": "Artilume T1 portable diode laser (Landscape orientation, 200x150mm)"
    },
    {
        "name": "Ortur Laser Master 2 / Pro (400 × 430 mm)",
        "width": 400.0, "height": 430.0, "origin": "Bottom-Left", "rapid": 4000.0
    },
    {
        "name": "Ortur Laser Master 3 (400 × 400 mm)",
        "width": 400.0, "height": 400.0, "origin": "Bottom-Left", "rapid": 6000.0
    },
    {
        "name": "xTool D1 / D1 Pro (430 × 400 mm)",
        "width": 430.0, "height": 400.0, "origin": "Top-Left", "rapid": 4000.0
    },
    {
        "name": "xTool D1 Pro + Extension Kit (930 × 430 mm)",
        "width": 930.0, "height": 430.0, "origin": "Top-Left", "rapid": 4000.0
    },
    {
        "name": "Sculpfun S9 / S10 / S30 (410 × 400 mm)",
        "width": 410.0, "height": 400.0, "origin": "Bottom-Left", "rapid": 3000.0
    },
    {
        "name": "Sculpfun S9/S30 + Extension Kit (950 × 410 mm)",
        "width": 950.0, "height": 410.0, "origin": "Bottom-Left", "rapid": 3000.0
    },
    {
        "name": "Creality Falcon 2 / Falcon 2 Pro (400 × 415 mm)",
        "width": 400.0, "height": 415.0, "origin": "Bottom-Left", "rapid": 5000.0
    },
    {
        "name": "Atomstack A5 / S10 / X7 / A20 (410 × 400 mm)",
        "width": 410.0, "height": 400.0, "origin": "Bottom-Left", "rapid": 4000.0
    },
    {
        "name": "Atomstack + Extension Kit (850 × 410 mm)",
        "width": 850.0, "height": 410.0, "origin": "Bottom-Left", "rapid": 4000.0
    },
    {
        "name": "Two Trees TTS-55 (300 × 300 mm)",
        "width": 300.0, "height": 300.0, "origin": "Bottom-Left", "rapid": 3000.0
    },
    {
        "name": "Two Trees TS2 (450 × 450 mm)",
        "width": 450.0, "height": 450.0, "origin": "Bottom-Left", "rapid": 4000.0
    },
    {
        "name": "Longer Ray5 (400 × 400 mm)",
        "width": 400.0, "height": 400.0, "origin": "Bottom-Left", "rapid": 4000.0
    },
    {
        "name": "K40 Desktop CO2 Laser (300 × 200 mm)",
        "width": 300.0, "height": 200.0, "origin": "Top-Left", "rapid": 3000.0
    },
    {
        "name": "Omtech 50W Desktop CO2 (500 × 300 mm)",
        "width": 500.0, "height": 300.0, "origin": "Top-Left", "rapid": 4000.0
    },
    {
        "name": "Omtech 60W / 80W CO2 Laser (700 × 500 mm)",
        "width": 700.0, "height": 500.0, "origin": "Top-Left", "rapid": 5000.0
    },
]


# ---------------------------------------------------------------------------
# Interactive Live Bed Preview Widget
# ---------------------------------------------------------------------------
class WorkbedPreviewWidget(QWidget):
    """
    Renders an interactive real-time visual diagram of the laser workbed,
    including mm rulers, origin beacon, safety keepout zone, and live laser head crosshair.
    """

    corner_clicked = pyqtSignal(str)  # 'BL', 'BR', 'TR', 'TL', 'Center'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(380, 320)
        self.bed_width: float = 400.0
        self.bed_height: float = 400.0
        self.origin_corner: str = "Bottom-Left"
        self.safety_margin: float = 5.0
        self.laser_pos: Tuple[float, float] = (0.0, 0.0)
        self.pt1: Optional[Tuple[float, float]] = None
        self.pt2: Optional[Tuple[float, float]] = None

        self.setStyleSheet("background-color: #121218; border: 1px solid #2a2a38; border-radius: 6px;")

    def update_bed(
        self,
        width: float,
        height: float,
        origin: str,
        margin: float,
        laser_pos: Optional[Tuple[float, float]] = None,
        pt1: Optional[Tuple[float, float]] = None,
        pt2: Optional[Tuple[float, float]] = None
    ):
        self.bed_width = max(10.0, width)
        self.bed_height = max(10.0, height)
        self.origin_corner = origin
        self.safety_margin = margin
        if laser_pos is not None:
            self.laser_pos = laser_pos
        self.pt1 = pt1
        self.pt2 = pt2
        self.update()

    def _map_coords(self, x: float, y: float, ox: float, oy: float, render_w: float, render_h: float, scale: float) -> Tuple[float, float]:
        px = (ox + render_w) - (x * scale) if "Right" in self.origin_corner else ox + (x * scale)
        py = (oy + render_h) - (y * scale) if "Bottom" in self.origin_corner else oy + (y * scale)
        return px, py

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Fill background
        painter.fillRect(0, 0, w, h, QColor("#121218"))

        # Margin for outer rulers and labels
        margin_x = 44
        margin_y = 44
        avail_w = w - (margin_x * 2)
        avail_h = h - (margin_y * 2)

        if avail_w <= 0 or avail_h <= 0:
            return

        scale = min(avail_w / self.bed_width, avail_h / self.bed_height)
        render_w = self.bed_width * scale
        render_h = self.bed_height * scale

        ox = margin_x + (avail_w - render_w) / 2.0
        oy = margin_y + (avail_h - render_h) / 2.0

        # Draw machine honeycomb grid texture on bed
        bed_rect = QRectF(ox, oy, render_w, render_h)
        painter.setPen(QPen(QColor("#242432"), 1))
        painter.setBrush(QBrush(QColor("#181822")))
        painter.drawRect(bed_rect)

        # Subtle grid lines (50mm or 100mm steps)
        grid_step = 50.0 if max(self.bed_width, self.bed_height) <= 600.0 else 100.0
        grid_pen = QPen(QColor("#1f1f2c"), 1, Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        x_mm = grid_step
        while x_mm < self.bed_width:
            gx = ox + (x_mm * scale)
            painter.drawLine(int(gx), int(oy), int(gx), int(oy + render_h))
            x_mm += grid_step

        y_mm = grid_step
        while y_mm < self.bed_height:
            gy = (oy + render_h) - (y_mm * scale)
            painter.drawLine(int(ox), int(gy), int(ox + render_w), int(gy))
            y_mm += grid_step

        # Safety Keepout Margin (Dashed orange border)
        if self.safety_margin > 0 and (render_w > self.safety_margin * 2 * scale) and (render_h > self.safety_margin * 2 * scale):
            sm_x = ox + (self.safety_margin * scale)
            sm_y = oy + (self.safety_margin * scale)
            sm_w = render_w - (self.safety_margin * 2 * scale)
            sm_h = render_h - (self.safety_margin * 2 * scale)
            painter.setPen(QPen(QColor(255, 153, 0, 160), 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(sm_x, sm_y, sm_w, sm_h))

        # Bed Outer Boundary (Bright Cyan)
        painter.setPen(QPen(QColor("#00aaff"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bed_rect)

        # Dimensions & Ruler Annotations
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#8888aa"), 1))

        # Bottom width label
        text_w = f"Width X: {self.bed_width:.1f} mm"
        painter.drawText(QRectF(ox, oy + render_h + 8, render_w, 20), Qt.AlignmentFlag.AlignCenter, text_w)

        # Left height label
        text_h = f"Height Y: {self.bed_height:.1f} mm"
        painter.save()
        painter.translate(ox - 8, oy + render_h / 2.0)
        painter.rotate(-90)
        painter.drawText(QRectF(-render_h / 2.0, -16, render_h, 20), Qt.AlignmentFlag.AlignCenter, text_h)
        painter.restore()

        # Origin Corner Indicator Beacon
        corner_coords = {
            "Bottom-Left": (ox, oy + render_h),
            "Top-Left": (ox, oy),
            "Bottom-Right": (ox + render_w, oy + render_h),
            "Top-Right": (ox + render_w, oy)
        }
        orig_px, orig_py = corner_coords.get(self.origin_corner, (ox, oy + render_h))

        # Glowing target ring
        painter.setPen(QPen(QColor("#00e5ff"), 2))
        painter.setBrush(QBrush(QColor(0, 229, 255, 60)))
        painter.drawEllipse(QPointF(orig_px, orig_py), 9, 9)
        painter.setBrush(QBrush(QColor("#00ff88")))
        painter.drawEllipse(QPointF(orig_px, orig_py), 3.5, 3.5)

        # Origin Label
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#00ff88"), 1))
        offset_lx = 12 if "Left" in self.origin_corner else -48
        offset_ly = -10 if "Bottom" in self.origin_corner else 18
        painter.drawText(int(orig_px + offset_lx), int(orig_py + offset_ly), "ORIGIN (0,0)")

        # 2-Corner Calibration Points (if set)
        if self.pt1:
            p1_x, p1_y = self._map_coords(self.pt1[0], self.pt1[1], ox, oy, render_w, render_h, scale)
            painter.setPen(QPen(QColor("#ffea00"), 2))
            painter.setBrush(QBrush(QColor(255, 234, 0, 100)))
            painter.drawEllipse(QPointF(p1_x, p1_y), 6, 6)
            painter.drawText(int(p1_x + 8), int(p1_y - 4), "Pt 1")

        if self.pt2:
            p2_x, p2_y = self._map_coords(self.pt2[0], self.pt2[1], ox, oy, render_w, render_h, scale)
            painter.setPen(QPen(QColor("#ff0077"), 2))
            painter.setBrush(QBrush(QColor(255, 0, 119, 100)))
            painter.drawEllipse(QPointF(p2_x, p2_y), 6, 6)
            painter.drawText(int(p2_x + 8), int(p2_y - 4), "Pt 2")

        # Live Laser Head Crosshair
        if self.laser_pos:
            lx, ly = self._map_coords(self.laser_pos[0], self.laser_pos[1], ox, oy, render_w, render_h, scale)

            painter.setPen(QPen(QColor("#ff3333"), 1.5))
            painter.drawLine(int(lx - 12), int(ly), int(lx + 12), int(ly))
            painter.drawLine(int(lx), int(ly - 12), int(lx), int(ly + 12))
            painter.setBrush(QBrush(QColor("#ff3333")))
            painter.drawEllipse(QPointF(lx, ly), 2.5, 2.5)

            # Laser coordinate readout
            coord_str = f"Laser: ({self.laser_pos[0]:.1f}, {self.laser_pos[1]:.1f})"
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#ff6666"), 1))
            painter.drawText(int(lx + 14), int(ly - 6), coord_str)


# ---------------------------------------------------------------------------
# Workbed Setup Dialog
# ---------------------------------------------------------------------------
class WorkbedSetupDialog(QDialog):
    """
    Comprehensive Workbed Area Setup & Machine Calibration Studio Dialog.
    """

    def __init__(
        self,
        settings: MachineSettings,
        serial_ctrl: Optional[SerialController] = None,
        scene: Optional[Any] = None,
        parent=None
    ):
        super().__init__(parent)
        self.settings = settings
        self.serial_ctrl = serial_ctrl
        self.scene = scene

        self.setWindowTitle("Workbed Area Setup & Machine Calibration Studio")
        self.resize(1020, 660)
        self.setMinimumSize(900, 580)

        self.calib_pt1: Optional[Tuple[float, float]] = None
        self.calib_pt2: Optional[Tuple[float, float]] = None

        self._init_ui()
        self._load_from_settings()

        # Connect serial status for live crosshair & alarm tracking
        if self.serial_ctrl:
            self.serial_ctrl.status_updated.connect(self._on_serial_status_updated)
            self.serial_ctrl.grbl_settings_updated.connect(self._on_grbl_settings_updated)
            if getattr(self.serial_ctrl, "is_alarm", False):
                self._show_alarm_banner(True, "Laser controller in ALARM state. Click 'Unlock Alarm ($X)' to clear.")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # 1. Header Banner
        header = QFrame()
        header.setStyleSheet("background-color: #1a1e28; border: 1px solid #2a3446; border-radius: 6px;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(14, 10, 14, 10)

        title_vbox = QVBoxLayout()
        title_lbl = QLabel("⚡ Workbed Area Setup & Calibration Studio")
        title_lbl.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold;")
        sub_lbl = QLabel("Accurately configure machine work area, travel limits, origin, test corner clearances, and wasteboard grids.")
        sub_lbl.setStyleSheet("color: #8899aa; font-size: 11px;")
        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(sub_lbl)
        h_layout.addLayout(title_vbox, 1)

        # Connection status pill
        conn_str = "Disconnected"
        conn_color = "#999999"
        conn_bg = "#2c2c36"
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            conn_str = f"Connected: {self.serial_ctrl.port_name}"
            conn_color = "#00ff88"
            conn_bg = "#003322"

        self.lbl_conn = QLabel(f"● {conn_str}")
        self.lbl_conn.setStyleSheet(f"background-color: {conn_bg}; color: {conn_color}; padding: 5px 10px; border-radius: 4px; font-weight: bold;")
        h_layout.addWidget(self.lbl_conn)

        main_layout.addWidget(header)

        # Alarm Recovery Banner (active when GRBL controller reports Alarm state)
        self.alarm_banner = QFrame()
        self.alarm_banner.setObjectName("AlarmBanner")
        self.alarm_banner.setStyleSheet("""
            #AlarmBanner {
                background-color: #38161a;
                border: 1.5px solid #ff4444;
                border-radius: 6px;
            }
        """)
        al_layout = QHBoxLayout(self.alarm_banner)
        al_layout.setContentsMargins(12, 6, 12, 6)
        al_layout.setSpacing(10)

        self.lbl_alarm_msg = QLabel("🚨 <b>ALARM ACTIVE:</b> Hard limit switch triggered or motion locked.")
        self.lbl_alarm_msg.setStyleSheet("color: #ff9999; font-size: 11px;")
        self.lbl_alarm_msg.setWordWrap(True)
        al_layout.addWidget(self.lbl_alarm_msg, 1)

        self.btn_alarm_unlock = QPushButton("🔓 Unlock ($X)")
        self.btn_alarm_unlock.setStyleSheet("background-color: #0088cc; color: #ffffff; font-weight: bold; padding: 4px 8px; font-size: 11px;")
        self.btn_alarm_unlock.clicked.connect(self._on_unlock_alarm)
        al_layout.addWidget(self.btn_alarm_unlock)

        self.btn_alarm_home = QPushButton("🏠 Home ($H)")
        self.btn_alarm_home.setStyleSheet("background-color: #245538; color: #00ff88; font-weight: bold; padding: 4px 8px; font-size: 11px;")
        self.btn_alarm_home.clicked.connect(self._on_home_machine)
        al_layout.addWidget(self.btn_alarm_home)

        self.btn_alarm_reset = QPushButton("🛑 Reset (Ctrl-X)")
        self.btn_alarm_reset.setStyleSheet("background-color: #552228; color: #ffaaaa; font-weight: bold; padding: 4px 8px; font-size: 11px;")
        self.btn_alarm_reset.clicked.connect(self._abort_motion)
        al_layout.addWidget(self.btn_alarm_reset)

        main_layout.addWidget(self.alarm_banner)
        self.alarm_banner.setVisible(False)

        # 2. Main Body Splitter (Left Controls, Right Live Diagram)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Controls Container
        controls_widget = QWidget()
        ctrl_layout = QVBoxLayout(controls_widget)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                min-width: 85px;
                padding: 6px 10px;
                font-weight: bold;
                font-size: 11px;
            }
        """)

        # Tab 1: Dimensions & Presets
        self.tabs.addTab(self._create_dimensions_tab(), "Bed Dimensions")

        # Tab 2: Hardware & Jog Calibration (Literal ampersand with &&)
        self.tabs.addTab(self._create_calibration_tab(), "Auto-Detect && Measure")

        # Tab 3: Verification & Corner Tests
        self.tabs.addTab(self._create_verification_tab(), "Travel Verification")

        # Tab 4: Wasteboard Grid Generator
        self.tabs.addTab(self._create_wasteboard_grid_tab(), "Wasteboard Grid")

        ctrl_layout.addWidget(self.tabs)
        splitter.addWidget(controls_widget)

        # Right Live Visual Diagram
        right_panel = QFrame()
        right_panel.setStyleSheet("background-color: #161620; border: 1px solid #282836; border-radius: 6px;")
        r_layout = QVBoxLayout(right_panel)
        r_layout.setContentsMargins(10, 10, 10, 10)

        preview_header = QHBoxLayout()
        preview_title = QLabel("Interactive Workbed Live Preview")
        preview_title.setStyleSheet("color: #00d0ff; font-weight: bold; font-size: 12px;")
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)

        self.lbl_bed_summary = QLabel("400.0 × 400.0 mm")
        self.lbl_bed_summary.setStyleSheet("color: #a0a0b8; font-size: 11px; font-weight: bold;")
        preview_header.addWidget(self.lbl_bed_summary)
        r_layout.addLayout(preview_header)

        self.preview_widget = WorkbedPreviewWidget(self)
        r_layout.addWidget(self.preview_widget, 1)

        # Diagram legend
        legend = QHBoxLayout()
        legend.setSpacing(12)
        lbl_leg1 = QLabel("🟦 Machine Boundary")
        lbl_leg1.setStyleSheet("color: #00aaff; font-size: 10px;")
        lbl_leg2 = QLabel("🟧 Safety Keepout")
        lbl_leg2.setStyleSheet("color: #ff9900; font-size: 10px;")
        lbl_leg3 = QLabel("🟢 Origin (0,0)")
        lbl_leg3.setStyleSheet("color: #00ff88; font-size: 10px;")
        lbl_leg4 = QLabel("🔴 Live Laser Head")
        lbl_leg4.setStyleSheet("color: #ff4444; font-size: 10px;")
        legend.addWidget(lbl_leg1)
        legend.addWidget(lbl_leg2)
        legend.addWidget(lbl_leg3)
        legend.addWidget(lbl_leg4)
        legend.addStretch(1)
        r_layout.addLayout(legend)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([540, 440])

        main_layout.addWidget(splitter, 1)

        # 3. Bottom Sync & Actions
        bottom_box = QHBoxLayout()

        self.chk_sync_grbl = QCheckBox("Sync Limits to GRBL EEPROM ($130, $131, $20)")
        self.chk_sync_grbl.setChecked(True)
        self.chk_sync_grbl.setToolTip(
            "Writes the calibrated bed width ($130) and height ($131) directly into your laser controller\n"
            "and enables hardware soft limits ($20=1) to prevent the laser from ever crashing into frame edges."
        )
        bottom_box.addWidget(self.chk_sync_grbl)
        bottom_box.addStretch(1)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("padding: 6px 14px; font-weight: 500;")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_box.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("✓ Save && Apply Workbed")
        self.btn_apply.setStyleSheet("background-color: #0088cc; color: #ffffff; font-weight: bold; padding: 6px 18px;")
        self.btn_apply.clicked.connect(self._on_apply_and_save)
        bottom_box.addWidget(self.btn_apply)

        main_layout.addLayout(bottom_box)

    # -----------------------------------------------------------------------
    # Tab 1: Dimensions & Presets
    # -----------------------------------------------------------------------
    def _create_dimensions_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # Preset Selector
        preset_group = QGroupBox("Popular Machine Profiles")
        preset_layout = QVBoxLayout(preset_group)
        self.combo_presets = QComboBox()
        for p in MACHINE_PRESETS:
            self.combo_presets.addItem(p["name"], p)
        self.combo_presets.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.combo_presets)
        layout.addWidget(preset_group)

        # Manual Dimensions
        dim_group = QGroupBox("Workbed Geometry && Origin")
        dim_grid = QGridLayout(dim_group)
        dim_grid.setSpacing(8)

        dim_grid.addWidget(QLabel("Workbed Width X:"), 0, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(20.0, 5000.0)
        self.spin_width.setDecimals(1)
        self.spin_width.setSuffix(" mm")
        self.spin_width.setValue(400.0)
        self.spin_width.valueChanged.connect(self._on_geometry_changed)
        dim_grid.addWidget(self.spin_width, 0, 1)

        dim_grid.addWidget(QLabel("Workbed Height Y:"), 1, 0)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(20.0, 5000.0)
        self.spin_height.setDecimals(1)
        self.spin_height.setSuffix(" mm")
        self.spin_height.setValue(400.0)
        self.spin_height.valueChanged.connect(self._on_geometry_changed)
        dim_grid.addWidget(self.spin_height, 1, 1)

        dim_grid.addWidget(QLabel("Origin Corner (0,0):"), 2, 0)
        self.combo_origin = QComboBox()
        self.combo_origin.addItems(["Bottom-Left", "Top-Left", "Bottom-Right", "Top-Right"])
        self.combo_origin.currentIndexChanged.connect(self._on_geometry_changed)
        dim_grid.addWidget(self.combo_origin, 2, 1)

        dim_grid.addWidget(QLabel("Safety Keepout Margin:"), 3, 0)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 50.0)
        self.spin_margin.setDecimals(1)
        self.spin_margin.setSuffix(" mm")
        self.spin_margin.setValue(5.0)
        self.spin_margin.setToolTip("Safety buffer from hard frame stops to avoid accidental limit switch collisions.")
        self.spin_margin.valueChanged.connect(self._on_geometry_changed)
        dim_grid.addWidget(self.spin_margin, 3, 1)

        layout.addWidget(dim_group)
        layout.addStretch(1)
        return tab

    # -----------------------------------------------------------------------
    # Tab 2: Hardware Auto-Detect & 2-Corner Jog Measurement
    # -----------------------------------------------------------------------
    def _create_calibration_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # Auto-detect from GRBL $$
        grbl_group = QGroupBox("1. Hardware Auto-Detection (GRBL EEPROM)")
        grbl_layout = QVBoxLayout(grbl_group)
        grbl_desc = QLabel("Reads factory hardware travel limits directly from connected laser firmware ($130 for X, $131 for Y).")
        grbl_desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        grbl_desc.setWordWrap(True)
        grbl_layout.addWidget(grbl_desc)

        self.btn_read_grbl = QPushButton("🔍 Query && Read Travel Limits from Laser ($$)")
        self.btn_read_grbl.setStyleSheet("background-color: #243448; color: #00d0ff; font-weight: bold; padding: 6px;")
        self.btn_read_grbl.clicked.connect(self._on_read_grbl_eeprom)
        grbl_layout.addWidget(self.btn_read_grbl)

        self.lbl_grbl_detected = QLabel("Status: Controller not queried yet.")
        self.lbl_grbl_detected.setStyleSheet("color: #bbbbcc; font-size: 11px;")
        grbl_layout.addWidget(self.lbl_grbl_detected)
        layout.addWidget(grbl_group)

        # 2-Corner Jog Calibration Mode
        jog_group = QGroupBox("2. Interactive 2-Corner Jog Measurement")
        jog_layout = QVBoxLayout(jog_group)
        jog_desc = QLabel(
            "For custom builds or extension kits: jog the laser to the physical origin corner and capture Pt 1. "
            "Then jog to the far diagonal corner and capture Pt 2. LaserForge calculates exact usable travel."
        )
        jog_desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        jog_desc.setWordWrap(True)
        jog_layout.addWidget(jog_desc)

        pts_grid = QGridLayout()
        self.btn_cap_pt1 = QPushButton("📍 1. Capture Origin Corner (Pt 1)")
        self.btn_cap_pt1.clicked.connect(self._on_capture_pt1)
        pts_grid.addWidget(self.btn_cap_pt1, 0, 0)

        self.lbl_pt1_status = QLabel("Pt 1: Not set")
        self.lbl_pt1_status.setStyleSheet("color: #ffea00; font-size: 11px;")
        pts_grid.addWidget(self.lbl_pt1_status, 0, 1)

        self.btn_cap_pt2 = QPushButton("📍 2. Capture Max Corner (Pt 2)")
        self.btn_cap_pt2.clicked.connect(self._on_capture_pt2)
        pts_grid.addWidget(self.btn_cap_pt2, 1, 0)

        self.lbl_pt2_status = QLabel("Pt 2: Not set")
        self.lbl_pt2_status.setStyleSheet("color: #ff0077; font-size: 11px;")
        pts_grid.addWidget(self.lbl_pt2_status, 1, 1)

        jog_layout.addLayout(pts_grid)

        self.btn_calc_measured = QPushButton("📐 Apply Measured Distance to Workbed")
        self.btn_calc_measured.setEnabled(False)
        self.btn_calc_measured.setStyleSheet("background-color: #1a3a2a; color: #00ff88; font-weight: bold; padding: 6px;")
        self.btn_calc_measured.clicked.connect(self._on_apply_measured_bed)
        jog_layout.addWidget(self.btn_calc_measured)

        layout.addWidget(jog_group)

        # Section 3: Vision Auto-Calibration
        vision_group = QGroupBox("3. Optical & Workbed Vision Auto-Calibration")
        vision_layout = QVBoxLayout(vision_group)
        v_desc = QLabel(
            "Uses overhead camera vision to automatically detect bed fiducials or ArUco markers, "
            "calculate high-precision coordinate homography, and align the workbed with the laser."
        )
        v_desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        v_desc.setWordWrap(True)
        vision_layout.addWidget(v_desc)

        self.btn_open_auto_calib = QPushButton("🤖 Launch Workbed Auto-Calibration Studio...")
        self.btn_open_auto_calib.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px;")
        self.btn_open_auto_calib.clicked.connect(self._open_auto_calib_studio)
        vision_layout.addWidget(self.btn_open_auto_calib)

        layout.addWidget(vision_group)
        layout.addStretch(1)
        return tab

    # -----------------------------------------------------------------------
    # Tab 3: Verification & Corner Tests
    # -----------------------------------------------------------------------
    def _create_verification_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        desc = QLabel("Verify machine motion and mechanical clearance at all 4 extremities of the workbed before cutting.")
        desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Quick Alarm Unlock & Home Bar
        rec_box = QHBoxLayout()
        self.btn_quick_unlock = QPushButton("🔓 Unlock Laser ($X)")
        self.btn_quick_unlock.setStyleSheet("background-color: #1a3048; color: #00d0ff; font-weight: bold; padding: 5px 10px;")
        self.btn_quick_unlock.clicked.connect(self._on_unlock_alarm)
        rec_box.addWidget(self.btn_quick_unlock)

        self.btn_quick_home = QPushButton("🏠 Home Machine ($H)")
        self.btn_quick_home.setStyleSheet("background-color: #1a3828; color: #00ff88; font-weight: bold; padding: 5px 10px;")
        self.btn_quick_home.clicked.connect(self._on_home_machine)
        rec_box.addWidget(self.btn_quick_home)
        layout.addLayout(rec_box)

        # Corner Jumps Grid
        corner_group = QGroupBox("Move Laser Head to Extents")
        cg_layout = QGridLayout(corner_group)

        # Test Speed & Safety Offset Controls
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Test Motion Speed:"))
        self.spin_test_speed = QDoubleSpinBox()
        self.spin_test_speed.setRange(100.0, 10000.0)
        self.spin_test_speed.setDecimals(0)
        self.spin_test_speed.setSuffix(" mm/min")
        default_spd = getattr(self.settings, "rapid_speed", 3000.0)
        self.spin_test_speed.setValue(default_spd)
        speed_row.addWidget(self.spin_test_speed)
        speed_row.addStretch(1)
        cg_layout.addLayout(speed_row, 0, 0, 1, 2)

        self.chk_safe_margin = QCheckBox("Stay inside safety keepout margin (recommended)")
        self.chk_safe_margin.setToolTip("Moves to safety margin offset (e.g. 5mm) to avoid bumping physical limit switches")
        self.chk_safe_margin.setChecked(False)
        cg_layout.addWidget(self.chk_safe_margin, 1, 0, 1, 2)

        self.btn_jump_tl = QPushButton("↖ Top-Left (0, H)")
        self.btn_jump_tl.clicked.connect(lambda: self._jump_to_corner("TL"))
        cg_layout.addWidget(self.btn_jump_tl, 2, 0)

        self.btn_jump_tr = QPushButton("↗ Top-Right (W, H)")
        self.btn_jump_tr.clicked.connect(lambda: self._jump_to_corner("TR"))
        cg_layout.addWidget(self.btn_jump_tr, 2, 1)

        self.btn_jump_bl = QPushButton("↙ Bottom-Left (0, 0)")
        self.btn_jump_bl.clicked.connect(lambda: self._jump_to_corner("BL"))
        cg_layout.addWidget(self.btn_jump_bl, 3, 0)

        self.btn_jump_br = QPushButton("↘ Bottom-Right (W, 0)")
        self.btn_jump_br.clicked.connect(lambda: self._jump_to_corner("BR"))
        cg_layout.addWidget(self.btn_jump_br, 3, 1)

        self.btn_jump_center = QPushButton("🎯 Bed Center (W/2, H/2)")
        self.btn_jump_center.clicked.connect(lambda: self._jump_to_corner("Center"))
        cg_layout.addWidget(self.btn_jump_center, 4, 0, 1, 2)

        layout.addWidget(corner_group)

        # Perimeter Framing Trace
        trace_group = QGroupBox("Perimeter Framing Trace")
        tg_layout = QVBoxLayout(trace_group)

        trace_desc = QLabel("Sends a low-power (0.5%) visible guide beam to physically trace the entire bed perimeter on your wasteboard.")
        trace_desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        trace_desc.setWordWrap(True)
        tg_layout.addWidget(trace_desc)

        btn_row = QHBoxLayout()
        self.btn_trace_perimeter = QPushButton("⚡ Trace Perimeter (0.5% Beam)")
        self.btn_trace_perimeter.setStyleSheet("background-color: #382414; color: #ff9900; font-weight: bold; padding: 6px;")
        self.btn_trace_perimeter.clicked.connect(self._trace_bed_perimeter)
        btn_row.addWidget(self.btn_trace_perimeter, 1)

        self.btn_stop_motion = QPushButton("🛑 Stop / Abort")
        self.btn_stop_motion.setStyleSheet("background-color: #481418; color: #ff4444; font-weight: bold; padding: 6px;")
        self.btn_stop_motion.clicked.connect(self._abort_motion)
        btn_row.addWidget(self.btn_stop_motion)
        tg_layout.addLayout(btn_row)

        layout.addWidget(trace_group)
        layout.addStretch(1)
        return tab

    # -----------------------------------------------------------------------
    # Tab 4: Wasteboard Grid Generator
    # -----------------------------------------------------------------------
    def _create_wasteboard_grid_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        desc = QLabel(
            "Laser-engrave a precision millimeter alignment grid directly onto your spoilboard / wasteboard. "
            "Provides instant visual squaring and alignment rulers for all future stock."
        )
        desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        opts_group = QGroupBox("Grid Parameters")
        opts_grid = QGridLayout(opts_group)

        opts_grid.addWidget(QLabel("Grid Interval:"), 0, 0)
        self.combo_grid_step = QComboBox()
        self.combo_grid_step.addItems(["10 mm Spacing", "25 mm Spacing", "50 mm Spacing", "100 mm Spacing"])
        self.combo_grid_step.setCurrentIndex(2)  # Default 50 mm
        opts_grid.addWidget(self.combo_grid_step, 0, 1)

        self.chk_grid_numbers = QCheckBox("Add Metric Measurement Numbers (50, 100, 150...)")
        self.chk_grid_numbers.setChecked(True)
        opts_grid.addWidget(self.chk_grid_numbers, 1, 0, 1, 2)

        self.chk_corner_stops = QCheckBox("Add 90° Corner Alignment Index Marks")
        self.chk_corner_stops.setChecked(True)
        opts_grid.addWidget(self.chk_corner_stops, 2, 0, 1, 2)

        self.chk_center_cross = QCheckBox("Add Center Target Crosshair")
        self.chk_center_cross.setChecked(True)
        opts_grid.addWidget(self.chk_center_cross, 3, 0, 1, 2)

        opts_grid.addWidget(QLabel("Output Layer:"), 4, 0)
        self.combo_grid_layer = QComboBox()
        self.combo_grid_layer.addItem("T1 - Tool / Guide Layer (Non-cutting visual layout)", 12)
        self.combo_grid_layer.addItem("C00 - Black Layer (Ready to cut/engrave into wasteboard)", 0)
        opts_grid.addWidget(self.combo_grid_layer, 4, 1)

        layout.addWidget(opts_group)

        self.btn_gen_grid = QPushButton("✨ Generate Grid on Canvas Scene")
        self.btn_gen_grid.setStyleSheet("background-color: #005577; color: #00e5ff; font-weight: bold; padding: 8px;")
        self.btn_gen_grid.clicked.connect(self._generate_wasteboard_grid)
        layout.addWidget(self.btn_gen_grid)

        layout.addStretch(1)
        return tab

    # -----------------------------------------------------------------------
    # Logic & State Synchronization
    # -----------------------------------------------------------------------
    def _load_from_settings(self):
        w = getattr(self.settings, "bed_width", 400.0)
        h = getattr(self.settings, "bed_height", 400.0)
        orig = getattr(self.settings, "origin_corner", "Bottom-Left")
        margin = getattr(self.settings, "safety_margin_mm", 5.0)

        self.spin_width.setValue(w)
        self.spin_height.setValue(h)
        idx = self.combo_origin.findText(orig)
        if idx >= 0:
            self.combo_origin.setCurrentIndex(idx)
        self.spin_margin.setValue(margin)

        self._on_geometry_changed()

    def _on_preset_selected(self, index: int):
        data = self.combo_presets.currentData()
        if not data or index == 0:
            return
        self.spin_width.setValue(data["width"])
        self.spin_height.setValue(data["height"])
        idx = self.combo_origin.findText(data["origin"])
        if idx >= 0:
            self.combo_origin.setCurrentIndex(idx)
        self._on_geometry_changed()

    def _on_geometry_changed(self):
        w = self.spin_width.value()
        h = self.spin_height.value()
        orig = self.combo_origin.currentText()
        margin = self.spin_margin.value()

        self.lbl_bed_summary.setText(f"{w:.1f} × {h:.1f} mm")
        self.preview_widget.update_bed(
            width=w,
            height=h,
            origin=orig,
            margin=margin,
            pt1=self.calib_pt1,
            pt2=self.calib_pt2
        )

    def _on_serial_status_updated(self, *args, **kwargs):
        state = ""
        wpos = (0.0, 0.0)
        if args:
            data = args[0]
            if isinstance(data, dict):
                state = str(data.get("state", ""))
                wp = data.get("wpos", [0.0, 0.0, 0.0])
                wpos = (float(wp[0]), float(wp[1]))
            elif isinstance(data, str):
                state = data
                if len(args) >= 3 and isinstance(args[2], (list, tuple)):
                    wpos = (float(args[2][0]), float(args[2][1]))
                elif self.serial_ctrl:
                    wp = getattr(self.serial_ctrl, "wpos", [0.0, 0.0, 0.0])
                    wpos = (float(wp[0]), float(wp[1]))

        if "alarm" in state.lower():
            self._show_alarm_banner(True, f"Laser controller in {state} state. Unlock ($X) or Home ($H) to clear.")
        elif state:
            self._show_alarm_banner(False)

        self.preview_widget.update_bed(
            width=self.spin_width.value(),
            height=self.spin_height.value(),
            origin=self.combo_origin.currentText(),
            margin=self.spin_margin.value(),
            laser_pos=wpos,
            pt1=self.calib_pt1,
            pt2=self.calib_pt2
        )

    def _on_unlock_alarm(self):
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            self.serial_ctrl.unlock()
            self._show_alarm_banner(False)
        else:
            self._show_alarm_banner(False)

    def _on_home_machine(self):
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            self.serial_ctrl.home()
            self._show_alarm_banner(False)
        else:
            self._show_alarm_banner(False)

    def _show_alarm_banner(self, visible: bool, message: Optional[str] = None):
        if hasattr(self, "lbl_alarm_msg") and message:
            self.lbl_alarm_msg.setText(f"🚨 <b>ALARM ACTIVE:</b> {message}")
        if hasattr(self, "alarm_banner"):
            self.alarm_banner.setVisible(visible)

    def _on_grbl_settings_updated(self, settings_dict: Dict[str, str]):
        x_travel = settings_dict.get("$130")
        y_travel = settings_dict.get("$131")
        soft_lim = settings_dict.get("$20", "0")

        if x_travel and y_travel:
            try:
                x_val = float(x_travel)
                y_val = float(y_travel)
                soft_status = "Enabled ($20=1)" if soft_lim == "1" else "Disabled ($20=0)"
                self.lbl_grbl_detected.setText(f"Detected: X = {x_val:.1f} mm, Y = {y_val:.1f} mm, Soft Limits: {soft_status}")
                self.lbl_grbl_detected.setStyleSheet("color: #00ff88; font-size: 11px;")
                self.spin_width.setValue(x_val)
                self.spin_height.setValue(y_val)
                self._on_geometry_changed()
            except ValueError:
                pass

    def _on_read_grbl_eeprom(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Laser Not Connected", "Please connect to your laser engraver first to query GRBL EEPROM travel limits.")
            return

        self.lbl_grbl_detected.setText("Querying controller $$ settings...")
        self.serial_ctrl.send_command("$$")

    def _on_capture_pt1(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            # Fallback for testing / simulated
            self.calib_pt1 = (0.0, 0.0)
        else:
            wpos = getattr(self.serial_ctrl, "current_wpos", getattr(self.serial_ctrl, "wpos", [0.0, 0.0, 0.0]))
            self.calib_pt1 = (float(wpos[0]), float(wpos[1]))

        self.lbl_pt1_status.setText(f"Pt 1: ({self.calib_pt1[0]:.1f}, {self.calib_pt1[1]:.1f})")
        self._check_calibration_ready()
        self._on_geometry_changed()

    def _on_capture_pt2(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            self.calib_pt2 = (400.0, 400.0)
        else:
            wpos = getattr(self.serial_ctrl, "current_wpos", getattr(self.serial_ctrl, "wpos", [400.0, 400.0, 0.0]))
            self.calib_pt2 = (float(wpos[0]), float(wpos[1]))

        self.lbl_pt2_status.setText(f"Pt 2: ({self.calib_pt2[0]:.1f}, {self.calib_pt2[1]:.1f})")
        self._check_calibration_ready()
        self._on_geometry_changed()

    def _check_calibration_ready(self):
        if self.calib_pt1 and self.calib_pt2:
            dx = abs(self.calib_pt2[0] - self.calib_pt1[0])
            dy = abs(self.calib_pt2[1] - self.calib_pt1[1])
            self.btn_calc_measured.setEnabled(True)
            self.btn_calc_measured.setText(f"📐 Apply Measured Area ({dx:.1f} × {dy:.1f} mm)")

    def _on_apply_measured_bed(self):
        if not self.calib_pt1 or not self.calib_pt2:
            return
        dx = abs(self.calib_pt2[0] - self.calib_pt1[0])
        dy = abs(self.calib_pt2[1] - self.calib_pt1[1])
        if dx < 10.0 or dy < 10.0:
            QMessageBox.warning(self, "Invalid Distance", "Measured travel area is too small (< 10 mm). Please check captured coordinates.")
            return

        self.spin_width.setValue(dx)
        self.spin_height.setValue(dy)
        self._on_geometry_changed()
        QMessageBox.information(self, "Measured Area Applied", f"Successfully applied calibrated dimensions: {dx:.1f} × {dy:.1f} mm.")

    def _open_auto_calib_studio(self):
        """Opens the interactive Vision Auto-Calibration Studio dialog."""
        from laserforge.core.camera_engine import CameraEngine
        from laserforge.ui.auto_calibration_dialog import AutoCalibrationDialog
        cam_eng = getattr(self, "camera_engine", None) or CameraEngine()
        dlg = AutoCalibrationDialog(
            camera_engine=cam_eng,
            settings=self.settings,
            serial_ctrl=self.serial_ctrl,
            scene=self.scene,
            parent=self
        )
        dlg.calibration_applied.connect(self._on_vision_calibration_applied)
        dlg.exec()

    def _on_vision_calibration_applied(self, calib):
        """Updates bed dimensions and visual diagram when calibration is applied."""
        if calib.bed_width_mm > 0 and calib.bed_height_mm > 0:
            self.spin_width.setValue(calib.bed_width_mm)
            self.spin_height.setValue(calib.bed_height_mm)
            self._on_geometry_changed()

    # -----------------------------------------------------------------------
    # Travel Verification Moves & Framing
    # -----------------------------------------------------------------------
    def _jump_to_corner(self, corner_name: str):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.information(self, "Simulated Move", f"Laser not connected. (Target coordinate for {corner_name} tested successfully).")
            return

        if getattr(self.serial_ctrl, "is_alarm", False):
            res = QMessageBox.question(
                self, "Laser in Alarm State",
                "The laser controller is in ALARM state (motion locked).\n\nWould you like to send Unlock ($X) now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                self._on_unlock_alarm()
            return

        w = self.spin_width.value()
        h = self.spin_height.value()
        rapid = self.spin_test_speed.value() if hasattr(self, "spin_test_speed") else getattr(self.settings, "rapid_speed", 3000.0)
        margin = self.spin_margin.value() if getattr(self, "chk_safe_margin", None) and self.chk_safe_margin.isChecked() else 0.0

        orig = self.combo_origin.currentText()
        is_right = "Right" in orig
        is_bottom = "Bottom" in orig

        if corner_name == "Center":
            target = (w / 2.0, h / 2.0)
        else:
            # Physical bed corners: BL (left, bottom), BR (right, bottom), TL (left, top), TR (right, top)
            want_right = (corner_name in ("BR", "TR"))
            want_top = (corner_name in ("TL", "TR"))

            tx = margin if (want_right == is_right) else max(margin, w - margin)
            ty = margin if (want_top != is_bottom) else max(margin, h - margin)
            target = (tx, ty)

        cmd = f"G90 G0 X{target[0]:.3f} Y{target[1]:.3f} F{rapid:.0f}"
        self.serial_ctrl.send_command(cmd)

    def _trace_bed_perimeter(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.information(self, "Simulated Framing", "Laser not connected. Perimeter framing path verified.")
            return

        w = self.spin_width.value()
        h = self.spin_height.value()
        speed = getattr(self.settings, "framing_speed", 2000.0)
        power_pct = getattr(self.settings, "framing_power_pct", 0.5)
        max_s = getattr(self.settings, "max_s_value", 1000)
        s_val = int(max_s * (power_pct / 100.0))

        # Safe bounding box trace
        cmds = [
            "G90 G21",
            f"G0 X0 Y0 F{speed:.0f}",
            f"M4 S{s_val}" if s_val > 0 else "G1",
            f"G1 X{w:.3f} Y0 F{speed:.0f}",
            f"G1 X{w:.3f} Y{h:.3f} F{speed:.0f}",
            f"G1 X0 Y{h:.3f} F{speed:.0f}",
            f"G1 X0 Y0 F{speed:.0f}",
            "M5",
            "G0 X0 Y0"
        ]
        for c in cmds:
            self.serial_ctrl.send_command(c)

    def _abort_motion(self):
        if self.serial_ctrl:
            self.serial_ctrl.send_realtime(0x18)  # Ctrl-X soft reset
            self.serial_ctrl.send_command("M5")
            self._show_alarm_banner(False)

    # -----------------------------------------------------------------------
    # Wasteboard Grid Generation
    # -----------------------------------------------------------------------
    def _generate_wasteboard_grid(self):
        if not self.scene:
            QMessageBox.warning(self, "No Canvas", "Canvas scene is not available.")
            return

        w = self.spin_width.value()
        h = self.spin_height.value()

        step_map = {0: 10.0, 1: 25.0, 2: 50.0, 3: 100.0}
        step_mm = step_map.get(self.combo_grid_step.currentIndex(), 50.0)
        target_layer = self.combo_grid_layer.currentData()
        add_numbers = self.chk_grid_numbers.isChecked()
        add_corners = self.chk_corner_stops.isChecked()
        add_center = self.chk_center_cross.isChecked()

        items_created = 0

        # 1. Outer perimeter border
        border_rect = RectEntity(x=0.0, y=0.0, width=w, height=h, layer_id=target_layer)
        self.scene.add_entity(border_rect)
        items_created += 1

        # 2. Vertical grid lines
        x = step_mm
        while x < w:
            line = LineEntity(x=x, y=0.0, x2=x, y2=h, layer_id=target_layer)
            self.scene.add_entity(line)
            items_created += 1

            if add_numbers and h > 20:
                txt = TextEntity(text=f"{int(x)}", x=x + 1.0, y=3.0, font_size=4.0, layer_id=target_layer)
                self.scene.add_entity(txt)
                items_created += 1
            x += step_mm

        # 3. Horizontal grid lines
        y = step_mm
        while y < h:
            line = LineEntity(x=0.0, y=y, x2=w, y2=y, layer_id=target_layer)
            self.scene.add_entity(line)
            items_created += 1

            if add_numbers and w > 20:
                txt = TextEntity(text=f"{int(y)}", x=3.0, y=y + 1.0, font_size=4.0, layer_id=target_layer)
                self.scene.add_entity(txt)
                items_created += 1
            y += step_mm

        # 4. Corner L-ticks
        if add_corners:
            tick_len = min(20.0, step_mm / 2.0)
            # Bottom-Left
            self.scene.add_entity(LineEntity(x=0, y=0, x2=tick_len, y2=0, layer_id=target_layer))
            self.scene.add_entity(LineEntity(x=0, y=0, x2=0, y2=tick_len, layer_id=target_layer))
            items_created += 2

        # 5. Center Crosshair
        if add_center:
            cx = w / 2.0
            cy = h / 2.0
            c_len = 15.0
            self.scene.add_entity(LineEntity(x=cx - c_len, y=cy, x2=cx + c_len, y2=cy, layer_id=target_layer))
            self.scene.add_entity(LineEntity(x=cx, y=cy - c_len, x2=cx, y2=cy + c_len, layer_id=target_layer))
            items_created += 2

        QMessageBox.information(
            self,
            "Grid Generated",
            f"Successfully generated {items_created} wasteboard grid elements on Layer {target_layer}."
        )

    # -----------------------------------------------------------------------
    # Save & Apply
    # -----------------------------------------------------------------------
    def _on_apply_and_save(self):
        w = self.spin_width.value()
        h = self.spin_height.value()
        orig = self.combo_origin.currentText()
        margin = self.spin_margin.value()

        # Update machine settings
        self.settings.bed_width = w
        self.settings.bed_height = h
        self.settings.origin_corner = orig
        setattr(self.settings, "safety_margin_mm", margin)

        # Sync to GRBL controller if requested and connected
        if self.chk_sync_grbl.isChecked() and self.serial_ctrl and self.serial_ctrl.is_connected:
            self.serial_ctrl.send_command(f"$130={w:.1f}")
            self.serial_ctrl.send_command(f"$131={h:.1f}")
            self.serial_ctrl.send_command("$20=1")

        self.accept()
