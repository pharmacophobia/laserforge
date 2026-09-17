"""
LaserForge Commercial License Activation & Free Trial Dialog.
Provides customer key activation, license status visualization, and device identification.
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QDesktopServices
from PyQt6.QtCore import QUrl

from laserforge.core.license_engine import LicenseEngine, LicenseStatus


class LicenseDialog(QDialog):
    """License Management & Activation Dialog."""

    license_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LaserForge Pro License & Trial Activation 🔑")
        self.setFixedSize(540, 460)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; }
            QGroupBox { border: 1px solid #334155; border-radius: 6px; margin-top: 12px; font-weight: bold; color: #38bdf8; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #cbd5e1; font-size: 12px; }
            QLineEdit { background-color: #1e293b; border: 1px solid #475569; border-radius: 4px; color: #f8fafc; padding: 6px 10px; font-size: 13px; font-family: monospace; }
            QLineEdit:focus { border: 1px solid #38bdf8; }
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton#btnDeactivate { background-color: #dc2626; }
            QPushButton#btnDeactivate:hover { background-color: #ef4444; }
            QPushButton#btnClose { background-color: #475569; }
            QPushButton#btnClose:hover { background-color: #64748b; }
        """)

        self._init_ui()
        self._refresh_status()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Header Badge & Status Box
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 12px;")
        sf_layout = QVBoxLayout(self.status_frame)

        self.lbl_title = QLabel("LaserForge Pro License Status")
        self.lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #f8fafc;")
        sf_layout.addWidget(self.lbl_title)

        self.lbl_status = QLabel("Evaluating...")
        self.lbl_status.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8; padding-top: 4px;")
        sf_layout.addWidget(self.lbl_status)

        self.lbl_details = QLabel("")
        self.lbl_details.setStyleSheet("font-size: 11px; color: #94a3b8;")
        sf_layout.addWidget(self.lbl_details)

        layout.addWidget(self.status_frame)

        # Activation Form Group
        self.grp_act = QGroupBox("Enter License Credentials")
        form_layout = QGridLayout(self.grp_act)

        form_layout.addWidget(QLabel("Registered Email:"), 0, 0)
        self.edit_email = QLineEdit()
        self.edit_email.setPlaceholderText("maker@example.com")
        form_layout.addWidget(self.edit_email, 0, 1)

        form_layout.addWidget(QLabel("License Key:"), 1, 0)
        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("LF-XXXX-XXXX-XXXX-XXXX")
        form_layout.addWidget(self.edit_key, 1, 1)

        form_layout.addWidget(QLabel("Machine ID:"), 2, 0)
        self.lbl_device_id = QLabel(LicenseEngine.get_device_fingerprint())
        self.lbl_device_id.setStyleSheet("font-family: monospace; color: #fde047; font-weight: bold;")
        form_layout.addWidget(self.lbl_device_id, 2, 1)

        layout.addWidget(self.grp_act)

        # Purchase Info & Links
        info_layout = QHBoxLayout()
        lbl_need_key = QLabel("Need a license?")
        lbl_need_key.setStyleSheet("color: #94a3b8; font-size: 12px;")
        btn_buy = QPushButton("Get License ($49 Perpetual)")
        btn_buy.setStyleSheet("background-color: #059669; font-size: 11px; padding: 5px 12px;")
        btn_buy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://laserforge.org/pricing")))
        info_layout.addWidget(lbl_need_key)
        info_layout.addWidget(btn_buy)
        info_layout.addStretch()
        layout.addLayout(info_layout)

        layout.addStretch()

        # Action Buttons
        btn_box = QHBoxLayout()
        self.btn_deactivate = QPushButton("Deactivate")
        self.btn_deactivate.setObjectName("btnDeactivate")
        self.btn_deactivate.clicked.connect(self._deactivate)
        btn_box.addWidget(self.btn_deactivate)

        btn_box.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setObjectName("btnClose")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)

        self.btn_activate = QPushButton("Activate License")
        self.btn_activate.clicked.connect(self._activate)
        btn_box.addWidget(self.btn_activate)

        layout.addLayout(btn_box)

    def _refresh_status(self):
        status: LicenseStatus = LicenseEngine.get_status()

        if status.is_licensed:
            self.lbl_status.setText(f"✅ Active Commercial License")
            self.lbl_status.setStyleSheet("font-size: 13px; font-weight: bold; color: #10b981;")
            self.lbl_details.setText(f"Licensed to: {status.licensed_to}\nKey: {status.license_key}\nThank you for supporting independent laser engineering software!")
            self.edit_email.setText(status.licensed_to)
            self.edit_key.setText(status.license_key)
            self.edit_email.setEnabled(False)
            self.edit_key.setEnabled(False)
            self.btn_activate.setEnabled(False)
            self.btn_deactivate.setVisible(True)
        elif status.is_trial_active:
            self.lbl_status.setText(f"⏳ 30-Day Free Trial ({status.days_remaining} days remaining)")
            self.lbl_status.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
            self.lbl_details.setText("You have unrestricted access to all features (no watermarks, full CAD/CAM).")
            self.btn_deactivate.setVisible(False)
        else:
            self.lbl_status.setText("⚠️ Free Trial Expired")
            self.lbl_status.setStyleSheet("font-size: 13px; font-weight: bold; color: #ef4444;")
            self.lbl_details.setText("Please activate with a commercial license key to continue burning jobs.")
            self.btn_deactivate.setVisible(False)

    def _activate(self):
        email = self.edit_email.text().strip()
        key = self.edit_key.text().strip()
        if not email or not key:
            QMessageBox.warning(self, "Input Required", "Please enter both your registered email and license key.")
            return

        success, msg = LicenseEngine.activate(key, email)
        if success:
            QMessageBox.information(self, "Activation Successful", msg)
            self._refresh_status()
            self.license_changed.emit(True)
        else:
            QMessageBox.critical(self, "Activation Failed", f"License verification failed:\n{msg}")

    def _deactivate(self):
        reply = QMessageBox.question(
            self, "Deactivate License",
            "Are you sure you want to deactivate this machine?\nThis will revert LaserForge back to free trial mode.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            LicenseEngine.deactivate()
            self.edit_email.setEnabled(True)
            self.edit_key.setEnabled(True)
            self.edit_email.clear()
            self.edit_key.clear()
            self.btn_activate.setEnabled(True)
            self._refresh_status()
            self.license_changed.emit(False)
