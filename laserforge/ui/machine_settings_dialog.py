"""
LaserForge Machine Settings Configuration Dialog.
Allows setting workbed dimensions, origin orientation, GRBL power scale ($30),
rapid travel feedrates, framing power, and air assist commands.
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
    QGroupBox, QDialogButtonBox, QCheckBox
)
from PyQt6.QtCore import Qt

from laserforge.config import MachineSettings


class MachineSettingsDialog(QDialog):
    def __init__(self, settings: MachineSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Machine Settings - LaserForge")
        self.setMinimumWidth(440)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 1. Workbed Dimensions
        bed_group = QGroupBox("Workbed Geometry")
        bed_layout = QGridLayout(bed_group)

        bed_layout.addWidget(QLabel("Width X (mm):"), 0, 0)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(50.0, 5000.0)
        self.width_spin.setValue(self.settings.bed_width)
        bed_layout.addWidget(self.width_spin, 0, 1)

        bed_layout.addWidget(QLabel("Height Y (mm):"), 1, 0)
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(50.0, 5000.0)
        self.height_spin.setValue(self.settings.bed_height)
        bed_layout.addWidget(self.height_spin, 1, 1)

        bed_layout.addWidget(QLabel("Origin Corner:"), 2, 0)
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["Bottom-Left", "Top-Left", "Bottom-Right", "Top-Right"])
        self.origin_combo.setCurrentText(self.settings.origin_corner)
        bed_layout.addWidget(self.origin_combo, 2, 1)

        layout.addWidget(bed_group)

        # 2. Laser Controller & G-Code
        laser_group = QGroupBox("Laser & GRBL Controller")
        laser_layout = QGridLayout(laser_group)

        laser_layout.addWidget(QLabel("Max S-Value ($30):"), 0, 0)
        self.max_s_spin = QSpinBox()
        self.max_s_spin.setRange(1, 100000)
        self.max_s_spin.setValue(self.settings.max_s_value)
        laser_layout.addWidget(self.max_s_spin, 0, 1)

        laser_layout.addWidget(QLabel("Laser Mode:"), 1, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["M4 (Dynamic Power - Recommended)", "M3 (Constant Power)"])
        if self.settings.laser_mode == "M4":
            self.mode_combo.setCurrentIndex(0)
        else:
            self.mode_combo.setCurrentIndex(1)
        laser_layout.addWidget(self.mode_combo, 1, 1)

        laser_layout.addWidget(QLabel("Rapid Speed (mm/min):"), 2, 0)
        self.rapid_spin = QDoubleSpinBox()
        self.rapid_spin.setRange(100.0, 30000.0)
        self.rapid_spin.setValue(self.settings.rapid_speed)
        laser_layout.addWidget(self.rapid_spin, 2, 1)

        laser_layout.addWidget(QLabel("Framing Power (%):"), 3, 0)
        self.frame_power_spin = QDoubleSpinBox()
        self.frame_power_spin.setRange(0.01, 10.0)
        self.frame_power_spin.setDecimals(2)
        self.frame_power_spin.setValue(self.settings.framing_power_pct)
        laser_layout.addWidget(self.frame_power_spin, 3, 1)

        layout.addWidget(laser_group)

        # Dialog Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _save_and_accept(self):
        self.settings.bed_width = self.width_spin.value()
        self.settings.bed_height = self.height_spin.value()
        self.settings.origin_corner = self.origin_combo.currentText()
        self.settings.max_s_value = self.max_s_spin.value()
        self.settings.laser_mode = "M4" if "M4" in self.mode_combo.currentText() else "M3"
        self.settings.rapid_speed = self.rapid_spin.value()
        self.settings.framing_power_pct = self.frame_power_spin.value()
        self.accept()
