"""
Unit and Integration Tests for LaserForge Project & Profile Packager (.lfpak):
1. Exporting bundles with project artwork, materials, machine settings, and templates
2. Inspecting bundles and verifying cryptographic SHA256 checksums
3. Restoring components and merging material databases
4. MainWindow UI action and shortcut verification
"""

import unittest
import os
import json
import tempfile
import shutil
import zipfile

from PyQt6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.core.models import RectEntity, CircleEntity, PathEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.core.materials_database import MaterialDatabase, MaterialProfile
from laserforge.config import MachineSettings
from laserforge.core.bundle_packager import BundlePackager, BundleManifest
from laserforge.ui.main_window import MainWindow


class TestBundlePackager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.bundle_path = os.path.join(self.test_dir, "test_project.lfpak")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_export_and_inspect_bundle(self):
        """Exporting a bundle produces a valid .lfpak archive with verified SHA256 checksums."""
        # Create test entities
        rect = RectEntity(layer_id=0, name="BaseBox", x=10.0, y=10.0, width=50.0, height=30.0)
        circle = CircleEntity(layer_id=1, name="Hole", x=25.0, y=25.0, radius_x=5.0, radius_y=5.0)
        entities = [rect, circle]

        layer_mgr = LayerManager()
        settings = MachineSettings()
        settings.bed_width = 400.0
        settings.bed_height = 400.0

        materials = [
            MaterialProfile(
                id="custom_wood_3mm",
                name="3mm Birch Plywood Cut",
                category="Wood",
                operation="Vector Cut",
                speed=400.0,
                power_pct=100.0
            )
        ]

        templates = [{"name": "flex_hinge_sample", "pitch": 2.0}]

        # Export bundle
        res = BundlePackager.export_bundle(
            export_path=self.bundle_path,
            project_entities=entities,
            layer_manager=layer_mgr,
            machine_settings=settings,
            materials=materials,
            templates=templates,
            bundle_name="Test-Box-Kit",
            author="TestAuthor",
            notes="Ready to cut on 3W blue diode."
        )

        self.assertTrue(res["success"])
        self.assertTrue(os.path.exists(self.bundle_path))
        self.assertGreater(res["file_size_kb"], 0)

        # Inspect bundle
        inspection = BundlePackager.inspect_bundle(self.bundle_path)
        self.assertTrue(inspection["valid"], inspection.get("error"))

        manifest: BundleManifest = inspection["manifest"]
        self.assertEqual(manifest.bundle_name, "Test-Box-Kit")
        self.assertEqual(manifest.author, "TestAuthor")
        self.assertTrue(manifest.has_project)
        self.assertTrue(manifest.has_materials)
        self.assertTrue(manifest.has_machine_settings)
        self.assertTrue(manifest.has_templates)
        self.assertEqual(manifest.contents_summary["entities_count"], 2)
        self.assertEqual(manifest.contents_summary["materials_count"], 1)

        # Verify all checksums are present
        self.assertIn("project.lfg", manifest.checksums)
        self.assertIn("materials.json", manifest.checksums)
        self.assertIn("machine_settings.json", manifest.checksums)
        self.assertIn("templates.json", manifest.checksums)

    def test_tampered_bundle_checksum_rejection(self):
        """Bundle inspection must fail if any internal component was altered or tampered with."""
        rect = RectEntity(layer_id=0, name="Box", x=0, y=0, width=10, height=10)
        layer_mgr = LayerManager()
        BundlePackager.export_bundle(
            export_path=self.bundle_path,
            project_entities=[rect],
            layer_manager=layer_mgr
        )

        # Tamper with the zip by replacing project.lfg with different content
        tampered_path = os.path.join(self.test_dir, "tampered.lfpak")
        with zipfile.ZipFile(self.bundle_path, "r") as zin:
            with zipfile.ZipFile(tampered_path, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "project.lfg":
                        data = b'{"corrupted": true}'
                    zout.writestr(item, data)

        inspection = BundlePackager.inspect_bundle(tampered_path)
        self.assertFalse(inspection["valid"])
        self.assertIn("Checksum verification failed", inspection["error"])

    def test_import_bundle_restoration(self):
        """Restoring a bundle extracts project, merges materials, and yields machine settings."""
        rect = RectEntity(layer_id=0, name="ImportBox", x=15.0, y=20.0, width=30.0, height=30.0)
        layer_mgr = LayerManager()
        settings = MachineSettings()
        settings.bed_width = 500.0
        settings.bed_height = 300.0

        materials = [
            MaterialProfile(
                id="test_import_mat_id_999",
                name="Special Test Alloy 1mm",
                category="Metal",
                operation="Surface Engrave",
                speed=800.0,
                power_pct=80.0
            )
        ]

        BundlePackager.export_bundle(
            export_path=self.bundle_path,
            project_entities=[rect],
            layer_manager=layer_mgr,
            machine_settings=settings,
            materials=materials
        )

        res = BundlePackager.import_bundle(
            bundle_path=self.bundle_path,
            restore_project=True,
            restore_materials=True,
            restore_machine_settings=True,
            merge_materials=True
        )

        self.assertTrue(res["success"])
        self.assertTrue(res["restored_project"])
        self.assertIn("project_raw", res)
        self.assertEqual(len(res["project_raw"]["entities"]), 1)
        self.assertEqual(res["project_raw"]["entities"][0]["name"], "ImportBox")

        self.assertIsNotNone(res["restored_machine_settings"])
        self.assertEqual(res["restored_machine_settings"]["bed_width"], 500.0)
        self.assertEqual(res["restored_machine_settings"]["bed_height"], 300.0)

        # Verify material was added to database
        db = MaterialDatabase()
        mat_ids = {m.id for m in db.get_all()}
        self.assertIn("test_import_mat_id_999", mat_ids)
        # Clean up
        db.delete_material("test_import_mat_id_999")

    def test_main_window_action(self):
        """MainWindow must have act_bundle_packager wired to Ctrl+Shift+P."""
        win = MainWindow()
        self.assertTrue(hasattr(win, "act_bundle_packager"))
        self.assertEqual(win.act_bundle_packager.shortcut().toString(), "Ctrl+Shift+P")
        win.close()


if __name__ == "__main__":
    unittest.main()
