"""
LaserForge Modern Dark Theme & Design Tokens.
LightBurn-inspired professional dark theme styling, color tokens, and custom QSS stylesheets.
"""

DARK_THEME_QSS = """
/* Global Window & Fonts */
QMainWindow, QDialog, QWidget {
    background-color: #1a1a20;
    color: #e0e0e8;
    font-family: 'Segoe UI', 'Ubuntu', 'Helvetica Neue', sans-serif;
    font-size: 12px;
}

/* Toolbars */
QToolBar {
    background-color: #24242e;
    border-bottom: 1px solid #323242;
    padding: 3px;
    spacing: 4px;
}
QToolButton {
    background-color: transparent;
    color: #d8d8e6;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 5px 8px;
    font-weight: 500;
}
QToolButton:hover {
    background-color: #343444;
    border: 1px solid #48485e;
    color: #ffffff;
}
QToolButton:pressed, QToolButton:checked {
    background-color: #0088cc;
    border: 1px solid #00aaff;
    color: #ffffff;
}

/* Dock Widgets */
QDockWidget {
    color: #f0f0ff;
    font-weight: bold;
    titlebar-close-icon: url(close.png);
}
QDockWidget::title {
    background-color: #262632;
    border: 1px solid #363648;
    border-radius: 4px 4px 0 0;
    padding: 6px 10px;
    text-align: left;
}

/* Group Boxes */
QGroupBox {
    border: 1px solid #36364a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: #00d4ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    left: 10px;
}

/* Buttons */
QPushButton {
    background-color: #2e2e3c;
    border: 1px solid #444458;
    color: #f0f0f8;
    padding: 6px 14px;
    border-radius: 5px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #3a3a4e;
    border-color: #5c5c78;
}
QPushButton:pressed {
    background-color: #1e1e28;
}
QPushButton:disabled {
    background-color: #202028;
    color: #606070;
    border-color: #2a2a38;
}

/* Special Action Buttons */
QPushButton#startBtn {
    background-color: #1b5e20;
    border: 1px solid #2e7d32;
    color: #ffffff;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#startBtn:hover {
    background-color: #2e7d32;
    border-color: #43a047;
}

QPushButton#pauseBtn {
    background-color: #f57f17;
    border: 1px solid #fbc02d;
    color: #000000;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#pauseBtn:hover {
    background-color: #fbc02d;
}

QPushButton#stopBtn {
    background-color: #b71c1c;
    border: 1px solid #d32f2f;
    color: #ffffff;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#stopBtn:hover {
    background-color: #d32f2f;
}

/* Tables & Lists */
QTableWidget, QTableView {
    background-color: #1e1e26;
    alternate-background-color: #242430;
    color: #e0e0f0;
    border: 1px solid #36364a;
    gridline-color: #2c2c3c;
    selection-background-color: #006699;
    selection-color: #ffffff;
    border-radius: 4px;
}
QHeaderView::section {
    background-color: #2a2a36;
    color: #c0c0d8;
    border: 1px solid #363648;
    padding: 4px 6px;
    font-weight: bold;
}

/* Inputs & Spinners */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #22222c;
    border: 1px solid #3a3a4e;
    color: #ffffff;
    padding: 4px 8px;
    border-radius: 4px;
    selection-background-color: #0088cc;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #00b0ff;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #181820;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3c3c50;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #545470;
}

QScrollBar:horizontal {
    border: none;
    background: #181820;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #3c3c50;
    min-width: 20px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #545470;
}

/* Status Bar */
QStatusBar {
    background-color: #1e1e26;
    color: #a0a0b8;
    border-top: 1px solid #2e2e3e;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid #36364a;
    background-color: #20202a;
}
QTabBar::tab {
    background-color: #262634;
    color: #b0b0c8;
    border: 1px solid #36364a;
    border-bottom: none;
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background-color: #20202a;
    color: #00d4ff;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background-color: #303042;
}

/* Sliders */
QSlider::groove:horizontal {
    height: 6px;
    background: #343446;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #00b0ff;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 1px solid #00b0ff;
    width: 14px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 7px;
}

/* Progress Bar */
QProgressBar {
    border: 1px solid #36364a;
    border-radius: 4px;
    text-align: center;
    color: #ffffff;
    background-color: #1e1e28;
    font-weight: bold;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0088cc, stop:1 #00e5ff);
    border-radius: 3px;
}
"""

def apply_dark_theme(app):
    """Applies the LaserForge dark stylesheet to the QApplication."""
    app.setStyleSheet(DARK_THEME_QSS)

