"""
LaserForge Telemetry & Diagnostics Engine.
Provides crash reporting, system diagnostics gathering, privacy anonymization,
and feedback dispatching for beta testers and end users.
"""

import os
import sys
import time
import json
import platform
import traceback
import zipfile
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field, asdict
import urllib.request
import urllib.error


CRASH_DIR = os.path.expanduser("~/.laserforge/crashes")


def sanitize_text(text: str) -> str:
    """Anonymizes sensitive user identifiers and personal paths from logs and tracebacks."""
    if not text:
        return ""
    home = os.path.expanduser("~")
    sanitized = text.replace(home, "~")
    user = os.environ.get("USER", "")
    if user and len(user) > 2:
        sanitized = sanitized.replace(f"/{user}/", "/user/")
    return sanitized


def collect_system_diagnostics(settings=None, serial_ctrl=None) -> Dict[str, Any]:
    """Collects non-invasive system hardware, OS, Python, and controller diagnostics."""
    diagnostics: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "laserforge_version": "2.5.0-beta",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "platform_str": platform.platform(),
            "display_server": (
                "Wayland" if os.environ.get("WAYLAND_DISPLAY") else
                ("X11" if os.environ.get("DISPLAY") else "Headless")
            )
        },
        "python": {
            "version": platform.python_version(),
            "compiler": platform.python_compiler(),
            "build": platform.python_build()[0],
        },
        "hardware": {
            "cpu_cores": os.cpu_count() or 1,
        }
    }

    # Query GPU acceleration hardware info if available
    try:
        from laserforge.core.gpu_accelerator import GPUAccelerator
        gpu_info = GPUAccelerator.get_hardware_info()
        diagnostics["hardware"]["gpu"] = {
            "summary": gpu_info.summary_short(),
            "opencl_available": gpu_info.opencl_available,
            "device_name": gpu_info.device_name,
            "vendor": gpu_info.vendor,
            "driver_version": gpu_info.driver_version
        }
    except Exception:
        diagnostics["hardware"]["gpu"] = "Unavailable"

    # Query connected laser machine settings and state if available
    if settings is not None:
        diagnostics["machine_settings"] = {
            "bed_width": getattr(settings, "bed_width", 400.0),
            "bed_height": getattr(settings, "bed_height", 400.0),
            "rapid_speed": getattr(settings, "rapid_speed", 3000.0),
            "max_s_value": getattr(settings, "max_s_value", 1000),
            "laser_mode": getattr(settings, "laser_mode", True),
            "last_connected_port": sanitize_text(str(getattr(settings, "last_connected_port", ""))),
            "auto_connect": getattr(settings, "auto_connect", True)
        }

    if serial_ctrl is not None:
        diagnostics["serial_controller"] = {
            "is_connected": getattr(serial_ctrl, "is_connected", False),
            "port_name": sanitize_text(str(getattr(serial_ctrl, "port_name", ""))),
            "machine_state": getattr(serial_ctrl, "machine_state", "Disconnected")
        }

    return diagnostics


