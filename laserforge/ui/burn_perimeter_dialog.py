"""
LaserForge Burn Perimeter Alignment Tool.
Provides:
1. Interactive perimeter burn/score toolpath generation for physical workpiece alignment,
   jig indexing, and sacrificial spoilboard marking.
2. Supports Bounding Box, Box + Crosshair, Corner L-Ticks, Center Crosshair, and Tight Convex Hull.
3. Live interactive visual preview showing machine bed, design bounds, perimeter trajectory, and laser head.
4. One-click direct laser execution with safety confirmation, optical guide framing, and inline progress monitoring.
5. Direct CAD layer insertion to add alignment marks as vector entities on the canvas.
"""

from typing import List, Tuple, Optional, Any
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QSpinBox, QFrame,
    QMessageBox, QRadioButton, QButtonGroup, QCheckBox, QComboBox,
    QProgressBar, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QPolygonF

from laserforge.config import MachineSettings
from laserforge.core.serial_controller import SerialController
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.models import LaserEntity
from laserforge.core.layer_manager import LayerManager


class BurnPerimeterVisualWidget(QWidget):
    """
    Live graphical preview of the laser bed, design bounding box,
    and the calculated alignment perimeter burn paths.
    """

    def __init__(self, bed_width: float = 400.0, bed_height: float = 400.0, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 240)
        self.bed_width = max(10.0, bed_width)
        self.bed_height = max(10.0, bed_height)

        self.source_bbox: Tuple[float, float, float, float] = (20.0, 20.0, 100.0, 80.0)
        self.perimeter_bbox: Tuple[float, float, float, float] = (20.0, 20.0, 100.0, 80.0)
        self.mode: str = "box"
        self.corner_tick_len: float = 8.0
        self.hull_points: List[Tuple[float, float]] = []
        self.laser_pos: Tuple[float, float] = (0.0, 0.0)

        self.setStyleSheet("background-color: #121218; border: 1px solid #2e2e3e; border-radius: 4px;")

    def update_geometry_state(
        self,
        source_bbox: Tuple[float, float, float, float],
        perimeter_bbox: Tuple[float, float, float, float],
        mode: str,
        corner_tick_len: float = 8.0,
        hull_points: Optional[List[Tuple[float, float]]] = None,
        laser_pos: Optional[Tuple[float, float]] = None
    ):
        self.source_bbox = source_bbox
        self.perimeter_bbox = perimeter_bbox
        self.mode = mode
        self.corner_tick_len = corner_tick_len
        self.hull_points = hull_points or []
        if laser_pos is not None:
            self.laser_pos = laser_pos
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor("#121218"))

        margin = 24
        draw_w = max(10, self.width() - margin * 2)
        draw_h = max(10, self.height() - margin * 2)
        scale = min(draw_w / self.bed_width, draw_h / self.bed_height)

        ox = margin + (draw_w - self.bed_width * scale) / 2.0
        oy = self.height() - margin - (draw_h - self.bed_height * scale) / 2.0

        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(ox + x * scale, oy - y * scale)

        # Machine Bed
        bed_rect = QRectF(ox, oy - self.bed_height * scale, self.bed_width * scale, self.bed_height * scale)
        painter.setPen(QPen(QColor("#2d2d3d"), 1, Qt.PenStyle.SolidLine))
        painter.setBrush(QBrush(QColor("#181822")))
        painter.drawRect(bed_rect)

        # Bed Grid (100mm lines)
        painter.setPen(QPen(QColor("#232332"), 1, Qt.PenStyle.DotLine))
        gx = 100.0
        while gx < self.bed_width:
            p1 = to_screen(gx, 0)
            p2 = to_screen(gx, self.bed_height)
            painter.drawLine(p1, p2)
            gx += 100.0

        gy = 100.0
        while gy < self.bed_height:
            p1 = to_screen(0, gy)
            p2 = to_screen(self.bed_width, gy)
            painter.drawLine(p1, p2)
            gy += 100.0

        # Bed dimensions label
        painter.setFont(QFont("monospace", 7))
        painter.setPen(QColor("#555566"))
        painter.drawText(int(ox + 4), int(oy - self.bed_height * scale + 12), f"0,{self.bed_height:.0f}")
        painter.drawText(int(ox + 4), int(oy - 4), "(0,0)")
        painter.drawText(int(ox + self.bed_width * scale - 45), int(oy - 4), f"{self.bed_width:.0f},0")

        # Source design bounding box (dashed cyan)
        sx1, sy1, sx2, sy2 = self.source_bbox
        sp1 = to_screen(sx1, sy2)
        sp2 = to_screen(sx2, sy1)
        src_rect = QRectF(sp1, sp2).normalized()
        painter.setPen(QPen(QColor("#00bcd4"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(src_rect)

        # Burn Perimeter (bright glowing orange/red)
        px1, py1, px2, py2 = self.perimeter_bbox
        pw = max(0.1, px2 - px1)
        ph = max(0.1, py2 - py1)

        burn_pen_glow = QPen(QColor(255, 87, 34, 70), 5)
        burn_pen = QPen(QColor("#ff5722"), 2, Qt.PenStyle.SolidLine)
        cross_pen = QPen(QColor("#ffd54f"), 1.5, Qt.PenStyle.DashDotLine)

        if self.mode == "hull" and len(self.hull_points) >= 3:
            poly = QPolygonF([to_screen(p[0], p[1]) for p in self.hull_points])
            painter.setPen(burn_pen_glow)
            painter.drawPolygon(poly)
            painter.setPen(burn_pen)
            painter.drawPolygon(poly)

        elif self.mode in ("box", "box_crosshair"):
            p_top_left = to_screen(px1, py2)
            p_bottom_right = to_screen(px2, py1)
            p_rect = QRectF(p_top_left, p_bottom_right).normalized()

            painter.setPen(burn_pen_glow)
            painter.drawRect(p_rect)
            painter.setPen(burn_pen)
            painter.drawRect(p_rect)

            if self.mode == "box_crosshair":
                cx = (px1 + px2) / 2.0
                cy = (py1 + py2) / 2.0
                painter.setPen(cross_pen)
                painter.drawLine(to_screen(px1, cy), to_screen(px2, cy))
                painter.drawLine(to_screen(cx, py1), to_screen(cx, py2))

        elif self.mode == "corners":
            t = max(1.0, min(self.corner_tick_len, pw / 2.0, ph / 2.0))
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
                painter.setPen(burn_pen_glow)
                painter.drawLine(p1, p2)
                painter.setPen(burn_pen)
                painter.drawLine(p1, p2)

        elif self.mode == "crosshair_only":
            cx = (px1 + px2) / 2.0
            cy = (py1 + py2) / 2.0
            painter.setPen(cross_pen)
            painter.drawLine(to_screen(px1, cy), to_screen(px2, cy))
            painter.drawLine(to_screen(cx, py1), to_screen(cx, py2))

        # Dimensions callouts
        painter.setFont(QFont("sans-serif", 8, QFont.Weight.Bold))
        painter.setPen(QColor("#ff9800"))
        dim_text = f"{pw:.1f} × {ph:.1f} mm"
        top_center = to_screen((px1 + px2) / 2.0, py2)
        painter.drawText(int(top_center.x() - 35), int(top_center.y() - 6), dim_text)

        # Laser Head Crosshair (if within bed)
        lx, ly = self.laser_pos
        if 0.0 <= lx <= self.bed_width and 0.0 <= ly <= self.bed_height:
            lp = to_screen(lx, ly)
            painter.setPen(QPen(QColor("#00e676"), 1.5))
            painter.drawLine(int(lp.x() - 8), int(lp.y()), int(lp.x() + 8), int(lp.y()))
            painter.drawLine(int(lp.x()), int(lp.y() - 8), int(lp.x()), int(lp.y() + 8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(lp, 5, 5)


class BurnPerimeterDialog(QDialog):
    """
    Burn Perimeter Tool for workpiece alignment, spoilboard marking, and jig indexing.
    """

    add_to_canvas_requested = pyqtSignal(list)

    def __init__(
        self,
        serial_ctrl: SerialController,
        settings: MachineSettings,
        gcode_gen: GCodeGenerator,
        layer_manager: Optional[LayerManager] = None,
        selected_entities: Optional[List[LaserEntity]] = None,
        all_entities: Optional[List[LaserEntity]] = None,
        custom_bbox: Optional[Tuple[float, float, float, float]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("🔥 Burn Perimeter Tool (Workpiece Alignment)")
        self.resize(760, 560)

        self.serial_ctrl = serial_ctrl
        self.settings = settings
        self.gcode_gen = gcode_gen
        self.layer_manager = layer_manager
        self.selected_entities = selected_entities or []
        self.all_entities = all_entities or []
        self.custom_bbox = custom_bbox

        self.is_streaming = False

        self._init_ui()
        self._connect_signals()
        self._update_scope_selection()
        self._recalculate_perimeter()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        # Header Info Banner
        header = QFrame()
        header.setStyleSheet("background-color: #1e1e28; border-radius: 6px; padding: 6px;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)

        icon_lbl = QLabel("🔥")
        icon_lbl.setStyleSheet("font-size: 20px;")
        h_layout.addWidget(icon_lbl)

        info_lbl = QLabel(
            "<b>Burn Perimeter Alignment Tool:</b> Score or burn precise alignment outlines onto "
            "sacrificial wasteboard, tape, or cardstock to align crooked or pre-cut workpieces with pinpoint precision."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #cfd8dc; font-size: 11px;")
        h_layout.addWidget(info_lbl, 1)

        self.lbl_conn_status = QLabel("CONNECTED" if self.serial_ctrl.is_connected else "DISCONNECTED")
        badge_style = (
            "background-color: #1b5e20; color: #a5d6a7; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 4px;"
            if self.serial_ctrl.is_connected else
            "background-color: #37474f; color: #cfd8dc; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 4px;"
        )
        self.lbl_conn_status.setStyleSheet(badge_style)
        h_layout.addWidget(self.lbl_conn_status)
        root_layout.addWidget(header)

        # Main Split
        main_split = QHBoxLayout()
        main_split.setSpacing(10)

        # LEFT COLUMN: Parameters & Controls
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        # 1. Target Scope Group
        scope_grp = QGroupBox("1. Alignment Target & Stock Boundary")
        scope_layout = QVBoxLayout(scope_grp)
        scope_layout.setSpacing(5)

        self.btn_grp_scope = QButtonGroup(self)
        self.rad_selected = QRadioButton(f"Selected Entities ({len(self.selected_entities)} items)")
        self.rad_all = QRadioButton(f"All Canvas Artwork ({len(self.all_entities)} items)")
        self.rad_custom = QRadioButton("Custom Stock Dimensions")

        self.btn_grp_scope.addButton(self.rad_selected)
        self.btn_grp_scope.addButton(self.rad_all)
        self.btn_grp_scope.addButton(self.rad_custom)

        if self.custom_bbox is not None:
            self.rad_custom.setChecked(True)
        elif self.selected_entities:
            self.rad_selected.setChecked(True)
        elif self.all_entities:
            self.rad_all.setChecked(True)
        else:
            self.rad_custom.setChecked(True)

        self.rad_selected.setEnabled(len(self.selected_entities) > 0)
        self.rad_all.setEnabled(len(self.all_entities) > 0)

        self.rad_selected.toggled.connect(self._on_scope_changed)
        self.rad_all.toggled.connect(self._on_scope_changed)
        self.rad_custom.toggled.connect(self._on_scope_changed)

        scope_layout.addWidget(self.rad_selected)
        scope_layout.addWidget(self.rad_all)
        scope_layout.addWidget(self.rad_custom)

        # Coordinates & Dimensions Grid
        dim_grid = QGridLayout()
        dim_grid.setSpacing(4)

        dim_grid.addWidget(QLabel("X:"), 0, 0)
        self.spin_x = QDoubleSpinBox()
        self.spin_x.setRange(-100.0, self.settings.bed_width + 100.0)
        self.spin_x.setSuffix(" mm")
        self.spin_x.valueChanged.connect(self._on_dim_changed)
        dim_grid.addWidget(self.spin_x, 0, 1)

        dim_grid.addWidget(QLabel("Y:"), 0, 2)
        self.spin_y = QDoubleSpinBox()
        self.spin_y.setRange(-100.0, self.settings.bed_height + 100.0)
        self.spin_y.setSuffix(" mm")
        self.spin_y.valueChanged.connect(self._on_dim_changed)
        dim_grid.addWidget(self.spin_y, 0, 3)

        dim_grid.addWidget(QLabel("Width:"), 1, 0)
        self.spin_w = QDoubleSpinBox()
        self.spin_w.setRange(1.0, self.settings.bed_width)
        self.spin_w.setValue(85.6)
        self.spin_w.setSuffix(" mm")
        self.spin_w.valueChanged.connect(self._on_dim_changed)
        dim_grid.addWidget(self.spin_w, 1, 1)

        dim_grid.addWidget(QLabel("Height:"), 1, 2)
        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(1.0, self.settings.bed_height)
        self.spin_h.setValue(54.0)
        self.spin_h.setSuffix(" mm")
        self.spin_h.valueChanged.connect(self._on_dim_changed)
        dim_grid.addWidget(self.spin_h, 1, 3)

        scope_layout.addLayout(dim_grid)
        left_col.addWidget(scope_grp)

        # 2. Geometry & Style Group
        geom_grp = QGroupBox("2. Perimeter Alignment Geometry")
        geom_layout = QGridLayout(geom_grp)
        geom_layout.setSpacing(6)

        geom_layout.addWidget(QLabel("Pattern:"), 0, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("🔲 Full Bounding Rectangle", "box")
        self.combo_mode.addItem("🎯 Bounding Box + Center Crosshair", "box_crosshair")
        self.combo_mode.addItem("📐 Corner L-Ticks (Corner Stops)", "corners")
        self.combo_mode.addItem("➕ Center Crosshair Only", "crosshair_only")
        self.combo_mode.addItem("🔷 Tight Convex Hull Outline", "hull")
        self.combo_mode.currentIndexChanged.connect(self._recalculate_perimeter)
        geom_layout.addWidget(self.combo_mode, 0, 1)

        geom_layout.addWidget(QLabel("Margin / Offset:"), 1, 0)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(-50.0, 100.0)
        self.spin_margin.setSingleStep(0.5)
        self.spin_margin.setValue(0.0)
        self.spin_margin.setSuffix(" mm")
        self.spin_margin.setToolTip("Expand (+margin) or shrink (-margin) the perimeter relative to artwork bounds")
        self.spin_margin.valueChanged.connect(self._recalculate_perimeter)
        geom_layout.addWidget(self.spin_margin, 1, 1)

        self.lbl_tick_len = QLabel("L-Tick Length:")
        self.spin_tick_len = QDoubleSpinBox()
        self.spin_tick_len.setRange(2.0, 50.0)
        self.spin_tick_len.setValue(8.0)
        self.spin_tick_len.setSuffix(" mm")
        self.spin_tick_len.valueChanged.connect(self._recalculate_perimeter)
        geom_layout.addWidget(self.lbl_tick_len, 2, 0)
        geom_layout.addWidget(self.spin_tick_len, 2, 1)
        self.lbl_tick_len.setVisible(False)
        self.spin_tick_len.setVisible(False)

        left_col.addWidget(geom_grp)

        # 3. Laser Burn Parameters Group
        burn_grp = QGroupBox("3. Laser Cut / Score Parameters")
        burn_layout = QGridLayout(burn_grp)
        burn_layout.setSpacing(6)

        burn_layout.addWidget(QLabel("Preset:"), 0, 0)
        self.combo_presets = QComboBox()
        self.combo_presets.addItem("Custom Settings", None)
        self.combo_presets.addItem("Paper / Cardstock (10% Power, 2000 mm/min)", (10.0, 2000.0, 1))
        self.combo_presets.addItem("Masking / Blue Tape (8% Power, 2500 mm/min)", (8.0, 2500.0, 1))
        self.combo_presets.addItem("Cardboard Template (15% Power, 1800 mm/min)", (15.0, 1800.0, 1))
        self.combo_presets.addItem("Wood / MDF Wasteboard (35% Power, 1200 mm/min)", (35.0, 1200.0, 1))
        self.combo_presets.addItem("Acrylic / Plastic Scrap (25% Power, 1000 mm/min)", (25.0, 1000.0, 1))
        self.combo_presets.addItem("Deep Alignment Score (50% Power, 800 mm/min)", (50.0, 800.0, 1))
        self.combo_presets.currentIndexChanged.connect(self._on_preset_selected)
        burn_layout.addWidget(self.combo_presets, 0, 1)

        burn_layout.addWidget(QLabel("Power:"), 1, 0)
        self.spin_power = QDoubleSpinBox()
        self.spin_power.setRange(1.0, 100.0)
        self.spin_power.setValue(15.0)
        self.spin_power.setSuffix("%")
        burn_layout.addWidget(self.spin_power, 1, 1)

        burn_layout.addWidget(QLabel("Speed:"), 2, 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(100.0, 10000.0)
        self.spin_speed.setSingleStep(100.0)
        self.spin_speed.setValue(1500.0)
        self.spin_speed.setSuffix(" mm/min")
        self.spin_speed.valueChanged.connect(self._update_metrics)
        burn_layout.addWidget(self.spin_speed, 2, 1)

        burn_layout.addWidget(QLabel("Passes:"), 3, 0)
        self.spin_passes = QSpinBox()
        self.spin_passes.setRange(1, 10)
        self.spin_passes.setValue(1)
        self.spin_passes.valueChanged.connect(self._update_metrics)
        burn_layout.addWidget(self.spin_passes, 3, 1)

        self.chk_air = QCheckBox("Air Assist (M8)")
        burn_layout.addWidget(self.chk_air, 4, 1)

        left_col.addWidget(burn_grp)
        left_col.addStretch(1)
        main_split.addLayout(left_col, 5)

        # RIGHT COLUMN: Visualization & Action
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # Visual Widget
        self.visual_widget = BurnPerimeterVisualWidget(
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height,
            parent=self
        )
        right_col.addWidget(self.visual_widget, 1)

        # Metrics Readout
        self.lbl_metrics = QLabel("Perimeter: 0.0 mm | Estimated Time: 0.0s")
        self.lbl_metrics.setStyleSheet(
            "background-color: #1a1a24; color: #ffd54f; font-weight: bold; font-family: monospace; "
            "padding: 5px 8px; border-radius: 4px; font-size: 11px;"
        )
        self.lbl_metrics.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_col.addWidget(self.lbl_metrics)

        # Stream Progress Bar
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setVisible(False)
        self.prog_bar.setStyleSheet(
            "QProgressBar { background-color: #242432; border-radius: 4px; text-align: center; font-weight: bold; color: white; } "
            "QProgressBar::chunk { background-color: #ff5722; border-radius: 4px; }"
        )
        right_col.addWidget(self.prog_bar)

        # CAD Layer Options
        cad_row = QHBoxLayout()
        cad_row.addWidget(QLabel("Target CAD Layer:"))
        self.combo_layer = QComboBox()
        if self.layer_manager:
            for lyr in self.layer_manager.get_all_layers():
                label = f"Layer {lyr.layer_id} ({lyr.name}) - {lyr.mode}"
                self.combo_layer.addItem(label, lyr.layer_id)
        else:
            self.combo_layer.addItem("Layer 12 (T1 Tool / Guide)", 12)
            self.combo_layer.addItem("Layer 2 (Red C02 / Cut)", 2)
            self.combo_layer.addItem("Layer 1 (Blue C01 / Score)", 1)
        # Select Tool Layer T1 (12) by default
        idx_t1 = self.combo_layer.findData(12)
        if idx_t1 != -1:
            self.combo_layer.setCurrentIndex(idx_t1)
        cad_row.addWidget(self.combo_layer, 1)

        self.btn_add_to_canvas = QPushButton("➕ Add to Canvas")
        self.btn_add_to_canvas.setToolTip("Insert perimeter geometry onto the selected CAD layer")
        self.btn_add_to_canvas.setStyleSheet("background-color: #0277bd; color: white; font-weight: bold; padding: 5px 10px;")
        self.btn_add_to_canvas.clicked.connect(self._add_to_canvas)
        cad_row.addWidget(self.btn_add_to_canvas)
        right_col.addLayout(cad_row)

        # Primary Laser Actions
        act_box = QGroupBox("Laser Machine Execution")
        act_layout = QVBoxLayout(act_box)
        act_layout.setSpacing(6)

        btn_row1 = QHBoxLayout()
        self.btn_frame_guide = QPushButton("🔦 Frame First (0.5% Guide Beam)")
        self.btn_frame_guide.setToolTip("Traces perimeter with non-marking optical guide beam before burning")
        self.btn_frame_guide.setStyleSheet("background-color: #00796b; color: white; font-weight: bold; padding: 7px;")
        self.btn_frame_guide.clicked.connect(self._run_framing_guide)
        btn_row1.addWidget(self.btn_frame_guide, 1)

        self.btn_burn_now = QPushButton("🔥 Burn Perimeter Now")
        self.btn_burn_now.setToolTip("Fires laser and burns the alignment perimeter on material")
        self.btn_burn_now.setStyleSheet(
            "background-color: #d84315; color: white; font-weight: bold; padding: 7px; font-size: 12px;"
        )
        self.btn_burn_now.clicked.connect(self._burn_perimeter_now)
        btn_row1.addWidget(self.btn_burn_now, 2)
        act_layout.addLayout(btn_row1)

        # Control Row (Pause/Stop during burn)
        self.ctrl_row = QHBoxLayout()
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setStyleSheet("background-color: #f57f17; color: white; font-weight: bold;")
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop = QPushButton("⏹ Emergency Stop")
        self.btn_stop.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")
        self.btn_stop.clicked.connect(self._stop_laser)
        self.ctrl_row.addWidget(self.btn_pause)
        self.ctrl_row.addWidget(self.btn_stop)
        self.ctrl_row_widget = QWidget()
        self.ctrl_row_widget.setLayout(self.ctrl_row)
        self.ctrl_row_widget.setVisible(False)
        act_layout.addWidget(self.ctrl_row_widget)

        right_col.addWidget(act_box)
        main_split.addLayout(right_col, 6)
        root_layout.addLayout(main_split, 1)

        # Bottom Bar: Copy G-Code & Close
        bot_row = QHBoxLayout()
        self.btn_copy_gcode = QPushButton("📋 Copy Perimeter G-Code")
        self.btn_copy_gcode.clicked.connect(self._copy_gcode)
        bot_row.addWidget(self.btn_copy_gcode)

        bot_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.close)
        bot_row.addWidget(btn_close)
        root_layout.addLayout(bot_row)

    def _connect_signals(self):
        self.serial_ctrl.connected.connect(lambda _: self._update_connection_ui(True))
        self.serial_ctrl.disconnected.connect(lambda: self._update_connection_ui(False))
        self.serial_ctrl.status_updated.connect(self._on_status_updated)
        self.serial_ctrl.job_progress.connect(self._on_job_progress)
        self.serial_ctrl.job_finished.connect(self._on_job_finished)

    def _update_connection_ui(self, connected: bool):
        if connected:
            self.lbl_conn_status.setText("CONNECTED")
            self.lbl_conn_status.setStyleSheet(
                "background-color: #1b5e20; color: #a5d6a7; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 4px;"
            )
        else:
            self.lbl_conn_status.setText("DISCONNECTED")
            self.lbl_conn_status.setStyleSheet(
                "background-color: #37474f; color: #cfd8dc; font-weight: bold; font-size: 10px; padding: 3px 8px; border-radius: 4px;"
            )

    def _on_status_updated(self, status: dict):
        mpos = status.get("mpos", (0.0, 0.0, 0.0))
        wpos = status.get("wpos", (0.0, 0.0, 0.0))
        cur_x = wpos[0] if wpos else mpos[0]
        cur_y = wpos[1] if wpos else mpos[1]
        self.visual_widget.laser_pos = (cur_x, cur_y)
        self.visual_widget.update()

    def _on_scope_changed(self):
        is_custom = self.rad_custom.isChecked()
        self.spin_x.setEnabled(is_custom)
        self.spin_y.setEnabled(is_custom)
        self.spin_w.setEnabled(is_custom)
        self.spin_h.setEnabled(is_custom)
        self._update_scope_selection()

    def _update_scope_selection(self):
        if self.rad_selected.isChecked() and self.selected_entities:
            target = self.selected_entities
            bounds = self.gcode_gen._resolve_target_bounds(target)
        elif self.rad_all.isChecked() and self.all_entities:
            target = self.all_entities
            bounds = self.gcode_gen._resolve_target_bounds(target)
        elif self.custom_bbox is not None and not self.rad_all.isChecked() and not self.rad_selected.isChecked():
            bounds = self.custom_bbox
        else:
            bounds = (
                self.spin_x.value(),
                self.spin_y.value(),
                self.spin_x.value() + self.spin_w.value(),
                self.spin_y.value() + self.spin_h.value()
            )

        if bounds:
            x1, y1, x2, y2 = bounds
            self.spin_x.blockSignals(True)
            self.spin_y.blockSignals(True)
            self.spin_w.blockSignals(True)
            self.spin_h.blockSignals(True)
            self.spin_x.setValue(x1)
            self.spin_y.setValue(y1)
            self.spin_w.setValue(max(0.1, x2 - x1))
            self.spin_h.setValue(max(0.1, y2 - y1))
            self.spin_x.blockSignals(False)
            self.spin_y.blockSignals(False)
            self.spin_w.blockSignals(False)
            self.spin_h.blockSignals(False)

        self._recalculate_perimeter()

    def _on_dim_changed(self):
        if self.rad_custom.isChecked():
            self._recalculate_perimeter()

    def _on_preset_selected(self, index: int):
        data = self.combo_presets.currentData()
        if data:
            power, speed, passes = data
            self.spin_power.setValue(power)
            self.spin_speed.setValue(speed)
            self.spin_passes.setValue(passes)

    def _get_target(self) -> Any:
        if self.rad_selected.isChecked() and self.selected_entities:
            return self.selected_entities
        elif self.rad_all.isChecked() and self.all_entities:
            return self.all_entities
        else:
            x = self.spin_x.value()
            y = self.spin_y.value()
            w = self.spin_w.value()
            h = self.spin_h.value()
            return (x, y, x + w, y + h)

    def _recalculate_perimeter(self):
        mode = self.combo_mode.currentData() or "box"
        self.lbl_tick_len.setVisible(mode == "corners")
        self.spin_tick_len.setVisible(mode == "corners")

        x1 = self.spin_x.value()
        y1 = self.spin_y.value()
        w = self.spin_w.value()
        h = self.spin_h.value()
        margin = self.spin_margin.value()

        source_bbox = (x1, y1, x1 + w, y1 + h)
        px1 = max(0.0, x1 - margin)
        py1 = max(0.0, y1 - margin)
        px2 = min(self.settings.bed_width, x1 + w + margin)
        py2 = min(self.settings.bed_height, y1 + h + margin)
        perimeter_bbox = (px1, py1, px2, py2)

        hull_pts: List[Tuple[float, float]] = []
        if mode == "hull":
            target = self._get_target()
            if isinstance(target, list) and target:
                all_pts = []
                for ent in target:
                    for path in self.gcode_gen.entity_to_paths(ent):
                        all_pts.extend(path)
                hull = self.gcode_gen._compute_convex_hull(all_pts) if len(all_pts) >= 3 else []
                if len(hull) >= 3 and margin != 0.0:
                    cx = sum(p[0] for p in hull) / len(hull)
                    cy = sum(p[1] for p in hull) / len(hull)
                    expanded = []
                    for px, py in hull:
                        dx, dy = px - cx, py - cy
                        d = math.hypot(dx, dy)
                        if d > 1e-6:
                            sc = (d + margin) / d
                            expanded.append((
                                max(0.0, min(self.settings.bed_width, cx + dx * sc)),
                                max(0.0, min(self.settings.bed_height, cy + dy * sc))
                            ))
                        else:
                            expanded.append((px, py))
                    hull = expanded
                hull_pts = hull

        self.visual_widget.update_geometry_state(
            source_bbox=source_bbox,
            perimeter_bbox=perimeter_bbox,
            mode=mode,
            corner_tick_len=self.spin_tick_len.value(),
            hull_points=hull_pts
        )
        self._update_metrics()

    def _calculate_perimeter_distance(self) -> float:
        mode = self.combo_mode.currentData() or "box"
        px1, py1, px2, py2 = self.visual_widget.perimeter_bbox
        w = max(0.0, px2 - px1)
        h = max(0.0, py2 - py1)

        if mode == "box":
            return (w + h) * 2.0
        elif mode == "box_crosshair":
            return (w + h) * 2.0 + w + h
        elif mode == "corners":
            t = max(1.0, min(self.spin_tick_len.value(), w / 2.0, h / 2.0))
            return 8.0 * t
        elif mode == "crosshair_only":
            return w + h
        elif mode == "hull" and len(self.visual_widget.hull_points) >= 3:
            pts = self.visual_widget.hull_points
            dist = 0.0
            for i in range(len(pts)):
                p1 = pts[i]
                p2 = pts[(i + 1) % len(pts)]
                dist += math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            return dist
        return (w + h) * 2.0

    def _update_metrics(self):
        dist_one_pass = self._calculate_perimeter_distance()
        passes = self.spin_passes.value()
        total_dist = dist_one_pass * passes
        speed = max(1.0, self.spin_speed.value())
        time_sec = (total_dist / speed) * 60.0

        self.lbl_metrics.setText(
            f"Perimeter: {dist_one_pass:.1f} mm | Total Cut: {total_dist:.1f} mm ({passes} pass) | Est. Time: {time_sec:.1f}s"
        )

    def _build_gcode(self, override_power_pct: Optional[float] = None, override_speed: Optional[float] = None) -> str:
        target = self._get_target()
        mode = self.combo_mode.currentData() or "box"
        margin = self.spin_margin.value()
        power = override_power_pct if override_power_pct is not None else self.spin_power.value()
        speed = override_speed if override_speed is not None else self.spin_speed.value()
        passes = 1 if override_power_pct is not None else self.spin_passes.value()
        tick_len = self.spin_tick_len.value()
        air = self.chk_air.isChecked()

        return self.gcode_gen.generate_burn_perimeter_gcode(
            target=target,
            mode=mode,
            margin_mm=margin,
            power_pct=power,
            speed=speed,
            passes=passes,
            corner_tick_len_mm=tick_len,
            air_assist=air
        )

    def _run_framing_guide(self):
        """Runs a low-power non-marking guide beam along the exact perimeter."""
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Laser Not Connected", "Please connect to the laser machine first.")
            return

        frame_power = getattr(self.settings, "framing_power_pct", 0.5)
        frame_speed = getattr(self.settings, "framing_speed", 2000.0)
        gcode = self._build_gcode(override_power_pct=frame_power, override_speed=frame_speed)

        if not gcode:
            QMessageBox.warning(self, "Framing Error", "Could not generate perimeter framing G-code.")
            return

        self._set_streaming_ui(True)
        self.serial_ctrl.start_job(gcode)

    def _burn_perimeter_now(self):
        """Streams the burn perimeter G-code to the connected laser."""
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Laser Not Connected", "Please connect to the laser machine first.")
            return

        gcode = self._build_gcode()
        if not gcode:
            QMessageBox.warning(self, "Burn Error", "Could not generate perimeter burn G-code.")
            return

        # Safety confirmation
        res = QMessageBox.warning(
            self,
            "Confirm Laser Perimeter Burn",
            f"You are about to burn an alignment perimeter onto the bed/material:\n\n"
            f"• Mode: {self.combo_mode.currentText()}\n"
            f"• Power: {self.spin_power.value():.1f}%\n"
            f"• Speed: {self.spin_speed.value():.0f} mm/min\n"
            f"• Passes: {self.spin_passes.value()}\n\n"
            f"⚠️ SAFETY CHECK: Ensure protective laser goggles are on and sacrificial wasteboard "
            f"or test stock is properly placed on the bed.\n\n"
            f"Do you want to fire the laser now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        self._set_streaming_ui(True)
        self.serial_ctrl.start_job(gcode)

    def _set_streaming_ui(self, running: bool):
        self.is_streaming = running
        self.btn_burn_now.setEnabled(not running)
        self.btn_frame_guide.setEnabled(not running)
        self.ctrl_row_widget.setVisible(running)
        self.prog_bar.setVisible(running)
        if running:
            self.prog_bar.setValue(0)

    def _toggle_pause(self):
        if self.serial_ctrl.is_paused:
            self.serial_ctrl.resume_job()
            self.btn_pause.setText("⏸ Pause")
            self.btn_pause.setStyleSheet("background-color: #f57f17; color: white; font-weight: bold;")
        else:
            self.serial_ctrl.pause_job()
            self.btn_pause.setText("▶ Resume")
            self.btn_pause.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")

    def _stop_laser(self):
        self.serial_ctrl.stop_streaming()
        self._set_streaming_ui(False)

    def _on_job_progress(self, current_line: int, total_lines: int):
        if total_lines > 0:
            pct = int(round((current_line / total_lines) * 100))
            self.prog_bar.setValue(pct)

    def _on_job_finished(self):
        if self.is_streaming:
            self._set_streaming_ui(False)
            QMessageBox.information(self, "Burn Complete", "Perimeter burn operation finished successfully!")

    def _add_to_canvas(self):
        target = self._get_target()
        mode = self.combo_mode.currentData() or "box"
        margin = self.spin_margin.value()
        layer_id = self.combo_layer.currentData()
        if layer_id is None:
            layer_id = 12
        tick_len = self.spin_tick_len.value()

        entities = self.gcode_gen.generate_burn_perimeter_entities(
            target=target,
            mode=mode,
            margin_mm=margin,
            layer_id=layer_id,
            corner_tick_len_mm=tick_len
        )

        if not entities:
            QMessageBox.warning(self, "Error", "Could not generate vector perimeter entities.")
            return

        self.add_to_canvas_requested.emit(entities)
        QMessageBox.information(
            self,
            "Perimeter Added",
            f"Added {len(entities)} alignment perimeter shape(s) to Layer {layer_id} on canvas!"
        )

    def _copy_gcode(self):
        gcode = self._build_gcode()
        if gcode:
            QApplication.clipboard().setText(gcode)
            QMessageBox.information(self, "G-Code Copied", "Perimeter alignment G-code copied to clipboard!")
        else:
            QMessageBox.warning(self, "Error", "No G-code generated to copy.")

    def closeEvent(self, event):
        if self.is_streaming:
            self.serial_ctrl.stop_streaming()
        super().closeEvent(event)
