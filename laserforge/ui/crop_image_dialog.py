"""
LaserForge Interactive Image Crop Dialog.
Provides visual, interactive rectangular image cropping with aspect ratio presets
(Freeform, 1:1 Square, 4:3, 3:2, 16:9, Business Card 85.6x54mm), drag-and-drop handles,
and live dimension readout for laser engraving preparation.
"""

from typing import Optional, Tuple
import math
from PIL import Image
import numpy as np

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QImage, QPixmap, QCursor, QFont
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QGroupBox, QFrame, QMessageBox, QWidget
)


class InteractiveCropWidget(QWidget):
    """
    Widget displaying an image with an interactive, resizable, draggable
    crop selection box with corner and edge handles.
    """
    crop_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self._pil_img: Optional[Image.Image] = None
        self._pixmap: Optional[QPixmap] = None
        self._img_rect = QRect()  # Display rect of image within widget

        # Crop rect in normalized image coordinates [0.0, 1.0]
        self._norm_crop = QRectF(0.1, 0.1, 0.8, 0.8)

        # Aspect ratio lock: None for freeform, float (w/h) for fixed
        self.aspect_ratio: Optional[float] = None

        # Drag state
        self._active_handle: Optional[str] = None
        self._drag_start_pos: QPoint = QPoint()
        self._drag_start_crop: QRectF = QRectF()

        self.setStyleSheet("background-color: #1a1a24;")

    def set_image(self, pil_img: Image.Image):
        self._pil_img = pil_img
        # Convert to QPixmap
        rgba = pil_img.convert("RGBA")
        qimg = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(qimg)
        # Default crop to 90% centered
        self._norm_crop = QRectF(0.05, 0.05, 0.9, 0.9)
        self._apply_aspect_ratio_to_crop()
        self.update()
        self.crop_changed.emit()

    def set_aspect_ratio(self, ratio: Optional[float]):
        self.aspect_ratio = ratio
        self._apply_aspect_ratio_to_crop()
        self.update()
        self.crop_changed.emit()

    def reset_crop(self):
        self._norm_crop = QRectF(0.0, 0.0, 1.0, 1.0)
        self._apply_aspect_ratio_to_crop()
        self.update()
        self.crop_changed.emit()

    def get_pixel_crop_box(self) -> Tuple[int, int, int, int]:
        """Returns (left, top, right, bottom) pixel coordinates on original PIL image."""
        if not self._pil_img:
            return (0, 0, 0, 0)
        w, h = self._pil_img.size
        l = max(0, min(w - 1, int(round(self._norm_crop.left() * w))))
        t = max(0, min(h - 1, int(round(self._norm_crop.top() * h))))
        r = max(l + 1, min(w, int(round(self._norm_crop.right() * w))))
        b = max(t + 1, min(h, int(round(self._norm_crop.bottom() * h))))
        return (l, t, r, b)

    def _apply_aspect_ratio_to_crop(self):
        if self.aspect_ratio is None or not self._pil_img:
            return
        img_w, img_h = self._pil_img.size
        if img_w <= 0 or img_h <= 0:
            return

        img_aspect = img_w / float(img_h)
        target_norm_aspect = self.aspect_ratio / img_aspect

        cx = self._norm_crop.center().x()
        cy = self._norm_crop.center().y()
        cur_w = self._norm_crop.width()
        cur_h = self._norm_crop.height()

        new_w = cur_w
        new_h = new_w / target_norm_aspect
        if new_h > 0.98 or cy - new_h / 2 < 0 or cy + new_h / 2 > 1.0:
            new_h = min(0.95, cur_h)
            new_w = new_h * target_norm_aspect

        new_w = min(0.98, max(0.05, new_w))
        new_h = min(0.98, max(0.05, new_h))

        l = max(0.0, min(1.0 - new_w, cx - new_w / 2.0))
        t = max(0.0, min(1.0 - new_h, cy - new_h / 2.0))
        self._norm_crop = QRectF(l, t, new_w, new_h)

    def _calc_display_geometry(self):
        if not self._pixmap or self._pixmap.isNull():
            return
        avail_w = self.width() - 20
        avail_h = self.height() - 20
        pm_w = self._pixmap.width()
        pm_h = self._pixmap.height()

        scale = min(avail_w / max(1, pm_w), avail_h / max(1, pm_h))
        disp_w = int(pm_w * scale)
        disp_h = int(pm_h * scale)
        disp_x = (self.width() - disp_w) // 2
        disp_y = (self.height() - disp_h) // 2
        self._img_rect = QRect(disp_x, disp_y, disp_w, disp_h)

    def _crop_to_screen_rect(self) -> QRect:
        x = self._img_rect.x() + int(self._norm_crop.left() * self._img_rect.width())
        y = self._img_rect.y() + int(self._norm_crop.top() * self._img_rect.height())
        w = max(10, int(self._norm_crop.width() * self._img_rect.width()))
        h = max(10, int(self._norm_crop.height() * self._img_rect.height()))
        return QRect(x, y, w, h)

    def _screen_to_norm_crop(self, screen_rect: QRect) -> QRectF:
        if self._img_rect.width() <= 0 or self._img_rect.height() <= 0:
            return QRectF(0, 0, 1, 1)
        l = (screen_rect.left() - self._img_rect.x()) / float(self._img_rect.width())
        t = (screen_rect.top() - self._img_rect.y()) / float(self._img_rect.height())
        w = screen_rect.width() / float(self._img_rect.width())
        h = screen_rect.height() / float(self._img_rect.height())

        l = max(0.0, min(1.0, l))
        t = max(0.0, min(1.0, t))
        w = max(0.02, min(1.0 - l, w))
        h = max(0.02, min(1.0 - t, h))
        return QRectF(l, t, w, h)

    def _get_handles(self, rect: QRect) -> dict:
        r = rect
        return {
            "TL": QPoint(r.left(), r.top()),
            "TR": QPoint(r.right(), r.top()),
            "BL": QPoint(r.left(), r.bottom()),
            "BR": QPoint(r.right(), r.bottom()),
            "T": QPoint(r.center().x(), r.top()),
            "B": QPoint(r.center().x(), r.bottom()),
            "L": QPoint(r.left(), r.center().y()),
            "R": QPoint(r.right(), r.center().y()),
        }

    def _handle_at(self, pt: QPoint) -> Optional[str]:
        sc_rect = self._crop_to_screen_rect()
        handles = self._get_handles(sc_rect)
        for name, h_pt in handles.items():
            if math.hypot(pt.x() - h_pt.x(), pt.y() - h_pt.y()) <= 8:
                return name
        if sc_rect.contains(pt):
            return "MOVE"
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor("#16161c"))

        self._calc_display_geometry()
        if not self._pixmap or self._img_rect.isEmpty():
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded")
            return

        # Draw scaled image
        painter.drawPixmap(self._img_rect, self._pixmap)

        # Crop rect on screen
        cr = self._crop_to_screen_rect()

        # Darkened overlay around crop
        dim_color = QColor(0, 0, 0, 160)
        # Top
        painter.fillRect(self._img_rect.left(), self._img_rect.top(), self._img_rect.width(), max(0, cr.top() - self._img_rect.top()), dim_color)
        # Bottom
        painter.fillRect(self._img_rect.left(), cr.bottom(), self._img_rect.width(), max(0, self._img_rect.bottom() - cr.bottom()), dim_color)
        # Left
        painter.fillRect(self._img_rect.left(), cr.top(), max(0, cr.left() - self._img_rect.left()), cr.height(), dim_color)
        # Right
        painter.fillRect(cr.right(), cr.top(), max(0, self._img_rect.right() - cr.right()), cr.height(), dim_color)

        # Rule of thirds grid lines inside crop
        grid_pen = QPen(QColor(255, 255, 255, 60), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        painter.drawLine(cr.left() + cr.width() // 3, cr.top(), cr.left() + cr.width() // 3, cr.bottom())
        painter.drawLine(cr.left() + 2 * cr.width() // 3, cr.top(), cr.left() + 2 * cr.width() // 3, cr.bottom())
        painter.drawLine(cr.left(), cr.top() + cr.height() // 3, cr.right(), cr.top() + cr.height() // 3)
        painter.drawLine(cr.left(), cr.top() + 2 * cr.height() // 3, cr.right(), cr.top() + 2 * cr.height() // 3)

        # Crop boundary
        crop_pen = QPen(QColor("#00e5ff"), 2)
        painter.setPen(crop_pen)
        painter.drawRect(cr)

        # Draw handles
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(QPen(QColor("#00838f"), 1.5))
        handles = self._get_handles(cr)
        for h_pt in handles.values():
            painter.drawRect(h_pt.x() - 4, h_pt.y() - 4, 8, 8)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pt = event.pos()
            handle = self._handle_at(pt)
            if handle:
                self._active_handle = handle
                self._drag_start_pos = pt
                self._drag_start_crop = QRectF(self._norm_crop)
            else:
                # Clicked outside crop: start fresh crop selection
                if self._img_rect.contains(pt):
                    norm_x = (pt.x() - self._img_rect.x()) / float(self._img_rect.width())
                    norm_y = (pt.y() - self._img_rect.y()) / float(self._img_rect.height())
                    self._norm_crop = QRectF(norm_x, norm_y, 0.05, 0.05)
                    self._active_handle = "BR"
                    self._drag_start_pos = pt
                    self._drag_start_crop = QRectF(self._norm_crop)
                    self.update()

    def mouseMoveEvent(self, event):
        pt = event.pos()
        if self._active_handle:
            dx_px = pt.x() - self._drag_start_pos.x()
            dy_px = pt.y() - self._drag_start_pos.y()
            if self._img_rect.width() > 0 and self._img_rect.height() > 0:
                dx = dx_px / float(self._img_rect.width())
                dy = dy_px / float(self._img_rect.height())

                c = QRectF(self._drag_start_crop)
                h = self._active_handle

                if h == "MOVE":
                    c.translate(dx, dy)
                    # Clamp to bounds
                    if c.left() < 0: c.moveLeft(0)
                    if c.top() < 0: c.moveTop(0)
                    if c.right() > 1: c.moveRight(1)
                    if c.bottom() > 1: c.moveBottom(1)
                else:
                    if "L" in h:
                        new_l = min(c.right() - 0.05, max(0.0, c.left() + dx))
                        c.setLeft(new_l)
                    if "R" in h:
                        new_r = max(c.left() + 0.05, min(1.0, c.right() + dx))
                        c.setRight(new_r)
                    if "T" in h:
                        new_t = min(c.bottom() - 0.05, max(0.0, c.top() + dy))
                        c.setTop(new_t)
                    if "B" in h:
                        new_b = max(c.top() + 0.05, min(1.0, c.bottom() + dy))
                        c.setBottom(new_b)

                self._norm_crop = c
                if self.aspect_ratio is not None and h != "MOVE":
                    self._apply_aspect_ratio_to_crop()
                self.update()
                self.crop_changed.emit()
        else:
            # Update cursor shape based on hover
            h = self._handle_at(pt)
            if h in ("TL", "BR"):
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            elif h in ("TR", "BL"):
                self.setCursor(QCursor(Qt.CursorShape.SizeBDiagCursor))
            elif h in ("T", "B"):
                self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
            elif h in ("L", "R"):
                self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
            elif h == "MOVE":
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def mouseReleaseEvent(self, event):
        self._active_handle = None


class CropImageDialog(QDialog):
    """
    Dialog for interactive photograph cropping.
    Emits cropped PIL Image upon acceptance.
    """
    def __init__(self, pil_image: Image.Image, parent=None, title="Crop Photograph for Laser Engraving"):
        super().__init__(parent)
        self.setWindowTitle(f"✂️ {title}")
        self.resize(750, 580)
        self.setMinimumSize(600, 450)

        self.original_image = pil_image
        self.cropped_image: Optional[Image.Image] = None

        self._init_ui()
        self.crop_widget.set_image(pil_image)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Toolbar: Aspect Ratio & Controls
        tb = QHBoxLayout()
        tb.setSpacing(8)

        tb.addWidget(QLabel("Aspect Ratio:"))
        self.combo_aspect = QComboBox()
        self.combo_aspect.addItem("Freeform (Unlocked)", None)
        self.combo_aspect.addItem("1:1 Square (Coasters / Medallions)", 1.0)
        self.combo_aspect.addItem("4:3 Standard Photo", 4.0 / 3.0)
        self.combo_aspect.addItem("3:2 Classic 35mm", 3.0 / 2.0)
        self.combo_aspect.addItem("16:9 Widescreen", 16.0 / 9.0)
        self.combo_aspect.addItem("Business Card (85.6 × 54 mm)", 85.6 / 54.0)
        self.combo_aspect.addItem("US Business Card (3.5 × 2 in)", 3.5 / 2.0)
        self.combo_aspect.currentIndexChanged.connect(self._on_aspect_changed)
        tb.addWidget(self.combo_aspect)

        btn_reset = QPushButton("🔄 Full Image")
        btn_reset.setToolTip("Reset crop boundary to include the full photograph")
        btn_reset.clicked.connect(self._on_reset_crop)
        tb.addWidget(btn_reset)

        tb.addStretch(1)

        self.lbl_dims = QLabel("Crop: 0 × 0 px")
        self.lbl_dims.setStyleSheet("font-weight: bold; color: #00e5ff; font-family: monospace;")
        tb.addWidget(self.lbl_dims)

        main_layout.addLayout(tb)

        # Interactive Canvas Widget
        self.crop_widget = InteractiveCropWidget(self)
        self.crop_widget.crop_changed.connect(self._update_dim_label)
        main_layout.addWidget(self.crop_widget, 1)

        # Bottom Actions
        bottom_row = QHBoxLayout()
        hint = QLabel("💡 Tip: Drag handles or click & drag inside the box to move the crop area.")
        hint.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        bottom_row.addWidget(hint)

        bottom_row.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(btn_cancel)

        btn_confirm = QPushButton("✂️ Apply Crop")
        btn_confirm.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 16px;")
        btn_confirm.clicked.connect(self._on_apply_crop)
        bottom_row.addWidget(btn_confirm)

        main_layout.addLayout(bottom_row)

    def _on_aspect_changed(self):
        ratio = self.combo_aspect.currentData()
        self.crop_widget.set_aspect_ratio(ratio)

    def _on_reset_crop(self):
        self.crop_widget.reset_crop()

    def _update_dim_label(self):
        l, t, r, b = self.crop_widget.get_pixel_crop_box()
        cw = max(1, r - l)
        ch = max(1, b - t)
        aspect = cw / float(ch)
        self.lbl_dims.setText(f"Crop: {cw} × {ch} px ({aspect:.2f}:1)")

    def _on_apply_crop(self):
        box = self.crop_widget.get_pixel_crop_box()
        l, t, r, b = box
        if (r - l) < 5 or (b - t) < 5:
            QMessageBox.warning(self, "Crop Too Small", "The crop area is too small. Please select a larger region.")
            return

        self.cropped_image = self.original_image.crop((l, t, r, b))
        self.accept()
