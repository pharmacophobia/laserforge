"""
LaserForge Serial Number & Batch Variable Text Generator Dialog.
Quickly generates sequential text labels, barcodes/tags, and serial badges for production.
"""

from typing import List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QDoubleSpinBox, QFontComboBox, QComboBox,
    QGroupBox, QMessageBox
)

from laserforge.core.font_tools import FontTools
from laserforge.core.models import TextEntity


class SerialGeneratorDialog(QDialog):
    serials_generated = pyqtSignal(list)  # Emits list of TextEntity

    def __init__(self, parent=None, bed_width: float = 150.0, bed_height: float = 200.0):
        super().__init__(parent)
        self.setWindowTitle("Sequential Serial Number & Batch Text Generator")
        self.resize(450, 420)
        self.bed_width = bed_width
        self.bed_height = bed_height

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl_desc = QLabel(
            "Quickly generate batches of serialized text labels (e.g. SN-001, SN-002, ...) "
            "spaced across the laser bed."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #b0bec5;")
        layout.addWidget(lbl_desc)

        grid = QGridLayout()
        grid.setSpacing(8)

        # Prefix
        grid.addWidget(QLabel("Prefix:"), 0, 0)
        self.txt_prefix = QLineEdit("SN-")
        grid.addWidget(self.txt_prefix, 0, 1)

        # Start number & count
        grid.addWidget(QLabel("Start Number:"), 1, 0)
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, 999999)
        self.spin_start.setValue(1)
        grid.addWidget(self.spin_start, 1, 1)

        grid.addWidget(QLabel("Quantity (Count):"), 2, 0)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 100)
        self.spin_count.setValue(10)
        grid.addWidget(self.spin_count, 2, 1)

        grid.addWidget(QLabel("Zero Padding (Digits):"), 3, 0)
        self.spin_digits = QSpinBox()
        self.spin_digits.setRange(1, 8)
        self.spin_digits.setValue(3)
        grid.addWidget(self.spin_digits, 3, 1)

        grid.addWidget(QLabel("Suffix:"), 4, 0)
        self.txt_suffix = QLineEdit("")
        grid.addWidget(self.txt_suffix, 4, 1)

        # Layout Arrangement
        arr_grp = QGroupBox("Layout & Spacing")
        a_grid = QGridLayout(arr_grp)
        a_grid.addWidget(QLabel("Direction:"), 0, 0)
        self.combo_dir = QComboBox()
        self.combo_dir.addItem("Vertical Column (Down)", "vert")
        self.combo_dir.addItem("Horizontal Row (Right)", "horiz")
        a_grid.addWidget(self.combo_dir, 0, 1)

        a_grid.addWidget(QLabel("Step Spacing (mm):"), 1, 0)
        self.spin_step = QDoubleSpinBox()
        self.spin_step.setRange(2.0, 100.0)
        self.spin_step.setValue(12.0)
        self.spin_step.setSuffix(" mm")
        a_grid.addWidget(self.spin_step, 1, 1)

        a_grid.addWidget(QLabel("Start Position (X, Y):"), 2, 0)
        h_pos = QHBoxLayout()
        self.spin_start_x = QDoubleSpinBox()
        self.spin_start_x.setRange(0, self.bed_width)
        self.spin_start_x.setValue(15.0)
        self.spin_start_x.setSuffix(" X")
        h_pos.addWidget(self.spin_start_x)
        self.spin_start_y = QDoubleSpinBox()
        self.spin_start_y.setRange(0, self.bed_height)
        self.spin_start_y.setValue(15.0)
        self.spin_start_y.setSuffix(" Y")
        h_pos.addWidget(self.spin_start_y)
        a_grid.addLayout(h_pos, 2, 1)

        grid.addWidget(arr_grp, 5, 0, 1, 2)

        # Typography
        typo_grp = QGroupBox("Typography")
        t_grid = QGridLayout(typo_grp)
        t_grid.addWidget(QLabel("Font:"), 0, 0)
        self.combo_font = QFontComboBox()
        t_grid.addWidget(self.combo_font, 0, 1)

        t_grid.addWidget(QLabel("Height:"), 1, 0)
        self.spin_font_sz = QDoubleSpinBox()
        self.spin_font_sz.setRange(2.0, 40.0)
        self.spin_font_sz.setValue(7.0)
        self.spin_font_sz.setSuffix(" mm")
        t_grid.addWidget(self.spin_font_sz, 1, 1)

        t_grid.addWidget(QLabel("Mode:"), 2, 0)
        self.combo_fill_mode = QComboBox()
        self.combo_fill_mode.addItem("Fill (Solid Engrave)", "Fill")
        self.combo_fill_mode.addItem("Outline (Vector Line Cut)", "Outline")
        t_grid.addWidget(self.combo_fill_mode, 2, 1)

        grid.addWidget(typo_grp, 6, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch(1)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_apply = QPushButton("✨ Generate Serial Sequence")
        btn_apply.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 14px;")
        btn_apply.clicked.connect(self._on_apply)
        btn_box.addWidget(btn_apply)

        layout.addLayout(btn_box)

    def _on_apply(self):
        direction = self.combo_dir.currentData()
        step = self.spin_step.value()
        step_x = step if direction == "horiz" else 0.0
        step_y = step if direction == "vert" else 0.0

        entities = FontTools.generate_serial_batch(
            prefix=self.txt_prefix.text(),
            start_number=self.spin_start.value(),
            count=self.spin_count.value(),
            digits=self.spin_digits.value(),
            suffix=self.txt_suffix.text(),
            start_x=self.spin_start_x.value(),
            start_y=self.spin_start_y.value(),
            step_x=step_x,
            step_y=step_y,
            font_family=self.combo_font.currentFont().family(),
            font_size_mm=self.spin_font_sz.value(),
            fill_mode=self.combo_fill_mode.currentData(),
            layer_id=0
        )

        self.serials_generated.emit(entities)
        self.accept()
