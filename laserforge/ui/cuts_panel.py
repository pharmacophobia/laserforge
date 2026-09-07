"""
LaserForge Cuts / Layers Panel.
Table displaying active laser cut layers with quick-edit parameters (speed, power, passes, mode)
and a bottom color swatch palette to assign layers to selected shapes.
"""

from typing import Optional, List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QDialog, QLabel, QDoubleSpinBox, QSpinBox,
    QComboBox, QCheckBox, QGroupBox, QFormLayout, QDialogButtonBox
)

from laserforge.config import LAYER_PALETTE, CUT_MODES
from laserforge.core.layer_manager import LayerManager
from laserforge.core.models import LayerCutSettings

class CutSettingsDialog(QDialog):
    """Detailed modal dialog to configure a layer's laser cut parameters."""
    def __init__(self, layer: LayerCutSettings, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.setWindowTitle(f"Cut Settings Editor - Layer {layer.name} ({layer.color})")
        self.setMinimumWidth(400)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        group = QGroupBox("Laser Parameters")
        form = QFormLayout(group)

        # Mode
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(CUT_MODES)
        self.combo_mode.setCurrentText(self.layer.mode)
        form.addRow("Cut Mode:", self.combo_mode)

        # Speed
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(10.0, 50000.0)
        self.spin_speed.setValue(self.layer.speed)
        self.spin_speed.setSuffix(" mm/min")
        form.addRow("Speed:", self.spin_speed)

        # Max Power
        self.spin_pmax = QDoubleSpinBox()
        self.spin_pmax.setRange(0.0, 100.0)
        self.spin_pmax.setValue(self.layer.power_max)
        self.spin_pmax.setSuffix(" %")
        form.addRow("Max Power:", self.spin_pmax)

        # Min Power
        self.spin_pmin = QDoubleSpinBox()
        self.spin_pmin.setRange(0.0, 100.0)
        self.spin_pmin.setValue(self.layer.power_min)
        self.spin_pmin.setSuffix(" %")
        form.addRow("Min Power:", self.spin_pmin)

        # Passes
        self.spin_passes = QSpinBox()
        self.spin_passes.setRange(1, 50)
        self.spin_passes.setValue(self.layer.passes)
        form.addRow("Pass Count:", self.spin_passes)

        # Z Step
        self.spin_zstep = QDoubleSpinBox()
        self.spin_zstep.setRange(0.0, 10.0)
        self.spin_zstep.setValue(self.layer.z_step)
        self.spin_zstep.setSuffix(" mm")
        form.addRow("Z Step per Pass:", self.spin_zstep)

        # Line Interval (for Fill/Image)
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.01, 5.0)
        self.spin_interval.setDecimals(3)
        self.spin_interval.setValue(self.layer.line_interval)
        self.spin_interval.setSuffix(" mm")
        form.addRow("Fill Line Interval:", self.spin_interval)

        # Air assist
        self.chk_air = QCheckBox("Enable Air Assist (M8)")
        self.chk_air.setChecked(self.layer.air_assist)
        form.addRow("Air Assist:", self.chk_air)

        layout.addWidget(group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_and_accept(self):
        self.layer.mode = self.combo_mode.currentText()
        self.layer.speed = self.spin_speed.value()
        self.layer.power_max = self.spin_pmax.value()
        self.layer.power_min = self.spin_pmin.value()
        self.layer.passes = self.spin_passes.value()
        self.layer.z_step = self.spin_zstep.value()
        self.layer.line_interval = self.spin_interval.value()
        self.layer.air_assist = self.chk_air.isChecked()
        self.accept()


class CutsPanel(QWidget):
    layer_selected = pyqtSignal(int)
    layers_updated = pyqtSignal()

    def __init__(self, layer_manager: LayerManager, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Table of Layers
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Layer", "Mode", "Speed", "Power", "Pass", "Air", "Out"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        # Bottom Color Swatch Palette (LightBurn style)
        swatch_group = QGroupBox("Color Palette")
        swatch_layout = QHBoxLayout(swatch_group)
        swatch_layout.setContentsMargins(4, 4, 4, 4)
        swatch_layout.setSpacing(3)

        for p in LAYER_PALETTE:
            lid = p["id"]
            color_hex = p["color"]
            btn = QPushButton(p["name"])
            btn.setFixedSize(36, 26)
            btn.setToolTip(f"{p['label']} ({color_hex})")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color_hex};
                    color: {'#000000' if lid in (4, 11) else '#ffffff'};
                    font-weight: bold;
                    font-size: 10px;
                    border: 1px solid #555555;
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    border: 2px solid #ffffff;
                }}
            """)
            btn.clicked.connect(lambda checked, layer_id=lid: self.layer_selected.emit(layer_id))
            swatch_layout.addWidget(btn)

        swatch_layout.addStretch()
        layout.addWidget(swatch_group)

        self.refresh_table()

    def refresh_table(self):
        """Re-populates the cuts table with current layer parameters."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        layers = self.layer_manager.get_all_layers()
        self.table.setRowCount(len(layers))

        for row, l in enumerate(layers):
            # 0. Layer icon + name
            pix = QPixmap(14, 14)
            pix.fill(QColor(l.color))
            item_name = QTableWidgetItem(QIcon(pix), l.name)
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_name)

            # 1. Mode
            item_mode = QTableWidgetItem(l.mode)
            item_mode.setFlags(item_mode.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, item_mode)

            # 2. Speed
            item_speed = QTableWidgetItem(f"{l.speed:.0f}")
            self.table.setItem(row, 2, item_speed)

            # 3. Power
            item_power = QTableWidgetItem(f"{l.power_max:.0f}%")
            self.table.setItem(row, 3, item_power)

            # 4. Passes
            item_pass = QTableWidgetItem(str(l.passes))
            self.table.setItem(row, 4, item_pass)

            # 5. Air
            item_air = QTableWidgetItem()
            item_air.setCheckState(Qt.CheckState.Checked if l.air_assist else Qt.CheckState.Unchecked)
            self.table.setItem(row, 5, item_air)

            # 6. Output
            item_out = QTableWidgetItem()
            item_out.setCheckState(Qt.CheckState.Checked if l.output_enabled else Qt.CheckState.Unchecked)
            self.table.setItem(row, 6, item_out)

        self.table.blockSignals(False)

    def _on_row_double_clicked(self, index):
        row = index.row()
        layers = self.layer_manager.get_all_layers()
        if 0 <= row < len(layers):
            dlg = CutSettingsDialog(layers[row], self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.refresh_table()
                self.layers_updated.emit()

    def _on_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        col = item.column()
        layers = self.layer_manager.get_all_layers()
        if row >= len(layers): return
        layer = layers[row]

        try:
            if col == 2:  # Speed
                val = float(item.text().replace("mm/min", "").strip())
                layer.speed = max(1.0, val)
            elif col == 3:  # Power
                val = float(item.text().replace("%", "").strip())
                layer.power_max = max(0.0, min(100.0, val))
            elif col == 4:  # Passes
                val = int(item.text().strip())
                layer.passes = max(1, val)
            elif col == 5:  # Air
                layer.air_assist = (item.checkState() == Qt.CheckState.Checked)
            elif col == 6:  # Output
                layer.output_enabled = (item.checkState() == Qt.CheckState.Checked)

            self.layers_updated.emit()
        except Exception:
            pass
