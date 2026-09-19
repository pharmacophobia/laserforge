"""
Unit tests for LaserForge Telemetry, System Diagnostics, and Feedback Engine.
"""

import os
import tempfile
import json
import zipfile
import unittest
from laserforge.config import MachineSettings
from laserforge.core.telemetry import (
    sanitize_text, collect_system_diagnostics, FeedbackReport, CrashManager, get_last_crash_report
)


class TestTelemetryEngine(unittest.TestCase):

    def test_path_sanitization(self):
        home = os.path.expanduser("~")
        sample_text = f"Error in file {home}/LaserForge/test.py"
        sanitized = sanitize_text(sample_text)
        self.assertNotIn(home, sanitized)
        self.assertIn("~/LaserForge/test.py", sanitized)

    def test_collect_system_diagnostics(self):
        settings = MachineSettings()
        diag = collect_system_diagnostics(settings=settings)

        self.assertIn("platform", diag)
        self.assertIn("python", diag)
        self.assertIn("hardware", diag)
        self.assertIn("machine_settings", diag)
        self.assertEqual(diag["machine_settings"]["bed_width"], 400.0)
        self.assertEqual(diag["machine_settings"]["bed_height"], 400.0)

    def test_feedback_report_markdown_generation(self):
        diag = collect_system_diagnostics()
        report = FeedbackReport(
            category="Bug Report",
            subject="Test Bed Error",
            message="Machine jogged beyond travel limit switch.",
            contact_info="tester@laserforge.org",
            diagnostics=diag,
            recent_logs=["G0 X0 Y0", "G0 X500 Y500", "ALARM: Hard limit"]
        )

        md = report.to_markdown()
        self.assertIn("# LaserForge Feedback: [Bug Report] Test Bed Error", md)
        self.assertIn("Machine jogged beyond travel limit switch.", md)
        self.assertIn("tester@laserforge.org", md)
        self.assertIn("ALARM: Hard limit", md)
        self.assertIn("System Diagnostics", md)

    def test_export_diagnostic_bundle_zip(self):
        report = FeedbackReport(
            category="Feature Request",
            subject="Add Rotary Chuck Preset",
            message="Please add preset for 80mm 3-jaw chuck.",
            contact_info="maker@workshop.net",
            recent_logs=["$101=80", "ok"]
        )

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            zip_path = tf.name

        try:
            fake_screenshot = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR..."
            res_path = report.export_bundle(zip_path, screenshot_bytes=fake_screenshot)
            self.assertTrue(os.path.exists(res_path))

            with zipfile.ZipFile(res_path, "r") as zf:
                names = zf.namelist()
                self.assertIn("issue_report.md", names)
                self.assertIn("diagnostics.json", names)
                self.assertIn("serial_console.log", names)
                self.assertIn("canvas_screenshot.png", names)
        finally:
            if os.path.exists(zip_path):
                os.unlink(zip_path)

    def test_crash_manager_dump(self):
        # Trigger an exception handler test directly
        try:
            raise ValueError("Simulated beta test crash for testing telemetry")
        except ValueError as e:
            exc_type, exc_val, exc_tb = type(e), e, e.__traceback__

        # Mock out excepthook run without popping a GUI dialog
        os.environ["LASERFORGE_HEADLESS"] = "1"
        try:
            CrashManager._on_unhandled_exception(exc_type, exc_val, exc_tb)
            last_report = get_last_crash_report()
            self.assertIsNotNone(last_report)
            self.assertEqual(last_report["exception_type"], "ValueError")
            self.assertIn("Simulated beta test crash", last_report["exception_message"])
        finally:
            os.environ.pop("LASERFORGE_HEADLESS", None)


if __name__ == "__main__":
    unittest.main()
