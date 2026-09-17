"""
Unit tests for LaserForge 2D Vector Boolean Operations Engine.
"""

import unittest
from laserforge.core.models import RectEntity, CircleEntity, PathEntity
from laserforge.core.boolean_engine import BooleanEngine


class TestBooleanEngine(unittest.TestCase):

    def setUp(self):
        # Overlapping squares:
        # A: [0, 0] to [20, 20]
        # B: [10, 0] to [30, 20]
        self.rect_a = RectEntity(layer_id=0, name="A", x=0.0, y=0.0, width=20.0, height=20.0)
        self.rect_b = RectEntity(layer_id=0, name="B", x=10.0, y=0.0, width=20.0, height=20.0)

    def test_union_overlapping_rectangles(self):
        res = BooleanEngine.union([self.rect_a, self.rect_b])
        self.assertEqual(len(res), 1)
        poly = BooleanEngine.entity_to_shapely(res[0])
        self.assertIsNotNone(poly)
        # Bounding box of united rectangle: [0, 0] to [30, 20]
        minx, miny, maxx, maxy = poly.bounds
        self.assertAlmostEqual(minx, 0.0, places=3)
        self.assertAlmostEqual(miny, 0.0, places=3)
        self.assertAlmostEqual(maxx, 30.0, places=3)
        self.assertAlmostEqual(maxy, 20.0, places=3)
        # Total area: (20*20) + (20*20) - (10*20) = 400 + 400 - 200 = 600
        self.assertAlmostEqual(poly.area, 600.0, places=2)

    def test_difference_subtract_notch(self):
        res = BooleanEngine.difference(self.rect_a, [self.rect_b])
        self.assertEqual(len(res), 1)
        poly = BooleanEngine.entity_to_shapely(res[0])
        self.assertIsNotNone(poly)
        # Remaining should be [0, 0] to [10, 20], area = 200
        self.assertAlmostEqual(poly.area, 200.0, places=2)
        minx, miny, maxx, maxy = poly.bounds
        self.assertAlmostEqual(minx, 0.0, places=3)
        self.assertAlmostEqual(maxx, 10.0, places=3)

    def test_intersection_overlap(self):
        res = BooleanEngine.intersection([self.rect_a, self.rect_b])
        self.assertEqual(len(res), 1)
        poly = BooleanEngine.entity_to_shapely(res[0])
        self.assertIsNotNone(poly)
        # Intersecting region: [10, 0] to [20, 20], area = 200
        self.assertAlmostEqual(poly.area, 200.0, places=2)
        minx, miny, maxx, maxy = poly.bounds
        self.assertAlmostEqual(minx, 10.0, places=3)
        self.assertAlmostEqual(maxx, 20.0, places=3)

    def test_xor_symmetric_difference(self):
        res = BooleanEngine.xor([self.rect_a, self.rect_b])
        poly = BooleanEngine.entity_to_shapely(res[0])
        self.assertIsNotNone(poly)
        # Area = 600 - 200 = 400 (the two non-overlapping 10x20 wings)
        total_area = sum(BooleanEngine.entity_to_shapely(r).area for r in res)
        self.assertAlmostEqual(total_area, 400.0, places=2)

    def test_circle_rect_union(self):
        circle = CircleEntity(layer_id=0, name="C", x=20.0, y=10.0, radius_x=5.0, radius_y=5.0)
        res = BooleanEngine.union([self.rect_a, circle])
        self.assertEqual(len(res), 1)
        poly = BooleanEngine.entity_to_shapely(res[0])
        self.assertIsNotNone(poly)
        minx, miny, maxx, maxy = poly.bounds
        self.assertAlmostEqual(maxx, 25.0, places=1)


if __name__ == "__main__":
    unittest.main()
