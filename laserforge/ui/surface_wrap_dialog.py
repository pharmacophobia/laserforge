"""
LaserForge 3D Curved Surface Wrapping Studio Dialog.

Interactive studio for projecting 2D laser artwork across non-planar surfaces:
- Cylinders (engraving bottles, rolling pins, pipes without a rotary axis)
- Spheres, domes, and curved bowls
- Sloped wedge planes
- 3D perspective wireframe canvas preview
- Direct 3D G-code export and canvas entity integration
"""

from typing import List, Tuple, Optional
import math
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QDoubleSpinBox, QPushButton, QGroupBox, QSplitter,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont

from laserforge.core.models import LaserEntity, PathEntity
from laserforge.core.surface_projector import SurfaceParameters, Surface3DProjector


class Surface3DPreviewCanvas(QWidget):
    """Isometric / 3D perspective wireframe preview canvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(440, 400)
        self.setStyleSheet("background-color: #121218; border: 1px solid #2a2a38; border-radius: 6px;")
        self.paths_3d: List[List[Tuple[float, float, float]]] = []
        self.surface_params = SurfaceParameters()
        self.yaw = 35.0    # Rotation angles in degrees
        self.pitch = 30.0

    def set_data(self, paths_3d: List[List[Tuple[float, float, float]]], params: SurfaceParameters):
        self.paths_3d = paths_3d
        self.surface_params = params
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#14141d"))

        cx, cy = w / 2.0, h / 2.0
        rad_yaw = math.radians(self.yaw)
        rad_pitch = math.radians(self.pitch)
        cos_y, sin_y = math.cos(rad_yaw), math.sin(rad_yaw)
        cos_p, sin_p = math.cos(rad_pitch), math.sin(rad_pitch)
        scale = 1.8

        def project(x, y, z) -> QPointF:
            # Simple 3D to 2D isometric projection
            rx = x * cos_y - y * sin_y
            ry = (x * sin_y + y * cos_y) * cos_p - z * sin_p
            return QPointF(cx + rx * scale, cy - ry * scale)

        # 1. Draw 3D curved wireframe mesh grid
        painter.setPen(QPen(QColor(60, 70, 90, 100), 1, Qt.PenStyle.DashLine))
        grid_r = 60.0
        grid_steps = 12
        step = (grid_r * 2) / grid_steps

        for i in range(grid_steps + 1):
            gx = -grid_r + i * step
            pts_line = []
            for j in range(grid_steps + 1):
                gy = -grid_r + j * step
                gz = Surface3DProjector.get_elevation_function(self.surface_params)(gx, gy)
                pts_line.append(project(gx, gy, gz))
            for k in range(len(pts_line) - 1):
                painter.drawLine(pts_line[k], pts_line[k + 1])

        # 2. Draw projected 3D toolpath lines
        painter.setPen(QPen(QColor("#00E5FF"), 2))
        for p in self.paths_3d:
            if len(p) < 2:
                continue
            for k in range(len(p) - 1):
                p1 = project(p[k][0], p[k][1], p[k][2])
                p2 = project(p[k + 1][0], p[k + 1][1], p[k + 1][2])
                painter.drawLine(p1, p2)

        # Draw HUD label
        painter.setFont(QFont("sans-serif", 9))
        painter.setPen(QColor("#8c8ca0"))
        painter.drawText(12, h - 12, f"Surface: {self.surface_params.surface_type} | 3D Contours: {len(self.paths_3d)}")


class SurfaceWrapStudioDialog(QDialog):
    """Dialog for projecting 2D artwork across 3D surfaces."""

    def __init__(self, entities: List[LaserEntity], parent=None):
        super().__init__(parent)
        self.setWindowTitle("3D Curved Surface Projection Studio")
        self.resize(860, 560)
        self.source_entities = entities
        self.projected_3d: List[List[Tuple[float, float, float]]] = []

        self._build_ui()
        self._update_projection()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left preview canvas
        self.canvas = Surface3DPreviewCanvas(self)
        splitter.addWidget(self.canvas)

        # Right control panel
        right_panel = QWidget()
        right_lay = QVBoxLayout(right_panel)
        right_lay.setSpacing(12)

        grp = QGroupBox("3D Surface Geometry")
        grp_lay = QGridLayout(grp)
        grp_lay.setSpacing(8)

        grp_lay.addWidget(QLabel("Surface Type:"), 0, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Cylinder", "Sphere", "Incline"])
        self.combo_type.currentTextChanged.connect(self._update_projection)
        grp_lay.addWidget(self.combo_type, 0, 1)

        grp_lay.addWidget(QLabel("Radius:"), 1, 0)
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(5.0, 500.0)
        self.spin_radius.setValue(50.0)
        self.spin_radius.setSuffix(" mm")
        self.spin_radius.valueChanged.connect(self._update_projection)
        grp_lay.addWidget(self.spin_radius, 1, 1)

        grp_lay.addWidget(QLabel("Cylinder Axis:"), 2, 0)
        self.combo_axis = QComboBox()
        self.combo_axis.addItems(["X Axis", "Y Axis"])
        self.combo_axis.currentTextChanged.connect(self._update_projection)
        grp_lay.addWidget(self.combo_axis, 2, 1)

        grp_lay.addWidget(QLabel("Subdivision Step:"), 3, 0)
        self.spin_step = QDoubleSpinBox()
        self.spin_step.setRange(0.1, 5.0)
        self.spin_step.setValue(0.5)
        self.spin_step.setSuffix(" mm")
        self.spin_step.valueChanged.connect(self._update_projection)
        grp_lay.addWidget(self.spin_step, 3, 1)

        right_lay.addWidget(grp)
        right_lay.addStretch()

        # Action Buttons
        btn_export = QPushButton("💾 Export 3D G-Code...")
        btn_export.clicked.connect(self._export_gcode)
        right_lay.addWidget(btn_export)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        right_lay.addWidget(btn_close)

        splitter.addWidget(right_panel)
        splitter.setSizes([540, 300])

    def _update_projection(self):
        stype = self.combo_type.currentText()
        axis = "X" if "X" in self.combo_axis.currentText() else "Y"
        params = SurfaceParameters(
            surface_type=stype,
            radius_mm=self.spin_radius.value(),
            axis=axis,
            subdivision_step_mm=self.spin_step.value()
        )

        # Extract contours from entities
        all_contours = []
        for ent in self.source_entities:
            if isinstance(ent, PathEntity):
                for c in ent.contours:
                    pts = [(ent.x + p[0], ent.y + p[1]) for p in c]
                    all_contours.append(pts)

        if not all_contours:
            # Fallback box test path
            all_contours = [[(-20, -20), (20, -20), (20, 20), (-20, 20), (-20, -20)]]

        self.projected_3d = Surface3DProjector.project_contours(all_contours, params)
        self.canvas.set_data(self.projected_3d, params)

    def _export_gcode(self):
        if not self.projected_3d:
            QMessageBox.warning(self, "Export", "No 3D paths generated.")
            return

        gcode_lines = Surface3DProjector.generate_nonplanar_gcode(self.projected_3d)
        filepath, _ = QFileDialog.getSaveFileName(self, "Export 3D G-Code", "", "G-Code Files (*.gcode *.nc)")
        if filepath:
            with open(filepath, "w") as f:
                f.write("\n".join(gcode_lines))
            QMessageBox.information(self, "Export Complete", f"Exported {len(gcode_lines)} lines of 3D non-planar G-code.")
