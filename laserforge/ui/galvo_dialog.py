"""
LaserForge Galvo & Fiber Laser Marking Studio Dialog.
Configures mirror delay compensation, beam wobble generator, and rotary cylinder band splitting.
"""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QPushButton, QGroupBox,
    QTabWidget, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.galvo_engine import GalvoEngine, GalvoDelays, WobbleConfig
from laserforge.core.models import LaserEntity, PathEntity


class GalvoStudioDialog(QDialog):
    """Galvo Mirror Delay & Beam Wobble Studio Dialog."""

    wobble_applied = pyqtSignal(dict)

    def __init__(self, selected_entities: Optional[List[LaserEntity]] = None, parent=None):
        super().__init__(parent)
        self.selected_entities = selected_entities or []
        self.setWindowTitle("Galvo & Fiber Laser Marking Studio 🪞")
        self.resize(540, 520)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # Tab 1: Beam Wobble Generator
        tab_wobble = QWidget()
        w_layout = QVBoxLayout(tab_wobble)

        grp_wobble = QGroupBox("Beam Wobble Parameters")
        w_grid = QGridLayout(grp_wobble)

        self.chk_wobble = QCheckBox("Enable Beam Wobble (Kerf Expansion & Deep Annealing)")
        self.chk_wobble.setChecked(True)
        w_grid.addWidget(self.chk_wobble, 0, 0, 1, 2)

        w_grid.addWidget(QLabel("Wobble Pattern:"), 1, 0)
        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems(["circle", "figure8", "sinusoidal"])
        w_grid.addWidget(self.combo_pattern, 1, 1)

        w_grid.addWidget(QLabel("Wobble Amplitude / Width (mm):"), 2, 0)
        self.spin_amp = QDoubleSpinBox()
        self.spin_amp.setRange(0.05, 5.0)
        self.spin_amp.setSingleStep(0.05)
        self.spin_amp.setValue(0.5)
        w_grid.addWidget(self.spin_amp, 2, 1)

        w_grid.addWidget(QLabel("Wobble Pitch / Cycle (mm):"), 3, 0)
        self.spin_pitch = QDoubleSpinBox()
        self.spin_pitch.setRange(0.02, 2.0)
        self.spin_pitch.setSingleStep(0.02)
        self.spin_pitch.setValue(0.15)
        w_grid.addWidget(self.spin_pitch, 3, 1)

        w_layout.addWidget(grp_wobble)

        lbl_target = QLabel(f"Targeting: {len(self.selected_entities)} selected canvas entities.")
        lbl_target.setStyleSheet("font-weight: bold; color: #38bdf8;")
        w_layout.addWidget(lbl_target)
        w_layout.addStretch()

        tabs.addTab(tab_wobble, "🌀 Beam Wobble")

        # Tab 2: Mirror Delay Calibration
        tab_delays = QWidget()
        d_layout = QVBoxLayout(tab_delays)

        grp_delays = QGroupBox("Galvanometer Settle Delays (Microseconds)")
        d_grid = QGridLayout(grp_delays)

        d_grid.addWidget(QLabel("Laser ON Delay (μs):"), 0, 0)
        self.spin_on_delay = QDoubleSpinBox()
        self.spin_on_delay.setRange(0.0, 5000.0)
        self.spin_on_delay.setValue(120.0)
        d_grid.addWidget(self.spin_on_delay, 0, 1)

        d_grid.addWidget(QLabel("Laser OFF Delay (μs):"), 1, 0)
        self.spin_off_delay = QDoubleSpinBox()
        self.spin_off_delay.setRange(0.0, 5000.0)
        self.spin_off_delay.setValue(100.0)
        d_grid.addWidget(self.spin_off_delay, 1, 1)

        d_grid.addWidget(QLabel("Mark Settle Delay (μs):"), 2, 0)
        self.spin_mark_delay = QDoubleSpinBox()
        self.spin_mark_delay.setRange(0.0, 5000.0)
        self.spin_mark_delay.setValue(200.0)
        d_grid.addWidget(self.spin_mark_delay, 2, 1)

        d_grid.addWidget(QLabel("Jump Rapid Delay (μs):"), 3, 0)
        self.spin_jump_delay = QDoubleSpinBox()
        self.spin_jump_delay.setRange(0.0, 5000.0)
        self.spin_jump_delay.setValue(250.0)
        d_grid.addWidget(self.spin_jump_delay, 3, 1)

        d_grid.addWidget(QLabel("Polygon Corner Delay (μs):"), 4, 0)
        self.spin_poly_delay = QDoubleSpinBox()
        self.spin_poly_delay.setRange(0.0, 5000.0)
        self.spin_poly_delay.setValue(80.0)
        d_grid.addWidget(self.spin_poly_delay, 4, 1)

        d_layout.addWidget(grp_delays)
        d_layout.addStretch()

        tabs.addTab(tab_delays, "⏱ Mirror Delays")

        layout.addWidget(tabs)

        # Dialog Buttons
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_apply = QPushButton("Apply Wobble & Delays 🚀")
        btn_apply.setStyleSheet("font-weight: bold; background-color: #2563eb; color: white; padding: 8px 16px;")
        btn_apply.clicked.connect(self._on_apply)
        btn_box.addWidget(btn_apply)

        layout.addLayout(btn_box)

    def _on_apply(self):
        wobble_cfg = WobbleConfig(
            enabled=self.chk_wobble.isChecked(),
            pattern=self.combo_pattern.currentText(),
            amplitude_mm=self.spin_amp.value(),
            pitch_mm=self.spin_pitch.value()
        )

        delays = GalvoDelays(
            laser_on_delay_us=self.spin_on_delay.value(),
            laser_off_delay_us=self.spin_off_delay.value(),
            mark_delay_us=self.spin_mark_delay.value(),
            jump_delay_us=self.spin_jump_delay.value(),
            polygon_delay_us=self.spin_poly_delay.value()
        )

        self.wobble_applied.emit({
            "wobble": wobble_cfg,
            "delays": delays
        })
        self.accept()
