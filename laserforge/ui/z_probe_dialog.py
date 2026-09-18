"""
LaserForge Z-Probe & Auto-Focus Studio Dialog.

Interactive control dialog for automated laser focus setting via touch plate:
- Real-time probe parameter tuning (feed rate, max travel, plate thickness)
- Lens focal length presets (20mm, 30mm, 50mm, or custom)
- One-click G38.2 probe cycle dispatch
- Interactive Z jogging helpers
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QComboBox, QCheckBox, QPushButton, QGroupBox,
    QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from laserforge.core.z_probe_controller import ZProbeEngine, ZProbeSettings
from laserforge.core.audio_alerts import AudioChimeEngine


class ZProbeStudioDialog(QDialog):
    """Studio dialog for running Z auto-focus touch plate cycles."""

    def __init__(self, serial_ctrl=None, settings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Z-Probe & Auto-Focus Studio (G38.2)")
        self.resize(560, 520)
        self.setMinimumSize(480, 440)

        self.serial_ctrl = serial_ctrl
        self.app_settings = settings
        self.probe_engine = ZProbeEngine(serial_controller=serial_ctrl, parent=self)

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header Info Banner
        header = QLabel("⚡ Auto-Focus & Touch-Plate Calibration")
        header.setFont(QFont("sans-serif", 13, QFont.Weight.Bold))
        header.setStyleSheet("color: #00E5FF;")
        layout.addWidget(header)

        desc = QLabel(
            "Connect your touch plate clip to the laser carriage and place the plate "
            "directly on top of your workpiece. The laser will descend at a controlled feed "
            "rate, detect electrical contact, and automatically zero the focal point."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a0a0b8; font-size: 11px;")
        layout.addWidget(desc)

        # Group 1: Touch Plate & Lens Parameters
        grp_calib = QGroupBox("Touch Plate & Optics Geometry")
        grp_calib_lay = QGridLayout(grp_calib)
        grp_calib_lay.setSpacing(10)

        grp_calib_lay.addWidget(QLabel("Touch Plate Thickness:"), 0, 0)
        self.spin_plate = QDoubleSpinBox()
        self.spin_plate.setRange(0.1, 100.0)
        self.spin_plate.setValue(getattr(self.app_settings, "z_probe_plate_thickness", 15.0))
        self.spin_plate.setSuffix(" mm")
        grp_calib_lay.addWidget(self.spin_plate, 0, 1)

        grp_calib_lay.addWidget(QLabel("Lens Focal Length / Offset:"), 1, 0)
        self.combo_lens = QComboBox()
        self.combo_lens.addItem("Standard Lens (0 mm offset)", 0.0)
        self.combo_lens.addItem("20 mm Focal Lens Block", 20.0)
        self.combo_lens.addItem("30 mm Focal Lens Block", 30.0)
        self.combo_lens.addItem("50 mm Focal Lens Block", 50.0)
        self.combo_lens.addItem("Custom Offset...", -1.0)
        self.combo_lens.currentIndexChanged.connect(self._on_lens_preset_changed)
        grp_calib_lay.addWidget(self.combo_lens, 1, 1)

        self.spin_focal = QDoubleSpinBox()
        self.spin_focal.setRange(-100.0, 100.0)
        self.spin_focal.setValue(getattr(self.app_settings, "z_probe_focal_offset", 0.0))
        self.spin_focal.setSuffix(" mm")
        self.spin_focal.setEnabled(False)
        grp_calib_lay.addWidget(self.spin_focal, 2, 1)

        layout.addWidget(grp_calib)

        # Group 2: Motion Parameters
        grp_motion = QGroupBox("Probing Motion Settings")
        grp_motion_lay = QGridLayout(grp_motion)
        grp_motion_lay.setSpacing(10)

        grp_motion_lay.addWidget(QLabel("Probing Feed Rate:"), 0, 0)
        self.spin_feed = QDoubleSpinBox()
        self.spin_feed.setRange(10.0, 1000.0)
        self.spin_feed.setValue(getattr(self.app_settings, "z_probe_feed_rate", 120.0))
        self.spin_feed.setSuffix(" mm/min")
        grp_motion_lay.addWidget(self.spin_feed, 0, 1)

        grp_motion_lay.addWidget(QLabel("Max Descent Distance:"), 1, 0)
        self.spin_travel = QDoubleSpinBox()
        self.spin_travel.setRange(5.0, 200.0)
        self.spin_travel.setValue(getattr(self.app_settings, "z_probe_max_travel", 40.0))
        self.spin_travel.setSuffix(" mm")
        grp_motion_lay.addWidget(self.spin_travel, 1, 1)

        grp_motion_lay.addWidget(QLabel("Retract Height:"), 2, 0)
        self.spin_retract = QDoubleSpinBox()
        self.spin_retract.setRange(0.5, 50.0)
        self.spin_retract.setValue(getattr(self.app_settings, "z_probe_retract", 3.0))
        self.spin_retract.setSuffix(" mm")
        grp_motion_lay.addWidget(self.spin_retract, 2, 1)

        self.chk_auto_zero = QCheckBox("Set Work Coordinate Z0 (G10 L20 P1) Automatically")
        self.chk_auto_zero.setChecked(getattr(self.app_settings, "z_probe_auto_zero", True))
        grp_motion_lay.addWidget(self.chk_auto_zero, 3, 0, 1, 2)

        layout.addWidget(grp_motion)

        # Progress / Status label
        self.lbl_status = QLabel("Ready. Verify touch plate connection before starting.")
        self.lbl_status.setStyleSheet("color: #88c0d0; font-weight: bold;")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Manual Z Jog Helper Toolbar
        h_jog = QHBoxLayout()
        h_jog.addWidget(QLabel("Manual Z Adjustment:"))
        btn_z_up = QPushButton("▲ Z +5mm")
        btn_z_up.clicked.connect(lambda: self._jog_z(5.0))
        btn_z_down = QPushButton("▼ Z -5mm")
        btn_z_down.clicked.connect(lambda: self._jog_z(-5.0))
        h_jog.addWidget(btn_z_up)
        h_jog.addWidget(btn_z_down)
        layout.addLayout(h_jog)

        # Action Buttons
        btn_box = QHBoxLayout()
        self.btn_probe = QPushButton("🎯 Start Auto-Focus Probe Cycle")
        self.btn_probe.setStyleSheet("""
            QPushButton {
                background-color: #0088cc;
                color: white;
                font-weight: bold;
                padding: 10px 18px;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0099ee;
            }
        """)
        self.btn_probe.clicked.connect(self._run_probe)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        btn_box.addWidget(btn_close)
        btn_box.addWidget(self.btn_probe)
        layout.addLayout(btn_box)

    def _connect_signals(self):
        self.probe_engine.probe_progress.connect(self._on_progress)
        self.probe_engine.probe_success.connect(self._on_success)
        self.probe_engine.probe_failed.connect(self._on_failed)

    def _on_lens_preset_changed(self, idx: int):
        val = self.combo_lens.currentData()
        if val == -1.0:
            self.spin_focal.setEnabled(True)
        else:
            self.spin_focal.setEnabled(False)
            self.spin_focal.setValue(val)

    def _jog_z(self, delta_mm: float):
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            self.serial_ctrl.send_command(f"$J=G91 G21 Z{delta_mm:.3f} F{self.spin_feed.value():.1f}")
        else:
            QMessageBox.information(self, "Z Jog", "Laser is not connected.")

    def _run_probe(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to your laser before probing.")
            return

        settings = ZProbeSettings(
            feed_rate_mm_min=self.spin_feed.value(),
            max_travel_mm=self.spin_travel.value(),
            retract_distance_mm=self.spin_retract.value(),
            plate_thickness_mm=self.spin_plate.value(),
            focal_offset_mm=self.spin_focal.value(),
            auto_zero_work_z=self.chk_auto_zero.isChecked()
        )

        # Save settings back to app config
        if self.app_settings:
            self.app_settings.z_probe_feed_rate = settings.feed_rate_mm_min
            self.app_settings.z_probe_max_travel = settings.max_travel_mm
            self.app_settings.z_probe_retract = settings.retract_distance_mm
            self.app_settings.z_probe_plate_thickness = settings.plate_thickness_mm
            self.app_settings.z_probe_focal_offset = settings.focal_offset_mm
            self.app_settings.z_probe_auto_zero = settings.auto_zero_work_z

        self.progress_bar.setVisible(True)
        self.btn_probe.setEnabled(False)
        self.probe_engine.execute_probe(settings)

    def _on_progress(self, msg: str):
        self.lbl_status.setText(msg)

    def _on_success(self, triggered_z: float):
        self.progress_bar.setVisible(False)
        self.btn_probe.setEnabled(True)
        self.lbl_status.setText(f"✓ Probe Successful! Triggered at Z={triggered_z:.3f} mm. Focal height zeroed.")
        AudioChimeEngine.play_chime("probe_trigger")

    def _on_failed(self, err: str):
        self.progress_bar.setVisible(False)
        self.btn_probe.setEnabled(True)
        self.lbl_status.setText(f"✗ Probing Error: {err}")
        AudioChimeEngine.play_chime("alarm")
