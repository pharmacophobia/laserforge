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

    # Automated crash and unhandled exception interceptor
    from laserforge.core.telemetry import CrashManager
    CrashManager.install()

    # Initialize Qt Application
    import os
    os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
    app = QApplication(sys.argv)
    # Enable HiDPI crisp icon rendering if attribute is present (PyQt5/early Qt6)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app.setApplicationName("LaserForge")
    app.setOrganizationName("LaserForge")

    # Apply dark theme styling
    apply_dark_theme(app)

    # Check for splash screen suppression flags
    no_splash = any(arg in sys.argv for arg in ("--no-splash", "--headless", "-ns"))
    splash = None
    if not no_splash:
        try:
            from laserforge.ui.splash_screen import LaserForgeSplashScreen
            splash = LaserForgeSplashScreen()
            splash.show()
            splash.set_progress(10, "Initializing core machine profiles...")
            app.processEvents()
        except Exception as e:
            print(f"[LaserForge Warning] Could not launch splash screen: {e}", file=sys.stderr)
            splash = None

    # Launch Main Window
    start_tutorial = any(arg in sys.argv for arg in ("--tutorial", "-t"))
    window = MainWindow(start_tutorial=start_tutorial, splash_callback=splash.set_progress if splash else None)
    CrashManager.register_context_provider(lambda: {
        "settings": getattr(window, "settings", None),
        "serial": getattr(window, "serial_ctrl", None),
        "recent_logs": window.console_panel.console_output.toPlainText().splitlines() if hasattr(window, "console_panel") else []
    })

    if splash:
        splash.finish_splash(window)
    else:
        window.showMaximized()

    # Clean shutdown handling
    ret = app.exec()
    try:
        window.serial_ctrl.disconnect()
    except Exception as e:
        print(f"[LaserForge] Serial port shutdown error: {e}", file=sys.stderr)
    try:
        from laserforge.core.worker_lifecycle import get_lifecycle_manager
        get_lifecycle_manager().shutdown_all(timeout=3.0)
    except Exception as e:
        print(f'[LaserForge] Worker lifecycle shutdown error: {e}', file=sys.stderr)
    sys.exit(ret)


if __name__ == "__main__":
    main()
