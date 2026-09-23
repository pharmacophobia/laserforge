"""
LaserForge AI Assistant & Copilot Panel.
PyQt6 dock panel providing an interactive chat interface for:
- Bed alignment and gantry skew diagnostics
- Camera configuration and lens distortion review
- Natural language CAD object manipulation
- One-click quick action chips (Diagnose Bed, Center Artwork, Place on Stock, Fit to Bed)
"""

import html
from typing import Optional, Dict, Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt6.QtGui import QFont, QTextCursor, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QComboBox, QGroupBox, QFormLayout,
    QCheckBox, QSplitter, QFrame, QScrollArea
)

from laserforge.config import MachineSettings
from laserforge.core.ai_assistant import AIAssistantEngine
from laserforge.core.camera_engine import CameraEngine
from laserforge.core.auto_calibration import AutoCalibrationEngine


class AIAssistantWorker(QThread):
    """Background worker for non-blocking AI API calls and tool execution."""
    tool_executed = pyqtSignal(str, dict, dict)  # tool_name, args, result
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, engine: AIAssistantEngine, prompt: str):
        super().__init__()
        self.engine = engine
        self.prompt = prompt

    def run(self):
        try:
            def on_tool(name: str, args: Dict[str, Any], res: Dict[str, Any]):
                self.tool_executed.emit(name, args, res)

            response = self.engine.send_prompt(self.prompt, tool_callback=on_tool)
            self.response_ready.emit(response)
        except Exception as e:
            self.error_occurred.emit(str(e))


