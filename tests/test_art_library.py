"""
Unit and Integration Tests for LaserForge Art & Component Library Studio.
Verifies ArtItem serialization, ArtLibrary saving/loading, filtering,
thumbnail generation, and canvas drag-and-drop placement.
"""

import os
import shutil
import tempfile
import unittest
import base64

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)
from laserforge.core.art_library import (
    ArtItem, ArtLibrary, ArtLibraryManager, render_entities_thumbnail, create_default_standard_library
)
from laserforge.ui.main_window import MainWindow
from laserforge.ui.canvas_scene import LaserItemWrapper

# Ensure QApplication exists for GUI/QImage tests
app = QApplication.instance() or QApplication([])


class TestArtLibrary(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="laserforge_art_test_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_art_item_serialization_and_instantiation(self):
        """Tests ArtItem serialization, deserialization, and dynamic entity instantiation."""
        entities = [
            RectEntity(name="Base", layer_id=0, x=10.0, y=20.0, width=50.0, height=30.0, corner_radius=2.0),
            CircleEntity(name="Mounting Hole", layer_id=0, x=35.0, y=35.0, radius_x=4.0, radius_y=4.0)
        ]

        lib = ArtLibrary(name="TestLib", filepath=os.path.join(self.temp_dir, "test.lflib"))
        item = lib.add_item_from_entities(
            name="Bracket Mount",
            entities=entities,
            category="Hardware",
            tags=["bracket", "mount", "m4"],
            description="50x30mm mounting bracket with 8mm center hole."
        )

        self.assertIsNotNone(item)
        self.assertEqual(item.name, "Bracket Mount")
        self.assertEqual(item.category, "Hardware")
        self.assertIn("bracket", item.tags)
        self.assertGreater(len(item.thumbnail_b64), 100)

        # Test bounds
        self.assertAlmostEqual(item.width_mm, 50.0, places=1)
        self.assertAlmostEqual(item.height_mm, 30.0, places=1)

        # Test to_dict / from_dict
        d = item.to_dict()
        restored = ArtItem.from_dict(d)
        self.assertEqual(restored.id, item.id)
        self.assertEqual(restored.name, item.name)
        self.assertEqual(restored.category, item.category)
        self.assertEqual(len(restored.entities_data), 2)

        # Test instantiate_entities at center (200, 200)
        new_ents = item.instantiate_entities(target_x=200.0, target_y=200.0, center=True)
        self.assertEqual(len(new_ents), 2)

        # Bounding box of instantiated entities should center on (200, 200)
        b_x1 = min(e.get_bounds()[0] for e in new_ents)
        b_y1 = min(e.get_bounds()[1] for e in new_ents)
        b_x2 = max(e.get_bounds()[2] for e in new_ents)
        b_y2 = max(e.get_bounds()[3] for e in new_ents)
        cx = (b_x1 + b_x2) / 2.0
        cy = (b_y1 + b_y2) / 2.0
        self.assertAlmostEqual(cx, 200.0, places=1)
        self.assertAlmostEqual(cy, 200.0, places=1)

    def test_art_library_file_persistence_and_filtering(self):
        """Tests saving and reloading a .lflib file, plus multi-factor filtering."""
        lib_path = os.path.join(self.temp_dir, "CustomParts.lflib")
        lib = ArtLibrary(name="Custom Parts", filepath=lib_path)

        # Add item 1: Keyhole
        lib.add_item_from_entities(
            name="Keyhole 15mm",
            entities=[RectEntity(x=0, y=0, width=8, height=15)],
            category="Mounts",
            tags=["wall", "hanger", "keyhole"]
        )

        # Add item 2: M3 Hole
        lib.add_item_from_entities(
            name="M3 Hole",
            entities=[CircleEntity(x=3, y=3, radius_x=1.6, radius_y=1.6)],
            category="Fasteners",
            tags=["screw", "m3", "hole"]
        )

        # Add item 3: M4 Hole
        lib.add_item_from_entities(
            name="M4 Hole",
            entities=[CircleEntity(x=4, y=4, radius_x=2.15, radius_y=2.15)],
            category="Fasteners",
            tags=["screw", "m4", "hole"]
        )

        # Save to disk
        lib.save()
        self.assertTrue(os.path.exists(lib_path))

        # Reload from disk
        loaded_lib = ArtLibrary.load(lib_path)
        self.assertEqual(loaded_lib.name, "Custom Parts")
        self.assertEqual(len(loaded_lib.items), 3)

        # Test filtering by query
        m_items = loaded_lib.filter_items(query="m3")
        self.assertEqual(len(m_items), 1)
        self.assertEqual(m_items[0].name, "M3 Hole")

        # Test filtering by category
        fasteners = loaded_lib.filter_items(category="Fasteners")
        self.assertEqual(len(fasteners), 2)

        # Test filtering by tag
        hangers = loaded_lib.filter_items(tag="hanger")
        self.assertEqual(len(hangers), 1)
        self.assertEqual(hangers[0].name, "Keyhole 15mm")

    def test_default_standard_hardware_library(self):
        """Tests the pre-configured Standard Hardware & Fasteners library."""
        std_path = os.path.join(self.temp_dir, "Standard_Hardware.lflib")
        lib = create_default_standard_library(std_path)
        self.assertEqual(len(lib.items), 10)

        item_names = [it.name for it in lib.items.values()]
        self.assertIn("M3 Screw Clearance Hole", item_names)
        self.assertIn("M4 Screw Clearance Hole", item_names)
        self.assertIn("M5 Screw Clearance Hole", item_names)
        self.assertIn("Keyhole Wall Mount Slot", item_names)
        self.assertIn("Cable Tie Pass-Through Slot", item_names)
        self.assertIn("Keychain / Earring Loop Tab", item_names)
        self.assertIn("Sliding Box Lid Finger Pull", item_names)
        self.assertIn("90° Corner Alignment Fiducial", item_names)

        # Test thumbnail base64 validity for each item
        for it in lib.items.values():
            self.assertTrue(len(it.thumbnail_b64) > 50)
            raw = base64.b64decode(it.thumbnail_b64)
            self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_art_library_manager(self):
        """Tests multi-library discovery and active library management."""
        mgr = ArtLibraryManager(self.temp_dir)
        # Should have automatically created Standard_Hardware.lflib
        self.assertIn("Standard Hardware & Laser Components", mgr.loaded_libraries)
        self.assertEqual(mgr.active_library_name, "Standard Hardware & Laser Components")

        # Create a new library
        new_lib = mgr.create_new_library("User Templates")
        self.assertEqual(mgr.active_library_name, "User Templates")
        self.assertIn("User Templates", mgr.loaded_libraries)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "User_Templates.lflib")))

        # Switch active library
        mgr.set_active_library("Standard Hardware & Laser Components")
        self.assertEqual(mgr.active_library_name, "Standard Hardware & Laser Components")

        # Unload user library
        mgr.unload_library("User Templates")
        self.assertNotIn("User Templates", mgr.loaded_libraries)

    def test_main_window_art_library_integration(self):
        """Tests that MainWindow integrates Art Library, inserts items, and creates selections."""
        win = MainWindow()
        win.scene.clear()

        # Check that Art Library dock exists and is tabified
        self.assertTrue(hasattr(win, "art_dock"))
        self.assertTrue(hasattr(win, "art_library_panel"))
        self.assertIsNotNone(win.art_library_panel)

        # Get an item from the standard library
        active_lib = win.art_library_manager.get_active_library()
        self.assertIsNotNone(active_lib)
        items = list(active_lib.items.values())
        self.assertGreater(len(items), 0)

        target_item = items[0]

        # Insert on canvas at (150, 150)
        win.insert_art_item_on_canvas(target_item, target_x=150.0, target_y=150.0)

        # Verify entities added to scene
        entities = win.scene.get_all_entities()
        self.assertGreater(len(entities), 0)

        # Test simulating drop event
        win.scene.clear()
        win._on_art_item_dropped(target_item.id, 120.0, 180.0)
        entities_after_drop = win.scene.get_all_entities()
        self.assertGreater(len(entities_after_drop), 0)

        # Verify items are selected upon insertion
        selected = win.scene.selectedItems()
        self.assertEqual(len(selected), len(entities_after_drop))


if __name__ == "__main__":
    unittest.main()
