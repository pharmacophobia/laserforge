"""
LaserForge Trace Image Dialog.
Interactive image-to-vector tracing dialog (LightBurn-style Trace Image tool).
Provides real-time thresholding, curve smoothing, noise filtering, vector overlay preview,
direct canvas insertion as native PathEntity, and standalone SVG file export.
"""

from typing import List, Tuple, Optional
import os
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QFileDialog, QGroupBox, QSplitter, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QImage, QPixmap, QWheelEvent,
    QMouseEvent, QPaintEvent, QPainterPath
)

from laserforge.config import LAYER_PALETTE
from laserforge.core.models import PathEntity
from laserforge.core.image_tracer import ImageTracer, otsu_threshold


class TracePreviewCanvas(QWidget):
    """Zoomable/pannable canvas displaying the source image and traced vector overlay."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: Optional[QPixmap] = None
        self.contours: List[List[Tuple[float, float]]] = [] # In pixel coordinates
        self.image_opacity = 0.5  # 0.0 to 1.0

        # View transform
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._panning = False
        self._last_mouse = QPointF()

        self.setMinimumSize(450, 400)
        self.setStyleSheet("background-color: #1a1a22;")

    def set_source_image(self, pil_img: Image.Image):
        # Convert PIL Image to QPixmap
        img_rgb = pil_img.convert("RGBA")
        data = img_rgb.tobytes("raw", "RGBA")
        qimg = QImage(data, img_rgb.width, img_rgb.height, QImage.Format.Format_RGBA8888)
        self.pixmap = QPixmap.fromImage(qimg)
        self.reset_view()

    def set_contours(self, contours: List[List[Tuple[float, float]]]):
        self.contours = contours
        path = QPainterPath()
        for poly in contours:
            if len(poly) < 2:
                continue
            path.moveTo(poly[0][0], poly[0][1])
            for pt in poly[1:]:
                path.lineTo(pt[0], pt[1])
        self._cached_path = path
        self.update()

    def set_opacity(self, val: float):
        self.image_opacity = max(0.0, min(1.0, val))
        self.update()

    def reset_view(self):
        if not self.pixmap or self.pixmap.isNull():
            return
        w = max(10, self.pixmap.width())
        h = max(10, self.pixmap.height())

        avail_w = max(100, self.width() - 40)
        avail_h = max(100, self.height() - 40)

        self.zoom = min(avail_w / w, avail_h / h)
        self.pan_x = (self.width() - w * self.zoom) / 2.0
        self.pan_y = (self.height() - h * self.zoom) / 2.0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.reset_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pan_x == 0.0 and self.pan_y == 0.0:
            self.reset_view()

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        pos = event.position()
        self.pan_x = pos.x() - (pos.x() - self.pan_x) * factor
        self.pan_y = pos.y() - (pos.y() - self.pan_y) * factor
        self.zoom *= factor
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._panning = True
            self._last_mouse = event.position()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.position() - self._last_mouse
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self._last_mouse = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._panning = False

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#16161c"))

        if not self.pixmap or self.pixmap.isNull():
            painter.setPen(QColor("#757575"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded")
            return

        painter.save()
        painter.translate(self.pan_x, self.pan_y)
        painter.scale(self.zoom, self.zoom)

        # 1. Render background image with adjustable opacity
        painter.setOpacity(self.image_opacity)
        painter.drawPixmap(0, 0, self.pixmap)

        # Image border
        painter.setOpacity(1.0)
        border_pen = QPen(QColor("#424242"), 1.0, Qt.PenStyle.DashLine)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.drawRect(QRectF(0, 0, self.pixmap.width(), self.pixmap.height()))

        # 2. Render vector contours over image
        pen_vector = QPen(QColor("#00e5ff"), 1.5)
        pen_vector.setCosmetic(True)
        painter.setPen(pen_vector)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if hasattr(self, "_cached_path") and self._cached_path:
            painter.drawPath(self._cached_path)

        painter.restore()


class TraceImageDialog(QDialog):
    def __init__(
        self,
        pil_image: Image.Image,
        image_name: str = "Image",
        initial_width_mm: float = 80.0,
        initial_height_mm: float = 80.0,
        active_layer_id: int = 0,
        parent=None
    ):
        super().__init__(parent)
        self.pil_image = pil_image
        self.image_name = image_name
        self.active_layer_id = active_layer_id

        self.setWindowTitle(f"Trace Image to Vector (SVG) - {image_name}")
        self.resize(1000, 680)

        # Calculated pixel contours and final outputs
        self.pixel_contours: List[List[Tuple[float, float]]] = []
        self.result_path_entity: Optional[PathEntity] = None
        self.delete_original_image = False

        # Live calculation debounce timer
        self.calc_timer = QTimer(self)
        self.calc_timer.setSingleShot(True)
        self.calc_timer.setInterval(120)  # 120ms debounce
        self.calc_timer.timeout.connect(self._recalculate_contours)

        # Dimension variables
        orig_w, orig_h = pil_image.size
        self.aspect_ratio = orig_w / max(1, orig_h)
        self.initial_w_mm = initial_width_mm
        self.initial_h_mm = initial_width_mm / self.aspect_ratio if self.aspect_ratio else initial_height_mm

        self._init_ui()
        self.canvas.set_source_image(self.pil_image)

        # Initial calculation with Otsu auto-threshold
        self._auto_otsu()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Canvas View Container
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        canvas_header = QHBoxLayout()
        self.lbl_info = QLabel(f"<b>{self.image_name}</b> ({self.pil_image.width} × {self.pil_image.height} px)")
        self.lbl_info.setStyleSheet("color: #cfd8dc;")
        canvas_header.addWidget(self.lbl_info)
        canvas_header.addStretch(1)

        btn_fit = QPushButton("⛶ Fit View")
        btn_fit.clicked.connect(lambda: self.canvas.reset_view())
        canvas_header.addWidget(btn_fit)
        left_layout.addLayout(canvas_header)

        self.canvas = TracePreviewCanvas(self)
        left_layout.addWidget(self.canvas, 1)

        # Image fade slider
        fade_row = QHBoxLayout()
        fade_row.addWidget(QLabel("Image Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(lambda v: self.canvas.set_opacity(v / 100.0))
        fade_row.addWidget(self.opacity_slider, 1)

        self.lbl_stats = QLabel("Vectors: 0 contours | 0 vertices")
        self.lbl_stats.setStyleSheet("font-family: monospace; color: #00e5ff;")
        fade_row.addWidget(self.lbl_stats)
        left_layout.addLayout(fade_row)

        splitter.addWidget(left_widget)

        # Right Controls Panel
        right_widget = QWidget()
        right_widget.setFixedWidth(360)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(8)

        # 1. Tracing Parameters Group
        trace_group = QGroupBox("Tracing & Thresholding")
        trace_grid = QGridLayout(trace_group)
        trace_grid.setSpacing(6)

        # Threshold
        trace_grid.addWidget(QLabel("Threshold:"), 0, 0)
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(0, 255)
        self.thresh_slider.setValue(128)
        self.thresh_slider.valueChanged.connect(self._on_thresh_slider_changed)
        trace_grid.addWidget(self.thresh_slider, 0, 1)

        self.thresh_spin = QSpinBox()
        self.thresh_spin.setRange(0, 255)
        self.thresh_spin.setValue(128)
        self.thresh_spin.setFixedWidth(55)
        self.thresh_spin.valueChanged.connect(self._on_thresh_spin_changed)
        trace_grid.addWidget(self.thresh_spin, 0, 2)

        self.btn_auto_otsu = QPushButton("Auto (Otsu)")
        self.btn_auto_otsu.setToolTip("Automatically compute best threshold for this image")
        self.btn_auto_otsu.clicked.connect(self._auto_otsu)
        trace_grid.addWidget(self.btn_auto_otsu, 1, 0, 1, 3)

        # Invert toggle
        self.chk_invert = QCheckBox("Invert (Trace Light on Dark)")
        self.chk_invert.toggled.connect(self._schedule_calc)
        trace_grid.addWidget(self.chk_invert, 2, 0, 1, 3)

        # Smoothness (RDP Epsilon)
        trace_grid.addWidget(QLabel("Smoothness:"), 3, 0)
        self.smooth_spin = QDoubleSpinBox()
        self.smooth_spin.setRange(0.05, 10.0)
        self.smooth_spin.setSingleStep(0.2)
        self.smooth_spin.setValue(1.0)
        self.smooth_spin.setSuffix(" px")
        self.smooth_spin.valueChanged.connect(self._schedule_calc)
        trace_grid.addWidget(self.smooth_spin, 3, 1, 1, 2)

        # Noise / Dust Filter (Min Area)
        trace_grid.addWidget(QLabel("Noise Filter:"), 4, 0)
        self.noise_spin = QSpinBox()
        self.noise_spin.setRange(1, 1000)
        self.noise_spin.setValue(12)
        self.noise_spin.setSuffix(" px²")
        self.noise_spin.valueChanged.connect(self._schedule_calc)
        trace_grid.addWidget(self.noise_spin, 4, 1, 1, 2)

        # Gaussian Blur Pre-filter
        trace_grid.addWidget(QLabel("Denoise Blur:"), 5, 0)
        self.blur_spin = QDoubleSpinBox()
        self.blur_spin.setRange(0.0, 10.0)
        self.blur_spin.setSingleStep(0.5)
        self.blur_spin.setValue(0.5)
        self.blur_spin.setSuffix(" px")
        self.blur_spin.valueChanged.connect(self._schedule_calc)
        trace_grid.addWidget(self.blur_spin, 5, 1, 1, 2)

        right_layout.addWidget(trace_group)

        # 2. Output & Dimensions Group
        out_group = QGroupBox("Vector Output Dimensions")
        out_grid = QGridLayout(out_group)
        out_grid.setSpacing(6)

        out_grid.addWidget(QLabel("Width (mm):"), 0, 0)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1.0, 3000.0)
        self.width_spin.setValue(self.initial_w_mm)
        self.width_spin.setSuffix(" mm")
        self.width_spin.valueChanged.connect(self._on_width_changed)
        out_grid.addWidget(self.width_spin, 0, 1)

        out_grid.addWidget(QLabel("Height (mm):"), 1, 0)
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(1.0, 3000.0)
        self.height_spin.setValue(self.initial_h_mm)
        self.height_spin.setSuffix(" mm")
        self.height_spin.valueChanged.connect(self._on_height_changed)
        out_grid.addWidget(self.height_spin, 1, 1)

        self.chk_lock_aspect = QCheckBox("Lock Aspect Ratio 🔒")
        self.chk_lock_aspect.setChecked(True)
        out_grid.addWidget(self.chk_lock_aspect, 2, 0, 1, 2)

        out_grid.addWidget(QLabel("Target Layer:"), 3, 0)
        self.layer_combo = QComboBox()
        for p in LAYER_PALETTE:
            self.layer_combo.addItem(f"{p['name']} - {p['label']}", p["id"])
        if 0 <= self.active_layer_id < self.layer_combo.count():
            self.layer_combo.setCurrentIndex(self.active_layer_id)
        out_grid.addWidget(self.layer_combo, 3, 1)

        self.chk_delete_orig = QCheckBox("Delete Original Bitmap")
        self.chk_delete_orig.setChecked(True)
        out_grid.addWidget(self.chk_delete_orig, 4, 0, 1, 2)

        right_layout.addWidget(out_group)
        right_layout.addStretch(1)

        # 3. Action Buttons
        btn_apply = QPushButton("✔  Apply & Insert Vector")
        btn_apply.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 10px; font-size: 13px;"
        )
        btn_apply.clicked.connect(self._apply_and_close)
        right_layout.addWidget(btn_apply)

        btn_export = QPushButton("💾  Export as SVG File...")
        btn_export.setStyleSheet("font-weight: bold; padding: 8px;")
        btn_export.clicked.connect(self._export_svg)
        right_layout.addWidget(btn_export)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        right_layout.addWidget(btn_cancel)

        splitter.addWidget(right_widget)
        main_layout.addWidget(splitter)

    def _on_thresh_slider_changed(self, val: int):
        self.thresh_spin.blockSignals(True)
        self.thresh_spin.setValue(val)
        self.thresh_spin.blockSignals(False)
        self._schedule_calc()

    def _on_thresh_spin_changed(self, val: int):
        self.thresh_slider.blockSignals(True)
        self.thresh_slider.setValue(val)
        self.thresh_slider.blockSignals(False)
        self._schedule_calc()

    def _auto_otsu(self):
        gray = self.pil_image.convert("L")
        thresh = otsu_threshold(np.array(gray))
        self.thresh_slider.setValue(thresh)
        self.thresh_spin.setValue(thresh)
        self._recalculate_contours()

    def _on_width_changed(self, w: float):
        if self.chk_lock_aspect.isChecked() and self.aspect_ratio > 0:
            h = w / self.aspect_ratio
            self.height_spin.blockSignals(True)
            self.height_spin.setValue(h)
            self.height_spin.blockSignals(False)

    def _on_height_changed(self, h: float):
        if self.chk_lock_aspect.isChecked() and self.aspect_ratio > 0:
            w = h * self.aspect_ratio
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(w)
            self.width_spin.blockSignals(False)

    def _schedule_calc(self):
        self.calc_timer.start()

    def _recalculate_contours(self):
        """Runs the vector tracer in pixel space for the live preview."""
        thresh = self.thresh_spin.value()
        invert = self.chk_invert.isChecked()
        smooth = self.smooth_spin.value()
        noise = float(self.noise_spin.value())
        blur = self.blur_spin.value()

        # Extract contours in image pixel space
        contours = ImageTracer.trace_image(
            self.pil_image,
            threshold=thresh,
            invert=invert,
            blur_radius=blur,
            smoothness=smooth,
            min_area_pixels=noise,
            scale_x=1.0,
            scale_y=1.0
        )

        self.pixel_contours = contours
        self.canvas.set_contours(contours)

        total_pts = sum(len(c) for c in contours)
        self.lbl_stats.setText(f"Vectors: {len(contours)} contours | {total_pts} vertices")

    def _apply_and_close(self):
        """Constructs native PathEntity scaled to desired millimeter dimensions."""
        if not self.pixel_contours:
            QMessageBox.warning(self, "Trace Image", "No vector contours extracted. Try adjusting threshold.")
            return

        w_mm = self.width_spin.value()
        h_mm = self.height_spin.value()
        scale_x = w_mm / max(1.0, self.pil_image.width)
        scale_y = h_mm / max(1.0, self.pil_image.height)

        scaled_contours = []
        for poly in self.pixel_contours:
            scaled_poly = [(pt[0] * scale_x, pt[1] * scale_y) for pt in poly]
            scaled_contours.append(scaled_poly)

        layer_id = self.layer_combo.currentData()
        name = f"Traced_{os.path.splitext(self.image_name)[0]}"

        self.result_path_entity = PathEntity(
            layer_id=layer_id,
            name=name,
            x=0.0,
            y=0.0,
            contours=scaled_contours,
            closed=True
        )
        self.delete_original_image = self.chk_delete_orig.isChecked()
        self.accept()

    def _export_svg(self):
        """Exports the traced vectors directly to a standard SVG file."""
        if not self.pixel_contours:
            QMessageBox.warning(self, "Export SVG", "No vector contours extracted. Try adjusting threshold.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Export Traced SVG", f"{os.path.splitext(self.image_name)[0]}.svg",
            "Scalable Vector Graphics (*.svg);;All Files (*)"
        )
        if not out_path:
            return

        w_mm = self.width_spin.value()
        h_mm = self.height_spin.value()
        scale_x = w_mm / max(1.0, self.pil_image.width)
        scale_y = h_mm / max(1.0, self.pil_image.height)

        scaled_contours = [
            [(pt[0] * scale_x, pt[1] * scale_y) for pt in poly]
            for poly in self.pixel_contours
        ]

        try:
            ImageTracer.export_svg_file(scaled_contours, out_path, w_mm, h_mm)
            QMessageBox.information(self, "SVG Exported", f"Successfully exported vector SVG to:\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to write SVG: {e}")
