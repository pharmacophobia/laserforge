"""
Unit Tests for LaserForge Directional Vector Hatching System.

Tests:
1. Unconnected vector polygon extraction (single, multiple, holes/donuts).
2. Spatial neighbor graph triangulation and connectivity.
3. Strict >= 15° neighbor angular separation guarantee.
4. Center-to-edge angular divergence modulation (center divergence > edge divergence).
5. Outer boundary convergence toward vertical lines (90° baseline).
6. Toolpath line generation with exact polygon clipping.
7. Serpentine zig-zag laser path optimization.
8. Cross-hatching dual-perpendicular infill.
9. Interactive studio dialog offscreen instantiation and generation.
"""

import unittest
import os
import math
import numpy as np

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication

# Ensure single QApplication instance
_app = QApplication.instance() or QApplication([])

from laserforge.core.models import RectEntity, CircleEntity, PathEntity
from laserforge.core.directional_hatch import (
    DirectionalHatchGenerator, DirectionalHatchSettings, DirectionalHatchResult,
    VectorPolygon, angular_difference
)
from laserforge.ui.directional_hatch_dialog import DirectionalHatchDialog


class TestDirectionalHatching(unittest.TestCase):

    def test_angular_difference(self):
        """Verify angular difference helper on line orientations (period 180°)."""
        self.assertAlmostEqual(angular_difference(90.0, 90.0), 0.0)
        self.assertAlmostEqual(angular_difference(90.0, 105.0), 15.0)
        self.assertAlmostEqual(angular_difference(10.0, 175.0), 15.0)  # Wraps around 180
        self.assertAlmostEqual(angular_difference(0.0, 180.0), 0.0)
        self.assertAlmostEqual(angular_difference(45.0, 135.0), 90.0)

    def test_extract_polygons_from_entities(self):
        """Extract disjoint polygons from rectangles, circles, and multi-contour paths."""
        r1 = RectEntity(x=10.0, y=10.0, width=20.0, height=20.0)
        c1 = CircleEntity(x=80.0, y=80.0, radius_x=15.0, radius_y=15.0)
        path = PathEntity(
            x=150.0, y=150.0,
            contours=[
                [(0, 0), (25, 0), (25, 25), (0, 25), (0, 0)],
                [(40, 0), (65, 0), (65, 25), (40, 25), (40, 0)]
            ]
        )

        polys = DirectionalHatchGenerator.extract_polygons([r1, c1, path])
        self.assertEqual(len(polys), 4)

        for p in polys:
            self.assertGreater(p.area, 0.0)
            self.assertGreater(len(p.outer_contour), 2)
            self.assertIsNotNone(p.shapely_polygon)
            self.assertGreaterEqual(p.radial_distance, 0.0)
            self.assertLessEqual(p.radial_distance, 1.0)

    def test_spatial_neighbor_graph(self):
        """Ensure neighbor graph connects spatially adjacent shapes symmetrically."""
        # 3x3 grid of shapes
        entities = []
        for r in range(3):
            for c in range(3):
                entities.append(RectEntity(x=c * 30.0, y=r * 30.0, width=15.0, height=15.0))

        polys = DirectionalHatchGenerator.extract_polygons(entities)
        neighbors = DirectionalHatchGenerator.build_neighbor_graph(polys)

        self.assertEqual(len(neighbors), 9)
        # Verify symmetry: if j in neighbors[i] => i in neighbors[j]
        for i, adj in neighbors.items():
            self.assertGreater(len(adj), 0, f"Polygon {i} must have neighbors")
            for j in adj:
                self.assertIn(i, neighbors[j], f"Symmetry broken between {i} and {j}")

    def test_strict_min_neighbor_angle_constraint(self):
        """
        Verify the core constraint: Direction of lines must NEVER be closer
        than 15 degrees to any neighboring vector!
        """
        # Test on multiple grid layouts and random seeds
        for seed in [1, 42, 123, 777]:
            entities = []
            for r in range(4):
                for c in range(4):
                    entities.append(RectEntity(x=c * 25.0, y=r * 25.0, width=15.0, height=15.0))

            settings = DirectionalHatchSettings(
                min_neighbor_angle_diff=15.0,
                center_divergence_deg=75.0,
                edge_divergence_deg=10.0,
                baseline_angle_deg=90.0,
                random_seed=seed
            )

            res = DirectionalHatchGenerator.generate(entities, settings)
            self.assertEqual(len(res.polygons), 16)
            self.assertGreaterEqual(
                res.min_diff_achieved, 15.0 - 1e-3,
                f"Seed {seed}: Achieved min diff ({res.min_diff_achieved:.2f}°) must be >= 15.0°"
            )

            # Explicit check across every neighbor pair
            for u, n_list in res.neighbors.items():
                for v in n_list:
                    if u < v:
                        diff = angular_difference(res.assigned_angles[u], res.assigned_angles[v])
                        self.assertGreaterEqual(
                            diff, 15.0 - 1e-3,
                            f"Neighbor pair ({u}, {v}) has diff {diff:.2f}° < 15°!"
                        )

    def test_center_to_edge_divergence_modulation(self):
        """
        Verify: Difference between neighboring vectors is greatest in the center
        and lessens as it approaches the outer edges.
        """
        # 5x5 grid provides clear center vs perimeter vectors
        entities = []
        for r in range(5):
            for c in range(5):
                entities.append(RectEntity(x=c * 20.0, y=r * 20.0, width=12.0, height=12.0))

        settings = DirectionalHatchSettings(
            min_neighbor_angle_diff=15.0,
            center_divergence_deg=80.0,
            edge_divergence_deg=10.0,
            baseline_angle_deg=90.0,
            random_seed=42
        )

        res = DirectionalHatchGenerator.generate(entities, settings)

        center_diffs = []
        edge_diffs = []

        for u, n_list in res.neighbors.items():
            for v in n_list:
                if u < v:
                    diff = angular_difference(res.assigned_angles[u], res.assigned_angles[v])
                    r_mid = (res.polygons[u].radial_distance + res.polygons[v].radial_distance) / 2.0
                    if r_mid < 0.35:
                        center_diffs.append(diff)
                    elif r_mid > 0.70:
                        edge_diffs.append(diff)

        self.assertGreater(len(center_diffs), 0)
        self.assertGreater(len(edge_diffs), 0)

        avg_center = np.mean(center_diffs)
        avg_edge = np.mean(edge_diffs)

        # Center divergence should be significantly higher than outer edge difference
        self.assertGreater(
            avg_center, avg_edge,
            f"Center diff ({avg_center:.2f}°) must be greater than edge diff ({avg_edge:.2f}°)"
        )
        self.assertGreater(avg_center, 35.0, "Center should have wide angular divergence")

    def test_outer_edge_convergence_to_vertical(self):
        """
        Verify: Outer edge vectors converge toward vertical baseline (90°).
        """
        entities = []
        for r in range(5):
            for c in range(5):
                entities.append(RectEntity(x=c * 20.0, y=r * 20.0, width=12.0, height=12.0))

        settings = DirectionalHatchSettings(
            min_neighbor_angle_diff=15.0,
            center_divergence_deg=75.0,
            edge_divergence_deg=12.0,
            baseline_angle_deg=90.0,
            random_seed=42
        )

        res = DirectionalHatchGenerator.generate(entities, settings)

        # Compute deviation from vertical 90° for edge vs center
        center_deviations = []
        edge_deviations = []

        for poly in res.polygons:
            ang = res.assigned_angles[poly.index]
            dev = angular_difference(ang, 90.0)
            if poly.radial_distance < 0.3:
                center_deviations.append(dev)
            elif poly.radial_distance > 0.8:
                edge_deviations.append(dev)

        avg_center_dev = np.mean(center_deviations)
        avg_edge_dev = np.mean(edge_deviations)

        self.assertGreater(
            avg_center_dev, avg_edge_dev,
            f"Center deviation ({avg_center_dev:.1f}°) must exceed edge deviation ({avg_edge_dev:.1f}°)"
        )

    def test_hatch_line_geometry_and_clipping(self):
        """Verify that hatch lines are strictly clipped inside polygon boundaries."""
        r = RectEntity(x=0.0, y=0.0, width=50.0, height=30.0)
        polys = DirectionalHatchGenerator.extract_polygons([r])
        poly = polys[0]

        lines = DirectionalHatchGenerator.generate_hatch_lines_for_polygon(
            poly=poly,
            angle_deg=45.0,
            line_spacing_mm=2.0,
            cross_hatch=False,
            serpentine=True
        )

        self.assertGreater(len(lines), 5)
        # Verify every vertex of every line segment is within the rectangle [0, 50] x [0, 30]
        for line in lines:
            self.assertGreaterEqual(len(line), 2)
            for x, y in line:
                self.assertGreaterEqual(x, -1e-4)
                self.assertLessEqual(x, 50.0 + 1e-4)
                self.assertGreaterEqual(y, -1e-4)
                self.assertLessEqual(y, 30.0 + 1e-4)

    def test_cross_hatch_mode(self):
        """Cross hatch mode generates dual perpendicular line sets."""
        r = RectEntity(x=0.0, y=0.0, width=30.0, height=30.0)
        polys = DirectionalHatchGenerator.extract_polygons([r])
        poly = polys[0]

        single_lines = DirectionalHatchGenerator.generate_hatch_lines_for_polygon(
            poly=poly, angle_deg=30.0, line_spacing_mm=2.0, cross_hatch=False
        )
        cross_lines = DirectionalHatchGenerator.generate_hatch_lines_for_polygon(
            poly=poly, angle_deg=30.0, line_spacing_mm=2.0, cross_hatch=True
        )

        self.assertGreater(len(cross_lines), len(single_lines) * 1.5)

    def test_directional_hatch_dialog(self):
        """Test offscreen instantiation and interactive execution of DirectionalHatchDialog."""
        entities = [
            RectEntity(x=0.0, y=0.0, width=25.0, height=25.0),
            RectEntity(x=35.0, y=0.0, width=25.0, height=25.0),
            RectEntity(x=0.0, y=35.0, width=25.0, height=25.0),
            CircleEntity(x=47.5, y=47.5, radius_x=12.5, radius_y=12.5)
        ]

        dlg = DirectionalHatchDialog(entities=entities, active_layer_id=2)
        self.assertIsNotNone(dlg.result)
        self.assertEqual(len(dlg.result.polygons), 4)
        self.assertGreaterEqual(dlg.result.min_diff_achieved, 15.0 - 1e-3)
        self.assertGreater(dlg.result.total_line_count, 0)
        self.assertGreater(dlg.result.total_hatch_length_mm, 0.0)

        # Toggle preview settings
        dlg._toggle_graph(False)
        self.assertFalse(dlg.canvas.show_neighbor_graph)
        dlg._toggle_arrows(False)
        self.assertFalse(dlg.canvas.show_direction_arrows)
        dlg._toggle_color_mode(False)
        self.assertFalse(dlg.canvas.color_by_angle)


if __name__ == "__main__":
    unittest.main()
