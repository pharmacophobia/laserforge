"""
LaserForge Project & Calibrated Profile Bundle (.lfpak) Studio Dialog.
Enables workshop backup, cross-machine deployment, and one-click package sharing.
"""

from typing import List, Optional, Dict, Any
import os
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QTextEdit, QCheckBox, QPushButton, QGroupBox, QTabWidget,
    QFileDialog, QMessageBox, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal

from laserforge.core.bundle_packager import BundlePackager, BundleManifest
from laserforge.core.models import LaserEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.materials_database import MaterialDatabase
from laserforge.config import MachineSettings


class BundlePackagerDialog(QDialog):
    """Project & Profile Packager Studio (.lfpak) Dialog."""

    project_restored = pyqtSignal(dict)
    materials_restored = pyqtSignal(int)
    settings_restored = pyqtSignal(dict)

    def __init__(
        self,
        current_entities: Optional[List[LaserEntity]] = None,
        layer_manager: Optional[LayerManager] = None,
        machine_settings: Optional[MachineSettings] = None,
        parent=None
    ):
        super().__init__(parent)
        self.current_entities = current_entities or []
        self.layer_manager = layer_manager
        self.machine_settings = machine_settings
        self.material_db = MaterialDatabase()
        self.inspected_bundle_path: Optional[str] = None

        self.setWindowTitle("Project & Profile Packager Studio (.lfpak) 📦")
        self.resize(580, 560)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # -------------------------------------------------------------
        # TAB 1: EXPORT BUNDLE
        # -------------------------------------------------------------
        tab_export = QWidget()
        exp_layout = QVBoxLayout(tab_export)

        # Metadata Group
        grp_meta = QGroupBox("Package Metadata")
        m_grid = QGridLayout(grp_meta)

        m_grid.addWidget(QLabel("Package Name:"), 0, 0)
        self.edit_pkg_name = QLineEdit("My-LaserForge-Project")
        m_grid.addWidget(self.edit_pkg_name, 0, 1)

        m_grid.addWidget(QLabel("Author / Studio:"), 1, 0)
        self.edit_author = QLineEdit("Maker")
        m_grid.addWidget(self.edit_author, 1, 1)

        m_grid.addWidget(QLabel("Description / Notes:"), 2, 0)
        self.edit_notes = QTextEdit()
        self.edit_notes.setPlaceholderText("Project notes, material stock recommendations, focal height...")
        self.edit_notes.setMaximumHeight(60)
        m_grid.addWidget(self.edit_notes, 2, 1)

        exp_layout.addWidget(grp_meta)

        # Contents Selection Group
        grp_contents = QGroupBox("Select Components to Include")
        c_layout = QVBoxLayout(grp_contents)

        self.chk_exp_project = QCheckBox(f"Active Canvas Artwork ({len(self.current_entities)} objects)")
        self.chk_exp_project.setChecked(len(self.current_entities) > 0)
        c_layout.addWidget(self.chk_exp_project)

        mat_count = len(self.material_db.get_all())
        self.chk_exp_materials = QCheckBox(f"Material Presets Library ({mat_count} calibrated profiles)")
        self.chk_exp_materials.setChecked(True)
        c_layout.addWidget(self.chk_exp_materials)

        bed_desc = f"{self.machine_settings.bed_width}x{self.machine_settings.bed_height}mm" if self.machine_settings else "Active Bed"
        self.chk_exp_settings = QCheckBox(f"Machine & GRBL Hardware Profile ({bed_desc})")
        self.chk_exp_settings.setChecked(False)
        c_layout.addWidget(self.chk_exp_settings)

        self.chk_exp_templates = QCheckBox("Living Hinge & Box Enclosure Templates")
        self.chk_exp_templates.setChecked(True)
        c_layout.addWidget(self.chk_exp_templates)

        exp_layout.addWidget(grp_contents)
        exp_layout.addStretch()

        btn_export = QPushButton("Export .lfpak Bundle Archive 💾")
        btn_export.setStyleSheet("font-weight: bold; background-color: #059669; color: white; padding: 10px 18px; font-size: 13px;")
        btn_export.clicked.connect(self._do_export)
        exp_layout.addWidget(btn_export)

        tabs.addTab(tab_export, "📤 Export Bundle (.lfpak)")

        # -------------------------------------------------------------
        # TAB 2: IMPORT / RESTORE BUNDLE
        # -------------------------------------------------------------
        tab_import = QWidget()
        imp_layout = QVBoxLayout(tab_import)

        # File Chooser
        grp_file = QGroupBox("Select Package Archive")
        f_layout = QHBoxLayout(grp_file)
        self.lbl_import_path = QLabel("No .lfpak bundle selected.")
        self.lbl_import_path.setStyleSheet("color: #94a3b8;")
        f_layout.addWidget(self.lbl_import_path)

        btn_browse = QPushButton("Browse .lfpak...")
        btn_browse.clicked.connect(self._browse_import_bundle)
        f_layout.addWidget(btn_browse)
        imp_layout.addWidget(grp_file)

        # Inspection Overview
        grp_insp = QGroupBox("Bundle Manifest & Integrity")
        self.i_layout = QVBoxLayout(grp_insp)
        self.lbl_insp_summary = QLabel("Select a bundle file to inspect its contents and cryptographic SHA256 checksums.")
        self.lbl_insp_summary.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        self.lbl_insp_summary.setWordWrap(True)
        self.i_layout.addWidget(self.lbl_insp_summary)
        imp_layout.addWidget(grp_insp)

        # Selective Restoration Options
        grp_restore = QGroupBox("Selective Restoration Options")
        r_layout = QVBoxLayout(grp_restore)

        self.chk_imp_project = QCheckBox("Restore Canvas Project (replaces active canvas artwork)")
        self.chk_imp_project.setChecked(True)
        r_layout.addWidget(self.chk_imp_project)

        self.chk_imp_materials = QCheckBox("Import Calibrated Material Presets")
        self.chk_imp_materials.setChecked(True)
        r_layout.addWidget(self.chk_imp_materials)

        # Materials Conflict Strategy
        mat_opts_layout = QHBoxLayout()
        mat_opts_layout.setContentsMargins(20, 0, 0, 0)
        self.rb_merge = QRadioButton("Merge with existing presets (keep current)")
        self.rb_merge.setChecked(True)
        self.rb_overwrite = QRadioButton("Overwrite / Replace entire database")
        mat_opts_layout.addWidget(self.rb_merge)
        mat_opts_layout.addWidget(self.rb_overwrite)
        r_layout.addLayout(mat_opts_layout)

        self.chk_imp_settings = QCheckBox("Apply Hardware Machine Settings (Bed Dimensions, Accelerations)")
        self.chk_imp_settings.setChecked(False)
        r_layout.addWidget(self.chk_imp_settings)

        self.chk_imp_templates = QCheckBox("Import Design Templates")
        self.chk_imp_templates.setChecked(True)
        r_layout.addWidget(self.chk_imp_templates)

        imp_layout.addWidget(grp_restore)
        imp_layout.addStretch()

        self.btn_import = QPushButton("Restore Selected Components 🚀")
        self.btn_import.setEnabled(False)
        self.btn_import.setStyleSheet("font-weight: bold; background-color: #2563eb; color: white; padding: 10px 18px; font-size: 13px;")
        self.btn_import.clicked.connect(self._do_import)
        imp_layout.addWidget(self.btn_import)

        tabs.addTab(tab_import, "📥 Import / Restore (.lfpak)")

        layout.addWidget(tabs)

        # Dialog Close
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _do_export(self):
        default_name = self.edit_pkg_name.text().strip() or "bundle"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save LaserForge Package Bundle", f"{default_name}.lfpak", "LaserForge Bundle (*.lfpak)"
        )
        if not file_path:
            return

        proj_ents = self.current_entities if self.chk_exp_project.isChecked() else None
        mats = self.material_db.get_all() if self.chk_exp_materials.isChecked() else None
        ms = self.machine_settings if self.chk_exp_settings.isChecked() else None
        tmpls = [{"name": "living_hinge_standard", "type": "flex"}] if self.chk_exp_templates.isChecked() else None

        try:
            res = BundlePackager.export_bundle(
                export_path=file_path,
                project_entities=proj_ents,
                layer_manager=self.layer_manager,
                machine_settings=ms,
                materials=mats,
                templates=tmpls,
                bundle_name=self.edit_pkg_name.text().strip(),
                author=self.edit_author.text().strip(),
                notes=self.edit_notes.toPlainText().strip()
            )
            QMessageBox.information(
                self, "Export Successful",
                f"<h3>Package Bundle Created</h3>"
                f"<p><b>Archive:</b> {os.path.basename(file_path)}</p>"
                f"<p><b>Size:</b> {res['file_size_kb']} KB</p>"
                f"<p><b>Checksums:</b> {len(res['manifest'].checksums)} files verified with SHA256.</p>"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export bundle: {e}")

    def _browse_import_bundle(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select LaserForge Package Bundle", "", "LaserForge Bundle (*.lfpak);;All Files (*)"
        )
        if not file_path:
            return

        self.inspected_bundle_path = file_path
        self.lbl_import_path.setText(os.path.basename(file_path))
        self.lbl_import_path.setStyleSheet("color: #38bdf8; font-weight: bold;")

        inspection = BundlePackager.inspect_bundle(file_path)
        if not inspection.get("valid", False):
            QMessageBox.critical(self, "Invalid Bundle", f"Bundle inspection failed:\n{inspection.get('error')}")
            self.btn_import.setEnabled(False)
            return

        manifest: BundleManifest = inspection["manifest"]
        summary_lines = [
            f"<b>Package:</b> {manifest.bundle_name} (v{manifest.app_version})",
            f"<b>Author:</b> {manifest.author} | <b>Created:</b> {manifest.created_at[:10]}",
            f"<b>Integrity:</b> ✅ All SHA256 Checksums Verified ({len(manifest.checksums)} files)",
            f"<b>Contents:</b>"
        ]
        if manifest.has_project:
            summary_lines.append(f" • Canvas Artwork: {manifest.contents_summary.get('entities_count', 0)} shapes across {manifest.contents_summary.get('layers_count', 0)} layers")
        if manifest.has_materials:
            summary_lines.append(f" • Material Presets: {manifest.contents_summary.get('materials_count', 0)} profiles")
        if manifest.has_machine_settings:
            summary_lines.append(f" • Machine Profile: {manifest.contents_summary.get('machine_bed', 'N/A')}")
        if manifest.notes:
            summary_lines.append(f"<b>Notes:</b> <i>{manifest.notes}</i>")

        self.lbl_insp_summary.setText("<br>".join(summary_lines))
        self.chk_imp_project.setEnabled(manifest.has_project)
        self.chk_imp_materials.setEnabled(manifest.has_materials)
        self.chk_imp_settings.setEnabled(manifest.has_machine_settings)
        self.chk_imp_templates.setEnabled(manifest.has_templates)
        self.btn_import.setEnabled(True)

    def _do_import(self):
        if not self.inspected_bundle_path:
            return

        res = BundlePackager.import_bundle(
            bundle_path=self.inspected_bundle_path,
            restore_project=self.chk_imp_project.isChecked(),
            restore_materials=self.chk_imp_materials.isChecked(),
            restore_machine_settings=self.chk_imp_settings.isChecked(),
            restore_templates=self.chk_imp_templates.isChecked(),
            merge_materials=self.rb_merge.isChecked()
        )

        if not res.get("success", False):
            QMessageBox.critical(self, "Import Failed", f"Failed to restore bundle: {res.get('error')}")
            return

        report = []
        if res.get("restored_project") and "project_raw" in res:
            self.project_restored.emit(res["project_raw"])
            report.append("• Canvas project restored.")
        if res.get("restored_materials_count", 0) > 0:
            count = res["restored_materials_count"]
            self.materials_restored.emit(count)
            report.append(f"• {count} material presets imported to library.")
        if res.get("restored_machine_settings") is not None:
            self.settings_restored.emit(res["restored_machine_settings"])
            report.append("• Machine hardware profile updated.")

        QMessageBox.information(
            self, "Restoration Complete",
            f"<h3>Bundle Restored Successfully</h3>"
            + "<br>".join(report)
        )
        self.accept()
