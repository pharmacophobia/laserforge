"""
LaserForge Material Library & Test Matrix Studio Dialog.
Pre-calibrated parameter database for 3W diode lasers (anodized aluminum cards, wood, leather, acrylic),
custom material profile management, and automated parametric test grid generator.
"""

from typing import Optional, List
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QGroupBox, QSplitter, QListWidget, QListWidgetItem,
    QMessageBox, QTabWidget, QDialogButtonBox, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.materials_database import (
    MaterialDatabase, MaterialProfile
)
from laserforge.core.models import LayerCutSettings, LaserEntity


class TestMatrixDialog(QDialog):
    """Sub-dialog to generate a parametric Power vs Speed test grid."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Material Test Matrix (Power vs. Speed Grid)")
        self.resize(440, 420)
        self.generated_entities: List[LaserEntity] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form_group = QGroupBox("Test Matrix Grid Settings")
        form = QFormLayout(form_group)

        # Speed Range
        speed_row = QHBoxLayout()
        self.spin_min_speed = QSpinBox()
        self.spin_min_speed.setRange(50, 10000)
        self.spin_min_speed.setValue(400)
        self.spin_min_speed.setSuffix(" mm/min")
        speed_row.addWidget(self.spin_min_speed)

        speed_row.addWidget(QLabel("to"))
        self.spin_max_speed = QSpinBox()
        self.spin_max_speed.setRange(50, 10000)
        self.spin_max_speed.setValue(2000)
        self.spin_max_speed.setSuffix(" mm/min")
        speed_row.addWidget(self.spin_max_speed)
        form.addRow("Speed Range:", speed_row)

        self.spin_speed_steps = QSpinBox()
        self.spin_speed_steps.setRange(2, 10)
        self.spin_speed_steps.setValue(5)
        form.addRow("Speed Columns:", self.spin_speed_steps)

        # Power Range
        power_row = QHBoxLayout()
        self.spin_min_power = QSpinBox()
        self.spin_min_power.setRange(5, 100)
        self.spin_min_power.setValue(20)
        self.spin_min_power.setSuffix(" %")
        power_row.addWidget(self.spin_min_power)

        power_row.addWidget(QLabel("to"))
        self.spin_max_power = QSpinBox()
        self.spin_max_power.setRange(5, 100)
        self.spin_max_power.setValue(100)
        self.spin_max_power.setSuffix(" %")
        power_row.addWidget(self.spin_max_power)
        form.addRow("Power Range:", power_row)

        self.spin_power_steps = QSpinBox()
        self.spin_power_steps.setRange(2, 10)
        self.spin_power_steps.setValue(5)
        form.addRow("Power Rows:", self.spin_power_steps)

        # Swatch geometry
        self.spin_swatch_size = QDoubleSpinBox()
        self.spin_swatch_size.setRange(4.0, 25.0)
        self.spin_swatch_size.setValue(8.0)
        self.spin_swatch_size.setSuffix(" mm")
        form.addRow("Swatch Size:", self.spin_swatch_size)

        self.combo_test_type = QComboBox()
        self.combo_test_type.addItems(["Fill (Engrave Test)", "Line (Vector Cut Test)", "Both (Concentric Box)"])
        form.addRow("Test Pattern:", self.combo_test_type)

        layout.addWidget(form_group)

        # 3W recommendation note
        note = QLabel(
            "<i>Fits perfectly on a scrap metal business card blank or wood coupon.<br>"
            "Running this test finds your 3W laser's exact sweet spot in minutes.</i>"
        )
        note.setStyleSheet("color: #90a4ae; font-size: 11px;")
        layout.addWidget(note)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._generate)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _generate(self):
        min_s = float(self.spin_min_speed.value())
        max_s = float(self.spin_max_speed.value())
        s_steps = self.spin_speed_steps.value()

        min_p = float(self.spin_min_power.value())
        max_p = float(self.spin_max_power.value())
        p_steps = self.spin_power_steps.value()

        speeds = [min_s + (max_s - min_s) * i / max(1, s_steps - 1) for i in range(s_steps)]
        powers = [min_p + (max_p - min_p) * i / max(1, p_steps - 1) for i in range(p_steps)]

        test_mode = "Fill"
        if "Line" in self.combo_test_type.currentText():
            test_mode = "Line"
        elif "Both" in self.combo_test_type.currentText():
            test_mode = "Both"

        self.generated_entities = MaterialDatabase.generate_test_matrix_entities(
            speeds=speeds,
            powers=powers,
            swatch_size=self.spin_swatch_size.value(),
            spacing=3.0,
            test_type=test_mode,
            start_x=30.0,
            start_y=30.0
        )
        self.accept()


class MaterialLibraryDialog(QDialog):
    """Interactive Material Library & 3W Preset Manager."""

    applied_to_layer = pyqtSignal(MaterialProfile)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("3W Laser Material Library & Calibrated Presets")
        self.resize(940, 580)

        self.db = MaterialDatabase()
        self.selected_profile: Optional[MaterialProfile] = None
        self.test_matrix_entities: List[LaserEntity] = []

        self._init_ui()
        self._populate_categories()
        self._populate_list()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # -------------------------------------------------------------
        # LEFT PANE: Category Filter & Material Profiles List
        # -------------------------------------------------------------
        left_widget = QWidget()
        left_widget.setFixedWidth(370)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Category:"))
        self.combo_cat = QComboBox()
        self.combo_cat.currentIndexChanged.connect(self._on_category_changed)
        cat_row.addWidget(self.combo_cat, 1)
        left_layout.addLayout(cat_row)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search materials...")
        self.search_box.textChanged.connect(self._on_search_changed)
        left_layout.addWidget(self.search_box)

        self.list_materials = QListWidget()
        self.list_materials.currentItemChanged.connect(self._on_item_selected)
        left_layout.addWidget(self.list_materials, 1)

        splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # RIGHT PANE: Parameter Details & Action Buttons
        # -------------------------------------------------------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 4, 0)
        right_layout.setSpacing(8)

        self.lbl_mat_title = QLabel("Select a Material Profile")
        self.lbl_mat_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #00e5ff;")
        right_layout.addWidget(self.lbl_mat_title)

        # Detail parameters box
        detail_group = QGroupBox("Calibrated 3W Diode Laser Settings")
        detail_grid = QGridLayout(detail_group)
        detail_grid.setSpacing(8)
        detail_grid.setColumnStretch(1, 1)
        detail_grid.setColumnStretch(3, 1)

        detail_grid.addWidget(QLabel("Operation:"), 0, 0)
        self.lbl_op = QLabel("-")
        self.lbl_op.setStyleSheet("font-weight: bold;")
        detail_grid.addWidget(self.lbl_op, 0, 1)

        detail_grid.addWidget(QLabel("Cut Mode:"), 0, 2)
        self.lbl_mode = QLabel("-")
        self.lbl_mode.setStyleSheet("font-weight: bold;")
        detail_grid.addWidget(self.lbl_mode, 0, 3)

        detail_grid.addWidget(QLabel("Speed:"), 1, 0)
        self.lbl_speed = QLabel("-")
        self.lbl_speed.setStyleSheet("color: #81d4fa; font-family: monospace; font-weight: bold;")
        detail_grid.addWidget(self.lbl_speed, 1, 1)

        detail_grid.addWidget(QLabel("Power:"), 1, 2)
        self.lbl_power = QLabel("-")
        self.lbl_power.setStyleSheet("color: #ff8a80; font-family: monospace; font-weight: bold;")
        detail_grid.addWidget(self.lbl_power, 1, 3)

        detail_grid.addWidget(QLabel("Passes:"), 2, 0)
        self.lbl_passes = QLabel("-")
        detail_grid.addWidget(self.lbl_passes, 2, 1)

        detail_grid.addWidget(QLabel("Line Interval:"), 2, 2)
        self.lbl_interval = QLabel("-")
        detail_grid.addWidget(self.lbl_interval, 2, 3)

        detail_grid.addWidget(QLabel("Pass Delay (Cooling):"), 3, 0)
        self.lbl_delay = QLabel("-")
        detail_grid.addWidget(self.lbl_delay, 3, 1)

        detail_grid.addWidget(QLabel("Air Assist:"), 3, 2)
        self.lbl_air = QLabel("-")
        detail_grid.addWidget(self.lbl_air, 3, 3)

        right_layout.addWidget(detail_group)

        # Notes & Guidance
        desc_group = QGroupBox("3W Laser Operational Tips && Notes")
        desc_layout = QVBoxLayout(desc_group)
        self.lbl_desc = QLabel("No material selected.")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #cfd8dc; font-size: 11px;")
        desc_layout.addWidget(self.lbl_desc)
        right_layout.addWidget(desc_group)

        right_layout.addStretch(1)

        # Action Buttons
        btn_apply = QPushButton("✔  Apply to Active Layer")
        btn_apply.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 9px; font-size: 12px; border-radius: 4px;"
        )
        btn_apply.clicked.connect(self._apply_to_layer)
        right_layout.addWidget(btn_apply)

        btn_matrix = QPushButton("📊  Generate Material Test Matrix (Power vs Speed)...")
        btn_matrix.setStyleSheet("font-weight: bold; padding: 7px;")
        btn_matrix.clicked.connect(self._open_test_matrix_dialog)
        right_layout.addWidget(btn_matrix)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        right_layout.addWidget(btn_close)

        splitter.addWidget(right_widget)
        main_layout.addWidget(splitter)

    def _populate_categories(self):
        self.combo_cat.clear()
        self.combo_cat.addItem("All Categories")
        for cat in self.db.get_categories():
            self.combo_cat.addItem(cat)

    def _populate_list(self):
        self.list_materials.clear()
        cat = self.combo_cat.currentText()
        query = self.search_box.text().lower().strip()

        for mat in self.db.materials:
            if cat != "All Categories" and mat.category != cat:
                continue
            if query and query not in mat.name.lower() and query not in mat.description.lower():
                continue

            item = QListWidgetItem(f"{mat.name} ({mat.operation})")
            item.setData(Qt.ItemDataRole.UserRole, mat)
            self.list_materials.addItem(item)

        if self.list_materials.count() > 0:
            self.list_materials.setCurrentRow(0)

    def _on_category_changed(self):
        self._populate_list()

    def _on_search_changed(self):
        self._populate_list()

    def _on_item_selected(self, current: Optional[QListWidgetItem]):
        if not current:
            return
        mat: MaterialProfile = current.data(Qt.ItemDataRole.UserRole)
        self.selected_profile = mat

        self.lbl_mat_title.setText(f"{mat.name}")
        self.lbl_op.setText(mat.operation)
        self.lbl_mode.setText(mat.mode)
        self.lbl_speed.setText(f"{mat.speed:.0f} mm/min")
        self.lbl_power.setText(f"{mat.power_pct:.0f}%")
        self.lbl_passes.setText(f"{mat.passes} pass(es)")
        self.lbl_interval.setText(f"{mat.line_interval:.3f} mm")
        self.lbl_delay.setText(f"{mat.pass_delay_sec:.1f} s" if mat.pass_delay_sec > 0 else "None")
        self.lbl_air.setText("Enabled (M8)" if mat.air_assist else "Disabled")
        self.lbl_desc.setText(mat.description or "Calibrated for 3W blue diode (450nm) lasers.")

    def _apply_to_layer(self):
        if not self.selected_profile:
            return
        self.applied_to_layer.emit(self.selected_profile)
        self.accept()

    def _open_test_matrix_dialog(self):
        dlg = TestMatrixDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.generated_entities:
            self.test_matrix_entities = dlg.generated_entities
            self.accept()
