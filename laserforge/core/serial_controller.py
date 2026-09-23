"""
LaserForge Serial Controller for GRBL Laser Engravers.
Provides high-speed buffered G-code streaming, real-time status polling, jogging,
homing, framing, and emergency stop abort handling via PyQt6 QThread signals.
"""

import time
import threading
import queue
import re
import socket
import select
from typing import List, Optional, Tuple, Dict, Any
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from laserforge.core.auto_connect import (
    PortDetector, AutoConnectWorker, USBHotplugWatcher, RankedPort
)


def sanitize_gcode_line(line: str) -> str:
    """
    Sanitizes a single G-code line before transmission to GRBL hardware.
    1. Removes inline semicolon comments ('; ...' to end of line).
    2. Removes parenthesis comments ('(...)').
    3. Strips whitespace and returns clean machine command.
    """
    if not line:
        return ""
    # Strip semicolon comments
    s = line.split(";", 1)[0]
    # Strip parenthesis comments
    s = re.sub(r"\(.*?\)", "", s)
    return s.strip()


# Standard GRBL 1.1 Error Code Reference
GRBL_ERRORS: Dict[int, str] = {
    1: "Letter format missing in G-code word",
    2: "Numeric value format is not valid",
    3: "Grbl '$' system command not recognized",
    4: "Negative value for expected positive value",
    5: "Homing cycle failure",
    6: "Minimum step pulse must be > 3usec",
    7: "EEPROM read failed",
    8: "Command not allowed unless Grbl is IDLE",
    9: "G-code locked out in Alarm or Jog state (click Unlock $X first)",
    10: "Soft limits cannot be enabled without homing",
    11: "Line characters exceeded buffer limit",
    12: "Step rate exceeded maximum supported",
    13: "Safety door opened",
    14: "Build info line exceeded EEPROM limit",
    15: "Jog target exceeds machine travel",
    16: "Jog command invalid format",
    17: "Laser mode requires PWM output",
    20: "Unsupported or invalid G-code command (buffer overflow or corrupted block)",
    21: "Multiple commands from same modal group in block",
    22: "Feed rate undefined or missing",
    23: "G-code command requires integer value",
    24: "More than two axis words found",
    25: "Repeated G-code word in block",
    26: "No axis words found for move",
    27: "Line number value not less than 50,000",
    28: "G-code command requires a P value",
    29: "Grbl supports coordinate systems G54-G59",
    30: "G53 invalid with current motion mode",
    31: "Axis words found without active motion mode",
    32: "Arc requires target pointer",
    33: "Motion command target is invalid",
    34: "Arc radius error",
    35: "Arc requires in-plane offset word",
    36: "Unused value words found in block",
    37: "Dynamic tool length offset error",
    38: "Tool number greater than max",
}

# Standard GRBL 1.1 Alarm Reference
GRBL_ALARMS: Dict[int, str] = {
    1: "Hard limit switch triggered (carriage hit limit switch or end of travel)",
    2: "Soft limit alarm (target motion exceeds machine travel bounds)",
    3: "Reset while in motion",
    4: "Probe fail: probe not in expected initial state",
    5: "Probe fail: probe did not contact workpiece within travel",
    6: "Homing fail: active homing cycle was reset",
    7: "Homing fail: safety door was opened during homing",
    8: "Homing fail: pull-off travel failed to clear limit switch",
    9: "Homing fail: limit switch search distance exceeded",
    10: "Homing fail: dual-axis switch not cleared",
}

# Standard GRBL 1.1 Firmware Parameter Descriptions
GRBL_SETTING_DESCRIPTIONS: Dict[str, Tuple[str, str, str]] = {
    "$0": ("Step pulse time", "microseconds", "Sets time length per step pulse (min 3us)"),
    "$1": ("Step idle delay", "milliseconds", "Time to keep stepper motors energized after move. 255 = keep locked"),
    "$2": ("Step pulse invert", "mask", "Inverts step pulse pin signal (active high/low)"),
    "$3": ("Direction invert", "mask", "Inverts motor direction: 1=X, 2=Y, 4=Z"),
    "$4": ("Step enable invert", "bool", "Inverts stepper driver enable pin"),
    "$5": ("Limit pins invert", "bool", "Inverts limit switch input pins (normally open vs closed)"),
    "$6": ("Probe pin invert", "bool", "Inverts probe pin input signal"),
    "$10": ("Status report options", "mask", "Controls GRBL status report fields (WPos vs MPos, buffer, pins)"),
    "$11": ("Junction deviation", "mm", "Cornering speed factor. Lower = slower through sharp corners"),
    "$12": ("Arc tolerance", "mm", "G2/G3 arc discretization precision"),
    "$13": ("Report inches", "bool", "0 = mm, 1 = inches"),
    "$20": ("Soft limits enable", "bool", "Prevents machine from exceeding travel bounds in G-code"),
    "$21": ("Hard limits enable", "bool", "Immediately halts machine if endstop switch is tripped"),
    "$22": ("Homing cycle enable", "bool", "Enables $H homing cycle to find mechanical limits"),
    "$23": ("Homing dir invert", "mask", "Homing direction invert mask (1=X, 2=Y, 4=Z)"),
    "$24": ("Homing feed", "mm/min", "Slow pull-off touch speed during homing"),
    "$25": ("Homing seek", "mm/min", "Initial fast search speed during homing"),
    "$26": ("Homing debounce", "milliseconds", "Switch debounce delay for noisy endstops"),
    "$27": ("Homing pull-off", "mm", "Distance moved off limit switch after trigger"),
    "$30": ("Max spindle speed / PWM ($30)", "RPM / PWM", "Maximum laser power S-value (e.g. 1000 for 100% duty cycle)"),
    "$31": ("Min spindle speed / PWM ($31)", "RPM / PWM", "Minimum laser power S-value (usually 0)"),
    "$32": ("Laser-mode enable ($32)", "bool", "1 = Diode/CO2 laser mode (dynamic M4 power scaling), 0 = Spindle"),
    "$100": ("X Steps/mm", "step/mm", "Number of stepper pulses to move X axis by 1.0 mm"),
    "$101": ("Y Steps/mm", "step/mm", "Number of stepper pulses to move Y axis by 1.0 mm"),
    "$102": ("Z Steps/mm", "step/mm", "Number of stepper pulses to move Z axis by 1.0 mm"),
    "$110": ("X Max rate", "mm/min", "Maximum rapid travel speed for X axis"),
    "$111": ("Y Max rate", "mm/min", "Maximum rapid travel speed for Y axis"),
    "$112": ("Z Max rate", "mm/min", "Maximum rapid travel speed for Z axis"),
    "$120": ("X Acceleration", "mm/sec^2", "Acceleration rate for X axis motion planner"),
    "$121": ("Y Acceleration", "mm/sec^2", "Acceleration rate for Y axis motion planner"),
    "$122": ("Z Acceleration", "mm/sec^2", "Acceleration rate for Z axis motion planner"),
    "$130": ("X Max travel", "mm", "Maximum travel distance of X axis before soft limit alarm"),
    "$131": ("Y Max travel", "mm", "Maximum travel distance of Y axis before soft limit alarm"),
    "$132": ("Z Max travel", "mm", "Maximum travel distance of Z axis before soft limit alarm"),
}


