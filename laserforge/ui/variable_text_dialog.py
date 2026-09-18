"""
LaserForge Variable Text & CSV Batch Merge Studio Dialog.
Integrates spreadsheet data with vector design templates to generate personalized
production runs of name tags, serialized asset tags, and compliance badges.
"""

import os
from typing import List, Optional, Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QGroupBox,
    QFormLayout, QFileDialog, QMessageBox, QSplitter, QWidget, QHeaderView
)

from laserforge.core.models import LaserEntity
from laserforge.core.variable_text_engine import (
    VariableTextDataset, VariableTextEngine
)


class VariableTextDialog(QDialog):
    """Interactive Studio Dialog for Batch Variable Text and CSV Data Merge."""

    batch_generated = pyqtSignal(list)  # Emits generated LaserEntity list

    def __init__(
        self,
        template_entities: List[LaserEntity],
        bed_width: float = 400.0,
        bed_height: float = 400.0,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Variable Text & Batch CSV Production Merge Studio")
        self.resize(800, 560)
        self.template_entities = template_entities
        self.bed_width = bed_width
        self.bed_height = bed_height

        self.dataset = VariableTextDataset()
        self.detected_vars = VariableTextEngine.find_template_variables(self.template_entities)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header description
        lbl_info = QLabel(
            "Merge external CSV/TSV data into design templates. Placeholders in text "
            "(e.g. %NAME%, %TITLE%, %SERIAL:03d%, %DATE%) are automatically populated per item."
        )
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #b0bec5; font-size: 11px;")
        layout.addWidget(lbl_info)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Column: Data Source & Table Preview
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        h_file = QHBoxLayout()
        self.btn_load_csv = QPushButton("📂 Load CSV / TSV File...")
        self.btn_load_csv.setStyleSheet("font-weight: bold; padding: 5px;")
        self.btn_load_csv.clicked.connect(self._on_load_csv)
        h_file.addWidget(self.btn_load_csv)

        self.lbl_file = QLabel("No file loaded (Click to browse)")
        self.lbl_file.setStyleSheet("color: #90a4ae; font-style: italic;")
        h_file.addWidget(self.lbl_file, 1)
        left_layout.addLayout(h_file)

        # Table preview
        self.table = QTableWidget()
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a24;
                border: 1px solid #2d2d3f;
                color: #e0e0e0;
            }
            QHeaderView::section {
                background-color: #242432;
                color: #00e5ff;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #36364a;
            }
        """)
        left_layout.addWidget(self.table, 1)
        self.table_preview = self.table

        splitter.addWidget(left_widget)

        # Right Column: Variables & Grid Layout Parameters
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Detected variables group
        grp_vars = QGroupBox("Detected Template Placeholders")
        v_vars = QVBoxLayout(grp_vars)
        if self.detected_vars:
            var_str = ", ".join([f"%{v}%" for v in self.detected_vars])
            lbl_vars = QLabel(f"Found: <b>{var_str}</b>")
            lbl_vars.setStyleSheet("color: #00e5ff;")
        else:
            lbl_vars = QLabel(
                "No %VARIABLE% tags found in selected text.<br/>"
                "<i>Tip: Add %NAME% or %SERIAL% to text to substitute values.</i>"
            )
            lbl_vars.setStyleSheet("color: #ffab00;")
        lbl_vars.setWordWrap(True)
        v_vars.addWidget(lbl_vars)
        right_layout.addWidget(grp_vars)

        # Grid settings group
        grp_grid = QGroupBox("Tiled Grid Layout Parameters")
        form_grid = QFormLayout(grp_grid)

        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 50)
        self.spin_cols.setValue(5)
        self.spin_cols.valueChanged.connect(self._update_telemetry)
        form_grid.addRow("Grid Columns (X):", self.spin_cols)

        self.spin_spacing_x = QDoubleSpinBox()
        self.spin_spacing_x.setRange(0.0, 100.0)
        self.spin_spacing_x.setValue(5.0)
        self.spin_spacing_x.setSuffix(" mm")
        self.spin_spacing_x.valueChanged.connect(self._update_telemetry)
        form_grid.addRow("X Item Spacing:", self.spin_spacing_x)

        self.spin_spacing_y = QDoubleSpinBox()
        self.spin_spacing_y.setRange(0.0, 100.0)
        self.spin_spacing_y.setValue(5.0)
        self.spin_spacing_y.setSuffix(" mm")
        self.spin_spacing_y.valueChanged.connect(self._update_telemetry)
        form_grid.addRow("Y Item Spacing:", self.spin_spacing_y)

        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 100.0)
        self.spin_margin.setValue(10.0)
        self.spin_margin.setSuffix(" mm")
        self.spin_margin.valueChanged.connect(self._update_telemetry)
        form_grid.addRow("Bed Edge Margin:", self.spin_margin)

        self.spin_serial_start = QSpinBox()
        self.spin_serial_start.setRange(0, 999999)
        self.spin_serial_start.setValue(1)
        form_grid.addRow("Start Serial (%SERIAL%):", self.spin_serial_start)

        right_layout.addWidget(grp_grid)

        # Summary telemetry
        grp_summary = QGroupBox("Production Batch Telemetry")
        form_summary = QFormLayout(grp_summary)
        self.lbl_items_placed = QLabel("0 / 0 items")
        self.lbl_sheet_dims = QLabel("0 × 0 mm")
        self.lbl_bed_fit = QLabel("Ready")
        self.lbl_bed_fit.setStyleSheet("font-weight: bold; color: #00e5ff;")

        form_summary.addRow("Parts to Generate:", self.lbl_items_placed)
        form_summary.addRow("Sheet Footprint:", self.lbl_sheet_dims)
        form_summary.addRow("Laser Bed Fit:", self.lbl_bed_fit)
        right_layout.addWidget(grp_summary)

        right_layout.addStretch()
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # Bottom buttons
        h_btn = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        self.btn_generate = QPushButton("🚀 Generate Batch onto Canvas")
        self.btn_generate.setStyleSheet(
            "background-color: #00e676; color: #000000; font-weight: bold; padding: 6px 16px;"
        )
        self.btn_generate.clicked.connect(self._on_generate_batch)

        h_btn.addStretch()
        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(self.btn_generate)
        layout.addLayout(h_btn)

    def load_dataset(self, dataset: VariableTextDataset):
        """Populates the dialog data table and calculates recommended layout."""
        self.dataset = dataset
        self.table.setColumnCount(len(self.dataset.columns))
        self.table.setHorizontalHeaderLabels(self.dataset.columns)
        self.table.setRowCount(len(self.dataset.rows))

        for r_idx, row in enumerate(self.dataset.rows):
            for c_idx, col_name in enumerate(self.dataset.columns):
                val = row.fields.get(col_name, "")
                self.table.setItem(r_idx, c_idx, QTableWidgetItem(str(val)))

        if self.template_entities:
            w = max(1.0, max(e.get_bounds()[2] for e in self.template_entities) - min(e.get_bounds()[0] for e in self.template_entities))
            ideal_cols = max(1, int((self.bed_width - 20) / (w + self.spin_spacing_x.value())))
            self.spin_cols.setValue(min(ideal_cols, len(self.dataset.rows)))

        self._update_telemetry()

    def _on_load_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CSV / Spreadsheet", "", "CSV Files (*.csv *.tsv *.txt);;All Files (*)"
        )
        if not path:
            return

        try:
            ds = VariableTextDataset.from_csv_file(path)
            self.lbl_file.setText(os.path.basename(path))
            self.load_dataset(ds)
        except Exception as ex:
            QMessageBox.critical(self, "Load Error", f"Failed to parse CSV file: {ex}")

    def _update_telemetry(self):
        if not self.dataset.rows or not self.template_entities:
            self.lbl_items_placed.setText("0 items")
            self.lbl_sheet_dims.setText("0 × 0 mm")
            self.lbl_bed_fit.setText("Load CSV to calculate")
            return

        cols = self.spin_cols.value()
        total_items = len(self.dataset.rows)
        rows = (total_items + cols - 1) // cols

        min_x = min(e.get_bounds()[0] for e in self.template_entities)
        min_y = min(e.get_bounds()[1] for e in self.template_entities)
        max_x = max(e.get_bounds()[2] for e in self.template_entities)
        max_y = max(e.get_bounds()[3] for e in self.template_entities)
        tw = max(1.0, max_x - min_x)
        th = max(1.0, max_y - min_y)

        sp_x = self.spin_spacing_x.value()
        sp_y = self.spin_spacing_y.value()
        m = self.spin_margin.value()

        footprint_w = cols * tw + (cols - 1) * sp_x
        footprint_h = rows * th + (rows - 1) * sp_y

        self.lbl_items_placed.setText(f"{total_items} parts ({cols} cols × {rows} rows)")
        self.lbl_sheet_dims.setText(f"{footprint_w:.1f} × {footprint_h:.1f} mm")

        fits = (footprint_w + 2 * m <= self.bed_width) and (footprint_h + 2 * m <= self.bed_height)
        if fits:
            self.lbl_bed_fit.setText("✅ Fits completely on laser bed")
            self.lbl_bed_fit.setStyleSheet("font-weight: bold; color: #00e676;")
        else:
            self.lbl_bed_fit.setText("⚠️ Exceeds active workbed size")
            self.lbl_bed_fit.setStyleSheet("font-weight: bold; color: #ff9100;")

    def _on_generate_batch(self):
        if not self.dataset.rows:
            QMessageBox.warning(self, "No Data", "Please load a CSV data file first.")
            return

        if not self.template_entities:
            QMessageBox.warning(self, "No Template", "Please select template shapes on the canvas first.")
            return

        batch_entities, meta = VariableTextEngine.generate_batch_array(
            template_entities=self.template_entities,
            dataset=self.dataset,
            bed_width=self.bed_width,
            bed_height=self.bed_height,
            spacing_x=self.spin_spacing_x.value(),
            spacing_y=self.spin_spacing_y.value(),
            margin_x=self.spin_margin.value(),
            margin_y=self.spin_margin.value(),
            columns=self.spin_cols.value(),
            serial_start=self.spin_serial_start.value()
        )

        if not batch_entities:
            QMessageBox.warning(self, "Generation Failed", "No parts could be placed within the bed dimensions.")
            return

        self.batch_generated.emit(batch_entities)
        self.accept()
