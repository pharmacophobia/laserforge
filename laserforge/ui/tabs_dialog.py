"""
LaserForge Holding Tabs & Micro-Bridges Studio Dialog.
Configures structural holding tabs and uncut micro-bridges along closed cutting contours
to prevent small cut parts from dropping through honeycomb beds or tipping into laser nozzles.
"""

from typing import List, Tuple, Optional, Any, Dict
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QDoubleSpinBox, QSpinBox, QComboBox,
    QMessageBox, QFrame, QRadioButton, QButtonGroup, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QFont

from laserforge.core.models import LaserEntity, PathEntity, RectEntity, CircleEntity, LayerCutSettings
from laserforge.core.tab_engine import TabEngine


class TabsPreviewWidget(QFrame):
    """Visual diagram showing the cut path (green/layer) interrupted by holding tabs (amber)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #1a1a24; border: 1px solid #333348; border-radius: 4px;")
        self.setMinimumSize(320, 240)

        self.contours: List[List[Tuple[float, float]]] = []
        self.tab_count: int = 4
        self.tab_width: float = 1.2
        self.manual_ratios: List[float] = []

    def set_data(
        self,
        contours: List[List[Tuple[float, float]]],
        tab_count: int,
        tab_width: float,
        manual_ratios: Optional[List[float]] = None
    ):
        self.contours = contours
        self.tab_count = tab_count
        self.tab_width = tab_width
        self.manual_ratios = manual_ratios or []
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.contours:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a closed vector shape\nto preview holding tabs")
            return

        # Compute bounding box
        all_pts = [pt for c in self.contours for pt in c]
        if not all_pts:
            return
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bw = max(1.0, max_x - min_x)
        bh = max(1.0, max_y - min_y)

        pad = 30.0
        w = float(self.width()) - pad * 2
        h = float(self.height()) - pad * 2
        scale = min(w / bw, h / bh)

        ox = pad + (w - bw * scale) / 2.0 - min_x * scale
        oy = pad + (h - bh * scale) / 2.0 - min_y * scale

        # Draw contour segments with TabEngine
        for c in self.contours:
            slices = TabEngine.slice_contour_with_tabs(
                c,
                tab_count=self.tab_count,
                tab_width=self.tab_width,
                manual_tab_ratios=self.manual_ratios if self.manual_ratios else None
            )

            # Draw cuts (Cyan/Green solid line)
            pen_cut = QPen(QColor("#06b6d4"), 2.5)
            painter.setPen(pen_cut)
            for sl in slices:
                if sl["type"] == "cut":
                    pts = sl["path"]
                    for i in range(len(pts) - 1):
                        p1 = QPointF(ox + pts[i][0] * scale, oy + pts[i][1] * scale)
                        p2 = QPointF(ox + pts[i + 1][0] * scale, oy + pts[i + 1][1] * scale)
                        painter.drawLine(p1, p2)

            # Draw tabs (Bright Amber bridge markers)
            pen_tab = QPen(QColor("#f59e0b"), 4.0)
            painter.setPen(pen_tab)
            for sl in slices:
                if sl["type"] == "tab":
                    p1 = QPointF(ox + sl["start"][0] * scale, oy + sl["start"][1] * scale)
                    p2 = QPointF(ox + sl["end"][0] * scale, oy + sl["end"][1] * scale)
                    painter.drawLine(p1, p2)
                    # Draw bridge indicator circle
                    painter.setBrush(QBrush(QColor("#f59e0b")))
                    painter.drawEllipse(p1, 3.5, 3.5)
                    painter.drawEllipse(p2, 3.5, 3.5)


class HoldingTabsDialog(QDialog):
    """Dialog for configuring and generating structural holding tabs / micro-bridges."""

    tabs_applied = pyqtSignal(dict)  # Emits config applied

    def __init__(self, entities: List[LaserEntity], layer_settings: Optional[LayerCutSettings] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Holding Tabs & Micro-Bridges Studio ⚡")
        self.setMinimumSize(680, 520)
        self.setStyleSheet("""
            QDialog { background-color: #121218; color: #f1f5f9; }
            QGroupBox { border: 1px solid #2e2e3e; border-radius: 6px; margin-top: 12px; font-weight: bold; color: #93c5fd; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #cbd5e1; font-size: 12px; }
            QDoubleSpinBox, QSpinBox, QComboBox { background-color: #1a1a24; border: 1px solid #3b3b4f; border-radius: 4px; color: #f1f5f9; padding: 4px; font-size: 12px; }
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 4px; padding: 7px 16px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton#btnCancel { background-color: #374151; }
            QPushButton#btnCancel:hover { background-color: #4b5563; }
            QPushButton#btnClear { background-color: #dc2626; }
            QPushButton#btnClear:hover { background-color: #ef4444; }
        """)

        self.entities = entities
        self.layer_settings = layer_settings

        self._init_ui()
        self._load_current_values()
        self._update_preview()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # Left Column: Controls
        left_col = QVBoxLayout()

        # Group 1: Tab Geometry & Distribution
        geom_group = QGroupBox("Holding Tab Geometry")
        g_layout = QGridLayout(geom_group)

        g_layout.addWidget(QLabel("Tab Width:"), 0, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.2, 10.0)
        self.spin_width.setSingleStep(0.1)
        self.spin_width.setSuffix(" mm")
        self.spin_width.setValue(1.2)
        self.spin_width.valueChanged.connect(self._update_preview)
        g_layout.addWidget(self.spin_width, 0, 1)

        g_layout.addWidget(QLabel("Tab Count per Part:"), 1, 0)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 32)
        self.spin_count.setValue(4)
        self.spin_count.valueChanged.connect(self._update_preview)
        g_layout.addWidget(self.spin_count, 1, 1)

        g_layout.addWidget(QLabel("Tab Laser Power:"), 2, 0)
        self.spin_power = QDoubleSpinBox()
        self.spin_power.setRange(0.0, 100.0)
        self.spin_power.setSingleStep(5.0)
        self.spin_power.setSuffix(" %")
        self.spin_power.setValue(0.0)
        self.spin_power.setToolTip("0% = Full uncut bridge (laser off / rapid across bridge)\n>0% = Skin tab / micro-bridge with partial laser cut for easy manual breakout")
        g_layout.addWidget(self.spin_power, 2, 1)

        left_col.addWidget(geom_group)

        # Group 2: Scope & Target
        scope_group = QGroupBox("Application Target")
        s_layout = QVBoxLayout(scope_group)

        self.rb_selected = QRadioButton(f"Selected Shapes ({len(self.entities)})")
        self.rb_selected.setChecked(True)
        self.rb_layer = QRadioButton("Active Layer (All Shapes)")
        s_layout.addWidget(self.rb_selected)
        s_layout.addWidget(self.rb_layer)

        left_col.addWidget(scope_group)

        # Info Box
        info_box = QFrame()
        info_box.setStyleSheet("background-color: #1e1b4b; border: 1px solid #4338ca; border-radius: 4px; padding: 8px;")
        info_layout = QVBoxLayout(info_box)
        info_title = QLabel("💡 Honeycomb Bed Protection")
        info_title.setStyleSheet("font-weight: bold; color: #a5b4fc;")
        info_desc = QLabel(
            "Holding tabs interrupt the cutting toolpath with small structural bridges.\n"
            "This keeps parts firmly attached to sheet stock so they don't tip into honeycomb slats or strike the laser nozzle."
        )
        info_desc.setWordWrap(True)
        info_desc.setStyleSheet("color: #c7d2fe; font-size: 11px;")
        info_layout.addWidget(info_title)
        info_layout.addWidget(info_desc)
        left_col.addWidget(info_box)

        left_col.addStretch()

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Tabs")
        self.btn_clear.setObjectName("btnClear")
        self.btn_clear.clicked.connect(self._clear_tabs)
        btn_layout.addWidget(self.btn_clear)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        self.btn_apply = QPushButton("Apply Tabs")
        self.btn_apply.clicked.connect(self._apply_tabs)
        btn_layout.addWidget(self.btn_apply)

        left_col.addLayout(btn_layout)
        main_layout.addLayout(left_col, 1)

        # Right Column: Visual Preview
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("Live Tab Distribution Preview:"))
        self.preview_widget = TabsPreviewWidget()
        right_col.addWidget(self.preview_widget, 1)
        main_layout.addLayout(right_col, 1)

    def _load_current_values(self):
        if self.layer_settings:
            self.spin_width.setValue(getattr(self.layer_settings, "tab_width", 1.2))
            self.spin_count.setValue(getattr(self.layer_settings, "tab_count", 4))
            self.spin_power.setValue(getattr(self.layer_settings, "tab_power_pct", 0.0))

    def _extract_contours(self) -> List[List[Tuple[float, float]]]:
        contours = []
        for ent in self.entities:
            if isinstance(ent, PathEntity):
                for c in ent.contours:
                    if len(c) >= 3:
                        contours.append(c)
            elif isinstance(ent, RectEntity):
                rx, ry = ent.x, ent.y
                rw, rh = ent.width, ent.height
                contours.append([(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh), (rx, ry)])
            elif isinstance(ent, CircleEntity):
                cx, cy = ent.x, ent.y
                rx, ry = ent.radius_x, ent.radius_y
                steps = 48
                c = [(cx + rx * math.cos(2 * math.pi * i / steps), cy + ry * math.sin(2 * math.pi * i / steps)) for i in range(steps)]
                c.append(c[0])
                contours.append(c)
        return contours

    def _update_preview(self):
        contours = self._extract_contours()
        self.preview_widget.set_data(
            contours,
            tab_count=self.spin_count.value(),
            tab_width=self.spin_width.value()
        )

    def _apply_tabs(self):
        res = {
            "tab_count": self.spin_count.value(),
            "tab_width": self.spin_width.value(),
            "tab_power_pct": self.spin_power.value(),
            "target": "selected" if self.rb_selected.isChecked() else "layer",
            "tabs_enabled": True
        }
        self.tabs_applied.emit(res)
        self.accept()

    def _clear_tabs(self):
        res = {
            "tab_count": 0,
            "tab_width": 0.0,
            "tab_power_pct": 0.0,
            "target": "selected" if self.rb_selected.isChecked() else "layer",
            "tabs_enabled": False
        }
        self.tabs_applied.emit(res)
        self.accept()