class VirtualGrblSerial:
    """
    In-memory virtual GRBL 1.1f controller for test-driving LaserForge without hardware.
    Simulates motion coordinates, status polling '<Idle|MPos:x,y,z|FS:0,0|Ov:100,100,100>',
    feed/power overrides, homing, alarms, and G-code execution.
    """
    def __init__(self, port: str = "VIRTUAL_GRBL", baudrate: int = 115200, timeout: float = 0.1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_open = True

        self._rx_buffer = bytearray()
        self._tx_buffer = bytearray()
        self._lock = threading.Lock()

        # Simulated machine state
        self.state = "Idle"
        self.mpos = [0.0, 0.0, 0.0]
        self.wpos = [0.0, 0.0, 0.0]
        self.wco = [0.0, 0.0, 0.0]
        self.feed_rate = 0.0
        self.laser_power = 0
        self.overrides = [100, 100, 100]  # Feed, Rapid, Power %

        # Startup banner
        self._enqueue(b"\r\nGrbl 1.1f ['$' for help]\r\n")

    def _enqueue(self, data: bytes):
        with self._lock:
            self._rx_buffer.extend(data)

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._rx_buffer)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            chunk = bytes(self._rx_buffer[:size])
            del self._rx_buffer[:size]
            return chunk

    def readline(self, size: int = -1) -> bytes:
        with self._lock:
            idx = self._rx_buffer.find(b"\n")
            if idx != -1:
                line = bytes(self._rx_buffer[:idx + 1])
                del self._rx_buffer[:idx + 1]
                return line
            else:
                line = bytes(self._rx_buffer)
                self._rx_buffer.clear()
                return line

    def reset_input_buffer(self):
        with self._lock:
            self._rx_buffer.clear()

    def reset_output_buffer(self):
        with self._lock:
            self._tx_buffer.clear()

    def write(self, data: bytes) -> int:
        for b in data:
            # Single-byte real-time commands
            if b == ord('?'):
                # Send status report
                status = (
                    f"<{self.state}|MPos:{self.mpos[0]:.3f},{self.mpos[1]:.3f},{self.mpos[2]:.3f}|"
                    f"WPos:{self.wpos[0]:.3f},{self.wpos[1]:.3f},{self.wpos[2]:.3f}|"
                    f"FS:{int(self.feed_rate)},{self.laser_power}|"
                    f"Ov:{self.overrides[0]},{self.overrides[1]},{self.overrides[2]}>\r\n"
                )
                self._enqueue(status.encode('latin1'))
            elif b == 0x18:  # Soft reset
                self.state = "Idle"
                self._enqueue(b"\r\nGrbl 1.1f ['$' for help]\r\nok\r\n")
            elif b == ord('!'):  # Feed hold
                self.state = "Hold"
            elif b == ord('~'):  # Cycle start / resume
                if self.state == "Hold":
                    self.state = "Idle"
            elif b == 0x90:  # Reset feed 100%
                self.overrides[0] = 100
            elif b == 0x91:  # Feed +10%
                self.overrides[0] = min(200, self.overrides[0] + 10)
            elif b == 0x92:  # Feed -10%
                self.overrides[0] = max(10, self.overrides[0] - 10)
            elif b == 0x93:  # Feed +1%
                self.overrides[0] = min(200, self.overrides[0] + 1)
            elif b == 0x94:  # Feed -1%
                self.overrides[0] = max(10, self.overrides[0] - 1)
            elif b == 0x95:  # Rapid 100%
                self.overrides[1] = 100
            elif b == 0x96:  # Rapid 50%
                self.overrides[1] = 50
            elif b == 0x97:  # Rapid 25%
                self.overrides[1] = 25
            elif b == 0x99:  # Reset power 100%
                self.overrides[2] = 100
            elif b == 0x9A:  # Power +10%
                self.overrides[2] = min(200, self.overrides[2] + 10)
            elif b == 0x9B:  # Power -10%
                self.overrides[2] = max(0, self.overrides[2] - 10)
            elif b == 0x9C:  # Power +1%
                self.overrides[2] = min(200, self.overrides[2] + 1)
            elif b == 0x9D:  # Power -1%
                self.overrides[2] = max(0, self.overrides[2] - 1)
            elif b == ord('\n') or b == ord('\r'):
                if self._tx_buffer:
                    line = self._tx_buffer.decode('latin1', errors='ignore').strip()
                    self._tx_buffer.clear()
                    if line:
                        self._process_command_line(line)
            else:
                self._tx_buffer.append(b)
        return len(data)

    def _process_command_line(self, line: str):
        if line == "$$":
            resp = [
                "$0=10", "$1=25", "$2=0", "$3=0", "$4=0", "$5=0", "$6=0",
                "$10=1", "$11=0.010", "$12=0.002", "$13=0",
                "$20=0", "$21=0", "$22=0", "$23=0", "$24=25.000", "$25=500.000",
                "$26=250", "$27=1.000", "$30=1000", "$31=0", "$32=1",
                "$100=80.000", "$101=80.000", "$102=250.000",
                "$110=6000.000", "$111=6000.000", "$112=1000.000",
                "$120=500.000", "$121=500.000", "$122=100.000",
                "$130=400.000", "$131=400.000", "$132=50.000",
                "ok\r\n"
            ]
            self._enqueue(("\r\n".join(resp)).encode('latin1'))
        elif line == "$I":
            self._enqueue(b"[VER:1.1f.20260917:LaserForge-Virtual]\r\n[OPT:V,15,128]\r\nok\r\n")
        elif line == "$G":
            self._enqueue(b"[GC:G0 G54 G17 G21 G90 G94 M5 M9 T0 F0 S0]\r\nok\r\n")
        elif line == "$H":
            self.mpos = [0.0, 0.0, 0.0]
            self.wpos = [0.0, 0.0, 0.0]
            self._enqueue(b"ok\r\n")
        elif line == "$X":
            self.state = "Idle"
            self._enqueue(b"[MSG:Caution: Unlocked]\r\nok\r\n")
        elif line.startswith("$"):
            self._enqueue(b"ok\r\n")
        else:
            if ";" in line:
                self._enqueue(b"error:2\r\n")
                return

            if "G38.2" in line.upper() or "G38.3" in line.upper():
                # Simulate probe contact
                probe_z = -15.0
                parts = line.upper().split()
                for p in parts:
                    if p.startswith("Z"):
                        try:
                            probe_z = float(p[1:]) / 2.0  # simulate contact midway
                        except ValueError:
                            pass
                self.mpos[2] = probe_z
                self.wpos[2] = probe_z
                self._enqueue(f"[PRB:{self.mpos[0]:.3f},{self.mpos[1]:.3f},{probe_z:.3f}:1]\r\nok\r\n".encode('latin1'))
                return

            # Parse G-code motion
            parts = line.upper().split()
            for p in parts:
                if not p:
                    continue
                letter = p[0]
                val_str = p[1:]
                if letter in ("X", "Y", "Z", "F", "S", "G", "M", "P", "L", "I", "J", "K", "R"):
                    if not val_str:
                        self._enqueue(b"error:2\r\n")
                        return
                    try:
                        num = float(val_str)
                    except ValueError:
                        self._enqueue(b"error:2\r\n")
                        return
                    if letter == "X":
                        self.mpos[0] = num
                        self.wpos[0] = num
                    elif letter == "Y":
                        self.mpos[1] = num
                        self.wpos[1] = num
                    elif letter == "Z":
                        self.mpos[2] = num
                        self.wpos[2] = num
                    elif letter == "F":
                        self.feed_rate = num
                    elif letter == "S":
                        self.laser_power = int(num)
                else:
                    self._enqueue(b"error:2\r\n")
                    return
            self._enqueue(b"ok\r\n")

    def flush(self):
        pass

    def close(self):
        self.is_open = False


