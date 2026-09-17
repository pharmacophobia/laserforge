"""
LaserForge Interactive Directional Vector Hatching Studio Dialog.

Provides real-time interactive preview, neighbor graph visualization,
fine-tuning for center-to-edge angular divergence, line spacing,
and 15° neighbor separation constraint enforcement.
"""

from typing import List, Tuple, Optional, Dict, Any, Set
import math
import numpy as np

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QGroupBox, QSplitter, QFrame, QMessageBox,
    QScrollArea
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QWheelEvent,
    QMouseEvent, QPaintEvent, QPainterPath, QFont
)

from laserforge.config import LAYER_PALETTE
from laserforge.core.models import LaserEntity, PathEntity
from laserforge.core.directional_hatch import (
    DirectionalHatchGenerator, DirectionalHatchSettings, DirectionalHatchResult,
    VectorPolygon, angular_difference
)


class DirectionalHatchCanvas(QWidget):
    """
    Interactive zoomable & pannable preview canvas showing:
    - Extracted closed vector polygon contours
    - Directional hatched laser cut lines inside each polygon
    - Centroid direction indicator arrows and angles
    - Spatial neighbor graph connectivity
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.polygons: List[VectorPolygon] = []
        self.neighbors: Dict[int, List[int]] = {}
        self.assigned_angles: Dict[int, float] = {}
        self.hatched_entities: List[PathEntity] = []

        self.show_neighbor_graph: bool = True
        self.show_direction_arrows: bool = True
        self.show_angle_labels: bool = True
        self.color_by_angle: bool = True
        self.show_outer_bounds: bool = True

        self.zoom: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0
        self._panning: bool = False
        self._last_mouse = QPointF()

        self.setMinimumSize(500, 480)
        self.setStyleSheet("background-color: #121218; border: 1px solid #2a2a38; border-radius: 6px;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_data(
        self,
        polygons: List[VectorPolygon],
        neighbors: Dict[int, List[int]],
        assigned_angles: Dict[int, float],
        hatched_entities: List[PathEntity]
    ):
        self.polygons = polygons
        self.neighbors = neighbors
        self.assigned_angles = assigned_angles
        self.hatched_entities = hatched_entities
        self.update()

    def reset_view(self):
        if not self.polygons:
            self.zoom = 1.0
            self.pan_x = 0.0
            self.pan_y = 0.0
            self.update()
            return

        all_min_x = min(p.bounds[0] for p in self.polygons)
        all_min_y = min(p.bounds[1] for p in self.polygons)
        all_max_x = max(p.bounds[2] for p in self.polygons)
        all_max_y = max(p.bounds[3] for p in self.polygons)

        w = max(10.0, all_max_x - all_min_x)
        h = max(10.0, all_max_y - all_min_y)

        avail_w = max(50, self.width() - 80)
        avail_h = max(50, self.height() - 80)

        scale_x = avail_w / w
        scale_y = avail_h / h
        self.zoom = min(scale_x, scale_y)

        center_x = (all_min_x + all_max_x) / 2.0
        center_y = (all_min_y + all_max_y) / 2.0

        self.pan_x = (self.width() / 2.0) - (center_x * self.zoom)
        self.pan_y = (self.height() / 2.0) - (center_y * self.zoom)
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        new_zoom = max(0.05, min(100.0, self.zoom * factor))

        mpos = event.position()
        self.pan_x = mpos.x() - (mpos.x() - self.pan_x) * (new_zoom / self.zoom)
        self.pan_y = mpos.y() - (mpos.y() - self.pan_y) * (new_zoom / self.zoom)
        self.zoom = new_zoom
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self._panning = True
            self._last_mouse = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.position() - self._last_mouse
            self._last_mouse = event.position()
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._panning = False

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw dark grid
        w = self.width()
        h = self.height()
        painter.fillRect(0, 0, w, h, QColor("#14141d"))

        # Grid lines (50mm in world coords)
        grid_step = 25.0 * self.zoom
        if grid_step > 8.0:
            pen_grid = QPen(QColor("#1e1e2c"), 1, Qt.PenStyle.DotLine)
            painter.setPen(pen_grid)
            start_x = self.pan_x % grid_step
            while start_x < w:
                painter.drawLine(int(start_x), 0, int(start_x), h)
                start_x += grid_step
            start_y = self.pan_y % grid_step
            while start_y < h:
                painter.drawLine(0, int(start_y), w, int(start_y))
                start_y += grid_step

        if not self.polygons:
            painter.setPen(QColor("#666680"))
            painter.setFont(QFont("sans-serif", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No vector shapes loaded for hatching")
            return

        def world_to_screen(wx: float, wy: float) -> QPointF:
            return QPointF(self.pan_x + wx * self.zoom, self.pan_y + wy * self.zoom)

        # 1. Draw Neighbor Graph Edges (if enabled)
        if self.show_neighbor_graph and self.neighbors:
            painter.setPen(QPen(QColor(80, 140, 255, 75), 1, Qt.PenStyle.DashLine))
            drawn_edges: Set[Tuple[int, int]] = set()
            for u, n_list in self.neighbors.items():
                cu = world_to_screen(self.polygons[u].centroid[0], self.polygons[u].centroid[1])
                for v in n_list:
                    edge = (min(u, v), max(u, v))
                    if edge not in drawn_edges and v < len(self.polygons):
                        drawn_edges.add(edge)
                        cv = world_to_screen(self.polygons[v].centroid[0], self.polygons[v].centroid[1])
                        painter.drawLine(cu, cv)

        # 2. Draw Polygon Hatch Lines and Boundaries
        for poly in self.polygons:
            idx = poly.index
            ang = self.assigned_angles.get(idx, 90.0)

            # Color generation
            if self.color_by_angle:
                # Map angle [0, 180) to HSL hue [0, 360)
                hue = int((ang % 180.0) * 2.0)
                line_color = QColor.fromHsl(hue, 220, 180)
                bound_color = QColor.fromHsl(hue, 240, 130)
            else:
                line_color = QColor("#00E5FF")
                bound_color = QColor("#FFFFFF")

            # Draw outer polygon boundary
            if self.show_outer_bounds and poly.outer_contour:
                p_path = QPainterPath()
                p0 = world_to_screen(poly.outer_contour[0][0], poly.outer_contour[0][1])
                p_path.moveTo(p0)
                for pt in poly.outer_contour[1:]:
                    p_path.lineTo(world_to_screen(pt[0], pt[1]))
                p_path.closeSubpath()

                for hole in poly.holes:
                    if hole:
                        h0 = world_to_screen(hole[0][0], hole[0][1])
                        p_path.moveTo(h0)
                        for pt in hole[1:]:
                            p_path.lineTo(world_to_screen(pt[0], pt[1]))
                        p_path.closeSubpath()

                # Soft transparent fill
                fill_color = QColor(bound_color)
                fill_color.setAlpha(18)
                painter.fillPath(p_path, QBrush(fill_color))

                pen_bound = QPen(bound_color, max(1.0, 1.2 * (self.zoom ** 0.3)))
                painter.setPen(pen_bound)
                painter.drawPath(p_path)

            # Draw hatched lines for this entity
            if idx < len(self.hatched_entities):
                ent = self.hatched_entities[idx]
                pen_hatch = QPen(line_color, max(1.0, 0.8 * (self.zoom ** 0.3)))
                painter.setPen(pen_hatch)

                # Skip outer contour if keep_original_contours was prepended
                start_c_idx = 0
                if len(ent.contours) > 0 and ent.contours[0] == poly.outer_contour:
                    start_c_idx = 1 + len(poly.holes)

                for c in ent.contours[start_c_idx:]:
                    if len(c) >= 2:
                        sp_path = QPainterPath()
                        sp_path.moveTo(world_to_screen(ent.x + c[0][0], ent.y + c[0][1]))
                        for pt in c[1:]:
                            sp_path.lineTo(world_to_screen(ent.x + pt[0], ent.y + pt[1]))
                        painter.drawPath(sp_path)

            # 3. Draw Centroid Indicator Arrow & Angle Label
            cx, cy = poly.centroid
            sc_c = world_to_screen(cx, cy)

            if self.show_direction_arrows:
                rad = math.radians(ang)
                arrow_len = max(12.0, min(35.0, 20.0 * (self.zoom ** 0.5)))
                dx = math.cos(rad) * arrow_len
                dy = math.sin(rad) * arrow_len

                painter.setPen(QPen(QColor("#FFFFFF"), 2))
                painter.drawLine(
                    QPointF(sc_c.x() - dx, sc_c.y() - dy),
                    QPointF(sc_c.x() + dx, sc_c.y() + dy)
                )
                # Centroid dot
                painter.setBrush(QBrush(QColor("#FFCC00")))
                painter.setPen(QPen(QColor("#000000"), 1))
                painter.drawEllipse(sc_c, 3, 3)

            if self.show_angle_labels and self.zoom > 0.4:
                painter.setFont(QFont("monospace", 8, QFont.Weight.Bold))
                painter.setPen(QColor("#FFFFFF"))
                label_txt = f"{ang:.0f}°"
                painter.drawText(int(sc_c.x() + 6), int(sc_c.y() - 6), label_txt)

        # Draw HUD info
        painter.setFont(QFont("sans-serif", 9))
        painter.setPen(QColor("#8c8ca0"))
        hud = f"Zoom: {self.zoom * 100:.0f}%  |  Vectors: {len(self.polygons)}  |  Pan: Drag with middle/right mouse"
        painter.drawText(12, self.height() - 12, hud)


class DirectionalHatchDialog(QDialog):
    """
    Interactive Studio Dialog for Directional Vector Hatching.
    Allows user to tune line spacing, divergence, constraints, and preview results.
    """
    def __init__(
        self,
        entities: List[LaserEntity],
        active_layer_id: int = 1,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Directional Vector Hatching Studio — Multi-Angle Vector Infill")
        self.resize(1120, 720)
        self.setMinimumSize(880, 560)

        self.source_entities = entities
        self.active_layer_id = active_layer_id
        self.result: Optional[DirectionalHatchResult] = None
        self.output_mode: str = "new"  # "new" or "replace"

        # Internal debounce timer for live regeneration
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(180)
        self._update_timer.timeout.connect(self._run_generation)

        self._build_ui()
        # Initial generation
        self._run_generation()
        self.canvas.reset_view()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left: Canvas Preview Area
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.canvas = DirectionalHatchCanvas(self)
        left_layout.addWidget(self.canvas, 1)

        # Canvas bottom toolbar
        tb_layout = QHBoxLayout()
        btn_reset_zoom = QPushButton("🔍 Fit Artwork")
        btn_reset_zoom.clicked.connect(self.canvas.reset_view)
        tb_layout.addWidget(btn_reset_zoom)

        self.chk_show_graph = QCheckBox("Show Neighbor Graph")
        self.chk_show_graph.setChecked(True)
        self.chk_show_graph.toggled.connect(self._toggle_graph)
        tb_layout.addWidget(self.chk_show_graph)

        self.chk_show_arrows = QCheckBox("Direction Arrows")
        self.chk_show_arrows.setChecked(True)
        self.chk_show_arrows.toggled.connect(self._toggle_arrows)
        tb_layout.addWidget(self.chk_show_arrows)

        self.chk_color_angle = QCheckBox("Color by Angle")
        self.chk_color_angle.setChecked(True)
        self.chk_color_angle.toggled.connect(self._toggle_color_mode)
        tb_layout.addWidget(self.chk_color_angle)

        tb_layout.addStretch()
        left_layout.addLayout(tb_layout)
        splitter.addWidget(left_widget)

        # Right: Parameters & Controls Panel
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(380)
        right_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(14)

        # Group 1: Hatching Pattern
        grp_hatch = QGroupBox("Vector Hatching Parameters")
        grp_hatch_lay = QGridLayout(grp_hatch)
        grp_hatch_lay.setSpacing(8)

        grp_hatch_lay.addWidget(QLabel("Line Spacing (mm):"), 0, 0)
        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 10.0)
        self.spin_spacing.setSingleStep(0.1)
        self.spin_spacing.setValue(1.0)
        self.spin_spacing.setDecimals(2)
        self.spin_spacing.valueChanged.connect(self._schedule_update)
        grp_hatch_lay.addWidget(self.spin_spacing, 0, 1)

        grp_hatch_lay.addWidget(QLabel("Baseline Orientation:"), 1, 0)
        self.spin_baseline = QDoubleSpinBox()
        self.spin_baseline.setRange(0.0, 180.0)
        self.spin_baseline.setValue(90.0)  # Vertical lines
        self.spin_baseline.setSuffix("° (Vertical)")
        self.spin_baseline.valueChanged.connect(self._schedule_update)
        grp_hatch_lay.addWidget(self.spin_baseline, 1, 1)

        self.chk_cross_hatch = QCheckBox("Cross Hatch (Dual Perpendicular)")
        self.chk_cross_hatch.setChecked(False)
        self.chk_cross_hatch.toggled.connect(self._schedule_update)
        grp_hatch_lay.addWidget(self.chk_cross_hatch, 2, 0, 1, 2)

        self.chk_serpentine = QCheckBox("Serpentine Pass (Zig-Zag Laser Cut)")
        self.chk_serpentine.setChecked(True)
        self.chk_serpentine.setToolTip("Alternates cut direction to eliminate wasteful laser rapid moves")
        self.chk_serpentine.toggled.connect(self._schedule_update)
        grp_hatch_lay.addWidget(self.chk_serpentine, 3, 0, 1, 2)

        right_layout.addWidget(grp_hatch)

        # Group 2: Neighbor Constraints & Divergence
        grp_rules = QGroupBox("Angular Gradient & Separation Rules")
        grp_rules_lay = QGridLayout(grp_rules)
        grp_rules_lay.setSpacing(8)

        grp_rules_lay.addWidget(QLabel("Min Neighbor Diff:"), 0, 0)
        self.spin_min_diff = QDoubleSpinBox()
        self.spin_min_diff.setRange(5.0, 45.0)
        self.spin_min_diff.setValue(15.0)
        self.spin_min_diff.setSuffix("°")
        self.spin_min_diff.setToolTip("Strict rule: No two adjacent/neighboring vectors will ever have lines closer than this angle")
        self.spin_min_diff.valueChanged.connect(self._schedule_update)
        grp_rules_lay.addWidget(self.spin_min_diff, 0, 1)

        grp_rules_lay.addWidget(QLabel("Center Divergence:"), 1, 0)
        self.spin_center_div = QDoubleSpinBox()
        self.spin_center_div.setRange(20.0, 90.0)
        self.spin_center_div.setValue(75.0)
        self.spin_center_div.setSuffix("°")
        self.spin_center_div.setToolTip("Maximum angular divergence between vectors in the center of the artwork")
        self.spin_center_div.valueChanged.connect(self._schedule_update)
        grp_rules_lay.addWidget(self.spin_center_div, 1, 1)

        grp_rules_lay.addWidget(QLabel("Edge Convergence:"), 2, 0)
        self.spin_edge_div = QDoubleSpinBox()
        self.spin_edge_div.setRange(0.0, 30.0)
        self.spin_edge_div.setValue(10.0)
        self.spin_edge_div.setSuffix("°")
        self.spin_edge_div.setToolTip("Max deviation from vertical near the perimeter boundary")
        self.spin_edge_div.valueChanged.connect(self._schedule_update)
        grp_rules_lay.addWidget(self.spin_edge_div, 2, 1)

        # Random Seed & Regenerate button
        h_seed = QHBoxLayout()
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(1, 999999)
        self.spin_seed.setValue(42)
        self.spin_seed.valueChanged.connect(self._schedule_update)
        btn_seed = QPushButton("🎲 New Seed")
        btn_seed.clicked.connect(self._randomize_seed)
        h_seed.addWidget(self.spin_seed)
        h_seed.addWidget(btn_seed)
        grp_rules_lay.addLayout(h_seed, 3, 0, 1, 2)

        right_layout.addWidget(grp_rules)

        # Group 3: Layer & Output Options
        grp_out = QGroupBox("Output & Layer Settings")
        grp_out_lay = QGridLayout(grp_out)
        grp_out_lay.setSpacing(8)

        grp_out_lay.addWidget(QLabel("Target Layer:"), 0, 0)
        self.combo_layer = QComboBox()
        for lyr in LAYER_PALETTE:
            if not lyr.get("is_tool", False):
                self.combo_layer.addItem(f"{lyr['name']} ({lyr['label']})", lyr["id"])
        # Set active layer
        idx = self.combo_layer.findData(self.active_layer_id)
        if idx >= 0:
            self.combo_layer.setCurrentIndex(idx)
        self.combo_layer.currentIndexChanged.connect(self._schedule_update)
        grp_out_lay.addWidget(self.combo_layer, 0, 1)

        self.chk_keep_contours = QCheckBox("Keep Original Perimeter Contours")
        self.chk_keep_contours.setChecked(True)
        self.chk_keep_contours.setToolTip("Include the outer closed boundary vector line with the hatched lines")
        self.chk_keep_contours.toggled.connect(self._schedule_update)
        grp_out_lay.addWidget(self.chk_keep_contours, 1, 0, 1, 2)

        grp_out_lay.addWidget(QLabel("Output Mode:"), 2, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Add to Canvas as New Paths", "new")
        self.combo_mode.addItem("Replace Selected Vectors", "replace")
        grp_out_lay.addWidget(self.combo_mode, 2, 1)

        right_layout.addWidget(grp_out)

        # Group 4: Live Statistics & Constraint Status
        grp_stats = QGroupBox("Hatching Metrics & Verification")
        grp_stats_lay = QVBoxLayout(grp_stats)
        grp_stats_lay.setSpacing(6)

        self.lbl_stat_vectors = QLabel("Shapes Extracted: 0")
        self.lbl_stat_lines = QLabel("Total Hatch Lines: 0")
        self.lbl_stat_length = QLabel("Total Cut Path: 0.00 mm")
        self.lbl_stat_min_diff = QLabel("Min Neighbor Separation: --")
        self.lbl_stat_center_diff = QLabel("Center Neighbor Separation: --")

        grp_stats_lay.addWidget(self.lbl_stat_vectors)
        grp_stats_lay.addWidget(self.lbl_stat_lines)
        grp_stats_lay.addWidget(self.lbl_stat_length)
        grp_stats_lay.addWidget(self.lbl_stat_min_diff)
        grp_stats_lay.addWidget(self.lbl_stat_center_diff)

        right_layout.addWidget(grp_stats)
        right_layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        self.btn_apply = QPushButton("Apply Hatching to Canvas")
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #0088cc;
                color: white;
                font-weight: bold;
                padding: 9px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0099ee;
            }
        """)
        self.btn_apply.clicked.connect(self.accept)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_apply)
        right_layout.addLayout(btn_layout)

        right_scroll.setWidget(right_widget)
        splitter.addWidget(right_scroll)
        splitter.setSizes([740, 380])

    def _schedule_update(self):
        self._update_timer.start()

    def _randomize_seed(self):
        import random
        self.spin_seed.setValue(random.randint(1, 999999))

    def _toggle_graph(self, checked: bool):
        self.canvas.show_neighbor_graph = checked
        self.canvas.update()

    def _toggle_arrows(self, checked: bool):
        self.canvas.show_direction_arrows = checked
        self.canvas.show_angle_labels = checked
        self.canvas.update()

    def _toggle_color_mode(self, checked: bool):
        self.canvas.color_by_angle = checked
        self.canvas.update()

    def _run_generation(self):
        target_layer = self.combo_layer.currentData()
        if target_layer is None:
            target_layer = 1

        settings = DirectionalHatchSettings(
            line_spacing_mm=self.spin_spacing.value(),
            min_neighbor_angle_diff=self.spin_min_diff.value(),
            center_divergence_deg=self.spin_center_div.value(),
            edge_divergence_deg=self.spin_edge_div.value(),
            baseline_angle_deg=self.spin_baseline.value(),
            cross_hatch=self.chk_cross_hatch.isChecked(),
            keep_original_contours=self.chk_keep_contours.isChecked(),
            target_layer_id=target_layer,
            serpentine_toolpath=self.chk_serpentine.isChecked(),
            random_seed=self.spin_seed.value()
        )

        res = DirectionalHatchGenerator.generate(self.source_entities, settings)
        self.result = res
        self.output_mode = self.combo_mode.currentData() or "new"

        # Update preview canvas
        self.canvas.set_data(
            polygons=res.polygons,
            neighbors=res.neighbors,
            assigned_angles=res.assigned_angles,
            hatched_entities=res.hatched_entities
        )

        # Update metrics
        n_polys = len(res.polygons)
        self.lbl_stat_vectors.setText(f"Shapes Extracted: <b>{n_polys}</b> unconnected vectors")
        self.lbl_stat_lines.setText(f"Total Hatch Lines: <b>{res.total_line_count}</b> segments")
        self.lbl_stat_length.setText(f"Total Cut Path: <b>{res.total_hatch_length_mm:.1f} mm</b> ({res.total_hatch_length_mm/1000.0:.2f} m)")

        min_req = settings.min_neighbor_angle_diff
        achieved = res.min_diff_achieved
        if n_polys <= 1:
            self.lbl_stat_min_diff.setText("Min Neighbor Separation: <i>N/A (Single shape)</i>")
        elif achieved >= min_req - 1e-3:
            self.lbl_stat_min_diff.setText(
                f"Min Neighbor Separation: <font color='#00FF66'><b>{achieved:.1f}°</b></font> (Rule: ≥ {min_req:.0f}° ✓)"
            )
        else:
            self.lbl_stat_min_diff.setText(
                f"Min Neighbor Separation: <font color='#FF5555'><b>{achieved:.1f}°</b></font> (Rule: ≥ {min_req:.0f}°)"
            )

        self.lbl_stat_center_diff.setText(
            f"Center Neighbor Contrast: <b>{res.center_diff_achieved:.1f}°</b> (Divergence peak)"
        )
