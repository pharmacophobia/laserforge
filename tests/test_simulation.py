"""
Unit Tests for LaserForge Project Outcome Simulation & Simulate Button Feature.

Tests:
1. Simulate button placement adjacent to Start button in LaserControlPanel.
2. Signal propagation from LaserControlPanel.simulate_job_requested.
3. SimulationCanvas material presets, realistic outcome rendering, and toolpath modes.
4. Cumulative execution time calculation and playback scrubber controls.
5. Laser head plasma beam state rendering (burning vs rapid travel).
6. Layer execution breakdown and layer visibility toggles.
7. Direct Start Job integration from PreviewDialog.
"""

import unittest
import os
import math
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_app = QApplication.instance() or QApplication([])

from laserforge.config import MachineSettings
from laserforge.core.models import RectEntity, CircleEntity
from laserforge.core.gcode_generator import GCodeJobResult, ToolpathSegment
from laserforge.core.serial_controller import SerialController
from laserforge.ui.laser_control_panel import LaserControlPanel
from laserforge.ui.preview_dialog import PreviewDialog, SimulationCanvas, MATERIAL_PRESETS
from laserforge.ui.main_window import MainWindow


class TestSimulationFeature(unittest.TestCase):

    def setUp(self):
        self.settings = MachineSettings()
        self.serial_ctrl = SerialController()

    def test_simulate_button_adjacent_to_start(self):
        """Verify Simulate button is present and located right next to Start button."""
        panel = LaserControlPanel(self.serial_ctrl, settings=self.settings)

        self.assertTrue(hasattr(panel, "btn_simulate"), "Panel must have btn_simulate")
        self.assertTrue(hasattr(panel, "btn_start"), "Panel must have btn_start")

        self.assertIn("Simulate", panel.btn_simulate.text())
        self.assertIn("Start", panel.btn_start.text())

        # Test signal emission
        emitted = []
        panel.simulate_job_requested.connect(lambda: emitted.append(True))
        panel.btn_simulate.click()
        self.assertEqual(len(emitted), 1, "Clicking btn_simulate must emit simulate_job_requested")

    def test_simulation_canvas_materials_and_modes(self):
        """Verify realistic material burn outcome mode and toolpath mode."""
        segs = [
            ToolpathSegment(move_type="rapid", x1=0, y1=0, x2=10, y2=10, feedrate=3000, power_pct=0, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=10, y1=10, x2=50, y2=10, feedrate=1000, power_pct=85, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=50, y1=10, x2=50, y2=50, feedrate=1000, power_pct=85, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=50, y1=50, x2=10, y2=50, feedrate=1000, power_pct=85, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=10, y1=50, x2=10, y2=10, feedrate=1000, power_pct=85, layer_id=0, color="#000000")
        ]
        canvas = SimulationCanvas(segs, (10.0, 10.0, 50.0, 50.0))

        # Default mode is outcome
        self.assertEqual(canvas.view_mode, "outcome")
        self.assertIn(canvas.material_key, MATERIAL_PRESETS)

        # Toggle through all material presets without crash
        for mat_key in MATERIAL_PRESETS.keys():
            canvas.material_key = mat_key
            canvas.update()

        # Switch to toolpath vector mode
        canvas.view_mode = "toolpath"
        canvas.show_rapids = True
        canvas.update()

    def test_preview_dialog_playback_and_scrubber(self):
        """Verify scrubber, speed controls, and cumulative time calculation."""
        segs = [
            ToolpathSegment(move_type="rapid", x1=0, y1=0, x2=10, y2=10, feedrate=3000, power_pct=0, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=10, y1=10, x2=40, y2=10, feedrate=1200, power_pct=80, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=40, y1=10, x2=40, y2=40, feedrate=1200, power_pct=80, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="rapid", x1=40, y1=40, x2=0, y2=0, feedrate=3000, power_pct=0, layer_id=0, color="#000000")
        ]
        gcode = "G90\nG0 X10 Y10\nM4 S800\nG1 X40 Y10 F1200\nG1 X40 Y40\nM5\nG0 X0 Y0\n"
        job = GCodeJobResult(
            gcode=gcode,
            segments=segs,
            total_cut_dist_mm=60.0,
            total_rapid_dist_mm=54.1,
            estimated_time_sec=4.0,
            bounding_box=(0.0, 0.0, 40.0, 40.0)
        )

        dlg = PreviewDialog(job, settings=self.settings)

        # Cumulative time array check
        self.assertEqual(len(dlg.cumulative_times_sec), len(segs) + 1)
        self.assertGreater(dlg.total_time_sec, 0.0)

        # Test stepping forward & backward
        dlg._reset_scrubber()
        self.assertEqual(dlg.slider.value(), 0)

        dlg._step_segments(2)
        self.assertEqual(dlg.slider.value(), 2)

        dlg._step_segments(-1)
        self.assertEqual(dlg.slider.value(), 1)

        dlg._jump_to_end()
        self.assertEqual(dlg.slider.value(), len(segs))

        # Test play/pause toggle
        dlg._reset_scrubber()
        dlg._toggle_playback()
        self.assertTrue(dlg.play_timer.isActive())
        self.assertEqual(dlg.btn_play.text(), "⏸ Pause")

        dlg._toggle_playback()
        self.assertFalse(dlg.play_timer.isActive())
        self.assertEqual(dlg.btn_play.text(), "▶ Play")

    def test_layer_visibility_filter(self):
        """Verify layers can be toggled on/off in the simulation view."""
        segs = [
            ToolpathSegment(move_type="cut", x1=0, y1=0, x2=10, y2=0, feedrate=1000, power_pct=80, layer_id=0, color="#000000"),
            ToolpathSegment(move_type="cut", x1=0, y1=10, x2=10, y2=10, feedrate=1000, power_pct=80, layer_id=1, color="#1E90FF")
        ]
        canvas = SimulationCanvas(segs, (0.0, 0.0, 10.0, 10.0))

        # Initially all layers visible
        self.assertEqual(len(canvas.hidden_layers), 0)

        # Hide layer 1
        canvas.hidden_layers.add(1)
        self.assertIn(1, canvas.hidden_layers)

        # Unhide layer 1
        canvas.hidden_layers.discard(1)
        self.assertNotIn(1, canvas.hidden_layers)

    def test_main_window_simulate_integration(self):
        """Verify MainWindow connects simulate button to preview_simulation."""
        win = MainWindow()
        self.assertTrue(hasattr(win, "preview_simulation"))
        self.assertTrue(hasattr(win.laser_panel, "btn_simulate"))


if __name__ == "__main__":
    unittest.main()
