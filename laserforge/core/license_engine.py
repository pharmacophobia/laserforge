"""
LaserForge Commercial License & 30-Day Free Trial Engine.
Provides cryptographic offline license key validation, machine-bound activation,
and a tamper-resistant 30-day unrestricted free trial manager.
"""

from typing import Tuple, Dict, Any, Optional
import math
import os
import json
import time
import hmac
import hashlib
import base64
import uuid
import platform
from dataclasses import dataclass, asdict

LICENSE_SALT = b"LaserForge-Pro-CAM-2026-SuperSecretKeySalt-77291a"
LICENSE_FILE_PATH = os.path.expanduser("~/.laserforge/license.json")
TRIAL_DURATION_DAYS = 30


@dataclass
class LicenseStatus:
    is_licensed: bool = False
    licensed_to: str = ""
    license_key: str = ""
    license_type: str = "trial"  # "perpetual", "commercial", "trial", "expired"
    is_trial_active: bool = True
    days_remaining: int = 30
    is_expired: bool = False
    status_text: str = "30-Day Free Trial"
    device_id: str = ""


class LicenseEngine:
    """Core cryptographic licensing and trial verification engine."""

    LICENSE_FILE_PATH: str = os.path.expanduser("~/.laserforge/license.json")

    @staticmethod
    def get_device_fingerprint() -> str:
        """Generates a stable hardware machine fingerprint (MAC address + CPU platform)."""
        try:
            node = uuid.getnode()
            plat = platform.processor() or platform.machine()
            raw = f"{node}:{plat}:{os.environ.get('USER', '')}"
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()
        except Exception:
            return "DEFAULT-DEVICE-ID"

    @classmethod
    def generate_license_key(
        cls,
        email: str,
        license_type: str = "perpetual",
        device_id: str = "",
        is_site_license: bool = False
    ) -> str:
        """
        Merchant tool to generate a valid signed commercial license key for a customer.
        Key format: LF-XXXX-XXXX-XXXX-XXXX
        """
        email_clean = email.strip().lower()
        dev_tag = "UNIVERSAL" if (is_site_license or not device_id) else device_id.strip().upper()
        payload = f"{email_clean}:{license_type}:{dev_tag}"
        sig = hmac.new(LICENSE_SALT, payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
        p_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()[:8]
        s_hash = sig[:8]
        full_code = f"{p_hash[:4]}{s_hash[:4]}{p_hash[4:8]}{s_hash[4:8]}"
        return f"LF-{full_code[0:4]}-{full_code[4:8]}-{full_code[8:12]}-{full_code[12:16]}"

    @classmethod
    def verify_license_key(cls, key_str: str, email: str, device_id: str = "") -> Tuple[bool, str]:
        """Verifies if a license key matches the customer email and cryptographic signature."""
        if not key_str or not email:
            return False, "License key and registered email are required."

        key_clean = key_str.strip().upper().replace(" ", "")
        email_clean = email.strip().lower()

        # Check machine-bound keys
        if device_id:
            for ltype in ["perpetual", "commercial", "pro"]:
                if key_clean == cls.generate_license_key(email_clean, ltype, device_id=device_id):
                    return True, f"Valid {ltype.capitalize()} License (Machine-Bound)"

        # Check site / universal keys
        for ltype in ["perpetual", "commercial", "pro"]:
            if key_clean == cls.generate_license_key(email_clean, ltype, is_site_license=True):
                return True, f"Valid {ltype.capitalize()} License (Site/Universal)"

        return False, "Invalid license key for this email address."

    validate_key = verify_license_key

    @classmethod
    def _read_license_file(cls) -> Dict[str, Any]:
        path = cls.LICENSE_FILE_PATH
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_b64 = f.read().strip()
                json_str = base64.b64decode(raw_b64.encode("utf-8")).decode("utf-8")
                return json.loads(json_str)
        except Exception:
            return {}

    @classmethod
    def _write_license_file(cls, data: Dict[str, Any]):
        path = cls.LICENSE_FILE_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            json_str = json.dumps(data, indent=2)
            raw_b64 = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw_b64)
        except Exception as e:
            print(f"Error writing license file: {e}")

    @classmethod
    def get_status(cls) -> LicenseStatus:
        """Evaluates current licensing and 30-day trial status."""
        data = cls._read_license_file()
        now = int(time.time())
        dev_id = cls.get_device_fingerprint()

        # 1. Check if activated with valid key
        key = data.get("license_key", "")
        email = data.get("licensed_to", "")
        if key and email:
            valid, msg = cls.verify_license_key(key, email, device_id=dev_id)
            if valid:
                return LicenseStatus(
                    is_licensed=True,
                    licensed_to=email,
                    license_key=key,
                    license_type=data.get("license_type", "perpetual"),
                    is_trial_active=False,
                    days_remaining=9999,
                    is_expired=False,
                    status_text=f"Licensed to {email}",
                    device_id=dev_id
                )

        # 2. Check 30-day trial status
        first_run = data.get("first_run_timestamp")
        last_run = data.get("last_run_timestamp", now)

        if first_run is None:
            # First launch ever: initialize trial
            first_run = now
            last_run = now
            data["first_run_timestamp"] = first_run
            data["last_run_timestamp"] = last_run
            data["run_count"] = 1
            data["device_id"] = dev_id
            cls._write_license_file(data)

        # Anti-tamper clock rollback detection
        if now < last_run - 86400:  # Clock moved back more than 24 hours
            return LicenseStatus(
                is_licensed=False,
                is_trial_active=False,
                days_remaining=0,
                is_expired=True,
                status_text="Trial Clock Error (Tamper Detected)",
                device_id=dev_id
            )

        # Update last_run
        data["last_run_timestamp"] = now
        data["run_count"] = data.get("run_count", 0) + 1
        cls._write_license_file(data)

        elapsed_sec = max(0, now - first_run)
        total_trial_sec = TRIAL_DURATION_DAYS * 86400
        remaining_sec = max(0, total_trial_sec - elapsed_sec)
        days_left = int(math.ceil(remaining_sec / 86400.0))

        if days_left <= 0:
            return LicenseStatus(
                is_licensed=False,
                is_trial_active=False,
                days_remaining=0,
                is_expired=True,
                status_text="30-Day Free Trial Expired",
                device_id=dev_id
            )

        return LicenseStatus(
            is_licensed=False,
            is_trial_active=True,
            days_remaining=days_left,
            is_expired=False,
            status_text=f"30-Day Free Trial ({days_left} days left)",
            device_id=dev_id
        )

    @classmethod
    def activate(cls, key_str: str, email: str) -> Tuple[bool, str]:
        """Activates LaserForge with a purchased license key and email."""
        dev_id = cls.get_device_fingerprint()
        valid, msg = cls.verify_license_key(key_str, email, device_id=dev_id)
        if not valid:
            return False, msg

        data = cls._read_license_file()
        data["license_key"] = key_str.strip().upper()
        data["licensed_to"] = email.strip().lower()
        data["license_type"] = "perpetual"
        data["activated_at"] = int(time.time())
        data["device_id"] = cls.get_device_fingerprint()
        cls._write_license_file(data)
        return True, "LaserForge Pro successfully activated! Thank you for supporting native Linux laser software."

    @classmethod
    def deactivate(cls) -> bool:
        """Removes license key and reverts to trial mode."""
        data = cls._read_license_file()
        data.pop("license_key", None)
        data.pop("licensed_to", None)
        data.pop("license_type", None)
        cls._write_license_file(data)
        return True
