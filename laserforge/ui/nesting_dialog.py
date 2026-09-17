"""
LaserForge 2D Nesting Optimizer Studio Dialog.
Interactive sheet bin packing with live visual preview, rotation controls,
cavity hole nesting, and efficiency metrics.
"""

from typing import List, Optional
import time
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QWidget, QFrame, QMessageBox
)

from laserforge.config import MachineSettings
from laserforge.core.models import LaserEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.nesting_engine import NestingEngine, NestingResult, NestItem


class NestingPreviewWidget(QWidget):
    """Visual preview widget rendering the sheet material and nested parts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(450, 400)
        self.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333333; border-radius: 4px;")
        self.sheet_w = 400.0
        self.sheet_h = 400.0
        self.result: Optional[NestingResult] = None
        self.layer_manager: Optional[LayerManager] = None

    def set_sheet_and_result(self, w: float, h: float, res: Optional[NestingResult], layer_mgr: Optional[LayerManager]):
        self.sheet_w = w
        self.sheet_h = h
        self.result = res
        self.layer_manager = layer_mgr
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 25.0

        avail_w = w - 2 * margin
        avail_h = h - 2 * margin
        if self.sheet_w <= 0 or self.sheet_h <= 0:
            return

        scale = min(avail_w / self.sheet_w, avail_h / self.sheet_h)
        draw_w = self.sheet_w * scale
        draw_h = self.sheet_h * scale

        ox = margin + (avail_w - draw_w) / 2.0
        oy = margin + (avail_h - draw_h) / 2.0

        # Draw sheet background
        sheet_rect = QRectF(ox, oy, draw_w, draw_h)
        painter.setPen(QPen(QColor("#00e676"), 2, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor("#242424")))
        painter.drawRect(sheet_rect)

        # Draw dimension labels
        painter.setPen(QColor("#888888"))
        painter.setFont(QFont("Monospace", 8))
        painter.drawText(int(ox), int(oy - 6), f"{self.sheet_w:.0f} mm")
        painter.save()
        painter.translate(ox - 8, oy + draw_h / 2.0)
        painter.rotate(-90)
        painter.drawText(0, 0, f"{self.sheet_h:.0f} mm")
        painter.restore()

        if self.result is None:
            painter.setPen(QColor("#666666"))
            painter.setFont(QFont("Sans", 11))
            painter.drawText(sheet_rect, Qt.AlignmentFlag.AlignCenter, "Click 'Run Nesting Optimization'\nto preview packing layout")
            return

        # Render placed parts
        for item in self.result.placed_items:
            # Map polygon coordinates to widget
            ent = item.entity
            color_hex = "#00bcd4"
            if self.layer_manager:
                layer = self.layer_manager.get_layer(ent.layer_id)
                if layer:
                    color_hex = layer.color

            c = QColor(color_hex)
            c_fill = QColor(c.red(), c.green(), c.blue(), 90)

            # Placed dx, dy
            dx = item.placed_x - item.orig_x
            dy = item.placed_y - item.orig_y

            from shapely import affinity
            placed_geom = item.polygon
            if item.rotation_deg != 0:
                placed_geom = affinity.rotate(placed_geom, item.rotation_deg, origin='center')
            placed_geom = affinity.translate(placed_geom, dx, dy)

            path = QPainterPath()
            if hasattr(placed_geom, "exterior") and placed_geom.exterior:
                ext_coords = list(placed_geom.exterior.coords)
                if ext_coords:
                    p0x = ox + ext_coords[0][0] * scale
                    p0y = oy + ext_coords[0][1] * scale
                    path.moveTo(p0x, p0y)
                    for px, py in ext_coords[1:]:
                        path.lineTo(ox + px * scale, oy + py * scale)
                    path.closeSubpath()

                for interior in placed_geom.interiors:
                    int_coords = list(interior.coords)
                    if int_coords:
                        p0x = ox + int_coords[0][0] * scale
                        p0y = oy + int_coords[0][1] * scale
                        path.moveTo(p0x, p0y)
                        for px, py in int_coords[1:]:
                            path.lineTo(ox + px * scale, oy + py * scale)
                        path.closeSubpath()

            pen_color = QColor("#ffeb3b") if item.nested_in_hole else c
            painter.setPen(QPen(pen_color, 1.5))
            painter.setBrush(QBrush(c_fill))
            painter.drawPath(path)


class NestingDialog(QDialog):
    """Studio dialog for nesting and bin packing optimization."""

    nesting_applied = pyqtSignal(list)  # Emits list of (entity, new_x, new_y, rotation)

    def __init__(
        self,
        entities: List[LaserEntity],
        selected_entities: List[LaserEntity],
        settings: MachineSettings,
        layer_manager: LayerManager,
        parent=None
    ):
        super().__init__(parent)
        self.all_entities = entities
        self.selected_entities = selected_entities
        self.settings = settings
        self.layer_manager = layer_manager

        self.setWindowTitle("2D Nesting Optimizer Studio 📦")
        self.resize(850, 560)
        self.latest_result: Optional[NestingResult] = None

        self._init_ui()
        self._update_preview()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Controls Panel
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setSpacing(10)

        # Group 1: Sheet Definition
        grp_sheet = QGroupBox("Target Stock / Sheet Size")
        sheet_form = QGridLayout(grp_sheet)

        sheet_form.addWidget(QLabel("Preset:"), 0, 0)
        self.combo_preset = QComboBox()
        self.combo_preset.addItems([
            f"Full Machine Bed ({self.settings.bed_width:.0f} × {self.settings.bed_height:.0f} mm)",
            "Standard Sheet (300 × 200 mm)",
            "Square Stock (200 × 200 mm)",
            "A4 Sheet (297 × 210 mm)",
            "Custom Stock"
        ])
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        sheet_form.addWidget(self.combo_preset, 0, 1, 1, 2)

        sheet_form.addWidget(QLabel("Width:"), 1, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(10.0, 5000.0)
        self.spin_width.setValue(self.settings.bed_width)
        self.spin_width.setSuffix(" mm")
        self.spin_width.valueChanged.connect(self._update_preview)
        sheet_form.addWidget(self.spin_width, 1, 1)

        sheet_form.addWidget(QLabel("Height:"), 1, 2)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(10.0, 5000.0)
        self.spin_height.setValue(self.settings.bed_height)
        self.spin_height.setSuffix(" mm")
        self.spin_height.valueChanged.connect(self._update_preview)
        sheet_form.addWidget(self.spin_height, 1, 3)

        ctrl_layout.addWidget(grp_sheet)

        # Group 2: Spacing & Margin
        grp_spacing = QGroupBox("Clearance & Spacing")
        spacing_form = QGridLayout(grp_spacing)

        spacing_form.addWidget(QLabel("Part Spacing:"), 0, 0)
        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.1, 50.0)
        self.spin_spacing.setValue(2.0)
        self.spin_spacing.setSuffix(" mm")
        self.spin_spacing.setToolTip("Minimum gap between adjacent parts")
        spacing_form.addWidget(self.spin_spacing, 0, 1)

        spacing_form.addWidget(QLabel("Sheet Margin:"), 1, 0)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 100.0)
        self.spin_margin.setValue(5.0)
        self.spin_margin.setSuffix(" mm")
        self.spin_margin.setToolTip("Safety border around the sheet perimeter")
        spacing_form.addWidget(self.spin_margin, 1, 1)

        ctrl_layout.addWidget(grp_spacing)

        # Group 3: Optimization Parameters
        grp_opt = QGroupBox("Orientation & Nesting Strategy")
        opt_layout = QVBoxLayout(grp_opt)

        rot_box = QHBoxLayout()
        rot_box.addWidget(QLabel("Rotations:"))
        self.combo_rot = QComboBox()
        self.combo_rot.addItems([
            "90° Increments (4 Directions)",
            "45° Increments (8 Directions)",
            "Fixed (No Rotation)"
        ])
        rot_box.addWidget(self.combo_rot)
        opt_layout.addLayout(rot_box)

        self.chk_hole_nest = QCheckBox("Enable Cavity / Hole Nesting")
        self.chk_hole_nest.setChecked(True)
        self.chk_hole_nest.setToolTip("Packs small parts inside the cutout holes of larger frames/rings")
        opt_layout.addWidget(self.chk_hole_nest)

        # Selection Scope
        scope_box = QHBoxLayout()
        scope_box.addWidget(QLabel("Scope:"))
        self.combo_scope = QComboBox()
        if self.selected_entities:
            self.combo_scope.addItems([
                f"Selected Shapes ({len(self.selected_entities)} items)",
                f"All Shapes ({len(self.all_entities)} items)"
            ])
        else:
            self.combo_scope.addItems([f"All Canvas Shapes ({len(self.all_entities)} items)"])
        scope_box.addWidget(self.combo_scope)
        opt_layout.addLayout(scope_box)

        ctrl_layout.addWidget(grp_opt)

        # Stats Card
        self.frame_stats = QFrame()
        self.frame_stats.setStyleSheet("background-color: #222; border: 1px solid #444; border-radius: 4px; padding: 6px;")
        stats_layout = QVBoxLayout(self.frame_stats)
        stats_layout.setContentsMargins(8, 8, 8, 8)
        stats_layout.setSpacing(4)

        self.lbl_stats_title = QLabel("📊 Nesting Performance")
        self.lbl_stats_title.setStyleSheet("font-weight: bold; color: #00e676;")
        stats_layout.addWidget(self.lbl_stats_title)

        self.lbl_parts_info = QLabel("Total Shapes: -")
        stats_layout.addWidget(self.lbl_parts_info)

        self.lbl_density = QLabel("Packing Density: - %")
        stats_layout.addWidget(self.lbl_density)

        self.lbl_time = QLabel("Compute Time: - ms")
        stats_layout.addWidget(self.lbl_time)

        ctrl_layout.addWidget(self.frame_stats)

        ctrl_layout.addStretch()

        # Action Buttons
        btn_calc = QPushButton("⚡  Run Nesting Optimization")
        btn_calc.setStyleSheet("background-color: #00897b; color: white; font-weight: bold; padding: 8px;")
        btn_calc.clicked.connect(self._run_nesting)
        ctrl_layout.addWidget(btn_calc)

        btn_apply = QPushButton("✅  Apply Layout to Bed")
        btn_apply.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 8px;")
        btn_apply.clicked.connect(self._apply_layout)
        ctrl_layout.addWidget(btn_apply)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        ctrl_layout.addWidget(btn_cancel)

        splitter.addWidget(ctrl_widget)

        # Right Preview Panel
        self.preview_widget = NestingPreviewWidget()
        splitter.addWidget(self.preview_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter)

    def _on_preset_changed(self, idx: int):
        if idx == 0:  # Full bed
            self.spin_width.setValue(self.settings.bed_width)
            self.spin_height.setValue(self.settings.bed_height)
        elif idx == 1:  # 300x200
            self.spin_width.setValue(300.0)
            self.spin_height.setValue(200.0)
        elif idx == 2:  # 200x200
            self.spin_width.setValue(200.0)
            self.spin_height.setValue(200.0)
        elif idx == 3:  # A4 (297x210)
            self.spin_width.setValue(297.0)
            self.spin_height.setValue(210.0)

    def _update_preview(self):
        self.preview_widget.set_sheet_and_result(
            self.spin_width.value(),
            self.spin_height.value(),
            self.latest_result,
            self.layer_manager
        )

    def _get_target_entities(self) -> List[LaserEntity]:
        txt = self.combo_scope.currentText()
        if "Selected Shapes" in txt and self.selected_entities:
            return self.selected_entities
        return self.all_entities

    def _run_nesting(self):
        targets = self._get_target_entities()
        if not targets:
            QMessageBox.warning(self, "No Shapes", "There are no vector shapes available to nest.")
            return

        w = self.spin_width.value()
        h = self.spin_height.value()
        spacing = self.spin_spacing.value()
        margin = self.spin_margin.value()

        # Rotation angles
        rot_mode = self.combo_rot.currentIndex()
        if rot_mode == 0:
            rotations = [0.0, 90.0, 180.0, 270.0]
        elif rot_mode == 1:
            rotations = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
        else:
            rotations = [0.0]

        allow_holes = self.chk_hole_nest.isChecked()

        res = NestingEngine.nest(
            entities=targets,
            sheet_width=w,
            sheet_height=h,
            part_spacing=spacing,
            sheet_margin=margin,
            rotations=rotations,
            allow_hole_nesting=allow_holes
        )

        self.latest_result = res
        self._update_preview()

        # Update stats
        num_placed = len(res.placed_items)
        num_unplaced = len(res.unplaced_items)
        tot = num_placed + num_unplaced
        if num_unplaced == 0:
            self.lbl_parts_info.setText(f"Placed: <b>{num_placed}/{tot}</b> (All fit)")
            self.lbl_parts_info.setStyleSheet("color: #00e676;")
        else:
            self.lbl_parts_info.setText(f"Placed: <b>{num_placed}/{tot}</b> (⚠️ {num_unplaced} did not fit)")
            self.lbl_parts_info.setStyleSheet("color: #ff9800;")

        self.lbl_density.setText(f"Packing Density: <b>{res.efficiency_pct:.1f}%</b>")
        self.lbl_time.setText(f"Compute Time: <b>{res.execution_time_ms:.1f} ms</b>")

    def _apply_layout(self):
        if not self.latest_result or not self.latest_result.placed_items:
            QMessageBox.information(self, "No Solution", "Please run nesting optimization before applying.")
            return

        # Prepare updates: list of (entity, new_x, new_y, rotation)
        updates = []
        for item in self.latest_result.placed_items:
            updates.append((item.entity, item.placed_x, item.placed_y, item.rotation_deg))

        self.nesting_applied.emit(updates)
        self.accept()