class NetworkSocketSerial:
    """
    TCP Socket Serial emulator for LaserForge.
    Enables connecting to wireless G-code bridges (such as PiBridge or esp3d) over network sockets.
    Provides a drop-in pySerial-compatible interface: write, read, in_waiting, reset_input_buffer, close.
    """
    def __init__(self, host: str, port: int = 8088, timeout: float = 1.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.is_open = False
        self._sock: Optional[socket.socket] = None
        self._rx_buffer = bytearray()
        self._lock = threading.Lock()
        self.open()

    def open(self):
        with self._lock:
            self.close()
            target_host = self.host
            target_port = self.port
            if target_host.endswith(".local"):
                try:
                    target_host = socket.gethostbyname(target_host)
                except Exception:
                    try:
                        from laserforge.core.auto_connect import discover_pibridge_service
                        disc = discover_pibridge_service()
                        if disc:
                            target_host, target_port = disc
                    except Exception:
                        pass
                if target_host.endswith(".local"):
                    try:
                        test_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        test_s.settimeout(0.5)
                        test_s.connect(("10.0.11.212", target_port))
                        test_s.close()
                        target_host = "10.0.11.212"
                    except Exception:
                        pass

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(max(3.0, self.timeout))
            s.connect((target_host, target_port))
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 5)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            except (AttributeError, OSError):
                pass
            s.setblocking(False)
            self._sock = s
            self.is_open = True
            self._rx_buffer.clear()

    def write(self, data: bytes) -> int:
        if not self.is_open or self._sock is None:
            raise serial.SerialException("Network socket not connected")
        with self._lock:
            total_sent = 0
            data_len = len(data)
            deadline = time.time() + max(5.0, self.timeout)
            while total_sent < data_len:
                try:
                    sent = self._sock.send(data[total_sent:])
                    if sent == 0:
                        self.is_open = False
                        raise serial.SerialException("Network socket connection broken")
                    total_sent += sent
                except (BlockingIOError, socket.timeout):
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise serial.SerialException("Network socket write timed out")
                    _, w, _ = select.select([], [self._sock], [], min(0.2, remaining))
                    if not w and time.time() >= deadline:
                        raise serial.SerialException("Network socket write timed out")
                except socket.error as e:
                    self.is_open = False
                    raise serial.SerialException(f"Network write error: {e}")
            return total_sent

    def _poll(self):
        if not self.is_open or self._sock is None:
            return
        try:
            r, _, _ = select.select([self._sock], [], [], 0.0)
            if self._sock in r:
                chunk = self._sock.recv(4096)
                if not chunk:
                    self.is_open = False
                    return
                self._rx_buffer.extend(chunk)
        except (BlockingIOError, socket.timeout):
            pass
        except socket.error as e:
            self.is_open = False
            if not self._rx_buffer:
                raise serial.SerialException(f"Network socket error: {e}")

    @property
    def in_waiting(self) -> int:
        with self._lock:
            self._poll()
            return len(self._rx_buffer)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            self._poll()
            if not self._rx_buffer:
                if not self.is_open:
                    raise serial.SerialException("Connection closed by remote laser bridge")
                return b""
            chunk = bytes(self._rx_buffer[:size])
            del self._rx_buffer[:size]
            return chunk

    def reset_input_buffer(self):
        with self._lock:
            self._rx_buffer.clear()

    def reset_output_buffer(self):
        pass

    def flush(self):
        pass

    def close(self):
        self.is_open = False
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


