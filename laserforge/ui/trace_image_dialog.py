"""
LaserForge Trace Image Dialog.
Interactive, professional-grade image-to-vector tracing studio (LightBurn-style Trace Image tool).
Provides:
  - 4 View Modes: Overlay (Image + Vectors), Binary Mask (B&W), Vectors Only, and Original Image
  - 3 Detection Engines: Standard Threshold (Global / Otsu), Adaptive Gaussian (Photos / Uneven Lighting), Canny Edge Sketch
  - Curve & Corner Refinement: Sub-pixel RDP polygon simplification, corner-preserving Chaikin curve smoothing, turning-angle threshold
  - Filtering: Bilateral edge-preserving denoise pre-filter, dust/speck min area filter, ignore image border, ignore inner holes
  - Presets: Clean Logo / Clipart, Photo / Sketch, Detailed Text / Line Art, Outer Silhouette Only, Canny Edge Sketch
  - Real-time responsive live preview (<15ms per frame) with zoom & pan controls, node visualization, and translucent fill preview
  - Native PathEntity canvas insertion & direct standalone SVG export
"""

from typing import List, Tuple, Optional, Dict, Any
import os
import time
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QFileDialog, QGroupBox, QSplitter, QFrame, QMessageBox,
    QScrollArea, QButtonGroup
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
    """
    Interactive zoomable & pannable canvas displaying the source image,
    the binary threshold mask, and traced vector paths.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: Optional[QPixmap] = None
        self.mask_pixmap: Optional[QPixmap] = None
        self.contours: List[List[Tuple[float, float]]] = []

        # View settings
        self.view_mode: str = "overlay"  # "overlay", "mask", "vectors", "original"
        self.image_opacity: float = 0.5
        self.show_nodes: bool = False
        self.show_fill: bool = True
        self.show_vectors_on_mask: bool = True

        self._cached_path = QPainterPath()

        # View transform
        self.zoom: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0
        self._panning: bool = False
        self._last_mouse = QPointF()

        self.setMinimumSize(450, 420)
        self.setStyleSheet("background-color: #14141a;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_source_image(self, pil_img: Image.Image):
        """Loads and prepares the source PIL image as QPixmap."""
        img_rgb = pil_img.convert("RGBA")
        data = img_rgb.tobytes("raw", "RGBA")
        qimg = QImage(data, img_rgb.width, img_rgb.height, QImage.Format.Format_RGBA8888).copy()
        self.pixmap = QPixmap.fromImage(qimg)
        self.reset_view()

    def set_binary_mask(self, mask_np: Optional[np.ndarray]):
        """Updates the binary mask (0 or 255) for the B&W preview mode."""
        if mask_np is None or mask_np.size == 0:
            self.mask_pixmap = None
            self.update()
            return
        h, w = mask_np.shape[:2]
        mask_contiguous = np.ascontiguousarray(mask_np, dtype=np.uint8)
        qimg = QImage(mask_contiguous.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        self.mask_pixmap = QPixmap.fromImage(qimg)
        self.update()

    def set_contours(self, contours: List[List[Tuple[float, float]]]):
        """Sets the traced vector contour loops and builds the QPainterPath."""
        self.contours = contours
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for poly in contours:
            if len(poly) < 2:
                continue
            path.moveTo(poly[0][0], poly[0][1])
            for pt in poly[1:]:
                path.lineTo(pt[0], pt[1])
            path.closeSubpath()
        self._cached_path = path
        self.update()

    def set_view_mode(self, mode: str):
        self.view_mode = mode
        self.update()

    def set_opacity(self, val: float):
        self.image_opacity = max(0.0, min(1.0, val))
        self.update()

    def set_show_nodes(self, show: bool):
        self.show_nodes = show
        self.update()

    def set_show_fill(self, show: bool):
        self.show_fill = show
        self.update()

    def reset_view(self):
        """Fits the image comfortably within the canvas view."""
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

    def zoom_in(self):
        self._zoom_at(self.width() / 2.0, self.height() / 2.0, 1.25)

    def zoom_out(self):
        self._zoom_at(self.width() / 2.0, self.height() / 2.0, 0.8)

    def zoom_actual(self):
        if not self.pixmap:
            return
        self.zoom = 1.0
        self.pan_x = (self.width() - self.pixmap.width()) / 2.0
        self.pan_y = (self.height() - self.pixmap.height()) / 2.0
        self.update()

    def _zoom_at(self, center_x: float, center_y: float, factor: float):
        new_zoom = max(0.02, min(50.0, self.zoom * factor))
        actual_factor = new_zoom / self.zoom
        self.pan_x = center_x - (center_x - self.pan_x) * actual_factor
        self.pan_y = center_y - (center_y - self.pan_y) * actual_factor
        self.zoom = new_zoom
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
        self._zoom_at(pos.x(), pos.y(), factor)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._panning = True
            self._last_mouse = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.position() - self._last_mouse
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self._last_mouse = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._panning = False
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#14141a"))

        if not self.pixmap or self.pixmap.isNull():
            painter.setPen(QColor("#757575"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded")
            return

        painter.save()
        painter.translate(self.pan_x, self.pan_y)
        painter.scale(self.zoom, self.zoom)

        w = float(self.pixmap.width())
        h = float(self.pixmap.height())

        # 1. Base Layer Rendering
        if self.view_mode == "mask":
            if self.mask_pixmap and not self.mask_pixmap.isNull():
                painter.setOpacity(1.0)
                painter.drawPixmap(0, 0, self.mask_pixmap)
            else:
                painter.fillRect(QRectF(0, 0, w, h), QColor("#000000"))
        elif self.view_mode == "vectors":
            # Solid dark slate workspace background
            painter.fillRect(QRectF(0, 0, w, h), QColor("#1c1d26"))
        elif self.view_mode == "original":
            painter.setOpacity(1.0)
            painter.drawPixmap(0, 0, self.pixmap)
        else:  # "overlay"
            painter.setOpacity(self.image_opacity)
            painter.drawPixmap(0, 0, self.pixmap)

        # 2. Outer Image Frame (dashed reference box)
        painter.setOpacity(1.0)
        border_pen = QPen(QColor("#546e7a"), 1.0, Qt.PenStyle.DashLine)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0, 0, w, h))

        # 3. Vector Contours & Nodes
        show_vectors = (
            self.view_mode in ("overlay", "vectors") or
            (self.view_mode == "mask" and self.show_vectors_on_mask)
        )

        if show_vectors and hasattr(self, "_cached_path") and not self._cached_path.isEmpty():
            # Translucent fill preview
            if self.show_fill:
                fill_color = QColor(0, 229, 255, 40) if self.view_mode != "mask" else QColor(255, 64, 129, 50)
                painter.setBrush(QBrush(fill_color))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)

            # High-visibility cosmetic vector stroke
            stroke_color = QColor("#00e5ff") if self.view_mode != "mask" else QColor("#ff4081")
            pen_vector = QPen(stroke_color, 1.4)
            pen_vector.setCosmetic(True)
            painter.setPen(pen_vector)
            painter.drawPath(self._cached_path)

            # Node vertex markers
            if self.show_nodes and self.contours:
                painter.setBrush(QBrush(QColor("#ffea00")))
                node_pen = QPen(QColor("#111111"), 0.5)
                node_pen.setCosmetic(True)
                painter.setPen(node_pen)
                r = 2.2 / max(0.15, self.zoom)
                for poly in self.contours:
                    for pt in poly:
                        painter.drawEllipse(QPointF(pt[0], pt[1]), r, r)

        painter.restore()


class TraceImageDialog(QDialog):
    """Full-featured LightBurn-grade image-to-vector tracing studio."""

    PRESETS = {
        "Clean Logo / Clipart (Default)": {
            "mode": 0,  # Standard Otsu
            "invert": False,
            "smoothness": 0.8,
            "corner_sharpness": 65,
            "smooth_iter": 1,
            "noise_filter": 12,
            "denoise_blur": 0.5,
            "ignore_border": True,
            "ignore_holes": False,
            "desc": "Best for high-contrast logos, black & white clipart, and crisp graphic icons."
        },
        "Photo / Sketch (Adaptive Gaussian)": {
            "mode": 1,  # Adaptive
            "adaptive_bs": 15,
            "adaptive_c": 4.0,
            "invert": False,
            "smoothness": 0.6,
            "corner_sharpness": 65,
            "smooth_iter": 1,
            "noise_filter": 16,
            "denoise_blur": 1.0,
            "ignore_border": True,
            "ignore_holes": False,
            "desc": "Gaussian thresholding adapts to uneven lighting, photo gradients, and pencil sketches."
        },
        "Detailed Text & Line Art": {
            "mode": 0,  # Standard Otsu
            "invert": False,
            "smoothness": 0.3,
            "corner_sharpness": 40,
            "smooth_iter": 0,  # Raw polygons to keep sharp serifs
            "noise_filter": 4,
            "denoise_blur": 0.0,
            "ignore_border": True,
            "ignore_holes": False,
            "desc": "Ultra-low simplification with 0 curve rounding to preserve sharp serif fonts and lines."
        },
        "Outer Silhouette Only (No Holes)": {
            "mode": 0,  # Standard Otsu
            "invert": False,
            "smoothness": 1.2,
            "corner_sharpness": 70,
            "smooth_iter": 2,  # Organic smooth
            "noise_filter": 25,
            "denoise_blur": 1.0,
            "ignore_border": True,
            "ignore_holes": True,
            "desc": "Traces outermost perimeter only — ideal for sticker cut lines, badge cutouts, and base plates."
        },
        "Canny Edge Sketch": {
            "mode": 2,  # Canny
            "canny_thresh": 100,
            "invert": False,
            "smoothness": 0.8,
            "corner_sharpness": 60,
            "smooth_iter": 1,
            "noise_filter": 10,
            "denoise_blur": 0.5,
            "ignore_border": True,
            "ignore_holes": False,
            "desc": "Extracts gradient outline boundaries directly via Canny edge detection."
        }
    }

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

        self.setWindowTitle(f"Trace Image to Vector (SVG Studio) — {image_name}")
        self.resize(1160, 740)

        self.pixel_contours: List[List[Tuple[float, float]]] = []
        self.result_path_entity: Optional[PathEntity] = None
        self.delete_original_image = False
        self._loading_preset = False

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

        # Initial Otsu calculation and preset load
        self._apply_preset("Clean Logo / Clipart (Default)")

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # -------------------------------------------------------------
        # LEFT PANE: Canvas + View Toolbar + Status
        # -------------------------------------------------------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Header Toolbar: View Mode Buttons + Zoom Controls
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self.lbl_info = QLabel(f"<b>{self.image_name}</b> ({self.pil_image.width} × {self.pil_image.height} px)")
        self.lbl_info.setStyleSheet("color: #cfd8dc; font-size: 12px;")
        top_bar.addWidget(self.lbl_info)
        top_bar.addStretch(1)

        # View Mode Button Group
        mode_btn_group = QButtonGroup(self)
        mode_btn_group.setExclusive(True)

        self.btn_view_overlay = QPushButton("🔲 Overlay")
        self.btn_view_overlay.setCheckable(True)
        self.btn_view_overlay.setChecked(True)
        self.btn_view_overlay.clicked.connect(lambda: self._set_view_mode("overlay"))
        mode_btn_group.addButton(self.btn_view_overlay)
        top_bar.addWidget(self.btn_view_overlay)

        self.btn_view_mask = QPushButton("⬛ Mask (B&W)")
        self.btn_view_mask.setCheckable(True)
        self.btn_view_mask.clicked.connect(lambda: self._set_view_mode("mask"))
        mode_btn_group.addButton(self.btn_view_mask)
        top_bar.addWidget(self.btn_view_mask)

        self.btn_view_vectors = QPushButton("⚡ Vectors")
        self.btn_view_vectors.setCheckable(True)
        self.btn_view_vectors.clicked.connect(lambda: self._set_view_mode("vectors"))
        mode_btn_group.addButton(self.btn_view_vectors)
        top_bar.addWidget(self.btn_view_vectors)

        self.btn_view_orig = QPushButton("🖼 Original")
        self.btn_view_orig.setCheckable(True)
        self.btn_view_orig.clicked.connect(lambda: self._set_view_mode("original"))
        mode_btn_group.addButton(self.btn_view_orig)
        top_bar.addWidget(self.btn_view_orig)

        # Visual check toggles
        self.chk_show_fill = QCheckBox("Fill")
        self.chk_show_fill.setChecked(True)
        self.chk_show_fill.setToolTip("Show semi-transparent preview fill for closed vector paths")
        self.chk_show_fill.toggled.connect(lambda v: self.canvas.set_show_fill(v))
        top_bar.addWidget(self.chk_show_fill)

        self.chk_show_nodes = QCheckBox("Nodes")
        self.chk_show_nodes.setChecked(False)
        self.chk_show_nodes.setToolTip("Show vector vertex node dots")
        self.chk_show_nodes.toggled.connect(lambda v: self.canvas.set_show_nodes(v))
        top_bar.addWidget(self.chk_show_nodes)

        # Zoom buttons
        btn_zin = QPushButton("➕")
        btn_zin.setToolTip("Zoom In (or Wheel Up)")
        btn_zin.setFixedWidth(28)
        btn_zin.clicked.connect(lambda: self.canvas.zoom_in())
        top_bar.addWidget(btn_zin)

        btn_zout = QPushButton("➖")
        btn_zout.setToolTip("Zoom Out (or Wheel Down)")
        btn_zout.setFixedWidth(28)
        btn_zout.clicked.connect(lambda: self.canvas.zoom_out())
        top_bar.addWidget(btn_zout)

        btn_z11 = QPushButton("1:1")
        btn_z11.setToolTip("Actual Size (100%)")
        btn_z11.setFixedWidth(34)
        btn_z11.clicked.connect(lambda: self.canvas.zoom_actual())
        top_bar.addWidget(btn_z11)

        btn_fit = QPushButton("⛶ Fit")
        btn_fit.setToolTip("Fit Image to View")
        btn_fit.clicked.connect(lambda: self.canvas.reset_view())
        top_bar.addWidget(btn_fit)

        left_layout.addLayout(top_bar)

        # Canvas Widget
        self.canvas = TracePreviewCanvas(self)
        left_layout.addWidget(self.canvas, 1)

        # Bottom Bar: Opacity + Live Contour Stats
        bot_bar = QHBoxLayout()
        self.lbl_opacity = QLabel("Image Opacity:")
        bot_bar.addWidget(self.lbl_opacity)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        bot_bar.addWidget(self.opacity_slider, 1)

        self.lbl_opacity_val = QLabel("50%")
        self.lbl_opacity_val.setFixedWidth(35)
        bot_bar.addWidget(self.lbl_opacity_val)

        bot_bar.addSpacing(12)

        self.lbl_stats = QLabel("Vectors: 0 contours | 0 vertices | 0.0 ms")
        self.lbl_stats.setStyleSheet("font-family: monospace; color: #00e5ff; font-weight: bold;")
        bot_bar.addWidget(self.lbl_stats)

        left_layout.addLayout(bot_bar)
        splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # RIGHT PANE: Controls (Encapsulated in a ScrollArea)
        # -------------------------------------------------------------
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFixedWidth(400)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(8)

        # 1. Preset Selector Group
        preset_group = QGroupBox("Quick Presets")
        preset_vbox = QVBoxLayout(preset_group)
        preset_vbox.setSpacing(4)

        self.preset_combo = QComboBox()
        for p_name in self.PRESETS.keys():
            self.preset_combo.addItem(p_name)
        self.preset_combo.addItem("Custom")
        self.preset_combo.currentTextChanged.connect(self._on_preset_selected)
        preset_vbox.addWidget(self.preset_combo)

        self.lbl_preset_desc = QLabel(self.PRESETS["Clean Logo / Clipart (Default)"]["desc"])
        self.lbl_preset_desc.setStyleSheet("color: #90a4ae; font-size: 11px; font-style: italic;")
        self.lbl_preset_desc.setWordWrap(True)
        preset_vbox.addWidget(self.lbl_preset_desc)

        right_layout.addWidget(preset_group)

        # 2. Detection & Thresholding Group
        detect_group = QGroupBox("Detection Engine & Binarization")
        detect_grid = QGridLayout(detect_group)
        detect_grid.setSpacing(6)

        detect_grid.addWidget(QLabel("Mode:"), 0, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Standard Threshold (Global / Otsu)")
        self.combo_mode.addItem("Adaptive Gaussian (Photos / Lighting)")
        self.combo_mode.addItem("Canny Edge Sketch")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        detect_grid.addWidget(self.combo_mode, 0, 1, 1, 2)

        # Invert toggle
        self.chk_invert = QCheckBox("Invert (Trace Light on Dark)")
        self.chk_invert.setToolTip("Inverts black and white foreground detection")
        self.chk_invert.toggled.connect(self._on_user_param_changed)
        detect_grid.addWidget(self.chk_invert, 1, 0, 1, 3)

        # Sub-container: Standard Threshold Controls
        self.widget_thresh = QWidget()
        w_thresh_layout = QGridLayout(self.widget_thresh)
        w_thresh_layout.setContentsMargins(0, 0, 0, 0)
        w_thresh_layout.setSpacing(6)

        w_thresh_layout.addWidget(QLabel("Cutoff:"), 0, 0)
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(0, 255)
        self.thresh_slider.setValue(128)
        self.thresh_slider.valueChanged.connect(self._on_thresh_slider_changed)
        w_thresh_layout.addWidget(self.thresh_slider, 0, 1)

        self.thresh_spin = QSpinBox()
        self.thresh_spin.setRange(0, 255)
        self.thresh_spin.setValue(128)
        self.thresh_spin.setFixedWidth(55)
        self.thresh_spin.valueChanged.connect(self._on_thresh_spin_changed)
        w_thresh_layout.addWidget(self.thresh_spin, 0, 2)

        self.btn_auto_otsu = QPushButton("⚡ Auto Threshold (Otsu)")
        self.btn_auto_otsu.setToolTip("Automatically compute optimal binarization threshold via OpenCV Otsu")
        self.btn_auto_otsu.clicked.connect(self._auto_otsu)
        w_thresh_layout.addWidget(self.btn_auto_otsu, 1, 0, 1, 3)
        detect_grid.addWidget(self.widget_thresh, 2, 0, 1, 3)

        # Sub-container: Adaptive Gaussian Controls
        self.widget_adaptive = QWidget()
        w_adapt_layout = QGridLayout(self.widget_adaptive)
        w_adapt_layout.setContentsMargins(0, 0, 0, 0)
        w_adapt_layout.setSpacing(6)

        w_adapt_layout.addWidget(QLabel("Block Size:"), 0, 0)
        self.adaptive_bs_slider = QSlider(Qt.Orientation.Horizontal)
        self.adaptive_bs_slider.setRange(1, 49)  # 2*v+1 gives 3 to 99
        self.adaptive_bs_slider.setValue(7)       # 2*7+1 = 15
        self.adaptive_bs_slider.valueChanged.connect(self._on_adaptive_bs_slider_changed)
        w_adapt_layout.addWidget(self.adaptive_bs_slider, 0, 1)

        self.adaptive_bs_spin = QSpinBox()
        self.adaptive_bs_spin.setRange(3, 99)
        self.adaptive_bs_spin.setSingleStep(2)
        self.adaptive_bs_spin.setValue(15)
        self.adaptive_bs_spin.setFixedWidth(55)
        self.adaptive_bs_spin.valueChanged.connect(self._on_adaptive_bs_spin_changed)
        w_adapt_layout.addWidget(self.adaptive_bs_spin, 0, 2)

        w_adapt_layout.addWidget(QLabel("Constant C:"), 1, 0)
        self.adaptive_c_slider = QSlider(Qt.Orientation.Horizontal)
        self.adaptive_c_slider.setRange(-20, 20)
        self.adaptive_c_slider.setValue(4)
        self.adaptive_c_slider.valueChanged.connect(self._on_adaptive_c_slider_changed)
        w_adapt_layout.addWidget(self.adaptive_c_slider, 1, 1)

        self.adaptive_c_spin = QDoubleSpinBox()
        self.adaptive_c_spin.setRange(-20.0, 20.0)
        self.adaptive_c_spin.setSingleStep(0.5)
        self.adaptive_c_spin.setValue(4.0)
        self.adaptive_c_spin.setFixedWidth(55)
        self.adaptive_c_spin.valueChanged.connect(self._on_adaptive_c_spin_changed)
        w_adapt_layout.addWidget(self.adaptive_c_spin, 1, 2)

        detect_grid.addWidget(self.widget_adaptive, 3, 0, 1, 3)
        self.widget_adaptive.hide()

        # Sub-container: Canny Edge Controls
        self.widget_canny = QWidget()
        w_canny_layout = QGridLayout(self.widget_canny)
        w_canny_layout.setContentsMargins(0, 0, 0, 0)
        w_canny_layout.setSpacing(6)

        w_canny_layout.addWidget(QLabel("Sensitivity:"), 0, 0)
        self.canny_slider = QSlider(Qt.Orientation.Horizontal)
        self.canny_slider.setRange(10, 255)
        self.canny_slider.setValue(100)
        self.canny_slider.valueChanged.connect(self._on_canny_slider_changed)
        w_canny_layout.addWidget(self.canny_slider, 0, 1)

        self.canny_spin = QSpinBox()
        self.canny_spin.setRange(10, 255)
        self.canny_spin.setValue(100)
        self.canny_spin.setFixedWidth(55)
        self.canny_spin.valueChanged.connect(self._on_canny_spin_changed)
        w_canny_layout.addWidget(self.canny_spin, 0, 2)

        detect_grid.addWidget(self.widget_canny, 4, 0, 1, 3)
        self.widget_canny.hide()

        right_layout.addWidget(detect_group)

        # 3. Vector Refinement & Curve Smoothing Group
        refine_group = QGroupBox("Vector Smoothing & Corner Control")
        refine_grid = QGridLayout(refine_group)
        refine_grid.setSpacing(6)

        # Smoothness (RDP Epsilon)
        refine_grid.addWidget(QLabel("Simplification:"), 0, 0)
        self.smooth_slider = QSlider(Qt.Orientation.Horizontal)
        self.smooth_slider.setRange(5, 400)  # maps to 0.05 - 4.00 px
        self.smooth_slider.setValue(80)
        self.smooth_slider.valueChanged.connect(self._on_smooth_slider_changed)
        refine_grid.addWidget(self.smooth_slider, 0, 1)

        self.smooth_spin = QDoubleSpinBox()
        self.smooth_spin.setRange(0.05, 5.0)
        self.smooth_spin.setSingleStep(0.1)
        self.smooth_spin.setValue(0.8)
        self.smooth_spin.setSuffix(" px")
        self.smooth_spin.setFixedWidth(70)
        self.smooth_spin.valueChanged.connect(self._on_smooth_spin_changed)
        refine_grid.addWidget(self.smooth_spin, 0, 2)

        # Curve Smoothing iterations (Chaikin)
        refine_grid.addWidget(QLabel("Curve Smooth:"), 1, 0)
        self.combo_smooth_iter = QComboBox()
        self.combo_smooth_iter.addItem("None (Raw Polygons)")
        self.combo_smooth_iter.addItem("Light (1 Subdiv)")
        self.combo_smooth_iter.addItem("High (2 Subdiv)")
        self.combo_smooth_iter.setCurrentIndex(1)
        self.combo_smooth_iter.currentIndexChanged.connect(self._on_user_param_changed)
        refine_grid.addWidget(self.combo_smooth_iter, 1, 1, 1, 2)

        # Corner Sharpness (Preservation Threshold)
        refine_grid.addWidget(QLabel("Corner Keep:"), 2, 0)
        self.corner_slider = QSlider(Qt.Orientation.Horizontal)
        self.corner_slider.setRange(30, 90)
        self.corner_slider.setValue(65)
        self.corner_slider.valueChanged.connect(self._on_corner_slider_changed)
        refine_grid.addWidget(self.corner_slider, 2, 1)

        self.corner_spin = QSpinBox()
        self.corner_spin.setRange(30, 90)
        self.corner_spin.setValue(65)
        self.corner_spin.setSuffix("°")
        self.corner_spin.setFixedWidth(70)
        self.corner_spin.setToolTip("Corners sharper than this angle will remain crisp and unrounded")
        self.corner_spin.valueChanged.connect(self._on_corner_spin_changed)
        refine_grid.addWidget(self.corner_spin, 2, 2)

        # Denoise Pre-filter
        refine_grid.addWidget(QLabel("Denoise Blur:"), 3, 0)
        self.blur_spin = QDoubleSpinBox()
        self.blur_spin.setRange(0.0, 8.0)
        self.blur_spin.setSingleStep(0.2)
        self.blur_spin.setValue(0.5)
        self.blur_spin.setSuffix(" px")
        self.blur_spin.setToolTip("Bilateral edge-preserving filter to remove bitmap noise and grain")
        self.blur_spin.valueChanged.connect(self._on_user_param_changed)
        refine_grid.addWidget(self.blur_spin, 3, 1, 1, 2)

        # Dust / Noise Filter (Min Area)
        refine_grid.addWidget(QLabel("Noise Filter:"), 4, 0)
        self.noise_spin = QSpinBox()
        self.noise_spin.setRange(0, 2000)
        self.noise_spin.setSingleStep(5)
        self.noise_spin.setValue(12)
        self.noise_spin.setSuffix(" px²")
        self.noise_spin.setToolTip("Discard small speckles and noise contours below this area")
        self.noise_spin.valueChanged.connect(self._on_user_param_changed)
        refine_grid.addWidget(self.noise_spin, 4, 1, 1, 2)

        # Ignore outer image border
        self.chk_ignore_border = QCheckBox("Ignore Outer Image Border")
        self.chk_ignore_border.setChecked(True)
        self.chk_ignore_border.setToolTip("Drops the rectangular bounding box framing the entire image")
        self.chk_ignore_border.toggled.connect(self._on_user_param_changed)
        refine_grid.addWidget(self.chk_ignore_border, 5, 0, 1, 3)

        # Ignore inner holes
        self.chk_ignore_holes = QCheckBox("Ignore Inner Holes (Silhouette Only)")
        self.chk_ignore_holes.setChecked(False)
        self.chk_ignore_holes.setToolTip("Extracts only outermost outer contours — great for cutting outline badges")
        self.chk_ignore_holes.toggled.connect(self._on_user_param_changed)
        refine_grid.addWidget(self.chk_ignore_holes, 6, 0, 1, 3)

        right_layout.addWidget(refine_group)

        # 4. Output Dimensions & Target Layer Group
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

        self.chk_delete_orig = QCheckBox("Delete Original Bitmap on Canvas")
        self.chk_delete_orig.setChecked(True)
        out_grid.addWidget(self.chk_delete_orig, 4, 0, 1, 2)

        right_layout.addWidget(out_group)
        right_layout.addStretch(1)

        # 5. Action Buttons
        btn_apply = QPushButton("✔  Apply & Insert Vector")
        btn_apply.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 10px; font-size: 13px; border-radius: 4px;"
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

        scroll_area.setWidget(right_widget)
        splitter.addWidget(scroll_area)
        main_layout.addWidget(splitter)

    # -----------------------------------------------------------------
    # View & Opacity Controls
    # -----------------------------------------------------------------
    def _set_view_mode(self, mode: str):
        self.canvas.set_view_mode(mode)
        # Enable opacity slider only for overlay mode
        is_overlay = (mode == "overlay")
        self.opacity_slider.setEnabled(is_overlay)
        self.lbl_opacity.setEnabled(is_overlay)
        self.lbl_opacity_val.setEnabled(is_overlay)

    def _on_opacity_slider_changed(self, val: int):
        self.lbl_opacity_val.setText(f"{val}%")
        self.canvas.set_opacity(val / 100.0)

    # -----------------------------------------------------------------
    # Preset Handling
    # -----------------------------------------------------------------
    def _on_preset_selected(self, preset_name: str):
        if self._loading_preset or preset_name == "Custom":
            return
        self._apply_preset(preset_name)

    def _apply_preset(self, preset_name: str):
        p = self.PRESETS.get(preset_name)
        if not p:
            return

        self._loading_preset = True
        try:
            self.lbl_preset_desc.setText(p.get("desc", ""))
            mode_idx = p.get("mode", 0)
            self.combo_mode.setCurrentIndex(mode_idx)
            self._update_mode_widgets(mode_idx)

            self.chk_invert.setChecked(p.get("invert", False))

            if mode_idx == 0:
                # Standard Otsu
                gray = np.array(self.pil_image.convert("L"))
                auto_t = otsu_threshold(gray)
                self.thresh_slider.setValue(auto_t)
                self.thresh_spin.setValue(auto_t)
            elif mode_idx == 1:
                # Adaptive
                bs = p.get("adaptive_bs", 15)
                c = p.get("adaptive_c", 4.0)
                self.adaptive_bs_spin.setValue(bs)
                self.adaptive_bs_slider.setValue((bs - 1) // 2)
                self.adaptive_c_spin.setValue(c)
                self.adaptive_c_slider.setValue(int(c))
            elif mode_idx == 2:
                # Canny
                ct = p.get("canny_thresh", 100)
                self.canny_slider.setValue(ct)
                self.canny_spin.setValue(ct)

            # Smoothness
            sm = p.get("smoothness", 0.8)
            self.smooth_spin.setValue(sm)
            self.smooth_slider.setValue(int(sm * 100))

            # Corner
            cn = p.get("corner_sharpness", 65)
            self.corner_spin.setValue(cn)
            self.corner_slider.setValue(cn)

            # Curve smoothing
            self.combo_smooth_iter.setCurrentIndex(p.get("smooth_iter", 1))

            # Filters
            self.noise_spin.setValue(p.get("noise_filter", 12))
            self.blur_spin.setValue(p.get("denoise_blur", 0.5))
            self.chk_ignore_border.setChecked(p.get("ignore_border", True))
            self.chk_ignore_holes.setChecked(p.get("ignore_holes", False))
        finally:
            self._loading_preset = False

        self._recalculate_contours()

    def _mark_custom_preset(self):
        if not self._loading_preset and self.preset_combo.currentText() != "Custom":
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentText("Custom")
            self.lbl_preset_desc.setText("Customized tracing parameters.")
            self.preset_combo.blockSignals(False)

    def _on_user_param_changed(self):
        self._mark_custom_preset()
        self._schedule_calc()

    # -----------------------------------------------------------------
    # Mode Switching
    # -----------------------------------------------------------------
    def _on_mode_changed(self, idx: int):
        self._update_mode_widgets(idx)
        self._mark_custom_preset()
        self._schedule_calc()

    def _update_mode_widgets(self, idx: int):
        self.widget_thresh.setVisible(idx == 0)
        self.widget_adaptive.setVisible(idx == 1)
        self.widget_canny.setVisible(idx == 2)

    # -----------------------------------------------------------------
    # Synced Sliders & SpinBoxes
    # -----------------------------------------------------------------
    def _on_thresh_slider_changed(self, val: int):
        self.thresh_spin.blockSignals(True)
        self.thresh_spin.setValue(val)
        self.thresh_spin.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_thresh_spin_changed(self, val: int):
        self.thresh_slider.blockSignals(True)
        self.thresh_slider.setValue(val)
        self.thresh_slider.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _auto_otsu(self):
        if self.combo_mode.currentIndex() != 0:
            self.combo_mode.setCurrentIndex(0)
        gray = np.array(self.pil_image.convert("L"))
        thresh = otsu_threshold(gray)
        self.thresh_slider.setValue(thresh)
        self.thresh_spin.setValue(thresh)
        self._recalculate_contours()

    def _on_adaptive_bs_slider_changed(self, v: int):
        bs = 2 * v + 1
        self.adaptive_bs_spin.blockSignals(True)
        self.adaptive_bs_spin.setValue(bs)
        self.adaptive_bs_spin.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_adaptive_bs_spin_changed(self, bs: int):
        if bs % 2 == 0:
            bs += 1
            self.adaptive_bs_spin.setValue(bs)
        v = (bs - 1) // 2
        self.adaptive_bs_slider.blockSignals(True)
        self.adaptive_bs_slider.setValue(v)
        self.adaptive_bs_slider.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_adaptive_c_slider_changed(self, val: int):
        self.adaptive_c_spin.blockSignals(True)
        self.adaptive_c_spin.setValue(float(val))
        self.adaptive_c_spin.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_adaptive_c_spin_changed(self, val: float):
        self.adaptive_c_slider.blockSignals(True)
        self.adaptive_c_slider.setValue(int(val))
        self.adaptive_c_slider.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_canny_slider_changed(self, val: int):
        self.canny_spin.blockSignals(True)
        self.canny_spin.setValue(val)
        self.canny_spin.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_canny_spin_changed(self, val: int):
        self.canny_slider.blockSignals(True)
        self.canny_slider.setValue(val)
        self.canny_slider.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_smooth_slider_changed(self, val: int):
        sm = val / 100.0
        self.smooth_spin.blockSignals(True)
        self.smooth_spin.setValue(sm)
        self.smooth_spin.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_smooth_spin_changed(self, sm: float):
        self.smooth_slider.blockSignals(True)
        self.smooth_slider.setValue(int(sm * 100))
        self.smooth_slider.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_corner_slider_changed(self, val: int):
        self.corner_spin.blockSignals(True)
        self.corner_spin.setValue(val)
        self.corner_spin.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

    def _on_corner_spin_changed(self, val: int):
        self.corner_slider.blockSignals(True)
        self.corner_slider.setValue(val)
        self.corner_slider.blockSignals(False)
        self._mark_custom_preset()
        self._schedule_calc()

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

    # -----------------------------------------------------------------
    # Live Contour Extraction Engine
    # -----------------------------------------------------------------
    def _recalculate_contours(self):
        """Runs the vector tracer in image pixel space for the interactive preview."""
        t0 = time.perf_counter()

        mode_idx = self.combo_mode.currentIndex()
        if mode_idx == 1:
            mode = "adaptive"
            threshold = None
        elif mode_idx == 2:
            mode = "edge"
            threshold = self.canny_spin.value()
        else:
            mode = "threshold"
            threshold = self.thresh_spin.value()

        invert = self.chk_invert.isChecked()
        blur = self.blur_spin.value()
        adaptive_bs = self.adaptive_bs_spin.value()
        adaptive_c = self.adaptive_c_spin.value()

        # 1. Compute binary mask
        try:
            binary_mask = ImageTracer.get_binary_mask(
                self.pil_image,
                threshold=threshold,
                mode=mode,
                invert=invert,
                blur_radius=blur,
                adaptive_block_size=adaptive_bs,
                adaptive_c=adaptive_c
            )
        except Exception as e:
            self.lbl_stats.setText(f"Error computing mask: {e}")
            return

        self.canvas.set_binary_mask(binary_mask)

        # 2. Extract smoothed vector contours
        smooth = self.smooth_spin.value()
        corner_deg = float(self.corner_spin.value())
        smooth_iter = self.combo_smooth_iter.currentIndex()  # 0: None, 1: Light, 2: High
        noise_area = float(self.noise_spin.value())
        ignore_holes = self.chk_ignore_holes.isChecked()
        ignore_border = self.chk_ignore_border.isChecked()

        try:
            contours = ImageTracer.trace_image(
                binary_mask=binary_mask,
                smoothness=smooth,
                corner_sharpness_deg=corner_deg,
                smooth_iterations=smooth_iter,
                min_area_pixels=noise_area,
                ignore_holes=ignore_holes,
                ignore_border=ignore_border,
                scale_x=1.0,
                scale_y=1.0
            )
        except Exception as e:
            self.lbl_stats.setText(f"Error tracing contours: {e}")
            return

        t_calc = (time.perf_counter() - t0) * 1000.0

        self.pixel_contours = contours
        self.canvas.set_contours(contours)

        total_pts = sum(len(c) for c in contours)
        self.lbl_stats.setText(
            f"Vectors: {len(contours)} contours | {total_pts} vertices | {t_calc:.1f} ms"
        )

    # -----------------------------------------------------------------
    # Output & Export Actions
    # -----------------------------------------------------------------
    def _apply_and_close(self):
        """Constructs native PathEntity scaled to desired millimeter dimensions."""
        if not self.pixel_contours:
            QMessageBox.warning(self, "Trace Image", "No vector contours extracted. Try adjusting threshold or mode.")
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
            QMessageBox.warning(self, "Export SVG", "No vector contours extracted. Try adjusting threshold or mode.")
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
