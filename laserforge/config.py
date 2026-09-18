"""
LaserForge Configuration and Default Parameters.
Stores default workbed geometry, layer palettes, laser cut profiles, and application settings.
"""

from dataclasses import dataclass, field
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
    min_s_value: int = 0
    laser_mode: str = DEFAULT_LASER_MODE  # "M4", "M3", or "M106"
    use_inline_power: bool = True         # Use inline G1 S... commands for smooth raster & vector moves
    enable_arcs: bool = True              # Emit native G2/G3 circular arcs instead of polygonal micro-lines
    rapid_speed: float = DEFAULT_RAPID_SPEED
    baud_rate: int = DEFAULT_BAUD_RATE
    jog_speed: float = DEFAULT_JOG_SPEED
    framing_power_pct: float = DEFAULT_FRAMING_POWER
    framing_speed: float = DEFAULT_FRAMING_SPEED

    # Laser Firing & Timing Controls
    laser_fire_delay_ms: float = 0.0      # Dwell pause in ms after laser fires before moving
    laser_off_delay_ms: float = 0.0       # Dwell pause in ms after laser shuts off
    overscan_enabled: bool = False        # Lead-in/lead-out overscan to eliminate edge burn
    overscan_pct: float = 2.5             # Overscan % of raster scanline length
    overscan_mode: str = "Acceleration"   # "Acceleration" (d=v^2/2a), "Percentage", or "Fixed"
    overscan_mm: float = 2.0              # Fixed overscan in mm
    overscan_accel_multiplier: float = 1.2 # Safety margin above theoretical v^2 / (2*a)
    white_space_skip_enabled: bool = True  # Rapid G0 jump across wide empty gaps
    white_space_skip_threshold_mm: float = 5.0 # Minimum gap (mm) to trigger G0 white-space skip
    flood_fill_enabled: bool = True       # Engrave disconnected shapes / islands individually
    flood_fill_separation_mm: float = 12.0 # Minimum gap (mm) between islands to trigger flood fill
    continuous_inline_streaming: bool = True # Zero-stutter G1 S... / G0 streaming without intermediate M5
    raster_fast_whitespace_speed: float = 0.0 # Rapid speed for whitespace jumps (0 = use machine rapid_speed)
    kerf_width_mm: float = 0.08           # Diode laser beam spot width / kerf compensation
    test_pulse_power_pct: float = 1.0     # Laser test fire pulse power %
    test_pulse_duration_ms: int = 100     # Laser test fire pulse duration ms

    # Kinematics & GRBL Parameters
    x_steps_per_mm: float = 80.0
    y_steps_per_mm: float = 80.0
    z_steps_per_mm: float = 250.0
    x_max_rate: float = 5000.0            # mm/min
    y_max_rate: float = 5000.0            # mm/min
    z_max_rate: float = 500.0             # mm/min
    x_accel: float = 500.0                # mm/sec^2
    y_accel: float = 500.0                # mm/sec^2
    z_accel: float = 10.0                 # mm/sec^2
    invert_x_dir: bool = False
    invert_y_dir: bool = False
    invert_z_dir: bool = False
    software_mirror_x: bool = False       # Invert X axis coordinates in generated G-code
    software_mirror_y: bool = False       # Invert Y axis coordinates in generated G-code
    soft_limits_enabled: bool = False
    hard_limits_enabled: bool = False
    homing_enabled: bool = False

    # Job Workflow & Post-Job Positioning
    finish_position_mode: str = "Origin"  # "Origin", "Job Start", "Park Position", "Hold Current"
    park_x: float = 0.0
    park_y: float = 0.0
    custom_start_gcode: str = ""
    custom_end_gcode: str = ""
    validate_gcode_before_start: bool = True  # Run pre-flight GRBL validator before job execution
    strict_validation: bool = False           # If True, block execution on warnings as well as errors

    # Air Assist & Peripherals
    air_assist_cmd: str = "M8"
    air_assist_off_cmd: str = "M9"
    enable_air_assist_by_default: bool = False
    air_assist_pre_delay_sec: float = 0.0
    air_assist_post_delay_sec: float = 0.0
    enable_z_moves: bool = False

    # Hardware GPU Acceleration & Display
    enable_gpu_acceleration: bool = True  # Accelerates raster filtering, dithering, and contour tracing via CUDA/OpenCL
    enable_opengl_canvas: bool = True     # Hardware OpenGL canvas viewport for 60-120 FPS rendering

    # Connectivity
    auto_connect: bool = True
    last_connected_port: str = ""

    # Rotary Axis Parameters (Rollers & Chucks)
    rotary_enabled: bool = False
    rotary_type: str = "Roller"           # "Roller" or "Chuck"
    rotary_mode: str = "Software Scaling" # "Software Scaling" or "Hardware $101"
    rotary_axis: str = "Y"                # Axis driven by rotary ("Y" or "X")
    rotary_roller_diameter: float = 20.0  # Drive roller wheel diameter in mm
    rotary_roller_distance: float = 50.0  # Center-to-center distance between rollers in mm
    rotary_object_diameter: float = 65.0  # Cylindrical workpiece outer diameter in mm
    rotary_steps_per_rev: float = 3200.0  # Steps per 360 degree revolution of rotary motor
    rotary_original_y_steps: float = 80.0 # Original Y-axis steps/mm ($101) to restore
    rotary_invert_dir: bool = False       # Invert rotation direction

    # Z-Probe & Auto-Focus
    z_probe_cmd: str = "G38.2"
    z_probe_feed_rate: float = 120.0
    z_probe_max_travel: float = 40.0
    z_probe_retract: float = 3.0
    z_probe_plate_thickness: float = 15.0
    z_probe_focal_offset: float = 0.0
    z_probe_auto_zero: bool = True

    # Audio Alerts & Workshop Chimes
    audio_chime_enabled: bool = True
    audio_chime_volume: float = 0.8

    # Custom G-Code Quick Macros
    custom_macros: List[Dict[str, str]] = field(default_factory=lambda: [
        {"name": "Home All", "gcode": "$H", "color": "#0099ff"},
        {"name": "Air Assist On", "gcode": "M8", "color": "#00cc66"},
        {"name": "Air Assist Off", "gcode": "M9", "color": "#757575"},
        {"name": "Go to Origin", "gcode": "G90 G0 X0 Y0", "color": "#ff9900"},
        {"name": "Park Rear", "gcode": "G90 G0 X0 Y400", "color": "#9966ff"},
        {"name": "Set Work Zero", "gcode": "G10 L20 P1 X0 Y0 Z0", "color": "#e91e63"},
    ])

    # Fisheye Camera Settings
    camera_fisheye_enabled: bool = False
    camera_lens_fov: float = 150.0
    camera_fisheye_k1: float = -0.12
    camera_fisheye_k2: float = 0.03
    camera_fisheye_k3: float = 0.0
    camera_fisheye_k4: float = 0.0

