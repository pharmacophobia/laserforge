"""
Unit and Integration Tests for LaserForge Phase 3:
1. Commercial Licensing & 30-Day Free Trial Engine (Hardware fingerprinting, HMAC signature, tamper detection)
2. Living Hinges & Curved Box / Lattice Flex Studio (Straight, Wavy, Diamond flex patterns & bend math)
3. UI Integration & Shortcut Non-Collision
"""

import unittest
import os
import json
import time
import math
import tempfile
import shutil

from PyQt6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.core.license_engine import LicenseEngine, LicenseStatus
from laserforge.core.living_hinge_engine import LivingHingeEngine, LivingHingeConfig


class TestLicenseEngine(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for license storage during tests
        self.test_dir = tempfile.mkdtemp()
        self.orig_license_path = LicenseEngine.LICENSE_FILE_PATH
        self.test_license_path = os.path.join(self.test_dir, "license.json")
        LicenseEngine.LICENSE_FILE_PATH = self.test_license_path

    def tearDown(self):
        LicenseEngine.LICENSE_FILE_PATH = self.orig_license_path
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_device_fingerprint(self):
        """Device fingerprint should be a 16-character hexadecimal string."""
        fp = LicenseEngine.get_device_fingerprint()
        self.assertIsInstance(fp, str)
        self.assertEqual(len(fp), 16)
        # Consistent across multiple calls on same machine
        self.assertEqual(fp, LicenseEngine.get_device_fingerprint())

    def test_key_generation_and_validation(self):
        """Signed license keys must validate for the issuing email and machine."""
        email = "maker@laserforge.org"
        device_id = LicenseEngine.get_device_fingerprint()
        key = LicenseEngine.generate_license_key(email, device_id=device_id)

        self.assertTrue(key.startswith("LF-"))
        parts = key.split("-")
        self.assertEqual(len(parts), 5)

        # Valid key verification
        is_valid, msg = LicenseEngine.validate_key(key, email, device_id)
        self.assertTrue(is_valid, msg)

        # Invalid key (different email)
        is_valid_wrong_email, _ = LicenseEngine.validate_key(key, "imposter@bad.com", device_id)
        self.assertFalse(is_valid_wrong_email)

        # Invalid key (different machine ID)
        is_valid_wrong_dev, _ = LicenseEngine.validate_key(key, email, "0000000000000000")
        self.assertFalse(is_valid_wrong_dev)

        # Tampered key string
        tampered_key = key[:-2] + "AA"
        is_valid_tampered, _ = LicenseEngine.validate_key(tampered_key, email, device_id)
        self.assertFalse(is_valid_tampered)

    def test_universal_site_license(self):
        """Universal site keys should validate regardless of machine ID."""
        email = "lab@university.edu"
        key = LicenseEngine.generate_license_key(email, is_site_license=True)
        is_valid, msg = LicenseEngine.validate_key(key, email, "any_device_hash_1234")
        self.assertTrue(is_valid, msg)

    def test_initial_free_trial_state(self):
        """Fresh installation without license file must grant 30-day unrestricted trial."""
        status = LicenseEngine.get_status()
        self.assertFalse(status.is_licensed)
        self.assertTrue(status.is_trial_active)
        self.assertEqual(status.days_remaining, 30)
        self.assertFalse(status.is_expired)
        self.assertTrue(os.path.exists(self.test_license_path))

    def test_activation_and_deactivation(self):
        """Activating with a valid key updates status to licensed; deactivating restores trial."""
        email = "fablab@maker.com"
        device_id = LicenseEngine.get_device_fingerprint()
        key = LicenseEngine.generate_license_key(email, device_id=device_id)

        # Activate
        success, msg = LicenseEngine.activate(key, email)
        self.assertTrue(success, msg)

        status = LicenseEngine.get_status()
        self.assertTrue(status.is_licensed)
        self.assertEqual(status.licensed_to, email)
        self.assertEqual(status.license_key, key)

        # Deactivate
        LicenseEngine.deactivate()
        status_after = LicenseEngine.get_status()
        self.assertFalse(status_after.is_licensed)
        self.assertTrue(status_after.is_trial_active)

    def test_clock_tamper_detection(self):
        """Detect backward system clock changes intended to extend free trial."""
        # Initialize trial
        LicenseEngine.get_status()
        
        # Load file and simulate last run was 10 days in the FUTURE
        data = LicenseEngine._read_license_file()
        data["last_run_timestamp"] = time.time() + 864000
        LicenseEngine._write_license_file(data)

        # Now get_status should detect clock tamper
        status = LicenseEngine.get_status()
        self.assertTrue(status.is_expired)
        self.assertFalse(status.is_trial_active)
        self.assertIn("Tamper Detected", status.status_text)


class TestLivingHingeEngine(unittest.TestCase):
    def test_bend_length_calculation(self):
        """Arc length L = R * theta (radians). For 90 deg and R=20mm, L = 20 * pi/2 =~ 31.416mm."""
        arc_len = LivingHingeEngine.calculate_hinge_width(bend_radius=20.0, bend_angle_deg=90.0)
        expected = 20.0 * (math.pi / 2.0)
        self.assertAlmostEqual(arc_len, expected, places=3)

        # 180 deg bend (U-bend) at 15mm radius
        u_bend = LivingHingeEngine.calculate_hinge_width(bend_radius=15.0, bend_angle_deg=180.0)
        self.assertAlmostEqual(u_bend, 15.0 * math.pi, places=3)

    def test_straight_alternating_lattice(self):
        """Verify straight alternating cut lines generation."""
        contours = LivingHingeEngine.generate_straight_lattice(
            width=50.0,
            height=30.0,
            cut_length=12.0,
            gap_length=2.5,
            column_spacing=4.0
        )
        self.assertGreater(len(contours), 0)

        for line in contours:
            self.assertEqual(len(line), 2)
            p1, p2 = line
            # Lines should be vertical cuts (x1 == x2)
            self.assertAlmostEqual(p1[0], p2[0], places=5)
            self.assertLessEqual(p1[1], p2[1])

    def test_wavy_sinuous_lattice(self):
        """Verify wavy flex pattern generation."""
        contours = LivingHingeEngine.generate_wavy_lattice(
            width=60.0,
            height=40.0,
            wave_amplitude=1.5,
            wave_wavelength=12.0,
            gap_length=2.0,
            column_spacing=4.0
        )
        self.assertGreater(len(contours), 0)
        # Each wavy line has multiple interpolated vertices
        self.assertGreater(len(contours[0]), 4)

    def test_diamond_honeycomb_lattice(self):
        """Verify diamond honeycomb flex pattern generation."""
        contours = LivingHingeEngine.generate_diamond_lattice(
            width=45.0,
            height=35.0,
            cell_size=8.0,
            slit_gap=1.5
        )
        self.assertGreater(len(contours), 0)

    def test_generate_hinge_entities(self):
        """Test entity generation with solid border tabs."""
        cfg = LivingHingeConfig(
            width=50.0,
            height=80.0,
            cut_pattern="straight",
            add_border_tabs=True,
            border_tab_width=10.0
        )
        entities = LivingHingeEngine.generate_hinge_entities(cfg)
        self.assertEqual(len(entities), 2)  # Slits + Perimeter border
        slit_entity = entities[0]
        border_entity = entities[1]
        self.assertIn("Living_Hinge_Slits", slit_entity.name)
        self.assertIn("Living_Hinge_Perimeter", border_entity.name)
        self.assertTrue(border_entity.closed)


class TestPhase3UIIntegration(unittest.TestCase):
    def test_main_window_actions_and_dialogs(self):
        """Verify MainWindow has act_living_hinge and act_license configured."""
        from laserforge.ui.main_window import MainWindow
        win = MainWindow()
        self.assertTrue(hasattr(win, "act_living_hinge"))
        self.assertTrue(hasattr(win, "act_license"))
        self.assertTrue(hasattr(win, "act_check_updates"))

        # Verify keyboard shortcut for Living Hinge is Ctrl+Alt+H
        self.assertEqual(win.act_living_hinge.shortcut().toString(), "Ctrl+Alt+H")

        # Verify title reflects license / trial
        title = win.windowTitle()
        self.assertIn("LaserForge", title)
        self.assertTrue("Trial" in title or "License" in title or "Evaluation" in title)

        win.close()


if __name__ == "__main__":
    unittest.main()
