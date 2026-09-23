"""
Unit and Integration Tests for LaserForge Loading Splash Screen
and Workbed Area Setup & Calibration Studio.
"""

import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Ensure a single QApplication instance exists for tests
app = QApplication.instance()
if not app:
    app = QApplication([])

from laserforge.config import MachineSettings
from laserforge.core.serial_controller import SerialController, VirtualGrblSerial
from laserforge.core.layer_manager import LayerManager
from laserforge.ui.canvas_scene import LaserCanvasScene
from laserforge.ui.splash_screen import LaserForgeSplashScreen
from laserforge.ui.workbed_setup_dialog import (
    WorkbedSetupDialog, WorkbedPreviewWidget, MACHINE_PRESETS
)


class TestSplashScreen(unittest.TestCase):
    """Tests for LaserForgeSplashScreen."""

    def setUp(self):
        self.splash = LaserForgeSplashScreen()

    def tearDown(self):
        self.splash.close()

    def test_splash_initial_state(self):
        self.assertEqual(self.splash.progress_bar.value(), 0)
        self.assertEqual(self.splash.lbl_percent.text(), "0%")
        self.assertIn("v1.4.0", self.splash.lbl_version.text())
        self.assertEqual(self.splash.lbl_title.text(), "LASERFORGE")

    def test_splash_set_progress(self):
        self.splash.set_progress(45, "Loading 2D CAD canvas...")
        self.assertEqual(self.splash.progress_bar.value(), 45)
        self.assertEqual(self.splash.lbl_percent.text(), "45%")
        self.assertEqual(self.splash.lbl_status.text(), "Loading 2D CAD canvas...")

    def test_splash_clamping(self):
        self.splash.set_progress(-10, "Negative clamped")
        self.assertEqual(self.splash.progress_bar.value(), 0)
        self.splash.set_progress(150, "Exceeded clamped")
        self.assertEqual(self.splash.progress_bar.value(), 100)

    def test_splash_finish(self):
        mock_win = MagicMock()
        self.splash.finish_splash(mock_win)
        self.assertEqual(self.splash.progress_bar.value(), 100)
        mock_win.show.assert_called_once()
        mock_win.showMaximized.assert_called_once()


