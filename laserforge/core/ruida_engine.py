"""
LaserForge Ruida DSP Controller & .rd Binary Toolpath Engine.
Compiles vector toolpaths into native Ruida DSP scancodes (.rd / .ud5) and provides
an Ethernet UDP network driver for OMTech, Thunder Laser, and Boss CO2 laser cutters.
"""

from typing import List, Tuple, Dict, Any, Optional
import struct
import socket
import os
import math
from dataclasses import dataclass

from laserforge.core.models import LaserEntity, PathEntity, RectEntity, CircleEntity, LineEntity


RUIDA_DEFAULT_IP = "192.168.1.100"
RUIDA_DEFAULT_PORT = 50200
RUIDA_STEPS_PER_MM = 100.0  # Common hardware resolution (0.01 mm per Ruida step)


@dataclass
class RuidaLayerConfig:
    layer_id: int = 0
    speed_mm_s: float = 100.0      # Ruida speeds are in mm/s (not mm/min)
    power_pct: float = 20.0        # 0 - 100 %
    min_power_pct: float = 15.0    # Corner min power
    air_assist: bool = True


class RuidaCompiler:
    """Compiles 2D geometries into Ruida DSP binary byte streams (.rd)."""

    # Ruida Opcode constants
    CMD_RAPID_MOVE = 0x88
    CMD_CUT_MOVE = 0x89
    CMD_SET_POWER = 0x8A
    CMD_SET_SPEED = 0x8B
    CMD_LASER_ON = 0x8C
    CMD_LASER_OFF = 0x8D
    CMD_END_JOB = 0x00

    @classmethod
    def compile_paths_to_rd(
        cls,
        entities: List[LaserEntity],
        layer_configs: Optional[Dict[int, RuidaLayerConfig]] = None,
        scale_steps_per_mm: float = RUIDA_STEPS_PER_MM
    ) -> bytearray:
        """
        Encodes vector entities into standard Ruida DSP binary payload.
        Coordinates are converted to integer step counts (0.01mm resolution).
        """
        stream = bytearray()

        # Ruida Magic Header
        stream.extend(b"RD6442\x00\x01")

        current_x = 0
        current_y = 0

        for ent in entities:
            # Determine layer settings
            cfg = layer_configs.get(ent.layer_id, RuidaLayerConfig()) if layer_configs else RuidaLayerConfig()
            pwr = getattr(ent, "power_override", None) or cfg.power_pct
            spd = getattr(ent, "speed_override", None) or (cfg.speed_mm_s * 60.0)
            spd_mm_s = spd / 60.0

            # Emit speed and power commands
            # Power command: 0x8A + 1 byte power (0-100)
            stream.append(cls.CMD_SET_POWER)
            stream.append(int(min(100, max(0, round(pwr)))))

            # Speed command: 0x8B + 2 bytes speed in mm/s
            stream.append(cls.CMD_SET_SPEED)
            stream.extend(struct.pack(">H", int(min(65535, max(1, round(spd_mm_s))))))

            # Extract line segments
            paths: List[List[Tuple[float, float]]] = []
            if isinstance(ent, PathEntity):
                for c in ent.contours:
                    abs_c = [(ent.x + px, ent.y + py) for px, py in c]
                    if ent.closed and abs_c and abs_c[0] != abs_c[-1]:
                        abs_c.append(abs_c[0])
                    paths.append(abs_c)
            elif isinstance(ent, RectEntity):
                pts = [
                    (ent.x, ent.y),
                    (ent.x + ent.width, ent.y),
                    (ent.x + ent.width, ent.y + ent.height),
                    (ent.x, ent.y + ent.height),
                    (ent.x, ent.y)
                ]
                paths.append(pts)
            elif isinstance(ent, LineEntity):
                paths.append([(ent.x, ent.y), (ent.x2, ent.y2)])
            elif isinstance(ent, CircleEntity):
                # Interpolate circle
                steps = 36
                circ_pts = []
                for s in range(steps + 1):
                    rad = 2.0 * math.pi * (s / float(steps))
                    circ_pts.append((ent.x + ent.radius_x * math.cos(rad), ent.y + ent.radius_y * math.sin(rad)))
                paths.append(circ_pts)

            for path in paths:
                if not path:
                    continue

                # 1. Rapid move to path start (laser OFF)
                start_x = int(round(path[0][0] * scale_steps_per_mm))
                start_y = int(round(path[0][1] * scale_steps_per_mm))

                stream.append(cls.CMD_LASER_OFF)
                stream.append(cls.CMD_RAPID_MOVE)
                stream.extend(struct.pack(">ii", start_x, start_y))

                # 2. Laser ON and cut moves
                stream.append(cls.CMD_LASER_ON)
                for pt in path[1:]:
                    tx = int(round(pt[0] * scale_steps_per_mm))
                    ty = int(round(pt[1] * scale_steps_per_mm))
                    stream.append(cls.CMD_CUT_MOVE)
                    stream.extend(struct.pack(">ii", tx, ty))

                # 3. Laser OFF at end of path
                stream.append(cls.CMD_LASER_OFF)

        # End of job marker
        stream.append(cls.CMD_END_JOB)
        return stream


