"""
LaserForge Z-Probe and Auto-Focus Controller.

Provides automated touch-plate probing cycles (G38.2/G38.3) to zero the Z-axis,
measure material thickness, and position the laser head at exact optical focus:
- Safe feed rate with relative travel limits (G91 G38.2 Z-... F...)
- Touch plate thickness compensation (Z0 = Z_trigger + plate_thickness)
- Optical lens focal distance preset adjustment
- GRBL [PRB:...] response parsing and coordinate zeroing (G10 L20 P1 Z...)
- Post-probe safe retract cycle
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
import re
import time
import threading
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class ZProbeSettings:
    """Parameters configuring the Z-touch plate probing operation."""
    probe_command: str = "G38.2"          # G38.2 (stop on touch, error on miss), G38.3 (no error)
    feed_rate_mm_min: float = 120.0       # Safe slow descent speed (mm/min)
    max_travel_mm: float = 40.0           # Max downwards Z distance to probe before aborting
    retract_distance_mm: float = 3.0      # Distance to retract above trigger point after probing
    plate_thickness_mm: float = 15.0      # Calibrated touch plate thickness in mm
    focal_offset_mm: float = 0.0          # Optical lens focal offset from top of plate to focal point
    auto_zero_work_z: bool = True         # Apply G10 L20 P1 Z{plate + focal} to set WCS Z zero
    restore_wcs: bool = True              # Return to absolute coordinates (G90) upon completion


class ZProbeEngine(QObject):
    """
    Coordinates G-code dispatch and response parsing for laser auto-focus probe cycles.
    """
    probe_started = pyqtSignal()
    probe_progress = pyqtSignal(str)
    probe_success = pyqtSignal(float)      # Triggered Z machine position
    probe_failed = pyqtSignal(str)         # Failure message

    def __init__(self, serial_controller=None, parent=None):
        super().__init__(parent)
        self.serial_ctrl = serial_controller
        self.settings = ZProbeSettings()
        self.is_probing = False
        self._last_probe_pos: Optional[Tuple[float, float, float]] = None

    def generate_probe_gcode(self, settings: Optional[ZProbeSettings] = None) -> List[str]:
        """
        Generates the standard, non-destructive sequence of G-code commands
        for an auto-focus touch plate probe.
        """
        cfg = settings or self.settings
        cmd = cfg.probe_command
        feed = max(10.0, cfg.feed_rate_mm_min)
        dist = max(1.0, abs(cfg.max_travel_mm))
        retract = max(0.5, cfg.retract_distance_mm)
        thickness = cfg.plate_thickness_mm
        focal = cfg.focal_offset_mm
        total_z_ref = thickness + focal

        lines = [
            "; --- LaserForge Auto-Focus Z-Probe Cycle ---",
            "G91",                                      # Relative positioning
            f"{cmd} Z-{dist:.3f} F{feed:.1f}",          # Probe toward touch plate
            "G90",                                      # Absolute positioning
        ]

        if cfg.auto_zero_work_z:
            # Set current position as calibrated touch plate reference
            lines.append(f"G10 L20 P1 Z{total_z_ref:.3f}")

        # Retract safely above plate
        lines.append("G91")
        lines.append(f"G0 Z{retract:.3f}")
        lines.append("G90")
        lines.append("; --- End Z-Probe Cycle ---")

        return lines

    @staticmethod
    def parse_grbl_prb(response_line: str) -> Optional[Tuple[float, float, float, bool]]:
        """
        Parses GRBL probe result response line:
        Example: [PRB:0.000,0.000,-14.235:1]
        Returns: (x, y, z, success)
        """
        match = re.search(r"\[PRB:([-+]?[0-9]*\.?[0-9]+),([-+]?[0-9]*\.?[0-9]+),([-+]?[0-9]*\.?[0-9]+):([01])\]", response_line)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            z = float(match.group(3))
            ok = (match.group(4) == "1")
            return (x, y, z, ok)
        return None

    def execute_probe(self, settings: Optional[ZProbeSettings] = None) -> bool:
        """
        Streams probe command sequence through SerialController with synchronous
        acknowledgment tracking and PRB response parsing.
        """
        if not self.serial_ctrl or not getattr(self.serial_ctrl, "is_connected", False):
            self.probe_failed.emit("Laser is not connected. Please connect via serial port first.")
            return False

        if getattr(self.serial_ctrl, "is_streaming", False):
            self.probe_failed.emit("Cannot run Z-probe while a job is actively streaming.")
            return False

        if self.is_probing:
            self.probe_failed.emit("A probe cycle is already in progress.")
            return False

        cfg = settings or self.settings
        self.is_probing = True
        self.probe_started.emit()
        self.probe_progress.emit(f"Starting Z-probe toward plate ({cfg.feed_rate_mm_min:.0f} mm/min)...")

        worker = threading.Thread(target=self._probe_worker, args=(cfg,), daemon=True)
        worker.start()
        return True

    def _probe_worker(self, cfg: ZProbeSettings):
        prb_result: Optional[Tuple[float, float, float, bool]] = None

        def on_log(direction: str, text: str):
            nonlocal prb_result
            if direction == "rx" and "[PRB:" in text:
                parsed = self.parse_grbl_prb(text)
                if parsed:
                    prb_result = parsed

        try:
            if hasattr(self.serial_ctrl, "log_received"):
                self.serial_ctrl.log_received.connect(on_log)

            # Drain residual ack_queue
            if hasattr(self.serial_ctrl, "ack_queue"):
                while not self.serial_ctrl.ack_queue.empty():
                    try:
                        self.serial_ctrl.ack_queue.get_nowait()
                    except Exception:
                        break

            # Calculate safe timeout for probe move:
            # travel_time = (max_travel_mm / feed_rate_mm_min) * 60 + 10 seconds margin
            probe_timeout = (abs(cfg.max_travel_mm) / max(1.0, cfg.feed_rate_mm_min)) * 60.0 + 10.0

            gcode_cmds = self.generate_probe_gcode(cfg)
            for cmd in gcode_cmds:
                cl = cmd.strip()
                if not cl or cl.startswith(";"):
                    continue

                is_probe_cmd = "G38." in cl
                timeout = probe_timeout if is_probe_cmd else 5.0

                self.serial_ctrl.send_command(cl)

                # Wait for ACK if ack_queue is available
                if hasattr(self.serial_ctrl, "ack_queue"):
                    try:
                        token_type, token_val = self.serial_ctrl.ack_queue.get(timeout=timeout)
                        if token_type in ("error", "alarm"):
                            self.probe_failed.emit(f"Controller {token_type}: {token_val}")
                            return
                    except Exception:
                        self.probe_failed.emit(f"Command timed out waiting for response: {cl}")
                        return

                if is_probe_cmd and prb_result is not None:
                    _x, _y, z, ok = prb_result
                    if not ok:
                        self.probe_failed.emit("Touch plate was not contacted within max travel limit.")
                        return
                    self._last_probe_pos = (_x, _y, z)

            # Successfully completed sequence
            triggered_z = self._last_probe_pos[2] if self._last_probe_pos else 0.0
            self.probe_success.emit(triggered_z)
            self.probe_progress.emit(f"Probe completed successfully (Z={triggered_z:.3f} mm).")

        except Exception as e:
            self.probe_failed.emit(f"Probing error: {e}")
        finally:
            self.is_probing = False
            if hasattr(self.serial_ctrl, "log_received"):
                try:
                    self.serial_ctrl.log_received.disconnect(on_log)
                except Exception:
                    pass