class TestWorkbedSetupDialog(unittest.TestCase):
    """Tests for WorkbedSetupDialog and WorkbedPreviewWidget."""

    def setUp(self):
        self.settings = MachineSettings(bed_width=400.0, bed_height=400.0, origin_corner="Bottom-Left", rapid_speed=3000.0)
        self.layer_manager = LayerManager()
        self.scene = LaserCanvasScene(self.layer_manager)
        self.virtual_grbl = VirtualGrblSerial()
        self.serial_ctrl = SerialController()
        self.serial_ctrl.connect("VIRTUAL_GRBL")

        self.dialog = WorkbedSetupDialog(
            settings=self.settings,
            serial_ctrl=self.serial_ctrl,
            scene=self.scene
        )

    def tearDown(self):
        self.dialog.close()
        self.serial_ctrl.disconnect()
        self.virtual_grbl.close()

    def test_dialog_loads_settings(self):
        self.assertEqual(self.dialog.spin_width.value(), 400.0)
        self.assertEqual(self.dialog.spin_height.value(), 400.0)
        self.assertEqual(self.dialog.combo_origin.currentText(), "Bottom-Left")
        self.assertEqual(self.dialog.preview_widget.bed_width, 400.0)
        self.assertEqual(self.dialog.preview_widget.bed_height, 400.0)

    def test_preset_selection(self):
        # Select xTool D1 Pro (430 x 400 mm, Top-Left)
        xtool_idx = -1
        for i in range(self.dialog.combo_presets.count()):
            if "xTool D1 / D1 Pro" in self.dialog.combo_presets.itemText(i):
                xtool_idx = i
                break
        self.assertGreater(xtool_idx, 0)
        self.dialog.combo_presets.setCurrentIndex(xtool_idx)

        self.assertEqual(self.dialog.spin_width.value(), 430.0)
        self.assertEqual(self.dialog.spin_height.value(), 400.0)
        self.assertEqual(self.dialog.combo_origin.currentText(), "Top-Left")
        self.assertEqual(self.dialog.preview_widget.bed_width, 430.0)

    def test_artilume_t1_preset_selection(self):
        # Select Artilume T1 / T1-P (150 x 200 mm, Bottom-Left)
        artilume_idx = -1
        for i in range(self.dialog.combo_presets.count()):
            if "Artilume T1" in self.dialog.combo_presets.itemText(i):
                artilume_idx = i
                break
        self.assertGreater(artilume_idx, 0)
        self.dialog.combo_presets.setCurrentIndex(artilume_idx)

        self.assertEqual(self.dialog.spin_width.value(), 150.0)
        self.assertEqual(self.dialog.spin_height.value(), 200.0)
        self.assertEqual(self.dialog.combo_origin.currentText(), "Bottom-Left")
        self.assertEqual(self.dialog.preview_widget.bed_width, 150.0)
        self.assertEqual(self.dialog.preview_widget.bed_height, 200.0)

        # Test MachineSettingsDialog also loads Artilume T1 preset
        from laserforge.ui.machine_settings_dialog import MachineSettingsDialog
        m_dlg = MachineSettingsDialog(self.settings, serial_ctrl=self.serial_ctrl)
        try:
            m_artilume_idx = -1
            for i in range(m_dlg.combo_presets.count()):
                if "Artilume T1" in m_dlg.combo_presets.itemText(i):
                    m_artilume_idx = i
                    break
            self.assertGreater(m_artilume_idx, 0)
            m_dlg.combo_presets.setCurrentIndex(m_artilume_idx)
            self.assertEqual(m_dlg.width_spin.value(), 150.0)
            self.assertEqual(m_dlg.height_spin.value(), 200.0)
            self.assertEqual(m_dlg.origin_combo.currentText(), "Bottom-Left")
        finally:
            m_dlg.close()

    def test_grbl_eeprom_detection(self):
        # Simulate GRBL $$ response with $130=450.0 and $131=410.0 and $20=1
        test_settings = {
            "$130": "450.000",
            "$131": "410.000",
            "$20": "1"
        }
        self.dialog._on_grbl_settings_updated(test_settings)
        self.assertEqual(self.dialog.spin_width.value(), 450.0)
        self.assertEqual(self.dialog.spin_height.value(), 410.0)
        self.assertIn("Enabled ($20=1)", self.dialog.lbl_grbl_detected.text())

    def test_2corner_jog_measurement(self):
        # Set Pt 1 = (10.0, 10.0) and Pt 2 = (460.0, 420.0)
        self.dialog.calib_pt1 = (10.0, 10.0)
        self.dialog.calib_pt2 = (460.0, 420.0)
        self.dialog._check_calibration_ready()

        self.assertTrue(self.dialog.btn_calc_measured.isEnabled())
        self.assertIn("450.0 × 410.0 mm", self.dialog.btn_calc_measured.text())

        # Apply measured bed
        with patch("PyQt6.QtWidgets.QMessageBox.information") as mock_info:
            self.dialog._on_apply_measured_bed()
            mock_info.assert_called_once()

        self.assertEqual(self.dialog.spin_width.value(), 450.0)
        self.assertEqual(self.dialog.spin_height.value(), 410.0)

    def test_corner_jumps_dispatch(self):
        with patch.object(self.serial_ctrl, "send_command") as mock_send:
            self.dialog.spin_width.setValue(500.0)
            self.dialog.spin_height.setValue(300.0)

            self.dialog._jump_to_corner("TR")
            mock_send.assert_called_with("G90 G0 X500.000 Y300.000 F3000")

            self.dialog._jump_to_corner("Center")
            mock_send.assert_called_with("G90 G0 X250.000 Y150.000 F3000")

    def test_perimeter_framing_dispatch(self):
        with patch.object(self.serial_ctrl, "send_command") as mock_send:
            self.dialog.spin_width.setValue(400.0)
            self.dialog.spin_height.setValue(400.0)
            self.dialog._trace_bed_perimeter()

            # Verify that motion bounding commands were sent
            sent_cmds = [c[0][0] for c in mock_send.call_args_list]
            self.assertIn("G90 G21", sent_cmds)
            self.assertTrue(any("X400.000" in cmd for cmd in sent_cmds))
            self.assertIn("M5", sent_cmds)

    def test_wasteboard_grid_generator(self):
        from laserforge.ui.canvas_scene import LaserItemWrapper
        initial_entity_count = len([i for i in self.scene.items() if isinstance(i, LaserItemWrapper)])
        self.dialog.spin_width.setValue(200.0)
        self.dialog.spin_height.setValue(200.0)
        self.dialog.combo_grid_step.setCurrentIndex(2)  # 50 mm spacing

        with patch("PyQt6.QtWidgets.QMessageBox.information") as mock_info:
            self.dialog._generate_wasteboard_grid()
            mock_info.assert_called_once()

        current_count = len([i for i in self.scene.items() if isinstance(i, LaserItemWrapper)])
        self.assertGreater(current_count, initial_entity_count)

    def test_apply_and_save(self):
        self.dialog.spin_width.setValue(480.0)
        self.dialog.spin_height.setValue(420.0)
        self.dialog.combo_origin.setCurrentText("Top-Left")
        self.dialog.spin_margin.setValue(8.0)
        self.dialog.chk_sync_grbl.setChecked(True)

        with patch.object(self.serial_ctrl, "send_command") as mock_send:
            self.dialog._on_apply_and_save()
            # Verify settings updated
            self.assertEqual(self.settings.bed_width, 480.0)
            self.assertEqual(self.settings.bed_height, 420.0)
            self.assertEqual(self.settings.origin_corner, "Top-Left")
            self.assertEqual(getattr(self.settings, "safety_margin_mm"), 8.0)

            # Verify GRBL EEPROM sync commands
            sent_cmds = [c[0][0] for c in mock_send.call_args_list]
            self.assertIn("$130=480.0", sent_cmds)
            self.assertIn("$131=420.0", sent_cmds)
            self.assertIn("$20=1", sent_cmds)

    def test_alarm_banner_and_recovery(self):
        # Initial: hidden
        self.assertTrue(self.dialog.alarm_banner.isHidden())

        # Alarm status received
        self.dialog._on_serial_status_updated({"state": "Alarm:1", "wpos": [0, 0, 0]})
        self.assertFalse(self.dialog.alarm_banner.isHidden())
        self.assertIn("ALARM", self.dialog.lbl_alarm_msg.text())

        # Unlock clicked
        with patch.object(self.serial_ctrl, "unlock") as mock_unlock:
            self.dialog._on_unlock_alarm()
            mock_unlock.assert_called_once()
            self.assertTrue(self.dialog.alarm_banner.isHidden())

        # Home clicked
        with patch.object(self.serial_ctrl, "home") as mock_home:
            self.dialog._on_home_machine()
            mock_home.assert_called_once()

    def test_main_window_workbed_action_exists(self):
        from laserforge.ui.main_window import MainWindow
        win = MainWindow(start_tutorial=False)
        try:
            self.assertTrue(hasattr(win.actions, "workbed_setup"))
            self.assertEqual(win.actions.workbed_setup.text(), "Workbed Setup & Calibration Wizard...")
            self.assertEqual(win.actions.workbed_setup.shortcut().toString(), "F4")
        finally:
            try:
                win.serial_ctrl.disconnect()
            except Exception:
                pass
            win.close()

    def test_laser_reticle_origin_mapping(self):
        """Verify machine coordinates (0, 0) and jogging map to correct scene coordinates based on origin."""
        self.scene.set_bed_size(400.0, 300.0, "Bottom-Left")
        self.scene.update_laser_position(0.0, 0.0, state="Idle", connected=True)
        reticle = self.scene.laser_reticle
        # Bottom-Left: (0, 0) machine -> (0, 300) scene
        self.assertAlmostEqual(reticle.pos().x(), 0.0)
        self.assertAlmostEqual(reticle.pos().y(), 300.0)
        self.assertAlmostEqual(reticle.laser_x, 0.0)
        self.assertAlmostEqual(reticle.laser_y, 0.0)

        # Jogging +Y moves up in scene (decreasing scene y)
        self.scene.update_laser_position(0.0, 50.0, state="Jog", connected=True)
        self.assertAlmostEqual(reticle.pos().x(), 0.0)
        self.assertAlmostEqual(reticle.pos().y(), 250.0)
        self.assertAlmostEqual(reticle.laser_x, 0.0)
        self.assertAlmostEqual(reticle.laser_y, 50.0)

        # Top-Left: (0, 0) machine -> (0, 0) scene
        self.scene.set_bed_size(400.0, 300.0, "Top-Left")
        self.scene.update_laser_position(0.0, 0.0, state="Idle", connected=True)
        self.assertAlmostEqual(reticle.pos().x(), 0.0)
        self.assertAlmostEqual(reticle.pos().y(), 0.0)

        # Top-Left: +Y moves down in scene (increasing scene y)
        self.scene.update_laser_position(0.0, 50.0, state="Jog", connected=True)
        self.assertAlmostEqual(reticle.pos().x(), 0.0)
        self.assertAlmostEqual(reticle.pos().y(), 50.0)

        # Bottom-Right: (0, 0) machine -> (400, 300) scene
        self.scene.set_bed_size(400.0, 300.0, "Bottom-Right")
        self.scene.update_laser_position(0.0, 0.0, state="Idle", connected=True)
        self.assertAlmostEqual(reticle.pos().x(), 400.0)
        self.assertAlmostEqual(reticle.pos().y(), 300.0)

        # Top-Right: (0, 0) machine -> (400, 0) scene
        self.scene.set_bed_size(400.0, 300.0, "Top-Right")
        self.scene.update_laser_position(0.0, 0.0, state="Idle", connected=True)
        self.assertAlmostEqual(reticle.pos().x(), 400.0)
        self.assertAlmostEqual(reticle.pos().y(), 0.0)

    def test_workbed_preview_coordinate_mapping(self):
        """Verify WorkbedPreviewWidget._map_coords places (0, 0) at origin beacon across all corners."""
        pw = self.dialog.preview_widget
        ox, oy = 20.0, 30.0
        rw, rh = 200.0, 150.0
        scale = 0.5

        # Bottom-Left
        pw.origin_corner = "Bottom-Left"
        px, py = pw._map_coords(0.0, 0.0, ox, oy, rw, rh, scale)
        self.assertAlmostEqual(px, ox)
        self.assertAlmostEqual(py, oy + rh)

        # Top-Left
        pw.origin_corner = "Top-Left"
        px, py = pw._map_coords(0.0, 0.0, ox, oy, rw, rh, scale)
        self.assertAlmostEqual(px, ox)
        self.assertAlmostEqual(py, oy)

        # Bottom-Right
        pw.origin_corner = "Bottom-Right"
        px, py = pw._map_coords(0.0, 0.0, ox, oy, rw, rh, scale)
        self.assertAlmostEqual(px, ox + rw)
        self.assertAlmostEqual(py, oy + rh)

        # Top-Right
        pw.origin_corner = "Top-Right"
        px, py = pw._map_coords(0.0, 0.0, ox, oy, rw, rh, scale)
        self.assertAlmostEqual(px, ox + rw)
        self.assertAlmostEqual(py, oy)

    def test_top_left_corner_jumps(self):
        """Verify _jump_to_corner on a Top-Left machine targets correct machine coordinates."""
        with patch.object(self.serial_ctrl, "send_command") as mock_send:
            self.dialog.spin_width.setValue(400.0)
            self.dialog.spin_height.setValue(300.0)
            self.dialog.combo_origin.setCurrentText("Top-Left")

            # On Top-Left machine, TL is machine (0, 0)
            self.dialog._jump_to_corner("TL")
            mock_send.assert_called_with("G90 G0 X0.000 Y0.000 F3000")

            # BL is machine (0, 300)
            self.dialog._jump_to_corner("BL")
            mock_send.assert_called_with("G90 G0 X0.000 Y300.000 F3000")

            # TR is machine (400, 0)
            self.dialog._jump_to_corner("TR")
            mock_send.assert_called_with("G90 G0 X400.000 Y0.000 F3000")

            # BR is machine (400, 300)
            self.dialog._jump_to_corner("BR")
            mock_send.assert_called_with("G90 G0 X400.000 Y300.000 F3000")

    def test_shape_properties_origin_inversion(self):
        """Verify ShapePropertiesPanel reflects and edits coordinates relative to workbed origin."""
        from laserforge.ui.shape_properties import ShapePropertiesPanel
        from laserforge.core.models import RectEntity

        self.scene.set_bed_size(400.0, 400.0, "Bottom-Left")
        props = ShapePropertiesPanel(self.scene)

        # Place rectangle at scene x=50, y=380 (which is 20mm from bottom origin)
        rect = RectEntity(layer_id=0, x=50.0, y=380.0, width=40.0, height=20.0)
        wrapper = self.scene.add_entity(rect)
        wrapper.setSelected(True)

        props.update_from_selection()
        self.assertAlmostEqual(props.x_spin.value(), 50.0)
        self.assertAlmostEqual(props.y_spin.value(), 20.0)

        # Move Y to 30.0 in properties panel -> should move shape UP to scene y=370
        props.y_spin.setValue(30.0)
        self.assertAlmostEqual(rect.y, 370.0)


if __name__ == "__main__":
    unittest.main()
