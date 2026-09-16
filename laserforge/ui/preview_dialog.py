"""
LaserForge Project Outcome Simulation & Toolpath Preview Studio.

Provides:
1. Realistic Material Outcome Simulation:
   - Visualizes the finished physical burn finish on real materials
     (Basswood/Birch Plywood, Dark Walnut, Black Acrylic, White Acrylic,
      Vegetable-Tanned Leather, Anodized Aluminum, Kraft Cardboard, or Dark CAD).
   - Realistic laser kerf charring, heat-affected zone halo, and engraved depth.
2. Animated Toolpath Playback & Laser Plasma Beam:
   - Scrubbable timeline with multi-speed animation (0.5x to 100x).
   - Dynamic glowing fiery laser beam spot with plasma core and sparks when cutting.
   - Real-time HUD showing head coordinates (X, Y), feedrate, power %, and elapsed time.
3. Layer-by-Layer Breakdown:
   - Layer statistics, cut distances, and visibility filters.
4. GRBL 1.1 Validation & G-Code Inspector:
   - Syntax validation, bounds violation detection, and export options.
5. Direct Job Launch:
   - Start laser job directly from the simulation studio once outcomes are verified.
"""

from typing import List, Tuple, Optional, Dict, Any, Set
import math
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QComboBox, QTextEdit, QFileDialog,
    QTabWidget, QSplitter, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPaintEvent,
    QWheelEvent, QMouseEvent, QRadialGradient, QLinearGradient
)

from laserforge.config import MachineSettings
from laserforge.core.gcode_generator import GCodeJobResult, ToolpathSegment
from laserforge.core.gcode_validator import GCodeValidator, ValidationReport


MATERIAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "birch_wood": {
        "name": "Basswood / Birch Plywood",
        "bg_color": QColor("#E6D4B2"),
        "bed_border": QColor("#C4B28E"),
        "rapid_color": QColor(180, 50, 50, 75),
        "kerf_outer": QColor(100, 55, 20, 85),     # Golden-brown heat scorch halo
        "kerf_inner": QColor(25, 14, 8, 245),      # Deep dark charcoal cut kerf
        "engrave_color": QColor(55, 30, 14, 215),  # Rich dark wood engrave burn
        "is_material": True
    },
    "walnut_wood": {
        "name": "Dark Walnut / Hardwood",
        "bg_color": QColor("#463222"),
        "bed_border": QColor("#332316"),
        "rapid_color": QColor(220, 70, 70, 75),
        "kerf_outer": QColor(20, 10, 5, 120),
        "kerf_inner": QColor(10, 5, 2, 250),
        "engrave_color": QColor(28, 16, 10, 220),
        "is_material": True
    },
    "black_acrylic": {
        "name": "Glossy Black Acrylic",
        "bg_color": QColor("#121216"),
        "bed_border": QColor("#262630"),
        "rapid_color": QColor(244, 67, 54, 75),
        "kerf_outer": QColor(5, 5, 5, 180),
        "kerf_inner": QColor(0, 0, 0, 255),
        "engrave_color": QColor(240, 240, 245, 230),  # Frosted white laser ablation
        "is_material": True
    },
    "white_acrylic": {
        "name": "White Acrylic / Delrin",
        "bg_color": QColor("#F2F4F7"),
        "bed_border": QColor("#D0D6DC"),
        "rapid_color": QColor(220, 50, 50, 75),
        "kerf_outer": QColor(120, 130, 140, 70),
        "kerf_inner": QColor(40, 45, 50, 235),
        "engrave_color": QColor(60, 65, 70, 200),
        "is_material": True
    },
    "leather": {
        "name": "Vegetable Tanned Leather",
        "bg_color": QColor("#9E6030"),
        "bed_border": QColor("#7E4920"),
        "rapid_color": QColor(220, 50, 50, 75),
        "kerf_outer": QColor(60, 30, 10, 110),
        "kerf_inner": QColor(18, 9, 3, 250),
        "engrave_color": QColor(42, 20, 7, 225),
        "is_material": True
    },
    "aluminum": {
        "name": "Anodized Aluminum Blank",
        "bg_color": QColor("#222A30"),
        "bed_border": QColor("#37474F"),
        "rapid_color": QColor(244, 67, 54, 75),
        "kerf_outer": QColor(200, 210, 220, 40),
        "kerf_inner": QColor(245, 248, 250, 240),  # Brilliant silver laser mark
        "engrave_color": QColor(235, 242, 248, 230),
        "is_material": True
    },
    "cardboard": {
        "name": "Kraft Cardboard",
        "bg_color": QColor("#C9AA80"),
        "bed_border": QColor("#A4865E"),
        "rapid_color": QColor(220, 50, 50, 75),
        "kerf_outer": QColor(90, 55, 25, 95),
        "kerf_inner": QColor(28, 16, 9, 245),
        "engrave_color": QColor(52, 30, 14, 215),
        "is_material": True
    },
    "cad_dark": {
        "name": "Dark CAD Workbed",
        "bg_color": QColor("#181820"),
        "bed_border": QColor("#2c2c3e"),
        "rapid_color": QColor(244, 67, 54, 110),
        "kerf_outer": QColor(0, 229, 255, 40),
        "kerf_inner": QColor(0, 229, 255, 255),
        "engrave_color": QColor(0, 229, 255, 200),
        "is_material": False
    }
}


