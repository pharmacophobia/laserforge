"""
LaserForge Rotary Axis Engine (Rollers & Chucks).
Computes surface step scaling, circumferences, roller wheel contact kinematics,
software G-code coordinate scaling, and GRBL $101 EEPROM overrides.
"""

import math
from typing import Tuple, Dict, Any, Optional
from laserforge.config import MachineSettings


class RotaryEngine:
    """
    Kinematics engine for rotary roller and chuck laser engraving.
    """

    @staticmethod
    def compute_circumference(diameter_mm: float) -> float:
        """Calculates workpiece circumference C = pi * diameter."""
        if diameter_mm <= 0:
            return 0.0
        return math.pi * diameter_mm

    @staticmethod
    def calculate_steps_per_mm(
        rotary_type: str,
        object_diameter_mm: float,
        steps_per_rev: float,
        roller_diameter_mm: float = 20.0
    ) -> float:
        """
        Calculates effective steps per millimeter for roller or chuck rotary attachments.

        Parameters:
            rotary_type: "Roller" or "Chuck"
            object_diameter_mm: Workpiece cylindrical outer diameter (mm)
            steps_per_rev: Motor steps per 360 degree revolution (e.g. 200 steps * 16 microsteps = 3200)
            roller_diameter_mm: Diameter of the driving roller wheels (for Roller type)

        Returns:
            Required steps per millimeter.
        """
        if steps_per_rev <= 0:
            return 80.0

        if rotary_type.lower() == "roller":
            # For roller rotary, contact surface speed equals roller wheel surface speed
            # C_roller = pi * D_roller
            # steps/mm = steps_per_rev / (pi * D_roller)
            d = max(1.0, roller_diameter_mm)
            circ = math.pi * d
            return steps_per_rev / circ

        else:  # "Chuck"
            # For chuck rotary, 1 revolution rotates the workpiece by pi * D_object
            d = max(1.0, object_diameter_mm)
            circ = math.pi * d
            return steps_per_rev / circ

    @classmethod
    def calculate_software_scale_factor(
        cls,
        settings: MachineSettings
    ) -> float:
        """
        Computes the coordinate scaling multiplier for software-based G-code transformation.
        scale_factor = target_rotary_steps_per_mm / original_machine_steps_per_mm
        """
        if not settings.rotary_enabled:
            return 1.0

        target_steps = cls.calculate_steps_per_mm(
            rotary_type=settings.rotary_type,
            object_diameter_mm=settings.rotary_object_diameter,
            steps_per_rev=settings.rotary_steps_per_rev,
            roller_diameter_mm=settings.rotary_roller_diameter
        )

        base_steps = settings.rotary_original_y_steps if settings.rotary_original_y_steps > 0 else settings.y_steps_per_mm
        if base_steps <= 0:
            return 1.0

        scale = target_steps / base_steps
        if settings.rotary_invert_dir:
            scale = -scale
        return scale

    @classmethod
    def generate_test_rotation_gcode(
        cls,
        settings: MachineSettings,
        feedrate: float = 1200.0
    ) -> str:
        """
        Generates G-code to rotate the workpiece exactly 360 degrees and back.
        Uses relative moves (G91) and restores absolute positioning (G90).
        """
        circ = cls.compute_circumference(settings.rotary_object_diameter)
        if circ <= 0:
            circ = 100.0

        scale = 1.0
        if settings.rotary_mode == "Software Scaling":
            scale = cls.calculate_software_scale_factor(settings)

        # Distance to move in machine coordinates
        move_dist = circ * scale
        inv = -1.0 if settings.rotary_invert_dir else 1.0
        signed_dist = move_dist * inv

        lines = [
            "; --- LaserForge Rotary 360° Calibration Test ---",
            "G91          ; Relative positioning",
            f"G0 Y{signed_dist:.3f} F{feedrate:.0f} ; Rotate +360°",
            "G4 P0.5      ; Dwell pause 0.5s",
            f"G0 Y{-signed_dist:.3f} F{feedrate:.0f} ; Return -360°",
            "G90          ; Restore absolute positioning",
            "; --- Test Complete ---"
        ]
        return "\n".join(lines)

    @classmethod
    def generate_eeprom_override_command(cls, settings: MachineSettings) -> str:
        """Returns the GRBL EEPROM command to set $101 to the rotary steps/mm."""
        target_steps = cls.calculate_steps_per_mm(
            rotary_type=settings.rotary_type,
            object_diameter_mm=settings.rotary_object_diameter,
            steps_per_rev=settings.rotary_steps_per_rev,
            roller_diameter_mm=settings.rotary_roller_diameter
        )
        return f"$101={target_steps:.3f}"

    @classmethod
    def generate_eeprom_restore_command(cls, settings: MachineSettings) -> str:
        """Returns the GRBL EEPROM command to restore $101 to the original steps/mm."""
        orig = settings.rotary_original_y_steps if settings.rotary_original_y_steps > 0 else settings.y_steps_per_mm
        return f"$101={orig:.3f}"
