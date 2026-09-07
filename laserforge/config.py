"""
LaserForge Configuration and Default Parameters.
Stores default workbed geometry, layer palettes, laser cut profiles, and application settings.
"""

from dataclasses import dataclass
from typing import Dict, List

# Default Machine Workbed Geometry
DEFAULT_BED_WIDTH_MM = 400.0   # Default 400 mm
DEFAULT_BED_HEIGHT_MM = 400.0  # Default 400 mm
DEFAULT_ORIGIN_CORNER = "Bottom-Left"  # "Bottom-Left", "Top-Left", "Bottom-Right", "Top-Right"

# Default Machine G-Code Parameters
DEFAULT_BAUD_RATE = 115200
DEFAULT_MAX_S_VALUE = 1000     # GRBL $30 max spindle speed
DEFAULT_LASER_MODE = "M4"      # M4 = Dynamic laser power (GRBL 1.1+), M3 = Constant power
DEFAULT_RAPID_SPEED = 3000.0   # G0 speed in mm/min
DEFAULT_JOG_SPEED = 2000.0     # Jogging speed in mm/min
DEFAULT_FRAMING_POWER = 0.5    # 0.5% power for visible framing guide without burning material
DEFAULT_FRAMING_SPEED = 2000.0 # Speed when framing bounding box

# LightBurn Standard Layer Color Palette
LAYER_PALETTE: List[Dict[str, str]] = [
    {"id": 0, "name": "C00", "color": "#000000", "label": "Black"},
    {"id": 1, "name": "C01", "color": "#1E90FF", "label": "Blue"},
    {"id": 2, "name": "C02", "color": "#FF2A2A", "label": "Red"},
    {"id": 3, "name": "C03", "color": "#00C853", "label": "Green"},
    {"id": 4, "name": "C04", "color": "#FFD600", "label": "Yellow"},
    {"id": 5, "name": "C05", "color": "#FF6D00", "label": "Orange"},
    {"id": 6, "name": "C06", "color": "#00E5FF", "label": "Cyan"},
    {"id": 7, "name": "C07", "color": "#D500F9", "label": "Magenta"},
    {"id": 8, "name": "C08", "color": "#8D6E63", "label": "Brown"},
    {"id": 9, "name": "C09", "color": "#78909C", "label": "Slate"},
    {"id": 10, "name": "C10", "color": "#FF4081", "label": "Pink"},
    {"id": 11, "name": "C11", "color": "#76FF03", "label": "Lime"},
    {"id": 12, "name": "T1", "color": "#E040FB", "label": "Tool / Guide", "is_tool": True},
]

# Supported Cut Modes
CUT_MODES = ["Line", "Fill", "Fill + Line", "Image"]

@dataclass
class MachineSettings:
    bed_width: float = DEFAULT_BED_WIDTH_MM
    bed_height: float = DEFAULT_BED_HEIGHT_MM
    origin_corner: str = DEFAULT_ORIGIN_CORNER
    max_s_value: int = DEFAULT_MAX_S_VALUE
    laser_mode: str = DEFAULT_LASER_MODE
    rapid_speed: float = DEFAULT_RAPID_SPEED
    baud_rate: int = DEFAULT_BAUD_RATE
    framing_power_pct: float = DEFAULT_FRAMING_POWER
    framing_speed: float = DEFAULT_FRAMING_SPEED
    air_assist_cmd: str = "M8"
    air_assist_off_cmd: str = "M9"
    enable_z_moves: bool = False
