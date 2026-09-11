"""
LaserForge Curved / Arc Text Dialog.
Interactive tool for engraving text along a circular curve or coaster rim.
"""

from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QFontComboBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QGroupBox, QMessageBox
)

from laserforge.core.font_tools import FontTools
from laserforge.core.models import PathEntity


class CurvedTextDialog(QDialog):
    curved_text_created = pyqtSignal(object)  # Emits PathEntity

    def __init__(self, parent=None, bed_width: float = 150.0, bed_height: float = 200.0):
        super().__init__(parent)
        self.setWindowTitle("Curved Arc Text Tool")
        self.resize(460, 420)
        self.bed_width = bed_width
        self.bed_height = bed_height

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl_desc = QLabel("Bends vector text smoothly along a circular radius (ideal for coasters, badges, and coins).")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #b0bec5;")
        layout.addWidget(lbl_desc)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(QLabel("Text:"), 0, 0)
        self.txt_input = QLineEdit("CUSTOM LASER ENGRAVING")
        grid.addWidget(self.txt_input, 0, 1)

        grid.addWidget(QLabel("Font Family:"), 1, 0)
        self.combo_font = QFontComboBox()
        grid.addWidget(self.combo_font, 1, 1)

        grid.addWidget(QLabel("Font Size (mm):"), 2, 0)
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(3.0, 60.0)
        self.spin_size.setValue(10.0)
        self.spin_size.setSuffix(" mm")
        grid.addWidget(self.spin_size, 2, 1)

        grid.addWidget(QLabel("Arc Radius:"), 3, 0)
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(5.0, 200.0)
        self.spin_radius.setValue(40.0)
        self.spin_radius.setSuffix(" mm")
        grid.addWidget(self.spin_radius, 3, 1)

        grid.addWidget(QLabel("Orientation:"), 4, 0)
        self.combo_orient = QComboBox()
        self.combo_orient.addItems(["Top (Clockwise)", "Bottom (Counter-Clockwise)"])
        grid.addWidget(self.combo_orient, 4, 1)

        # Center position
        pos_grp = QGroupBox("Center Position")
        p_layout = QGridLayout(pos_grp)
        p_layout.addWidget(QLabel("Center X:"), 0, 0)
        self.spin_cx = QDoubleSpinBox()
        self.spin_cx.setRange(0, self.bed_width)
        self.spin_cx.setValue(self.bed_width / 2.0)
        self.spin_cx.setSuffix(" mm")
        p_layout.addWidget(self.spin_cx, 0, 1)

        p_layout.addWidget(QLabel("Center Y:"), 0, 2)
        self.spin_cy = QDoubleSpinBox()
        self.spin_cy.setRange(0, self.bed_height)
        self.spin_cy.setValue(self.bed_height / 2.0)
        self.spin_cy.setSuffix(" mm")
        p_layout.addWidget(self.spin_cy, 0, 3)

        grid.addWidget(pos_grp, 5, 0, 1, 2)

        # Style toggles
        h_style = QHBoxLayout()
        self.chk_bold = QCheckBox("Bold")
        self.chk_bold.setChecked(True)
        h_style.addWidget(self.chk_bold)

        self.chk_italic = QCheckBox("Italic")
        h_style.addWidget(self.chk_italic)

        grid.addLayout(h_style, 6, 1)

        layout.addLayout(grid)
        layout.addStretch(1)

        # Action buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_apply = QPushButton("✨ Create Curved Text")
        btn_apply.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 14px;")
        btn_apply.clicked.connect(self._on_apply)
        btn_box.addWidget(btn_apply)

        layout.addLayout(btn_box)

    def _on_apply(self):
        text = self.txt_input.text().strip()
        if not text:
            QMessageBox.warning(self, "No Text", "Please enter text to curve.")
            return

        ent = FontTools.generate_curved_text(
            text=text,
            font_family=self.combo_font.currentFont().family(),
            font_size_mm=self.spin_size.value(),
            radius_mm=self.spin_radius.value(),
            cx=self.spin_cx.value(),
            cy=self.spin_cy.value(),
            orientation=self.combo_orient.currentText(),
            bold=self.chk_bold.isChecked(),
            italic=self.chk_italic.isChecked()
        )

        if not ent:
            QMessageBox.warning(self, "Generation Error", "Could not generate curved text geometry.")
            return

        self.curved_text_created.emit(ent)
        self.accept()
