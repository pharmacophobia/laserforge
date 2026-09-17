"""
Unit tests for LaserForge Parametric Box & Finger-Joint Enclosure Engine.
"""

import unittest
from laserforge.core.box_engine import BoxEngine, BoxPanel
from laserforge.core.models import PathEntity


class TestBoxEngine(unittest.TestCase):

    def test_generate_6_sided_box(self):
        panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, finger_width=10.0, kerf=0.15, style="6-sided"
        )
        self.assertEqual(len(panels), 6)
        names = [p.name for p in panels]
        self.assertIn("Bottom", names)
        self.assertIn("Top", names)
        self.assertIn("Front", names)
        self.assertIn("Back", names)
        self.assertIn("Left", names)
        self.assertIn("Right", names)

        # Check that all panels have closed outlines with vertices
        for p in panels:
            self.assertGreaterEqual(len(p.outline), 12)
            self.assertEqual(p.outline[0], p.outline[-1])

    def test_generate_open_top_box(self):
        panels = BoxEngine.generate_box(
            width=120.0, depth=90.0, height=50.0, thickness=4.0, style="open-top"
        )
        self.assertEqual(len(panels), 5)
        names = [p.name for p in panels]
        self.assertNotIn("Top", names)
        self.assertIn("Bottom", names)

    def test_generate_sliding_lid_box(self):
        panels = BoxEngine.generate_box(
            width=100.0, depth=80.0, height=60.0, thickness=3.0, style="sliding-lid"
        )
        self.assertEqual(len(panels), 6)
        names = [p.name for p in panels]
        self.assertIn("Sliding_Lid", names)

        # Left and Right sides should have internal slot cutouts for the lid
        left_panel = next(p for p in panels if p.name == "Left")
        self.assertEqual(len(left_panel.internal_cutouts), 1)

    def test_layout_to_entities(self):
        panels = BoxEngine.generate_box(width=80.0, depth=60.0, height=40.0, thickness=3.0)
        entities = BoxEngine.layout_to_entities(panels, start_x=10.0, start_y=10.0, spacing=5.0)

        # Should produce PathEntity objects and label TextEntities
        path_ents = [e for e in entities if isinstance(e, PathEntity)]
        self.assertEqual(len(path_ents), 6)

        # Verify none of the entities have overlapping start positions
        positions = set((e.x, e.y) for e in path_ents)
        self.assertEqual(len(positions), 6)


if __name__ == "__main__":
    unittest.main()