class RuidaUDPClient:
    """Ethernet UDP client for communication with Ruida RDC644X laser controllers."""

    def __init__(self, ip: str = RUIDA_DEFAULT_IP, port: int = RUIDA_DEFAULT_PORT, timeout_sec: float = 1.5):
        self.ip = ip
        self.port = port
        self.timeout = timeout_sec

    def ping(self) -> Tuple[bool, str]:
        """Sends a query packet to check if the Ruida controller is online."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            # Ruida diagnostic status inquiry packet: 0xD5, 0x5D, 0x00, 0x01
            query = bytes([0xD5, 0x5D, 0x00, 0x01])
            sock.sendto(query, (self.ip, self.port))
            data, addr = sock.recvfrom(1024)
            sock.close()
            return True, f"Ruida Controller Online at {self.ip}:{self.port} (Received {len(data)} bytes)"
        except socket.timeout:
            return False, f"Timeout: No response from Ruida controller at {self.ip}:{self.port}"
        except Exception as e:
            return False, f"Network Error: {e}"

    def upload_rd_file(self, rd_bytes: bytes, filename: str = "job.rd") -> Tuple[bool, str]:
        """Uploads .rd binary toolpath payload to Ruida memory buffer."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout * 2)

            # Chunked transmission (Ruida packets typically 1024 bytes)
            chunk_size = 1024
            total_chunks = max(1, int(math.ceil(len(rd_bytes) / float(chunk_size))))

            for i in range(total_chunks):
                chunk = rd_bytes[i * chunk_size:(i + 1) * chunk_size]
                header = struct.pack(">BBHH", 0xD5, 0x5D, i, len(chunk))
                sock.sendto(header + chunk, (self.ip, self.port))

            sock.close()
            return True, f"Successfully transferred {len(rd_bytes)} bytes ({total_chunks} packets) to Ruida DSP."
        except Exception as e:
            return False, f"Upload failed: {e}"

    def start_job(self) -> Tuple[bool, str]:
        """Traces and starts burning active memory buffer on Ruida."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            cmd = bytes([0xD5, 0x5D, 0x03, 0x01])  # Ruida START command
            sock.sendto(cmd, (self.ip, self.port))
            sock.close()
            return True, "Ruida burn started."
        except Exception as e:
            return False, f"Failed to start Ruida job: {e}"

    def stop_job(self) -> Tuple[bool, str]:
        """Emergency stop command to halt Ruida motion."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            cmd = bytes([0xD5, 0x5D, 0x04, 0x01])  # Ruida STOP command
            sock.sendto(cmd, (self.ip, self.port))
            sock.close()
            return True, "Ruida emergency stop dispatched."
        except Exception as e:
            return False, f"Failed to stop Ruida: {e}"