class SimulationCanvas(QWidget):
    """
    High-fidelity rendering canvas simulating:
    - Real-world material textures, laser kerf charring, and engraved depths
    - High-speed interactive zoom and pan
    - Laser head motion with dynamic fiery plasma beam core and glow
    - Interactive HUD with head position, feedrate, power, and cut state
    """
    def __init__(
        self,
        segments: List[ToolpathSegment],
        bbox: Tuple[float, float, float, float],
        parent=None
    ):
        super().__init__(parent)
        self.segments = segments
        self.bbox = bbox  # (min_x, min_y, max_x, max_y)
        self.current_idx = len(segments)  # Defaults to showing full path

        # View transform
        self.scale = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.last_mouse_pos = QPointF()
        self.panning = False

        # Simulation Display Options
        self.view_mode: str = "outcome"  # "outcome" (material burn) or "toolpath" (CAD lines)
        self.material_key: str = "birch_wood"
        self.show_rapids: bool = False
        self.show_laser_head: bool = True
        self.show_grid: bool = True
        self.hidden_layers: Set[int] = set()

        self.setMinimumSize(500, 420)
        self.setStyleSheet("background-color: #121218;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_current_index(self, idx: int):
        self.current_idx = max(0, min(len(self.segments), idx))
        self.update()

    def reset_view(self):
        """Fits toolpath bounding box into current widget geometry."""
        min_x, min_y, max_x, max_y = self.bbox
        w = max(10.0, max_x - min_x)
        h = max(10.0, max_y - min_y)

        margin = 48.0
        avail_w = max(100.0, self.width() - margin * 2)
        avail_h = max(100.0, self.height() - margin * 2)

        self.scale = min(avail_w / w, avail_h / h)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        self.pan_x = (self.width() / 2.0) - cx * self.scale
        self.pan_y = (self.height() / 2.0) + cy * self.scale
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.reset_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reset_view()

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        new_scale = max(0.05, min(100.0, self.scale * factor))
        mpos = event.position()
        self.pan_x = mpos.x() - (mpos.x() - self.pan_x) * (new_scale / self.scale)
        self.pan_y = mpos.y() - (mpos.y() - self.pan_y) * (new_scale / self.scale)
        self.scale = new_scale
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self.panning = True
            self.last_mouse_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.panning:
            delta = event.position() - self.last_mouse_pos
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.last_mouse_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.panning = False

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        mat_info = MATERIAL_PRESETS.get(self.material_key, MATERIAL_PRESETS["birch_wood"])
        is_outcome = (self.view_mode == "outcome")

        # 1. Fill Canvas Background
        w = self.width()
        h = self.height()
        bg_color = mat_info["bg_color"] if is_outcome else QColor("#14141a")
        painter.fillRect(0, 0, w, h, bg_color)

        # Coordinate transformation: origin bottom-left in machine space
        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(self.pan_x + x * self.scale, self.pan_y - y * self.scale)

        # 2. Draw Simulated Workpiece Board Boundary (if in outcome mode)
        min_x, min_y, max_x, max_y = self.bbox
        if is_outcome and (max_x > min_x) and (max_y > min_y):
            # Give workpiece a slight margin border
            board_margin = max(5.0, min(15.0, (max_x - min_x) * 0.08))
            p_tl = to_screen(min_x - board_margin, max_y + board_margin)
            p_br = to_screen(max_x + board_margin, min_y - board_margin)
            board_rect = QRectF(p_tl.x(), p_tl.y(), p_br.x() - p_tl.x(), p_br.y() - p_tl.y())

            # Subtle board drop-shadow and bevel
            shadow_rect = board_rect.adjusted(3, 3, 3, 3)
            painter.fillRect(shadow_rect, QColor(0, 0, 0, 45))
            painter.fillRect(board_rect, mat_info["bg_color"])

            pen_border = QPen(mat_info["bed_border"], 2)
            painter.setPen(pen_border)
            painter.drawRect(board_rect)

        # 3. Draw Background Machine Grid (if enabled)
        if self.show_grid and not is_outcome:
            grid_step = 25.0 * self.scale
            if grid_step > 8.0:
                pen_grid = QPen(QColor("#1f1f2a"), 1, Qt.PenStyle.DotLine)
                painter.setPen(pen_grid)
                start_x = self.pan_x % grid_step
                while start_x < w:
                    painter.drawLine(int(start_x), 0, int(start_x), h)
                    start_x += grid_step
                start_y = self.pan_y % grid_step
                while start_y < h:
                    painter.drawLine(0, int(start_y), w, int(start_y))
                    start_y += grid_step

        # Draw machine origin crosshair (0, 0)
        origin_pt = to_screen(0, 0)
        painter.setPen(QPen(QColor("#606070"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(origin_pt.x() - 15, origin_pt.y()), QPointF(origin_pt.x() + 15, origin_pt.y()))
        painter.drawLine(QPointF(origin_pt.x(), origin_pt.y() - 15), QPointF(origin_pt.x(), origin_pt.y() + 15))

        # 4. Render Cut & Engrave Toolpath Segments up to current_idx
        rapid_pen = QPen(mat_info["rapid_color"], 1.0, Qt.PenStyle.DotLine)

        # Pens for simulated outcome burn
        kerf_outer_pen = QPen(mat_info["kerf_outer"], max(1.8, 1.8 * (self.scale ** 0.4)))
        kerf_outer_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        kerf_inner_pen = QPen(mat_info["kerf_inner"], max(1.0, 1.0 * (self.scale ** 0.4)))
        kerf_inner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        engrave_pen = QPen(mat_info["engrave_color"], max(1.2, 1.2 * (self.scale ** 0.4)))
        engrave_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        last_pt = None
        last_seg: Optional[ToolpathSegment] = None

        # Pass 1: Outer heat scorch halo (in outcome mode)
        if is_outcome:
            for i in range(self.current_idx):
                seg = self.segments[i]
                if seg.layer_id in self.hidden_layers:
                    continue
                if seg.move_type != "rapid":
                    p1 = to_screen(seg.x1, seg.y1)
                    p2 = to_screen(seg.x2, seg.y2)
                    painter.setPen(kerf_outer_pen)
                    painter.drawLine(p1, p2)

        # Pass 2: Main cut lines, engravings, and rapids
        for i in range(self.current_idx):
            seg = self.segments[i]
            if seg.layer_id in self.hidden_layers:
                continue

            p1 = to_screen(seg.x1, seg.y1)
            p2 = to_screen(seg.x2, seg.y2)
            last_pt = p2
            last_seg = seg

            if seg.move_type == "rapid":
                if self.show_rapids:
                    painter.setPen(rapid_pen)
                    painter.drawLine(p1, p2)
            else:
                if is_outcome:
                    if seg.power_pct > 65.0:
                        painter.setPen(kerf_inner_pen)
                    else:
                        painter.setPen(engrave_pen)
                else:
                    pen_color = QColor(seg.color) if seg.color else QColor("#00e5ff")
                    painter.setPen(QPen(pen_color, max(1.0, 1.2 * (self.scale ** 0.3))))

                painter.drawLine(p1, p2)

        # 5. Draw Animated Laser Head with Glowing Plasma Beam Spot
        if self.show_laser_head and last_pt and last_seg:
            is_firing = (last_seg.move_type != "rapid")

            if is_firing:
                # Dynamic fiery laser plasma focal spot
                # Outer plasma glow
                glow = QRadialGradient(last_pt, 16.0)
                glow.setColorAt(0.0, QColor(255, 255, 220, 255))   # Pure white hot core
                glow.setColorAt(0.25, QColor(255, 200, 40, 220))   # Vibrant yellow plasma
                glow.setColorAt(0.65, QColor(255, 70, 10, 140))    # Intense fiery orange
                glow.setColorAt(1.0, QColor(255, 30, 0, 0))        # Fade to transparent

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(glow))
                painter.drawEllipse(last_pt, 16.0, 16.0)

                # Hot white laser focal point
                painter.setBrush(QBrush(QColor("#FFFFFF")))
                painter.drawEllipse(last_pt, 2.5, 2.5)

                # Laser nozzle ring
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(255, 220, 50, 200), 1.2))
                painter.drawEllipse(last_pt, 7.0, 7.0)
            else:
                # Rapid travel head indicator (cyan crosshairs)
                painter.setPen(QPen(QColor("#00e5ff"), 1.2))
                painter.setBrush(QBrush(QColor(0, 229, 255, 60)))
                painter.drawEllipse(last_pt, 5.0, 5.0)
                painter.drawLine(QPointF(last_pt.x() - 10, last_pt.y()), QPointF(last_pt.x() + 10, last_pt.y()))
                painter.drawLine(QPointF(last_pt.x(), last_pt.y() - 10), QPointF(last_pt.x(), last_pt.y() + 10))

        # 6. Live HUD Overlay (Head Position, Speed, Power)
        hud_rect = QRectF(10, 10, 310, 54)
        painter.fillRect(hud_rect, QColor(15, 15, 22, 210))
        painter.setPen(QPen(QColor(50, 50, 70, 230), 1))
        painter.drawRect(hud_rect)

        painter.setFont(QFont("monospace", 8, QFont.Weight.Bold))
        if last_seg and last_pt:
            cur_x = last_seg.x2
            cur_y = last_seg.y2
            is_firing = (last_seg.move_type != "rapid")
            status_txt = "⚡ BURNING" if is_firing else "✈ RAPID"
            status_col = "#00FF66" if is_firing else "#00E5FF"

            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(18, 26, f"Head: X={cur_x:6.1f}mm  Y={cur_y:6.1f}mm")

            painter.setPen(QColor(status_col))
            painter.drawText(18, 40, f"State: {status_txt}")

            painter.setPen(QColor("#AAAAAA"))
            painter.drawText(120, 40, f"Feed: {last_seg.feedrate:4.0f} mm/min")

            painter.setPen(QColor("#FFD54F"))
            painter.drawText(18, 54, f"Power: {last_seg.power_pct:4.1f}%")

            painter.setPen(QColor("#8888AA"))
            painter.drawText(120, 54, f"Move: {self.current_idx}/{len(self.segments)}")
        else:
            painter.setPen(QColor("#888888"))
            painter.drawText(18, 32, "Laser Head Idle (Ready)")


