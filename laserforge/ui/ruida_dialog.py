"""
LaserForge Ruida DSP Ethernet Controller & .rd Binary Export Dialog.
Uploads toolpaths over Ethernet UDP to OMTech/Thunder Laser CO2 cutters,
or exports standalone .rd binary files for USB thumb drive burning.
"""

from typing import List, Optional
import os
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QSpinBox, QPushButton, QGroupBox, QTextEdit, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt

from laserforge.core.ruida_engine import RuidaCompiler, RuidaUDPClient, RUIDA_DEFAULT_IP, RUIDA_DEFAULT_PORT
from laserforge.core.models import LaserEntity


class RuidaDialog(QDialog):
    """Ruida DSP Ethernet Controller & Binary Exporter Dialog."""

    def __init__(self, entities: List[LaserEntity], parent=None):
        super().__init__(parent)
        self.entities = entities
        self.setWindowTitle("Ruida DSP Ethernet Controller & .rd Toolpath Studio 📡")
        self.resize(540, 480)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 1. Controller Network Configuration
        grp_net = QGroupBox("Ruida DSP Ethernet Settings")
        n_grid = QGridLayout(grp_net)

        n_grid.addWidget(QLabel("Controller IP Address:"), 0, 0)
        self.edit_ip = QLineEdit(RUIDA_DEFAULT_IP)
        n_grid.addWidget(self.edit_ip, 0, 1)

        n_grid.addWidget(QLabel("UDP Port:"), 0, 2)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(RUIDA_DEFAULT_PORT)
        n_grid.addWidget(self.spin_port, 0, 3)

        btn_ping = QPushButton("📡 Test Ping / Connect")
        btn_ping.clicked.connect(self._ping_controller)
        n_grid.addWidget(btn_ping, 1, 0, 1, 4)

        layout.addWidget(grp_net)

        # 2. File & Memory Actions
        grp_act = QGroupBox("DSP Actions & File Compilation")
        a_layout = QVBoxLayout(grp_act)

        lbl_summary = QLabel(f"Active Job Entities: {len(self.entities)} vector objects")
        lbl_summary.setStyleSheet("font-weight: bold; color: #38bdf8;")
        a_layout.addWidget(lbl_summary)

        btn_row = QHBoxLayout()

        btn_export = QPushButton("💾 Export .rd File (USB Thumb Drive)...")
        btn_export.clicked.connect(self._export_rd_file)
        btn_row.addWidget(btn_export)

        btn_upload = QPushButton("⚡ Upload & Burn via UDP")
        btn_upload.setStyleSheet("font-weight: bold; background-color: #2563eb; color: white;")
        btn_upload.clicked.connect(self._upload_and_burn)
        btn_row.addWidget(btn_upload)

        a_layout.addLayout(btn_row)
        layout.addWidget(grp_act)

        # 3. Network Status Log
        layout.addWidget(QLabel("Controller Communication Log:"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #0f172a; color: #f8fafc; font-family: monospace; font-size: 11px;")
        layout.addWidget(self.txt_log)

        # Dialog Close Button
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

        self._log("Ruida DSP Studio ready. Default controller IP: 192.168.1.100:50200")

    def _log(self, msg: str):
        self.txt_log.append(f"> {msg}")

    def _ping_controller(self):
        ip = self.edit_ip.text().strip()
        port = self.spin_port.value()
        client = RuidaUDPClient(ip=ip, port=port)
        self._log(f"Pinging Ruida controller at {ip}:{port}...")
        ok, msg = client.ping()
        if ok:
            self._log(f"✅ {msg}")
            QMessageBox.information(self, "Controller Online", msg)
        else:
            self._log(f"❌ {msg}")
            QMessageBox.warning(self, "Ping Failed", msg)

    def _export_rd_file(self):
        if not self.entities:
            QMessageBox.warning(self, "Empty Scene", "No vector artwork to compile.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Ruida Binary File", "job.rd", "Ruida RD Files (*.rd *.ud5)"
        )
        if file_path:
            try:
                rd_bytes = RuidaCompiler.compile_paths_to_rd(self.entities)
                with open(file_path, "wb") as f:
                    f.write(rd_bytes)
                self._log(f"Saved {len(rd_bytes)} bytes to {os.path.basename(file_path)}")
                QMessageBox.information(self, "Export Successful", f"Saved {len(rd_bytes)} bytes to {file_path}")
            except Exception as e:
                self._log(f"Export error: {e}")
                QMessageBox.critical(self, "Export Error", f"Failed to compile .rd file: {e}")

    def _upload_and_burn(self):
        if not self.entities:
            QMessageBox.warning(self, "Empty Scene", "No vector artwork to burn.")
            return

        ip = self.edit_ip.text().strip()
        port = self.spin_port.value()
        client = RuidaUDPClient(ip=ip, port=port)

        rd_bytes = RuidaCompiler.compile_paths_to_rd(self.entities)
        self._log(f"Uploading {len(rd_bytes)} bytes to Ruida at {ip}:{port}...")

        ok, msg = client.upload_rd_file(bytes(rd_bytes))
        if ok:
            self._log(f"✅ {msg}")
            # Ask confirmation to start burning
            res = QMessageBox.question(
                self, "Start Ruida Burn",
                "Toolpaths successfully transferred to Ruida buffer!\n\nStart laser job now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                burn_ok, burn_msg = client.start_job()
                self._log(burn_msg)
        else:
            self._log(f"❌ {msg}")
            QMessageBox.critical(self, "Transfer Failed", msg)
