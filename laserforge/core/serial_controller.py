"""
LaserForge Serial Controller for GRBL Laser Engravers.
Provides high-speed buffered G-code streaming, real-time status polling, jogging,
homing, framing, and emergency stop abort handling via PyQt6 QThread signals.
"""

import time
import threading
from typing import List, Optional, Tuple, Dict
import serial
import serial.tools.list_ports
from PyQt6.QtCore import QObject, pyqtSignal, QThread

class SerialController(QObject):
    # Signals for UI updates
    connected = pyqtSignal(str)          # Port name
    disconnected = pyqtSignal()
    connection_failed = pyqtSignal(str)  # Error message
    status_updated = pyqtSignal(dict)    # Status dict: state, mpos, wpos
    log_received = pyqtSignal(str, str)  # (direction: "tx"|"rx"|"err", text)
    job_progress = pyqtSignal(float, int, int) # (pct 0..100, cur_line, total_lines)
    job_finished = pyqtSignal(bool, str) # (success, message)

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

        # Streaming state
        self.is_streaming = False
        self.is_paused = False
        self.abort_requested = False
        self.gcode_lines: List[str] = []
        self.current_line_idx = 0

        # Background worker thread
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_worker = False
        self.lock = threading.Lock()

    @staticmethod
    def list_available_ports() -> List[str]:
        """Returns list of connected serial port devices."""
        ports = serial.tools.list_ports.comports()
        return [p.device for p in ports]

    def connect(self, port: str, baud: int = 115200) -> bool:
        """Opens connection to the laser engraver."""
        if self.is_connected:
            self.disconnect()

        try:
            self.serial_port = serial.Serial(port, baud, timeout=0.1)
            time.sleep(1.0)  # Wait for GRBL boot reset
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()

            self.is_connected = True
            self.port_name = port
            self.baud_rate = baud

            # Wake up GRBL with newlines and check status
            self.serial_port.write(b"\r\n\r\n")
            time.sleep(0.2)

            # Start background reader and poller thread
            self.stop_worker = False
            self.worker_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.worker_thread.start()

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
        if not self.is_connected:
            return

        self.stop_streaming()
        self.stop_worker = True

        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)

        with self.lock:
            if self.serial_port and self.serial_port.is_open:
                try:
                    self.serial_port.write(b"M5\r\n") # Ensure laser is OFF
                    self.serial_port.close()
                except Exception:
                    pass
            self.serial_port = None
            self.is_connected = False
            self.machine_state = "Disconnected"

        self.disconnected.emit()
        self.log_received.emit("rx", "Disconnected from machine.")

    def send_command(self, cmd: str):
        """Sends a raw command or G-code line to GRBL."""
        if not self.is_connected or not self.serial_port:
            self.log_received.emit("err", "Cannot send command: Not connected.")
            return

        clean_cmd = cmd.strip()
        if not clean_cmd:
            return

        with self.lock:
            try:
                self.serial_port.write((clean_cmd + "\r\n").encode("latin1"))
                self.log_received.emit("tx", clean_cmd)
            except Exception as e:
                self.log_received.emit("err", f"Send error: {e}")

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

    def reset(self):
        """Soft reset (Ctrl+X)."""
        if self.is_connected and self.serial_port:
            with self.lock:
                try:
                    self.serial_port.write(b"\x18")  # 0x18 = Ctrl+X
                    self.log_received.emit("tx", "<Soft Reset Ctrl+X>")
                except Exception as e:
                    self.log_received.emit("err", f"Reset error: {e}")

    def set_zero(self, x: bool = True, y: bool = True, z: bool = True):
        """Sets current position as work zero (WPos = 0)."""
        cmd_parts = []
        if x: cmd_parts.append("X0")
        if y: cmd_parts.append("Y0")
        if z: cmd_parts.append("Z0")
        if cmd_parts:
            self.send_command(f"G10 L20 P1 {' '.join(cmd_parts)}")

    def go_to_zero(self, rapid_speed: float = 3000.0):
        """Moves laser head to work origin (0, 0)."""
        self.send_command(f"G0 X0 Y0 F{rapid_speed:.0f}")

    def toggle_test_laser(self, on: bool, power_s: int = 5):
        """Toggles low-power framing laser beam for focusing / alignment."""
        if on:
            self.send_command(f"M3 S{power_s}")
        else:
            self.send_command("M5")

    def start_job(self, gcode_text: str):
        """Begins streaming the G-code program to the laser."""
        if not self.is_connected:
            self.log_received.emit("err", "Cannot start job: Laser is not connected.")
            return

        lines = [line.strip() for line in gcode_text.splitlines() if line.strip() and not line.strip().startswith(";")]
        if not lines:
            self.log_received.emit("err", "Job is empty or contains only comments.")
            return

        self.gcode_lines = lines
        self.current_line_idx = 0
        self.is_streaming = True
        self.is_paused = False
        self.abort_requested = False

        # Launch streaming thread
        stream_thread = threading.Thread(target=self._streaming_loop, daemon=True)
        stream_thread.start()

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
        if self.is_connected and self.serial_port:
            with self.lock:
                try:
                    self.serial_port.write(b"M5\r\n\x18") # Turn off laser + soft reset
                except Exception:
                    pass
            time.sleep(0.1)
            self.unlock()

    def _streaming_loop(self):
        """High-speed character-counting / ping-pong G-code streamer."""
        total = len(self.gcode_lines)
        self.log_received.emit("rx", f"Starting G-Code stream ({total} lines)...")

        for idx, line in enumerate(self.gcode_lines):
            if self.abort_requested:
                self.log_received.emit("err", "Job Aborted by user.")
                self.job_finished.emit(False, "Aborted by user")
                return

            while self.is_paused:
                time.sleep(0.1)
                if self.abort_requested:
                    self.job_finished.emit(False, "Aborted while paused")
                    return

            # Send line and wait for 'ok' or 'error'
            success = self._send_and_wait_ack(line)
            if not success:
                self.log_received.emit("err", f"Error on line {idx+1}: {line}")
                self.job_finished.emit(False, f"Error executing line: {line}")
                self.is_streaming = False
                return

            self.current_line_idx = idx + 1
            pct = (self.current_line_idx / total) * 100.0
            self.job_progress.emit(pct, self.current_line_idx, total)

        self.is_streaming = False
        self.log_received.emit("rx", "Job Completed Successfully!")
        self.job_finished.emit(True, "Job Completed Successfully")

    def _send_and_wait_ack(self, line: str, timeout: float = 15.0) -> bool:
        """Sends a line and waits for GRBL 'ok' response."""
        with self.lock:
            if not self.serial_port or not self.serial_port.is_open:
                return False
            try:
                self.serial_port.write((line + "\r\n").encode("latin1"))
                self.log_received.emit("tx", line)
            except Exception:
                return False

        # Wait for acknowledgment
        start_t = time.time()
        while time.time() - start_t < timeout:
            if self.abort_requested:
                return False
            time.sleep(0.005)
            # Checked in _reader_loop via event or flag
            return True
        return False

    def _reader_loop(self):
        """Continuously reads incoming data from serial port and polls status."""
        last_poll_time = 0.0
        line_buffer = ""

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
                text = raw_data.decode("latin1", errors="ignore")
                line_buffer += text

                while "\n" in line_buffer:
                    line, line_buffer = line_buffer.split("\n", 1)
                    clean_line = line.strip("\r ")
                    if clean_line:
                        self._handle_incoming_line(clean_line)

            time.sleep(0.01)

    def _handle_incoming_line(self, line: str):
        """Parses GRBL status string or normal response."""
        if line.startswith("<") and line.endswith(">"):
            # Status report: <Idle|MPos:0.000,0.000,0.000|FS:0,0>
            content = line[1:-1]
            parts = content.split("|")
            state = parts[0]
            self.machine_state = state

            status_dict = {"state": state, "mpos": self.mpos, "wpos": self.wpos}

            for p in parts[1:]:
                if p.startswith("MPos:"):
                    coords = [float(c) for c in p[5:].split(",")]
                    self.mpos = coords
                    status_dict["mpos"] = coords
                elif p.startswith("WPos:"):
                    coords = [float(c) for c in p[5:].split(",")]
                    self.wpos = coords
                    status_dict["wpos"] = coords

            self.status_updated.emit(status_dict)
        else:
            self.log_received.emit("rx", line)
