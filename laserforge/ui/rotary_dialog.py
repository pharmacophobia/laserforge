"""
LaserForge Rotary Axis Studio Dialog (Rollers & Chucks).
Provides live interactive kinematics calibration, circumference calculations,
visual cylinder bed guides, 360° test rotation jogging, and dual-mode control.
"""

import math
from typing import Optional
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QPen, QBrush, QPainter, QFont, QRadialGradient, QLinearGradient
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QWidget, QFrame, QMessageBox
)

from laserforge.config import MachineSettings
from laserforge.core.rotary_engine import RotaryEngine
from laserforge.core.serial_controller import SerialController


class CylinderVisualWidget(QWidget):
    """Visual diagram showing the cylindrical workpiece and rotation vector."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 320)
        self.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333; border-radius: 4px;")
        self.diameter = 65.0
        self.circumference = 204.2
        self.rotary_type = "Roller"
        self.is_enabled = False

    def update_values(self, diameter: float, circumference: float, rtype: str, enabled: bool):
        self.diameter = diameter
        self.circumference = circumference
        self.rotary_type = rtype
        self.is_enabled = enabled
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Title
        painter.setPen(QColor("#888888"))
        painter.setFont(QFont("Sans", 9))
        status = "Active" if self.is_enabled else "Disabled"
        status_color = "#00e676" if self.is_enabled else "#ff5252"
        painter.drawText(12, 20, f"Cylinder Geometry ({status})")

        cx = w / 2.0
        cy = h / 2.0 - 10.0

        cyl_w = min(w * 0.55, 180.0)
        cyl_h = min(h * 0.45, 120.0)

        x1 = cx - cyl_w / 2.0
        y1 = cy - cyl_h / 2.0

        # Draw 3D Cylinder representation
        # Cylinder body gradient
        grad = QLinearGradient(x1, y1, x1, y1 + cyl_h)
        if self.is_enabled:
            grad.setColorAt(0.0, QColor("#1e3a5f"))
            grad.setColorAt(0.4, QColor("#3b82f6"))
            grad.setColorAt(0.7, QColor("#1d4ed8"))
            grad.setColorAt(1.0, QColor("#0f172a"))
            outline_pen = QPen(QColor("#60a5fa"), 2)
        else:
            grad.setColorAt(0.0, QColor("#2a2a2a"))
            grad.setColorAt(0.5, QColor("#444444"))
            grad.setColorAt(1.0, QColor("#1f1f1f"))
            outline_pen = QPen(QColor("#555555"), 2)

        # Body
        painter.setPen(outline_pen)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(QRectF(x1, y1, cyl_w, cyl_h), 8, 8)

        # Left ellipse face
        face_rx = 18.0
        painter.setBrush(QBrush(QColor("#1e293b") if self.is_enabled else QColor("#222")))
        painter.drawEllipse(QPointF(x1, cy), face_rx, cyl_h / 2.0)

        # Right ellipse face
        painter.setBrush(QBrush(QColor("#38bdf8") if self.is_enabled else QColor("#444")))
        painter.drawEllipse(QPointF(x1 + cyl_w, cy), face_rx, cyl_h / 2.0)

        # Draw Roller wheels underneath if Roller type
        if self.rotary_type.lower() == "roller":
            roller_r = 14.0
            roller_y = y1 + cyl_h + 16.0
            r1_x = cx - 35.0
            r2_x = cx + 35.0

            painter.setPen(QPen(QColor("#888"), 1.5))
            painter.setBrush(QBrush(QColor("#333")))
            painter.drawEllipse(QPointF(r1_x, roller_y), roller_r, roller_r)
            painter.drawEllipse(QPointF(r2_x, roller_y), roller_r, roller_r)

            painter.setPen(QColor("#aaa"))
            painter.setFont(QFont("Sans", 7))
            painter.drawText(int(cx - 30), int(roller_y + 24), "Drive Rollers")

        # Dimension readouts
        painter.setPen(QColor("#00e676"))
        painter.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
        painter.drawText(int(cx - 50), int(y1 - 10), f"⌀ {self.diameter:.1f} mm")

        painter.setPen(QColor("#ffeb3b"))
        painter.drawText(int(cx - 65), int(h - 12), f"Circumference: {self.circumference:.1f} mm")


class RotaryDialog(QDialog):
    """Studio Dialog to configure rotary roller and chuck laser engraving."""

    rotary_settings_changed = pyqtSignal()

    def __init__(
        self,
        settings: MachineSettings,
        serial_controller: Optional[SerialController] = None,
        parent=None
    ):
        super().__init__(parent)
        self.settings = settings
        self.serial = serial_controller

        self.setWindowTitle("Rotary Axis Studio 🔄")
        self.resize(800, 520)
        self._init_ui()
        self._recompute_and_update()

    def _init_ui(self):
        layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Configuration Controls
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setSpacing(10)

        # 1. Enable & Type
        grp_arch = QGroupBox("Rotary Hardware Configuration")
        form_arch = QGridLayout(grp_arch)

        self.chk_enable = QCheckBox("Enable Rotary Axis Mode")
        self.chk_enable.setChecked(getattr(self.settings, "rotary_enabled", False))
        self.chk_enable.setStyleSheet("font-weight: bold; color: #00e676; font-size: 13px;")
        self.chk_enable.toggled.connect(self._recompute_and_update)
        form_arch.addWidget(self.chk_enable, 0, 0, 1, 2)

        form_arch.addWidget(QLabel("Rotary Type:"), 1, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Roller", "Chuck"])
        self.combo_type.setCurrentText(getattr(self.settings, "rotary_type", "Roller"))
        self.combo_type.currentTextChanged.connect(self._recompute_and_update)
        form_arch.addWidget(self.combo_type, 1, 1)

        form_arch.addWidget(QLabel("Control Mode:"), 2, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Software Scaling", "Hardware $101"])
        self.combo_mode.setCurrentText(getattr(self.settings, "rotary_mode", "Software Scaling"))
        self.combo_mode.setToolTip(
            "Software Scaling: Multiplies G-code coordinates without touching GRBL EEPROM (safest).\n"
            "Hardware $101: Overrides GRBL $101 steps/mm directly in controller EEPROM."
        )
        self.combo_mode.currentTextChanged.connect(self._recompute_and_update)
        form_arch.addWidget(self.combo_mode, 2, 1)

        self.chk_invert = QCheckBox("Invert Rotation Direction")
        self.chk_invert.setChecked(getattr(self.settings, "rotary_invert_dir", False))
        self.chk_invert.toggled.connect(self._recompute_and_update)
        form_arch.addWidget(self.chk_invert, 3, 0, 1, 2)

        ctrl_layout.addWidget(grp_arch)

        # 2. Dimensions & Kinematics
        grp_dim = QGroupBox("Workpiece & Roller Dimensions")
        form_dim = QGridLayout(grp_dim)

        form_dim.addWidget(QLabel("Object Diameter (D):"), 0, 0)
        self.spin_diameter = QDoubleSpinBox()
        self.spin_diameter.setRange(1.0, 500.0)
        self.spin_diameter.setValue(getattr(self.settings, "rotary_object_diameter", 65.0))
        self.spin_diameter.setSuffix(" mm")
        self.spin_diameter.valueChanged.connect(self._on_diameter_changed)
        form_dim.addWidget(self.spin_diameter, 0, 1)

        form_dim.addWidget(QLabel("Circumference (C):"), 1, 0)
        self.spin_circumference = QDoubleSpinBox()
        self.spin_circumference.setRange(1.0, 1600.0)
        self.spin_circumference.setValue(RotaryEngine.compute_circumference(self.spin_diameter.value()))
        self.spin_circumference.setSuffix(" mm")
        self.spin_circumference.valueChanged.connect(self._on_circumference_changed)
        form_dim.addWidget(self.spin_circumference, 1, 1)

        form_dim.addWidget(QLabel("Roller Diameter:"), 2, 0)
        self.spin_roller_diam = QDoubleSpinBox()
        self.spin_roller_diam.setRange(1.0, 150.0)
        self.spin_roller_diam.setValue(getattr(self.settings, "rotary_roller_diameter", 20.0))
        self.spin_roller_diam.setSuffix(" mm")
        self.spin_roller_diam.valueChanged.connect(self._recompute_and_update)
        form_dim.addWidget(self.spin_roller_diam, 2, 1)

        form_dim.addWidget(QLabel("Steps per Revolution:"), 3, 0)
        self.spin_steps_rev = QDoubleSpinBox()
        self.spin_steps_rev.setRange(100.0, 100000.0)
        self.spin_steps_rev.setValue(getattr(self.settings, "rotary_steps_per_rev", 3200.0))
        self.spin_steps_rev.setSingleStep(100.0)
        self.spin_steps_rev.valueChanged.connect(self._recompute_and_update)
        form_dim.addWidget(self.spin_steps_rev, 3, 1)

        ctrl_layout.addWidget(grp_dim)

        # 3. Telemetry Card
        card = QFrame()
        card.setStyleSheet("background-color: #222; border: 1px solid #444; border-radius: 4px; padding: 6px;")
        card_layout = QVBoxLayout(card)

        self.lbl_calc_steps = QLabel("Calculated Steps/mm: 50.93")
        self.lbl_calc_steps.setStyleSheet("font-weight: bold; color: #00e676; font-size: 13px;")
        card_layout.addWidget(self.lbl_calc_steps)

        self.lbl_scale = QLabel("Software Scale Factor: 0.6366x")
        self.lbl_scale.setStyleSheet("color: #00bcd4;")
        card_layout.addWidget(self.lbl_scale)

        ctrl_layout.addWidget(card)

        ctrl_layout.addStretch()

        # Action Buttons
        btn_test = QPushButton("🔄  Test 360° Rotation Jog")
        btn_test.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; padding: 8px;")
        btn_test.clicked.connect(self._run_360_test)
        ctrl_layout.addWidget(btn_test)

        btn_save = QPushButton("💾  Save & Apply Settings")
        btn_save.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 8px;")
        btn_save.clicked.connect(self._save_and_apply)
        ctrl_layout.addWidget(btn_save)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        ctrl_layout.addWidget(btn_close)

        splitter.addWidget(ctrl_widget)

        # Right Preview Widget
        self.visual_widget = CylinderVisualWidget()
        splitter.addWidget(self.visual_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

    def _on_diameter_changed(self, val: float):
        self.spin_circumference.blockSignals(True)
        self.spin_circumference.setValue(RotaryEngine.compute_circumference(val))
        self.spin_circumference.blockSignals(False)
        self._recompute_and_update()

    def _on_circumference_changed(self, val: float):
        self.spin_diameter.blockSignals(True)
        self.spin_diameter.setValue(val / math.pi if val > 0 else 0.0)
        self.spin_diameter.blockSignals(False)
        self._recompute_and_update()

    def _recompute_and_update(self):
        diam = self.spin_diameter.value()
        circ = self.spin_circumference.value()
        rtype = self.combo_type.currentText()
        enabled = self.chk_enable.isChecked()

        # Show/hide roller diameter depending on type
        is_roller = (rtype.lower() == "roller")
        self.spin_roller_diam.setEnabled(is_roller)

        steps_mm = RotaryEngine.calculate_steps_per_mm(
            rotary_type=rtype,
            object_diameter_mm=diam,
            steps_per_rev=self.spin_steps_rev.value(),
            roller_diameter_mm=self.spin_roller_diam.value()
        )

        orig_y = self.settings.rotary_original_y_steps if self.settings.rotary_original_y_steps > 0 else self.settings.y_steps_per_mm
        scale = steps_mm / orig_y if orig_y > 0 else 1.0
        if self.chk_invert.isChecked():
            scale = -scale

        self.lbl_calc_steps.setText(f"Calculated Steps/mm: <b>{steps_mm:.2f}</b>")
        self.lbl_scale.setText(f"Software Scale Factor: <b>{scale:.4f}x</b>")

        self.visual_widget.update_values(diam, circ, rtype, enabled)

    def _run_360_test(self):
        """Sends a 360 degree rotation jog test via the serial controller."""
        if not self.serial or not getattr(self.serial, "is_connected", False):
            QMessageBox.warning(self, "Serial Disconnected", "Please connect to your GRBL laser via USB before running a 360° test jog.")
            return

        # Temporarily create test settings
        test_settings = MachineSettings()
        test_settings.rotary_enabled = True
        test_settings.rotary_type = self.combo_type.currentText()
        test_settings.rotary_mode = self.combo_mode.currentText()
        test_settings.rotary_object_diameter = self.spin_diameter.value()
        test_settings.rotary_roller_diameter = self.spin_roller_diam.value()
        test_settings.rotary_steps_per_rev = self.spin_steps_rev.value()
        test_settings.rotary_original_y_steps = self.settings.y_steps_per_mm
        test_settings.rotary_invert_dir = self.chk_invert.isChecked()

        gcode = RotaryEngine.generate_test_rotation_gcode(test_settings)
        for line in gcode.splitlines():
            cl = line.strip()
            if cl and not cl.startswith(";"):
                self.serial.send_command(cl)

        QMessageBox.information(
            self, "360° Rotation Dispatched",
            f"Rotated cylinder 360° ({self.spin_circumference.value():.1f} mm) and returned to origin.\n"
            "Verify the workpiece made an exact 1-turn rotation."
        )

    def _save_and_apply(self):
        self.settings.rotary_enabled = self.chk_enable.isChecked()
        self.settings.rotary_type = self.combo_type.currentText()
        self.settings.rotary_mode = self.combo_mode.currentText()
        self.settings.rotary_object_diameter = self.spin_diameter.value()
        self.settings.rotary_roller_diameter = self.spin_roller_diam.value()
        self.settings.rotary_steps_per_rev = self.spin_steps_rev.value()
        self.settings.rotary_invert_dir = self.chk_invert.isChecked()

        # If Hardware $101 mode selected and serial connected, offer to send $101
        if self.settings.rotary_enabled and self.settings.rotary_mode == "Hardware $101":
            if self.serial and getattr(self.serial, "is_connected", False):
                cmd = RotaryEngine.generate_eeprom_override_command(self.settings)
                self.serial.send_command(cmd)

        self.rotary_settings_changed.emit()
        QMessageBox.information(self, "Rotary Settings Applied", "Rotary Axis settings successfully saved and applied.")
