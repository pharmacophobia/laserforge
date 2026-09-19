"""
Unit and integration tests for LaserForge User Guide & FAQ Reference Studio.
"""

import os
import unittest
from PyQt6.QtWidgets import QApplication

from laserforge.ui.guide_dialog import UserGuideDialog, GUIDE_SECTIONS
from laserforge.ui.main_window import MainWindow


class TestUserGuide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["LASERFORGE_HEADLESS"] = "1"
        cls.app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

    def test_guide_sections_data(self):
        self.assertGreaterEqual(len(GUIDE_SECTIONS), 8)
        expected_ids = [
            "getting_started",
            "cuts_layers",
            "photo_raster",
            "hardware_grbl",
            "design_studios",
            "safety_framing",
            "faq_troubleshooting",
            "keyboard_shortcuts"
        ]
        actual_ids = [s["id"] for s in GUIDE_SECTIONS]
        for eid in expected_ids:
            self.assertIn(eid, actual_ids)

    def test_guide_dialog_initialization_and_selection(self):
        dlg = UserGuideDialog()
        dlg.show()
        self.assertEqual(dlg.list_sections.count(), len(GUIDE_SECTIONS))
        self.assertEqual(dlg.list_sections.currentRow(), 0)
        self.assertIn("Getting Started", dlg.browser.toPlainText())

        # Select FAQ section
        faq_row = -1
        for i, s in enumerate(GUIDE_SECTIONS):
            if s["id"] == "faq_troubleshooting":
                faq_row = i
                break
        self.assertNotEqual(faq_row, -1)
        dlg.list_sections.setCurrentRow(faq_row)
        self.assertIn("Frequently Asked Questions", dlg.browser.toPlainText())
        self.assertIn("laser beam is not firing", dlg.browser.toPlainText())
        dlg.close()

    def test_guide_search_filtering(self):
        dlg = UserGuideDialog()
        dlg.show()

        # Search for 'kerf'
        dlg.search_edit.setText("kerf")
        visible_count = sum(1 for i in range(dlg.list_sections.count()) if not dlg.list_sections.item(i).isHidden())
        self.assertGreater(visible_count, 0)
        self.assertIn("kerf", dlg.browser.toPlainText().lower())

        # Search for non-matching nonsense
        dlg.search_edit.setText("xyzzy_nonexistent_token_12345")
        visible_none = sum(1 for i in range(dlg.list_sections.count()) if not dlg.list_sections.item(i).isHidden())
        self.assertEqual(visible_none, 0)
        self.assertIn("No matching topics found", dlg.browser.toPlainText())

        # Clear search
        dlg.search_edit.clear()
        visible_all = sum(1 for i in range(dlg.list_sections.count()) if not dlg.list_sections.item(i).isHidden())
        self.assertEqual(visible_all, len(GUIDE_SECTIONS))
        dlg.close()

    def test_guide_quick_action_delegation(self):
        mw = MainWindow()
        dlg = UserGuideDialog(main_window=mw)
        dlg.show()

        # Test launching interactive tutorial from guide
        dlg._launch_tutorial()
        self.assertIsNotNone(mw._tutorial_dialog)
        self.assertFalse(mw._tutorial_dialog.isHidden())
        mw._tutorial_dialog.close()

        dlg.close()
        mw.close()

    def test_help_menu_user_guide_action_wiring(self):
        mw = MainWindow()
        self.assertTrue(hasattr(mw.actions, "user_guide"))
        self.assertEqual(mw.actions.user_guide.shortcut().toString(), "F1")
        self.assertIn("User Guide", mw.actions.user_guide.text())

        # Trigger action
        mw.actions.user_guide.trigger()
        self.assertIsNotNone(mw._guide_dialog)
        self.assertFalse(mw._guide_dialog.isHidden())

        # Trigger again should reuse existing dialog
        first_dlg = mw._guide_dialog
        mw.actions.user_guide.trigger()
        self.assertIs(mw._guide_dialog, first_dlg)

        mw._guide_dialog.close()
        mw.close()


if __name__ == "__main__":
    unittest.main()
