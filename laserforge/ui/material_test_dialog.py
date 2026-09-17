"""
LaserForge Material Test Card & Calibration Grid Studio Dialog.
Configures and generates parametric 2D matrices of Speed vs Power patches with single-line labels.
"""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QLineEdit,
    QPushButton, QGroupBox, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.material_test_generator import MaterialTestGenerator, MaterialTestGridConfig
from laserforge.core.models import LaserEntity


class MaterialTestDialog(QDialog):
    """Material Test Matrix & Calibration Studio Dialog."""

    grid_generated = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Automated Material Test Matrix Studio ⚡")
        self.resize(520, 560)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 1. Power & Speed Ranges Group
        grp_ranges = QGroupBox("Test Matrix Parameters")
        grid = QGridLayout(grp_ranges)

        # Speed (Rows)
        grid.addWidget(QLabel("Min Speed (mm/min):"), 0, 0)
        self.spin_min_speed = QDoubleSpinBox()
        self.spin_min_speed.setRange(50.0, 10000.0)
        self.spin_min_speed.setValue(300.0)
        grid.addWidget(self.spin_min_speed, 0, 1)

        grid.addWidget(QLabel("Max Speed (mm/min):"), 0, 2)
        self.spin_max_speed = QDoubleSpinBox()
        self.spin_max_speed.setRange(50.0, 20000.0)
        self.spin_max_speed.setValue(1800.0)
        grid.addWidget(self.spin_max_speed, 0, 3)

        grid.addWidget(QLabel("Speed Steps (Rows):"), 1, 0)
        self.spin_speed_steps = QSpinBox()
        self.spin_speed_steps.setRange(2, 20)
        self.spin_speed_steps.setValue(5)
        grid.addWidget(self.spin_speed_steps, 1, 1)

        # Power (Columns)
        grid.addWidget(QLabel("Min Power (%):"), 2, 0)
        self.spin_min_power = QDoubleSpinBox()
        self.spin_min_power.setRange(1.0, 100.0)
        self.spin_min_power.setValue(10.0)
        grid.addWidget(self.spin_min_power, 2, 1)

        grid.addWidget(QLabel("Max Power (%):"), 2, 2)
        self.spin_max_power = QDoubleSpinBox()
        self.spin_max_power.setRange(1.0, 100.0)
        self.spin_max_power.setValue(90.0)
        grid.addWidget(self.spin_max_power, 2, 3)

        grid.addWidget(QLabel("Power Steps (Cols):"), 3, 0)
        self.spin_power_steps = QSpinBox()
        self.spin_power_steps.setRange(2, 20)
        self.spin_power_steps.setValue(5)
        grid.addWidget(self.spin_power_steps, 3, 1)

        layout.addWidget(grp_ranges)

        # 2. Patch Geometry & Mode Group
        grp_geom = QGroupBox("Patch Style & Geometry")
        g_layout = QGridLayout(grp_geom)

        g_layout.addWidget(QLabel("Patch Mode:"), 0, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Fill (Vector Hatching)", "Cut (Perimeter Lines)", "Both (Hatch + Perimeter)"])
        g_layout.addWidget(self.combo_mode, 0, 1)

        g_layout.addWidget(QLabel("Hatch Interval (mm):"), 0, 2)
        self.spin_hatch_interval = QDoubleSpinBox()
        self.spin_hatch_interval.setRange(0.05, 2.0)
        self.spin_hatch_interval.setSingleStep(0.05)
        self.spin_hatch_interval.setValue(0.2)
        g_layout.addWidget(self.spin_hatch_interval, 0, 3)

        g_layout.addWidget(QLabel("Patch Width (mm):"), 1, 0)
        self.spin_w = QDoubleSpinBox()
        self.spin_w.setRange(3.0, 50.0)
        self.spin_w.setValue(8.0)
        g_layout.addWidget(self.spin_w, 1, 1)

        g_layout.addWidget(QLabel("Patch Height (mm):"), 1, 2)
        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(3.0, 50.0)
        self.spin_h.setValue(8.0)
        g_layout.addWidget(self.spin_h, 1, 3)

        g_layout.addWidget(QLabel("Patch Gap (mm):"), 2, 0)
        self.spin_gap = QDoubleSpinBox()
        self.spin_gap.setRange(0.5, 10.0)
        self.spin_gap.setValue(2.5)
        g_layout.addWidget(self.spin_gap, 2, 1)

        layout.addWidget(grp_geom)

        # 3. Labeling & Frame Group
        grp_labels = QGroupBox("Single-Line Text & Outer Frame")
        l_layout = QGridLayout(grp_labels)

        self.chk_labels = QCheckBox("Burn Single-Line Numeric Labels (Power % & Speed mm/m)")
        self.chk_labels.setChecked(True)
        l_layout.addWidget(self.chk_labels, 0, 0, 1, 2)

        l_layout.addWidget(QLabel("Card Header Title:"), 1, 0)
        self.edit_title = QLineEdit("LaserForge Material Matrix")
        l_layout.addWidget(self.edit_title, 1, 1)

        self.chk_frame = QCheckBox("Include Outer Drop-Out Cutout Frame")
        self.chk_frame.setChecked(True)
        l_layout.addWidget(self.chk_frame, 2, 0, 1, 2)

        layout.addWidget(grp_labels)

        # Info & Action Buttons
        self.lbl_info = QLabel("Total Patches: 25 | Dimensions: ~80 x ~75 mm")
        self.lbl_info.setStyleSheet("font-weight: bold; color: #38bdf8;")
        layout.addWidget(self.lbl_info)

        # Connect updates
        for w in [self.spin_speed_steps, self.spin_power_steps, self.spin_w, self.spin_h, self.spin_gap]:
            w.valueChanged.connect(self._update_info)

        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_generate = QPushButton("Add Test Matrix to Bed 🚀")
        btn_generate.setStyleSheet("font-weight: bold; background-color: #2563eb; color: white; padding: 8px 16px;")
        btn_generate.clicked.connect(self._on_generate)
        btn_box.addWidget(btn_generate)

        layout.addLayout(btn_box)
        self._update_info()

    def _update_info(self):
        s_steps = self.spin_speed_steps.value()
        p_steps = self.spin_power_steps.value()
        pw = self.spin_w.value()
        ph = self.spin_h.value()
        gap = self.spin_gap.value()

        tot_w = 24.0 + p_steps * (pw + gap)
        tot_h = 16.0 + s_steps * (ph + gap)
        self.lbl_info.setText(f"Total Patches: {s_steps * p_steps} ({s_steps} rows × {p_steps} cols) | Dimensions: ~{tot_w:.0f} × ~{tot_h:.0f} mm")

    def _on_generate(self):
        mode_str = "fill"
        if "Cut" in self.combo_mode.currentText():
            mode_str = "cut"
        elif "Both" in self.combo_mode.currentText():
            mode_str = "both"

        cfg = MaterialTestGridConfig(
            min_speed=self.spin_min_speed.value(),
            max_speed=self.spin_max_speed.value(),
            speed_steps=self.spin_speed_steps.value(),
            min_power=self.spin_min_power.value(),
            max_power=self.spin_max_power.value(),
            power_steps=self.spin_power_steps.value(),
            patch_width=self.spin_w.value(),
            patch_height=self.spin_h.value(),
            patch_gap=self.spin_gap.value(),
            test_mode=mode_str,
            hatch_interval=self.spin_hatch_interval.value(),
            include_labels=self.chk_labels.isChecked(),
            title_text=self.edit_title.text().strip(),
            include_frame=self.chk_frame.isChecked()
        )

        entities = MaterialTestGenerator.generate_grid(cfg, origin_x=20.0, origin_y=20.0)
        self.grid_generated.emit(entities)
        self.accept()
