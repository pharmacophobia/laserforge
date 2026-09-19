"""
LaserForge In-App Feedback & Crash Reporting Dialogs.
Allows beta testers and laser operators to report bugs, send feedback,
and submit diagnostic crash reports directly to the creator.
"""

import os
import sys
import io
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox, QPushButton,
    QMessageBox, QFileDialog, QGroupBox, QTabWidget, QApplication
)
from PyQt6.QtCore import Qt, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QColor, QFont, QPixmap

from laserforge.core.telemetry import (
    FeedbackReport, collect_system_diagnostics, sanitize_text
)


class FeedbackDialog(QDialog):
    """
    User-facing feedback, suggestion, and bug reporting studio.
    Allows beta testers to easily message the creator with system logs and canvas screenshots.
    """

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("Message the Creator & Report Issues 💬")
        self.resize(680, 580)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; font-family: sans-serif; }
            QGroupBox { border: 1px solid #334155; border-radius: 6px; margin-top: 10px; font-weight: bold; color: #38bdf8; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #cbd5e1; font-size: 12px; }
            QLineEdit, QTextEdit, QComboBox { background-color: #1e293b; border: 1px solid #475569; border-radius: 4px; color: #f8fafc; padding: 6px; font-size: 12px; }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #38bdf8; }
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton#btnSecondary { background-color: #334155; color: #cbd5e1; }
            QPushButton#btnSecondary:hover { background-color: #475569; color: #ffffff; }
        """)

        self.screenshot_bytes: Optional[bytes] = None
        self._init_ui()
        self._gather_context()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header Title
        lbl_title = QLabel("<h2>Send Feedback or Report an Issue</h2>")
        lbl_title.setStyleSheet("color: #38bdf8; margin-bottom: 0px;")
        lbl_subtitle = QLabel("Your feedback goes directly to the creator to help improve LaserForge during beta.")
        lbl_subtitle.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_subtitle)

        # Form Group
        form_group = QGroupBox("Report Details")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(8)

        # Category
        self.combo_category = QComboBox()
        self.combo_category.addItems([
            "🐛 Bug Report (Something is broken or crashing)",
            "⚡ Hardware / Laser Incompatibility (GRBL, Ruida, or connection issue)",
            "💡 Feature Request / Improvement Idea",
            "⭐ General Feedback / User Experience",
            "❓ Question / Help Needed"
        ])
        form_layout.addRow("Category:", self.combo_category)

        # Contact Info
        self.txt_contact = QLineEdit()
        self.txt_contact.setPlaceholderText("your_email@example.com or Discord username (optional, for follow-up)")
        form_layout.addRow("Your Contact:", self.txt_contact)

        # Subject
        self.txt_subject = QLineEdit()
        self.txt_subject.setPlaceholderText("Brief summary of the issue or idea")
        form_layout.addRow("Subject:", self.txt_subject)

        # Message / Details
        self.txt_message = QTextEdit()
        self.txt_message.setPlaceholderText(
            "Please describe what you were trying to do, what happened, and what you expected to see.\n"
            "If reporting a bug, what are the steps to reproduce it?"
        )
        self.txt_message.setMinimumHeight(120)
        form_layout.addRow("Description:", self.txt_message)

        layout.addWidget(form_group)

        # Diagnostics & Attachments Group
        attach_group = QGroupBox("Privacy-Safe Diagnostics & Context")
        attach_layout = QVBoxLayout(attach_group)
        attach_layout.setSpacing(6)

        self.chk_include_diag = QCheckBox("Include anonymized system hardware & OS diagnostics (CPU, GPU, Qt, bed dimensions)")
        self.chk_include_diag.setChecked(True)
        attach_layout.addWidget(self.chk_include_diag)

        self.chk_include_logs = QCheckBox("Include recent machine communications log (last 50 GRBL G-code/status entries)")
        self.chk_include_logs.setChecked(True)
        attach_layout.addWidget(self.chk_include_logs)

        self.chk_include_screenshot = QCheckBox("Attach current workspace canvas screenshot")
        self.chk_include_screenshot.setChecked(True)
        attach_layout.addWidget(self.chk_include_screenshot)

        # Expandable diagnostics inspection
        self.btn_inspect_diag = QPushButton("🔍 Inspect What Data Will Be Sent (Full Transparency)")
        self.btn_inspect_diag.setObjectName("btnSecondary")
        self.btn_inspect_diag.clicked.connect(self._toggle_diagnostics_view)
        attach_layout.addWidget(self.btn_inspect_diag)

        self.txt_diagnostics_preview = QTextEdit()
        self.txt_diagnostics_preview.setReadOnly(True)
        self.txt_diagnostics_preview.setStyleSheet("font-family: monospace; font-size: 11px; background-color: #090d16;")
        self.txt_diagnostics_preview.setMaximumHeight(140)
        self.txt_diagnostics_preview.hide()
        attach_layout.addWidget(self.txt_diagnostics_preview)

        layout.addWidget(attach_group)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_copy_markdown = QPushButton("📋 Copy to Clipboard (Markdown)")
        self.btn_copy_markdown.setObjectName("btnSecondary")
        self.btn_copy_markdown.setToolTip("Copies formatted report ready to paste into Discord, GitHub, or Reddit")
        self.btn_copy_markdown.clicked.connect(self._copy_markdown)
        btn_layout.addWidget(self.btn_copy_markdown)

        self.btn_export_zip = QPushButton("💾 Export Diagnostic Bundle (.zip)")
        self.btn_export_zip.setObjectName("btnSecondary")
        self.btn_export_zip.setToolTip("Saves report, screenshot, and logs into a zip file to attach in email or Discord")
        self.btn_export_zip.clicked.connect(self._export_zip)
        btn_layout.addWidget(self.btn_export_zip)

        btn_layout.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btnSecondary")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        self.btn_send = QPushButton("🚀 Send Feedback Directly")
        self.btn_send.setToolTip("Transmits report directly to creator via configured webhook or opens email client")
        self.btn_send.clicked.connect(self._send_report)
        btn_layout.addWidget(self.btn_send)

        layout.addLayout(btn_layout)

    def _gather_context(self):
        """Extracts current settings, serial logs, and canvas screenshot from MainWindow."""
        settings = getattr(self.main_window, "settings", None)
        serial_ctrl = getattr(self.main_window, "serial_ctrl", None)
        self.diagnostics = collect_system_diagnostics(settings=settings, serial_ctrl=serial_ctrl)

        # Gather recent serial console logs if available
        self.recent_logs = []
        if self.main_window and hasattr(self.main_window, "console_panel"):
            cp = self.main_window.console_panel
            if hasattr(cp, "console_output"):
                text = cp.console_output.toPlainText()
                lines = [line for line in text.splitlines() if line.strip()]
                self.recent_logs = lines[-50:]

        # Grab screenshot of canvas if available
        if self.main_window and hasattr(self.main_window, "canvas_widget"):
            try:
                pixmap = self.main_window.canvas_widget.grab()
                buffer = QByteArray()
                qbuffer = QBuffer(buffer)
                qbuffer.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(qbuffer, "PNG")
                self.screenshot_bytes = bytes(buffer.data())
            except Exception:
                self.screenshot_bytes = None

    def _build_report(self) -> FeedbackReport:
        cat_text = self.combo_category.currentText().split(" ")[1] if " " in self.combo_category.currentText() else self.combo_category.currentText()
        subject = self.txt_subject.text().strip() or f"Beta Feedback ({cat_text})"
        message = self.txt_message.toPlainText().strip()
        contact = self.txt_contact.text().strip()

        diag = self.diagnostics if self.chk_include_diag.isChecked() else {}
        logs = self.recent_logs if self.chk_include_logs.isChecked() else []

        return FeedbackReport(
            category=cat_text,
            subject=subject,
            message=message,
            contact_info=contact,
            diagnostics=diag,
            recent_logs=logs
        )

    def _toggle_diagnostics_view(self):
        if self.txt_diagnostics_preview.isVisible():
            self.txt_diagnostics_preview.hide()
            self.btn_inspect_diag.setText("🔍 Inspect What Data Will Be Sent (Full Transparency)")
        else:
            rep = self._build_report()
            self.txt_diagnostics_preview.setPlainText(rep.to_markdown())
            self.txt_diagnostics_preview.show()
            self.btn_inspect_diag.setText("▲ Hide Data Preview")

    def _copy_markdown(self):
        rep = self._build_report()
        md = rep.to_markdown()
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(md)
            QMessageBox.information(
                self, "Report Copied",
                "Full issue report and diagnostics copied to clipboard!\n\n"
                "You can now paste (Ctrl+V) directly into GitHub Issues, Discord, or an email."
            )

    def _export_zip(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Diagnostic Bundle", "laserforge_diagnostic_report.zip",
            "ZIP Archives (*.zip);;All Files (*)"
        )
        if not path:
            return

        rep = self._build_report()
        screenshot = self.screenshot_bytes if self.chk_include_screenshot.isChecked() else None
        try:
            rep.export_bundle(path, screenshot_bytes=screenshot)
            QMessageBox.information(
                self, "Exported Successfully",
                f"Diagnostic report bundle saved to:\n{path}\n\n"
                "You can attach this file in Discord or email it to the creator."
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to save zip bundle: {e}")

    def _send_report(self):
        msg = self.txt_message.toPlainText().strip()
        if not msg:
            QMessageBox.warning(self, "Empty Message", "Please enter a brief description before submitting.")
            return

        rep = self._build_report()

        # Check for configured webhook URL in environment or settings
        webhook_url = os.environ.get("LASERFORGE_FEEDBACK_WEBHOOK", "")
        if not webhook_url and self.main_window and hasattr(self.main_window, "settings"):
            webhook_url = getattr(self.main_window.settings, "feedback_webhook_url", "")

        if webhook_url:
            self.btn_send.setEnabled(False)
            self.btn_send.setText("Transmitting...")
            QApplication.processEvents()

            success, status_msg = rep.send_via_webhook(webhook_url)
            self.btn_send.setEnabled(True)
            self.btn_send.setText("🚀 Send Feedback Directly")

            if success:
                QMessageBox.information(
                    self, "Feedback Received!",
                    "<b>Thank you!</b> Your feedback and diagnostics have been delivered directly to the creator.\n"
                    "We appreciate you helping beta-test LaserForge!"
                )
                self.accept()
                return
            else:
                QMessageBox.warning(
                    self, "Webhook Delivery Notice",
                    f"Direct webhook delivery could not be completed ({status_msg}).\n\n"
                    "We will open your default email client with the report pre-filled instead."
                )

        # Fallback to mailto link or clipboard
        import urllib.parse
        recipient = "creator@laserforge.org"
        if self.main_window and hasattr(self.main_window, "settings"):
            recipient = getattr(self.main_window.settings, "developer_contact_email", recipient)

        subject = urllib.parse.quote(f"LaserForge Beta: [{rep.category}] {rep.subject}")
        body = urllib.parse.quote(rep.to_markdown()[:1800])
        mailto_url = f"mailto:{recipient}?subject={subject}&body={body}"

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(mailto_url))

        QMessageBox.information(
            self, "Email Prepared",
            f"An email to <b>{recipient}</b> has been prepared with your report.\n\n"
            "If your email client did not open automatically, you can use 'Copy to Clipboard' "
            "to paste the details into your preferred message app."
        )
        self.accept()


class CrashReportDialog(QDialog):
    """
    Emergency dialog displayed when an uncaught exception is intercepted by CrashManager.
    Explains the error, provides clean diagnostics, and lets the user submit the trace.
    """

    def __init__(
        self,
        exc_type: str,
        exc_value: str,
        stack_trace: str,
        diagnostics: Dict[str, Any],
        recent_logs: List[str],
        parent=None
    ):
        super().__init__(parent)
        self.exc_type = exc_type
        self.exc_value = exc_value
        self.stack_trace = stack_trace
        self.diagnostics = diagnostics
        self.recent_logs = recent_logs

        self.setWindowTitle("LaserForge — Unexpected Issue Intercepted ⚠️")
        self.resize(640, 480)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; }
            QLabel { color: #cbd5e1; font-size: 12px; }
            QTextEdit { background-color: #090d16; border: 1px solid #334155; border-radius: 4px; color: #f43f5e; font-family: monospace; font-size: 11px; }
            QPushButton { background-color: #e11d48; color: #ffffff; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #f43f5e; }
            QPushButton#btnSecondary { background-color: #334155; color: #cbd5e1; }
            QPushButton#btnSecondary:hover { background-color: #475569; color: #ffffff; }
        """)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        lbl_header = QLabel("<h3>LaserForge encountered an unexpected error</h3>")
        lbl_header.setStyleSheet("color: #fb7185; margin: 0;")
        layout.addWidget(lbl_header)

        lbl_desc = QLabel(
            "LaserForge captured this issue before it crashed your machine. "
            "A crash dump has been saved to <code>~/.laserforge/crashes/</code>. "
            "Please copy or submit this report so we can fix it immediately."
        )
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        txt_trace = QTextEdit()
        txt_trace.setReadOnly(True)
        txt_trace.setPlainText(f"{self.exc_type}: {self.exc_value}\n\n{sanitize_text(self.stack_trace)}")
        layout.addWidget(txt_trace)

        btn_layout = QHBoxLayout()
        btn_copy = QPushButton("📋 Copy Crash Report to Clipboard")
        btn_copy.setObjectName("btnSecondary")
        btn_copy.clicked.connect(self._copy_crash)
        btn_layout.addWidget(btn_copy)

        btn_save = QPushButton("💾 Save Diagnostics File")
        btn_save.setObjectName("btnSecondary")
        btn_save.clicked.connect(self._save_crash)
        btn_layout.addWidget(btn_save)

        btn_layout.addStretch(1)

        btn_close = QPushButton("Dismiss")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _copy_crash(self):
        report = FeedbackReport(
            category="Crash Report",
            subject=f"Crash: {self.exc_type} - {self.exc_value}",
            message="Application encountered an unhandled exception.",
            diagnostics=self.diagnostics,
            recent_logs=self.recent_logs,
            stack_trace=self.stack_trace
        )
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(report.to_markdown())
            QMessageBox.information(self, "Copied", "Crash report copied to clipboard!")

    def _save_crash(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Crash Log", "laserforge_crash.md", "Markdown (*.md);;All Files (*)"
        )
        if not path:
            return
        report = FeedbackReport(
            category="Crash Report",
            subject=f"Crash: {self.exc_type} - {self.exc_value}",
            message="Application encountered an unhandled exception.",
            diagnostics=self.diagnostics,
            recent_logs=self.recent_logs,
            stack_trace=self.stack_trace
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(report.to_markdown())
            QMessageBox.information(self, "Saved", f"Crash report saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to write file: {e}")