class AIAssistantPanel(QWidget):
    """Interactive AI Copilot panel for laser operations and CAD manipulation."""

    def __init__(
        self,
        settings: Optional[MachineSettings] = None,
        scene: Optional[Any] = None,
        camera_engine: Optional[CameraEngine] = None,
        parent=None
    ):
        super().__init__(parent)
        self.settings = settings or MachineSettings()
        self.scene = scene
        self.camera_engine = camera_engine

        self.engine = AIAssistantEngine(
            settings=self.settings,
            scene=self.scene,
            camera_engine=self.camera_engine
        )
        self.current_worker: Optional[AIAssistantWorker] = None

        self._init_ui()
        self._append_system_banner()

    def set_scene(self, scene: Any):
        """Updates scene reference if scene changes."""
        self.scene = scene
        self.engine.scene = scene

    def set_camera_engine(self, cam_engine: CameraEngine):
        """Updates camera engine reference."""
        self.camera_engine = cam_engine
        self.engine.camera_engine = cam_engine

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Header bar
        header = QHBoxLayout()
        title_label = QLabel("🤖 <b>DeepSeek AI Copilot</b>")
        title_label.setStyleSheet("color: #00e5ff; font-size: 13px;")
        header.addWidget(title_label)

        header.addStretch(1)

        self.status_badge = QLabel("Ready")
        self.status_badge.setStyleSheet(
            "background-color: #2e7d32; color: #ffffff; padding: 2px 8px; "
            "border-radius: 9px; font-size: 10px; font-weight: bold;"
        )
        header.addWidget(self.status_badge)

        self.btn_settings_toggle = QPushButton("⚙ Settings")
        self.btn_settings_toggle.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        self.btn_settings_toggle.setCheckable(True)
        self.btn_settings_toggle.clicked.connect(self._toggle_settings)
        header.addWidget(self.btn_settings_toggle)

        layout.addLayout(header)

        # Settings Drawer (Collapsible)
        self.settings_group = QGroupBox("AI Engine & Endpoint Configuration")
        self.settings_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #444; margin-top: 6px; padding-top: 8px; border-radius: 4px; background: #222; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #00e5ff; }"
        )
        self.settings_group.setVisible(False)
        s_layout = QFormLayout(self.settings_group)
        s_layout.setContentsMargins(8, 8, 8, 8)
        s_layout.setSpacing(6)

        self.combo_provider = QComboBox()
        self.combo_provider.addItems([
            "DeepSeek API (Cloud)",
            "Ollama (Local deepseek-r1)",
            "LM Studio (Local endpoint)",
            "Custom OpenAI Endpoint"
        ])
        curr_provider = getattr(self.settings, "ai_provider", "deepseek").lower()
        if curr_provider == "ollama":
            self.combo_provider.setCurrentIndex(1)
        elif curr_provider == "lmstudio":
            self.combo_provider.setCurrentIndex(2)
        elif curr_provider == "custom":
            self.combo_provider.setCurrentIndex(3)
        else:
            self.combo_provider.setCurrentIndex(0)
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        s_layout.addRow("Provider:", self.combo_provider)

        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_api_key.setPlaceholderText("Enter DeepSeek API Key (sk-...) or leave blank for local")
        self.edit_api_key.setText(getattr(self.settings, "ai_api_key", ""))
        s_layout.addRow("API Key:", self.edit_api_key)

        self.edit_api_base = QLineEdit()
        self.edit_api_base.setText(getattr(self.settings, "ai_api_base", "https://api.deepseek.com/v1"))
        s_layout.addRow("Base URL:", self.edit_api_base)

        self.edit_model = QLineEdit()
        self.edit_model.setText(getattr(self.settings, "ai_model", "deepseek-chat"))
        s_layout.addRow("Model:", self.edit_model)

        btn_save_settings = QPushButton("💾 Save AI Settings")
        btn_save_settings.setStyleSheet("background-color: #0288d1; color: white; padding: 4px; font-weight: bold;")
        btn_save_settings.clicked.connect(self._save_settings)
        s_layout.addRow("", btn_save_settings)

        layout.addWidget(self.settings_group)

        # Quick Action Chips (Two neat rows for speed, alignment, and CAD)
        chips_box = QVBoxLayout()
        chips_box.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        btn_chip_speed = QPushButton("⚡ Optimize Speed")
        btn_chip_speed.setStyleSheet("background-color: #f57f17; color: #ffffff; font-weight: bold;")
        btn_chip_speed.setToolTip("Analyze project for speed bottlenecks (DPI overkill, scan orientation, white-space skip)")
        btn_chip_speed.clicked.connect(lambda: self.trigger_quick_command("analyze engraving speed bottlenecks and recommend optimizations"))
        row1.addWidget(btn_chip_speed)

        btn_chip_mat = QPushButton("🪵 Material Preset")
        btn_chip_mat.setToolTip("Look up calibrated speed and power for birch, basswood, slate, acrylic, etc.")
        btn_chip_mat.clicked.connect(lambda: self.trigger_quick_command("suggest material preset for birch plywood engraving"))
        row1.addWidget(btn_chip_mat)

        btn_chip_diag = QPushButton("📐 Diagnose Bed")
        btn_chip_diag.setToolTip("Inspect gantry skew, leveling, and reprojection error telemetry")
        btn_chip_diag.clicked.connect(lambda: self.trigger_quick_command("diagnose bed alignment and gantry skew"))
        row1.addWidget(btn_chip_diag)
        chips_box.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(4)
        btn_chip_cam = QPushButton("📷 Camera")
        btn_chip_cam.setToolTip("Check overhead camera resolution, lens distortion, and homography alignment")
        btn_chip_cam.clicked.connect(lambda: self.trigger_quick_command("check camera configuration and status"))
        row2.addWidget(btn_chip_cam)

        btn_chip_center = QPushButton("🎯 Center Bed")
        btn_chip_center.setToolTip("Center selected objects on the laser bed")
        btn_chip_center.clicked.connect(lambda: self.trigger_quick_command("center selected objects on bed"))
        row2.addWidget(btn_chip_center)

        btn_chip_stock = QPushButton("🪵 Place Stock")
        btn_chip_stock.setToolTip("Detect material on bed view and position artwork on it")
        btn_chip_stock.clicked.connect(lambda: self.trigger_quick_command("detect material on bed and place artwork inside it"))
        row2.addWidget(btn_chip_stock)

        btn_chip_fit = QPushButton("📐 Fit Bed")
        btn_chip_fit.setToolTip("Scale and center artwork within bed limits")
        btn_chip_fit.clicked.connect(lambda: self.trigger_quick_command("fit artwork to laser bed with 10mm margin"))
        row2.addWidget(btn_chip_fit)
        chips_box.addLayout(row2)

        layout.addLayout(chips_box)

        # Chat display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.document().setMaximumBlockCount(1500)
        self.chat_display.setStyleSheet(
            "background-color: #141414; color: #eceff1; border: 1px solid #333333; "
            "border-radius: 4px; padding: 6px; font-size: 11px; line-height: 1.4;"
        )
        layout.addWidget(self.chat_display, 1)

        # Input Row
        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Ask DeepSeek AI (e.g. 'how to engrave faster?', 'preset for slate', 'move right 20mm')...")
        self.input_edit.returnPressed.connect(self._send_user_prompt)
        input_row.addWidget(self.input_edit, 1)

        self.btn_send = QPushButton("Send")
        self.btn_send.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 4px 10px;")
        self.btn_send.clicked.connect(self._send_user_prompt)
        input_row.addWidget(self.btn_send)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setStyleSheet("padding: 4px 8px; font-size: 10px;")
        self.btn_clear.clicked.connect(self._clear_chat)
        input_row.addWidget(self.btn_clear)

        layout.addLayout(input_row)

    def _append_system_banner(self):
        """Displays initial introduction banner in chat."""
        banner_html = (
            "<div style='margin-bottom: 8px; padding: 6px; background-color: #1a2733; "
            "border-left: 3px solid #00e5ff; border-radius: 3px; font-size: 11px;'>"
            "<b style='color: #00e5ff;'>LaserForge DeepSeek Copilot Initialized</b><br>"
            "Ready to assist with:<br>"
            "• <b>⚡ Engraving Speed Optimization</b>: slash job times by 30-70% via DPI, orientation & G0 skip.<br>"
            "• <b>🪵 Calibrated Material Presets</b>: instant speed/power settings from tested database.<br>"
            "• <b>📐 Bed Alignment & Skew Diagnostics</b>: gantry racking & leveling recommendations.<br>"
            "• <b>📷 Camera Telemetry</b>: lens calibration & bed homography status.<br>"
            "• <b>🎨 CAD Manipulation</b>: move, rotate, scale, align, or fit artwork on the bed."
            "</div>"
        )
        self.chat_display.append(banner_html)

    def _toggle_settings(self):
        visible = self.btn_settings_toggle.isChecked()
        self.settings_group.setVisible(visible)

    def _on_provider_changed(self, idx: int):
        if idx == 0:  # DeepSeek
            self.edit_api_base.setText("https://api.deepseek.com/v1")
            self.edit_model.setText("deepseek-chat")
            self.settings.ai_provider = "deepseek"
        elif idx == 1:  # Ollama
            self.edit_api_base.setText("http://localhost:11434/v1")
            self.edit_model.setText("deepseek-r1:latest")
            self.settings.ai_provider = "ollama"
        elif idx == 2:  # LM Studio
            self.edit_api_base.setText("http://localhost:1234/v1")
            self.edit_model.setText("deepseek-r1")
            self.settings.ai_provider = "lmstudio"
        else:  # Custom
            self.settings.ai_provider = "custom"

    def _save_settings(self):
        self.settings.ai_api_key = self.edit_api_key.text().strip()
        self.settings.ai_api_base = self.edit_api_base.text().strip()
        self.settings.ai_model = self.edit_model.text().strip()
        self.btn_settings_toggle.setChecked(False)
        self.settings_group.setVisible(False)
        self._append_message("System", "AI configuration updated successfully.", is_system=True)

    def trigger_quick_command(self, command: str):
        """Triggers a command as if typed by user."""
        self.input_edit.setText(command)
        self._send_user_prompt()

    def _send_user_prompt(self):
        text = self.input_edit.text().strip()
        if not text:
            return

        if self.current_worker and self.current_worker.isRunning():
            self._append_message("System", "AI is currently thinking. Please wait...", is_system=True)
            return

        self.input_edit.clear()
        self._append_message("Operator", text, is_user=True)
        self._set_status("Thinking...", bg_color="#f57c00")

        self.current_worker = AIAssistantWorker(self.engine, text)
        self.current_worker.tool_executed.connect(self._on_tool_executed)
        self.current_worker.response_ready.connect(self._on_response_ready)
        self.current_worker.error_occurred.connect(self._on_error_occurred)
        self.current_worker.start()

    @pyqtSlot(str, dict, dict)
    def _on_tool_executed(self, tool_name: str, args: Dict[str, Any], res: Dict[str, Any]):
        msg = res.get("message", "Executed")
        badge_html = (
            f"<div style='margin: 4px 0; color: #80cbc4; font-size: 10px; font-family: monospace;'>"
            f"⚙ [Tool: <b>{html.escape(tool_name)}</b>] → {html.escape(str(msg))}"
            f"</div>"
        )
        self.chat_display.append(badge_html)

    @pyqtSlot(str)
    def _on_response_ready(self, response_text: str):
        self._set_status("Ready", bg_color="#2e7d32")
        self._append_message("DeepSeek Copilot", response_text, is_ai=True)

    @pyqtSlot(str)
    def _on_error_occurred(self, err_text: str):
        self._set_status("Error", bg_color="#c62828")
        self._append_message("AI Error", err_text, is_system=True)

    def _append_message(self, sender: str, text: str, is_user: bool = False, is_ai: bool = False, is_system: bool = False):
        formatted_text = html.escape(text).replace("\n", "<br>")

        # Simple markdown bold & bullet formatting
        import re
        formatted_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', formatted_text)
        formatted_text = re.sub(r'^\* (.*?)(?=<br>|$)', r'• \1', formatted_text, flags=re.MULTILINE)

        if is_user:
            bg_color = "#1e374d"
            sender_color = "#4fc3f7"
        elif is_ai:
            bg_color = "#1c2621"
            sender_color = "#69f0ae"
        else:
            bg_color = "#2a1e1e"
            sender_color = "#ff8a80"

        msg_html = (
            f"<div style='margin: 4px 0; padding: 6px 8px; background-color: {bg_color}; "
            f"border-radius: 4px;'>"
            f"<b style='color: {sender_color}; font-size: 11px;'>{html.escape(sender)}:</b><br>"
            f"<div style='margin-top: 2px; color: #eceff1; font-size: 11px;'>{formatted_text}</div>"
            f"</div>"
        )
        self.chat_display.append(msg_html)
        self.chat_display.moveCursor(QTextCursor.MoveOperation.End)

    def _set_status(self, text: str, bg_color: str):
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(
            f"background-color: {bg_color}; color: #ffffff; padding: 2px 8px; "
            f"border-radius: 9px; font-size: 10px; font-weight: bold;"
        )

    def _clear_chat(self):
        self.chat_display.clear()
        self._append_system_banner()