class PreviewDialog(QDialog):
    """
    Complete Interactive Project Outcome Simulation & Toolpath Preview Dialog.
    """
    def __init__(
        self,
        job_result: GCodeJobResult,
        parent=None,
        settings: Optional[MachineSettings] = None
    ):
        super().__init__(parent)
        self.job = job_result
        self.settings = settings or getattr(parent, "settings", None) or MachineSettings()

        # Run GRBL G-Code Validation
        validator = GCodeValidator(self.settings)
        self.validation_report = validator.validate(self.job.gcode)

        self.setWindowTitle("Project Outcome Simulation & Toolpath Preview Studio — LaserForge")
        self.resize(1050, 740)
        self.setMinimumSize(850, 580)

        # Precompute segment times for accurate cumulative elapsed time tracking
        self.segment_times_sec: List[float] = []
        self.cumulative_times_sec: List[float] = [0.0]
        cum = 0.0
        rapid_spd = getattr(self.settings, "rapid_speed", 3000.0) / 60.0

        for seg in self.job.segments:
            d = math.hypot(seg.x2 - seg.x1, seg.y2 - seg.y1)
            spd = (seg.feedrate / 60.0) if seg.move_type != "rapid" else rapid_spd
            t_seg = d / max(0.1, spd)
            self.segment_times_sec.append(t_seg)
            cum += t_seg
            self.cumulative_times_sec.append(cum)

        self.total_time_sec = cum if cum > 0 else self.job.estimated_time_sec

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(20)  # 50 FPS
        self.play_timer.timeout.connect(self._on_timer_tick)
        self.speed_multiplier = 5

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Tabs: Simulation & Raw G-Code & Validation
        tabs = QTabWidget()

        # Tab 1: Simulation View
        sim_widget = QWidget()
        sim_layout = QVBoxLayout(sim_widget)
        sim_layout.setContentsMargins(4, 4, 4, 4)
        sim_layout.setSpacing(8)

        # Top Control & Metric Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        # Material surface selector
        top_bar.addWidget(QLabel("Material Surface:"))
        self.combo_mat = QComboBox()
        for key, info in MATERIAL_PRESETS.items():
            self.combo_mat.addItem(info["name"], key)
        self.combo_mat.currentIndexChanged.connect(self._on_material_changed)
        top_bar.addWidget(self.combo_mat)

        # View mode selector
        top_bar.addWidget(QLabel("View Mode:"))
        self.combo_view_mode = QComboBox()
        self.combo_view_mode.addItem("🎨 Simulated Outcome (Material & Burn)", "outcome")
        self.combo_view_mode.addItem("📐 Toolpath Vectors (Machine Trajectory)", "toolpath")
        self.combo_view_mode.currentIndexChanged.connect(self._on_view_mode_changed)
        top_bar.addWidget(self.combo_view_mode)

        # Toggles
        self.chk_rapids = QCheckBox("Show Rapids (G0)")
        self.chk_rapids.setChecked(False)
        self.chk_rapids.toggled.connect(self._on_rapids_toggled)
        top_bar.addWidget(self.chk_rapids)

        top_bar.addStretch(1)

        mins = int(self.total_time_sec // 60)
        secs = int(self.total_time_sec % 60)
        time_str = f"{mins:02d}m {secs:02d}s" if mins > 0 else f"{secs}s"

        lbl_time = QLabel(f"⏱ Est. Time: <b>{time_str}</b>")
        lbl_cut = QLabel(f"✂ Cut Dist: <b>{self.job.total_cut_dist_mm:.1f} mm</b>")
        for lbl in (lbl_time, lbl_cut):
            lbl.setStyleSheet("background-color: #262632; padding: 4px 8px; border-radius: 4px; color: #cfd8dc;")
            top_bar.addWidget(lbl)

        btn_reset_view = QPushButton("⛶ Fit Artwork")
        btn_reset_view.clicked.connect(lambda: self.canvas.reset_view())
        top_bar.addWidget(btn_reset_view)

        sim_layout.addLayout(top_bar)

        # 2D Simulation Canvas
        self.canvas = SimulationCanvas(self.job.segments, self.job.bounding_box, parent=self)
        sim_layout.addWidget(self.canvas, 1)

        # Scrubber Slider & Media Playback Controls
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(6)

        btn_first = QPushButton("⏮")
        btn_first.setToolTip("Jump to start")
        btn_first.setFixedWidth(36)
        btn_first.clicked.connect(self._reset_scrubber)
        ctrl_layout.addWidget(btn_first)

        btn_step_back = QPushButton("⏪ -10")
        btn_step_back.setToolTip("Step backward 10 segments")
        btn_step_back.clicked.connect(lambda: self._step_segments(-10))
        ctrl_layout.addWidget(btn_step_back)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold; padding: 4px 10px;")
        self.btn_play.setFixedWidth(74)
        self.btn_play.clicked.connect(self._toggle_playback)
        ctrl_layout.addWidget(self.btn_play)

        btn_step_fwd = QPushButton("⏩ +10")
        btn_step_fwd.setToolTip("Step forward 10 segments")
        btn_step_fwd.clicked.connect(lambda: self._step_segments(10))
        ctrl_layout.addWidget(btn_step_fwd)

        btn_last = QPushButton("⏭")
        btn_last.setToolTip("Jump to end (Show full outcome)")
        btn_last.setFixedWidth(36)
        btn_last.clicked.connect(self._jump_to_end)
        ctrl_layout.addWidget(btn_last)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(self.job.segments))
        self.slider.setValue(len(self.job.segments))
        self.slider.valueChanged.connect(self._on_slider_moved)
        ctrl_layout.addWidget(self.slider, 1)

        self.lbl_time_progress = QLabel(f"{time_str} / {time_str} (100%)")
        self.lbl_time_progress.setStyleSheet("font-family: monospace; font-size: 11px; color: #a5d6a7;")
        self.lbl_time_progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ctrl_layout.addWidget(self.lbl_time_progress)

        ctrl_layout.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.5x", "1x", "2x", "5x", "10x", "25x", "50x", "100x"])
        self.speed_combo.setCurrentText("5x")
        self.speed_multiplier = 5
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        ctrl_layout.addWidget(self.speed_combo)

        sim_layout.addLayout(ctrl_layout)
        tabs.addTab(sim_widget, "🎬 Project Outcome Simulation")

        # Tab 2: Layers & Execution Breakdown
        layers_widget = self._build_layers_tab()
        tabs.addTab(layers_widget, "📋 Layer Execution Breakdown")

        # Tab 3: GRBL Validation Report
        val_widget = self._build_validation_tab()
        val_tab_title = f"🛡️ GRBL Validation ({len(self.validation_report.issues)})" if self.validation_report.issues else "🛡️ GRBL Validation"
        tabs.addTab(val_widget, val_tab_title)

        # Tab 4: Generated G-Code
        gcode_widget = self._build_gcode_tab()
        tabs.addTab(gcode_widget, "📄 Generated G-Code")

        main_layout.addWidget(tabs)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(4, 4, 4, 4)

        w_mm = max(0.0, self.job.bounding_box[2] - self.job.bounding_box[0])
        h_mm = max(0.0, self.job.bounding_box[3] - self.job.bounding_box[1])
        lbl_dims = QLabel(f"📐 Job Bounding Box: <b>{w_mm:.1f} × {h_mm:.1f} mm</b> | Rapids: <b>{self.job.total_rapid_dist_mm:.1f} mm</b>")
        lbl_dims.setStyleSheet("color: #9999aa; font-size: 11px;")
        bottom_bar.addWidget(lbl_dims)

        bottom_bar.addStretch(1)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)

        # Direct Start Job button!
        self.btn_start_job = QPushButton("▶ Start Laser Job Now")
        self.btn_start_job.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                font-weight: bold;
                padding: 7px 16px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
        """)
        self.btn_start_job.setToolTip("Directly launch and burn this job to the connected laser engraver")
        self.btn_start_job.clicked.connect(self._on_start_job_clicked)
        bottom_bar.addWidget(self.btn_start_job)

        main_layout.addLayout(bottom_bar)

    def _build_layers_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)

        # Group segments by layer_id
        layer_stats: Dict[int, Dict[str, Any]] = {}
        rapid_spd = getattr(self.settings, "rapid_speed", 3000.0) / 60.0

        for seg in self.job.segments:
            lid = seg.layer_id
            if lid not in layer_stats:
                layer_stats[lid] = {
                    "color": seg.color,
                    "cuts": 0,
                    "cut_dist": 0.0,
                    "rapid_dist": 0.0,
                    "time_sec": 0.0,
                    "max_power": 0.0,
                    "speed": seg.feedrate
                }
            d = math.hypot(seg.x2 - seg.x1, seg.y2 - seg.y1)
            if seg.move_type == "rapid":
                layer_stats[lid]["rapid_dist"] += d
                layer_stats[lid]["time_sec"] += d / max(0.1, rapid_spd)
            else:
                layer_stats[lid]["cuts"] += 1
                layer_stats[lid]["cut_dist"] += d
                layer_stats[lid]["time_sec"] += d / max(0.1, (seg.feedrate / 60.0))
                if seg.power_pct > layer_stats[lid]["max_power"]:
                    layer_stats[lid]["max_power"] = seg.power_pct

        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels([
            "Visible", "Layer", "Color", "Cut Distance", "Rapid Distance", "Est. Time", "Max Power"
        ])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(layer_stats))

        for row, (lid, st) in enumerate(sorted(layer_stats.items())):
            # Checkbox
            chk = QCheckBox()
            chk.setChecked(True)
            chk.toggled.connect(lambda checked, l_id=lid: self._toggle_layer_visibility(l_id, checked))
            table.setCellWidget(row, 0, chk)

            # Layer name
            table.setItem(row, 1, QTableWidgetItem(f"C{lid:02d}"))

            # Color pill
            col_item = QTableWidgetItem(st["color"])
            col_item.setForeground(QColor(st["color"]))
            table.setItem(row, 2, col_item)

            table.setItem(row, 3, QTableWidgetItem(f"{st['cut_dist']:.1f} mm"))
            table.setItem(row, 4, QTableWidgetItem(f"{st['rapid_dist']:.1f} mm"))

            m = int(st["time_sec"] // 60)
            s = int(st["time_sec"] % 60)
            table.setItem(row, 5, QTableWidgetItem(f"{m:02d}:{s:02d}"))
            table.setItem(row, 6, QTableWidgetItem(f"{st['max_power']:.0f}%"))

        layout.addWidget(table)
        return widget

    def _build_validation_tab(self) -> QWidget:
        val_widget = QWidget()
        val_layout = QVBoxLayout(val_widget)
        val_layout.setContentsMargins(6, 6, 6, 6)
        val_layout.setSpacing(8)

        val_header = QFrame()
        vh_layout = QHBoxLayout(val_header)
        vh_layout.setContentsMargins(10, 8, 10, 8)
        if self.validation_report.has_errors:
            val_header.setStyleSheet("background-color: #4a1515; border-radius: 4px; border: 1px solid #d32f2f;")
            vh_lbl = QLabel(f"<b>❌ G-Code Validation Failed:</b> {len(self.validation_report.errors)} error(s) must be resolved before cutting.")
        elif self.validation_report.has_warnings:
            val_header.setStyleSheet("background-color: #4a3415; border-radius: 4px; border: 1px solid #f57c00;")
            vh_lbl = QLabel(f"<b>⚠️ G-Code Validation Passed with Warnings:</b> {len(self.validation_report.warnings)} warning(s) detected.")
        else:
            val_header.setStyleSheet("background-color: #153e20; border-radius: 4px; border: 1px solid #388e3c;")
            vh_lbl = QLabel("<b>✅ Clean G-Code:</b> 100% compliant with GRBL 1.1 specification and machine bounds.")
        vh_layout.addWidget(vh_lbl)
        val_layout.addWidget(val_header)

        if self.validation_report.issues:
            table = QTableWidget()
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels(["Severity", "Line", "Code", "Description", "G-Code"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            table.verticalHeader().setVisible(False)
            table.setRowCount(len(self.validation_report.issues))

            mono = QFont("monospace", 9)
            for row, issue in enumerate(self.validation_report.issues):
                item_s = QTableWidgetItem("🔴 ERROR" if issue.severity == "error" else "🟡 WARN")
                item_s.setForeground(QColor("#ff5252" if issue.severity == "error" else "#ffd740"))
                item_s.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 0, item_s)

                item_l = QTableWidgetItem(f"L{issue.line_number}")
                item_l.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, 1, item_l)

                table.setItem(row, 2, QTableWidgetItem(issue.error_code))
                table.setItem(row, 3, QTableWidgetItem(issue.message))

                item_g = QTableWidgetItem(issue.line_text)
                item_g.setFont(mono)
                table.setItem(row, 4, item_g)

            val_layout.addWidget(table, 1)
        else:
            lbl_all_good = QLabel("No syntax errors, out-of-bounds moves, or laser hazards found.")
            lbl_all_good.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_all_good.setStyleSheet("color: #a5d6a7; font-size: 13px; padding: 40px;")
            val_layout.addWidget(lbl_all_good, 1)

        return val_widget

    def _build_gcode_tab(self) -> QWidget:
        gcode_widget = QWidget()
        gcode_layout = QVBoxLayout(gcode_widget)
        gcode_layout.setContentsMargins(6, 6, 6, 6)

        self.gcode_edit = QTextEdit()
        self.gcode_edit.setPlainText(self.job.gcode)
        self.gcode_edit.setReadOnly(True)
        self.gcode_edit.setFont(QFont("monospace", 9))
        self.gcode_edit.setStyleSheet("background-color: #1a1a1a; color: #a5d6a7;")
        gcode_layout.addWidget(self.gcode_edit, 1)

        gcode_btn_row = QHBoxLayout()
        btn_save = QPushButton("💾 Save G-Code (.nc)...")
        btn_save.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 12px;")
        btn_save.clicked.connect(self._save_gcode)
        gcode_btn_row.addWidget(btn_save)

        btn_copy = QPushButton("📋 Copy to Clipboard")
        btn_copy.clicked.connect(self._copy_gcode)
        gcode_btn_row.addWidget(btn_copy)
        gcode_btn_row.addStretch(1)

        gcode_layout.addLayout(gcode_btn_row)
        return gcode_widget

    def _on_material_changed(self):
        mat_key = self.combo_mat.currentData()
        self.canvas.material_key = mat_key
        self.canvas.update()

    def _on_view_mode_changed(self):
        mode = self.combo_view_mode.currentData()
        self.canvas.view_mode = mode
        # By default in outcome mode, hide rapid lines for cleaner realistic visualization
        if mode == "outcome":
            self.chk_rapids.setChecked(False)
            self.canvas.show_rapids = False
        else:
            self.chk_rapids.setChecked(True)
            self.canvas.show_rapids = True
        self.canvas.update()

    def _on_rapids_toggled(self, checked: bool):
        self.canvas.show_rapids = checked
        self.canvas.update()

    def _toggle_layer_visibility(self, layer_id: int, visible: bool):
        if visible:
            self.canvas.hidden_layers.discard(layer_id)
        else:
            self.canvas.hidden_layers.add(layer_id)
        self.canvas.update()

    def _toggle_playback(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.btn_play.setText("▶ Play")
        else:
            if self.slider.value() >= len(self.job.segments):
                self.slider.setValue(0)
            self.play_timer.start()
            self.btn_play.setText("⏸ Pause")

    def _reset_scrubber(self):
        self.play_timer.stop()
        self.btn_play.setText("▶ Play")
        self.slider.setValue(0)

    def _jump_to_end(self):
        self.play_timer.stop()
        self.btn_play.setText("▶ Play")
        self.slider.setValue(len(self.job.segments))

    def _step_segments(self, delta: int):
        new_val = max(0, min(len(self.job.segments), self.slider.value() + delta))
        self.slider.setValue(new_val)

    def _on_timer_tick(self):
        step = max(1, self.speed_multiplier)
        new_val = self.slider.value() + step
        if new_val >= len(self.job.segments):
            self.slider.setValue(len(self.job.segments))
            self.play_timer.stop()
            self.btn_play.setText("▶ Play")
        else:
            self.slider.setValue(new_val)

    def _on_slider_moved(self, val: int):
        self.canvas.set_current_index(val)
        elapsed = self.cumulative_times_sec[min(val, len(self.cumulative_times_sec) - 1)]
        e_mins = int(elapsed // 60)
        e_secs = int(elapsed % 60)
        t_mins = int(self.total_time_sec // 60)
        t_secs = int(self.total_time_sec % 60)
        pct = (val / max(1, len(self.job.segments))) * 100.0
        self.lbl_time_progress.setText(f"{e_mins:02d}:{e_secs:02d} / {t_mins:02d}:{t_secs:02d} ({pct:.0f}%)")

    def _on_speed_changed(self, idx: int):
        text = self.speed_combo.currentText().replace("x", "")
        self.speed_multiplier = int(float(text))

    def _on_start_job_clicked(self):
        """Starts laser cutting directly after outcome verification."""
        p = self.parent()
        if p and hasattr(p, "start_job"):
            self.accept()
            p.start_job()
        else:
            QMessageBox.information(
                self, "Start Job",
                "To run this job, connect to your laser engraver in the Laser panel and click Start."
            )

    def _save_gcode(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save G-Code", "output.nc", "G-Code Files (*.nc *.gcode);;All Files (*)"
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.job.gcode)

    def _copy_gcode(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.job.gcode)
