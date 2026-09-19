"""
Unit tests for LaserForge Plugin Architecture & License Security Enhancements.
"""

import os
import tempfile
import unittest
from laserforge.core.plugin_api import (
    LaserForgePlugin, PluginMetadata, PluginRegistry, get_plugin_registry
)
from laserforge.core.license_engine import LicenseEngine, LicenseStatus, log_license_event


class MockHeaderPlugin(LaserForgePlugin):
    metadata = PluginMetadata(name="MockHeader", version="1.0.0")

    def __init__(self):
        super().__init__()
        self.started = False
        self.completed = False
        self.progress_pct = 0.0

    def register_gcode_postprocessor(self):
        return lambda gcode: "; MOCK_HEADER\n" + gcode

    def register_canvas_tool(self):
        return {
            "tool_id": "test_tool",
            "label": "Test Tool",
            "cursor": "crosshair"
        }

    def register_layer_panel_widget(self):
        return "DummyWidget"

    def on_job_start(self, gcode: str, estimated_time_sec: float) -> None:
        self.started = True

    def on_job_progress(self, lines_sent: int, lines_total: int, pct: float) -> None:
        self.progress_pct = pct

    def on_job_complete(self, duration_sec: float, was_aborted: bool) -> None:
        self.completed = True


class TestPluginSystem(unittest.TestCase):
    def setUp(self):
        self.registry = PluginRegistry()

    def test_postprocessor_pipeline(self):
        plugin = MockHeaderPlugin()
        self.registry._plugins[plugin.metadata.name] = plugin
        pp = plugin.register_gcode_postprocessor()
        self.registry._gcode_postprocessors.append(pp)

        raw_gcode = "G0 X10 Y10\nM3 S1000\nG1 X20 Y20\nM5"
        processed = self.registry.apply_gcode_postprocessors(raw_gcode)
        self.assertTrue(processed.startswith("; MOCK_HEADER\n"))
        self.assertIn("G1 X20 Y20", processed)

    def test_tool_and_widget_registration(self):
        plugin = MockHeaderPlugin()
        self.registry._plugins[plugin.metadata.name] = plugin
        self.registry._canvas_tools.append(plugin.register_canvas_tool())
        self.registry._layer_widgets.append((plugin.metadata.name, plugin.register_layer_panel_widget()))

        tools = self.registry.get_canvas_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["tool_id"], "test_tool")

        widgets = self.registry.get_layer_widgets()
        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0][0], "MockHeader")

    def test_job_lifecycle_dispatch(self):
        plugin = MockHeaderPlugin()
        self.registry._plugins[plugin.metadata.name] = plugin

        self.registry.dispatch_job_start("G0 X0", 12.5)
        self.assertTrue(plugin.started)

        self.registry.dispatch_job_progress(50, 100, 50.0)
        self.assertEqual(plugin.progress_pct, 50.0)

        self.registry.dispatch_job_complete(12.0, False)
        self.assertTrue(plugin.completed)


class TestLicenseSecurity(unittest.TestCase):
    def test_license_integrity_verification(self):
        status = LicenseStatus()
        valid, msg = status.verify_integrity()
        self.assertTrue(valid)

    def test_audit_logging_does_not_crash(self):
        # Should execute cleanly without exceptions
        log_license_event("TEST_EVENT", "UnitTest verification event")


if __name__ == "__main__":
    unittest.main()
