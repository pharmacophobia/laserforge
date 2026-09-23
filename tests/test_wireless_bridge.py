"""
Tests for LaserForge Wireless Bridge, NetworkSocketSerial, and Auto-Discovery.
Verifies seamless communication with PiBridge on Raspberry Pi.
"""

import socket
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from PyQt6.QtCore import QCoreApplication

from laserforge.core.auto_connect import (
    probe_network_laser,
    probe_port_for_grbl,
    AutoConnectWorker,
    PortDetector
)
from laserforge.core.serial_controller import NetworkSocketSerial, SerialController


class MockGrblTcpServer:
    """Lightweight mock TCP server simulating a GRBL laser controller on PiBridge."""
    def __init__(self, port: int = 0):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('127.0.0.1', port))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            try:
                self.server.settimeout(0.5)
                client, _ = self.server.accept()
                client.settimeout(0.5)
                # Send welcome banner on connect
                client.sendall(b"\r\nGrbl 1.1h ['$' for help]\r\n")
                while self.running:
                    try:
                        data = client.recv(1024)
                        if not data:
                            break
                        if b"?" in data:
                            client.sendall(b"<Idle|MPos:10.000,20.000,0.000|Bf:15,128|FS:0,0>\r\nok\r\n")
                        elif b"$$" in data:
                            client.sendall(b"$0=10\r\n$1=25\r\nok\r\n")
                        elif b"$I" in data:
                            client.sendall(b"[VER:1.1h.20260920:LaserForge]\r\nok\r\n")
                        elif b"\x18" in data: # Soft reset
                            client.sendall(b"\r\nGrbl 1.1h ['$' for help]\r\n")
                        else:
                            client.sendall(b"ok\r\n")
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                client.close()
            except socket.timeout:
                continue
            except Exception:
                break

    def stop(self):
        self.running = False
        try:
            self.server.close()
        except Exception:
            pass


class TestWirelessBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_server = MockGrblTcpServer()
        cls.server_port = cls.mock_server.port

    @classmethod
    def tearDownClass(cls):
        cls.mock_server.stop()

    def test_probe_network_laser_success(self):
        """Verifies probing an active TCP GRBL bridge returns True and the GRBL banner."""
        target = f"tcp://127.0.0.1:{self.server_port}"
        is_grbl, baud, banner = probe_network_laser(target, timeout=1.0)
        self.assertTrue(is_grbl)
        self.assertEqual(baud, 115200)
        self.assertTrue("Grbl" in banner or "<" in banner)

    def test_probe_network_laser_offline(self):
        """Verifies probing an offline network address fails gracefully without throwing."""
        target = "tcp://127.0.0.1:59999"  # Unused port
        is_grbl, baud, banner = probe_network_laser(target, timeout=0.1)
        self.assertFalse(is_grbl)
        self.assertIsNone(baud)

    def test_probe_port_for_grbl_routes_network(self):
        """Verifies probe_port_for_grbl automatically dispatches network URIs to probe_network_laser."""
        target = f"tcp://127.0.0.1:{self.server_port}"
        is_grbl, baud, banner = probe_port_for_grbl(target, timeout=1.0)
        self.assertTrue(is_grbl)
        self.assertEqual(baud, 115200)

    def test_network_socket_serial_stream(self):
        """Tests NetworkSocketSerial drop-in pySerial emulator with real socket server."""
        ser = NetworkSocketSerial(host="127.0.0.1", port=self.server_port, timeout=1.0)
        self.assertTrue(ser.is_open)

        # Give server time to send initial banner
        time.sleep(0.15)
        self.assertTrue(ser.in_waiting > 0)
        banner = ser.read(ser.in_waiting).decode("latin1")
        self.assertIn("Grbl", banner)

        # Send status query
        ser.write(b"?\n")
        time.sleep(0.15)
        resp = ser.read(ser.in_waiting).decode("latin1")
        self.assertIn("Idle", resp)

        ser.close()
        self.assertFalse(ser.is_open)

    def test_serial_controller_network_connect(self):
        """Verifies SerialController successfully connects and interacts with a network laser."""
        ctrl = SerialController()
        connected_events = []
        ctrl.connected.connect(lambda p: connected_events.append(p))

        target = f"tcp://127.0.0.1:{self.server_port}"
        success = ctrl.connect(target, baud=115200)
        self.assertTrue(success)
        self.assertTrue(ctrl.is_connected)
        self.assertEqual(len(connected_events), 1)

        # Send test command
        ctrl.send_command("G0 X10 Y20")
        time.sleep(0.1)

        ctrl.disconnect()
        self.assertFalse(ctrl.is_connected)

    def test_autoconnect_worker_discovers_wireless_laser(self):
        """Verifies AutoConnectWorker detects wireless laser when USB ports return no laser."""
        target = f"tcp://127.0.0.1:{self.server_port}"

        # Mock PortDetector to return no USB ports, and mock default target to our mock server
        with patch.object(PortDetector, "get_ranked_ports", return_value=[]):
            with patch("laserforge.core.auto_connect.probe_port_for_grbl") as mock_probe:
                def fake_probe(port, *args, **kwargs):
                    if "laserbridge" in port or str(self.server_port) in port:
                        return True, 115200, "<Idle|MPos:0,0,0>"
                    return False, None, ""
                mock_probe.side_effect = fake_probe

                worker = AutoConnectWorker()
                found_signals = []
                worker.laser_found.connect(lambda port, baud, banner: found_signals.append((port, baud, banner)))

                worker.run()

                self.assertEqual(len(found_signals), 1)
                self.assertIn("tcp://laserbridge.local:8088", found_signals[0][0])
                self.assertEqual(found_signals[0][1], 115200)


if __name__ == '__main__':
    unittest.main()
