"""
LaserForge Simulation Preview Dialog.
Provides a real-time 2D toolpath visualization, animated laser head scrubber,
ETA estimation, rapid/cut distance metrics, and G-code text inspector with file export.
"""

from typing import List, Tuple, Optional
import math
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QComboBox, QTextEdit, QFileDialog,
    QTabWidget, QSplitter, QFrame, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPaintEvent,
    QWheelEvent, QMouseEvent
)

from laserforge.config import MachineSettings
from laserforge.core.gcode_generator import GCodeJobResult, ToolpathSegment
from laserforge.core.gcode_validator import GCodeValidator, ValidationReport


class SimulationCanvas(QWidget):
    """Custom canvas rendering laser toolpaths with zoom, pan, and head animation."""
    def __init__(self, segments: List[ToolpathSegment], bbox: Tuple[float, float, float, float], parent=None):
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

        self.setMinimumSize(450, 400)
        self.setStyleSheet("background-color: #1e1e1e;")

    def set_current_index(self, idx: int):
        self.current_idx = max(0, min(len(self.segments), idx))
        self.update()

    def reset_view(self):
        """Fits toolpath bounding box into current widget geometry."""
        min_x, min_y, max_x, max_y = self.bbox
        w = max(10.0, max_x - min_x)
        h = max(10.0, max_y - min_y)

        margin = 40.0
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
        mouse_pos = event.position()
        self.pan_x = mouse_pos.x() - (mouse_pos.x() - self.pan_x) * factor
        self.pan_y = mouse_pos.y() - (mouse_pos.y() - self.pan_y) * factor
        self.scale *= factor
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
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
        painter.fillRect(self.rect(), QColor("#1a1a1a"))

        # Coordinate transformation: origin bottom-left in machine space
        # Screen X = pan_x + x * scale
        # Screen Y = pan_y - y * scale
        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(self.pan_x + x * self.scale, self.pan_y - y * self.scale)

        # Draw machine origin crosshair (0, 0)
        origin_pt = to_screen(0, 0)
        painter.setPen(QPen(QColor("#424242"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(origin_pt.x() - 15, origin_pt.y()), QPointF(origin_pt.x() + 15, origin_pt.y()))
        painter.drawLine(QPointF(origin_pt.x(), origin_pt.y() - 15), QPointF(origin_pt.x(), origin_pt.y() + 15))

        # Render segments up to current_idx
        rapid_pen = QPen(QColor(244, 67, 54, 130), 1.0, Qt.PenStyle.DotLine)

        last_pt = None
        for i in range(self.current_idx):
            seg = self.segments[i]
            p1 = to_screen(seg.x1, seg.y1)
            p2 = to_screen(seg.x2, seg.y2)

            if seg.move_type == "rapid":
                painter.setPen(rapid_pen)
            else:
                pen_color = QColor(seg.color) if seg.color else QColor("#00e5ff")
                painter.setPen(QPen(pen_color, 1.3))

            painter.drawLine(p1, p2)
            last_pt = p2

        # Draw animated laser head cursor if at least 1 segment drawn
        if last_pt:
            painter.setPen(QPen(QColor("#ff1744"), 1.5))
            painter.setBrush(QBrush(QColor("#ff5252")))
            painter.drawEllipse(last_pt, 4.0, 4.0)

            # Pulsing target rings
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(last_pt, 9.0, 9.0)


class PreviewDialog(QDialog):
    def __init__(self, job_result: GCodeJobResult, parent=None, settings: Optional[MachineSettings] = None):
        super().__init__(parent)
        self.job = job_result
        self.settings = settings or getattr(parent, "settings", None) or MachineSettings()

        # Run GRBL G-Code Validation
        validator = GCodeValidator(self.settings)
        self.validation_report = validator.validate(self.job.gcode)

        self.setWindowTitle("LaserForge - Toolpath Simulation & G-Code Preview")
        self.resize(950, 680)

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(20)  # 50 FPS
        self.play_timer.timeout.connect(self._on_timer_tick)
        self.speed_multiplier = 1

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Tabs: Simulation & Raw G-Code
        tabs = QTabWidget()

        # Tab 1: Simulation View
        sim_widget = QWidget()
        sim_layout = QVBoxLayout(sim_widget)
        sim_layout.setContentsMargins(4, 4, 4, 4)

        # Top Metric Cards
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)

        mins = int(self.job.estimated_time_sec // 60)
        secs = int(self.job.estimated_time_sec % 60)
        time_str = f"{mins:02d}m {secs:02d}s" if mins > 0 else f"{secs}s"

        lbl_time = QLabel(f"⏱ Estimated Time: <b>{time_str}</b>")
        lbl_cut = QLabel(f"✂ Cut Dist: <b>{self.job.total_cut_dist_mm:.1f} mm</b>")
        lbl_rapid = QLabel(f"⚡ Rapid Dist: <b>{self.job.total_rapid_dist_mm:.1f} mm</b>")
        lbl_segs = QLabel(f"Segment Count: <b>{len(self.job.segments)}</b>")

        for lbl in (lbl_time, lbl_cut, lbl_rapid, lbl_segs):
            lbl.setStyleSheet("background-color: #2b2b2b; padding: 4px 8px; border-radius: 4px; color: #cfd8dc;")
            metrics_row.addWidget(lbl)

        # Validation pill in metrics row
        if self.validation_report.has_errors:
            lbl_val = QLabel(f"❌ {len(self.validation_report.errors)} Error(s)")
            lbl_val.setStyleSheet("background-color: #5c1d1d; color: #ff8a80; padding: 4px 8px; border-radius: 4px; font-weight: bold;")
        elif self.validation_report.has_warnings:
            lbl_val = QLabel(f"⚠️ {len(self.validation_report.warnings)} Warning(s)")
            lbl_val.setStyleSheet("background-color: #5c431d; color: #ffd54f; padding: 4px 8px; border-radius: 4px; font-weight: bold;")
        else:
            lbl_val = QLabel("✅ GRBL 1.1 Valid")
            lbl_val.setStyleSheet("background-color: #1b4d2e; color: #81c784; padding: 4px 8px; border-radius: 4px; font-weight: bold;")
        metrics_row.addWidget(lbl_val)

        metrics_row.addStretch(1)
        btn_reset_view = QPushButton("⛶ Fit View")
        btn_reset_view.clicked.connect(lambda: self.canvas.reset_view())
        metrics_row.addWidget(btn_reset_view)
        sim_layout.addLayout(metrics_row)

        # 2D Simulation Canvas
        self.canvas = SimulationCanvas(self.job.segments, self.job.bounding_box)
        sim_layout.addWidget(self.canvas, 1)

        # Scrubber Slider & Media Controls
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)

        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setFixedWidth(70)
        self.btn_play.clicked.connect(self._toggle_playback)
        ctrl_layout.addWidget(self.btn_play)

        self.btn_reset = QPushButton("⏮ Reset")
        self.btn_reset.clicked.connect(self._reset_scrubber)
        ctrl_layout.addWidget(self.btn_reset)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(self.job.segments))
        self.slider.setValue(len(self.job.segments))
        self.slider.valueChanged.connect(self._on_slider_moved)
        ctrl_layout.addWidget(self.slider, 1)

        self.lbl_progress = QLabel(f"{len(self.job.segments)} / {len(self.job.segments)}")
        self.lbl_progress.setFixedWidth(90)
        self.lbl_progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ctrl_layout.addWidget(self.lbl_progress)

        ctrl_layout.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["1x", "2x", "5x", "10x", "25x", "50x"])
        self.speed_combo.setCurrentText("5x")
        self.speed_multiplier = 5
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        ctrl_layout.addWidget(self.speed_combo)

        sim_layout.addLayout(ctrl_layout)
        tabs.addTab(sim_widget, "Toolpath Simulation")

        # Tab 2: Raw G-Code
        gcode_widget = QWidget()
        gcode_layout = QVBoxLayout(gcode_widget)
        gcode_layout.setContentsMargins(4, 4, 4, 4)

        self.gcode_edit = QTextEdit()
        self.gcode_edit.setPlainText(self.job.gcode)
        self.gcode_edit.setReadOnly(True)
        font = QFont("monospace", 9)
        self.gcode_edit.setFont(font)
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
        tabs.addTab(gcode_widget, "Generated G-Code")

        # Tab 3: GRBL Validation Report
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

        val_tab_title = f"Validation ({len(self.validation_report.issues)})" if self.validation_report.issues else "Validation"
        tabs.addTab(val_widget, val_tab_title)

        main_layout.addWidget(tabs)

        # Bottom Close Button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        main_layout.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)

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
        self.lbl_progress.setText(f"{val} / {len(self.job.segments)}")

    def _on_speed_changed(self, idx: int):
        text = self.speed_combo.currentText().replace("x", "")
        self.speed_multiplier = int(text)

    def _save_gcode(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save G-Code", "output.nc", "G-Code Files (*.nc *.gcode);;All Files (*)")
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.job.gcode)

    def _copy_gcode(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.job.gcode)
