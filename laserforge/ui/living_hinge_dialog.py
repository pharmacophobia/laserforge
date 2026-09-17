"""
LaserForge Living Hinge & Lattice Flex Studio Dialog.
Interactive parametric CAD designer for laser-cut living hinges and bendable curved sheet materials.
"""

from typing import List, Optional
import math
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QComboBox, QCheckBox, QPushButton, QLabel,
    QSplitter, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont

from laserforge.core.living_hinge_engine import LivingHingeEngine, LivingHingeConfig
from laserforge.core.models import LaserEntity


class LivingHingePreviewWidget(QFrame):
    """Visual preview of living hinge lattice slits and outer borders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #121218; border: 1px solid #2e2e3e; border-radius: 4px;")
        self.setMinimumSize(380, 360)
        self.entities: List[LaserEntity] = []

    def set_entities(self, entities: List[LaserEntity]):
        self.entities = entities
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.entities:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Adjust parameters to preview living hinge")
            return

        all_bounds = [e.get_bounds() for e in self.entities]
        min_x = min(b[0] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_x = max(b[2] for b in all_bounds)
        max_y = max(b[3] for b in all_bounds)

        bw = max(1.0, max_x - min_x)
        bh = max(1.0, max_y - min_y)

        pad = 25.0
        w = float(self.width()) - pad * 2
        h = float(self.height()) - pad * 2
        scale = min(w / bw, h / bh)

        ox = pad + (w - bw * scale) / 2.0 - min_x * scale
        oy = pad + (h - bh * scale) / 2.0 - min_y * scale

        for ent in self.entities:
            # Draw contours
            if hasattr(ent, "contours"):
                is_perimeter = getattr(ent, "closed", False)
                pen_color = QColor("#00e5ff") if is_perimeter else QColor("#f59e0b")
                pen = QPen(pen_color, 1.6 if is_perimeter else 1.2)
                painter.setPen(pen)

                for contour in ent.contours:
                    for i in range(len(contour) - 1):
                        p1 = QPointF(ox + contour[i][0] * scale, oy + contour[i][1] * scale)
                        p2 = QPointF(ox + contour[i + 1][0] * scale, oy + contour[i + 1][1] * scale)
                        painter.drawLine(p1, p2)


class LivingHingeDialog(QDialog):
    """Parametric Studio for Living Hinges and Lattice Flex."""

    hinge_generated = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Living Hinge & Lattice Flex Studio 🪚")
        self.setMinimumSize(820, 520)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; }
            QGroupBox { border: 1px solid #334155; border-radius: 6px; margin-top: 10px; font-weight: bold; color: #38bdf8; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #cbd5e1; font-size: 12px; }
            QDoubleSpinBox, QComboBox { background-color: #1e293b; border: 1px solid #475569; border-radius: 4px; color: #f8fafc; padding: 4px; font-size: 12px; }
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton#btnCancel { background-color: #475569; }
            QPushButton#btnCancel:hover { background-color: #64748b; }
        """)

        self._current_entities: List[LaserEntity] = []
        self._init_ui()
        self._on_params_changed()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left Column: Controls
        left_w = QWidget()
        left_layout = QVBoxLayout(left_w)

        # Group 1: Bend Geometry Calculator
        g_bend = QGroupBox("1. Bend Geometry & Curvature")
        f_bend = QFormLayout(g_bend)

        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(2.0, 500.0)
        self.spin_radius.setValue(20.0)
        self.spin_radius.setSuffix(" mm")
        self.spin_radius.valueChanged.connect(self._on_bend_changed)
        f_bend.addRow("Inside Bend Radius:", self.spin_radius)

        self.spin_angle = QDoubleSpinBox()
        self.spin_angle.setRange(10.0, 360.0)
        self.spin_angle.setValue(90.0)
        self.spin_angle.setSuffix("°")
        self.spin_angle.valueChanged.connect(self._on_bend_changed)
        f_bend.addRow("Bend Angle:", self.spin_angle)

        self.lbl_arc_len = QLabel("Calculated Arc Span: 31.4 mm")
        self.lbl_arc_len.setStyleSheet("font-family: monospace; color: #fde047; font-weight: bold;")
        f_bend.addRow(self.lbl_arc_len)

        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(10.0, 1000.0)
        self.spin_height.setValue(100.0)
        self.spin_height.setSuffix(" mm")
        self.spin_height.valueChanged.connect(self._on_params_changed)
        f_bend.addRow("Hinge Length (Axis):", self.spin_height)

        left_layout.addWidget(g_bend)

        # Group 2: Lattice Slit Parameters
        g_slit = QGroupBox("2. Lattice Pattern & Flexibility")
        f_slit = QFormLayout(g_slit)

        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems([
            "Straight Alternating Lattice",
            "Wavy Sinuous Flex (High Torsion)",
            "Diamond Honeycomb Flex"
        ])
        self.combo_pattern.currentIndexChanged.connect(self._on_params_changed)
        f_slit.addRow("Pattern Style:", self.combo_pattern)

        self.spin_cut_len = QDoubleSpinBox()
        self.spin_cut_len.setRange(2.0, 50.0)
        self.spin_cut_len.setValue(12.0)
        self.spin_cut_len.setSuffix(" mm")
        self.spin_cut_len.valueChanged.connect(self._on_params_changed)
        f_slit.addRow("Slit Cut Length:", self.spin_cut_len)

        self.spin_gap = QDoubleSpinBox()
        self.spin_gap.setRange(0.5, 10.0)
        self.spin_gap.setValue(1.8)
        self.spin_gap.setSuffix(" mm")
        self.spin_gap.setToolTip("Width of uncut structural bridge between slits")
        self.spin_gap.valueChanged.connect(self._on_params_changed)
        f_slit.addRow("Bridge Gap Length:", self.spin_gap)

        self.spin_pitch = QDoubleSpinBox()
        self.spin_pitch.setRange(0.8, 10.0)
        self.spin_pitch.setValue(2.0)
        self.spin_pitch.setSuffix(" mm")
        self.spin_pitch.setToolTip("Distance between adjacent slit columns")
        self.spin_pitch.valueChanged.connect(self._on_params_changed)
        f_slit.addRow("Column Spacing:", self.spin_pitch)

        left_layout.addWidget(g_slit)

        # Group 3: Solid Mounting Tabs
        g_border = QGroupBox("3. Outer Frame & Mounting Tabs")
        f_border = QFormLayout(g_border)

        self.chk_borders = QCheckBox("Add Solid Attachment Borders")
        self.chk_borders.setChecked(True)
        self.chk_borders.toggled.connect(self._on_params_changed)
        f_border.addRow(self.chk_borders)

        self.spin_border_w = QDoubleSpinBox()
        self.spin_border_w.setRange(2.0, 100.0)
        self.spin_border_w.setValue(15.0)
        self.spin_border_w.setSuffix(" mm")
        self.spin_border_w.valueChanged.connect(self._on_params_changed)
        f_border.addRow("Border Tab Width:", self.spin_border_w)

        left_layout.addWidget(g_border)
        left_layout.addStretch()

        # Action Buttons
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_add = QPushButton("Add Hinge to Project Bed ➕")
        btn_add.clicked.connect(self._apply_to_bed)
        btn_box.addWidget(btn_add)
        left_layout.addLayout(btn_box)

        splitter.addWidget(left_w)

        # Right Column: Visual Preview
        right_w = QWidget()
        right_layout = QVBoxLayout(right_w)
        right_layout.addWidget(QLabel("Real-Time Living Hinge Lattice Preview:"))
        self.preview_widget = LivingHingePreviewWidget()
        right_layout.addWidget(self.preview_widget, 1)

        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 40)
        splitter.setStretchFactor(1, 60)
        main_layout.addWidget(splitter)

    def _on_bend_changed(self):
        r = self.spin_radius.value()
        a = self.spin_angle.value()
        arc_span = LivingHingeEngine.calculate_hinge_width(r, a)
        self.lbl_arc_len.setText(f"Calculated Arc Span: {arc_span:.1f} mm")
        self._on_params_changed()

    def _on_params_changed(self):
        r = self.spin_radius.value()
        a = self.spin_angle.value()
        arc_span = LivingHingeEngine.calculate_hinge_width(r, a)

        pattern_keys = ["straight", "wavy", "diamond"]
        pattern = pattern_keys[self.combo_pattern.currentIndex()]

        cfg = LivingHingeConfig(
            width=arc_span,
            height=self.spin_height.value(),
            bend_radius=r,
            bend_angle_deg=a,
            cut_pattern=pattern,
            cut_length=self.spin_cut_len.value(),
            gap_length=self.spin_gap.value(),
            column_spacing=self.spin_pitch.value(),
            add_border_tabs=self.chk_borders.isChecked(),
            border_tab_width=self.spin_border_w.value()
        )

        self._current_entities = LivingHingeEngine.generate_hinge_entities(cfg, origin_x=0.0, origin_y=0.0)
        self.preview_widget.set_entities(self._current_entities)

    def _apply_to_bed(self):
        if not self._current_entities:
            QMessageBox.warning(self, "No Hinge", "Configure valid hinge dimensions first.")
            return

        self.hinge_generated.emit(self._current_entities)
        self.accept()
