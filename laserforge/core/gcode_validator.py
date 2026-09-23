"""
LaserForge GRBL 1.1 G-Code Validator Engine.
Performs pre-flight inspection of G-code programs to prevent machine alarms,
workpiece damage, hardware collisions, and unsafe laser operations.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set, Any
import re
import math

from laserforge.config import MachineSettings


@dataclass(slots=True)
class ValidationIssue:
    line_number: int       # 1-indexed line number
    line_text: str         # Original line text
    severity: str          # "error" or "warning"
    error_code: str        # e.g. "GRBL_ERR_20", "OUT_OF_BOUNDS", "LASER_SAFETY"
    message: str           # User-friendly explanation


@dataclass
class ValidationReport:
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    total_lines: int = 0
    motion_count: int = 0
    bounding_box: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # (min_x, min_y, max_x, max_y)
    max_feedrate: float = 0.0
    max_power: float = 0.0
    laser_mode: str = "None"
    laser_ever_fired: bool = False
    laser_off_at_end: bool = True

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    def summary_text(self) -> str:
        """Returns a formatted plain-text summary of the validation report."""
        lines = []
        if self.has_errors:
            lines.append(f"❌ Validation FAILED with {len(self.errors)} error(s) and {len(self.warnings)} warning(s).")
        elif self.has_warnings:
            lines.append(f"⚠️ Validation PASSED with {len(self.warnings)} warning(s).")
        else:
            lines.append("✅ Validation PASSED: G-Code is 100% GRBL 1.1 compliant.")

        lines.append(f"• Total Lines: {self.total_lines} ({self.motion_count} motion moves)")
        min_x, min_y, max_x, max_y = self.bounding_box
        lines.append(f"• Motion Extents: X: [{min_x:.2f}, {max_x:.2f}] mm, Y: [{min_y:.2f}, {max_y:.2f}] mm")
        lines.append(f"• Max Feedrate: {self.max_feedrate:.0f} mm/min | Max Laser Power: S{self.max_power:.0f}")
        return "\n".join(lines)


class GCodeValidator:
    """
    GRBL 1.1 Pre-Flight G-Code Validator.
    Simulates modal state machines, tracks motion coordinates, and verifies GRBL compliance.
    """

    # GRBL 1.1 Modal Groups
    MODAL_GROUPS_G: Dict[str, int] = {
        # Group 0: Non-modal
        "G4": 0, "G10": 0, "G28": 0, "G30": 0, "G28.1": 0, "G30.1": 0, "G53": 0, "G92": 0, "G92.1": 0,
        # Group 1: Motion
        "G0": 1, "G1": 1, "G2": 1, "G3": 1, "G38.2": 1, "G38.3": 1, "G38.4": 1, "G38.5": 1, "G80": 1,
        # Group 2: Plane Selection
        "G17": 2, "G18": 2, "G19": 2,
        # Group 3: Distance Mode
        "G90": 3, "G91": 3,
        # Group 4: Arc IJK Distance Mode
        "G91.1": 4,
        # Group 5: Feed Rate Mode
        "G93": 5, "G94": 5,
        # Group 6: Units
        "G20": 6, "G21": 6,
        # Group 7: Cutter Radius Compensation
        "G40": 7,
        # Group 8: Tool Length Offset
        "G43.1": 8, "G49": 8,
        # Group 12: Work Coordinate System
        "G54": 12, "G55": 12, "G56": 12, "G57": 12, "G58": 12, "G59": 12,
        # Group 13: Path Control Mode
        "G61": 13,
    }

    MODAL_GROUPS_M: Dict[str, int] = {
        # Group 0: Program Flow
        "M0": 0, "M1": 0, "M2": 0, "M30": 0,
        # Group 4: Spindle / Laser Mode
        "M3": 4, "M4": 4, "M5": 4,
        # Group 7: Coolant / Air Assist
        "M7": 7, "M8": 7, "M9": 7,
    }

    # Common 3D-Printer (Marlin/RepRap) codes that cause GRBL error:20
    MARLIN_3D_CODES: Dict[str, str] = {
        "M104": "Set Extruder Temperature (3D printer code)",
        "M109": "Wait for Extruder Temperature (3D printer code)",
        "M140": "Set Bed Temperature (3D printer code)",
        "M190": "Wait for Bed Temperature (3D printer code)",
        "M106": "Fan Speed (3D printer code)",
        "M107": "Fan Off (3D printer code)",
        "M82": "Extruder Absolute Mode (3D printer code)",
        "M83": "Extruder Relative Mode (3D printer code)",
        "M84": "Stop Idle Hold / Steppers Off (3D printer code)",
        "G29": "Bed Auto-Leveling (3D printer code)",
    }

    VALID_WORDS: Set[str] = {
        "G", "M", "F", "S", "X", "Y", "Z", "I", "J", "K", "R", "P", "L", "N", "T", "%"
    }

    def __init__(self, settings: Optional[MachineSettings] = None, strict: bool = False):
        self.settings = settings or MachineSettings()
        self.strict = strict

    def validate(
        self,
        gcode_text: str,
        bed_width: Optional[float] = None,
        bed_height: Optional[float] = None,
        max_s: Optional[int] = None
    ) -> ValidationReport:
        """
        Validates G-code program string against GRBL 1.1 specs, travel boundaries, and laser safety.
        """
        w = bed_width if bed_width is not None else self.settings.bed_width
        h = bed_height if bed_height is not None else self.settings.bed_height
        max_power = max_s if max_s is not None else self.settings.max_s_value

        issues: List[ValidationIssue] = []
        raw_lines = gcode_text.splitlines()

        # Simulated Controller State
        cur_motion_mode: Optional[str] = None  # G0, G1, G2, G3, etc.
        cur_distance_mode: str = "G90"         # G90 (absolute) or G91 (incremental)
        cur_plane: str = "G17"                 # G17 (XY)
        cur_units: str = "G21"                 # G21 (mm) or G20 (inch)
        cur_feedrate: Optional[float] = None
        cur_laser_cmd: Optional[str] = None    # M3, M4, M5
        cur_s_value: float = 0.0
        cur_x: float = 0.0
        cur_y: float = 0.0
        cur_z: float = 0.0

        all_x: List[float] = [0.0]
        all_y: List[float] = [0.0]
        motion_count: int = 0
        peak_feedrate: float = 0.0
        peak_power: float = 0.0
        laser_ever_fired: bool = False
        laser_off_at_end: bool = True

        # Tolerances
        bounds_tolerance = 0.5  # 0.5 mm boundary margin

        for line_idx, raw_line in enumerate(raw_lines, start=1):
            line_str = raw_line.strip()
            if not line_str:
                continue

            # Check 1: Maximum buffer line length (GRBL line buffer is 256 bytes)
            # Pure comment lines (starting with ; or () never enter GRBL's line buffer.
            # Any command or mixed line exceeding 256 bytes triggers buffer overflow.
            if not line_str.startswith(";") and not line_str.startswith("(") and len(raw_line) > 256:
                issues.append(ValidationIssue(
                    line_number=line_idx,
                    line_text=raw_line[:60] + "...",
                    severity="error",
                    error_code="GRBL_BUFFER_OVERFLOW",
                    message=f"Line length ({len(raw_line)} chars) exceeds GRBL maximum buffer size of 256 bytes."
                ))

            # Strip comments
            # 1. Semicolon comments
            clean_line = re.sub(r';.*$', '', line_str)
            # 2. Parentheses comments
            clean_line = re.sub(r'\(.*?\)', '', clean_line).strip()

            if not clean_line:
                continue

            # GRBL special command check (e.g. $$, $H, $X inside gcode file)
            if clean_line.startswith("$"):
                issues.append(ValidationIssue(
                    line_number=line_idx,
                    line_text=raw_line,
                    severity="warning",
                    error_code="GRBL_SYSTEM_COMMAND",
                    message=f"System command '{clean_line}' found inside G-code job stream."
                ))
                continue

            # Tokenize line into words
            words, parse_err = self._tokenize_words(clean_line, line_idx, raw_line)
            if parse_err:
                issues.extend(parse_err)
                continue

            # Check for modal group conflicts on the same line
            group_conflicts = self._check_modal_conflicts(words, line_idx, raw_line)
            if group_conflicts:
                issues.extend(group_conflicts)

            # Process G and M words on this line
            line_motion_cmd: Optional[str] = None
            line_has_axis: bool = False
            target_x: Optional[float] = None
            target_y: Optional[float] = None
            target_z: Optional[float] = None
            arc_i: Optional[float] = None
            arc_j: Optional[float] = None
            arc_k: Optional[float] = None
            arc_r: Optional[float] = None
            dwell_p: Optional[float] = None

            for letter, val_str, num_val in words:
                word_str = f"{letter}{val_str}"

                # 3D printer Marlin check
                if word_str in self.MARLIN_3D_CODES:
                    laser_mode = getattr(self.settings, "laser_mode", "M4")
                    if word_str in ("M106", "M107") and laser_mode == "M106":
                        pass
                    else:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_20_MARLIN",
                            message=f"Unsupported 3D-printer command '{word_str}' ({self.MARLIN_3D_CODES[word_str]}). "
                                    f"Will cause GRBL error:20."
                        ))
                elif letter == "E":
                    issues.append(ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="GRBL_ERR_20_EXTRUDER",
                        message=f"Extruder motion word 'E{val_str}' detected. GRBL laser controllers do not support extruder axes."
                    ))
                elif letter not in self.VALID_WORDS:
                    issues.append(ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="GRBL_ERR_1",
                        message=f"Invalid or unsupported letter word '{letter}'. GRBL only accepts standard motion words."
                    ))

                # G codes
                if letter == "G":
                    norm_g = f"G{int(num_val)}" if num_val.is_integer() else f"G{num_val}"
                    if norm_g not in self.MODAL_GROUPS_G:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_20",
                            message=f"Unsupported or invalid G-code '{norm_g}'. Will trigger GRBL error:20."
                        ))
                    else:
                        g_group = self.MODAL_GROUPS_G[norm_g]
                        if g_group == 1:  # Motion command
                            cur_motion_mode = norm_g
                            line_motion_cmd = norm_g
                        elif g_group == 2:  # Plane
                            cur_plane = norm_g
                        elif g_group == 3:  # Distance mode
                            cur_distance_mode = norm_g
                        elif g_group == 6:  # Units
                            cur_units = norm_g

                # M codes
                elif letter == "M":
                    norm_m = f"M{int(num_val)}" if num_val.is_integer() else f"M{num_val}"
                    is_m106_laser_mode = getattr(self.settings, "laser_mode", "M4") == "M106"

                    if norm_m in ("M106", "M107") and is_m106_laser_mode:
                        # M106/M107 are legitimate laser control commands when laser_mode == "M106"
                        # M106 = laser ON (equivalent to M3/M4), M107 = laser OFF (equivalent to M5)
                        cur_laser_cmd = norm_m
                        if norm_m == "M106":
                            if cur_s_value > 0:
                                laser_ever_fired = True
                                laser_off_at_end = False
                        elif norm_m == "M107":
                            laser_off_at_end = True
                    elif norm_m not in self.MODAL_GROUPS_M:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_20",
                            message=f"Unsupported M-code '{norm_m}'. Will trigger GRBL error:20."
                        ))
                    else:
                        m_group = self.MODAL_GROUPS_M[norm_m]
                        if m_group == 4:  # Spindle / Laser
                            cur_laser_cmd = norm_m
                            if norm_m in ("M3", "M4"):
                                if cur_s_value > 0:
                                    laser_ever_fired = True
                                    laser_off_at_end = False
                            elif norm_m == "M5":
                                laser_off_at_end = True

                # Feedrate F
                elif letter == "F":
                    if num_val <= 0:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_22",
                            message=f"Feedrate F{num_val} must be strictly positive (F > 0)."
                        ))
                    else:
                        unit_factor = 25.4 if cur_units == "G20" else 1.0
                        cur_feedrate = num_val * unit_factor
                        peak_feedrate = max(peak_feedrate, cur_feedrate)

                # Laser Power S
                elif letter == "S":
                    if num_val < 0:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_25",
                            message=f"Laser power S{num_val} cannot be negative."
                        ))
                    else:
                        cur_s_value = num_val
                        peak_power = max(peak_power, cur_s_value)
                        if cur_s_value > max_power:
                            issues.append(ValidationIssue(
                                line_number=line_idx,
                                line_text=raw_line,
                                severity="warning",
                                error_code="EXCEEDS_MAX_POWER",
                                message=f"Laser power S{cur_s_value:.0f} exceeds configured maximum ($30={max_power}). "
                                        f"GRBL will clamp to max power."
                            ))
                        if cur_s_value > 0 and cur_laser_cmd in ("M3", "M4", "M106"):
                            laser_ever_fired = True
                            laser_off_at_end = False
                        elif cur_s_value == 0:
                            laser_off_at_end = True

                # Coordinates & Arc Parameters
                elif letter == "X":
                    target_x = num_val
                    line_has_axis = True
                elif letter == "Y":
                    target_y = num_val
                    line_has_axis = True
                elif letter == "Z":
                    target_z = num_val
                    line_has_axis = True
                elif letter == "I":
                    arc_i = num_val
                elif letter == "J":
                    arc_j = num_val
                elif letter == "K":
                    arc_k = num_val
                elif letter == "R":
                    arc_r = num_val
                elif letter == "P":
                    dwell_p = num_val

            # Motion Execution Check
            active_motion = line_motion_cmd or (cur_motion_mode if line_has_axis else None)

            if active_motion in ("G0", "G1", "G2", "G3") and line_has_axis:
                motion_count += 1

                # Check feedrate requirement for cutting/feed motion
                if active_motion in ("G1", "G2", "G3"):
                    if cur_feedrate is None or cur_feedrate <= 0:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_22",
                            message=f"Motion move '{active_motion}' attempted before feedrate (F) was defined. "
                                    f"Will trigger GRBL error:22."
                        ))

                # Rapid transit safety check
                if active_motion == "G0":
                    if cur_laser_cmd in ("M3", "M106") and cur_s_value > 0:
                        mode_label = "M3" if cur_laser_cmd == "M3" else "M106"
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="warning",
                            error_code="RAPID_MOVE_BURN_HAZARD",
                            message=f"Rapid move (G0) while constant laser power ({mode_label}, S{cur_s_value:.0f}) is ON. "
                                    f"May burn unintended diagonal lines across workpiece."
                        ))

                # Unit conversion factor
                u = 25.4 if cur_units == "G20" else 1.0

                # Calculate new machine coordinates
                if cur_distance_mode == "G90":  # Absolute
                    new_x = target_x * u if target_x is not None else cur_x
                    new_y = target_y * u if target_y is not None else cur_y
                    new_z = target_z * u if target_z is not None else cur_z
                else:  # G91 Incremental
                    new_x = cur_x + (target_x * u if target_x is not None else 0.0)
                    new_y = cur_y + (target_y * u if target_y is not None else 0.0)
                    new_z = cur_z + (target_z * u if target_z is not None else 0.0)

                # Arc Validation (G2 / G3)
                if active_motion in ("G2", "G3"):
                    arc_err = self._validate_arc(
                        active_motion, cur_plane, cur_x, cur_y, new_x, new_y,
                        arc_i, arc_j, arc_k, arc_r, u, line_idx, raw_line
                    )
                    if arc_err:
                        issues.append(arc_err)

                # Update current position
                cur_x, cur_y, cur_z = new_x, new_y, new_z
                all_x.append(cur_x)
                all_y.append(cur_y)

                # Travel Envelope Boundaries Check
                if (cur_x < -bounds_tolerance or cur_x > w + bounds_tolerance or
                    cur_y < -bounds_tolerance or cur_y > h + bounds_tolerance):
                    issues.append(ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="OUT_OF_BOUNDS",
                        message=f"Target coordinates (X={cur_x:.2f}, Y={cur_y:.2f}) exceed physical workbed bounds "
                                f"[0 to {w:.1f} mm, 0 to {h:.1f} mm]. Will trigger GRBL ALARM:2 (soft limit) or carriage crash."
                    ))

        # Check: Empty Job
        if motion_count == 0:
            issues.append(ValidationIssue(
                line_number=1,
                line_text=raw_lines[0] if raw_lines else "",
                severity="warning",
                error_code="NO_MOTION",
                message="G-Code contains no valid motion commands (G0/G1/G2/G3)."
            ))

        # Check: Laser shutoff safety at end of file
        if laser_ever_fired and not laser_off_at_end:
            issues.append(ValidationIssue(
                line_number=len(raw_lines),
                line_text=raw_lines[-1] if raw_lines else "",
                severity="error",
                error_code="LASER_NOT_SHUT_OFF",
                message="Job does not shut off laser (M5 or S0) before end of program! "
                        "The laser beam would remain powered on after job completion."
            ))

        # Compute Bounding Box
        bbox = (min(all_x), min(all_y), max(all_x), max(all_y))

        # Determine validity:
        # Invalid if there are any errors. If strict mode is enabled, warnings also invalidate.
        has_errs = any(i.severity == "error" for i in issues)
        has_warns = any(i.severity == "warning" for i in issues)
        is_valid = (not has_errs) if not self.strict else (not has_errs and not has_warns)

        return ValidationReport(
            is_valid=is_valid,
            issues=issues,
            total_lines=len(raw_lines),
            motion_count=motion_count,
            bounding_box=bbox,
            max_feedrate=peak_feedrate,
            max_power=peak_power,
            laser_mode=cur_laser_cmd or "M4",
            laser_ever_fired=laser_ever_fired,
            laser_off_at_end=laser_off_at_end
        )

    def _tokenize_words(
        self, clean_line: str, line_idx: int, raw_line: str
    ) -> Tuple[List[Tuple[str, str, float]], List[ValidationIssue]]:
        """
        Tokenizes clean G-code line into (Letter, ValueString, FloatValue) tuples.
        Detects syntax formatting errors, missing numbers, and invalid characters.
        """
        words = []
        issues = []

        pattern = re.compile(r'([A-Za-z%])([+\-]?[0-9]*\.?[0-9]+)?')
        pos = 0

        for match in pattern.finditer(clean_line):
            start, end = match.span()
            gap = clean_line[pos:start].strip()
            if gap:
                issues.append(ValidationIssue(
                    line_number=line_idx,
                    line_text=raw_line,
                    severity="error",
                    error_code="GRBL_ERR_1",
                    message=f"Syntax error: Unexpected character(s) '{gap}' in block. Letter word expected."
                ))

            pos = end
            letter = match.group(1).upper()
            val_str = match.group(2)

            if letter == "%":
                continue

            if val_str is None or val_str == "":
                issues.append(ValidationIssue(
                    line_number=line_idx,
                    line_text=raw_line,
                    severity="error",
                    error_code="GRBL_ERR_2",
                    message=f"Missing numeric value after word '{letter}'. A number format was expected."
                ))
                continue

            try:
                num_val = float(val_str)
                words.append((letter, val_str, num_val))
            except ValueError:
                issues.append(ValidationIssue(
                    line_number=line_idx,
                    line_text=raw_line,
                    severity="error",
                    error_code="GRBL_ERR_2",
                    message=f"Invalid numeric value '{val_str}' for word '{letter}'."
                ))

        trailing = clean_line[pos:].strip()
        if trailing:
            issues.append(ValidationIssue(
                line_number=line_idx,
                line_text=raw_line,
                severity="error",
                error_code="GRBL_ERR_1",
                message=f"Syntax error: Unexpected trailing character(s) '{trailing}' at end of block."
            ))

        return words, issues

    def _check_modal_conflicts(
        self, words: List[Tuple[str, str, float]], line_idx: int, raw_line: str
    ) -> List[ValidationIssue]:
        """
        Detects modal group collisions and duplicate words on the same line (GRBL error:21 and error:25).
        """
        issues = []
        seen_g_groups: Dict[int, str] = {}
        seen_m_groups: Dict[int, str] = {}
        seen_words: Set[str] = set()

        for letter, val_str, num_val in words:
            if letter in ("X", "Y", "Z", "F", "S", "I", "J", "K", "R"):
                if letter in seen_words:
                    issues.append(ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="GRBL_ERR_25",
                        message=f"Duplicate word '{letter}' found in block. GRBL error:25 (Repeated word)."
                    ))
                seen_words.add(letter)

            if letter == "G":
                norm_g = f"G{int(num_val)}" if num_val.is_integer() else f"G{num_val}"
                if norm_g in self.MODAL_GROUPS_G:
                    group = self.MODAL_GROUPS_G[norm_g]
                    if group != 0:
                        if group in seen_g_groups:
                            issues.append(ValidationIssue(
                                line_number=line_idx,
                                line_text=raw_line,
                                severity="error",
                                error_code="GRBL_ERR_21",
                                message=f"Conflicting G-codes '{seen_g_groups[group]}' and '{norm_g}' in modal group {group}. "
                                        f"Will trigger GRBL error:21."
                            ))
                        else:
                            seen_g_groups[group] = norm_g

            elif letter == "M":
                norm_m = f"M{int(num_val)}" if num_val.is_integer() else f"M{num_val}"
                if norm_m in self.MODAL_GROUPS_M:
                    group = self.MODAL_GROUPS_M[norm_m]
                    if group in seen_m_groups:
                        issues.append(ValidationIssue(
                            line_number=line_idx,
                            line_text=raw_line,
                            severity="error",
                            error_code="GRBL_ERR_21",
                            message=f"Conflicting M-codes '{seen_m_groups[group]}' and '{norm_m}' in modal group {group}. "
                                    f"Will trigger GRBL error:21."
                        ))
                    else:
                        seen_m_groups[group] = norm_m

        return issues

    def _validate_arc(
        self,
        motion_cmd: str,
        plane: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        i: Optional[float],
        j: Optional[float],
        k: Optional[float],
        r: Optional[float],
        unit_scale: float,
        line_idx: int,
        raw_line: str
    ) -> Optional[ValidationIssue]:
        """
        Validates circular arc geometric parameters (GRBL error:33 and error:34).
        """
        if plane == "G17":  # XY plane
            if r is not None:
                scaled_r = r * unit_scale
                if scaled_r == 0:
                    return ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="GRBL_ERR_33",
                        message="Arc radius R cannot be zero."
                    )
                chord = math.hypot(x2 - x1, y2 - y1)
                if chord > 2.0 * abs(scaled_r) + 0.005:
                    return ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="GRBL_ERR_33",
                        message=f"Arc target endpoint unreachable with radius R={scaled_r:.3f} "
                                f"(chord {chord:.3f} mm > diameter {2.0 * abs(scaled_r):.3f} mm)."
                    )
            elif i is not None or j is not None:
                off_i = (i or 0.0) * unit_scale
                off_j = (j or 0.0) * unit_scale
                center_x = x1 + off_i
                center_y = y1 + off_j
                radius_start = math.hypot(off_i, off_j)
                radius_end = math.hypot(x2 - center_x, y2 - center_y)
                radius_diff = abs(radius_start - radius_end)

                if radius_diff > 0.005 and (radius_diff / max(0.001, radius_start)) > 0.001:
                    return ValidationIssue(
                        line_number=line_idx,
                        line_text=raw_line,
                        severity="error",
                        error_code="GRBL_ERR_34",
                        message=f"Arc radius mismatch: start radius {radius_start:.3f} mm != end radius {radius_end:.3f} mm "
                                f"(delta {radius_diff:.3f} mm exceeds GRBL 0.005mm tolerance). Will trigger GRBL error:34."
                    )
            else:
                return ValidationIssue(
                    line_number=line_idx,
                    line_text=raw_line,
                    severity="error",
                    error_code="GRBL_ERR_33",
                    message=f"Arc command '{motion_cmd}' missing I/J center offsets or R radius parameter."
                )

        return None

    @classmethod
    def repair_gcode(
        cls,
        gcode_text: str,
        bed_width: float = 400.0,
        bed_height: float = 400.0,
        max_s: int = 1000,
        default_feedrate: float = 1000.0,
        margin_mm: float = 2.0
    ) -> Tuple[str, List[str]]:
        """
        Simulates, inspects, and automatically repairs common G-code issues:
        1. Ensures metric units (G21) and absolute positioning (G90) are initialized.
        2. Translates/strips 3D-printer (Marlin/RepRap) codes (M104, M140, M106, M107, M82, M84, G29, E-words).
        3. Injects missing feedrates (F) on G1/G2/G3 cutting motions.
        4. Clamps negative or out-of-range laser power (S) values to [0, max_s].
        5. Automatically shifts/scales out-of-bounds artwork into safe workbed margins [margin, bed_dim - margin].
        6. Inserts laser shutoff (M5) before G0 rapid moves if laser was burning.
        7. Guarantees safety laser shutoff (M5 S0) and safe return to origin at end of program.
        8. Resolves modal group conflicts on the same line by maintaining valid sequential execution.
        9. Removes repeated axis words on the same line.

        Returns:
            (repaired_gcode_text, list_of_repairs_applied)
        """
        repairs: List[str] = []
        lines = gcode_text.splitlines()

        # Pass 1: Parse absolute coordinates to determine if out-of-bounds shifting/scaling is needed
        cur_x = 0.0
        cur_y = 0.0
        cur_dist_mode = "G90"
        all_x: List[float] = []
        all_y: List[float] = []

        for line in lines:
            c = re.sub(r";.*$", "", line)
            c = re.sub(r"\(.*?\)", "", c).strip()
            if not c:
                continue
            if "G90" in c.upper():
                cur_dist_mode = "G90"
            elif "G91" in c.upper():
                cur_dist_mode = "G91"

            xm = re.search(r"X([+-]?\d+(?:\.\d+)?)", c, re.IGNORECASE)
            ym = re.search(r"Y([+-]?\d+(?:\.\d+)?)", c, re.IGNORECASE)
            if xm:
                vx = float(xm.group(1))
                cur_x = vx if cur_dist_mode == "G90" else cur_x + vx
                all_x.append(cur_x)
            if ym:
                vy = float(ym.group(1))
                cur_y = vy if cur_dist_mode == "G90" else cur_y + vy
                all_y.append(cur_y)

        scale_factor = 1.0
        dx = 0.0
        dy = 0.0
        needs_shift = False

        if all_x and all_y:
            min_x, max_x = min(all_x), max(all_x)
            min_y, max_y = min(all_y), max(all_y)
            job_w = max(0.001, max_x - min_x)
            job_h = max(0.001, max_y - min_y)
            avail_w = max(10.0, bed_width - 2 * margin_mm)
            avail_h = max(10.0, bed_height - 2 * margin_mm)

            if job_w > avail_w or job_h > avail_h:
                scale_factor = min(avail_w / job_w, avail_h / job_h)
                needs_shift = True
                dx = margin_mm - min_x * scale_factor
                dy = margin_mm - min_y * scale_factor
                repairs.append(f"Auto-scaled artwork by {scale_factor*100:.1f}% to fit within physical bed limits")
                repairs.append(f"Shifted artwork by ΔX={dx:+.2f} mm, ΔY={dy:+.2f} mm to margin {margin_mm} mm")
            elif min_x < margin_mm or min_y < margin_mm or max_x > (bed_width - margin_mm) or max_y > (bed_height - margin_mm):
                needs_shift = True
                if min_x < margin_mm:
                    dx = margin_mm - min_x
                elif max_x > (bed_width - margin_mm):
                    dx = (bed_width - margin_mm) - max_x

                if min_y < margin_mm:
                    dy = margin_mm - min_y
                elif max_y > (bed_height - margin_mm):
                    dy = (bed_height - margin_mm) - max_y

                repairs.append(f"Shifted artwork by ΔX={dx:+.2f} mm, ΔY={dy:+.2f} mm into safe bed envelope")

        # Pass 2: Line by line transformation
        output_lines: List[str] = []
        active_motion: Optional[str] = None
        active_feed: Optional[float] = None
        active_laser: str = "M5"
        active_s: float = 0.0
        laser_ever_on: bool = False
        has_g21: bool = False
        has_g90: bool = False

        marlin_drop = {"M104", "M109", "M140", "M190", "M82", "M83", "M84", "G29"}

        for line_idx, line in enumerate(lines, start=1):
            clean = line.strip()
            if not clean:
                continue

            comment = ""
            if ";" in clean:
                clean, comment = clean.split(";", 1)
                comment = ";" + comment
                clean = clean.strip()

            if not clean:
                output_lines.append(comment)
                continue

            # Check for 3D printer commands
            words = clean.split()
            first_word = words[0].upper()

            if any(first_word.startswith(code) for code in marlin_drop):
                repairs.append(f"Removed 3D-printer command '{first_word}' (L{line_idx})")
                continue

            if first_word.startswith("M106"):
                s_match = re.search(r"S([\d.-]+)", clean, re.IGNORECASE)
                s_val = min(max_s, max(0, int(float(s_match.group(1))))) if s_match else max_s
                clean = f"M3 S{s_val}"
                active_laser = "M3"
                active_s = s_val
                laser_ever_on = True
                repairs.append(f"Converted 3D-printer fan M106 to laser M3 S{s_val} (L{line_idx})")
            elif first_word.startswith("M107"):
                clean = "M5 S0"
                active_laser = "M5"
                active_s = 0.0
                repairs.append(f"Converted 3D-printer fan off M107 to laser M5 (L{line_idx})")

            # Strip extruder words E...
            if re.search(r"E[+-]?\d+(?:\.\d+)?", clean, re.IGNORECASE):
                clean = re.sub(r"\s*E[+-]?\d+(?:\.\d+)?", "", clean, flags=re.IGNORECASE).strip()
                repairs.append(f"Stripped extruder word 'E' from motion line (L{line_idx})")

            # Check for G21 / G90
            if "G21" in clean.upper():
                has_g21 = True
            if "G90" in clean.upper():
                has_g90 = True

            # Track motion mode
            gm = re.search(r"\b(G[0-3])\b", clean, re.IGNORECASE)
            if gm:
                active_motion = gm.group(1).upper()

            # Track laser mode
            lm = re.search(r"\b(M[3-5])\b", clean, re.IGNORECASE)
            if lm:
                active_laser = lm.group(1).upper()
                if active_laser in ("M3", "M4"):
                    laser_ever_on = True

            # Check F word
            fm = re.search(r"F([\d.-]+)", clean, re.IGNORECASE)
            if fm:
                try:
                    active_feed = float(fm.group(1))
                except ValueError:
                    pass

            # Check S word and clamp
            sm = re.search(r"S([\d.-]+)", clean, re.IGNORECASE)
            if sm:
                try:
                    raw_s = float(sm.group(1))
                    clamped_s = max(0.0, min(float(max_s), raw_s))
                    active_s = clamped_s
                    if clamped_s != raw_s:
                        repairs.append(f"Clamped laser power S{raw_s:.0f} to S{clamped_s:.0f} (L{line_idx})")
                        clean = re.sub(r"S[\d.-]+", f"S{clamped_s:.0f}", clean, flags=re.IGNORECASE)
                except ValueError:
                    pass

            # Check coordinate shift / scaling
            if needs_shift:
                clean = re.sub(r"X([+-]?\d+(?:\.\d+)?)", lambda m: f"X{float(m.group(1))*scale_factor + dx:.3f}", clean, flags=re.IGNORECASE)
                clean = re.sub(r"Y([+-]?\d+(?:\.\d+)?)", lambda m: f"Y{float(m.group(1))*scale_factor + dy:.3f}", clean, flags=re.IGNORECASE)
                clean = re.sub(r"I([+-]?\d+(?:\.\d+)?)", lambda m: f"I{float(m.group(1))*scale_factor:.3f}", clean, flags=re.IGNORECASE)
                clean = re.sub(r"J([+-]?\d+(?:\.\d+)?)", lambda m: f"J{float(m.group(1))*scale_factor:.3f}", clean, flags=re.IGNORECASE)
                clean = re.sub(r"R([+-]?\d+(?:\.\d+)?)", lambda m: f"R{float(m.group(1))*scale_factor:.3f}", clean, flags=re.IGNORECASE)

            # Check missing feedrate on cutting motion
            is_cutting_move = (active_motion in ("G1", "G2", "G3")) and any(ax in clean.upper() for ax in ("X", "Y", "Z"))
            if is_cutting_move and (active_feed is None or active_feed <= 0) and not re.search(r"F[\d.-]+", clean, re.IGNORECASE):
                clean += f" F{default_feedrate:.0f}"
                active_feed = default_feedrate
                repairs.append(f"Injected missing feedrate F{default_feedrate:.0f} (L{line_idx})")

            # Rapid move G0 with laser on
            if active_motion == "G0" and active_laser in ("M3", "M4") and active_s > 0:
                output_lines.append("M5 S0")
                repairs.append(f"Extinguished laser (M5) before rapid move G0 (L{line_idx})")
                active_laser = "M5"
                active_s = 0.0

            # Modal conflict check: e.g. G0 G1 on same line
            g_codes_on_line = re.findall(r"\b(G\d+\.?\d*)\b", clean, re.IGNORECASE)
            valid_motions = [g for g in g_codes_on_line if g.upper() in ("G0", "G1", "G2", "G3")]
            if len(valid_motions) > 1:
                last_m = valid_motions[-1].upper()
                clean = re.sub(r"\b(G[0-3])\b", "", clean, flags=re.IGNORECASE).strip()
                clean = f"{last_m} {clean}"
                repairs.append(f"Resolved conflicting motion commands to {last_m} (L{line_idx})")

            if clean:
                full_l = f"{clean} {comment}".strip() if comment else clean
                output_lines.append(full_l)

        # Prepend headers if missing
        if not has_g90:
            output_lines.insert(0, "G90")
            repairs.append("Prepended G90 absolute distance mode header")
        if not has_g21:
            output_lines.insert(0, "G21")
            repairs.append("Prepended G21 millimeter units header")

        # Guarantee safety laser shutoff and origin park at end
        last_non_empty = [l.strip() for l in output_lines if l.strip() and not l.strip().startswith(";")]
        if not last_non_empty or not last_non_empty[-1].startswith("M5"):
            output_lines.append("M5 S0")
            output_lines.append("G0 X0 Y0")
            repairs.append("Appended safety laser shutoff (M5 S0) and return to origin at program end")

        repaired_text = "\n".join(output_lines)
        return repaired_text, repairs

    @classmethod
    def simulate_to_job(cls, gcode_text: str, settings: Optional[MachineSettings] = None):
        """
        Parses and simulates any GRBL G-code program string into ToolpathSegment objects,
        calculating cutting distance, rapid travel distance, ETA, and bounding box.
        """
        from laserforge.core.gcode_generator import GCodeJobResult, ToolpathSegment
        from laserforge.config import MachineSettings

        st = settings or MachineSettings()
        rapid_speed = getattr(st, "rapid_speed", 3000.0)
        x_accel = getattr(st, "x_accel", 1000.0)

        cur_x = 0.0
        cur_y = 0.0
        cur_feed = rapid_speed
        cur_s = 0.0
        cur_motion = "G0"
        cur_dist_mode = "G90"
        cur_laser_mode = "M5"

        segments: List[ToolpathSegment] = []
        total_cut = 0.0
        total_rapid = 0.0
        total_time = 0.0
        all_x = [0.0]
        all_y = [0.0]

        max_s = getattr(st, "max_s_value", 1000)

        for line in gcode_text.splitlines():
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("("):
                continue

            clean = re.sub(r";.*$", "", line)
            clean = re.sub(r"\(.*?\)", "", clean).strip()
            if not clean:
                continue

            for gm in re.findall(r"G(\d+\.?\d*)", clean, re.IGNORECASE):
                g_code = f"G{int(float(gm))}"
                if g_code in ("G0", "G1", "G2", "G3"):
                    cur_motion = g_code
                elif g_code in ("G90", "G91"):
                    cur_dist_mode = g_code

            for mm in re.findall(r"M(\d+\.?\d*)", clean, re.IGNORECASE):
                m_code = f"M{int(float(mm))}"
                if m_code in ("M3", "M4", "M5"):
                    cur_laser_mode = m_code

            fm = re.search(r"F([\d.-]+)", clean, re.IGNORECASE)
            if fm:
                try:
                    cur_feed = float(fm.group(1))
                except ValueError:
                    pass

            sm = re.search(r"S([\d.-]+)", clean, re.IGNORECASE)
            if sm:
                try:
                    cur_s = float(sm.group(1))
                except ValueError:
                    pass

            xm = re.search(r"X([\d.-]+)", clean, re.IGNORECASE)
            ym = re.search(r"Y([\d.-]+)", clean, re.IGNORECASE)

            if xm or ym:
                target_x = cur_x
                target_y = cur_y
                if xm:
                    val = float(xm.group(1))
                    target_x = val if cur_dist_mode == "G90" else cur_x + val
                if ym:
                    val = float(ym.group(1))
                    target_y = val if cur_dist_mode == "G90" else cur_y + val

                dist = math.hypot(target_x - cur_x, target_y - cur_y)
                if dist > 0.0001:
                    is_cut = (cur_motion in ("G1", "G2", "G3")) and (cur_laser_mode in ("M3", "M4")) and (cur_s > 0)
                    move_type = "cut" if is_cut else "rapid"
                    power_pct = (cur_s / max(1.0, max_s)) * 100.0 if is_cut else 0.0
                    feed = cur_feed if is_cut else rapid_speed
                    color = "#00e5ff" if is_cut else "#ff5252"

                    segments.append(ToolpathSegment(
                        move_type=move_type,
                        x1=cur_x,
                        y1=cur_y,
                        x2=target_x,
                        y2=target_y,
                        feedrate=feed,
                        power_pct=power_pct,
                        layer_id=0 if is_cut else -1,
                        color=color
                    ))

                    if is_cut:
                        total_cut += dist
                    else:
                        total_rapid += dist

                    t_const = (dist / max(1.0, feed)) * 60.0
                    t_ramp = 2.0 * (feed / 60.0) / max(100.0, x_accel)
                    total_time += max(t_const, t_ramp)

                cur_x = target_x
                cur_y = target_y
                all_x.append(cur_x)
                all_y.append(cur_y)

        bbox = (min(all_x), min(all_y), max(all_x), max(all_y))
        return GCodeJobResult(
            gcode=gcode_text,
            segments=segments,
            total_cut_dist_mm=total_cut,
            total_rapid_dist_mm=total_rapid,
            estimated_time_sec=total_time,
            bounding_box=bbox
        )
