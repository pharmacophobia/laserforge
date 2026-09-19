"""
LaserForge UI Utilities.
Shared helper functions for icon generation and Qt widget utilities.
"""
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen


def create_tool_icon(text: str, bg_color: str = "#2b2b36", fg_color: str = "#00e5ff") -> QIcon:
    """Generates a high-contrast procedural icon for toolbar actions."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(bg_color))
    painter.setPen(QPen(QColor("#3d3d4d"), 1))
    painter.drawRoundedRect(2, 2, 28, 28, 4, 4)
    painter.setPen(QColor(fg_color))
    font = QFont("sans-serif", 12, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pix)
