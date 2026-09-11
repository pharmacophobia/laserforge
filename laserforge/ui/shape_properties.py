"""
LaserForge Shape Properties Panel.
Displays and edits numeric coordinates (X, Y), dimensions (Width, Height),
rotation angle, aspect ratio lock, and quick alignment tools for selected CAD entities.
"""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QPushButton, QToolButton, QGroupBox,
    QCheckBox, QComboBox, QFontComboBox, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
)
from laserforge.ui.canvas_scene import LaserCanvasScene, LaserItemWrapper
from laserforge.config import DEFAULT_BED_WIDTH_MM, DEFAULT_BED_HEIGHT_MM



class ShapePropertiesPanel(QWidget):
    trace_image_requested = pyqtSignal()
    photo_studio_requested = pyqtSignal()
    crop_image_requested = pyqtSignal()
    curved_text_requested = pyqtSignal()

    def __init__(self, scene: LaserCanvasScene, parent=None):

        super().__init__(parent)
        self.scene = scene
        self._is_updating_ui = False
        self.lock_aspect_ratio = True

        self._init_ui()
        self._connect_signals()
        self.update_from_selection()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 1. Transform / Geometry Group
        geo_group = QGroupBox("Transform / Geometry")
        geo_layout = QGridLayout(geo_group)
        geo_layout.setContentsMargins(6, 8, 6, 6)
        geo_layout.setSpacing(4)

        # X & Y Pos
        geo_layout.addWidget(QLabel("X (mm):"), 0, 0)
        self.x_spin = QDoubleSpinBox()
        self.x_spin.setRange(-2000, 2000)
        self.x_spin.setSingleStep(1.0)
        self.x_spin.setDecimals(2)
        self.x_spin.valueChanged.connect(self._on_pos_changed)
        geo_layout.addWidget(self.x_spin, 0, 1)

        geo_layout.addWidget(QLabel("Y (mm):"), 0, 2)
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setRange(-2000, 2000)
        self.y_spin.setSingleStep(1.0)
        self.y_spin.setDecimals(2)
        self.y_spin.valueChanged.connect(self._on_pos_changed)
        geo_layout.addWidget(self.y_spin, 0, 3)

        # Width & Height
        geo_layout.addWidget(QLabel("W (mm):"), 1, 0)
        self.w_spin = QDoubleSpinBox()
        self.w_spin.setRange(0.01, 2000)
        self.w_spin.setSingleStep(1.0)
        self.w_spin.setDecimals(2)
        self.w_spin.valueChanged.connect(self._on_width_changed)
        geo_layout.addWidget(self.w_spin, 1, 1)

        geo_layout.addWidget(QLabel("H (mm):"), 1, 2)
        self.h_spin = QDoubleSpinBox()
        self.h_spin.setRange(0.01, 2000)
        self.h_spin.setSingleStep(1.0)
        self.h_spin.setDecimals(2)
        self.h_spin.valueChanged.connect(self._on_height_changed)
        geo_layout.addWidget(self.h_spin, 1, 3)

        # Rotation & Aspect Lock
        geo_layout.addWidget(QLabel("Rotate:"), 2, 0)
        self.rot_spin = QDoubleSpinBox()
        self.rot_spin.setRange(-360, 360)
        self.rot_spin.setSingleStep(5.0)
        self.rot_spin.setSuffix("°")
        self.rot_spin.valueChanged.connect(self._on_rot_changed)
        geo_layout.addWidget(self.rot_spin, 2, 1)

        self.aspect_cb = QCheckBox("Lock 🔒")
        self.aspect_cb.setChecked(True)
        self.aspect_cb.toggled.connect(self._on_aspect_toggled)
        geo_layout.addWidget(self.aspect_cb, 2, 2, 1, 2)

        layout.addWidget(geo_group)

        # 2. Text & Typography Group (Visible when TextEntity is selected)
        self.text_group = QGroupBox("Text & Typography")
        text_layout = QGridLayout(self.text_group)
        text_layout.setContentsMargins(6, 8, 6, 6)
        text_layout.setSpacing(4)

        # Text Content
        text_layout.addWidget(QLabel("Text:"), 0, 0)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Text content...")
        self.text_input.textChanged.connect(self._on_text_content_changed)
        self.text_input.editingFinished.connect(self._on_text_editing_finished)
        text_layout.addWidget(self.text_input, 0, 1, 1, 3)

        # Font Family
        text_layout.addWidget(QLabel("Font:"), 1, 0)
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(self._on_font_family_changed)
        text_layout.addWidget(self.font_combo, 1, 1, 1, 3)

        # Font Size & Formatting
        text_layout.addWidget(QLabel("Size:"), 2, 0)
        self.font_size_spin = QDoubleSpinBox()
        self.font_size_spin.setRange(1.0, 500.0)
        self.font_size_spin.setSingleStep(1.0)
        self.font_size_spin.setDecimals(1)
        self.font_size_spin.setSuffix(" mm")
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        text_layout.addWidget(self.font_size_spin, 2, 1)

        style_box = QHBoxLayout()
        style_box.setSpacing(3)
        self.btn_bold = QToolButton()
        self.btn_bold.setText("B")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setToolTip("Bold")
        self.btn_bold.setStyleSheet("font-weight: bold; font-size: 12px; min-width: 24px; min-height: 22px;")
        self.btn_bold.toggled.connect(self._on_bold_toggled)

        self.btn_italic = QToolButton()
        self.btn_italic.setText("I")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setToolTip("Italic")
        self.btn_italic.setStyleSheet("font-style: italic; font-size: 12px; font-family: serif; min-width: 24px; min-height: 22px;")
        self.btn_italic.toggled.connect(self._on_italic_toggled)

        self.btn_underline = QToolButton()
        self.btn_underline.setText("U")
        self.btn_underline.setCheckable(True)
        self.btn_underline.setToolTip("Underline")
        self.btn_underline.setStyleSheet("text-decoration: underline; font-size: 12px; min-width: 24px; min-height: 22px;")
        self.btn_underline.toggled.connect(self._on_underline_toggled)

        style_box.addWidget(self.btn_bold)
        style_box.addWidget(self.btn_italic)
        style_box.addWidget(self.btn_underline)
        text_layout.addLayout(style_box, 2, 2, 1, 2)

        # Outlined vs. Fill Mode
        text_layout.addWidget(QLabel("Mode:"), 3, 0)
        self.text_mode_combo = QComboBox()
        self.text_mode_combo.addItems(["Fill (Solid Engrave)", "Outlined (Vector Cut)"])
        self.text_mode_combo.currentIndexChanged.connect(self._on_text_mode_changed)
        text_layout.addWidget(self.text_mode_combo, 3, 1, 1, 3)

        self.text_group.setVisible(False)
        layout.addWidget(self.text_group)

        # 3. Alignment & Positioning Group
        align_group = QGroupBox("Alignment & Arrange")
        align_layout = QGridLayout(align_group)
        align_layout.setContentsMargins(6, 8, 6, 6)
        align_layout.setSpacing(4)

        btn_align_left = QPushButton("⇤ Left")
        btn_align_center_x = QPushButton("↔ Center")
        btn_align_right = QPushButton("Right ⇥")
        btn_align_top = QPushButton("⊼ Top")
        btn_align_center_y = QPushButton("↕ Middle")
        btn_align_bottom = QPushButton("Bottom ⊻")

        btn_dist_h = QPushButton("⇥ Distribute H")
        btn_dist_v = QPushButton("⇵ Distribute V")
        btn_center_parent = QPushButton("🎯 In Shape")
        btn_bed_center = QPushButton("🎯 Bed Center")

        btn_align_left.clicked.connect(lambda: self._align("left"))
        btn_align_center_x.clicked.connect(lambda: self._align("center_x"))
        btn_align_right.clicked.connect(lambda: self._align("right"))
        btn_align_top.clicked.connect(lambda: self._align("top"))
        btn_align_center_y.clicked.connect(lambda: self._align("center_y"))
        btn_align_bottom.clicked.connect(lambda: self._align("bottom"))
        btn_dist_h.clicked.connect(lambda: self._align("distribute_h"))
        btn_dist_v.clicked.connect(lambda: self._align("distribute_v"))
        btn_center_parent.clicked.connect(lambda: self._align("center_in_parent"))
        btn_bed_center.clicked.connect(self._center_on_bed)

        align_layout.addWidget(btn_align_left, 0, 0)
        align_layout.addWidget(btn_align_center_x, 0, 1)
        align_layout.addWidget(btn_align_right, 0, 2)
        align_layout.addWidget(btn_align_top, 1, 0)
        align_layout.addWidget(btn_align_center_y, 1, 1)
        align_layout.addWidget(btn_align_bottom, 1, 2)
        align_layout.addWidget(btn_dist_h, 2, 0)
        align_layout.addWidget(btn_dist_v, 2, 1)
        align_layout.addWidget(btn_center_parent, 2, 2)
        align_layout.addWidget(btn_bed_center, 3, 0, 1, 3)

        layout.addWidget(align_group)

        # 3. Image Photo Studio & Vectorization Group
        self.img_group = QGroupBox("Photo & Bitmap Studio")
        img_layout = QVBoxLayout(self.img_group)
        img_layout.setContentsMargins(6, 8, 6, 6)
        img_layout.setSpacing(6)

        self.btn_photo_studio = QPushButton("📷 Open in Photo Engrave Studio...")
        self.btn_photo_studio.setStyleSheet("background-color: #9c27b0; color: white; font-weight: bold; padding: 6px;")
        self.btn_photo_studio.clicked.connect(self.photo_studio_requested.emit)
        img_layout.addWidget(self.btn_photo_studio)

        self.btn_crop_photo = QPushButton("✂️ Crop Photo...")
        self.btn_crop_photo.setStyleSheet("background-color: #37474f; color: white; font-weight: bold; padding: 6px;")
        self.btn_crop_photo.clicked.connect(self.crop_image_requested.emit)
        img_layout.addWidget(self.btn_crop_photo)

        self.btn_trace_img = QPushButton("⚡ Trace Image to SVG...")
        self.btn_trace_img.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px;")
        self.btn_trace_img.clicked.connect(self.trace_image_requested.emit)
        img_layout.addWidget(self.btn_trace_img)

        self.img_group.setVisible(False)
        layout.addWidget(self.img_group)

        layout.addStretch(1)


    def _connect_signals(self):
        self.scene.selectionChanged.connect(self.update_from_selection)
        self.scene.entity_modified.connect(self.update_from_selection)

    def _on_aspect_toggled(self, checked: bool):
        self.lock_aspect_ratio = checked

    def update_from_selection(self):
        if self._is_updating_ui:
            return

        try:
            selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        except RuntimeError:
            return
        if not selected_items:
            self.setEnabled(False)
            self.img_group.setVisible(False)
            self.text_group.setVisible(False)
            self._is_updating_ui = True
            self.x_spin.setValue(0)
            self.y_spin.setValue(0)
            self.w_spin.setValue(0)
            self.h_spin.setValue(0)
            self.rot_spin.setValue(0)
            self._is_updating_ui = False
            return

        self.setEnabled(True)
        has_image = any(isinstance(i.entity, ImageEntity) for i in selected_items)
        self.img_group.setVisible(has_image)

        has_text = any(isinstance(i.entity, TextEntity) for i in selected_items)
        self.text_group.setVisible(has_text)

        self._is_updating_ui = True

        if has_text:
            text_items = [i for i in selected_items if isinstance(i.entity, TextEntity)]
            if text_items:
                tent = text_items[0].entity
                if not self.text_input.hasFocus() and self.text_input.text() != tent.text:
                    self.text_input.setText(tent.text)
                self.font_combo.setCurrentFont(QFont(tent.font_family))
                self.font_size_spin.setValue(tent.font_size)
                self.btn_bold.setChecked(tent.bold)
                self.btn_italic.setChecked(tent.italic)
                self.btn_underline.setChecked(getattr(tent, "underline", False))
                mode_idx = 1 if getattr(tent, "fill_mode", "Fill") == "Outline" else 0
                self.text_mode_combo.setCurrentIndex(mode_idx)


        if len(selected_items) == 1:
            item = selected_items[0]
            item.sync_to_entity()
            ent = item.entity
            self.x_spin.setValue(ent.x)
            self.y_spin.setValue(ent.y)
            self.rot_spin.setValue(ent.rotation)

            b = ent.get_bounds()
            w = max(0.1, b[2] - b[0])
            h = max(0.1, b[3] - b[1])
            self.w_spin.setValue(w)
            self.h_spin.setValue(h)
        else:
            # Multi-selection bounding box
            min_x = min(i.entity.get_bounds()[0] for i in selected_items)
            min_y = min(i.entity.get_bounds()[1] for i in selected_items)
            max_x = max(i.entity.get_bounds()[2] for i in selected_items)
            max_y = max(i.entity.get_bounds()[3] for i in selected_items)
            self.x_spin.setValue(min_x)
            self.y_spin.setValue(min_y)
            self.w_spin.setValue(max_x - min_x)
            self.h_spin.setValue(max_y - min_y)
            self.rot_spin.setValue(0)

        self._is_updating_ui = False

    def _on_pos_changed(self):
        if self._is_updating_ui:
            return
        new_x = self.x_spin.value()
        new_y = self.y_spin.value()
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            return

        if len(selected_items) == 1:
            item = selected_items[0]
            item.entity.x = new_x
            item.entity.y = new_y
            item.sync_from_entity()
        else:
            # Shift entire group
            min_x = min(i.entity.get_bounds()[0] for i in selected_items)
            min_y = min(i.entity.get_bounds()[1] for i in selected_items)
            dx = new_x - min_x
            dy = new_y - min_y
            for item in selected_items:
                item.entity.x += dx
                item.entity.y += dy
                item.sync_from_entity()

        self.scene.entity_modified.emit()

    def _on_width_changed(self):
        if self._is_updating_ui:
            return
        new_w = self.w_spin.value()
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            return

        for item in selected_items:
            ent = item.entity
            b = ent.get_bounds()
            old_w = max(0.001, b[2] - b[0])
            scale_x = new_w / old_w

            if isinstance(ent, RectEntity):
                ent.width = new_w
                if self.lock_aspect_ratio:
                    ent.height *= scale_x
            elif isinstance(ent, CircleEntity):
                ent.radius_x = new_w / 2.0
                if self.lock_aspect_ratio:
                    ent.radius_y = ent.radius_x
            elif isinstance(ent, TextEntity):
                ent.width = new_w
                if self.lock_aspect_ratio:
                    ent.height *= scale_x
                    ent.font_size = max(2.0, ent.font_size * scale_x)
            elif isinstance(ent, ImageEntity):
                ent.width = new_w
                if self.lock_aspect_ratio:
                    ent.height *= scale_x
            elif isinstance(ent, PathEntity):
                scale_y = scale_x if self.lock_aspect_ratio else 1.0
                for contour in ent.contours:
                    for idx, pt in enumerate(contour):
                        contour[idx] = (pt[0] * scale_x, pt[1] * scale_y)
                ent.invalidate_bounds()

            item.sync_from_entity()

        self.scene.entity_modified.emit()
        self.update_from_selection()

    def _on_height_changed(self):
        if self._is_updating_ui:
            return
        new_h = self.h_spin.value()
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            return

        for item in selected_items:
            ent = item.entity
            b = ent.get_bounds()
            old_h = max(0.001, b[3] - b[1])
            scale_y = new_h / old_h

            if isinstance(ent, RectEntity):
                ent.height = new_h
                if self.lock_aspect_ratio:
                    ent.width *= scale_y
            elif isinstance(ent, CircleEntity):
                ent.radius_y = new_h / 2.0
                if self.lock_aspect_ratio:
                    ent.radius_x = ent.radius_y
            elif isinstance(ent, TextEntity):
                ent.height = new_h
                if self.lock_aspect_ratio:
                    ent.width *= scale_y
                    ent.font_size = max(2.0, ent.font_size * scale_y)
            elif isinstance(ent, ImageEntity):
                ent.height = new_h
                if self.lock_aspect_ratio:
                    ent.width *= scale_y
            elif isinstance(ent, PathEntity):
                scale_x = scale_y if self.lock_aspect_ratio else 1.0
                for contour in ent.contours:
                    for idx, pt in enumerate(contour):
                        contour[idx] = (pt[0] * scale_x, pt[1] * scale_y)
                ent.invalidate_bounds()

            item.sync_from_entity()

        self.scene.entity_modified.emit()
        self.update_from_selection()

    def _on_rot_changed(self):
        if self._is_updating_ui:
            return
        angle = self.rot_spin.value()
        for item in self.scene.selectedItems():
            if isinstance(item, LaserItemWrapper):
                item.entity.rotation = angle
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _align(self, mode: str):
        self.scene.align_selected(mode, DEFAULT_BED_WIDTH_MM, DEFAULT_BED_HEIGHT_MM)
        self.update_from_selection()

    def _center_on_bed(self):
        self.scene.align_selected("bed_center", DEFAULT_BED_WIDTH_MM, DEFAULT_BED_HEIGHT_MM)
        self.update_from_selection()

    # --- Typography Event Handlers ---

    def _on_text_content_changed(self, text: str):
        if self._is_updating_ui:
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.text = text
                font = QFont(item.entity.font_family, max(4, int(round(item.entity.font_size * 2))))
                fm = QFontMetricsF(font)
                tw = max(10.0, fm.horizontalAdvance(text) + 6.0)
                item.entity.width = max(item.entity.width, tw)
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_text_editing_finished(self):
        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()

    def _on_font_family_changed(self, font: QFont):
        if self._is_updating_ui:
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.font_family = font.family()
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_font_size_changed(self, size: float):
        if self._is_updating_ui:
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                orig_sz = max(0.1, item.entity.font_size)
                ratio = size / orig_sz
                item.entity.font_size = size
                if self.lock_aspect_ratio:
                    item.entity.height = max(1.0, item.entity.height * ratio)
                    item.entity.width = max(1.0, item.entity.width * ratio)
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_bold_toggled(self, checked: bool):
        if self._is_updating_ui:
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.bold = checked
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_italic_toggled(self, checked: bool):
        if self._is_updating_ui:
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.italic = checked
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_underline_toggled(self, checked: bool):
        if self._is_updating_ui:
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.underline = checked
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_text_mode_changed(self, index: int):
        if self._is_updating_ui:
            return
        mode_val = "Outline" if index == 1 else "Fill"
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.fill_mode = mode_val
                item.sync_from_entity()
        self.scene.entity_modified.emit()
