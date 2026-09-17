"""
LaserForge Automated Kerf Test Gauge Studio Dialog.
Interactive CAD preview dialog for generating precision kerf measurement gauges.
"""

from typing import List, Optional
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox,
    QMessageBox, QFileDialog, QFrame, QSplitter
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPainterPath

from laserforge.core.models import LaserEntity, PathEntity
from laserforge.core.kerf_test_generator import KerfTestGenerator, KerfTestSettings
from laserforge.core.svg_exporter import SVGExporter


class KerfTestCanvas(QFrame):
    """Interactive preview canvas rendering the generated kerf gauge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #333333; border-radius: 4px;")
        self.entities: List[LaserEntity] = []

    def set_entities(self, entities: List[LaserEntity]):
        self.entities = entities
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if not self.entities:
            painter.setPen(QColor("#777777"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Kerf Gauge Generated")
            return

        # Calculate bounding box of all entities
        all_bounds = [e.get_bounds() for e in self.entities]
        min_x = min(b[0] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_x = max(b[2] for b in all_bounds)
        max_y = max(b[3] for b in all_bounds)

        w = max(1.0, max_x - min_x)
        h = max(1.0, max_y - min_y)

        # Compute scaling to fit preview widget with margin
        margin = 35.0
        avail_w = max(10.0, self.width() - margin * 2.0)
        avail_h = max(10.0, self.height() - margin * 2.0)
        scale = min(avail_w / w, avail_h / h)

        # Center on widget
        draw_w = w * scale
        draw_h = h * scale
        offset_x = (self.width() - draw_w) / 2.0
        offset_y = (self.height() - draw_h) / 2.0

        for ent in self.entities:
            is_cut = (ent.layer_id == 0)
            pen_color = QColor("#ff1744") if is_cut else QColor("#00e5ff")
            pen_width = 2.0 if is_cut else 1.2
            painter.setPen(QPen(pen_color, pen_width))
            painter.setBrush(QBrush(QColor(255, 23, 68, 25)) if is_cut else Qt.BrushStyle.NoBrush)

            if hasattr(ent, "contours"):
                for contour in ent.contours:
                    if len(contour) < 2:
                        continue
                    path = QPainterPath()
                    start_pt = contour[0]
                    sx = offset_x + (ent.x + start_pt[0] - min_x) * scale
                    sy = offset_y + (ent.y + start_pt[1] - min_y) * scale
                    path.moveTo(sx, sy)
                    for pt in contour[1:]:
                        px = offset_x + (ent.x + pt[0] - min_x) * scale
                        py = offset_y + (ent.y + pt[1] - min_y) * scale
                        path.lineTo(px, py)
                    if getattr(ent, "closed", True):
                        path.closeSubpath()
                    painter.drawPath(path)


class KerfTestDialog(QDialog):
    """Interactive Studio Dialog for generating precision Kerf Test Gauges."""

    gauge_generated = pyqtSignal(list)

    def __init__(self, parent=None, active_cut_layer: int = 0, active_score_layer: int = 1):
        super().__init__(parent)
        self.setWindowTitle("Kerf Test Gauge Studio — Discover Exact Laser Beam Kerf")
        self.resize(850, 520)

        self.cut_layer_id = active_cut_layer
        self.engrave_layer_id = active_score_layer
        self.generated_entities: List[LaserEntity] = []

        self._build_ui()
        self._recalculate()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Left Column: Canvas Preview
        left_layout = QVBoxLayout()
        self.canvas = KerfTestCanvas(self)
        left_layout.addWidget(self.canvas, 1)

        legend_layout = QHBoxLayout()
        lbl_cut = QLabel("■ Cut Perimeter (Layer 0)")
        lbl_cut.setStyleSheet("color: #ff1744; font-weight: bold; font-size: 11px;")
        lbl_score = QLabel("■ Score / Label (Layer 1)")
        lbl_score.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 11px;")
        legend_layout.addWidget(lbl_cut)
        legend_layout.addWidget(lbl_score)
        legend_layout.addStretch()
        left_layout.addLayout(legend_layout)

        main_layout.addLayout(left_layout, 1)

        # Right Column: Controls & Presets
        right_widget = QFrame()
        right_widget.setFixedWidth(330)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Presets Group
        preset_group = QGroupBox("Material & Thickness Presets")
        preset_layout = QVBoxLayout(preset_group)
        self.combo_preset = QComboBox()
        self.combo_preset.addItems([
            "1/8 in (3.0 mm) Wood / Plywood",
            "1/4 in (6.0 mm) Thick Wood / MDF",
            "3.0 mm Cast Acrylic",
            "1.5 mm Thin Craft Wood / Matboard",
            "4.0 mm Corrugated Cardboard",
            "Custom Parameters"
        ])
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.combo_preset)
        right_layout.addWidget(preset_group)

        # Parameters Group
        param_group = QGroupBox("Kerf Test Gauge Geometry")
        grid = QGridLayout(param_group)
        grid.setSpacing(6)

        # Nominal Thickness
        grid.addWidget(QLabel("Nominal Thickness:"), 0, 0)
        self.spin_thick = QDoubleSpinBox()
        self.spin_thick.setRange(0.5, 25.0)
        self.spin_thick.setSingleStep(0.5)
        self.spin_thick.setValue(3.0)
        self.spin_thick.setSuffix(" mm")
        self.spin_thick.valueChanged.connect(self._recalculate)
        grid.addWidget(self.spin_thick, 0, 1)

        # Starting Kerf
        grid.addWidget(QLabel("Min Kerf to Test:"), 1, 0)
        self.spin_start_kerf = QDoubleSpinBox()
        self.spin_start_kerf.setRange(0.00, 1.00)
        self.spin_start_kerf.setSingleStep(0.01)
        self.spin_start_kerf.setValue(0.06)
        self.spin_start_kerf.setSuffix(" mm")
        self.spin_start_kerf.valueChanged.connect(self._recalculate)
        grid.addWidget(self.spin_start_kerf, 1, 1)

        # Kerf Step
        grid.addWidget(QLabel("Step Increment:"), 2, 0)
        self.spin_step = QDoubleSpinBox()
        self.spin_step.setRange(0.005, 0.20)
        self.spin_step.setSingleStep(0.005)
        self.spin_step.setValue(0.02)
        self.spin_step.setDecimals(3)
        self.spin_step.setSuffix(" mm")
        self.spin_step.valueChanged.connect(self._recalculate)
        grid.addWidget(self.spin_step, 2, 1)

        # Slot Count
        grid.addWidget(QLabel("Slot Count:"), 3, 0)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(3, 20)
        self.spin_count.setValue(10)
        self.spin_count.valueChanged.connect(self._recalculate)
        grid.addWidget(self.spin_count, 3, 1)

        # Slot Depth
        grid.addWidget(QLabel("Slot Depth:"), 4, 0)
        self.spin_depth = QDoubleSpinBox()
        self.spin_depth.setRange(4.0, 30.0)
        self.spin_depth.setValue(12.0)
        self.spin_depth.setSuffix(" mm")
        self.spin_depth.valueChanged.connect(self._recalculate)
        grid.addWidget(self.spin_depth, 4, 1)

        # Tooth Spacing
        grid.addWidget(QLabel("Tooth Width:"), 5, 0)
        self.spin_tooth = QDoubleSpinBox()
        self.spin_tooth.setRange(2.0, 20.0)
        self.spin_tooth.setValue(6.0)
        self.spin_tooth.setSuffix(" mm")
        self.spin_tooth.valueChanged.connect(self._recalculate)
        grid.addWidget(self.spin_tooth, 5, 1)

        right_layout.addWidget(param_group)

        # How to Use Note
        info_label = QLabel(
            "<b>How It Works:</b><br>"
            "1. Cut the test gauge & feeler tongue.<br>"
            "2. Slide the tongue into the test slots.<br>"
            "3. The slot that provides a snug, non-wobble press-fit is your exact laser beam kerf!"
        )
        info_label.setStyleSheet("color: #b0bec5; font-size: 10px; background-color: #263238; padding: 6px; border-radius: 4px;")
        info_label.setWordWrap(True)
        right_layout.addWidget(info_label)

        right_layout.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_export_svg = QPushButton("Export SVG...")
        self.btn_export_svg.clicked.connect(self._export_svg)
        btn_layout.addWidget(self.btn_export_svg)

        self.btn_add_canvas = QPushButton("✔ Add to Canvas")
        self.btn_add_canvas.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px;")
        self.btn_add_canvas.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_add_canvas)

        right_layout.addLayout(btn_layout)
        main_layout.addWidget(right_widget)

    def _on_preset_changed(self, idx: int):
        presets = [
            (3.0, 0.06, 0.02, 10),   # 1/8in wood
            (6.0, 0.08, 0.02, 10),   # 1/4in wood
            (3.0, 0.04, 0.02, 10),   # 3mm acrylic
            (1.5, 0.04, 0.02, 8),    # 1.5mm craft
            (4.0, 0.10, 0.03, 8),    # 4mm cardboard
        ]
        if idx < len(presets):
            t, k_min, k_step, cnt = presets[idx]
            self.spin_thick.setValue(t)
            self.spin_start_kerf.setValue(k_min)
            self.spin_step.setValue(k_step)
            self.spin_count.setValue(cnt)
            self._recalculate()

    def _recalculate(self):
        settings = KerfTestSettings(
            material_thickness_mm=self.spin_thick.value(),
            start_kerf_mm=self.spin_start_kerf.value(),
            kerf_step_mm=self.spin_step.value(),
            slot_count=self.spin_count.value(),
            slot_depth_mm=self.spin_depth.value(),
            tooth_width_mm=self.spin_tooth.value(),
            cut_layer_id=self.cut_layer_id,
            engrave_layer_id=self.engrave_layer_id
        )
        self.generated_entities = KerfTestGenerator.generate(settings)
        self.canvas.set_entities(self.generated_entities)

    def _export_svg(self):
        if not self.generated_entities:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Kerf Test Gauge SVG", "kerf_test_gauge.svg", "SVG Files (*.svg)")
        if not path:
            return
        ok = SVGExporter.export_svg_file(self.generated_entities, path)
        if ok:
            QMessageBox.information(self, "Export Success", f"Saved Kerf Gauge to:\n{path}")

    def accept(self):
        if self.generated_entities:
            self.gauge_generated.emit(self.generated_entities)
        super().accept()
