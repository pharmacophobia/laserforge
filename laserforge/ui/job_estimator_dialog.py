"""
LaserForge Pre-Job Time, Material, and Cost Estimator Dialog.
Calculates exact cutting time, rapid traverse, bounding area,
sheet material utilization, machine operational cost, and customer quote.
"""

from typing import Optional, Dict, Tuple
import os
import math

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QComboBox, QPushButton, QGroupBox, QFrame,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from laserforge.core.gcode_generator import GCodeJobResult


class JobEstimatorDialog(QDialog):
    """Interactive job cost, material utilization, and time estimation dialog."""

    MATERIAL_PRESETS = {
        "3mm Baltic Birch Plywood": {"sheet_w": 300.0, "sheet_h": 300.0, "sheet_cost": 12.00},
        "3mm Cast Acrylic (Clear/Color)": {"sheet_w": 300.0, "sheet_h": 300.0, "sheet_cost": 18.00},
        "5mm Cast Acrylic": {"sheet_w": 300.0, "sheet_h": 300.0, "sheet_cost": 25.00},
        "3mm MDF / Draftboard": {"sheet_w": 300.0, "sheet_h": 300.0, "sheet_cost": 6.50},
        "Veg-Tan Leather (1.5mm)": {"sheet_w": 300.0, "sheet_h": 300.0, "sheet_cost": 22.00},
        "Cardstock / Chipboard": {"sheet_w": 300.0, "sheet_h": 300.0, "sheet_cost": 2.00},
        "Custom Material": {"sheet_w": 400.0, "sheet_h": 400.0, "sheet_cost": 15.00}
    }

    def __init__(self, job_result: GCodeJobResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laser Job Cost & Time Estimator ⏱️")
        self.resize(680, 560)

        self.job = job_result
        self.run_job_requested = False

        self._init_ui()
        self._calculate_costs()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(14, 14, 14, 14)

        # 1. Top Summary Banner (Time & Total Cost)
        banner = QFrame()
        banner.setStyleSheet("background-color: #242432; border: 1px solid #36364a; border-radius: 6px; padding: 10px;")
        banner_layout = QHBoxLayout(banner)

        # Time metric
        time_box = QVBoxLayout()
        lbl_time_title = QLabel("ESTIMATED RUN TIME")
        lbl_time_title.setStyleSheet("color: #8c8ca8; font-size: 10px; font-weight: bold;")
        self.lbl_time_val = QLabel(self._format_time(self.job.estimated_time_sec))
        self.lbl_time_val.setStyleSheet("color: #00e5ff; font-size: 22px; font-weight: bold; font-family: monospace;")
        time_box.addWidget(lbl_time_title)
        time_box.addWidget(self.lbl_time_val)
        banner_layout.addLayout(time_box)

        # Divider
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setStyleSheet("color: #36364a;")
        banner_layout.addWidget(v_line)

        # Area metric
        bb = self.job.bounding_box
        w_mm = max(0.0, bb[2] - bb[0])
        h_mm = max(0.0, bb[3] - bb[1])
        area_cm2 = (w_mm * h_mm) / 100.0

        area_box = QVBoxLayout()
        lbl_area_title = QLabel("BOUNDING AREA")
        lbl_area_title.setStyleSheet("color: #8c8ca8; font-size: 10px; font-weight: bold;")
        self.lbl_area_val = QLabel(f"{w_mm:.1f} × {h_mm:.1f} mm\n({area_cm2:.1f} cm²)")
        self.lbl_area_val.setStyleSheet("color: #ffd600; font-size: 13px; font-weight: bold;")
        area_box.addWidget(lbl_area_title)
        area_box.addWidget(self.lbl_area_val)
        banner_layout.addLayout(area_box)

        # Divider
        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.Shape.VLine)
        v_line2.setStyleSheet("color: #36364a;")
        banner_layout.addWidget(v_line2)

        # Cost metric
        cost_box = QVBoxLayout()
        lbl_cost_title = QLabel("ESTIMATED TOTAL COST")
        lbl_cost_title.setStyleSheet("color: #8c8ca8; font-size: 10px; font-weight: bold;")
        self.lbl_total_cost = QLabel("$0.00")
        self.lbl_total_cost.setStyleSheet("color: #66bb6a; font-size: 24px; font-weight: bold;")
        cost_box.addWidget(lbl_cost_title)
        cost_box.addWidget(self.lbl_total_cost)
        banner_layout.addLayout(cost_box)

        main_layout.addWidget(banner)

        # 2. Toolpath & Motion Breakdown Group
        motion_group = QGroupBox("Motion & Distance Breakdown")
        motion_layout = QGridLayout(motion_group)
        motion_layout.setSpacing(6)

        cut_m = self.job.total_cut_dist_mm / 1000.0
        rapid_m = self.job.total_rapid_dist_mm / 1000.0
        total_m = cut_m + rapid_m
        eff_pct = (cut_m / max(0.001, total_m)) * 100.0

        motion_layout.addWidget(QLabel("Cutting Distance:"), 0, 0)
        motion_layout.addWidget(QLabel(f"<b>{self.job.total_cut_dist_mm:.0f} mm</b> ({cut_m:.2f} m)"), 0, 1)

        motion_layout.addWidget(QLabel("Rapid Travel Distance:"), 0, 2)
        motion_layout.addWidget(QLabel(f"<b>{self.job.total_rapid_dist_mm:.0f} mm</b> ({rapid_m:.2f} m)"), 0, 3)

        motion_layout.addWidget(QLabel("Traverse Efficiency:"), 1, 0)
        motion_layout.addWidget(QLabel(f"<b>{eff_pct:.1f}%</b> cutting moves"), 1, 1)

        motion_layout.addWidget(QLabel("Toolpath Segments:"), 1, 2)
        motion_layout.addWidget(QLabel(f"<b>{len(self.job.segments):,}</b> vector lines"), 1, 3)

        main_layout.addWidget(motion_group)

        # 3. Material & Operational Cost Breakdown Group
        cost_group = QGroupBox("Material & Pricing Calculator")
        cost_layout = QGridLayout(cost_group)
        cost_layout.setSpacing(6)

        cost_layout.addWidget(QLabel("Material Preset:"), 0, 0)
        self.combo_mat = QComboBox()
        for name in self.MATERIAL_PRESETS.keys():
            self.combo_mat.addItem(name)
        self.combo_mat.currentTextChanged.connect(self._on_mat_preset_changed)
        cost_layout.addWidget(self.combo_mat, 0, 1, 1, 3)

        cost_layout.addWidget(QLabel("Sheet Dimensions:"), 1, 0)
        sheet_dim_box = QHBoxLayout()
        self.spin_sheet_w = QDoubleSpinBox()
        self.spin_sheet_w.setRange(50.0, 2000.0)
        self.spin_sheet_w.setValue(300.0)
        self.spin_sheet_w.setSuffix(" mm")
        self.spin_sheet_w.valueChanged.connect(self._calculate_costs)

        self.spin_sheet_h = QDoubleSpinBox()
        self.spin_sheet_h.setRange(50.0, 2000.0)
        self.spin_sheet_h.setValue(300.0)
        self.spin_sheet_h.setSuffix(" mm")
        self.spin_sheet_h.valueChanged.connect(self._calculate_costs)

        sheet_dim_box.addWidget(self.spin_sheet_w)
        sheet_dim_box.addWidget(QLabel("×"))
        sheet_dim_box.addWidget(self.spin_sheet_h)
        cost_layout.addLayout(sheet_dim_box, 1, 1)

        cost_layout.addWidget(QLabel("Sheet Cost ($):"), 1, 2)
        self.spin_sheet_cost = QDoubleSpinBox()
        self.spin_sheet_cost.setRange(0.1, 1000.0)
        self.spin_sheet_cost.setValue(12.00)
        self.spin_sheet_cost.setPrefix("$ ")
        self.spin_sheet_cost.valueChanged.connect(self._calculate_costs)
        cost_layout.addWidget(self.spin_sheet_cost, 1, 3)

        cost_layout.addWidget(QLabel("Machine Rate ($/hr):"), 2, 0)
        self.spin_hourly_rate = QDoubleSpinBox()
        self.spin_hourly_rate.setRange(0.0, 250.0)
        self.spin_hourly_rate.setValue(20.00)
        self.spin_hourly_rate.setPrefix("$ ")
        self.spin_hourly_rate.valueChanged.connect(self._calculate_costs)
        cost_layout.addWidget(self.spin_hourly_rate, 2, 1)

        cost_layout.addWidget(QLabel("Markup / Profit (%):"), 2, 2)
        self.spin_markup = QDoubleSpinBox()
        self.spin_markup.setRange(0.0, 500.0)
        self.spin_markup.setValue(30.0)
        self.spin_markup.setSuffix(" %")
        self.spin_markup.valueChanged.connect(self._calculate_costs)
        cost_layout.addWidget(self.spin_markup, 2, 3)

        # Cost Breakdown Display Table
        self.lbl_breakdown = QLabel()
        self.lbl_breakdown.setStyleSheet("background-color: #1a1a24; border: 1px solid #2e2e3e; border-radius: 4px; padding: 6px; font-family: monospace; font-size: 11px;")
        cost_layout.addWidget(self.lbl_breakdown, 3, 0, 1, 4)

        main_layout.addWidget(cost_group)

        # 4. Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_export_quote = QPushButton("📄 Export Quote / Receipt...")
        self.btn_export_quote.clicked.connect(self._export_quote_report)
        btn_row.addWidget(self.btn_export_quote)

        btn_row.addStretch(1)

        btn_cancel = QPushButton("Close")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self.btn_start = QPushButton("⚡ Proceed to Start Job")
        self.btn_start.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 16px;")
        self.btn_start.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.btn_start)

        main_layout.addLayout(btn_row)

    def _format_time(self, sec: float) -> str:
        s = int(round(sec))
        hours = s // 3600
        mins = (s % 3600) // 60
        secs = s % 60
        if hours > 0:
            return f"{hours}h {mins:02d}m {secs:02d}s"
        return f"{mins:02d}m {secs:02d}s"

    def _on_mat_preset_changed(self, name: str):
        if name in self.MATERIAL_PRESETS:
            p = self.MATERIAL_PRESETS[name]
            self.spin_sheet_w.blockSignals(True)
            self.spin_sheet_h.blockSignals(True)
            self.spin_sheet_cost.blockSignals(True)

            self.spin_sheet_w.setValue(p["sheet_w"])
            self.spin_sheet_h.setValue(p["sheet_h"])
            self.spin_sheet_cost.setValue(p["sheet_cost"])

            self.spin_sheet_w.blockSignals(False)
            self.spin_sheet_h.blockSignals(False)
            self.spin_sheet_cost.blockSignals(False)
            self._calculate_costs()

    def _calculate_costs(self):
        bb = self.job.bounding_box
        w_mm = max(0.0, bb[2] - bb[0])
        h_mm = max(0.0, bb[3] - bb[1])
        job_area_mm2 = w_mm * h_mm

        sheet_w = self.spin_sheet_w.value()
        sheet_h = self.spin_sheet_h.value()
        sheet_area_mm2 = max(100.0, sheet_w * sheet_h)
        sheet_cost = self.spin_sheet_cost.value()

        # Material cost proportional to bounding area with 15% scrap margin
        mat_fraction = min(1.0, (job_area_mm2 * 1.15) / sheet_area_mm2)
        material_cost = mat_fraction * sheet_cost

        # Machine run cost
        run_hours = self.job.estimated_time_sec / 3600.0
        hourly_rate = self.spin_hourly_rate.value()
        machine_cost = run_hours * hourly_rate

        subtotal = material_cost + machine_cost
        markup_pct = self.spin_markup.value()
        total_quote = subtotal * (1.0 + markup_pct / 100.0)

        self.lbl_total_cost.setText(f"${total_quote:.2f}")

        breakdown_text = (
            f"Material Used:  {mat_fraction * 100:.1f}% of sheet ({job_area_mm2 / 100.0:.1f} cm²)  ➔  ${material_cost:.2f}\n"
            f"Machine Time:   {self._format_time(self.job.estimated_time_sec)} @ ${hourly_rate:.2f}/hr          ➔  ${machine_cost:.2f}\n"
            f"Subtotal:       ${subtotal:.2f}  |  Markup ({markup_pct:.0f}%): ${subtotal * (markup_pct / 100.0):.2f}\n"
            f"Suggested Quote: ${total_quote:.2f}"
        )
        self.lbl_breakdown.setText(breakdown_text)

    def _export_quote_report(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Job Cost Estimate", "LaserJob_Quote.txt", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        bb = self.job.bounding_box
        report = f"""==================================================
           LASERFORGE JOB ESTIMATE & QUOTE
==================================================
Estimated Run Time:  {self._format_time(self.job.estimated_time_sec)}
Cut Distance:        {self.job.total_cut_dist_mm:.1f} mm
Rapid Travel:        {self.job.total_rapid_dist_mm:.1f} mm
Bounding Dimensions: {bb[2]-bb[0]:.1f} x {bb[3]-bb[1]:.1f} mm
Area Used:           {(bb[2]-bb[0])*(bb[3]-bb[1])/100.0:.1f} cm²

Material:            {self.combo_mat.currentText()}
Sheet Dimensions:    {self.spin_sheet_w.value():.0f} x {self.spin_sheet_h.value():.0f} mm
Sheet Cost:          ${self.spin_sheet_cost.value():.2f}

{self.lbl_breakdown.text()}
==================================================
FINAL QUOTE: {self.lbl_total_cost.text()}
==================================================
"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(report)
            QMessageBox.information(self, "Export Complete", f"Quote saved successfully to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to save quote: {e}")

    def _on_start_clicked(self):
        self.run_job_requested = True
        self.accept()
