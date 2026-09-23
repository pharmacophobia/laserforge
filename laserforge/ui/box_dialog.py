"""
LaserForge Parametric Box & Finger-Joint Enclosure Studio Dialog.
Provides an interactive real-time 2D CAD studio for designing interlocking
laser-cut boxes, enclosures, and sliding-lid cases with kerf compensation.
"""

from typing import List, Optional, Any
import math
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QComboBox, QCheckBox, QPushButton, QLabel,
    QSplitter, QWidget, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont

from laserforge.core.box_engine import BoxEngine, BoxPanel
from laserforge.core.models import LaserEntity, PathEntity


class BoxPreviewWidget(QWidget):
    """Real-time 2D preview of flat interlocking box panels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(450, 380)
        self.panels: List[BoxPanel] = []
        self.spacing: float = 6.0
        self.setStyleSheet("background-color: #1a1a24; border-radius: 6px;")

    def set_panels(self, panels: List[BoxPanel], spacing: float = 6.0):
        self.panels = panels
        self.spacing = spacing
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        if not self.panels:
            painter.setPen(QColor("#6c7086"))
            painter.setFont(QFont("sans-serif", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Adjust parameters to generate box panels")
            return

        # Compute flat bounding box for panels
        cur_x = 0.0
        cur_y = 0.0
        row_max_h = 0.0
        panel_rects = []
        max_sheet_w = max(400.0, max((p.width for p in self.panels), default=400.0))

        for p in self.panels:
            if cur_x + p.width > max_sheet_w and cur_x > 0.0:
                cur_x = 0.0
                cur_y += row_max_h + self.spacing
                row_max_h = 0.0
            panel_rects.append((p, cur_x, cur_y))
            cur_x += p.width + self.spacing
            if p.height > row_max_h:
                row_max_h = p.height

        total_w = max((px + p.width for p, px, py in panel_rects), default=1.0)
        total_h = max((py + p.height for p, px, py in panel_rects), default=1.0)

        if total_w <= 0 or total_h <= 0:
            return

        # Viewport transformation
        margin = 35.0
        scale = min((w - margin * 2.0) / max(1.0, total_w), (h - margin * 2.0) / max(1.0, total_h))
        offset_x = (w - total_w * scale) / 2.0
        offset_y = (h - total_h * scale) / 2.0

        # Draw grid
        painter.setPen(QPen(QColor("#313244"), 1, Qt.PenStyle.DotLine))
        grid_step = 50.0 * scale
        if grid_step > 15:
            gx = offset_x % grid_step
            while gx < w:
                painter.drawLine(int(gx), 0, int(gx), h)
                gx += grid_step
            gy = offset_y % grid_step
            while gy < h:
                painter.drawLine(0, int(gy), w, int(gy))
                gy += grid_step

        # Draw panels
        for p, px, py in panel_rects:
            # Draw panel outline
            poly_points = []
            for vx, vy in p.outline:
                sx = offset_x + (px + vx) * scale
                # Flip Y for screen display
                sy = offset_y + (py + vy) * scale
                poly_points.append(QPointF(sx, sy))

            painter.setPen(QPen(QColor("#00e5ff"), 1.8))
            painter.setBrush(QBrush(QColor(0, 229, 255, 25)))
            if len(poly_points) >= 3:
                painter.drawPolygon(poly_points)

            # Draw internal cutouts
            if p.internal_cutouts:
                painter.setPen(QPen(QColor("#ff5252"), 1.5))
                painter.setBrush(QBrush(QColor(255, 82, 82, 35)))
                for cutout in p.internal_cutouts:
                    c_points = [QPointF(offset_x + (px + cx) * scale, offset_y + (py + cy) * scale) for cx, cy in cutout]
                    if len(c_points) >= 3:
                        painter.drawPolygon(c_points)

            # Draw panel name label
            painter.setPen(QColor("#cdd6f4"))
            painter.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
            lbl_x = offset_x + (px + p.width / 2.0) * scale
            lbl_y = offset_y + (py + p.height / 2.0) * scale
            painter.drawText(int(lbl_x - 35), int(lbl_y - 10), 70, 20, Qt.AlignmentFlag.AlignCenter, p.name)

        # Dimension watermark in corner
        painter.setPen(QColor("#a6adc8"))
        painter.setFont(QFont("sans-serif", 9))
        info_str = f"Panels: {len(self.panels)} | Sheet Footprint: {total_w:.1f} × {total_h:.1f} mm"
        painter.drawText(15, h - 15, info_str)


class BoxGeneratorDialog(QDialog):
    """Interactive Parametric Box Generator Studio."""

    panels_generated = pyqtSignal(list)  # List[LaserEntity]

    def __init__(self, settings: Optional[Any] = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("📦 Parametric Box & Finger-Joint Enclosure Studio")
        self.resize(960, 600)
        self._current_panels: List[BoxPanel] = []
        self._updating_preset: bool = False
        self._init_ui()
        self._on_params_changed()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left Control Panel
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 8, 8)

        # 1. Presets Group
        preset_group = QGroupBox("Box Presets")
        preset_layout = QVBoxLayout(preset_group)
        self.combo_preset = QComboBox()
        self.combo_preset.addItems([
            "Custom Dimensions",
            "Trinket / Jewelry Box (80 × 60 × 40 mm)",
            "Desktop Storage Bin (140 × 90 × 60 mm)",
            "Electronics Project Enclosure (120 × 80 × 50 mm)",
            "Pencil Box w/ Sliding Lid (180 × 65 × 35 mm)",
            "Large Organizer Caddy (200 × 140 × 90 mm)"
        ])
        self.combo_preset.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.combo_preset)
        left_layout.addWidget(preset_group)

        # 2. Dimensions Group
        dim_group = QGroupBox("Enclosure Dimensions")
        dim_form = QFormLayout(dim_group)

        self.combo_dim_mode = QComboBox()
        self.combo_dim_mode.addItems([
            "Outside Dimensions (Outer Footprint)",
            "Inside Dimensions (Internal Usable Space)"
        ])
        self.combo_dim_mode.currentIndexChanged.connect(self._on_params_changed)
        dim_form.addRow("Dimension Mode:", self.combo_dim_mode)

        self.spin_w = QDoubleSpinBox()
        self.spin_w.setRange(15.0, 1200.0)
        self.spin_w.setValue(100.0)
        self.spin_w.setSuffix(" mm")
        self.spin_w.valueChanged.connect(self._on_params_changed)
        dim_form.addRow("Width (X):", self.spin_w)

        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(15.0, 1200.0)
        self.spin_d.setValue(80.0)
        self.spin_d.setSuffix(" mm")
        self.spin_d.valueChanged.connect(self._on_params_changed)
        dim_form.addRow("Depth (Y):", self.spin_d)

        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(15.0, 600.0)
        self.spin_h.setValue(50.0)
        self.spin_h.setSuffix(" mm")
        self.spin_h.valueChanged.connect(self._on_params_changed)
        dim_form.addRow("Height (Z):", self.spin_h)

        self.lbl_dim_summary = QLabel()
        self.lbl_dim_summary.setStyleSheet(
            "background-color: #24273a; border: 1px solid #363a4f; border-radius: 5px; "
            "padding: 6px; color: #89b4fa; font-size: 11px; font-weight: bold;"
        )
        self.lbl_dim_summary.setWordWrap(True)
        dim_form.addRow(self.lbl_dim_summary)

        left_layout.addWidget(dim_group)

        # 3. Material & Joint Tolerances
        mat_group = QGroupBox("Joints & Kerf Fitting")
        mat_form = QFormLayout(mat_group)

        self.spin_thick = QDoubleSpinBox()
        self.spin_thick.setRange(0.5, 25.0)
        self.spin_thick.setValue(3.0)
        self.spin_thick.setSuffix(" mm")
        self.spin_thick.setToolTip("Thickness of sheet plywood / acrylic / MDF")
        self.spin_thick.valueChanged.connect(self._on_params_changed)
        mat_form.addRow("Material Thickness:", self.spin_thick)

        self.spin_finger = QDoubleSpinBox()
        self.spin_finger.setRange(3.0, 60.0)
        self.spin_finger.setValue(10.0)
        self.spin_finger.setSuffix(" mm")
        self.spin_finger.setToolTip("Target length of interlocking finger teeth")
        self.spin_finger.valueChanged.connect(self._on_params_changed)
        mat_form.addRow("Finger Joint Width:", self.spin_finger)

        self.spin_kerf = QDoubleSpinBox()
        self.spin_kerf.setRange(0.0, 1.0)
        self.spin_kerf.setDecimals(3)
        self.spin_kerf.setSingleStep(0.02)
        self.spin_kerf.setValue(0.15)
        self.spin_kerf.setSuffix(" mm")
        self.spin_kerf.setToolTip("Laser kerf compensation for tight glue-free friction fit")
        self.spin_kerf.valueChanged.connect(self._on_params_changed)
        mat_form.addRow("Kerf Compensation:", self.spin_kerf)

        self.combo_joint_type = QComboBox()
        self.combo_joint_type.addItems(["Finger Joint (90° Box)", "Dovetail Joint (Interlocking)"])
        self.combo_joint_type.currentIndexChanged.connect(self._on_joint_type_changed)
        mat_form.addRow("Joint Style:", self.combo_joint_type)

        self.spin_dovetail_angle = QDoubleSpinBox()
        self.spin_dovetail_angle.setRange(4.0, 25.0)
        self.spin_dovetail_angle.setValue(10.0)
        self.spin_dovetail_angle.setSuffix("°")
        self.spin_dovetail_angle.setToolTip("Angle of dovetail pin/tail flare (typically 7° - 14°)")
        self.spin_dovetail_angle.setEnabled(False)
        self.spin_dovetail_angle.valueChanged.connect(self._on_params_changed)
        mat_form.addRow("Dovetail Angle:", self.spin_dovetail_angle)

        self.combo_style = QComboBox()
        self.combo_style.addItems(["6-Sided Enclosed", "5-Sided Open Top", "Sliding Lid Case"])
        self.combo_style.currentIndexChanged.connect(self._on_params_changed)
        mat_form.addRow("Enclosure Style:", self.combo_style)

        self.lbl_joint_summary = QLabel()
        self.lbl_joint_summary.setStyleSheet(
            "background-color: #24273a; border: 1px solid #363a4f; border-radius: 5px; "
            "padding: 6px; color: #a6e3a1; font-size: 11px;"
        )
        self.lbl_joint_summary.setWordWrap(True)
        mat_form.addRow(self.lbl_joint_summary)

        left_layout.addWidget(mat_group)

        # 4. Options
        opt_group = QGroupBox("Layout Options")
        opt_form = QFormLayout(opt_group)

        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(1.0, 30.0)
        self.spin_spacing.setValue(6.0)
        self.spin_spacing.setSuffix(" mm")
        self.spin_spacing.valueChanged.connect(self._on_params_changed)
        opt_form.addRow("Panel Spacing:", self.spin_spacing)

        self.chk_labels = QCheckBox("Add Panel Text Labels")
        self.chk_labels.setChecked(True)
        self.chk_labels.setToolTip("Engrave outline text labels on each panel (BOTTOM, FRONT, etc.)")
        opt_form.addRow(self.chk_labels)

        left_layout.addWidget(opt_group)

        left_layout.addStretch()

        # Action Buttons
        btn_layout = QVBoxLayout()
        btn_apply = QPushButton("➕ Add Box Panels to Project Bed")
        btn_apply.setStyleSheet("background-color: #00e5ff; color: #111; font-weight: bold; padding: 8px;")
        btn_apply.clicked.connect(self._apply_to_bed)
        btn_layout.addWidget(btn_apply)

        btn_close = QPushButton("Cancel / Close")
        btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(btn_close)

        left_layout.addLayout(btn_layout)

        # Right Preview Widget
        self.preview_widget = BoxPreviewWidget(self)

        splitter.addWidget(left_widget)
        splitter.addWidget(self.preview_widget)
        splitter.setStretchFactor(0, 35)
        splitter.setStretchFactor(1, 65)

        main_layout.addWidget(splitter)

    def _on_preset_selected(self, index: int):
        if index == 0:
            return

        self._updating_preset = True
        self.spin_w.blockSignals(True)
        self.spin_d.blockSignals(True)
        self.spin_h.blockSignals(True)
        self.spin_thick.blockSignals(True)
        self.combo_style.blockSignals(True)
        self.combo_dim_mode.blockSignals(True)

        self.combo_dim_mode.setCurrentIndex(0)  # Presets are outer dimensions

        if index == 1:  # Trinket
            self.spin_w.setValue(80.0)
            self.spin_d.setValue(60.0)
            self.spin_h.setValue(40.0)
            self.spin_thick.setValue(3.0)
            self.combo_style.setCurrentIndex(0)
        elif index == 2:  # Storage bin
            self.spin_w.setValue(140.0)
            self.spin_d.setValue(90.0)
            self.spin_h.setValue(60.0)
            self.spin_thick.setValue(3.0)
            self.combo_style.setCurrentIndex(1)  # Open top
        elif index == 3:  # Electronics
            self.spin_w.setValue(120.0)
            self.spin_d.setValue(80.0)
            self.spin_h.setValue(50.0)
            self.spin_thick.setValue(3.0)
            self.combo_style.setCurrentIndex(0)
        elif index == 4:  # Sliding lid
            self.spin_w.setValue(180.0)
            self.spin_d.setValue(65.0)
            self.spin_h.setValue(35.0)
            self.spin_thick.setValue(3.0)
            self.combo_style.setCurrentIndex(2)  # Sliding lid
        elif index == 5:  # Large organizer
            self.spin_w.setValue(200.0)
            self.spin_d.setValue(140.0)
            self.spin_h.setValue(90.0)
            self.spin_thick.setValue(4.0)
            self.combo_style.setCurrentIndex(0)

        self.spin_w.blockSignals(False)
        self.spin_d.blockSignals(False)
        self.spin_h.blockSignals(False)
        self.spin_thick.blockSignals(False)
        self.combo_style.blockSignals(False)
        self.combo_dim_mode.blockSignals(False)
        self._updating_preset = False

        self._on_params_changed()

    def _on_joint_type_changed(self, index: int):
        is_dovetail = (index == 1)
        self.spin_dovetail_angle.setEnabled(is_dovetail)
        self._on_params_changed()

    def _on_params_changed(self):
        if not getattr(self, "_updating_preset", False):
            if self.combo_preset.currentIndex() != 0:
                self.combo_preset.blockSignals(True)
                self.combo_preset.setCurrentIndex(0)
                self.combo_preset.blockSignals(False)

        w = self.spin_w.value()
        d = self.spin_d.value()
        h = self.spin_h.value()
        t = self.spin_thick.value()
        finger = self.spin_finger.value()
        kerf = self.spin_kerf.value()
        style_idx = self.combo_style.currentIndex()
        style = "6-sided" if style_idx == 0 else ("open-top" if style_idx == 1 else "sliding-lid")
        joint_type = "dovetail" if self.combo_joint_type.currentIndex() == 1 else "finger"
        dovetail_angle = self.spin_dovetail_angle.value()
        dim_mode = "inner" if self.combo_dim_mode.currentIndex() == 1 else "outer"

        dims = BoxEngine.calculate_dimensions(
            width=w, depth=d, height=h, thickness=t, style=style, dimension_mode=dim_mode
        )

        mode_str = "Inside Cavity" if dim_mode == "inner" else "Outside Footprint"
        self.lbl_dim_summary.setText(
            f"📐 Input Mode: {mode_str}\n"
            f"• Usable Interior: {dims['inner_w']:.1f} × {dims['inner_d']:.1f} × {dims['inner_h']:.1f} mm\n"
            f"• Outer Footprint: {dims['outer_w']:.1f} × {dims['outer_d']:.1f} × {dims['outer_h']:.1f} mm"
        )

        def _get_tabs(edge_len, target_len):
            n = max(3, int(round(edge_len / target_len)))
            if n % 2 == 0:
                n += 1
            return n, edge_len / float(n)

        nw, tw = _get_tabs(dims["outer_w"], finger)
        nd, td = _get_tabs(dims["outer_d"], finger)
        nh, th = _get_tabs(dims["outer_h"], finger)
        self.lbl_joint_summary.setText(
            f"🧩 Tooth Count & Width:\n"
            f"• Width (X): {nw} teeth ({tw:.1f} mm)\n"
            f"• Depth (Y): {nd} teeth ({td:.1f} mm)\n"
            f"• Height (Z): {nh} teeth ({th:.1f} mm)"
        )

        self._current_panels = BoxEngine.generate_box(
            width=w, depth=d, height=h, thickness=t, finger_width=finger, kerf=kerf, style=style,
            joint_type=joint_type, dovetail_angle=dovetail_angle, dimension_mode=dim_mode
        )
        self.preview_widget.set_panels(self._current_panels, spacing=self.spin_spacing.value())

    def _apply_to_bed(self):
        if not self._current_panels:
            QMessageBox.warning(self, "No Panels", "Please configure valid box dimensions first.")
            return

        bed_w = getattr(self.settings, "bed_width", 400.0) if self.settings else 400.0
        entities = BoxEngine.layout_to_entities(
            self._current_panels,
            start_x=15.0,
            start_y=15.0,
            spacing=self.spin_spacing.value(),
            layer_id=0,
            include_labels=self.chk_labels.isChecked(),
            max_sheet_w=bed_w
        )
        self.panels_generated.emit(entities)
        self.accept()
