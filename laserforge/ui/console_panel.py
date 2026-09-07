"""
LaserForge Console Panel.
Provides a real-time serial terminal log with color-coded TX, RX, and error messages,
interactive command prompt with command history, and clear log actions.
"""

from typing import List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QCheckBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor, QColor

from laserforge.core.serial_controller import SerialController


class ConsolePanel(QWidget):
    def __init__(self, serial_ctrl: SerialController, parent=None):
        super().__init__(parent)
        self.serial_ctrl = serial_ctrl

        self.history: List[str] = []
        self.history_idx = 0

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Output Text View
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        font = QFont("monospace", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet(
            "background-color: #1a1a1a; color: #cfd8dc; "
            "border: 1px solid #333333; border-radius: 3px;"
        )
        layout.addWidget(self.text_edit, 1)

        # Bottom Input and Control Row
        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Type G-code or GRBL command (e.g. $$, $#, ?)...")
        self.input_edit.setFont(font)
        self.input_edit.returnPressed.connect(self._send_input)
        input_row.addWidget(self.input_edit, 1)

        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self._send_input)
        input_row.addWidget(self.btn_send)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.text_edit.clear)
        input_row.addWidget(self.btn_clear)

        self.autoscroll_cb = QCheckBox("Autoscroll")
        self.autoscroll_cb.setChecked(True)
        input_row.addWidget(self.autoscroll_cb)

        layout.addLayout(input_row)

    def _connect_signals(self):
        self.serial_ctrl.log_received.connect(self.append_log)

    def append_log(self, direction: str, text: str):
        """Formats and appends colored text to terminal."""
        # Clean string
        text = text.rstrip("\r\n")

        # Skip periodic ? status queries to avoid spamming the log
        if text == "?" or text.startswith("<"):
            return

        if direction == "tx":
            color = "#40c4ff"  # Light blue / Cyan
            prefix = ">> "
        elif direction == "err":
            color = "#ff5252"  # Red
            prefix = "!! "
        else:
            color = "#b9f6ca" if text.strip() == "ok" else "#eceff1" # Green for ok, white-ish for others
            prefix = "<< "

        html = f'<span style="color: {color};">{prefix}{text}</span><br>'
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.text_edit.insertHtml(html)

        if self.autoscroll_cb.isChecked():
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _send_input(self):
        cmd = self.input_edit.text().strip()
        if not cmd:
            return

        self.history.append(cmd)
        self.history_idx = len(self.history)
        self.input_edit.clear()

        self.serial_ctrl.send_command(cmd)

    def keyPressEvent(self, event):
        """Allows Up/Down arrow command history cycling when focused in input."""
        if self.input_edit.hasFocus():
            if event.key() == Qt.Key.Key_Up:
                if self.history and self.history_idx > 0:
                    self.history_idx -= 1
                    self.input_edit.setText(self.history[self.history_idx])
                return
            elif event.key() == Qt.Key.Key_Down:
                if self.history and self.history_idx < len(self.history) - 1:
                    self.history_idx += 1
                    self.input_edit.setText(self.history[self.history_idx])
                else:
                    self.history_idx = len(self.history)
                    self.input_edit.clear()
                return

        super().keyPressEvent(event)
