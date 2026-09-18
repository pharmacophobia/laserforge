"""
Unit and Integration Tests for LaserForge Vector Node Editing & Trim Scissor Tool.
Verifies conversion of basic geometric shapes into editable vector paths,
vertex manipulation (move, insert, delete, smooth, split/break),
Shapely-based segment trimming at intersections, and interactive canvas scene integration.
"""

import math
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF

from laserforge.core.models import RectEntity, CircleEntity, LineEntity, PathEntity
from laserforge.core.node_editor import (
    NodeEditorEngine, point_dist, dist_to_segment
)
from laserforge.core.layer_manager import LayerManager
from laserforge.ui.canvas_scene import (
    LaserCanvasScene, LaserItemWrapper, TOOL_SELECT, TOOL_NODE_EDIT, TOOL_TRIM
)

app = QApplication.instance() or QApplication([])


class TestNodeEditorEngine(unittest.TestCase):

    def test_entity_to_path_entity_conversion(self):
        """Tests converting Rect, Circle, and Line entities into editable PathEntities."""
        # Rectangle conversion
        rect = RectEntity(x=10.0, y=20.0, width=40.0, height=30.0)
        p_rect = NodeEditorEngine.entity_to_path_entity(rect)
        self.assertIsInstance(p_rect, PathEntity)
        self.assertEqual(len(p_rect.contours), 1)
        self.assertEqual(len(p_rect.contours[0]), 4)
        self.assertTrue(p_rect.closed)

        # Circle conversion (polygonized circular path)
        circ = CircleEntity(x=50.0, y=50.0, radius_x=15.0, radius_y=15.0)
        p_circ = NodeEditorEngine.entity_to_path_entity(circ)
        self.assertIsInstance(p_circ, PathEntity)
        self.assertTrue(len(p_circ.contours[0]) >= 36)
        self.assertTrue(p_circ.closed)

        # Line conversion
        line = LineEntity(x=5.0, y=10.0, x2=25.0, y2=30.0)
        p_line = NodeEditorEngine.entity_to_path_entity(line)
        self.assertIsInstance(p_line, PathEntity)
        self.assertEqual(len(p_line.contours[0]), 2)
        self.assertFalse(p_line.closed)

    def test_world_nodes_and_hit_testing(self):
        """Tests calculating absolute world coordinates of vertices and hit testing."""
        path = PathEntity(x=100.0, y=200.0, contours=[[(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]])
        nodes = NodeEditorEngine.get_world_nodes(path)
        self.assertEqual(len(nodes), 4)

        # First node is at (100, 200)
        self.assertEqual(nodes[0], (0, 0, 100.0, 200.0))
        # Second node is at (150, 200)
        self.assertEqual(nodes[1], (0, 1, 150.0, 200.0))

        # Hit test near (151, 199) within 3mm
        hit = NodeEditorEngine.find_node_near(path, 151.0, 199.0, hit_radius=3.0)
        self.assertEqual(hit, (0, 1))

        # Hit test far away -> None
        miss = NodeEditorEngine.find_node_near(path, 0.0, 0.0, hit_radius=3.0)
        self.assertIsNone(miss)

    def test_node_manipulations(self):
        """Tests moving, inserting, deleting, smoothing, and breaking paths."""
        path = PathEntity(
            x=0.0, y=0.0,
            contours=[[(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]],
            closed=True
        )

        # 1. Move vertex 1 from (40, 0) to (45, 5)
        NodeEditorEngine.move_node(path, 0, 1, 45.0, 5.0)
        self.assertEqual(path.contours[0][1], (45.0, 5.0))

        # 2. Insert vertex near midpoint of bottom edge (20, 40)
        ins = NodeEditorEngine.insert_node_near(path, 20.0, 40.0, max_dist=4.0)
        self.assertIsNotNone(ins)
        c_idx, n_idx = ins
        self.assertEqual(c_idx, 0)
        self.assertEqual(len(path.contours[0]), 5)

        # 3. Smooth a node
        NodeEditorEngine.smooth_node(path, 0, 1)

        # 4. Delete vertex
        deleted = NodeEditorEngine.delete_node(path, 0, 2)
        self.assertTrue(deleted)
        self.assertEqual(len(path.contours[0]), 4)

        # 5. Break closed path at node 0
        NodeEditorEngine.break_path_at_node(path, 0, 0)
        self.assertFalse(path.closed)

    def test_trim_scissor_tool(self):
        """Tests trimming an intersecting cross segment using Trim Scissor logic."""
        # Horizontal line from (0, 20) to (100, 20)
        h_line = PathEntity(
            x=0.0, y=0.0,
            contours=[[(0.0, 20.0), (100.0, 20.0)]],
            closed=False
        )

        # Vertical cutter line at x=50 from y=0 to 100
        v_line = LineEntity(x=50.0, y=0.0, x2=50.0, y2=100.0)

        # User clicks on the left side of the intersection at (25, 20) with Trim Scissor
        trimmed = NodeEditorEngine.trim_segment_at_point(
            target_entity=h_line,
            cutter_entities=[v_line],
            click_world_x=25.0,
            click_world_y=20.0,
            max_click_dist=6.0
        )

        self.assertIsNotNone(trimmed)
        # Left segment (0..50) was trimmed out, remaining segment should be (50..100)
        self.assertEqual(len(trimmed.contours), 1)
        remaining = trimmed.contours[0]
        self.assertAlmostEqual(remaining[0][0], 50.0, places=1)
        self.assertAlmostEqual(remaining[1][0], 100.0, places=1)

    def test_canvas_scene_node_edit_and_trim_integration(self):
        """Tests canvas scene tool switching, vertex selection, and vertex deletion."""
        lm = LayerManager()
        scene = LaserCanvasScene(lm)

        # Add a rectangle
        rect = RectEntity(x=10.0, y=10.0, width=50.0, height=50.0)
        wrapper = scene.add_entity(rect)
        wrapper.setSelected(True)

        # Switch to Node Edit tool: should convert primitive rect to PathEntity
        scene.set_active_tool(TOOL_NODE_EDIT)
        self.assertEqual(scene.active_tool, TOOL_NODE_EDIT)

        # Verify selected item is now a PathEntity
        sel_items = [it for it in scene.selectedItems() if isinstance(it, LaserItemWrapper)]
        self.assertEqual(len(sel_items), 1)
        path_wrapper = sel_items[0]
        self.assertIsInstance(path_wrapper.entity, PathEntity)

        # Simulate selecting vertex (0, 1) and deleting it
        path_wrapper._selected_node = (0, 1)
        init_vertex_count = len(path_wrapper.entity.contours[0])
        scene.delete_selected()
        self.assertEqual(len(path_wrapper.entity.contours[0]), init_vertex_count - 1)

        # Switch to Trim Tool
        scene.set_active_tool(TOOL_TRIM)
        self.assertEqual(scene.active_tool, TOOL_TRIM)


if __name__ == "__main__":
    unittest.main()
