"""
LaserForge Automated Laser Connection & Device Discovery Engine.
Provides:
- Intelligent USB device identification, VID/PID matching, and ranked port sorting.
- Fast non-destructive GRBL handshake probe (status query, soft-reset banner check).
- Background asynchronous scanning worker (QThread) to prevent GUI freezes.
- USB hotplug watcher for instant auto-connect upon cable insertion or power-up.
- Auto-reconnection watchdog on unexpected disconnection.
"""

from dataclasses import dataclass
import re
import threading
import time
from typing import Dict, List, Optional, Tuple, Any

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QObject, QThread, pyqtSignal, QTimer


# Known Laser Engraver & CNC USB-UART Controller Chips (VID, PID)
KNOWN_LASER_CHIPS: Dict[Tuple[int, int], Dict[str, str]] = {
    # WCH CH340 / CH341 (Standard for Ortur, Atomstack, Sculpfun, EleksMaker, CNC3018, TwoTrees, Neje)
    (0x1A86, 0x7523): {"chip": "CH340", "desc": "WCH CH340 USB-Serial (Standard Laser Engraver)"},
    (0x1A86, 0x5523): {"chip": "CH341", "desc": "WCH CH341 USB-Serial (Laser / CNC)"},
    (0x1A86, 0x7522): {"chip": "CH340K", "desc": "WCH CH340K USB-Serial"},

    # Silicon Labs CP210x (Used on xTool, LaserTree, Elegoo, ESP32 laser boards)
    (0x10C4, 0xEA60): {"chip": "CP2102/CP2104", "desc": "Silicon Labs CP210x USB to UART"},
    (0x10C4, 0xEA70): {"chip": "CP2105", "desc": "Silicon Labs Dual CP2105 USB to UART"},

    # FTDI Chips
    (0x0403, 0x6001): {"chip": "FT232R", "desc": "FTDI FT232R USB UART"},
    (0x0403, 0x6015): {"chip": "FT231X", "desc": "FTDI FT231X Full Speed USB UART"},

    # Prolific
    (0x067B, 0x2303): {"chip": "PL2303", "desc": "Prolific PL2303 USB-to-Serial"},

    # Arduino / Atmel (Uno, Nano, Mega running GRBL)
    (0x2341, 0x0043): {"chip": "ATmega328P", "desc": "Arduino Uno (GRBL 1.1)"},
    (0x2341, 0x0001): {"chip": "ATmega16U2", "desc": "Arduino Uno Rev3 (GRBL)"},
    (0x2341, 0x0010): {"chip": "ATmega2560", "desc": "Arduino Mega 2560 (GRBL-Mega)"},
    (0x2341, 0x0042): {"chip": "ATmega2560", "desc": "Arduino Mega (GRBL)"},

    # Raspberry Pi Pico / RP2040 (GRBL-HAL)
    (0x2E8A, 0x0003): {"chip": "RP2040", "desc": "Raspberry Pi Pico (grblHAL)"},
    (0x2E8A, 0x000A): {"chip": "RP2040", "desc": "Raspberry Pi Pico CDC UART"},

    # Espressif ESP32 (FluidNC / GRBL-ESP32 / LaserWeb)
    (0x303A, 0x1001): {"chip": "ESP32-S3", "desc": "Espressif ESP32-S3 (FluidNC / GRBL)"},
    (0x303A, 0x0002): {"chip": "ESP32", "desc": "Espressif ESP32 ROM CDC"},

    # STM32 Microcontrollers
    (0x0483, 0x5740): {"chip": "STM32F4", "desc": "STM32 Virtual COM Port (grblHAL)"},
}

# Standard GRBL Baud Rates to probe (ordered by frequency of use)
PROBE_BAUD_RATES = (115200, 250000, 57600, 9600, 38400)


@dataclass
class RankedPort:
    device: str
    description: str
    hwid: str
    vid: Optional[int]
    pid: Optional[int]
    chip_info: str
    display_name: str
    score: int
    is_usb: bool


