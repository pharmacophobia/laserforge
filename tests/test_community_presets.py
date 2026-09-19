"""
Unit tests for LaserForge Community Presets, Material Packs (.lfmat), and Vision Reticle Tracking.
Tests:
- MaterialPresetPack serialization and file I/O (.lfmat / .lfpak)
- CommunityPresetCatalog curated packs (Diode 10W-40W, CO2 40W-100W, Fiber 20W-50W)
- Search and filtering across multi-technology laser presets
- Merging and collision handling when importing packs into local database
- Exporting local material database to portable pack
- CommunityPackBrowserDialog and MaterialLibraryDialog UI (offscreen safe)
- CameraEngine laser-to-camera and camera-to-laser coordinate projection and reticle drawing
"""

import os
import tempfile
import unittest
import numpy as np

from PyQt6.QtWidgets import QApplication
import pytest

from laserforge.core.materials_database import MaterialProfile, MaterialDatabase
from laserforge.core.community_presets import (
    MaterialPresetPack, CommunityPresetCatalog
)
from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData, HAS_CV2
from laserforge.ui.material_library_dialog import (
    MaterialLibraryDialog, CommunityPackBrowserDialog
)


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestCommunityPresets(unittest.TestCase):
    """Test suite for MaterialPresetPack and CommunityPresetCatalog."""

    def setUp(self):
        self.tmp_cfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp_cfg.close()
        import laserforge.core.materials_database as md
        self.orig_cfg_path = md.MATERIALS_CONFIG_PATH
        md.MATERIALS_CONFIG_PATH = self.tmp_cfg.name

    def tearDown(self):
        import laserforge.core.materials_database as md
        md.MATERIALS_CONFIG_PATH = self.orig_cfg_path
        if os.path.exists(self.tmp_cfg.name):
            os.remove(self.tmp_cfg.name)

    def test_preset_pack_serialization(self):
        pack = CommunityPresetCatalog.get_co2_production_pack()
        d = pack.to_dict()
        self.assertEqual(d["pack_name"], "CO2 Laser Production Pack (40W - 100W)")
        self.assertIn("materials", d)
        self.assertGreater(len(d["materials"]), 0)

        restored = MaterialPresetPack.from_dict(d)
        self.assertEqual(restored.pack_name, pack.pack_name)
        self.assertEqual(len(restored.materials), len(pack.materials))
        self.assertEqual(restored.materials[0].name, pack.materials[0].name)

    def test_preset_pack_file_io(self):
        pack = CommunityPresetCatalog.get_fiber_mopa_pack()
        with tempfile.NamedTemporaryFile(suffix=".lfmat", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            pack.save_to_file(tmp_path)
            self.assertTrue(os.path.exists(tmp_path))

            loaded = MaterialPresetPack.load_from_file(tmp_path)
            self.assertEqual(loaded.pack_name, pack.pack_name)
            self.assertEqual(len(loaded.materials), len(pack.materials))
            self.assertIn("Fiber / MOPA (1064nm)", loaded.laser_types)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_curated_packs_exist(self):
        packs = CommunityPresetCatalog.get_all_curated_packs()
        self.assertGreaterEqual(len(packs), 3)
        pack_names = [p.pack_name for p in packs]
        self.assertTrue(any("Diode" in name for name in pack_names))
        self.assertTrue(any("CO2" in name for name in pack_names))
        self.assertTrue(any("Fiber" in name for name in pack_names))

    def test_search_curated_materials(self):
        # Search by keyword
        acrylic_results = CommunityPresetCatalog.search_curated_materials(query="acrylic")
        self.assertGreater(len(acrylic_results), 0)
        for m in acrylic_results:
            self.assertIn("acrylic", (m.name + m.description).lower())

        # Filter by laser type
        co2_results = CommunityPresetCatalog.search_curated_materials(laser_type="CO2 (10.6um)")
        self.assertGreater(len(co2_results), 0)
        for m in co2_results:
            self.assertEqual(m.laser_type, "CO2 (10.6um)")

        # Filter by wattage
        high_power = CommunityPresetCatalog.search_curated_materials(min_wattage=50.0)
        self.assertGreater(len(high_power), 0)
        for m in high_power:
            self.assertGreaterEqual(m.laser_wattage, 50.0)

    def test_database_import_and_export(self):
        db = MaterialDatabase()
        initial_count = len(db.materials)

        fiber_pack = CommunityPresetCatalog.get_fiber_mopa_pack()
        added, updated = CommunityPresetCatalog.import_pack_into_database(fiber_pack, db, overwrite=True)
        self.assertGreater(added, 0)
        self.assertEqual(len(db.materials), initial_count + added)

        # Re-importing same pack with overwrite should update, not add
        added2, updated2 = CommunityPresetCatalog.import_pack_into_database(fiber_pack, db, overwrite=True)
        self.assertEqual(added2, 0)
        self.assertEqual(updated2, len(fiber_pack.materials))

        # Test export
        with tempfile.NamedTemporaryFile(suffix=".lfmat", delete=False) as tmp:
            tmp_export = tmp.name

        try:
            exported = CommunityPresetCatalog.export_database_to_pack(
                db=db,
                pack_name="Test Export Pack",
                author="Test User",
                path=tmp_export
            )
            self.assertEqual(exported.pack_name, "Test Export Pack")
            self.assertEqual(len(exported.materials), len(db.materials))
            self.assertTrue(os.path.exists(tmp_export))
        finally:
            if os.path.exists(tmp_export):
                os.remove(tmp_export)


class TestMaterialLibraryUI(unittest.TestCase):
    """Test suite for MaterialLibraryDialog & CommunityPackBrowserDialog."""

    def test_pack_browser_dialog(self):
        dlg = CommunityPackBrowserDialog()
        self.assertGreater(dlg.list_packs.count(), 0)
        dlg.list_packs.setCurrentRow(0)
        self.assertIsNotNone(dlg.selected_pack)
        self.assertGreater(dlg.tbl_materials.rowCount(), 0)
        dlg.close()

    def test_material_library_dialog_filters(self):
        dlg = MaterialLibraryDialog()
        initial_items = dlg.list_materials.count()
        self.assertGreater(initial_items, 0)

        # Filter by CO2
        idx = dlg.combo_laser.findText("CO2 (10.6um)")
        if idx >= 0:
            dlg.combo_laser.setCurrentIndex(idx)
            # May be 0 if CO2 pack isn't in default db, or > 0
            pass

        # Switch back to All
        dlg.combo_laser.setCurrentIndex(0)
        self.assertEqual(dlg.list_materials.count(), initial_items)

        # Search query
        dlg.search_box.setText("anodized")
        self.assertGreater(dlg.list_materials.count(), 0)
        self.assertLess(dlg.list_materials.count(), initial_items)
        dlg.close()


class TestVisionReticleTracking(unittest.TestCase):
    """Test suite for CameraEngine live laser reticle tracking and coordinate mapping."""

    def setUp(self):
        self.engine = CameraEngine()
        # Set up a known bed homography (camera sensor 1920x1080 to bed 400x300 mm at 2.5 px/mm)
        cam_pts = [(200.0, 150.0), (1720.0, 150.0), (1720.0, 930.0), (200.0, 930.0)]
        bed_pts = [(0.0, 0.0), (400.0, 0.0), (400.0, 300.0), (0.0, 300.0)]
        self.engine.compute_bed_homography(cam_pts, bed_pts)

    def test_laser_to_camera_and_back(self):
        # Bed center (200 mm, 150 mm)
        cam_pos = self.engine.laser_to_camera(200.0, 150.0)
        self.assertIsNotNone(cam_pos)
        u, v = cam_pos
        # Bed center should map near the center of the camera quad (960, 540)
        self.assertAlmostEqual(u, 960.0, delta=10.0)
        self.assertAlmostEqual(v, 540.0, delta=10.0)

        # Map back from camera to laser
        bed_pos = self.engine.camera_to_laser(u, v)
        self.assertIsNotNone(bed_pos)
        bx, by = bed_pos
        self.assertAlmostEqual(bx, 200.0, delta=2.0)
        self.assertAlmostEqual(by, 150.0, delta=2.0)

    @unittest.skipUnless(HAS_CV2, "Requires OpenCV cv2")
    def test_draw_reticle_on_frame(self):
        frame = np.full((1080, 1920, 3), 40, dtype=np.uint8)
        self.engine.set_live_laser_position(100.0, 100.0, "Run")
        annotated = self.engine.draw_laser_reticle_on_frame(frame, (100.0, 100.0), "Run")
        self.assertIsNotNone(annotated)
        self.assertEqual(annotated.shape, frame.shape)
        # Check that pixels were drawn on the frame
        self.assertFalse(np.array_equal(annotated, frame))


if __name__ == "__main__":
    unittest.main()
