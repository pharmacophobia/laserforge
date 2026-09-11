"""
LaserForge G-Code Pre-Flight Validation Dialog.
Presents validation results, line-by-line errors and warnings, automated repairs,
interactive toolpath simulation, and job safety metrics before burning.
"""

from typing import Optional, List, Any
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QTextEdit, QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from laserforge.core.gcode_validator import ValidationReport, ValidationIssue


class ValidationDialog(QDialog):
    """
    Dialog displaying the results of the pre-flight GRBL G-code validation check,
    automatic repair actions, and interactive toolpath simulation.
    """

    def __init__(
        self,
        report: ValidationReport,
        parent=None,
        allow_proceed: bool = True,
        repaired_gcode: Optional[str] = None,
        repairs_applied: Optional[List[str]] = None,
        job_result: Optional[Any] = None,
        settings: Optional[Any] = None
    ):
        super().__init__(parent)
        self.report = report
        self.repaired_gcode = repaired_gcode
        self.repairs_applied = repairs_applied or []
        self.job_result = job_result
        self.settings = settings or getattr(parent, "settings", None)
        self.final_gcode = repaired_gcode if (repaired_gcode and self.repairs_applied) else None

        # Allow proceed if no errors or if successfully repaired
        has_active_errors = report.has_errors and (not bool(self.repairs_applied))
        self.allow_proceed = allow_proceed and (not has_active_errors)
        self.proceed_chosen = False

        self.setWindowTitle("LaserForge - G-Code Simulation, Safety Check & Auto-Repair")
        self.resize(850, 580)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 1. Header Banner
        header = QFrame()
        header_l = QVBoxLayout(header)
        header_l.setContentsMargins(14, 10, 14, 10)

        if self.repairs_applied:
            header.setStyleSheet("background-color: #1a3a4b; border-radius: 6px; border: 1px solid #00b0ff;")
            title_text = f"🛠️ Code Simulated & Repaired: {len(self.repairs_applied)} Issue(s) Fixed"
            desc_text = (
                "The pre-flight simulator identified syntax, boundary, or hardware safety issues in the code. "
                "LaserForge automatically repaired and re-validated the program to ensure 100% GRBL compliance "
                "before burning."
            )
        elif self.report.has_errors:
            header.setStyleSheet("background-color: #5c1d1d; border-radius: 6px; border: 1px solid #e53935;")
            title_text = f"❌ G-Code Validation Failed: {len(self.report.errors)} Error(s) Found"
            desc_text = (
                "The G-code program contains commands or coordinates that violate GRBL 1.1 "
                "specifications or physical machine travel boundaries."
            )
        elif self.report.has_warnings:
            header.setStyleSheet("background-color: #5c431d; border-radius: 6px; border: 1px solid #ffa000;")
            title_text = f"⚠️ G-Code Validation Warnings: {len(self.report.warnings)} Warning(s)"
            desc_text = (
                "The program is valid, but potential issues were detected (such as rapid burns "
                "or power level settings). Please review before running."
            )
        else:
            header.setStyleSheet("background-color: #1b4d2e; border-radius: 6px; border: 1px solid #43a047;")
            title_text = "✅ G-Code Validation Passed: 100% GRBL 1.1 Compliant"
            desc_text = "Simulation verified zero syntax errors, out-of-bounds moves, or laser safety hazards."

        lbl_title = QLabel(f"<h3 style='margin:0;'>{title_text}</h3>")
        header_l.addWidget(lbl_title)

        lbl_desc = QLabel(desc_text)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #e0e0e0; font-size: 11px;")
        header_l.addWidget(lbl_desc)

        layout.addWidget(header)

        # 2. Metrics Card
        metrics_frame = QFrame()
        metrics_frame.setStyleSheet("background-color: #24242e; border-radius: 6px; padding: 6px;")
        m_layout = QHBoxLayout(metrics_frame)
        m_layout.setContentsMargins(8, 6, 8, 6)

        min_x, min_y, max_x, max_y = self.report.bounding_box
        bounds_str = f"X: [{min_x:.1f}, {max_x:.1f}] mm | Y: [{min_y:.1f}, {max_y:.1f}] mm"

        m_layout.addWidget(QLabel(f"<b>Lines:</b> {self.report.total_lines}"))
        m_layout.addWidget(QLabel(f"<b>Motion Moves:</b> {self.report.motion_count}"))
        m_layout.addWidget(QLabel(f"<b>Extents:</b> {bounds_str}"))
        m_layout.addWidget(QLabel(f"<b>Max Speed:</b> {self.report.max_feedrate:.0f} mm/min"))
        m_layout.addWidget(QLabel(f"<b>Max Power:</b> S{self.report.max_power:.0f}"))
        m_layout.addStretch(1)

        layout.addWidget(metrics_frame)

        # 3. Repairs Card (if repairs applied)
        if self.repairs_applied:
            repairs_box = QFrame()
            repairs_box.setStyleSheet("background-color: #16261c; border: 1px solid #388e3c; border-radius: 6px;")
            rep_layout = QVBoxLayout(repairs_box)
            rep_layout.setContentsMargins(10, 8, 10, 8)
            rep_layout.setSpacing(4)

            rep_title = QLabel("<b>🔧 Automated Pre-Burn Repairs Applied:</b>")
            rep_title.setStyleSheet("color: #69f0ae; font-size: 11px;")
            rep_layout.addWidget(rep_title)

            for fix in self.repairs_applied:
                lbl_fix = QLabel(f"  • {fix}")
                lbl_fix.setStyleSheet("color: #c8e6c9; font-size: 11px;")
                rep_layout.addWidget(lbl_fix)

            layout.addWidget(repairs_box)

        # 4. Issues Table (if issues were detected in raw input)
        if self.report.issues:
            self.table = QTableWidget()
            self.table.setColumnCount(5)
            self.table.setHorizontalHeaderLabels(["Severity", "Line #", "Code", "Description", "Offending G-Code"])
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            self.table.verticalHeader().setVisible(False)
            self.table.setRowCount(len(self.report.issues))

            mono_font = QFont("monospace", 9)

            for row, issue in enumerate(self.report.issues):
                item_sev = QTableWidgetItem("🔴 ERROR" if issue.severity == "error" else "🟡 WARN")
                item_sev.setForeground(QColor("#ff5252" if issue.severity == "error" else "#ffd740"))
                item_sev.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 0, item_sev)

                item_line = QTableWidgetItem(f"L{issue.line_number}")
                item_line.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 1, item_line)

                item_code = QTableWidgetItem(issue.error_code)
                self.table.setItem(row, 2, item_code)

                item_msg = QTableWidgetItem(issue.message)
                self.table.setItem(row, 3, item_msg)

                item_raw = QTableWidgetItem(issue.line_text)
                item_raw.setFont(mono_font)
                self.table.setItem(row, 4, item_raw)

            layout.addWidget(self.table, 1)
        elif not self.repairs_applied:
            lbl_clean = QLabel("🎉 Clean bill of health! G-code is 100% verified and ready for burning.")
            lbl_clean.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_clean.setStyleSheet("color: #81c784; font-size: 13px; padding: 30px;")
            layout.addWidget(lbl_clean, 1)

        # 5. Button Bar
        btn_bar = QHBoxLayout()

        # Simulate Toolpath Preview button
        if self.job_result is not None:
            self.btn_simulate = QPushButton("🔍 Simulate Toolpath Preview")
            self.btn_simulate.setToolTip("Watch animated laser simulation before sending commands to hardware")
            self.btn_simulate.setStyleSheet("background-color: #0277bd; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
            self.btn_simulate.clicked.connect(self._open_simulation_preview)
            btn_bar.addWidget(self.btn_simulate)

        btn_bar.addStretch(1)

        if self.allow_proceed:
            proceed_text = "🔥 Burn Repaired Code" if self.repairs_applied else "Proceed / Start Job"
            btn_color = "#2e7d32" if self.repairs_applied else "#e65100"
            self.btn_proceed = QPushButton(proceed_text)
            self.btn_proceed.setStyleSheet(
                f"background-color: {btn_color}; color: white; font-weight: bold; padding: 6px 18px; border-radius: 4px;"
            )
            self.btn_proceed.clicked.connect(self._on_proceed)
            btn_bar.addWidget(self.btn_proceed)

        self.btn_close = QPushButton("Cancel / Abort" if self.allow_proceed else "Close")
        self.btn_close.setStyleSheet("padding: 6px 16px; border-radius: 4px;")
        self.btn_close.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_close)

        layout.addLayout(btn_bar)

    def _open_simulation_preview(self):
        """Opens the full animated PreviewDialog for visual verification."""
        if self.job_result is not None:
            from laserforge.ui.preview_dialog import PreviewDialog
            prev_dlg = PreviewDialog(self.job_result, parent=self, settings=self.settings)
            prev_dlg.exec()

    def _on_proceed(self):
        self.proceed_chosen = True
        self.accept()