class PortDetector:
    """Discovers, identifies, and ranks serial ports by likelihood of being a laser engraver."""

    @staticmethod
    def get_ranked_ports(include_dummy_tty: bool = False) -> List[RankedPort]:
        """
        Lists available ports sorted with top laser candidates first.
        Filters out inactive legacy motherboard ports (/dev/ttyS*) by default.
        """
        raw_ports = serial.tools.list_ports.comports()
        ranked: List[RankedPort] = []

        for p in raw_ports:
            dev = p.device
            desc = p.description or ""
            hwid = p.hwid or ""
            vid = p.vid
            pid = p.pid

            # Detect dummy motherboard serial ports on Linux (/dev/ttyS0 through /dev/ttyS31)
            is_dummy_linux_tty = bool(re.match(r"^/dev/ttyS\d+$", dev))
            if is_dummy_linux_tty and not include_dummy_tty:
                continue

            score = 0
            chip_info = ""

            # Check for known USB laser chips
            if vid is not None and pid is not None:
                chip_match = KNOWN_LASER_CHIPS.get((vid, pid))
                if chip_match:
                    chip_info = chip_match["desc"]
                    score += 150

            # Inspect device path naming
            is_usb = False
            dev_lower = dev.lower()
            if any(prefix in dev_lower for prefix in ("ttyusb", "ttyacm", "cu.usb", "rfcomm")):
                is_usb = True
                score += 80
            elif "com" in dev_lower and dev_lower not in ("com1", "com2"):
                is_usb = True
                score += 70

            # Inspect description keywords
            desc_lower = (desc + " " + hwid).lower()
            for kw in ("laser", "engraver", "grbl", "cnc", "ch340", "ch341", "cp210", "ftdi", "uart", "usb serial"):
                if kw in desc_lower:
                    score += 40
                    break

            if is_dummy_linux_tty:
                score -= 200

            # Build human-readable friendly display name
            if chip_info:
                display_name = f"{dev} — {chip_info}"
            elif desc and desc != "n/a" and desc != dev:
                display_name = f"{dev} — {desc}"
            elif is_usb:
                display_name = f"{dev} (USB Serial Device)"
            else:
                display_name = dev

            ranked.append(RankedPort(
                device=dev,
                description=desc,
                hwid=hwid,
                vid=vid,
                pid=pid,
                chip_info=chip_info,
                display_name=display_name,
                score=score,
                is_usb=is_usb
            ))

        ranked.sort(key=lambda x: x.score, reverse=True)

        # Always include the Virtual GRBL Simulator port for test-driving
        ranked.append(RankedPort(
            device="VIRTUAL_GRBL",
            description="LaserForge Virtual GRBL 1.1f Simulator",
            hwid="VIRTUAL_SIMULATOR",
            vid=0x0000,
            pid=0x0000,
            chip_info="In-Memory GRBL Simulator",
            display_name="VIRTUAL_GRBL (Software Simulator)",
            score=5,
            is_usb=False
        ))

        return ranked


def probe_port_for_grbl(
    port: str,
    baud_rates: Tuple[int, ...] = PROBE_BAUD_RATES,
    timeout: float = 0.45
) -> Tuple[bool, Optional[int], str]:
    """
    Safely probes a serial port to verify whether a GRBL laser controller is attached.
    Returns: (is_grbl, baud_rate, status_or_banner)
    Non-destructive: closes port before returning.
    """
    if port.upper().startswith("VIRTUAL"):
        return True, 115200, "Grbl 1.1f ['$' for help] (Virtual Simulator)"
    for baud in baud_rates:
        ser = None
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud,
                timeout=timeout,
                write_timeout=timeout
            )
            # Brief delay for DTR/RTS boot reset on some microcontrollers
            time.sleep(0.3)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # 1. First attempt: standard non-invasive status query '?'
            ser.write(b"?\n")
            time.sleep(0.2)
            resp = ser.read(ser.in_waiting or 256).decode("latin1", errors="replace")

            if "<" in resp or "Grbl" in resp:
                ser.close()
                return True, baud, resp.strip()

            # 2. Second attempt: wake-up newline + status
            ser.write(b"\n$$\n")
            time.sleep(0.2)
            resp2 = ser.read(ser.in_waiting or 256).decode("latin1", errors="replace")
            if "<" in resp2 or "Grbl" in resp2 or "$0=" in resp2 or "ok" in resp2:
                ser.close()
                return True, baud, resp2.strip()

            # 3. Third attempt: soft reset (0x18 / Ctrl+X)
            ser.write(b"\x18\n")
            time.sleep(0.3)
            resp3 = ser.read(ser.in_waiting or 256).decode("latin1", errors="replace")
            ser.close()
            if "Grbl" in resp3 or "<" in resp3:
                return True, baud, resp3.strip()

        except (serial.SerialException, OSError):
            if ser and ser.is_open:
                try: ser.close()
                except Exception: pass
            continue
        except Exception:
            if ser and ser.is_open:
                try: ser.close()
                except Exception: pass
            continue

    return False, None, ""


