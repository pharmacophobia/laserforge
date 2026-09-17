"""
LaserForge Mobile Remote Jogger & Workshop Web Pendant Studio Dialog.
Launches the embedded HTTP server and presents URL and QR code for scanning from a phone/tablet.
"""

from typing import Optional
import os
import qrcode
from PIL import Image
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage

from laserforge.core.web_pendant import WebPendantServer


class WebPendantDialog(QDialog):
    """Mobile Remote Jogger & Monitoring Pendant Studio Dialog."""

    def __init__(self, server: WebPendantServer, parent=None):
        super().__init__(parent)
        self.server = server
        self.setWindowTitle("Mobile Remote Jogger & Web Pendant 📱")
        self.setFixedSize(480, 520)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Header Info
        lbl_desc = QLabel(
            "LaserForge embedded web server allows you to jog the laser, frame workpieces, "
            "and trigger emergency stops from any phone, tablet, or laptop on your workshop Wi-Fi."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(lbl_desc)

        # Server Control Box
        grp_srv = QGroupBox("Server Status & Controls")
        s_layout = QVBoxLayout(grp_srv)

        h_ctrl = QHBoxLayout()
        self.lbl_status = QLabel("Server: Running ✅" if self.server.is_running else "Server: Stopped ⏸")
        self.lbl_status.setStyleSheet("font-weight: bold; font-size: 13px; color: #10b981;" if self.server.is_running else "font-weight: bold; font-size: 13px; color: #f87171;")
        h_ctrl.addWidget(self.lbl_status)

        self.btn_toggle = QPushButton("Stop Server" if self.server.is_running else "Start Server")
        self.btn_toggle.clicked.connect(self._toggle_server)
        h_ctrl.addWidget(self.btn_toggle)
        s_layout.addLayout(h_ctrl)

        layout.addWidget(grp_srv)

        # QR Code & URL Box
        grp_qr = QGroupBox("Scan with Phone / Tablet")
        q_layout = QVBoxLayout(grp_qr)
        q_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        q_layout.addWidget(self.lbl_qr)

        local_ip = WebPendantServer.get_local_ip()
        self.url = f"http://{local_ip}:{self.server.port}"

        self.lbl_url = QLabel(f"<b>Pendant URL:</b> <a href='{self.url}' style='color: #38bdf8;'>{self.url}</a>")
        self.lbl_url.setOpenExternalLinks(True)
        self.lbl_url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_url.setStyleSheet("font-size: 13px; padding-top: 6px;")
        q_layout.addWidget(self.lbl_url)

        layout.addWidget(grp_qr)

        self._render_qr_code()

        # Close button
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _render_qr_code(self):
        try:
            qr = qrcode.QRCode(box_size=5, border=2)
            qr.add_data(self.url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert PIL image to QPixmap
            im_bytes = img.convert("RGBA").tobytes("raw", "RGBA")
            qim = QImage(im_bytes, img.size[0], img.size[1], QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(qim)
            self.lbl_qr.setPixmap(pix)
        except Exception as e:
            self.lbl_qr.setText(f"[QR Code Error: {e}]")

    def _toggle_server(self):
        if self.server.is_running:
            self.server.stop()
            self.lbl_status.setText("Server: Stopped ⏸")
            self.lbl_status.setStyleSheet("font-weight: bold; font-size: 13px; color: #f87171;")
            self.btn_toggle.setText("Start Server")
        else:
            ok = self.server.start()
            if ok:
                self.lbl_status.setText("Server: Running ✅")
                self.lbl_status.setStyleSheet("font-weight: bold; font-size: 13px; color: #10b981;")
                self.btn_toggle.setText("Stop Server")
            else:
                QMessageBox.critical(self, "Server Error", "Failed to start Web Pendant server.")
