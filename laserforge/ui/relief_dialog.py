"""
LaserForge 3D Relief Engraving & Automated Z-Axis Step-Down Studio Dialog.
Configures multi-pass depth-stepping parameters and heightmap slicing for 3D reliefs.
"""

from typing import List, Optional
import os
from PIL import Image
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QGroupBox,
    QFileDialog, QMessageBox, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.relief_engine import ReliefEngine, ZStepConfig, ReliefCarveConfig
from laserforge.core.models import LaserEntity, PathEntity


class ReliefStudioDialog(QDialog):
    """3D Relief Engraving & Z-Step Depth Slicing Studio Dialog."""

    relief_generated = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("3D Relief Engraving & Automated Z-Step Studio 🏔")
        self.resize(560, 520)
        self.loaded_image: Optional[Image.Image] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # Tab 1: 3D Grayscale Heightmap Slicer
        tab_relief = QWidget()
        r_layout = QVBoxLayout(tab_relief)

        grp_file = QGroupBox("Heightmap Image Input")
        f_grid = QHBoxLayout(grp_file)
        self.lbl_file = QLabel("No heightmap loaded. (Click Browse...)")
        self.lbl_file.setStyleSheet("color: #94a3b8;")
        f_grid.addWidget(self.lbl_file)
        btn_browse = QPushButton("Browse Heightmap...")
        btn_browse.clicked.connect(self._browse_image)
        f_grid.addWidget(btn_browse)
        r_layout.addWidget(grp_file)

        grp_slicing = QGroupBox("Relief Slicing Parameters")
        s_grid = QGridLayout(grp_slicing)

        s_grid.addWidget(QLabel("Width (mm):"), 0, 0)
        self.spin_w = QDoubleSpinBox()
        self.spin_w.setRange(10.0, 500.0)
        self.spin_w.setValue(80.0)
        s_grid.addWidget(self.spin_w, 0, 1)

        s_grid.addWidget(QLabel("Height (mm):"), 0, 2)
        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(10.0, 500.0)
        self.spin_h.setValue(80.0)
        s_grid.addWidget(self.spin_h, 0, 3)

        s_grid.addWidget(QLabel("Max Carving Depth (mm):"), 1, 0)
        self.spin_depth = QDoubleSpinBox()
        self.spin_depth.setRange(0.1, 25.0)
        self.spin_depth.setValue(2.0)
        s_grid.addWidget(self.spin_depth, 1, 1)

        s_grid.addWidget(QLabel("Discrete Z Slices:"), 1, 2)
        self.spin_slices = QSpinBox()
        self.spin_slices.setRange(1, 20)
        self.spin_slices.setValue(5)
        s_grid.addWidget(self.spin_slices, 1, 3)

        s_grid.addWidget(QLabel("Scanline Interval (mm):"), 2, 0)
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.05, 1.0)
        self.spin_interval.setSingleStep(0.05)
        self.spin_interval.setValue(0.2)
        s_grid.addWidget(self.spin_interval, 2, 1)

        self.chk_invert = QCheckBox("Invert Depth (Darker = Deeper)")
        self.chk_invert.setChecked(True)
        s_grid.addWidget(self.chk_invert, 2, 2, 1, 2)

        r_layout.addWidget(grp_slicing)
        r_layout.addStretch()
        tabs.addTab(tab_relief, "🏔 3D Relief Slicer")

        # Tab 2: Automated Multi-Pass Z Step-Down
        tab_zstep = QWidget()
        z_layout = QVBoxLayout(tab_zstep)

        grp_z = QGroupBox("Motorized Z-Table Step-Down")
        z_grid = QGridLayout(grp_z)

        z_grid.addWidget(QLabel("Material Thickness (mm):"), 0, 0)
        self.spin_mat_thick = QDoubleSpinBox()
        self.spin_mat_thick.setRange(0.5, 50.0)
        self.spin_mat_thick.setValue(6.0)
        z_grid.addWidget(self.spin_mat_thick, 0, 1)

        z_grid.addWidget(QLabel("Cut Passes:"), 0, 2)
        self.spin_passes = QSpinBox()
        self.spin_passes.setRange(1, 20)
        self.spin_passes.setValue(4)
        z_grid.addWidget(self.spin_passes, 0, 3)

        z_grid.addWidget(QLabel("Z Step Down per Pass (mm):"), 1, 0)
        self.spin_z_step = QDoubleSpinBox()
        self.spin_z_step.setRange(0.1, 10.0)
        self.spin_z_step.setValue(1.5)
        z_grid.addWidget(self.spin_z_step, 1, 1)

        z_grid.addWidget(QLabel("Rapid Travel Clearance (mm):"), 1, 2)
        self.spin_retract = QDoubleSpinBox()
        self.spin_retract.setRange(1.0, 50.0)
        self.spin_retract.setValue(5.0)
        z_grid.addWidget(self.spin_retract, 1, 3)

        self.lbl_z_summary = QLabel("Pass Depths: Z0.0 -> Z-1.5 -> Z-3.0 -> Z-4.5 mm")
        self.lbl_z_summary.setStyleSheet("font-family: monospace; color: #fde047; padding-top: 8px;")
        z_grid.addWidget(self.lbl_z_summary, 2, 0, 1, 4)

        z_layout.addWidget(grp_z)
        z_layout.addStretch()
        tabs.addTab(tab_zstep, "⚙ Multi-Pass Z Step-Down")

        layout.addWidget(tabs)

        for w in [self.spin_passes, self.spin_z_step]:
            w.valueChanged.connect(self._update_z_summary)

        # Dialog Buttons
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_generate = QPushButton("Generate 3D Toolpaths & Add to Bed 🚀")
        btn_generate.setStyleSheet("font-weight: bold; background-color: #2563eb; color: white; padding: 8px 16px;")
        btn_generate.clicked.connect(self._on_generate)
        btn_box.addWidget(btn_generate)

        layout.addLayout(btn_box)

    def _browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Grayscale Heightmap Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )
        if file_path:
            try:
                self.loaded_image = Image.open(file_path)
                self.lbl_file.setText(os.path.basename(file_path))
                self.lbl_file.setStyleSheet("color: #38bdf8; font-weight: bold;")
            except Exception as e:
                QMessageBox.critical(self, "Error Loading Image", f"Failed to load image: {e}")

    def _update_z_summary(self):
        passes = self.spin_passes.value()
        step = self.spin_z_step.value()
        levels = [f"Z-{round(i * step, 2)}" for i in range(passes)]
        self.lbl_z_summary.setText(f"Pass Depths: {' -> '.join(levels)} mm")

    def _on_generate(self):
        if not self.loaded_image:
            QMessageBox.warning(self, "Image Required", "Please load a grayscale heightmap image first.")
            return

        cfg = ReliefCarveConfig(
            width_mm=self.spin_w.value(),
            height_mm=self.spin_h.value(),
            max_depth_mm=self.spin_depth.value(),
            z_slices=self.spin_slices.value(),
            line_interval_mm=self.spin_interval.value(),
            invert_heightmap=self.chk_invert.isChecked()
        )

        res = ReliefEngine.generate_relief_scanlines(self.loaded_image, cfg, origin_x=20.0, origin_y=20.0)
        
        # Package slices into PathEntity objects
        entities: List[LaserEntity] = []
        for s in res["slices"]:
            z_dep = s["z_depth"]
            segs = s["segments"]
            if segs:
                contours = [[p1, p2] for p1, p2 in segs]
                ent = PathEntity(
                    layer_id=0,
                    name=f"Relief_Slice_{s['slice_index']}_Z{z_dep}mm",
                    x=0.0,
                    y=0.0,
                    contours=contours,
                    closed=False
                )
                entities.append(ent)

        if not entities:
            QMessageBox.warning(self, "Empty Toolpaths", "No valid carving paths generated from this heightmap.")
            return

        self.relief_generated.emit(entities)
        self.accept()
