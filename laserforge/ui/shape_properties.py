"""
LaserForge Shape Properties Panel.
Displays and edits numeric coordinates (X, Y), dimensions (Width, Height),
rotation angle, aspect ratio lock, and quick alignment tools for selected CAD entities.
"""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QPushButton, QToolButton, QGroupBox,
    QCheckBox, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
)
from laserforge.ui.canvas_scene import LaserCanvasScene, LaserItemWrapper
from laserforge.config import DEFAULT_BED_WIDTH_MM, DEFAULT_BED_HEIGHT_MM



class ShapePropertiesPanel(QWidget):
    trace_image_requested = pyqtSignal()

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

        # 2. Alignment & Positioning Group
        align_group = QGroupBox("Alignment & Arrange")
        align_layout = QGridLayout(align_group)
        align_layout.setContentsMargins(6, 8, 6, 6)
        align_layout.setSpacing(4)

        btn_align_left = QPushButton("⇤ Left")
        btn_align_center_x = QPushButton("↔ Center")
        btn_align_right = QPushButton("Right ⇥")
        btn_align_top = QPushButton("barwedge Top")
        btn_align_center_y = QPushButton("↕ Middle")
        btn_align_bottom = QPushButton("Bottom ⊻")
        btn_bed_center = QPushButton("🎯 Bed Center")

        btn_align_left.clicked.connect(lambda: self._align("left"))
        btn_align_center_x.clicked.connect(lambda: self._align("center_x"))
        btn_align_right.clicked.connect(lambda: self._align("right"))
        btn_align_top.clicked.connect(lambda: self._align("top"))
        btn_align_center_y.clicked.connect(lambda: self._align("center_y"))
        btn_align_bottom.clicked.connect(lambda: self._align("bottom"))
        btn_bed_center.clicked.connect(self._center_on_bed)

        align_layout.addWidget(btn_align_left, 0, 0)
        align_layout.addWidget(btn_align_center_x, 0, 1)
        align_layout.addWidget(btn_align_right, 0, 2)
        align_layout.addWidget(btn_align_top, 1, 0)
        align_layout.addWidget(btn_align_center_y, 1, 1)
        align_layout.addWidget(btn_align_bottom, 1, 2)
        align_layout.addWidget(btn_bed_center, 2, 0, 1, 3)

        layout.addWidget(align_group)

        # 3. Image Vectorization Actions Group
        self.img_group = QGroupBox("Bitmap Vectorization")
        img_layout = QVBoxLayout(self.img_group)
        img_layout.setContentsMargins(6, 8, 6, 6)
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

        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            self.setEnabled(False)
            self.img_group.setVisible(False)
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
        self._is_updating_ui = True


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
            elif isinstance(ent, ImageEntity):
                ent.width = new_w
                if self.lock_aspect_ratio:
                    ent.height *= scale_x
            elif isinstance(ent, PathEntity):
                for contour in ent.contours:
                    for idx, pt in enumerate(contour):
                        contour[idx] = (ent.x + (pt[0] - ent.x) * scale_x, pt[1])

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
            elif isinstance(ent, ImageEntity):
                ent.height = new_h
                if self.lock_aspect_ratio:
                    ent.width *= scale_y
            elif isinstance(ent, PathEntity):
                for contour in ent.contours:
                    for idx, pt in enumerate(contour):
                        contour[idx] = (pt[0], ent.y + (pt[1] - ent.y) * scale_y)

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
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if len(selected_items) < 2:
            return

        boxes = [i.entity.get_bounds() for i in selected_items]
        min_x = min(b[0] for b in boxes)
        max_x = max(b[2] for b in boxes)
        min_y = min(b[1] for b in boxes)
        max_y = max(b[3] for b in boxes)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0

        for item, b in zip(selected_items, boxes):
            w = b[2] - b[0]
            h = b[3] - b[1]

            if mode == "left":
                item.entity.x += (min_x - b[0])
            elif mode == "right":
                item.entity.x += (max_x - b[2])
            elif mode == "center_x":
                item.entity.x += (center_x - (b[0] + w / 2.0))
            elif mode == "top":
                item.entity.y += (min_y - b[1])
            elif mode == "bottom":
                item.entity.y += (max_y - b[3])
            elif mode == "center_y":
                item.entity.y += (center_y - (b[1] + h / 2.0))

            item.sync_from_entity()

        self.scene.entity_modified.emit()
        self.update_from_selection()

    def _center_on_bed(self):
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            return

        boxes = [i.entity.get_bounds() for i in selected_items]
        min_x = min(b[0] for b in boxes)
        max_x = max(b[2] for b in boxes)
        min_y = min(b[1] for b in boxes)
        max_y = max(b[3] for b in boxes)

        curr_cx = (min_x + max_x) / 2.0
        curr_cy = (min_y + max_y) / 2.0

        target_cx = DEFAULT_BED_WIDTH_MM / 2.0
        target_cy = DEFAULT_BED_HEIGHT_MM / 2.0


        dx = target_cx - curr_cx
        dy = target_cy - curr_cy

        for item in selected_items:
            item.entity.x += dx
            item.entity.y += dy
            item.sync_from_entity()

        self.scene.entity_modified.emit()
        self.update_from_selection()
