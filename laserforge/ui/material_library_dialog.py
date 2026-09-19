"""
LaserForge Material Library, Community Presets & Test Matrix Studio Dialog.

Features:
1. Multi-technology laser support: Blue Diode (3W-40W), CO2 (40W-100W), Fiber/MOPA (20W-50W).
2. Curated Community Preset Pack Browser with 1-click import into active local library.
3. Import and export of portable Material Preset Packs (.lfmat / .lfpak).
4. Custom material profile management and persistence (~/.laserforge_materials.json).
5. Automated parametric power vs. speed test matrix generator.
"""

from typing import Optional, List
import os

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QComboBox, QGroupBox, QSplitter, QListWidget, QListWidgetItem,
    QMessageBox, QDialogButtonBox, QFormLayout, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.materials_database import (
    MaterialDatabase, MaterialProfile
)
from laserforge.core.community_presets import (
    CommunityPresetCatalog, MaterialPresetPack
)
from laserforge.core.models import LaserEntity


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

        note = QLabel(
            "<i>Fits perfectly on a scrap metal business card blank or wood coupon.<br>"
            "Running this test finds your laser's exact sweet spot in minutes.</i>"
        )
        note.setStyleSheet("color: #90a4ae; font-size: 11px;")
        layout.addWidget(note)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._generate_matrix)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _generate_matrix(self):
        min_s = self.spin_min_speed.value()
        max_s = self.spin_max_speed.value()
        steps_s = self.spin_speed_steps.value()
        step_val_s = (max_s - min_s) / (steps_s - 1) if steps_s > 1 else 0
        speeds = [min_s + i * step_val_s for i in range(steps_s)]

        min_p = self.spin_min_power.value()
        max_p = self.spin_max_power.value()
        steps_p = self.spin_power_steps.value()
        step_val_p = (max_p - min_p) / (steps_p - 1) if steps_p > 1 else 0
        powers = [min_p + i * step_val_p for i in range(steps_p)]

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

    def _generate(self):
        """Backwards compatibility alias for _generate_matrix."""
        self._generate_matrix()


