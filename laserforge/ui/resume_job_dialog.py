"""
LaserForge Resume Job Dialog.
Provides visual, interactive control for resuming an interrupted or stopped laser job
at an exact percentage (0% - 100%) or specific line number with modal state preview.
"""

from typing import Optional, List, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QGroupBox, QPlainTextEdit,
    QCheckBox, QFrame, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from laserforge.core.job_resumer import JobResumer, ResumedJob, JobAnalysis


class ResumeJobDialog(QDialog):
    """
    Dialog allowing the user to select an exact percentage or line number
    to resume an interrupted or stopped laser job.
    """

    def __init__(
        self,
        gcode_text: str,
        initial_line_idx: Optional[int] = None,
        parent: Optional[QWidget] = None,
        rapid_speed: float = 3000.0
    ):
        super().__init__(parent)
        self.setWindowTitle("Resume Laser Job")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)

        self.gcode_text = gcode_text
        self.rapid_speed = rapid_speed
        self.analysis = JobResumer.analyze_job(gcode_text)
        self.total_lines = self.analysis.total_lines

        if self.total_lines == 0:
            raise ValueError("G-code job contains no executable commands.")

        self.last_stopped_idx = initial_line_idx if initial_line_idx is not None else 0
        self.current_resumed_job: Optional[ResumedJob] = None
        self._updating_inputs = False

        self._init_ui()

        # Initialize to stopped line or 0
        init_idx = max(0, min(self.total_lines - 1, self.last_stopped_idx))
        self._set_target_line(init_idx)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header Info Banner
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header.setStyleSheet("background-color: #1e293b; border-radius: 6px; padding: 6px;")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 8)
        h_layout.setSpacing(4)

        title_lbl = QLabel("<b>⏯ Resume Job from Percentage or Line</b>")
        title_lbl.setStyleSheet("font-size: 13px; color: #38bdf8;")
        desc_lbl = QLabel(
            "LaserForge will safely rapid travel (G0) with laser completely OFF (M5) to the exact "
            "restart coordinate, restore cutting power and feedrate, and seamlessly continue the burn."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")

        h_layout.addWidget(title_lbl)
        h_layout.addWidget(desc_lbl)
        layout.addWidget(header)

        # Job Summary Row
        summary_group = QGroupBox("Original Job Metrics")
        summary_layout = QHBoxLayout(summary_group)
        summary_layout.setContentsMargins(8, 6, 8, 6)

        self.lbl_total_lines = QLabel(f"<b>Total Lines:</b> {self.total_lines:,}")
        self.lbl_cut_dist = QLabel(f"<b>Cut Distance:</b> {self.analysis.total_cut_distance_mm:.1f} mm")
        self.lbl_est_time = QLabel(f"<b>Est. Total Time:</b> {self.analysis.estimated_time_sec:.0f}s")
        summary_layout.addWidget(self.lbl_total_lines)
        summary_layout.addWidget(self.lbl_cut_dist)
        summary_layout.addWidget(self.lbl_est_time)
        layout.addWidget(summary_group)

        # Target Selection Group
        sel_group = QGroupBox("Resumption Point Selection")
        sel_layout = QVBoxLayout(sel_group)
        sel_layout.setSpacing(8)

        # Quick preset buttons
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Quick Jump:"))
        if self.last_stopped_idx > 0:
            self.btn_jump_stopped = QPushButton(f"📍 Interrupted Point (Line #{self.last_stopped_idx})")
            self.btn_jump_stopped.setStyleSheet("font-weight: bold; background-color: #0284c7; color: white;")
            self.btn_jump_stopped.clicked.connect(lambda: self._set_target_line(self.last_stopped_idx))
            preset_row.addWidget(self.btn_jump_stopped)

        for pct in (25, 50, 75):
            btn_pct = QPushButton(f"{pct}%")
            btn_pct.setFixedWidth(50)
            btn_pct.clicked.connect(lambda checked, p=pct: self._set_target_percentage(float(p)))
            preset_row.addWidget(btn_pct)

        preset_row.addStretch()
        sel_layout.addLayout(preset_row)

        # Percentage Slider
        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("Progress:"))
        self.pct_slider = QSlider(Qt.Orientation.Horizontal)
        self.pct_slider.setRange(0, 1000)  # 0.0% to 100.0% (0.1% steps)
        self.pct_slider.setValue(0)
        self.pct_slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self.pct_slider, 1)

        self.pct_spin = QDoubleSpinBox()
        self.pct_spin.setRange(0.0, 100.0)
        self.pct_spin.setSingleStep(0.5)
        self.pct_spin.setDecimals(1)
        self.pct_spin.setSuffix("%")
        self.pct_spin.setFixedWidth(75)
        self.pct_spin.valueChanged.connect(self._on_pct_spin_changed)
        slider_row.addWidget(self.pct_spin)
        sel_layout.addLayout(slider_row)

        # Line Number SpinBox
        line_row = QHBoxLayout()
        line_row.addWidget(QLabel("Target Line Number:"))
        self.line_spin = QSpinBox()
        self.line_spin.setRange(0, max(0, self.total_lines - 1))
        self.line_spin.setValue(0)
        self.line_spin.valueChanged.connect(self._on_line_spin_changed)
        line_row.addWidget(self.line_spin)

        self.chk_by_dist = QCheckBox("Calculate percentage by travel distance instead of line count")
        self.chk_by_dist.toggled.connect(self._on_mode_toggled)
        line_row.addWidget(self.chk_by_dist)
        line_row.addStretch()
        sel_layout.addLayout(line_row)

        layout.addWidget(sel_group)

        # Preview Details Group
        preview_group = QGroupBox("Resumption Verification & Preamble Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(6)

        info_row = QHBoxLayout()
        self.lbl_resume_coord = QLabel("<b>Target Origin:</b> X: 0.000 mm, Y: 0.000 mm")
        self.lbl_resume_coord.setStyleSheet("color: #38bdf8;")
        self.lbl_resume_power = QLabel("<b>State:</b> Laser OFF, Feed: 1000 mm/min")
        info_row.addWidget(self.lbl_resume_coord)
        info_row.addWidget(self.lbl_resume_power)
        preview_layout.addLayout(info_row)

        self.txt_preamble = QPlainTextEdit()
        self.txt_preamble.setReadOnly(True)
        self.txt_preamble.setMaximumHeight(110)
        font = QFont("monospace", 8)
        self.txt_preamble.setFont(font)
        self.txt_preamble.setStyleSheet("background-color: #0f172a; color: #a5f3fc; border: 1px solid #334155;")
        preview_layout.addWidget(self.txt_preamble)

        layout.addWidget(preview_group)

        # Dialog Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_start = QPushButton("▶ Execute Resumed Job")
        self.btn_start.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 6px 16px; font-size: 11px;"
        )
        self.btn_start.clicked.connect(self._on_accept)
        btn_layout.addWidget(self.btn_start)

        layout.addLayout(btn_layout)

    def _set_target_line(self, line_idx: int):
        self._updating_inputs = True
        try:
            clamped = max(0, min(self.total_lines - 1, line_idx))
            self.line_spin.setValue(clamped)
            pct = JobResumer.get_percentage_for_line(
                self.analysis.clean_lines,
                clamped,
                by_distance=self.chk_by_dist.isChecked()
            )
            self.pct_spin.setValue(pct)
            self.pct_slider.setValue(int(round(pct * 10)))
            self._update_preview(clamped)
        finally:
            self._updating_inputs = False

    def _set_target_percentage(self, pct: float):
        self._updating_inputs = True
        try:
            clamped_pct = max(0.0, min(100.0, pct))
            self.pct_spin.setValue(clamped_pct)
            self.pct_slider.setValue(int(round(clamped_pct * 10)))
            line_idx = JobResumer.get_line_for_percentage(
                self.analysis.clean_lines,
                clamped_pct,
                by_distance=self.chk_by_dist.isChecked()
            )
            self.line_spin.setValue(line_idx)
            self._update_preview(line_idx)
        finally:
            self._updating_inputs = False

    def _on_slider_changed(self, val: int):
        if self._updating_inputs:
            return
        pct = val / 10.0
        self._set_target_percentage(pct)

    def _on_pct_spin_changed(self, val: float):
        if self._updating_inputs:
            return
        self._set_target_percentage(val)

    def _on_line_spin_changed(self, val: int):
        if self._updating_inputs:
            return
        self._set_target_line(val)

    def _on_mode_toggled(self, checked: bool):
        if self._updating_inputs:
            return
        self._set_target_line(self.line_spin.value())

    def _update_preview(self, line_idx: int):
        try:
            resumed = JobResumer.build_resumed_job(
                self.analysis.clean_lines,
                target_line_idx=line_idx,
                rapid_speed=self.rapid_speed
            )
            self.current_resumed_job = resumed
            st = resumed.modal_state
            self.lbl_resume_coord.setText(
                f"<b>Target Origin:</b> X: {st.x:.3f} mm, Y: {st.y:.3f} mm"
            )
            laser_desc = f"{st.laser_mode} (S: {st.spindle_power:g})" if st.is_cutting else "M5 (Laser OFF)"
            self.lbl_resume_power.setText(
                f"<b>State:</b> {laser_desc}, Feed: {st.feedrate:.0f} mm/min"
            )
            self.txt_preamble.setPlainText("\n".join(resumed.preamble_lines))
        except Exception as e:
            self.txt_preamble.setPlainText(f"Preview calculation error: {e}")

    def _on_accept(self):
        if not self.current_resumed_job:
            QMessageBox.warning(self, "Error", "No valid resumed job calculated.")
            return
        self.accept()

    def get_resumed_gcode(self) -> str:
        """Returns the full synthesized G-code with safe preamble."""
        if self.current_resumed_job:
            return self.current_resumed_job.full_gcode
        return self.gcode_text