@dataclass
class FeedbackReport:
    """Encapsulates a user bug report, suggestion, or crash log."""
    category: str  # "Bug Report", "Hardware Issue", "Feature Request", "General Feedback"
    subject: str
    message: str
    contact_info: str = ""  # User email, GitHub handle, or Discord username (optional)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    recent_logs: List[str] = field(default_factory=list)
    stack_trace: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_markdown(self) -> str:
        """Formats the report into clean GitHub / Discord markdown."""
        md = [
            f"# LaserForge Feedback: [{self.category}] {self.subject}",
            f"**Submitted**: {self.timestamp}",
            f"**Contact**: {self.contact_info or 'Anonymous Beta Tester'}",
            "",
            "## Description / Steps to Reproduce",
            self.message or "*(No description provided)*",
            ""
        ]

        if self.stack_trace:
            md.extend([
                "## Exception Stack Trace",
                "```python",
                sanitize_text(self.stack_trace.strip()),
                "```",
                ""
            ])

        if self.diagnostics:
            p = self.diagnostics.get("platform", {})
            py = self.diagnostics.get("python", {})
            hw = self.diagnostics.get("hardware", {})
            gpu = hw.get("gpu", {})
            gpu_str = gpu.get("summary", "N/A") if isinstance(gpu, dict) else str(gpu)

            md.extend([
                "## System Diagnostics",
                f"- **LaserForge Version**: {self.diagnostics.get('laserforge_version', 'Unknown')}",
                f"- **OS**: {p.get('platform_str', 'Unknown')} ({p.get('display_server', 'N/A')})",
                f"- **Python**: {py.get('version', 'Unknown')}",
                f"- **CPU**: {hw.get('cpu_cores', '?')} Cores | **GPU**: {gpu_str}",
                ""
            ])

            ms = self.diagnostics.get("machine_settings")
            sc = self.diagnostics.get("serial_controller")
            if ms or sc:
                conn_str = f"Connected ({sc.get('port_name', '')})" if (sc and sc.get("is_connected")) else "Disconnected"
                bed_str = f"{ms.get('bed_width', '?')} × {ms.get('bed_height', '?')} mm" if ms else "N/A"
                md.extend([
                    "## Machine Status",
                    f"- **Connection**: {conn_str}",
                    f"- **Workbed**: {bed_str}",
                    ""
                ])

        if self.recent_logs:
            md.extend([
                "## Recent Machine Communications (Last Events)",
                "```text",
                "\n".join(sanitize_text(line.strip()) for line in self.recent_logs[-30:]),
                "```",
                ""
            ])

        return "\n".join(md)

    def send_via_webhook(self, webhook_url: str) -> Tuple[bool, str]:
        """Dispatches payload to a Discord webhook, Slack webhook, or HTTP endpoint."""
        if not webhook_url:
            return False, "No webhook URL configured."

        try:
            # Format payload compatible with Discord / Slack / standard JSON endpoint
            clean_md = self.to_markdown()

            # Discord embeds limit is 4096 chars
            summary_desc = (self.message[:500] + "...") if len(self.message) > 500 else (self.message or "Feedback submitted")

            payload = {
                "username": "LaserForge Beta Telemetry",
                "content": f"**[{self.category}]** {self.subject} (from `{self.contact_info or 'Anonymous'}`)",
                "embeds": [
                    {
                        "title": f"{self.category}: {self.subject}",
                        "description": summary_desc,
                        "color": 0x00E5FF if self.category != "Bug Report" else 0xFF3D71,
                        "fields": [
                            {"name": "App Version", "value": self.diagnostics.get("laserforge_version", "2.5.0-beta"), "inline": True},
                            {"name": "OS", "value": self.diagnostics.get("platform", {}).get("platform_str", "Linux")[:30], "inline": True},
                            {"name": "Timestamp", "value": self.timestamp, "inline": True}
                        ]
                    }
                ],
                # Include full structured JSON for generic API webhooks
                "raw_report": {
                    "category": self.category,
                    "subject": self.subject,
                    "message": self.message,
                    "contact": self.contact_info,
                    "diagnostics": self.diagnostics,
                    "stack_trace": sanitize_text(self.stack_trace)
                }
            }

            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=req_data,
                headers={"Content-Type": "application/json", "User-Agent": "LaserForge-Telemetry/2.5.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if 200 <= resp.status < 300:
                    return True, "Feedback successfully delivered to the creator!"
                else:
                    return False, f"Server responded with status {resp.status}"
        except urllib.error.URLError as e:
            return False, f"Network error: {e.reason}"
        except Exception as e:
            return False, f"Delivery error: {e}"

    def export_bundle(self, out_zip_path: str, screenshot_bytes: Optional[bytes] = None) -> str:
        """Packs the markdown report, diagnostics JSON, and optional screenshot into a single zip file."""
        os.makedirs(os.path.dirname(os.path.abspath(out_zip_path)), exist_ok=True)
        with zipfile.ZipFile(out_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("issue_report.md", self.to_markdown())
            zf.writestr("diagnostics.json", json.dumps(self.diagnostics, indent=2))
            if self.recent_logs:
                zf.writestr("serial_console.log", "\n".join(self.recent_logs))
            if screenshot_bytes:
                zf.writestr("canvas_screenshot.png", screenshot_bytes)
        return out_zip_path


class CrashManager:
    """Catches unhandled exceptions and saves timestamped crash reports."""

    _installed = False
    _original_excepthook = sys.excepthook
    _context_provider = None

    @classmethod
    def register_context_provider(cls, provider_callable):
        """Allows MainWindow or application state to attach current settings/serial context."""
        cls._context_provider = provider_callable

    @classmethod
    def install(cls):
        """Installs the global Python excepthook."""
        if cls._installed:
            return
        cls._original_excepthook = sys.excepthook
        sys.excepthook = cls._on_unhandled_exception
        cls._installed = True

    @classmethod
    def _on_unhandled_exception(cls, exc_type, exc_value, exc_tb):
        """Handles uncaught exceptions by logging a crash dump and alerting the user."""
        # 1. Print standard traceback to stderr
        trace_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"\n[LaserForge CRASH INTERCEPTOR]\n{trace_str}", file=sys.stderr)

        # 2. Gather diagnostics
        ctx = cls._context_provider() if callable(cls._context_provider) else {}
        settings = ctx.get("settings")
        serial_ctrl = ctx.get("serial")
        recent_logs = ctx.get("recent_logs", [])

        diag = collect_system_diagnostics(settings=settings, serial_ctrl=serial_ctrl)

        # 3. Save crash dump to disk
        try:
            os.makedirs(CRASH_DIR, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            dump_file = os.path.join(CRASH_DIR, f"crash_{ts}.json")
            dump_data = {
                "timestamp": ts,
                "exception_type": getattr(exc_type, "__name__", str(exc_type)),
                "exception_message": str(exc_value),
                "stack_trace": sanitize_text(trace_str),
                "diagnostics": diag,
                "recent_logs": recent_logs[-50:] if recent_logs else []
            }
            with open(dump_file, "w", encoding="utf-8") as f:
                json.dump(dump_data, f, indent=2)

            log_file = os.path.join(CRASH_DIR, "crash_history.log")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {getattr(exc_type, '__name__', 'Error')}: {exc_value}\n")
        except Exception as e:
            print(f"[LaserForge] Failed to write crash dump: {e}", file=sys.stderr)

        # 4. Display interactive crash dialog if Qt application is running
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app and not os.environ.get("LASERFORGE_HEADLESS"):
                from laserforge.ui.feedback_dialog import CrashReportDialog
                dlg = CrashReportDialog(
                    exc_type=getattr(exc_type, "__name__", str(exc_type)),
                    exc_value=str(exc_value),
                    stack_trace=trace_str,
                    diagnostics=diag,
                    recent_logs=recent_logs
                )
                dlg.exec()
        except Exception as e:
            print(f"[LaserForge] Could not launch crash dialog: {e}", file=sys.stderr)

        # Call original excepthook
        cls._original_excepthook(exc_type, exc_value, exc_tb)


def get_last_crash_report() -> Optional[Dict[str, Any]]:
    """Retrieves the most recent crash report from disk, or None."""
    if not os.path.isdir(CRASH_DIR):
        return None
    files = sorted(
        [os.path.join(CRASH_DIR, f) for f in os.listdir(CRASH_DIR) if f.startswith("crash_") and f.endswith(".json")],
        reverse=True
    )
    if not files:
        return None
    try:
        with open(files[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