class CommunityPackBrowserDialog(QDialog):
    """Browser for official and community curated material preset packs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 Curated Community Material Packs")
        self.resize(800, 500)
        self.packs = CommunityPresetCatalog.get_all_curated_packs()
        self.selected_pack: Optional[MaterialPresetPack] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left list of packs
        left_box = QGroupBox("Available Packs")
        v_left = QVBoxLayout(left_box)
        self.list_packs = QListWidget()
        self.list_packs.currentItemChanged.connect(self._on_pack_selected)
        for p in self.packs:
            item = QListWidgetItem(f"📦 {p.pack_name}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list_packs.addItem(item)
        v_left.addWidget(self.list_packs)
        splitter.addWidget(left_box)

        # Right preview of pack contents
        right_box = QGroupBox("Pack Information & Contents")
        v_right = QVBoxLayout(right_box)

        self.lbl_title = QLabel("Select a Pack")
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #00e5ff;")
        v_right.addWidget(self.lbl_title)

        self.lbl_meta = QLabel("-")
        self.lbl_meta.setStyleSheet("color: #90a4ae; font-size: 11px;")
        v_right.addWidget(self.lbl_meta)

        self.lbl_desc = QLabel("-")
        self.lbl_desc.setWordWrap(True)
        v_right.addWidget(self.lbl_desc)

        # Table of materials inside
        self.tbl_materials = QTableWidget(0, 4)
        self.tbl_materials.setHorizontalHeaderLabels(["Material Name", "Category", "Operation", "Speed / Power"])
        self.tbl_materials.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_materials.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_materials.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_materials.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_materials.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        v_right.addWidget(self.tbl_materials, 1)

        splitter.addWidget(right_box)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        layout.addWidget(splitter, 1)

        # Bottom row
        bottom_row = QHBoxLayout()
        self.chk_overwrite = QCheckBox("Overwrite existing material profiles with same ID")
        self.chk_overwrite.setChecked(True)
        bottom_row.addWidget(self.chk_overwrite)
        bottom_row.addStretch()

        self.btn_import = QPushButton("📥 Import Pack into My Library")
        self.btn_import.setStyleSheet("background-color: #00c853; color: white; font-weight: bold; padding: 6px 14px;")
        self.btn_import.clicked.connect(self._import_clicked)
        bottom_row.addWidget(self.btn_import)

        btn_cancel = QPushButton("Close")
        btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(btn_cancel)

        layout.addLayout(bottom_row)

        if self.list_packs.count() > 0:
            self.list_packs.setCurrentRow(0)

    def _on_pack_selected(self, current: Optional[QListWidgetItem]):
        if not current:
            return
        pack: MaterialPresetPack = current.data(Qt.ItemDataRole.UserRole)
        self.selected_pack = pack
        self.lbl_title.setText(pack.pack_name)
        laser_types_str = ", ".join(pack.laser_types) if pack.laser_types else "All Lasers"
        self.lbl_meta.setText(f"Author: {pack.author}  |  Version: {pack.version}  |  Laser: {laser_types_str}")
        self.lbl_desc.setText(pack.description or "Curated factory and community calibrations.")

        self.tbl_materials.setRowCount(len(pack.materials))
        for row, mat in enumerate(pack.materials):
            self.tbl_materials.setItem(row, 0, QTableWidgetItem(mat.name))
            self.tbl_materials.setItem(row, 1, QTableWidgetItem(mat.category))
            self.tbl_materials.setItem(row, 2, QTableWidgetItem(mat.operation))
            spd_pwr = f"{mat.speed:.0f} mm/min @ {mat.power_pct:.0f}%"
            self.tbl_materials.setItem(row, 3, QTableWidgetItem(spd_pwr))

    def _import_clicked(self):
        if not self.selected_pack:
            return
        self.accept()


class MaterialLibraryDialog(QDialog):
    """Interactive Material Library, Multi-Laser Presets & Community Sharing Studio."""

    applied_to_layer = pyqtSignal(MaterialProfile)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📚 LaserForge Material Library & Multi-Laser Presets")
        self.resize(1000, 620)

        self.db = MaterialDatabase()
        self.selected_profile: Optional[MaterialProfile] = None
        self.test_matrix_entities: List[LaserEntity] = []

        self._init_ui()
        self._populate_laser_types()
        self._populate_categories()
        self._populate_list()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # -------------------------------------------------------------
        # LEFT PANE: Filters, Search, Material List & Pack Management
        # -------------------------------------------------------------
        left_widget = QWidget()
        left_widget.setFixedWidth(400)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # Technology filter
        tech_row = QHBoxLayout()
        tech_row.addWidget(QLabel("Laser Type:"))
        self.combo_laser = QComboBox()
        self.combo_laser.currentIndexChanged.connect(self._on_filter_changed)
        tech_row.addWidget(self.combo_laser, 1)
        left_layout.addLayout(tech_row)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Category:"))
        self.combo_cat = QComboBox()
        self.combo_cat.currentIndexChanged.connect(self._on_filter_changed)
        cat_row.addWidget(self.combo_cat, 1)
        left_layout.addLayout(cat_row)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search materials, operations, tags...")
        self.search_box.textChanged.connect(self._on_filter_changed)
        left_layout.addWidget(self.search_box)

        self.list_materials = QListWidget()
        self.list_materials.currentItemChanged.connect(self._on_item_selected)
        left_layout.addWidget(self.list_materials, 1)

        # Community & Pack Buttons
        pack_btn_row = QHBoxLayout()
        self.btn_community = QPushButton("🌐 Community Packs...")
        self.btn_community.setStyleSheet("font-weight: bold; color: #00e5ff;")
        self.btn_community.clicked.connect(self._open_community_packs)
        pack_btn_row.addWidget(self.btn_community)

        self.btn_import_pack = QPushButton("📥 Import Pack...")
        self.btn_import_pack.clicked.connect(self._import_pack_file)
        pack_btn_row.addWidget(self.btn_import_pack)

        self.btn_export_pack = QPushButton("📤 Export Pack...")
        self.btn_export_pack.clicked.connect(self._export_pack_file)
        pack_btn_row.addWidget(self.btn_export_pack)

        left_layout.addLayout(pack_btn_row)

        splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # RIGHT PANE: Parameter Details & Action Buttons
        # -------------------------------------------------------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 0, 4, 0)
        right_layout.setSpacing(8)

        self.lbl_mat_title = QLabel("Select a Material Profile")
        self.lbl_mat_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #00e5ff;")
        right_layout.addWidget(self.lbl_mat_title)

        # Detail parameters box
        detail_group = QGroupBox("Calibrated Laser Settings")
        detail_grid = QGridLayout(detail_group)
        detail_grid.setSpacing(8)
        detail_grid.setColumnStretch(1, 1)
        detail_grid.setColumnStretch(3, 1)

        detail_grid.addWidget(QLabel("Laser Type:"), 0, 0)
        self.lbl_laser_info = QLabel("-")
        self.lbl_laser_info.setStyleSheet("color: #ffab40; font-weight: bold;")
        detail_grid.addWidget(self.lbl_laser_info, 0, 1)

        detail_grid.addWidget(QLabel("Author:"), 0, 2)
        self.lbl_author = QLabel("-")
        self.lbl_author.setStyleSheet("color: #b0bec5;")
        detail_grid.addWidget(self.lbl_author, 0, 3)

        detail_grid.addWidget(QLabel("Operation:"), 1, 0)
        self.lbl_op = QLabel("-")
        self.lbl_op.setStyleSheet("font-weight: bold;")
        detail_grid.addWidget(self.lbl_op, 1, 1)

        detail_grid.addWidget(QLabel("Cut Mode:"), 1, 2)
        self.lbl_mode = QLabel("-")
        self.lbl_mode.setStyleSheet("font-weight: bold;")
        detail_grid.addWidget(self.lbl_mode, 1, 3)

        detail_grid.addWidget(QLabel("Speed:"), 2, 0)
        self.lbl_speed = QLabel("-")
        self.lbl_speed.setStyleSheet("color: #81d4fa; font-family: monospace; font-weight: bold;")
        detail_grid.addWidget(self.lbl_speed, 2, 1)

        detail_grid.addWidget(QLabel("Power:"), 2, 2)
        self.lbl_power = QLabel("-")
        self.lbl_power.setStyleSheet("color: #ff8a80; font-family: monospace; font-weight: bold;")
        detail_grid.addWidget(self.lbl_power, 2, 3)

        detail_grid.addWidget(QLabel("Passes:"), 3, 0)
        self.lbl_passes = QLabel("-")
        detail_grid.addWidget(self.lbl_passes, 3, 1)

        detail_grid.addWidget(QLabel("Line Interval:"), 3, 2)
        self.lbl_interval = QLabel("-")
        detail_grid.addWidget(self.lbl_interval, 3, 3)

        detail_grid.addWidget(QLabel("Pass Delay (Cooling):"), 4, 0)
        self.lbl_delay = QLabel("-")
        detail_grid.addWidget(self.lbl_delay, 4, 1)

        detail_grid.addWidget(QLabel("Air Assist:"), 4, 2)
        self.lbl_air = QLabel("-")
        detail_grid.addWidget(self.lbl_air, 4, 3)

        right_layout.addWidget(detail_group)

        # Notes & Guidance
        desc_group = QGroupBox("Operational Notes && Material Calibration Tips")
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

    def _populate_laser_types(self):
        self.combo_laser.clear()
        self.combo_laser.addItem("All Laser Types")
        self.combo_laser.addItem("Diode (450nm)")
        self.combo_laser.addItem("CO2 (10.6um)")
        self.combo_laser.addItem("Fiber / MOPA (1064nm)")

    def _populate_categories(self):
        self.combo_cat.clear()
        self.combo_cat.addItem("All Categories")
        for cat in self.db.get_categories():
            self.combo_cat.addItem(cat)

    def _populate_list(self):
        self.list_materials.clear()
        selected_tech = self.combo_laser.currentText()
        cat = self.combo_cat.currentText()
        query = self.search_box.text().lower().strip()

        for mat in self.db.materials:
            # Laser type filter
            if selected_tech != "All Laser Types":
                mat_tech = getattr(mat, 'laser_type', 'Diode (450nm)')
                if mat_tech != selected_tech:
                    continue

            # Category filter
            if cat != "All Categories" and mat.category != cat:
                continue

            # Keyword search
            if query:
                mat_desc = getattr(mat, 'description', '')
                if (query not in mat.name.lower() and
                    query not in mat_desc.lower() and
                    query not in mat.category.lower()):
                    continue

            badge = " [CO2]" if "CO2" in getattr(mat, 'laser_type', '') else (" [Fiber]" if "Fiber" in getattr(mat, 'laser_type', '') else "")
            item = QListWidgetItem(f"{mat.name} ({mat.operation}){badge}")
            item.setData(Qt.ItemDataRole.UserRole, mat)
            self.list_materials.addItem(item)

        if self.list_materials.count() > 0:
            self.list_materials.setCurrentRow(0)

    def _on_filter_changed(self):
        self._populate_list()

    def _on_item_selected(self, current: Optional[QListWidgetItem]):
        if not current:
            return
        mat: MaterialProfile = current.data(Qt.ItemDataRole.UserRole)
        self.selected_profile = mat

        self.lbl_mat_title.setText(f"{mat.name}")
        laser_t = getattr(mat, 'laser_type', 'Diode (450nm)')
        laser_w = getattr(mat, 'laser_wattage', 3.0)
        self.lbl_laser_info.setText(f"{laser_t} ({laser_w:.0f}W)")
        self.lbl_author.setText(getattr(mat, 'author', 'LaserForge Community'))

        self.lbl_op.setText(mat.operation)
        self.lbl_mode.setText(mat.mode)
        self.lbl_speed.setText(f"{mat.speed:.0f} mm/min")
        self.lbl_power.setText(f"{mat.power_pct:.0f}%")
        self.lbl_passes.setText(f"{mat.passes} pass(es)")
        self.lbl_interval.setText(f"{mat.line_interval:.3f} mm")
        self.lbl_delay.setText(f"{mat.pass_delay_sec:.1f} s" if mat.pass_delay_sec > 0 else "None")
        self.lbl_air.setText("Enabled (M8)" if mat.air_assist else "Disabled")
        self.lbl_desc.setText(mat.description or f"Calibrated for {laser_t}.")

    def _open_community_packs(self):
        dlg = CommunityPackBrowserDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_pack:
            overwrite = dlg.chk_overwrite.isChecked()
            added, updated = CommunityPresetCatalog.import_pack_into_database(
                dlg.selected_pack, self.db, overwrite=overwrite
            )
            self._populate_categories()
            self._populate_list()
            QMessageBox.information(
                self,
                "Pack Imported",
                f"Successfully imported '{dlg.selected_pack.pack_name}'!\n"
                f"Added {added} new profiles, updated {updated} existing profiles."
            )

    def _import_pack_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import LaserForge Material Pack",
            os.path.expanduser("~"),
            "LaserForge Material Packs (*.lfmat *.lfpak *.json);;All Files (*)"
        )
        if not path:
            return
        try:
            pack = MaterialPresetPack.load_from_file(path)
            added, updated = CommunityPresetCatalog.import_pack_into_database(pack, self.db, overwrite=True)
            self._populate_categories()
            self._populate_list()
            QMessageBox.information(
                self,
                "Import Successful",
                f"Imported pack '{pack.pack_name}' by {pack.author}.\n"
                f"Added: {added} | Updated: {updated}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import material pack: {e}")

    def _export_pack_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export LaserForge Material Pack",
            os.path.expanduser("~/My_Laser_Materials.lfmat"),
            "LaserForge Material Pack (*.lfmat);;JSON Files (*.json)"
        )
        if not path:
            return
        try:
            pack = CommunityPresetCatalog.export_database_to_pack(
                db=self.db,
                pack_name="Custom LaserForge Material Library",
                author="Local User",
                description="Exported material profiles from LaserForge.",
                path=path
            )
            QMessageBox.information(
                self,
                "Export Complete",
                f"Successfully exported {len(pack.materials)} material profiles to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export material pack: {e}")

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
