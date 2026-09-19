import unittest
import os
import xml.etree.ElementTree as ET
from laserforge.core.models import RectEntity
from laserforge.core.layer_manager import LayerManager
from laserforge.config import MachineSettings
from laserforge.core.lbrn2_exporter import LBRN2Exporter
from laserforge.core.plugin_api import get_plugin_registry, PluginRegistry

class TestLBRN2Exporter(unittest.TestCase):
    def setUp(self):
        self.layer_manager = LayerManager()
        self.settings = MachineSettings()
        
    def test_export_empty(self):
        xml_str = LBRN2Exporter.export([], self.layer_manager, self.settings)
        self.assertIn("LightBurnProject", xml_str)
        self.assertIn('AppVersion="1.7.00"', xml_str)
        
    def test_export_rect(self):
        rect = RectEntity(layer_id=0, x=10, y=20, width=50, height=30)
        xml_str = LBRN2Exporter.export([rect], self.layer_manager, self.settings)
        self.assertIn('Type="Rect"', xml_str)
        self.assertIn('W="50.000000"', xml_str)
        self.assertIn('H="30.000000"', xml_str)

    def test_export_all_entities(self):
        from laserforge.core.models import CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
        entities = [
            RectEntity(layer_id=0, x=10, y=10, width=40, height=20),
            CircleEntity(layer_id=1, x=60, y=60, radius_x=15, radius_y=15),
            LineEntity(layer_id=0, x=0, y=0, x2=100, y2=100),
            PathEntity(layer_id=2, x=0, y=0, contours=[[(0, 0), (20, 0), (20, 20)]], closed=True),
            TextEntity(layer_id=1, x=30, y=30, text="LightBurn Test", font_family="Ubuntu", font_size=12),
            ImageEntity(layer_id=3, x=5, y=5, width=80, height=50, image_path="/tmp/test.png")
        ]
        xml_str = LBRN2Exporter.export(entities, self.layer_manager, self.settings)
        self.assertIn('Type="Rect"', xml_str)
        self.assertIn('Type="Ellipse"', xml_str)
        self.assertIn('Type="Path"', xml_str)
        self.assertIn('Type="Text"', xml_str)
        self.assertIn('Type="Bitmap"', xml_str)
        self.assertIn('LightBurn Test', xml_str)
        self.assertIn('/tmp/test.png', xml_str)

    def test_export_and_save_to_file(self):
        import tempfile
        rect = RectEntity(layer_id=0, x=5, y=5, width=30, height=30)
        with tempfile.NamedTemporaryFile(suffix=".lbrn2", delete=False) as tf:
            path = tf.name
        try:
            LBRN2Exporter.save([rect], self.layer_manager, path, self.settings)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("LightBurnProject", content)
            self.assertIn('Type="Rect"', content)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_main_window_export_lbrn_wiring(self):
        import tempfile
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        from laserforge.ui.main_window import MainWindow

        os.environ["LASERFORGE_HEADLESS"] = "1"
        app = QApplication.instance() or QApplication(["test", "-platform", "offscreen"])

        mw = MainWindow()
        self.assertTrue(hasattr(mw.actions, "export_lbrn"))
        self.assertEqual(mw.actions.export_lbrn.text(), "Export LightBurn Project (.lbrn2)...")

        # Add a shape to canvas
        rect = RectEntity(layer_id=0, x=10, y=10, width=50, height=50)
        mw.scene.add_entity(rect)

        with tempfile.NamedTemporaryFile(suffix=".lbrn2", delete=False) as tf:
            path = tf.name

        try:
            with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName", return_value=(path, "LightBurn Projects (*.lbrn2)")):
                with patch("PyQt6.QtWidgets.QMessageBox.information"):
                    mw.export_lbrn()

            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("LightBurnProject", content)
            self.assertIn('Type="Rect"', content)
        finally:
            if os.path.exists(path):
                os.unlink(path)
            mw.close()

class TestPluginRegistry(unittest.TestCase):
    def test_get_registry_singleton(self):
        reg1 = get_plugin_registry()
        reg2 = get_plugin_registry()
        self.assertIs(reg1, reg2)
        self.assertIsInstance(reg1, PluginRegistry)

    def test_plugin_discovery_empty(self):
        reg = PluginRegistry()
        reg.PLUGIN_DIR = "/tmp/non_existent_plugin_dir_laserforge"
        loaded = reg.discover_and_load({})
        self.assertEqual(loaded, [])

if __name__ == "__main__":
    unittest.main()
