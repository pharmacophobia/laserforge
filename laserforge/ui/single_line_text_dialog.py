"""
LaserForge Single-Line Stroke Font Dialog.
Interactive tool for creating centerline single-stroke text for fast laser marking and serial numbers.
"""

from typing import List, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QPlainTextEdit, QDoubleSpinBox, QPushButton, QWidget, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont

from laserforge.core.hershey_font import HersheyFont
from laserforge.core.models import PathEntity


class SingleLineTextPreview(QWidget):
    """Real-time 2D preview canvas of single-line stroke polylines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 260)
        self.strokes: List[List[Tuple[float, float]]] = []
        self.setStyleSheet("background-color: #1a1a24; border-radius: 6px;")

    def set_strokes(self, strokes: List[List[Tuple[float, float]]]):
        self.strokes = strokes
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        if not self.strokes:
            painter.setPen(QColor("#6c7086"))
            painter.setFont(QFont("sans-serif", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Type text to preview single-line strokes")
            return

        # Calculate bounding box of strokes
        all_pts = [pt for s in self.strokes for pt in s]
        min_x = min(pt[0] for pt in all_pts)
        min_y = min(pt[1] for pt in all_pts)
        max_x = max(pt[0] for pt in all_pts)
        max_y = max(pt[1] for pt in all_pts)

        stroke_w = max_x - min_x
        stroke_h = max_y - min_y

        margin = 30.0
        scale = min((w - margin * 2.0) / max(1.0, stroke_w), (h - margin * 2.0) / max(1.0, stroke_h))
        # Center in canvas
        offset_x = (w - stroke_w * scale) / 2.0 - (min_x * scale)
        offset_y = (h - stroke_h * scale) / 2.0 - (min_y * scale)

        # Draw grid
        painter.setPen(QPen(QColor("#313244"), 1, Qt.PenStyle.DotLine))
        grid_step = 25.0 * scale
        if grid_step > 10:
            gx = 0
            while gx < w:
                painter.drawLine(int(gx), 0, int(gx), h)
                gx += grid_step
            gy = 0
            while gy < h:
                painter.drawLine(0, int(gy), w, int(gy))
                gy += grid_step

        # Draw centerline stroke lines (cyan)
        painter.setPen(QPen(QColor("#00e5ff"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for s in self.strokes:
            if len(s) < 2:
                continue
            for i in range(len(s) - 1):
                p1 = QPointF(offset_x + s[i][0] * scale, offset_y + s[i][1] * scale)
                p2 = QPointF(offset_x + s[i + 1][0] * scale, offset_y + s[i + 1][1] * scale)
                painter.drawLine(p1, p2)

        # Info badge
        painter.setPen(QColor("#a6adc8"))
        painter.setFont(QFont("sans-serif", 9))
        info = f"Strokes: {len(self.strokes)} | Dimensions: {stroke_w:.1f} × {stroke_h:.1f} mm"
        painter.drawText(15, h - 15, info)


class SingleLineTextDialog(QDialog):
    """Interactive dialog for generating Hershey single-line stroke text."""

    entity_created = pyqtSignal(object)  # PathEntity

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✍️ Single-Line Stroke (Hershey Vector) Font")
        self.resize(800, 440)
        self._current_strokes: List[List[Tuple[float, float]]] = []
        self._init_ui()
        self._on_text_changed()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left Controls
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 8, 8)

        text_group = QGroupBox("Text Content")
        text_layout = QVBoxLayout(text_group)
        self.edit_text = QPlainTextEdit("LASERFORGE\nSERIAL: #00428-A")
        self.edit_text.setMaximumHeight(90)
        self.edit_text.textChanged.connect(self._on_text_changed)
        text_layout.addWidget(self.edit_text)
        left_layout.addWidget(text_group)

        param_group = QGroupBox("Typography & Scale")
        param_form = QFormLayout(param_group)

        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(1.0, 150.0)
        self.spin_size.setValue(8.0)
        self.spin_size.setSuffix(" mm")
        self.spin_size.setToolTip("Cap height of text in mm")
        self.spin_size.valueChanged.connect(self._on_text_changed)
        param_form.addRow("Font Height:", self.spin_size)

        self.spin_char_spacing = QDoubleSpinBox()
        self.spin_char_spacing.setRange(0.5, 3.0)
        self.spin_char_spacing.setSingleStep(0.1)
        self.spin_char_spacing.setValue(1.0)
        self.spin_char_spacing.valueChanged.connect(self._on_text_changed)
        param_form.addRow("Character Spacing:", self.spin_char_spacing)

        self.spin_line_spacing = QDoubleSpinBox()
        self.spin_line_spacing.setRange(0.8, 4.0)
        self.spin_line_spacing.setSingleStep(0.1)
        self.spin_line_spacing.setValue(1.4)
        self.spin_line_spacing.valueChanged.connect(self._on_text_changed)
        param_form.addRow("Line Spacing:", self.spin_line_spacing)

        left_layout.addWidget(param_group)
        left_layout.addStretch()

        # Action Buttons
        btn_layout = QVBoxLayout()
        btn_apply = QPushButton("➕ Add Single-Line Text to Bed")
        btn_apply.setStyleSheet("background-color: #00e5ff; color: #111; font-weight: bold; padding: 8px;")
        btn_apply.clicked.connect(self._apply_to_bed)
        btn_layout.addWidget(btn_apply)

        btn_close = QPushButton("Cancel / Close")
        btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(btn_close)
        left_layout.addLayout(btn_layout)

        # Right Preview
        self.preview = SingleLineTextPreview(self)

        splitter.addWidget(left_widget)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 40)
        splitter.setStretchFactor(1, 60)

        main_layout.addWidget(splitter)

    def _on_text_changed(self):
        text = self.edit_text.toPlainText()
        size = self.spin_size.value()
        c_space = self.spin_char_spacing.value()
        l_space = self.spin_line_spacing.value()

        self._current_strokes = HersheyFont.render_text(
            text=text, font_size_mm=size, x=0.0, y=0.0, char_spacing=c_space, line_spacing=l_space
        )
        self.preview.set_strokes(self._current_strokes)

    def _apply_to_bed(self):
        text = self.edit_text.toPlainText()
        if not text.strip():
            return

        ent = HersheyFont.create_entity(
            text=text,
            x=20.0,
            y=20.0,
            font_size_mm=self.spin_size.value(),
            layer_id=0,
            name="SingleLineText"
        )
        if ent:
            self.entity_created.emit(ent)
            self.accept()