class AutoConnectWorker(QThread):
    """
    Background worker thread that scans available serial ports,
    probes them for a responding GRBL controller, and reports results.
    """
    probe_started = pyqtSignal()
    probe_progress = pyqtSignal(str)              # Status message (e.g. "Probing /dev/ttyUSB1 @ 115200...")
    laser_found = pyqtSignal(str, int, str)        # (port, baud, banner)
    probe_failed = pyqtSignal(str)                # Failure reason
    probe_finished = pyqtSignal(bool, str)        # (success, message)

    def __init__(self, preferred_port: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.preferred_port = preferred_port
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        self.probe_started.emit()
        ports = PortDetector.get_ranked_ports(include_dummy_tty=False)

        if not ports:
            # Try once with all ports if no USB ports found
            ports = PortDetector.get_ranked_ports(include_dummy_tty=True)

        if not ports:
            self.probe_failed.emit("No serial communication ports detected on system.")
            self.probe_finished.emit(False, "No serial ports found")
            return

        # If preferred port is specified, move it to the very front
        if self.preferred_port:
            matching = [p for p in ports if p.device == self.preferred_port]
            non_matching = [p for p in ports if p.device != self.preferred_port]
            ports = matching + non_matching

        self.probe_progress.emit(f"Scanning {len(ports)} candidate serial port(s)...")

        for idx, port_info in enumerate(ports):
            if self._abort:
                self.probe_finished.emit(False, "Scan aborted")
                return

            dev = port_info.device
            chip_lbl = f" ({port_info.chip_info})" if port_info.chip_info else ""
            self.probe_progress.emit(f"Testing {dev}{chip_lbl}...")

            is_grbl, baud, banner = probe_port_for_grbl(dev, PROBE_BAUD_RATES, timeout=0.4)

            if is_grbl and baud:
                summary = banner.splitlines()[0] if banner else "GRBL Laser Controller"
                self.laser_found.emit(dev, baud, summary)
                self.probe_progress.emit(f"Found GRBL Laser on {dev} @ {baud} baud!")
                self.probe_finished.emit(True, f"Connected to {dev} ({summary})")
                return

        self.probe_failed.emit(
            "Laser not responding on any scanned port. Ensure power switch is ON and USB cable is plugged in."
        )
        self.probe_finished.emit(False, "No GRBL laser found")


class USBHotplugWatcher(QObject):
    """
    Periodically polls system serial ports to detect device insertions/removals
    and triggers automated connection or UI dropdown refresh.
    """
    ports_changed = pyqtSignal(list)       # List of RankedPort
    device_inserted = pyqtSignal(str)      # Device path of newly added port
    device_removed = pyqtSignal(str)       # Device path of removed port

    def __init__(self, check_interval_ms: int = 1500, parent=None):
        super().__init__(parent)
        self.known_devices: set = set()
        self.check_interval_ms = check_interval_ms
        self.timer: Optional[QTimer] = None
        self._stop_event: Optional[threading.Event] = None
        self._thread_worker: Optional[threading.Thread] = None
        self._initial_check()

    def start(self):
        from PyQt6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        curr_thread = QThread.currentThread()
        if app and curr_thread and curr_thread.eventDispatcher() is not None:
            if not self.timer:
                self.timer = QTimer(self)
                self.timer.setInterval(self.check_interval_ms)
                self.timer.timeout.connect(self._check_ports)
            self.timer.start()
        else:
            self.stop()
            self._stop_event = threading.Event()
            self._thread_worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread_worker.start()

    def _worker_loop(self):
        interval_sec = max(0.1, self.check_interval_ms / 1000.0)
        while self._stop_event and not self._stop_event.is_set():
            if self._stop_event.wait(interval_sec):
                break
            try:
                self._check_ports()
            except Exception:
                pass

    def stop(self):
        if self.timer:
            try:
                self.timer.stop()
            except Exception:
                pass
            self.timer = None
        if self._stop_event:
            self._stop_event.set()
        if self._thread_worker and self._thread_worker.is_alive():
            try:
                self._thread_worker.join(timeout=0.2)
            except Exception:
                pass
            self._thread_worker = None

    def _initial_check(self):
        ports = PortDetector.get_ranked_ports(include_dummy_tty=False)
        self.known_devices = {p.device for p in ports}

    def _check_ports(self):
        ports = PortDetector.get_ranked_ports(include_dummy_tty=False)
        current_devices = {p.device for p in ports}

        new_devices = current_devices - self.known_devices
        removed_devices = self.known_devices - current_devices

        if new_devices or removed_devices:
            self.known_devices = current_devices
            self.ports_changed.emit(ports)

            for d in new_devices:
                self.device_inserted.emit(d)

            for d in removed_devices:
                self.device_removed.emit(d)
