"""
LaserForge Interactive Image to SVG Cutout Studio Dialog.
Provides real-time interactive preview, offset margin adjustment,
smooth contour generation, keychain loop & standee tab additions,
and direct SVG export or canvas insertion.
"""

from typing import List, Tuple, Optional, Dict, Any
import os
import math
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QFileDialog, QGroupBox, QSplitter, QFrame, QMessageBox,
    QScrollArea, QButtonGroup, QRadioButton
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QImage, QPixmap, QWheelEvent,
    QMouseEvent, QPaintEvent, QPainterPath, QFont
)

from laserforge.config import LAYER_PALETTE
from laserforge.core.models import PathEntity, ImageEntity
from laserforge.core.image_cutout import AutoCutoutGenerator, CutoutResult


class CutoutPreviewCanvas(QWidget):
    """
    Interactive zoomable & pannable canvas displaying the source image,
    the binary subject mask, and the generated laser cut contours.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap: Optional[QPixmap] = None
        self.mask_pixmap: Optional[QPixmap] = None
        self.cutout_result: Optional[CutoutResult] = None

        self.view_mode: str = "overlay"  # "overlay", "cut_only", "mask", "original"
        self.cut_color: QColor = QColor("#FF2A2A")
        self.show_fill: bool = True
        self.image_opacity: float = 0.65

        self.zoom: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0
        self._panning: bool = False
        self._last_mouse = QPointF()

        self.target_w_mm: float = 80.0
        self.target_h_mm: float = 80.0

        self.setMinimumSize(460, 440)
        self.setStyleSheet("background-color: #14141a;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_source_image(self, pil_img: Image.Image, target_w_mm: float, target_h_mm: float):
        self.target_w_mm = target_w_mm
        self.target_h_mm = target_h_mm
        img_rgb = pil_img.convert("RGBA")
        data = img_rgb.tobytes("raw", "RGBA")
        qimg = QImage(data, img_rgb.width, img_rgb.height, QImage.Format.Format_RGBA8888).copy()
        self.pixmap = QPixmap.fromImage(qimg)
        self.reset_view()

    def set_mask_preview(self, mask_np: Optional[np.ndarray]):
        if mask_np is None or mask_np.size == 0:
            self.mask_pixmap = None
            self.update()
            return
        h, w = mask_np.shape[:2]
        mask_contig = np.ascontiguousarray(mask_np, dtype=np.uint8)
        qimg = QImage(mask_contig.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        self.mask_pixmap = QPixmap.fromImage(qimg)
        self.update()

    def set_cutout_result(self, result: Optional[CutoutResult], cut_color: QColor):
        self.cutout_result = result
        self.cut_color = cut_color
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

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)
        mouse_pos = event.position()
        old_zoom = self.zoom
        self.zoom = max(0.1, min(50.0, self.zoom * factor))
        self.pan_x = mouse_pos.x() - (mouse_pos.x() - self.pan_x) * (self.zoom / old_zoom)
        self.pan_y = mouse_pos.y() - (mouse_pos.y() - self.pan_y) * (self.zoom / old_zoom)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = True
            self._last_mouse = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.position() - self._last_mouse
            self._last_mouse = event.position()
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Draw dark grid background
        painter.fillRect(self.rect(), QColor("#14141a"))
        grid_pen = QPen(QColor("#20202a"), 1)
        painter.setPen(grid_pen)
        grid_size = 20
        for x in range(0, self.width(), grid_size):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), grid_size):
            painter.drawLine(0, y, self.width(), y)

        if not self.pixmap or self.pixmap.isNull():
            painter.setPen(QColor("#606075"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Image Loaded")
            return

        img_w = self.pixmap.width()
        img_h = self.pixmap.height()

        # Transform to image coordinates
        painter.save()
        painter.translate(self.pan_x, self.pan_y)
        painter.scale(self.zoom, self.zoom)

        # 1. Render Base Layer according to view_mode
        if self.view_mode in ("overlay", "original"):
            painter.setOpacity(self.image_opacity if self.view_mode == "overlay" else 1.0)
            painter.drawPixmap(0, 0, self.pixmap)
            painter.setOpacity(1.0)
        elif self.view_mode == "mask":
            if self.mask_pixmap and not self.mask_pixmap.isNull():
                # Scale mask to fit image rect
                painter.drawPixmap(0, 0, img_w, img_h, self.mask_pixmap)

        # 2. Render Cut Contours (in overlay or cut_only or mask mode)
        if self.view_mode in ("overlay", "cut_only", "mask") and self.cutout_result:
            scale_px_x = img_w / max(0.1, self.target_w_mm)
            scale_px_y = img_h / max(0.1, self.target_h_mm)

            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)

            for poly in self.cutout_result.contours:
                if len(poly) < 2:
                    continue
                # Contours are in mm relative to top-left of image
                px0 = poly[0][0] * scale_px_x
                py0 = poly[0][1] * scale_px_y
                path.moveTo(px0, py0)
                for pt in poly[1:]:
                    path.lineTo(pt[0] * scale_px_x, pt[1] * scale_px_y)
                path.closeSubpath()

            # Fill translucent cut area
            if self.show_fill and self.view_mode in ("overlay", "cut_only"):
                fill_color = QColor(self.cut_color)
                fill_color.setAlpha(35)
                painter.fillPath(path, QBrush(fill_color))

            # Cut vector line
            pen = QPen(self.cut_color, max(1.2 / self.zoom, 1.5))
            painter.setPen(pen)
            painter.drawPath(path)

            # Draw hanging loop center if present
            if self.cutout_result.hanging_hole_center_mm:
                hx_px = self.cutout_result.hanging_hole_center_mm[0] * scale_px_x
                hy_px = self.cutout_result.hanging_hole_center_mm[1] * scale_px_y
                painter.setPen(QPen(QColor("#00E5FF"), 1.0 / self.zoom))
                r = 4.0 / self.zoom
                painter.drawLine(QPointF(hx_px - r, hy_px), QPointF(hx_px + r, hy_px))
                painter.drawLine(QPointF(hx_px, hy_px - r), QPointF(hx_px, hy_px + r))

        painter.restore()

        # Canvas overlay HUD info
        painter.setPen(QColor("#8c8ca8"))
        font = QFont("Monospace", 9)
        painter.setFont(font)
        hud_text = f"Zoom: {int(self.zoom * 100)}% | Target: {self.target_w_mm:.1f} × {self.target_h_mm:.1f} mm"
        if self.cutout_result:
            hud_text += f" | Cutout: {self.cutout_result.width_mm:.1f} × {self.cutout_result.height_mm:.1f} mm"
        painter.drawText(12, self.height() - 12, hud_text)


class ImageCutoutDialog(QDialog):
    """
    Full-featured dialog for automatic image cutout contour generation,
    interactive margin adjustment, and SVG export.
    """

    PRESETS = {
        "Sticker / Decal (+2mm Round)": {
            "offset_mm": 2.0,
            "keep_holes": False,
            "smoothness": 1.2,
            "loop": False,
            "standee": False,
            "desc": "2mm smooth rounded outer cut border — perfect for vinyl stickers, labels, and decals."
        },
        "Tight Silhouette (0mm Exact)": {
            "offset_mm": 0.0,
            "keep_holes": True,
            "smoothness": 0.8,
            "loop": False,
            "standee": False,
            "desc": "Exact edge boundary cutout following the image artwork with internal cutout holes."
        },
        "Keychain / Charm (+3mm + Top Loop)": {
            "offset_mm": 3.0,
            "keep_holes": False,
            "smoothness": 1.4,
            "loop": True,
            "loop_dia": 3.5,
            "loop_collar": 2.5,
            "standee": False,
            "desc": "Solid 3mm acrylic/wood border with a 3.5mm top hanging hole for jump rings & keychains."
        },
        "Holiday Ornament (+4mm + Ribbon Loop)": {
            "offset_mm": 4.0,
            "keep_holes": False,
            "smoothness": 1.6,
            "loop": True,
            "loop_dia": 5.0,
            "loop_collar": 3.0,
            "standee": False,
            "desc": "Generous 4mm border with a 5mm hanging loop for festive ribbon and ornaments."
        },
        "Desk Standee / Figurine (+2mm + Tab)": {
            "offset_mm": 2.5,
            "keep_holes": False,
            "smoothness": 1.2,
            "loop": False,
            "standee": True,
            "tab_w": 15.0,
            "tab_h": 3.5,
            "desc": "Cutout contour with a bottom mounting tab to slot into an acrylic or wooden baseplate."
        }
    }

    def __init__(
        self,
        pil_image: Image.Image,
        image_name: str = "Image",
        initial_width_mm: float = 80.0,
        initial_height_mm: float = 80.0,
        active_cut_layer_id: int = 2,  # Layer 2 (C02 Red) standard cut layer
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Auto Image Cutout to SVG — {image_name}")
        self.resize(1060, 680)

        self.pil_image = pil_image
        self.image_name = image_name
        self.width_mm = initial_width_mm
        self.height_mm = initial_height_mm
        self.cut_layer_id = active_cut_layer_id

        # Output results
        self.result_cutout: Optional[CutoutResult] = None
        self.output_mode: str = "combo"  # "combo" (Engrave image + Cut path) or "cutout_only"

        # Debounce timer for real-time recalculation
        self._calc_timer = QTimer(self)
        self._calc_timer.setSingleShot(True)
        self._calc_timer.setInterval(120)
        self._calc_timer.timeout.connect(self._recalculate)

        self._init_ui()
        self.preview_canvas.set_source_image(self.pil_image, self.width_mm, self.height_mm)
        self._apply_preset("Sticker / Decal (+2mm Round)")

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # ---------------- Left Controls Panel ----------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(380)
        scroll.setMaximumWidth(420)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        ctrl_container = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_container)
        ctrl_layout.setSpacing(10)
        ctrl_layout.setContentsMargins(0, 0, 8, 0)

        # 1. Presets Group
        preset_group = QGroupBox("⚡ Quick Cutout Presets")
        preset_layout = QVBoxLayout(preset_group)
        self.combo_presets = QComboBox()
        for name in self.PRESETS.keys():
            self.combo_presets.addItem(name)
        self.combo_presets.currentTextChanged.connect(self._apply_preset)
        preset_layout.addWidget(self.combo_presets)

        self.lbl_preset_desc = QLabel()
        self.lbl_preset_desc.setWordWrap(True)
        self.lbl_preset_desc.setStyleSheet("color: #a0a0b8; font-size: 11px; font-style: italic;")
        preset_layout.addWidget(self.lbl_preset_desc)
        ctrl_layout.addWidget(preset_group)

        # 2. Subject Detection & Background
        bg_group = QGroupBox("🔍 Background & Subject Extraction")
        bg_layout = QGridLayout(bg_group)
        bg_layout.setSpacing(6)

        bg_layout.addWidget(QLabel("Detection Mode:"), 0, 0)
        self.combo_bg_mode = QComboBox()
        self.combo_bg_mode.addItems([
            "Auto (Alpha / Corners)",
            "Transparent Alpha Only",
            "Light / White Background",
            "Dark / Black Background",
            "High-Contrast (Otsu)"
        ])
        self.combo_bg_mode.currentIndexChanged.connect(self._on_param_changed)
        bg_layout.addWidget(self.combo_bg_mode, 0, 1)

        bg_layout.addWidget(QLabel("Color Tolerance:"), 1, 0)
        tol_box = QHBoxLayout()
        self.slider_tol = QSlider(Qt.Orientation.Horizontal)
        self.slider_tol.setRange(1, 100)
        self.slider_tol.setValue(25)
        self.spin_tol = QSpinBox()
        self.spin_tol.setRange(1, 100)
        self.spin_tol.setValue(25)
        self.slider_tol.valueChanged.connect(self.spin_tol.setValue)
        self.spin_tol.valueChanged.connect(self.slider_tol.setValue)
        self.slider_tol.valueChanged.connect(self._on_param_changed)
        tol_box.addWidget(self.slider_tol)
        tol_box.addWidget(self.spin_tol)
        bg_layout.addLayout(tol_box, 1, 1)

        self.chk_invert = QCheckBox("Invert Subject / Background")
        self.chk_invert.toggled.connect(self._on_param_changed)
        bg_layout.addWidget(self.chk_invert, 2, 0, 1, 2)

        ctrl_layout.addWidget(bg_group)

        # 3. Cutout Margin & Smoothing
        cut_group = QGroupBox("✂️ Cutout Contour & Margin")
        cut_layout = QGridLayout(cut_group)
        cut_layout.setSpacing(6)

        cut_layout.addWidget(QLabel("Offset Margin (mm):"), 0, 0)
        offset_box = QHBoxLayout()
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-10.0, 30.0)
        self.spin_offset.setSingleStep(0.5)
        self.spin_offset.setDecimals(1)
        self.spin_offset.setSuffix(" mm")
        self.spin_offset.setValue(2.0)
        self.spin_offset.valueChanged.connect(self._on_offset_spin_changed)

        self.slider_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_offset.setRange(-20, 60)  # half mm units
        self.slider_offset.setValue(4)  # 2.0 mm
        self.slider_offset.valueChanged.connect(self._on_offset_slider_changed)

        offset_box.addWidget(self.slider_offset)
        offset_box.addWidget(self.spin_offset)
        cut_layout.addLayout(offset_box, 0, 1)

        cut_layout.addWidget(QLabel("Curve Smoothness:"), 1, 0)
        self.slider_smooth = QSlider(Qt.Orientation.Horizontal)
        self.slider_smooth.setRange(2, 30)
        self.slider_smooth.setValue(12)
        self.slider_smooth.valueChanged.connect(self._on_param_changed)
        cut_layout.addWidget(self.slider_smooth, 1, 1)

        self.chk_holes = QCheckBox("Keep Interior Cutout Holes")
        self.chk_holes.setToolTip("When unchecked, creates a solid silhouette backing plate")
        self.chk_holes.toggled.connect(self._on_param_changed)
        cut_layout.addWidget(self.chk_holes, 2, 0, 1, 2)

        ctrl_layout.addWidget(cut_group)

        # 4. Keychain Loop & Standee Tabs
        feat_group = QGroupBox("🔗 Keychain Loop & Standee Slot Tab")
        feat_layout = QGridLayout(feat_group)
        feat_layout.setSpacing(6)

        # Hanging Loop
        self.chk_loop = QCheckBox("Add Keychain / Hanging Loop")
        self.chk_loop.toggled.connect(self._toggle_loop_controls)
        feat_layout.addWidget(self.chk_loop, 0, 0, 1, 2)

        feat_layout.addWidget(QLabel("Hole Diameter:"), 1, 0)
        self.spin_loop_dia = QDoubleSpinBox()
        self.spin_loop_dia.setRange(1.5, 12.0)
        self.spin_loop_dia.setValue(3.5)
        self.spin_loop_dia.setSuffix(" mm")
        self.spin_loop_dia.valueChanged.connect(self._on_param_changed)
        feat_layout.addWidget(self.spin_loop_dia, 1, 1)

        feat_layout.addWidget(QLabel("Loop Position:"), 2, 0)
        self.combo_loop_pos = QComboBox()
        self.combo_loop_pos.addItems(["Top", "Top-Left", "Top-Right"])
        self.combo_loop_pos.currentIndexChanged.connect(self._on_param_changed)
        feat_layout.addWidget(self.combo_loop_pos, 2, 1)

        # Standee Tab
        self.chk_standee = QCheckBox("Add Standee Base Tab (Slot Tenon)")
        self.chk_standee.toggled.connect(self._toggle_standee_controls)
        feat_layout.addWidget(self.chk_standee, 3, 0, 1, 2)

        feat_layout.addWidget(QLabel("Tab Width:"), 4, 0)
        self.spin_tab_w = QDoubleSpinBox()
        self.spin_tab_w.setRange(4.0, 50.0)
        self.spin_tab_w.setValue(15.0)
        self.spin_tab_w.setSuffix(" mm")
        self.spin_tab_w.valueChanged.connect(self._on_param_changed)
        feat_layout.addWidget(self.spin_tab_w, 4, 1)

        feat_layout.addWidget(QLabel("Tab Height:"), 5, 0)
        self.spin_tab_h = QDoubleSpinBox()
        self.spin_tab_h.setRange(2.0, 15.0)
        self.spin_tab_h.setValue(3.5)
        self.spin_tab_h.setSuffix(" mm")
        self.spin_tab_h.valueChanged.connect(self._on_param_changed)
        feat_layout.addWidget(self.spin_tab_h, 5, 1)

        ctrl_layout.addWidget(feat_group)

        # 5. Laser Layer & Workflow Output
        out_group = QGroupBox("🎯 Laser Placement & Layer")
        out_layout = QVBoxLayout(out_group)
        out_layout.setSpacing(6)

        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Cut Line Layer:"))
        self.combo_layer = QComboBox()
        for lyr in LAYER_PALETTE:
            if not lyr.get("is_tool"):
                self.combo_layer.addItem(f"{lyr['name']} - {lyr['label']} ({lyr['color']})", lyr["id"])
        # Default to C02 Red
        idx = self.combo_layer.findData(self.cut_layer_id)
        if idx >= 0:
            self.combo_layer.setCurrentIndex(idx)
        self.combo_layer.currentIndexChanged.connect(self._on_layer_changed)
        layer_row.addWidget(self.combo_layer)
        out_layout.addLayout(layer_row)

        self.radio_combo = QRadioButton("Image + Cutout Combo (Engrave & Cut)")
        self.radio_combo.setChecked(True)
        self.radio_combo.setToolTip("Places original image on Engrave layer and cut contour on Cut layer")
        out_layout.addWidget(self.radio_combo)

        self.radio_cut_only = QRadioButton("Cutout Vector Contour Only")
        self.radio_cut_only.setToolTip("Inserts only the vector cut line without keeping the image")
        out_layout.addWidget(self.radio_cut_only)

        ctrl_layout.addWidget(out_group)
        ctrl_layout.addStretch(1)

        scroll.setWidget(ctrl_container)
        splitter.addWidget(scroll)

        # ---------------- Right Preview & Actions Panel ----------------
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # View Mode Toolbar
        view_bar = QHBoxLayout()
        view_bar.setSpacing(6)

        self.btn_view_overlay = QPushButton("🖼️ Overlay")
        self.btn_view_cut = QPushButton("✂️ Cutout Only")
        self.btn_view_mask = QPushButton("⬛ B&W Mask")
        self.btn_view_orig = QPushButton("📷 Image")

        for btn in (self.btn_view_overlay, self.btn_view_cut, self.btn_view_mask, self.btn_view_orig):
            btn.setCheckable(True)

        self.btn_view_overlay.setChecked(True)
        self.view_grp = QButtonGroup(self)
        self.view_grp.addButton(self.btn_view_overlay)
        self.view_grp.addButton(self.btn_view_cut)
        self.view_grp.addButton(self.btn_view_mask)
        self.view_grp.addButton(self.btn_view_orig)

        self.btn_view_overlay.clicked.connect(lambda: self._set_view_mode("overlay"))
        self.btn_view_cut.clicked.connect(lambda: self._set_view_mode("cut_only"))
        self.btn_view_mask.clicked.connect(lambda: self._set_view_mode("mask"))
        self.btn_view_orig.clicked.connect(lambda: self._set_view_mode("original"))

        view_bar.addWidget(self.btn_view_overlay)
        view_bar.addWidget(self.btn_view_cut)
        view_bar.addWidget(self.btn_view_mask)
        view_bar.addWidget(self.btn_view_orig)
        view_bar.addStretch(1)

        btn_fit = QPushButton("🔍 Fit")
        btn_fit.clicked.connect(lambda: self.preview_canvas.reset_view())
        view_bar.addWidget(btn_fit)

        right_layout.addLayout(view_bar)

        # Interactive Canvas
        self.preview_canvas = CutoutPreviewCanvas(self)
        right_layout.addWidget(self.preview_canvas, 1)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_export_svg = QPushButton("💾 Export Standalone SVG...")
        self.btn_export_svg.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 8px 14px;")
        self.btn_export_svg.clicked.connect(self._export_svg_dialog)
        btn_row.addWidget(self.btn_export_svg)

        btn_row.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_insert = QPushButton("⚡ Insert to Laser Canvas")
        self.btn_insert.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold; padding: 8px 18px;")
        self.btn_insert.clicked.connect(self._on_insert)
        btn_row.addWidget(self.btn_insert)

        right_layout.addLayout(btn_row)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(1, 1)

    def _set_view_mode(self, mode: str):
        self.preview_canvas.view_mode = mode
        self.preview_canvas.update()

    def _on_offset_spin_changed(self, val: float):
        self.slider_offset.blockSignals(True)
        self.slider_offset.setValue(int(round(val * 2.0)))
        self.slider_offset.blockSignals(False)
        self._on_param_changed()

    def _on_offset_slider_changed(self, val: int):
        self.spin_offset.blockSignals(True)
        self.spin_offset.setValue(val / 2.0)
        self.spin_offset.blockSignals(False)
        self._on_param_changed()

    def _toggle_loop_controls(self, checked: bool):
        self.spin_loop_dia.setEnabled(checked)
        self.combo_loop_pos.setEnabled(checked)
        self._on_param_changed()

    def _toggle_standee_controls(self, checked: bool):
        self.spin_tab_w.setEnabled(checked)
        self.spin_tab_h.setEnabled(checked)
        self._on_param_changed()

    def _on_layer_changed(self):
        lyr_id = self.combo_layer.currentData()
        self.cut_layer_id = lyr_id
        for lyr in LAYER_PALETTE:
            if lyr["id"] == lyr_id:
                self.preview_canvas.cut_color = QColor(lyr["color"])
                self.preview_canvas.update()
                break

    def _apply_preset(self, preset_name: str):
        if preset_name not in self.PRESETS:
            return
        p = self.PRESETS[preset_name]
        self.lbl_preset_desc.setText(p.get("desc", ""))

        self.spin_offset.setValue(p.get("offset_mm", 2.0))
        self.chk_holes.setChecked(p.get("keep_holes", False))
        self.slider_smooth.setValue(int(p.get("smoothness", 1.0) * 10))

        has_loop = p.get("loop", False)
        self.chk_loop.setChecked(has_loop)
        if has_loop:
            self.spin_loop_dia.setValue(p.get("loop_dia", 3.5))

        has_standee = p.get("standee", False)
        self.chk_standee.setChecked(has_standee)
        if has_standee:
            self.spin_tab_w.setValue(p.get("tab_w", 15.0))
            self.spin_tab_h.setValue(p.get("tab_h", 3.5))

        self._recalculate()

    def _on_param_changed(self):
        self._calc_timer.start()

    def _recalculate(self):
        mode_str_map = {
            0: "auto",
            1: "alpha",
            2: "light_bg",
            3: "dark_bg",
            4: "otsu"
        }
        bg_mode = mode_str_map.get(self.combo_bg_mode.currentIndex(), "auto")
        pos_map = {0: "top", 1: "top-left", 2: "top-right"}
        loop_pos = pos_map.get(self.combo_loop_pos.currentIndex(), "top")

        result = AutoCutoutGenerator.generate_cutout(
            self.pil_image,
            target_width_mm=self.width_mm,
            target_height_mm=self.height_mm,
            offset_mm=self.spin_offset.value(),
            bg_mode=bg_mode,
            color_tolerance=self.spin_tol.value(),
            keep_interior_holes=self.chk_holes.isChecked(),
            smoothness=self.slider_smooth.value() / 10.0,
            add_hanging_loop=self.chk_loop.isChecked(),
            hanging_loop_dia_mm=self.spin_loop_dia.value(),
            hanging_loop_pos=loop_pos,
            add_standee_tab=self.chk_standee.isChecked(),
            standee_tab_w_mm=self.spin_tab_w.value(),
            standee_tab_h_mm=self.spin_tab_h.value(),
            invert_mask=self.chk_invert.isChecked()
        )

        self.result_cutout = result
        self.preview_canvas.set_mask_preview(result.mask_preview)
        self.preview_canvas.set_cutout_result(result, self.preview_canvas.cut_color)

    def _export_svg_dialog(self):
        if not self.result_cutout:
            QMessageBox.warning(self, "No Cutout", "No cutout contours available to export.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Cutout SVG File", f"{self.image_name}_cutout.svg",
            "Scalable Vector Graphics (*.svg);;All Files (*)"
        )
        if not out_path:
            return

        embed_img = QMessageBox.question(
            self, "Embed Artwork?",
            "Do you want to embed the original raster artwork inside the SVG for Print & Cut?\n\n"
            "Yes: Generates layered SVG with image on Engrave layer + cut path on Cut layer.\n"
            "No: Exports vector cut line path only.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        ) == QMessageBox.StandardButton.Yes

        try:
            AutoCutoutGenerator.export_svg_file(
                self.result_cutout,
                out_path,
                source_img=self.pil_image,
                embed_image=embed_img,
                target_width_mm=self.width_mm,
                target_height_mm=self.height_mm,
                stroke_color=self.preview_canvas.cut_color.name()
            )
            QMessageBox.information(self, "Export Complete", f"SVG cutout saved successfully to:\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to save SVG: {e}")

    def _on_insert(self):
        if not self.result_cutout or not self.result_cutout.contours:
            QMessageBox.warning(self, "No Cutout", "No cutout contours generated. Check background settings.")
            return

        self.output_mode = "combo" if self.radio_combo.isChecked() else "cutout_only"
        self.accept()
