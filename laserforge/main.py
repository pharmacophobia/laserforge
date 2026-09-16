#!/usr/bin/env python3
"""
LaserForge - High-Performance Laser Engraving and Cutting Suite.
LightBurn alternative for Linux and GRBL laser engravers.
"""

import os
import sys
import signal



from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from laserforge.ui.theme import apply_dark_theme
from laserforge.ui.main_window import MainWindow


def main():
    # Graceful handling of Ctrl+C in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Initialize Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("LaserForge")
    app.setOrganizationName("LaserForge")

    # Apply dark theme styling
    apply_dark_theme(app)

    # Launch Main Window
    window = MainWindow()
    window.show()

    # Clean shutdown handling
    ret = app.exec()
    try:
        window.serial_ctrl.disconnect()
    except Exception as e:
        print(f"[LaserForge] Serial port shutdown error: {e}", file=sys.stderr)
    sys.exit(ret)


if __name__ == "__main__":
    main()
