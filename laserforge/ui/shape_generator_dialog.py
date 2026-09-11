"""
LaserForge Parametric Shapes & Outline Offset Dialog.
Allows users to generate complex vector shapes (polygons, stars, gears, hearts, slots, rings)
and create outward/inward cut borders around existing artwork.
"""

from typing import List, Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QTabWidget, QWidget, QGroupBox,
    QMessageBox
)

from laserforge.core.shape_generator import ShapeGenerator
from laserforge.core.models import LaserEntity
from laserforge.core.layer_manager import LayerManager


class ShapeGeneratorDialog(QDialog):
    shape_generated = pyqtSignal(list)  # Emits list of LaserEntity
    offset_requested = pyqtSignal(float, str, int)  # (distance_mm, corner_style, target_layer_id)

    def __init__(
        self,
        parent=None,
        layer_manager: Optional[LayerManager] = None,
        selected_entities_count: int = 0,
        bed_width: float = 150.0,
        bed_height: float = 200.0,
        initial_tab: int = 0
    ):
        super().__init__(parent)
        self.setWindowTitle("LaserForge Shapes Library & Offset Border Tool")
        self.resize(520, 440)
        self.layer_manager = layer_manager
        self.selected_entities_count = selected_entities_count
        self.bed_width = bed_width
        self.bed_height = bed_height

        self._init_ui()
        if initial_tab == 1 and selected_entities_count > 0:
            self.tabs.setCurrentIndex(1)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        self.tabs = QTabWidget()

        # Tab 1: Parametric Shapes
        shape_tab = QWidget()
        s_layout = QVBoxLayout(shape_tab)

        s_grid = QGridLayout()
        s_grid.setSpacing(8)

        s_grid.addWidget(QLabel("Shape Type:"), 0, 0)
        self.combo_shape_type = QComboBox()
        self.combo_shape_type.addItem("Regular Polygon (Triangle, Hexagon...)", "polygon")
        self.combo_shape_type.addItem("Star (Parametric Points)", "star")
        self.combo_shape_type.addItem("Heart (Cardioid Curve)", "heart")
        self.combo_shape_type.addItem("Gear / Sprocket with Center Bore", "gear")
        self.combo_shape_type.addItem("Slot / Capsule (Round Ends)", "slot")
        self.combo_shape_type.addItem("Concentric Ring / Donut Washer", "ring")
        self.combo_shape_type.addItem("Cross / Plus", "cross")
        self.combo_shape_type.currentIndexChanged.connect(self._on_shape_type_changed)
        s_grid.addWidget(self.combo_shape_type, 0, 1)

        # Dynamic parameter widgets
        self.lbl_p1 = QLabel("Number of Sides:")
        self.spin_p1 = QSpinBox()
        self.spin_p1.setRange(3, 32)
        self.spin_p1.setValue(6)
        s_grid.addWidget(self.lbl_p1, 1, 0)
        s_grid.addWidget(self.spin_p1, 1, 1)

        self.lbl_p2 = QLabel("Radius / Outer Dia (mm):")
        self.spin_p2 = QDoubleSpinBox()
        self.spin_p2.setRange(2.0, 300.0)
        self.spin_p2.setValue(25.0)
        self.spin_p2.setSuffix(" mm")
        s_grid.addWidget(self.lbl_p2, 2, 0)
        s_grid.addWidget(self.spin_p2, 2, 1)

        self.lbl_p3 = QLabel("Inner Radius / Bore (mm):")
        self.spin_p3 = QDoubleSpinBox()
        self.spin_p3.setRange(1.0, 200.0)
        self.spin_p3.setValue(12.0)
        self.spin_p3.setSuffix(" mm")
        s_grid.addWidget(self.lbl_p3, 3, 0)
        s_grid.addWidget(self.spin_p3, 3, 1)

        # Placement
        pos_grp = QGroupBox("Placement on Laser Bed")
        pos_layout = QGridLayout(pos_grp)
        pos_layout.addWidget(QLabel("Center X (mm):"), 0, 0)
        self.spin_cx = QDoubleSpinBox()
        self.spin_cx.setRange(0.0, self.bed_width)
        self.spin_cx.setValue(self.bed_width / 2.0)
        self.spin_cx.setSuffix(" mm")
        pos_layout.addWidget(self.spin_cx, 0, 1)

        pos_layout.addWidget(QLabel("Center Y (mm):"), 1, 0)
        self.spin_cy = QDoubleSpinBox()
        self.spin_cy.setRange(0.0, self.bed_height)
        self.spin_cy.setValue(self.bed_height / 2.0)
        self.spin_cy.setSuffix(" mm")
        pos_layout.addWidget(self.spin_cy, 1, 1)

        pos_layout.addWidget(QLabel("Target Layer:"), 2, 0)
        self.combo_layer = QComboBox()
        self.combo_layer.addItem("Layer 0 (Black - Engrave)", 0)
        self.combo_layer.addItem("Layer 1 (Red - Cut)", 1)
        self.combo_layer.addItem("Layer 2 (Cyan - Guide)", 2)
        pos_layout.addWidget(self.combo_layer, 2, 1)

        s_layout.addLayout(s_grid)
        s_layout.addWidget(pos_grp)
        s_layout.addStretch(1)

        btn_insert = QPushButton("✨ Insert Shape onto Canvas")
        btn_insert.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px;")
        btn_insert.clicked.connect(self._on_insert_shape)
        s_layout.addWidget(btn_insert)

        self.tabs.addTab(shape_tab, "⭐ Parametric Shapes Generator")

        # Tab 2: Offset / Border Tool
        offset_tab = QWidget()
        o_layout = QVBoxLayout(offset_tab)

        lbl_desc = QLabel(
            "Creates an outward outline contour (for cutting borders) or inward inset "
            "around currently selected artwork."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #b0bec5; margin-bottom: 8px;")
        o_layout.addWidget(lbl_desc)

        lbl_sel = QLabel(f"Selected Workpieces on Canvas: {self.selected_entities_count}")
        lbl_sel.setStyleSheet("font-weight: bold; color: #80d8ff;")
        o_layout.addWidget(lbl_sel)

        o_grid = QGridLayout()
        o_grid.setSpacing(8)

        o_grid.addWidget(QLabel("Offset Distance:"), 0, 0)
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-50.0, 50.0)
        self.spin_offset.setValue(3.0)
        self.spin_offset.setSingleStep(0.5)
        self.spin_offset.setSuffix(" mm")
        self.spin_offset.setToolTip("Positive for outward border, negative for inward inset")
        o_grid.addWidget(self.spin_offset, 0, 1)

        o_grid.addWidget(QLabel("Corner Style:"), 1, 0)
        self.combo_join = QComboBox()
        self.combo_join.addItems(["Round", "Miter (Sharp)", "Bevel"])
        o_grid.addWidget(self.combo_join, 1, 1)

        o_grid.addWidget(QLabel("Target Layer:"), 2, 0)
        self.combo_offset_layer = QComboBox()
        self.combo_offset_layer.addItem("Layer 1 (Red - Cut Perimeter)", 1)
        self.combo_offset_layer.addItem("Layer 0 (Black - Engrave)", 0)
        self.combo_offset_layer.addItem("Layer 2 (Cyan - Guide)", 2)
        o_grid.addWidget(self.combo_offset_layer, 2, 1)

        o_layout.addLayout(o_grid)
        o_layout.addStretch(1)

        btn_apply_offset = QPushButton("✨ Create Offset Border")
        btn_apply_offset.setStyleSheet("background-color: #e91e63; color: white; font-weight: bold; padding: 6px;")
        btn_apply_offset.clicked.connect(self._on_apply_offset)
        if self.selected_entities_count == 0:
            btn_apply_offset.setEnabled(False)
            btn_apply_offset.setToolTip("Select at least one entity on canvas to offset")
        o_layout.addWidget(btn_apply_offset)

        self.tabs.addTab(offset_tab, "⭕ Offset / Cut Border Tool")

        main_layout.addWidget(self.tabs)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        main_layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

        self._on_shape_type_changed(0)

    def _on_shape_type_changed(self, idx: int):
        shape_type = self.combo_shape_type.currentData()
        if shape_type == "polygon":
            self.lbl_p1.setText("Number of Sides (N):")
            self.spin_p1.setVisible(True)
            self.spin_p1.setRange(3, 32)
            self.spin_p1.setValue(6)

            self.lbl_p2.setText("Circumscribed Radius:")
            self.spin_p2.setValue(25.0)

            self.lbl_p3.setVisible(False)
            self.spin_p3.setVisible(False)

        elif shape_type == "star":
            self.lbl_p1.setText("Number of Points:")
            self.spin_p1.setVisible(True)
            self.spin_p1.setRange(3, 24)
            self.spin_p1.setValue(5)

            self.lbl_p2.setText("Outer Tip Radius:")
            self.spin_p2.setValue(30.0)

            self.lbl_p3.setText("Inner Valley Radius:")
            self.lbl_p3.setVisible(True)
            self.spin_p3.setVisible(True)
            self.spin_p3.setValue(14.0)

        elif shape_type == "heart":
            self.lbl_p1.setVisible(False)
            self.spin_p1.setVisible(False)

            self.lbl_p2.setText("Heart Width (mm):")
            self.spin_p2.setValue(40.0)

            self.lbl_p3.setText("Heart Height (mm):")
            self.lbl_p3.setVisible(True)
            self.spin_p3.setVisible(True)
            self.spin_p3.setValue(40.0)

        elif shape_type == "gear":
            self.lbl_p1.setText("Number of Teeth:")
            self.spin_p1.setVisible(True)
            self.spin_p1.setRange(4, 48)
            self.spin_p1.setValue(12)

            self.lbl_p2.setText("Pitch Diameter (mm):")
            self.spin_p2.setValue(40.0)

            self.lbl_p3.setText("Center Shaft Bore (mm):")
            self.lbl_p3.setVisible(True)
            self.spin_p3.setVisible(True)
            self.spin_p3.setValue(6.0)

        elif shape_type == "slot":
            self.lbl_p1.setVisible(False)
            self.spin_p1.setVisible(False)

            self.lbl_p2.setText("Total Slot Length (mm):")
            self.spin_p2.setValue(60.0)

            self.lbl_p3.setText("Slot Width / Cap Dia:")
            self.lbl_p3.setVisible(True)
            self.spin_p3.setVisible(True)
            self.spin_p3.setValue(20.0)

        elif shape_type == "ring":
            self.lbl_p1.setVisible(False)
            self.spin_p1.setVisible(False)

            self.lbl_p2.setText("Outer Diameter (mm):")
            self.spin_p2.setValue(50.0)

            self.lbl_p3.setText("Inner Hole Dia (mm):")
            self.lbl_p3.setVisible(True)
            self.spin_p3.setVisible(True)
            self.spin_p3.setValue(30.0)

        elif shape_type == "cross":
            self.lbl_p1.setVisible(False)
            self.spin_p1.setVisible(False)

            self.lbl_p2.setText("Overall Size (mm):")
            self.spin_p2.setValue(40.0)

            self.lbl_p3.setText("Arm Thickness (mm):")
            self.lbl_p3.setVisible(True)
            self.spin_p3.setVisible(True)
            self.spin_p3.setValue(12.0)

    def _on_insert_shape(self):
        st = self.combo_shape_type.currentData()
        cx = self.spin_cx.value()
        cy = self.spin_cy.value()
        layer_id = self.combo_layer.currentData()
        ents: List[LaserEntity] = []

        if st == "polygon":
            ents.append(ShapeGenerator.create_regular_polygon(
                sides=self.spin_p1.value(), radius=self.spin_p2.value(),
                cx=cx, cy=cy, layer_id=layer_id
            ))
        elif st == "star":
            ents.append(ShapeGenerator.create_star(
                points=self.spin_p1.value(), r_outer=self.spin_p2.value(),
                r_inner=self.spin_p3.value(), cx=cx, cy=cy, layer_id=layer_id
            ))
        elif st == "heart":
            ents.append(ShapeGenerator.create_heart(
                width=self.spin_p2.value(), height=self.spin_p3.value(),
                cx=cx, cy=cy, layer_id=layer_id
            ))
        elif st == "gear":
            ents.extend(ShapeGenerator.create_gear(
                teeth=self.spin_p1.value(), pitch_dia=self.spin_p2.value(),
                bore_dia=self.spin_p3.value(), cx=cx, cy=cy, layer_id=layer_id
            ))
        elif st == "slot":
            ents.append(ShapeGenerator.create_slot_capsule(
                width=self.spin_p2.value(), height=self.spin_p3.value(),
                cx=cx, cy=cy, layer_id=layer_id
            ))
        elif st == "ring":
            ents.extend(ShapeGenerator.create_ring_donut(
                outer_dia=self.spin_p2.value(), inner_dia=self.spin_p3.value(),
                cx=cx, cy=cy, layer_id=layer_id
            ))
        elif st == "cross":
            ents.append(ShapeGenerator.create_cross(
                size=self.spin_p2.value(), arm_width=self.spin_p3.value(),
                cx=cx, cy=cy, layer_id=layer_id
            ))

        if ents:
            self.shape_generated.emit(ents)
            self.accept()

    def _on_apply_offset(self):
        dist = self.spin_offset.value()
        if abs(dist) < 0.05:
            QMessageBox.warning(self, "Invalid Distance", "Offset distance must be non-zero.")
            return

        join_style = self.combo_join.currentText().split()[0]
        layer_id = self.combo_offset_layer.currentData()
        self.offset_requested.emit(dist, join_style, layer_id)
        self.accept()
