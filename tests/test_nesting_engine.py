"""
Unit tests for LaserForge NestingEngine (2D bin packing, rotations, cavity nesting).
"""

import unittest
from laserforge.core.models import RectEntity, CircleEntity, PathEntity
from laserforge.core.nesting_engine import NestingEngine, NestItem


class TestNestingEngine(unittest.TestCase):

    def test_basic_packing_rectangles(self):
        # 4 rectangles 40x30
        rects = [
            RectEntity(layer_id=0, name=f"Rect_{i}", x=i*10.0, y=i*10.0, width=40.0, height=30.0, corner_radius=0.0)
            for i in range(4)
        ]

        result = NestingEngine.nest(
            entities=rects,
            sheet_width=200.0,
            sheet_height=200.0,
            part_spacing=2.0,
            sheet_margin=5.0
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.placed_items), 4)
        self.assertEqual(len(result.unplaced_items), 0)
        self.assertGreater(result.efficiency_pct, 0.0)

        # Verify no bounding box overlaps between placed items
        for i in range(len(result.placed_items)):
            p_i = result.placed_items[i]
            for j in range(i + 1, len(result.placed_items)):
                p_j = result.placed_items[j]
                # Distance between placed centers should exceed part dimensions
                dx = abs(p_i.placed_x - p_j.placed_x)
                dy = abs(p_i.placed_y - p_j.placed_y)
                # At least one axis must have separation >= (dim - 1e-3)
                self.assertTrue(dx >= 39.9 or dy >= 29.9, f"Overlap detected: i={i}, j={j}")

    def test_hole_cavity_nesting(self):
        # A large frame 100x100 with a 50x50 hole in the center
        # Outer: (0,0) to (100,100), Inner hole: (25,25) to (75,75)
        outer_contour = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        hole_contour = [(25, 25), (75, 25), (75, 75), (25, 75), (25, 25)]

        frame = PathEntity(layer_id=0, name="Frame", x=0, y=0, contours=[outer_contour, hole_contour])
        small_box = RectEntity(layer_id=1, name="SmallBox", x=0, y=0, width=30.0, height=30.0, corner_radius=0.0)

        result = NestingEngine.nest(
            entities=[frame, small_box],
            sheet_width=150.0,
            sheet_height=150.0,
            part_spacing=2.0,
            sheet_margin=5.0,
            allow_hole_nesting=True
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.placed_items), 2)
        # Check if small box was nested inside the hole
        small_item = next(it for it in result.placed_items if it.id == small_box.id)
        self.assertTrue(small_item.nested_in_hole)

    def test_oversized_parts_reported_unplaced(self):
        # 1 small rect and 1 giant rect larger than sheet
        small = RectEntity(layer_id=0, name="Small", x=0, y=0, width=20.0, height=20.0, corner_radius=0.0)
        giant = RectEntity(layer_id=0, name="Giant", x=0, y=0, width=500.0, height=500.0, corner_radius=0.0)

        result = NestingEngine.nest(
            entities=[small, giant],
            sheet_width=100.0,
            sheet_height=100.0
        )

        self.assertFalse(result.success)
        self.assertEqual(len(result.placed_items), 1)
        self.assertEqual(len(result.unplaced_items), 1)
        self.assertEqual(result.unplaced_items[0].id, giant.id)

    def test_nesting_dialog_lifecycle(self):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            app = QApplication([])

        from laserforge.config import MachineSettings
        from laserforge.core.layer_manager import LayerManager
        from laserforge.ui.nesting_dialog import NestingDialog

        settings = MachineSettings()
        layer_mgr = LayerManager()
        rect1 = RectEntity(layer_id=0, name="R1", x=10, y=10, width=30, height=20, corner_radius=0)
        rect2 = RectEntity(layer_id=0, name="R2", x=50, y=50, width=40, height=30, corner_radius=0)

        dlg = NestingDialog(
            entities=[rect1, rect2],
            selected_entities=[rect1],
            settings=settings,
            layer_manager=layer_mgr
        )

        dlg._run_nesting()
        self.assertIsNotNone(dlg.latest_result)
        self.assertEqual(len(dlg.latest_result.placed_items), 1)  # Only selected 1 shape
        dlg.close()


if __name__ == "__main__":
    unittest.main()
