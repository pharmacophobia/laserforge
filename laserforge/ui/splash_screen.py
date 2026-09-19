"""
LaserForge Startup Loading & Splash Screen.
Displays high-tech branding, initialization status, and smooth progress tracking
while heavy modules (PyQt6, OpenCV, DXF/SVG engines, CUDA/Torch) load.
"""

import os
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QFrame, QApplication, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QFont, QColor, QPainter, QLinearGradient, QPen


class LaserForgeSplashScreen(QWidget):
    """
    High-Performance Dark-Themed Frameless Splash / Loading Screen for LaserForge.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Frameless, stay on top, splash screen window hints
        self.setWindowFlags(
            Qt.WindowType.SplashScreen |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(540, 330)
        self._init_ui()

        # Center splash on primary display screen
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen:
                geo = screen.geometry()
                x = (geo.width() - self.width()) // 2
                y = (geo.height() - self.height()) // 2
                self.move(x, y)

    def _init_ui(self):
        # Outer wrapper layout to provide space for translucent drop shadow
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        # Main background container frame
        self.container = QFrame()
        self.container.setObjectName("SplashContainer")
        self.container.setStyleSheet("""
            #SplashContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1a1a24, stop:0.5 #14141c, stop:1 #0e0e14);
                border: 1.5px solid #00aaff;
                border-radius: 12px;
            }
        """)

        # Drop shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 170, 255, 90))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        # 1. Header with Logo, Title & Version Badge
        header_layout = QHBoxLayout()
        header_layout.setSpacing(14)

        # Logo icon
        self.lbl_logo = QLabel()
        logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "laserforge.png")
        if os.path.exists(logo_path):
            pix = QPixmap(logo_path)
            if not pix.isNull():
                self.lbl_logo.setPixmap(pix.scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if not self.lbl_logo.pixmap():
            # Fallback stylized laser icon
            self.lbl_logo.setText("⚡")
            self.lbl_logo.setStyleSheet("font-size: 38px; color: #00e5ff;")
            self.lbl_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_layout.addWidget(self.lbl_logo)

        # Title and subtitle text
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title_layout = QHBoxLayout()
        self.lbl_title = QLabel("LASERFORGE")
        self.lbl_title.setStyleSheet("""
            font-family: 'Segoe UI', 'Ubuntu', 'Helvetica Neue', sans-serif;
            font-size: 24px;
            font-weight: 900;
            letter-spacing: 2px;
            color: #ffffff;
        """)
        title_layout.addWidget(self.lbl_title)

        self.lbl_version = QLabel("v1.4.0")
        self.lbl_version.setStyleSheet("""
            background-color: #003355;
            color: #00d0ff;
            border: 1px solid #0088cc;
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: bold;
        """)
        title_layout.addWidget(self.lbl_version)
        title_layout.addStretch(1)

        self.lbl_subtitle = QLabel("LightBurn-Alternative Laser Engraving & Cutting Studio")
        self.lbl_subtitle.setStyleSheet("color: #9494a8; font-size: 12px; font-weight: 500;")

        text_layout.addLayout(title_layout)
        text_layout.addWidget(self.lbl_subtitle)
        header_layout.addLayout(text_layout, 1)

        layout.addLayout(header_layout)

        # 2. Tech / Feature Badges
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)
        chips = ["GRBL 1.1f Engine", "Dynamic M4 Power", "Camera V4L2", "GPU Acceleration"]
        for chip in chips:
            lbl_chip = QLabel(f"• {chip}")
            lbl_chip.setStyleSheet("""
                color: #5ab4e8;
                font-size: 10px;
                font-weight: 600;
                background-color: #1a2230;
                border: 1px solid #28384e;
                border-radius: 3px;
                padding: 2px 6px;
            """)
            chips_layout.addWidget(lbl_chip)
        chips_layout.addStretch(1)
        layout.addLayout(chips_layout)

        layout.addSpacing(6)

        # 3. Dynamic Status Message & Percentage
        status_row = QHBoxLayout()
        self.lbl_status = QLabel("Starting LaserForge engine...")
        self.lbl_status.setStyleSheet("color: #e0e0f0; font-size: 12px; font-weight: 600;")
        status_row.addWidget(self.lbl_status, 1)

        self.lbl_percent = QLabel("0%")
        self.lbl_percent.setStyleSheet("color: #00e5ff; font-size: 12px; font-weight: bold;")
        status_row.addWidget(self.lbl_percent)
        layout.addLayout(status_row)

        # 4. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #20202c;
                border: 1px solid #323246;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0077aa, stop:0.7 #00c8ff, stop:1 #00ffee);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # 5. Quick Workshop Tip Footer
        self.lbl_tip = QLabel("Tip: M4 dynamic power automatically scales laser output with travel speed.")
        self.lbl_tip.setStyleSheet("color: #6c6c82; font-size: 10px; font-style: italic;")
        layout.addWidget(self.lbl_tip)

        outer_layout.addWidget(self.container)

    def set_progress(self, value: int, message: Optional[str] = None):
        """Updates progress bar value (0-100) and optional status message."""
        clamped_val = max(0, min(100, int(value)))
        self.progress_bar.setValue(clamped_val)
        self.lbl_percent.setText(f"{clamped_val}%")
        if message:
            self.lbl_status.setText(message)
        # Flush GUI event queue so screen updates immediately if visible
        app = QApplication.instance()
        if app and self.isVisible():
            app.processEvents()

    def finish_splash(self, main_window: Optional[QWidget] = None):
        """Smoothly transitions to the main window and closes the splash."""
        self.set_progress(100, "Ready! Starting LaserForge Studio...")
        app = QApplication.instance()
        if app and self.isVisible():
            app.processEvents()
        if main_window:
            main_window.show()
            if hasattr(main_window, "showMaximized"):
                main_window.showMaximized()
            if hasattr(main_window, "raise_"):
                main_window.raise_()
            if hasattr(main_window, "activateWindow"):
                main_window.activateWindow()
        self.close()