class SerialController(QObject):
    # Signals for UI updates
    connected = pyqtSignal(str)          # Port name
    disconnected = pyqtSignal()
    connection_failed = pyqtSignal(str)  # Error message
    status_updated = pyqtSignal(dict)    # Status dict: state, mpos, wpos, pins
    log_received = pyqtSignal(str, str)  # (direction: "tx"|"rx"|"err", text)
    job_progress = pyqtSignal(float, int, int) # (pct 0..100, cur_line, total_lines)
    job_finished = pyqtSignal(bool, str) # (success, message)
    machine_parameters_loaded = pyqtSignal(dict) # {"bed_width": float, "bed_height": float, ...}
    grbl_setting_received = pyqtSignal(str, str) # ($key, val)
    grbl_settings_updated = pyqtSignal(dict)     # Full {key: val} dictionary

    # Automated Connection Signals
    auto_connect_started = pyqtSignal()
    auto_connect_progress = pyqtSignal(str)
    auto_connect_finished = pyqtSignal(bool, str)
    ports_changed = pyqtSignal(list)     # List of RankedPort

    sanitize_gcode_line = staticmethod(sanitize_gcode_line)

    def __init__(self):
        super().__init__()
        self.serial_port: Optional[serial.Serial] = None
        self.is_connected = False
        self.port_name = ""
        self.baud_rate = 115200

        # State tracking
        self.machine_state = "Disconnected"
        self.mpos = [0.0, 0.0, 0.0]
        self.wpos = [0.0, 0.0, 0.0]
        self.wco = [0.0, 0.0, 0.0]
        self.active_pins = ""
        self.feed_override_pct = 100
        self.rapid_override_pct = 100
        self.power_override_pct = 100
        self.grbl_settings: Dict[str, str] = {}
        self.machine_limits: Dict[str, Any] = {
            "bed_width": 400.0,
            "bed_height": 400.0,
            "max_s_value": 1000,
            "min_s_value": 0,
            "laser_mode": "M4",
            "hard_limits": False,
            "soft_limits": False,
            "homing_enabled": False,
            "x_steps_per_mm": 80.0,
            "y_steps_per_mm": 80.0,
            "z_steps_per_mm": 250.0,
            "x_max_rate": 5000.0,
            "y_max_rate": 5000.0,
            "x_accel": 500.0,
            "y_accel": 500.0,
            "invert_x_dir": False,
            "invert_y_dir": False,
            "invert_z_dir": False
        }

        # Streaming state
        self.is_streaming = False
        self.is_paused = False
        self.abort_requested = False
        self.gcode_lines: List[str] = []
        self.current_line_idx = 0
        self.last_job_gcode: str = ""
        self.last_job_lines: List[str] = []
        self.last_stopped_line_idx: int = 0
        self.streaming_mode: str = "auto"  # "auto", "line_by_line", "character_counting"

        # Automated connection & hotplug worker
        self.auto_connect_worker: Optional[AutoConnectWorker] = None
        self.hotplug_watcher: Optional[USBHotplugWatcher] = None
        self.auto_reconnect_enabled = True

        # Background worker thread & FIFO response queue
        self.worker_thread: Optional[threading.Thread] = None
        self.stream_thread: Optional[threading.Thread] = None
        self.stop_worker = False
        self.lock = threading.Lock()
        self.ack_queue: queue.Queue = queue.Queue()

    @property
    def is_network_connection(self) -> bool:
        """Returns True if currently connected over a TCP network socket bridge."""
        if isinstance(self.serial_port, NetworkSocketSerial):
            return True
        if self.port_name and (self.port_name.startswith("tcp://") or (":" in self.port_name and not self.port_name.startswith("/dev/"))):
            return True
        return False

    @property
    def current_wpos(self) -> List[float]:
        """Returns copy of current work position coordinates [X, Y, Z]."""
        return list(self.wpos)

    @property
    def current_mpos(self) -> List[float]:
        """Returns copy of current machine position coordinates [X, Y, Z]."""
        return list(self.mpos)

    @property
    def is_alarm(self) -> bool:
        """Returns True if the machine state is currently in ALARM."""
        return "alarm" in str(self.machine_state).lower()

    @staticmethod
    def list_available_ports(include_dummy_tty: bool = False) -> List[str]:
        """Returns sorted list of connected serial port devices with laser candidates first."""
        ports = PortDetector.get_ranked_ports(include_dummy_tty=include_dummy_tty)
        if not ports and not include_dummy_tty:
            ports = PortDetector.get_ranked_ports(include_dummy_tty=True)
        return [p.device for p in ports]

    @staticmethod
    def get_ranked_ports(include_dummy_tty: bool = False) -> List[RankedPort]:
        """Returns ranked list of serial ports with metadata and device descriptions."""
        ports = PortDetector.get_ranked_ports(include_dummy_tty=include_dummy_tty)
        if not ports and not include_dummy_tty:
            ports = PortDetector.get_ranked_ports(include_dummy_tty=True)
        return ports

    def start_auto_connect(self, preferred_port: Optional[str] = None):
        """Launches background probe to locate and connect to GRBL laser engraver."""
        if self.is_connected:
            self.disconnect()

        if self.auto_connect_worker and self.auto_connect_worker.isRunning():
            self.auto_connect_worker.abort()
            self.auto_connect_worker.wait(timeout=1000)

        target_pref = preferred_port or self.port_name
        if target_pref and target_pref.upper().startswith("VIRTUAL"):
            target_pref = None
        self.auto_connect_worker = AutoConnectWorker(preferred_port=target_pref, parent=self)
        self.auto_connect_worker.probe_started.connect(self.auto_connect_started.emit)
        self.auto_connect_worker.probe_progress.connect(self.auto_connect_progress.emit)
        self.auto_connect_worker.laser_found.connect(self._on_auto_laser_found)
        self.auto_connect_worker.probe_finished.connect(self._on_auto_probe_finished)
        self.auto_connect_worker.start()

    def stop_auto_connect(self):
        """Cancels any in-flight auto-connect scan."""
        if self.auto_connect_worker and self.auto_connect_worker.isRunning():
            self.auto_connect_worker.abort()
            self.auto_connect_worker.wait(timeout=500)

    def _on_auto_laser_found(self, port: str, baud: int, summary: str):
        self.log_received.emit("rx", f"Auto-detected GRBL laser on {port} ({summary})")
        self.connect(port, baud)

    def _on_auto_probe_finished(self, success: bool, msg: str):
        self.auto_connect_finished.emit(success, msg)

    def enable_hotplug_watcher(self, enabled: bool = True):
        """Starts or stops the background USB device plug-in watcher."""
        if enabled:
            if not self.hotplug_watcher:
                self.hotplug_watcher = USBHotplugWatcher(check_interval_ms=1500, parent=self)
                self.hotplug_watcher.ports_changed.connect(self.ports_changed.emit)
                self.hotplug_watcher.device_inserted.connect(self._on_usb_device_inserted)
                self.hotplug_watcher.start()
        else:
            if self.hotplug_watcher:
                self.hotplug_watcher.stop()
                self.hotplug_watcher = None

    def _on_usb_device_inserted(self, device_path: str):
        """Fires when a new USB serial device is plugged into the system."""
        self.log_received.emit("rx", f"USB serial device detected: {device_path}")
        if not self.is_connected and self.auto_reconnect_enabled:
            self.start_auto_connect(preferred_port=device_path)

    @staticmethod
    def parse_network_target(port: str) -> Optional[Tuple[str, int]]:
        """
        Parses a network connection string (e.g. 'tcp://192.168.1.50:8088',
        'laserbridge.local:8088', 'socket://10.0.0.5:8088', '192.168.1.50:8088') into (host, port).
        Returns None if port is a standard serial device (/dev/ttyUSB0, COM3, etc.).
        """
        if not port or port.upper().startswith("VIRTUAL"):
            return None
        p = port.strip()
        for prefix in ("tcp://", "socket://", "net://"):
            if p.lower().startswith(prefix):
                p = p[len(prefix):]
                break
        else:
            if p.startswith("/dev/"):
                return None
            if not (":" in p or p.endswith(".local")):
                return None

        p = p.split("/")[0]

        if ":" in p:
            host_part, port_part = p.split(":", 1)
            try:
                port_num = int(port_part)
                return host_part.strip(), port_num
            except ValueError:
                return None
        elif p.endswith(".local") or re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", p):
            return p.strip(), 8088

        return None

    def connect(self, port: str, baud: int = 115200) -> bool:
        """Opens connection to the laser engraver (USB Serial or Network TCP bridge)."""
        if self.is_connected:
            self.disconnect()

        try:
            net_target = self.parse_network_target(port)
            if net_target:
                host, net_port = net_target
                self.log_received.emit("rx", f"Connecting to network laser bridge at {host}:{net_port}...")
                self.serial_port = NetworkSocketSerial(host=host, port=net_port, timeout=2.0)
                time.sleep(0.2)
            elif port.upper() in ("VIRTUAL_GRBL", "VIRTUAL", "SIMULATOR"):
                self.serial_port = VirtualGrblSerial(port=port, baudrate=baud)
                time.sleep(0.1)
            else:
                self.serial_port = serial.Serial(port, baud, timeout=0.1)
                time.sleep(1.0)  # Wait for GRBL boot reset
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()

            self.is_connected = True
            self.port_name = port
            self.baud_rate = baud

            # Wake up GRBL with clean newlines and check status
            self.serial_port.write(b"\n\n")
            time.sleep(0.1 if port.upper().startswith("VIRTUAL") else 0.2)

            # Start background reader and poller thread
            self.stop_worker = False
            self.worker_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.worker_thread.start()

            # Query controller settings ($$) and build info ($I) asynchronously
            time.sleep(0.1)
            self.send_command("$$")
            self.send_command("$I")

            self.connected.emit(port)
            self.log_received.emit("rx", f"Connected to {port} at {baud} baud.")
            return True
        except Exception as e:
            self.is_connected = False
            self.connection_failed.emit(str(e))
            self.log_received.emit("err", f"Connection failed on {port}: {e}")
            return False

    def disconnect(self):
        """Safely disconnects from the laser."""
        was_connected = self.is_connected
        self.stop_worker = True
        self.stop_streaming()

        if self.worker_thread and self.worker_thread.is_alive():
            try:
                self.worker_thread.join(timeout=1.0)
            except Exception:
                pass

        with self.lock:
            if self.serial_port and self.serial_port.is_open:
                try:
                    self.serial_port.write(b"M5\n") # Ensure laser is OFF
                    self.serial_port.close()
                except Exception:
                    pass
            self.serial_port = None
            self.is_connected = False
            self.machine_state = "Disconnected"

        if was_connected:
            try:
                self.disconnected.emit()
                self.log_received.emit("rx", "Disconnected from machine.")
            except RuntimeError:
                pass

    def send_command(self, cmd: str):
        """Sends a raw command or G-code line to GRBL using standard \n terminator."""
        if not self.is_connected or not self.serial_port:
            self.log_received.emit("err", "Cannot send command: Not connected.")
            return

        clean_cmd = sanitize_gcode_line(cmd)
        if not clean_cmd:
            return

        with self.lock:
            try:
                self.serial_port.write((clean_cmd + "\n").encode("latin1"))
                self.log_received.emit("tx", clean_cmd)
            except Exception as e:
                self.log_received.emit("err", f"Send error: {e}")

    def send_realtime(self, byte: int):
        """Sends a single real-time GRBL command byte (!, ~, ?, 0x18, etc.).
        These are special single-byte commands that MUST NOT have a \\n terminator —
        GRBL processes them immediately outside the normal line-based command queue.
        """
        if not self.is_connected or not self.serial_port:
            return
        with self.lock:
            try:
                self.serial_port.write(bytes([byte]))
                self.log_received.emit("tx", f"<RT:0x{byte:02X}>")
            except Exception as e:
                self.log_received.emit("err", f"Realtime send error: {e}")

    def jog(self, dx: float, dy: float, dz: float, feed: float):
        """Executes a safe GRBL jog command."""
        if not self.is_connected:
            return
        parts = []
        if dx != 0: parts.append(f"X{dx:.3f}")
        if dy != 0: parts.append(f"Y{dy:.3f}")
        if dz != 0: parts.append(f"Z{dz:.3f}")
        if not parts: return

        # GRBL jog command format: $J=G91 G21 X... Y... F...
        jog_cmd = f"$J=G91 G21 {' '.join(parts)} F{feed:.0f}"
        self.send_command(jog_cmd)

    def home(self):
        """Homing cycle command ($H)."""
        self.send_command("$H")

    def unlock(self):
        """Kill alarm lock ($X)."""
        self.send_command("$X")

    def _send_realtime_byte(self, byte_val: bytes, desc: str = ""):
        """Sends a single-byte real-time GRBL command bypassing buffer queues."""
        if self.is_connected and self.serial_port:
            with self.lock:
                try:
                    self.serial_port.write(byte_val)
                    if desc:
                        self.log_received.emit("tx", f"<Realtime Override: {desc}>")
                except Exception as e:
                    self.log_received.emit("err", f"Override send error: {e}")

    def set_feed_override(self, code: str):
        """
        Sends GRBL 1.1 real-time feed override byte:
        code: '+10', '-10', '+1', '-1', '100'
        """
        mapping = {
            "100": (b"\x90", "Feed 100% Reset"),
            "+10": (b"\x91", "Feed +10%"),
            "-10": (b"\x92", "Feed -10%"),
            "+1":  (b"\x93", "Feed +1%"),
            "-1":  (b"\x94", "Feed -1%"),
        }
        entry = mapping.get(str(code))
        if entry:
            self._send_realtime_byte(entry[0], entry[1])

    def set_power_override(self, code: str):
        """
        Sends GRBL 1.1 real-time laser power override byte:
        code: '+10', '-10', '+1', '-1', '100'
        """
        mapping = {
            "100": (b"\x99", "Laser Power 100% Reset"),
            "+10": (b"\x9A", "Laser Power +10%"),
            "-10": (b"\x9B", "Laser Power -10%"),
            "+1":  (b"\x9C", "Laser Power +1%"),
            "-1":  (b"\x9D", "Laser Power -1%"),
        }
        entry = mapping.get(str(code))
        if entry:
            self._send_realtime_byte(entry[0], entry[1])

    def set_rapid_override(self, code: str):
        """
        Sends GRBL 1.1 real-time rapid travel override byte:
        code: '100', '50', '25'
        """
        mapping = {
            "100": (b"\x95", "Rapid 100%"),
            "50":  (b"\x96", "Rapid 50%"),
            "25":  (b"\x97", "Rapid 25%"),
        }
        entry = mapping.get(str(code))
        if entry:
            self._send_realtime_byte(entry[0], entry[1])

    def set_zero(self, x: bool = True, y: bool = True, z: bool = True):
        """Sets current position as work zero (WPos = 0)."""
        cmd_parts = []
        if x: cmd_parts.append("X0")
        if y: cmd_parts.append("Y0")
        if z: cmd_parts.append("Z0")
        if cmd_parts:
            self.send_command(f"G10 L20 P1 {' '.join(cmd_parts)}")

    def go_to_zero(self, rapid_speed: float = 3000.0):
        """Moves laser head to work origin (0, 0). Protected against mid-job motor injection."""
        if self.is_streaming:
            self.log_received.emit("err", "Cannot go to zero while a job is currently streaming.")
            return
        self.send_command(f"G0 X0 Y0 F{rapid_speed:.0f}")

    def go_to_pos(self, x: float, y: float, rapid_speed: float = 3000.0):
        """Moves laser head to specified work coordinates (G90 G0 X... Y...). Protected against mid-job motor injection."""
        if self.is_streaming:
            self.log_received.emit("err", "Cannot go to position while a job is currently streaming.")
            return
        self.send_command(f"G90 G0 X{x:.3f} Y{y:.3f} F{rapid_speed:.0f}")

    def probe_z(self, max_travel_mm: float = 40.0, feed: float = 50.0, plate_thickness_mm: float = 0.0):
        """
        Executes a straight Z-probe autofocus cycle (GRBL G38.2).
        Moves downward until touch-plate contact, zeroes Z, and retracts safely.
        """
        if self.is_streaming:
            self.log_received.emit("err", "Cannot run Z-probe while a job is streaming.")
            return
        if not self.is_connected:
            self.log_received.emit("err", "Cannot probe: Laser is not connected.")
            return

        self.log_received.emit("info", f"Starting Z-probe cycle (max {max_travel_mm}mm @ {feed}mm/min)...")
        # 1. Switch to relative coordinates and probe downwards
        self.send_command(f"G91 G38.2 Z-{abs(max_travel_mm):.2f} F{feed:.0f}")
        # 2. Set Z coordinate accounting for touch plate thickness
        self.send_command(f"G10 L20 P1 Z{plate_thickness_mm:.3f}")
        # 3. Retract 3mm safely above contact point
        self.send_command("G91 G0 Z3.0 F500")
        # 4. Return to absolute positioning mode
        self.send_command("G90")
        self.log_received.emit("info", "Z-probe cycle completed. Focal surface calibrated.")

    def toggle_test_laser(self, on: bool, power_s: int = 5):
        """Toggles low-power framing laser beam for focusing / alignment."""
        if on:
            # In GRBL Laser Mode ($32=1), stationary laser firing requires G1 modal state
            self.send_command(f"M3 G1 S{power_s} F1")
        else:
            self.send_command("M5 S0")
            self.send_command("G0")

    def pulse_laser(self, power_pct: float = 1.0, duration_ms: int = 100):
        """Test fires the laser beam for a precise duration in milliseconds."""
        max_s = self.machine_limits.get("max_s_value", 1000)
        s_val = max(1, int(round((power_pct / 100.0) * max_s)))
        dwell_sec = max(0.01, duration_ms / 1000.0)

        if not self.is_connected:
            self.log_received.emit("err", "Cannot pulse laser: Laser is not connected.")
            return

        def _run_pulse():
            try:
                # 1. In GRBL Laser Mode ($32=1), stationary laser emission requires active G1 modal state
                self.send_command(f"M3 G1 S{s_val} F1")
                self.log_received.emit("tx", f"Laser Pulse ON: M3 G1 S{s_val} ({power_pct:.1f}%, {duration_ms}ms)")
                # 2. Wait for pulse duration
                time.sleep(dwell_sec)
                # 3. Safely extinguish beam and restore rapid G0 modal state
                self.send_command("M5 S0")
                self.send_command("G0")
                self.log_received.emit("tx", "Laser Pulse OFF: M5 S0 (G0 restored)")
            except Exception as e:
                self.log_received.emit("err", f"Pulse laser error: {e}")
                try:
                    self.send_command("M5 S0")
                    self.send_command("G0")
                except Exception:
                    pass

        threading.Thread(target=_run_pulse, daemon=True).start()

    def go_to_park(self, park_x: float = 0.0, park_y: float = 0.0, rapid_speed: float = 3000.0):
        """Moves laser head to park position."""
        self.send_command(f"G0 X{park_x:.3f} Y{park_y:.3f} F{rapid_speed:.0f}")

    def query_grbl_settings(self):
        """Requests $$ configuration from connected GRBL controller."""
        self.send_command("$$")

    def set_grbl_setting(self, setting_num: Any, val: Any):
        """Writes an individual $ parameter to GRBL EEPROM."""
        s_str = str(setting_num).strip()
        if not s_str.startswith("$"):
            s_str = f"${s_str}"
        self.send_command(f"{s_str}={val}")

    def start_job(self, gcode_text: str):
        """Begins streaming the G-code program to the laser."""
        if not self.is_connected:
            self.log_received.emit("err", "Cannot start job: Laser is not connected.")
            return

        lines = []
        for raw_line in gcode_text.splitlines():
            clean = sanitize_gcode_line(raw_line)
            if clean:
                lines.append(clean)
        if not lines:
            self.log_received.emit("err", "Job is empty or contains only comments.")
            return

        self.last_job_gcode = gcode_text
        self.last_job_lines = list(lines)
        self.last_stopped_line_idx = 0

        self.gcode_lines = lines
        self.current_line_idx = 0
        self.is_streaming = True
        self.is_paused = False
        self.abort_requested = False

        # Launch streaming thread
        self.stream_thread = threading.Thread(target=self._streaming_loop, daemon=True)
        self.stream_thread.start()

    def resume_job_from_position(
        self,
        gcode_text: Optional[str] = None,
        line_idx: Optional[int] = None,
        percentage: Optional[float] = None,
        by_distance: bool = False
    ) -> bool:
        """
        Resumes a job from a specific line index or progress percentage.
        Synthesizes the safe resumption preamble and starts the stream.
        """
        from laserforge.core.job_resumer import JobResumer

        target_gcode = gcode_text or self.last_job_gcode
        if not target_gcode:
            self.log_received.emit("err", "Cannot resume: No previous job G-code found.")
            return False

        try:
            resumed = JobResumer.build_resumed_job(
                target_gcode,
                target_line_idx=line_idx,
                target_percentage=percentage,
                by_distance=by_distance
            )
            self.log_received.emit(
                "rx",
                f"Resuming job at line {resumed.resume_line_index} of {resumed.original_line_count} ({resumed.resume_percentage:.1f}%)..."
            )
            self.start_job(resumed.full_gcode)
            return True
        except Exception as e:
            self.log_received.emit("err", f"Job resumption failed: {e}")
            return False

    def pause_job(self):
        """Pauses job execution."""
        if self.is_streaming and not self.is_paused:
            self.is_paused = True
            with self.lock:
                if self.serial_port:
                    self.serial_port.write(b"!") # Feed hold
            self.log_received.emit("tx", "! (Feed Hold / Pause)")

    def resume_job(self):
        """Resumes paused job."""
        if self.is_streaming and self.is_paused:
            self.is_paused = False
            with self.lock:
                if self.serial_port:
                    self.serial_port.write(b"~") # Cycle start
            self.log_received.emit("tx", "~ (Cycle Start / Resume)")

    def stop_streaming(self):
        """Aborts active streaming job immediately."""
        self.abort_requested = True
        self.is_streaming = False
        self.is_paused = False
        self.ack_queue.put(("abort", "Aborted by user"))
        if self.stream_thread and self.stream_thread.is_alive() and threading.current_thread() != self.stream_thread:
            try:
                self.stream_thread.join(timeout=1.0)
            except Exception:
                pass
        if self.is_connected and self.serial_port:
            with self.lock:
                try:
                    self.serial_port.write(b"M5\n\x18") # Turn off laser + soft reset
                except Exception:
                    pass
            time.sleep(0.1)
            self.unlock()

    def _streaming_loop(self):
        """
        G-code streaming engine for GRBL.
        Uses strict line-by-line ACK flow control over network bridges,
        and high-speed character-counting buffers over direct USB.
        """
        try:
            self._do_streaming_loop()
        except RuntimeError:
            return

    def _do_streaming_loop(self):
        total = len(self.gcode_lines)
        use_line_by_line = (
            self.streaming_mode == "line_by_line" or
            (self.streaming_mode == "auto" and self.is_network_connection)
        )
        stream_mode_label = "Line-by-Line ACK (Network Safe)" if use_line_by_line else "Buffered (High-Speed USB)"
        self.log_received.emit("rx", f"Starting G-Code stream ({total} lines) [{stream_mode_label}]...")

        # Drain residual tokens from ack_queue before starting
        while not self.ack_queue.empty():
            try:
                self.ack_queue.get_nowait()
            except queue.Empty:
                break

        if use_line_by_line:
            # === STRICT LINE-BY-LINE PING-PONG FLOW CONTROL ===
            # Transmits 1 line at a time and waits for GRBL's 'ok' ACK.
            # Prevents Wi-Fi/TCP buffer overruns, dropped characters, and error:1 / error:23.
            idx = 0
            while idx < total:
                if self.abort_requested:
                    self.log_received.emit("err", "Job Aborted by user.")
                    self.job_finished.emit(False, "Aborted by user")
                    return

                while self.is_paused:
                    time.sleep(0.1)
                    if self.abort_requested:
                        self.job_finished.emit(False, "Aborted while paused")
                        return

                next_line = self.gcode_lines[idx]
                with self.lock:
                    if not self.serial_port or not self.serial_port.is_open:
                        self.job_finished.emit(False, "Connection lost during network stream")
                        self.is_streaming = False
                        return
                    try:
                        self.serial_port.write((next_line + "\n").encode("latin1"))
                        if not self.is_streaming or next_line.startswith(";") or not next_line.startswith("G1") or idx % 50 == 0:
                            self.log_received.emit("tx", next_line)
                    except Exception as e:
                        self.job_finished.emit(False, f"Network transmission error: {e}")
                        self.is_streaming = False
                        return

                # Wait synchronously for this line's ACK before transmitting next line
                ack_received = False
                send_time = time.time()
                while not ack_received and not self.abort_requested:
                    try:
                        token_type, token_val = self.ack_queue.get(timeout=0.20)
                        if token_type == "ok":
                            ack_received = True
                            self.current_line_idx = idx + 1
                            self.last_stopped_line_idx = self.current_line_idx
                            pct = (self.current_line_idx / total) * 100.0 if total > 0 else 100.0
                            self.job_progress.emit(pct, self.current_line_idx, total)
                            idx += 1
                        elif token_type in ("error", "alarm"):
                            err_msg = f"Laser controller {token_type}: {token_val} (at line {idx+1}: {next_line})"
                            self.log_received.emit("err", err_msg)
                            self.job_finished.emit(False, err_msg)
                            self.is_streaming = False
                            return
                        elif token_type == "abort":
                            self.job_finished.emit(False, "Aborted by user")
                            self.is_streaming = False
                            return
                    except queue.Empty:
                        now = time.time()
                        if self.machine_state in ("Run", "Jog", "Hold"):
                            send_time = now
                            continue
                        if now - getattr(self, "last_rx_time", now) > 60.0:
                            err_msg = f"Controller response timed out after 60s (at line {idx+1}: {next_line})"
                            self.log_received.emit("err", err_msg)
                            self.job_finished.emit(False, err_msg)
                            self.is_streaming = False
                            return

            self.is_streaming = False
            self.log_received.emit("rx", "Job Completed Successfully!")
            self.job_finished.emit(True, "Job Completed Successfully")
            return

        # === HIGH-SPEED CHARACTER-COUNTING BUFFERED STREAM (USB DIRECT) ===
        in_flight: List[int] = []  # Length of lines in flight (bytes including \n)
        max_buffer_bytes = 120    # Safe threshold for GRBL's 128-byte RX buffer
        idx = 0

        while idx < total or in_flight:
            if self.abort_requested:
                self.log_received.emit("err", "Job Aborted by user.")
                self.job_finished.emit(False, "Aborted by user")
                return

            while self.is_paused:
                time.sleep(0.1)
                if self.abort_requested:
                    self.job_finished.emit(False, "Aborted while paused")
                    return

            # Check if we can send another line into GRBL's RX buffer
            can_send = False
            if idx < total:
                next_line = self.gcode_lines[idx]
                line_bytes = len(next_line) + 1  # include \n
                if sum(in_flight) + line_bytes <= max_buffer_bytes:
                    can_send = True

            if can_send:
                with self.lock:
                    if not self.serial_port or not self.serial_port.is_open:
                        self.job_finished.emit(False, "Serial port disconnected during stream")
                        self.is_streaming = False
                        return
                    try:
                        self.serial_port.write((next_line + "\n").encode("latin1"))
                        if not self.is_streaming or next_line.startswith(";") or not next_line.startswith("G1") or idx % 50 == 0:
                            self.log_received.emit("tx", next_line)
                        in_flight.append(line_bytes)
                        idx += 1
                    except Exception as e:
                        self.job_finished.emit(False, f"Serial write failed: {e}")
                        self.is_streaming = False
                        return
            else:
                # Buffer is full or all lines dispatched: wait for ACK
                try:
                    token_type, token_val = self.ack_queue.get(timeout=0.20)
                    if token_type == "ok":
                        if in_flight:
                            in_flight.pop(0)
                        self.current_line_idx = min(total, idx - len(in_flight))
                        self.last_stopped_line_idx = self.current_line_idx
                        pct = (self.current_line_idx / total) * 100.0 if total > 0 else 100.0
                        self.job_progress.emit(pct, self.current_line_idx, total)
                    elif token_type in ("error", "alarm"):
                        err_msg = f"Laser controller {token_type}: {token_val} (near line {idx})"
                        self.log_received.emit("err", err_msg)
                        self.job_finished.emit(False, err_msg)
                        self.is_streaming = False
                        return
                    elif token_type == "abort":
                        self.job_finished.emit(False, "Aborted by user")
                        self.is_streaming = False
                        return
                except queue.Empty:
                    now = time.time()
                    if self.machine_state in ("Run", "Jog", "Hold"):
                        continue
                    if now - getattr(self, "last_rx_time", now) > 60.0:
                        err_msg = f"Controller response timed out after 60s (near line {idx})"
                        self.log_received.emit("err", err_msg)
                        self.job_finished.emit(False, err_msg)
                        self.is_streaming = False
                        return

        self.is_streaming = False
        self.log_received.emit("rx", "Job Completed Successfully!")
        self.job_finished.emit(True, "Job Completed Successfully")

    def _send_and_wait_ack(self, line: str, max_idle_timeout: float = 60.0) -> Tuple[bool, str]:
        """
        Sends a single line and synchronously waits for GRBL 'ok' or error response.
        Used for discrete calibration and manual control moves.
        """
        clean_line = sanitize_gcode_line(line)
        if not clean_line:
            return True, ""

        # Drain residual tokens before sending
        while not self.ack_queue.empty():
            try:
                self.ack_queue.get_nowait()
            except queue.Empty:
                break

        with self.lock:
            if not self.serial_port or not self.serial_port.is_open:
                return False, "Serial port not connected"
            try:
                self.serial_port.write((clean_line + "\n").encode("latin1"))
                self.log_received.emit("tx", clean_line)
            except Exception as e:
                return False, f"Write error: {e}"

        send_time = time.time()
        last_progress_time = send_time

        while not self.abort_requested:
            try:
                token_type, token_val = self.ack_queue.get(timeout=0.20)
                if token_type == "ok":
                    return True, ""
                elif token_type in ("error", "alarm"):
                    return False, token_val
                elif token_type == "abort":
                    return False, "Aborted by user"
            except queue.Empty:
                pass

            now = time.time()
            if self.machine_state in ("Run", "Jog", "Hold"):
                last_progress_time = now
                continue

            if now - last_progress_time > max_idle_timeout:
                return False, f"Controller response timed out after {max_idle_timeout:.0f}s"

        return False, "Job aborted by user"

    def _reader_loop(self):
        """Continuously reads incoming data from serial port and polls status."""
        last_poll_time = 0.0
        line_buffer = ""
        self.last_rx_time = time.time()

        while not self.stop_worker and self.is_connected:
            now = time.time()
            # Poll status every 250ms when idle or running
            if now - last_poll_time >= 0.25:
                last_poll_time = now
                with self.lock:
                    if self.serial_port and self.serial_port.is_open:
                        try:
                            self.serial_port.write(b"?")
                        except Exception:
                            pass

            # Read available bytes
            raw_data = b""
            with self.lock:
                if self.serial_port and self.serial_port.is_open:
                    try:
                        n = self.serial_port.in_waiting
                        if n > 0:
                            raw_data = self.serial_port.read(n)
                    except Exception:
                        break

            if raw_data:
                self.last_rx_time = time.time()
                text = raw_data.decode("latin1", errors="ignore")
                line_buffer += text

                while "\n" in line_buffer:
                    line, line_buffer = line_buffer.split("\n", 1)
                    clean_line = line.strip("\r ")
                    if clean_line:
                        self._handle_incoming_line(clean_line)

            if raw_data:
                time.sleep(0.001)
            else:
                time.sleep(0.005)

        # Handle unexpected serial port drop (e.g. USB cable unplugged or laser powered down)
        if not self.stop_worker and self.is_connected:
            with self.lock:
                if self.serial_port:
                    try: self.serial_port.close()
                    except Exception: pass
                self.serial_port = None
            self.is_connected = False
            self.machine_state = "Disconnected"
            self.disconnected.emit()
            self.log_received.emit("err", "Laser disconnected unexpectedly (USB cable unplugged or power loss).")

    def _handle_incoming_line(self, line: str):
        """Parses GRBL status string or normal response."""
        if self.stop_worker:
            return
        try:
            self._do_handle_incoming_line(line)
        except RuntimeError:
            return

    def _do_handle_incoming_line(self, line: str):
        if line.startswith("<") and line.endswith(">"):
            # Status report: <Idle|MPos:0.000,0.000,0.000|FS:0,0|Pn:PX>
            content = line[1:-1]
            parts = content.split("|")
            state = parts[0]
            self.machine_state = state

            status_dict = {"state": state, "mpos": self.mpos, "wpos": self.wpos, "pins": self.active_pins}

            for p in parts[1:]:
                if p.startswith("MPos:"):
                    try:
                        coords = [float(c) for c in p[5:].split(",")]
                        self.mpos = coords
                        status_dict["mpos"] = coords
                    except ValueError:
                        pass
                elif p.startswith("WPos:"):
                    try:
                        coords = [float(c) for c in p[5:].split(",")]
                        self.wpos = coords
                        status_dict["wpos"] = coords
                    except ValueError:
                        pass
                elif p.startswith("WCO:"):
                    try:
                        coords = [float(c) for c in p[4:].split(",")]
                        self.wco = coords
                    except ValueError:
                        pass
                elif p.startswith("Pn:"):
                    pins = p[3:]
                    self.active_pins = pins
                    status_dict["pins"] = pins
                elif p.startswith("Ov:"):
                    try:
                        ovs = [int(v) for v in p[3:].split(",")]
                        self.feed_override_pct = ovs[0]
                        self.rapid_override_pct = ovs[1]
                        self.power_override_pct = ovs[2]
                        status_dict["overrides"] = {
                            "feed": ovs[0],
                            "rapid": ovs[1],
                            "power": ovs[2]
                        }
                    except Exception:
                        pass

            # If controller only reports MPos ($10=1), compute WPos = MPos - WCO
            if not any(p.startswith("WPos:") for p in parts[1:]):
                self.wpos = [m - w for m, w in zip(self.mpos, self.wco)]
                status_dict["wpos"] = self.wpos

            self.status_updated.emit(status_dict)
        elif line == "ok":
            self.ack_queue.put(("ok", line))
            if not self.is_streaming:
                self.log_received.emit("rx", line)
        elif line.startswith("error:"):
            try:
                code = int(line.split(":")[1].strip())
                desc = GRBL_ERRORS.get(code, "Command error")
                err_desc = f"error:{code} ({desc})"
            except Exception:
                err_desc = line
            self.ack_queue.put(("error", err_desc))
            self.log_received.emit("err", err_desc)
        elif line.startswith("ALARM:"):
            self.machine_state = "Alarm"
            try:
                code = int(line.split(":")[1].strip())
                desc = GRBL_ALARMS.get(code, "Machine alarm")
                alarm_desc = f"ALARM:{code} ({desc})"
            except Exception:
                alarm_desc = line
            self.ack_queue.put(("alarm", alarm_desc))
            self.log_received.emit("err", alarm_desc)
        elif line.startswith("$"):
            self._handle_setting_line(line)
            self.log_received.emit("rx", line)
        elif line.startswith("["):
            self.log_received.emit("rx", line)
        else:
            self.log_received.emit("rx", line)

    def _handle_setting_line(self, line: str):
        """Parses $$ parameters like $130 (max X travel) and $131 (max Y travel)."""
        if "=" not in line:
            return
        key, raw_val = line.split("=", 1)
        key = key.strip()
        # Strip potential parenthesized comment: "80.000 (x, step/mm)"
        clean_val = raw_val.split("(")[0].strip() if "(" in raw_val else raw_val.strip()
        self.grbl_settings[key] = clean_val
        self.grbl_setting_received.emit(key, clean_val)
        self.grbl_settings_updated.emit(self.grbl_settings)

        try:
            if key == "$130":
                w = float(clean_val)
                if w > 0:
                    self.machine_limits["bed_width"] = w
            elif key == "$131":
                h = float(clean_val)
                if h > 0:
                    self.machine_limits["bed_height"] = h
            elif key == "$30":
                s = int(float(clean_val))
                if s > 0:
                    self.machine_limits["max_s_value"] = s
            elif key == "$31":
                self.machine_limits["min_s_value"] = int(float(clean_val))
            elif key == "$32":
                is_laser = int(float(clean_val)) == 1
                self.machine_limits["laser_mode"] = "M4" if is_laser else "M3"
            elif key == "$21":
                self.machine_limits["hard_limits"] = int(float(clean_val)) == 1
            elif key == "$20":
                self.machine_limits["soft_limits"] = int(float(clean_val)) == 1
            elif key == "$22":
                self.machine_limits["homing_enabled"] = int(float(clean_val)) == 1
            elif key == "$100":
                self.machine_limits["x_steps_per_mm"] = float(clean_val)
            elif key == "$101":
                self.machine_limits["y_steps_per_mm"] = float(clean_val)
            elif key == "$102":
                self.machine_limits["z_steps_per_mm"] = float(clean_val)
            elif key == "$110":
                self.machine_limits["x_max_rate"] = float(clean_val)
            elif key == "$111":
                self.machine_limits["y_max_rate"] = float(clean_val)
            elif key == "$120":
                self.machine_limits["x_accel"] = float(clean_val)
            elif key == "$121":
                self.machine_limits["y_accel"] = float(clean_val)
            elif key == "$3":
                mask = int(float(clean_val))
                self.machine_limits["invert_x_dir"] = bool(mask & 1)
                self.machine_limits["invert_y_dir"] = bool(mask & 2)
                self.machine_limits["invert_z_dir"] = bool(mask & 4)

            if key in ("$131", "$132"):
                self.machine_parameters_loaded.emit(self.machine_limits)
        except Exception:
            pass


