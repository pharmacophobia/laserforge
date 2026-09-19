"""
LaserForge Commercial License & 30-Day Free Trial Engine.
Provides cryptographic offline license key validation, machine-bound activation,
and a tamper-resistant 30-day unrestricted free trial manager.

Threat model
------------
LaserForge is distributed as Python source/bytecode.  Python .pyc files are
trivially decompilable, so any secret embedded in source code must be treated
as *obfuscated*, not *secret*.  The real defence layers are:

1. **Env-var salt** (LASERFORGE_LICENSE_SALT) — set by the vendor in their
   production key-generation environment so that keys generated there cannot
   be replicated by an attacker who only has the default fall-back salt.
2. **Runtime entropy mixing** — Python version is folded into the salt so that
   keys generated under one interpreter series are not valid under another,
   raising the bar for offline replay attacks.
3. **Machine fingerprinting** — keys can be bound to a specific device ID,
   so a stolen license file cannot simply be copied to another machine.
4. **Audit logging** — all activation events are written to a local append-only
   log, providing a forensic trail for abuse investigation.

None of these measures are a silver bullet against a determined reverse-engineer
with local filesystem access.  They are layered deterrents appropriate for a
desktop indie software product.
"""

from typing import Tuple, Dict, Any, Optional
import math
import os
import sys
import json
import time
import hmac
import hashlib
import base64
import uuid
import platform
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------------------
# Salt / key derivation
# ---------------------------------------------------------------------------

_LICENSE_SALT_CACHE: Optional[bytes] = None

_AUDIT_LOG_PATH: str = os.path.expanduser("~/.laserforge/license_audit.log")


def _get_license_salt() -> bytes:
    """
    Derives the HMAC signing salt from layered sources.

    Layer 1 — obfuscated byte fragments baked into the binary.
               These are NOT a plaintext secret; they are a first-layer
               deterrent against casual inspection.

    Layer 2 — LASERFORGE_LICENSE_SALT environment variable.
               **Must** be set in the vendor's production key-generation
               environment.  Keys generated without this env var set are
               identifiable as "development/default" keys and are not
               production-secure.

    Layer 3 — Python interpreter version string.
               Folds the major.minor version into the salt so that keys are
               interpreter-series-specific, raising the cost of offline
               replay attacks.

    The result is cached for the lifetime of the process.
    """
    global _LICENSE_SALT_CACHE
    if _LICENSE_SALT_CACHE is not None:
        return _LICENSE_SALT_CACHE

    # --- Layer 1: obfuscated static fragments ---
    _A = bytes([76, 97, 115, 101, 114, 70, 111, 114, 103, 101])   # b'LaserForge'
    _B = bytes([45, 80, 114, 111, 45, 67, 65, 77, 45, 50])        # b'-Pro-CAM-2'
    _C = bytes([48, 50, 54, 45, 75, 101, 121, 83, 97, 108])       # b'026-KeySal'
    _D = bytes([116, 45, 55, 55, 50, 57, 49, 97, 120, 120])       # b't-77291axx'
    base = _A + _B + _C + _D

    # --- Layer 2: operator-supplied production salt ---
    env_salt = os.environ.get('LASERFORGE_LICENSE_SALT', '')
    if not env_salt:
        import sys as _sys
        print(
            "[LaserForge] WARNING: LASERFORGE_LICENSE_SALT env var not set. "
            "Using default salt — license keys are NOT production-secure. "
            "Set this env var in your deployment environment.",
            file=_sys.stderr
        )

    # --- Layer 3: runtime entropy — Python interpreter series ---
    entropy_mix = f"{sys.version_info.major}.{sys.version_info.minor}".encode()

    if env_salt:
        combined = base + env_salt.encode('utf-8') + entropy_mix
    else:
        combined = base + entropy_mix

    _LICENSE_SALT_CACHE = hashlib.sha256(combined).digest()
    return _LICENSE_SALT_CACHE


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def log_license_event(event_type: str, details: str) -> None:
    """
    Appends a timestamped forensic entry to the license audit log.

    The log is append-only (never truncated by this function) and lives at
    ``~/.laserforge/license_audit.log``.  Each line is a tab-separated record:

        <ISO-8601 timestamp>\\t<event_type>\\t<details>

    Args:
        event_type: A short category tag, e.g. ``'ACTIVATE_OK'``,
                    ``'ACTIVATE_FAIL'``, ``'TRIAL_EXPIRED'``,
                    ``'FINGERPRINT_MISMATCH'``.
        details:    Human-readable detail string (no tabs or newlines).
    """
    try:
        os.makedirs(os.path.dirname(_AUDIT_LOG_PATH), exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        line = f"{ts}\t{event_type}\t{details}\n"
        with open(_AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass  # Audit failure must never crash the application


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

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

    def verify_integrity(self) -> Tuple[bool, str]:
        """
        Re-validates the stored license file on disk against the current
        machine fingerprint.

        This detects VM cloning or license file transplants: if the device ID
        recorded in the license file no longer matches the live hardware
        fingerprint, the license is considered invalid on this machine.

        Returns:
            (True, "OK") if the license is intact and the fingerprint matches
            (or the installation is still in trial mode with no bound device).

            (False, <reason>) with a human-readable reason string if integrity
            cannot be confirmed.
        """
        data = LicenseEngine._read_license_file()

        # No license file at all → treat as fresh trial, nothing to verify
        if not data:
            return True, "OK (no license file — trial mode)"

        stored_device_id = data.get("device_id", "")
        live_device_id = LicenseEngine.get_device_fingerprint()

        key = data.get("license_key", "")
        email = data.get("licensed_to", "")

        # If not activated (still in trial mode), machine fingerprint binding is not enforced
        if not key:
            return True, "OK (trial mode)"

        # If an activated commercial license is bound to hardware, verify fingerprint
        if stored_device_id and stored_device_id != live_device_id:
            msg = (
                "Machine fingerprint mismatch — license not valid on this hardware"
            )
            log_license_event(
                "FINGERPRINT_MISMATCH",
                f"stored={stored_device_id} live={live_device_id}"
            )
            return False, msg

        # Re-validate the cryptographic signature
        if key and email:
            valid, msg = LicenseEngine.verify_license_key(key, email, device_id=live_device_id)
            if not valid:
                log_license_event("INTEGRITY_CHECK_FAIL", f"key_invalid email={email}")
                return False, f"License key failed cryptographic verification: {msg}"

        return True, "OK"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

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
        sig = hmac.new(_get_license_salt(), payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
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
            log_license_event("TRIAL_EXPIRED", f"device={dev_id}")
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
            log_license_event("ACTIVATE_FAIL", f"email={email} reason={msg}")
            return False, msg

        data = cls._read_license_file()
        data["license_key"] = key_str.strip().upper()
        data["licensed_to"] = email.strip().lower()
        data["license_type"] = "perpetual"
        data["activated_at"] = int(time.time())
        data["device_id"] = cls.get_device_fingerprint()
        cls._write_license_file(data)
        log_license_event("ACTIVATE_OK", f"email={email} device={dev_id}")
        return True, "LaserForge Pro successfully activated! Thank you for supporting native Linux laser software."

    @classmethod
    def deactivate(cls) -> bool:
        """Removes license key and reverts to trial mode."""
        data = cls._read_license_file()
        email = data.get("licensed_to", "unknown")
        data.pop("license_key", None)
        data.pop("licensed_to", None)
        data.pop("license_type", None)
        cls._write_license_file(data)
        log_license_event("DEACTIVATE", f"email={email}")
        return True
