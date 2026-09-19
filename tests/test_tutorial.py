"""
Unit and integration tests for LaserForge Interactive Tutorial & Onboarding Studio.
"""

import os
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.serial_controller import SerialController
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.ui.canvas_scene import LaserCanvasScene
from laserforge.ui.tutorial_dialog import WelcomeOnboardingDialog, InteractiveTutorialDialog
from laserforge.ui.main_window import MainWindow


class TestTutorialDialogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["LASERFORGE_HEADLESS"] = "1"
        cls.app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

    def setUp(self):
        # Reset tutorial preferences for clean testing
        self.settings = QSettings("LaserForge", "LaserForge")
        self.settings.remove("tutorial_prompt_dismissed")

    def tearDown(self):
        self.settings.remove("tutorial_prompt_dismissed")

    def test_welcome_dialog_initialization_and_start(self):
        dlg = WelcomeOnboardingDialog()
        self.assertFalse(dlg.start_tutorial_selected)
        self.assertTrue(dlg.chk_dont_show.isChecked())

        # Simulate clicking Start Tutorial
        dlg._on_start()
        self.assertTrue(dlg.start_tutorial_selected)
        self.assertTrue(self.settings.value("tutorial_prompt_dismissed", False, type=bool))

    def test_welcome_dialog_skip(self):
        dlg = WelcomeOnboardingDialog()
        dlg._on_skip()
        self.assertFalse(dlg.start_tutorial_selected)
        self.assertTrue(self.settings.value("tutorial_prompt_dismissed", False, type=bool))

    def test_interactive_tutorial_steps_count_and_data(self):
        dlg = InteractiveTutorialDialog()
        self.assertEqual(len(dlg.steps_data), 6)
        expected_ids = [
            "welcome_workspace",
            "drawing_vectors",
            "cuts_layers",
            "simulation_preview",
            "virtual_grbl",
            "framing_burning"
        ]
        actual_ids = [s["id"] for s in dlg.steps_data]
        self.assertEqual(actual_ids, expected_ids)
        self.assertEqual(dlg.current_step, 0)
        self.assertIn("Workspace Tour", dlg.lbl_title.text())
        dlg.close()

    def test_interactive_tutorial_navigation(self):
        dlg = InteractiveTutorialDialog()
        self.assertEqual(dlg.current_step, 0)

        # Forward navigation
        dlg._on_next()
        self.assertEqual(dlg.current_step, 1)
        self.assertIn("Drawing", dlg.lbl_title.text())

        dlg._on_next()
        self.assertEqual(dlg.current_step, 2)
        self.assertIn("Layer Modes", dlg.lbl_title.text())

        # Backward navigation
        dlg._on_prev()
        self.assertEqual(dlg.current_step, 1)

        # Jump to last step
        dlg.show()
        dlg.show_step(5)
        self.assertEqual(dlg.current_step, 5)
        self.assertFalse(dlg.btn_finish.isHidden())
        self.assertTrue(dlg.btn_next.isHidden())
        dlg.close()

    def test_startup_checkbox_persistence(self):
        dlg = InteractiveTutorialDialog()
        dlg._on_startup_toggled(False)
        self.assertTrue(self.settings.value("tutorial_prompt_dismissed", False, type=bool))

        dlg._on_startup_toggled(True)
        self.assertFalse(self.settings.value("tutorial_prompt_dismissed", False, type=bool))
        dlg.close()

    def test_interactive_actions_with_main_window(self):
        mw = MainWindow()
        dlg = InteractiveTutorialDialog(main_window=mw)
        dlg.show()

        # Step 1 Action: Highlight workspace
        dlg.show_step(0)
        dlg._action_highlight_workspace()
        self.assertFalse(dlg.lbl_action_status.isHidden())
        self.assertIn("Workspace active", dlg.lbl_action_status.text())

        # Step 2 Action: Place sample shapes
        dlg.show_step(1)
        dlg._action_place_sample_shapes()
        entities = mw.scene.get_all_entities()
        self.assertEqual(len(entities), 3)
        names = [e.name for e in entities]
        self.assertIn("Keychain Outer", names)
        self.assertIn("Lanyard Hole", names)
        self.assertIn("Logo Text", names)

        # Step 3 Action: Configure layer settings
        dlg.show_step(2)
        dlg._action_configure_layers()
        c00 = mw.layer_manager.get_layer(0)
        c01 = mw.layer_manager.get_layer(1)
        self.assertEqual(c00.mode, "Line")
        self.assertEqual(c00.speed, 400.0)
        self.assertEqual(c00.power_max, 90.0)
        self.assertEqual(c01.mode, "Fill")
        self.assertEqual(c01.speed, 3000.0)
        self.assertEqual(c01.power_max, 35.0)

        # Step 5 Action: Connect Virtual Simulator
        dlg.show_step(4)
        dlg._action_connect_virtual_simulator()
        self.assertTrue(mw.serial_ctrl.is_connected)
        self.assertIn("VIRTUAL", mw.serial_ctrl.port_name.upper())

        # Step 6 Action: Load welcome project
        dlg.show_step(5)
        dlg._action_load_welcome_project()
        entities_after = mw.scene.get_all_entities()
        self.assertGreater(len(entities_after), 0)

        mw.serial_ctrl.disconnect()
        dlg.close()
        mw.close()

    def test_help_menu_action_opens_tutorial(self):
        mw = MainWindow()
        self.assertTrue(hasattr(mw.actions, "interactive_tutorial"))
        self.assertEqual(mw.actions.interactive_tutorial.shortcut().toString(), "F2")

        # Trigger tutorial action
        mw.actions.interactive_tutorial.trigger()
        self.assertIsNotNone(mw._tutorial_dialog)
        self.assertTrue(mw._tutorial_dialog.isVisible())

        # Triggering again should reuse existing dialog
        first_dlg = mw._tutorial_dialog
        mw.actions.interactive_tutorial.trigger()
        self.assertIs(mw._tutorial_dialog, first_dlg)

        mw._tutorial_dialog.close()
        mw.close()

    def test_export_lbrn_action_exists(self):
        mw = MainWindow()
        self.assertTrue(hasattr(mw.actions, "export_lbrn"))
        self.assertIn("LightBurn", mw.actions.export_lbrn.text())
        mw.close()


if __name__ == "__main__":
    unittest.main()
