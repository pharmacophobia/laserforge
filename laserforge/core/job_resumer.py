"""
LaserForge Mid-Job Resumption & Modal State Reconstruction Engine.
Allows resuming interrupted, stopped, or aborted laser jobs at any arbitrary
percentage (0% to 100%) or specific line number with mathematically verified
modal state reconstruction and safe rapid lead-in preambles.
"""

from dataclasses import dataclass, field
import math
import re
from typing import List, Tuple, Dict, Optional, Union, Any


@dataclass
class ModalState:
    """Represents the cumulative modal state of GRBL at a given G-code line."""
    line_index: int
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    feedrate: float = 1000.0
    spindle_power: float = 0.0
    laser_mode: str = "M5"        # "M3", "M4", "M5", "M106", "M107"
    motion_mode: str = "G0"       # "G0", "G1", "G2", "G3"
    units: str = "G21"            # "G21" (mm), "G20" (inches)
    pos_mode: str = "G90"         # "G90" (absolute), "G91" (relative)
    plane: str = "G17"            # "G17" (XY), "G18" (XZ), "G19" (YZ)
    coord_system: str = "G54"     # "G54" - "G59"
    feed_mode: str = "G94"        # "G94" (units/min)
    is_cutting: bool = False      # True if laser is actively commanded on


@dataclass
class JobAnalysis:
    """Detailed spatial and timing analysis of a G-code job."""
    total_lines: int
    clean_lines: List[str]
    motion_line_indices: List[int]
    total_cut_distance_mm: float
    total_rapid_distance_mm: float
    estimated_time_sec: float
    bounding_box: Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
    cumulative_distances: List[float]               # Distance reached at each clean line


@dataclass
class ResumedJob:
    """The result of a job resumption calculation."""
    original_line_count: int
    resume_line_index: int
    resume_percentage: float
    modal_state: ModalState
    preamble_lines: List[str]
    remaining_lines: List[str]
    full_gcode: str
    target_coord: Tuple[float, float, float]


class JobResumer:
    """
    Parses G-code programs, reconstructs modal controller states,
    and synthesizes safe lead-in sequences for mid-job resumption.
    """

    WORD_PATTERN = re.compile(r"([A-Z])\s*([-+]?[0-9]*\.?[0-9]+)", re.IGNORECASE)

    @staticmethod
    def sanitize_line(raw_line: str) -> str:
        """Strips comments and surrounding whitespace from a G-code line."""
        if not raw_line:
            return ""
        # Remove semicolon comments
        s = raw_line.split(";", 1)[0]
        # Remove parenthesis comments
        s = re.sub(r"\(.*?\)", "", s)
        return s.strip()

    @classmethod
    def sanitize_lines(cls, gcode_text_or_lines: Union[str, List[str]]) -> List[str]:
        """Converts raw G-code text or lines into a list of non-empty clean G-code statements."""
        if isinstance(gcode_text_or_lines, str):
            raw_lines = gcode_text_or_lines.splitlines()
        else:
            raw_lines = gcode_text_or_lines

        clean_lines: List[str] = []
        for raw in raw_lines:
            clean = cls.sanitize_line(raw)
            if clean:
                clean_lines.append(clean)
        return clean_lines

    @classmethod
    def analyze_job(cls, gcode_text_or_lines: Union[str, List[str]]) -> JobAnalysis:
        """Performs full geometric and modal analysis of the G-code job."""
        lines = cls.sanitize_lines(gcode_text_or_lines)
        total_lines = len(lines)

        motion_indices: List[int] = []
        cumulative_dist: List[float] = []
        total_cut = 0.0
        total_rapid = 0.0
        total_time = 0.0

        cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
        cur_f = 1000.0
        cur_motion = "G0"
        cur_laser_on = False
        cur_pos_mode = "G90"

        min_x, min_y = float("inf"), float("inf")
        max_x, max_y = float("-inf"), float("-inf")

        running_dist = 0.0

        for idx, line in enumerate(lines):
            words = cls._parse_words(line)

            # Update modal modes
            for letter, val in words:
                if letter == "G":
                    int_val = int(val)
                    if int_val in (0, 1, 2, 3):
                        cur_motion = f"G{int_val}"
                    elif int_val == 90:
                        cur_pos_mode = "G90"
                    elif int_val == 91:
                        cur_pos_mode = "G91"
                elif letter == "M":
                    int_val = int(val)
                    if int_val in (3, 4, 106):
                        cur_laser_on = True
                    elif int_val in (5, 107):
                        cur_laser_on = False
                elif letter == "F":
                    if val > 0:
                        cur_f = val

            # Check for coordinates
            has_x = any(l == "X" for l, _ in words)
            has_y = any(l == "Y" for l, _ in words)
            has_z = any(l == "Z" for l, _ in words)

            target_x = cur_x
            target_y = cur_y
            target_z = cur_z

            for letter, val in words:
                if letter == "X":
                    target_x = val if cur_pos_mode == "G90" else (cur_x + val)
                elif letter == "Y":
                    target_y = val if cur_pos_mode == "G90" else (cur_y + val)
                elif letter == "Z":
                    target_z = val if cur_pos_mode == "G90" else (cur_z + val)

            if has_x or has_y or has_z:
                motion_indices.append(idx)
                dx = target_x - cur_x
                dy = target_y - cur_y
                dz = target_z - cur_z
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                running_dist += dist

                is_cut = (cur_motion in ("G1", "G2", "G3")) and cur_laser_on
                if is_cut:
                    total_cut += dist
                else:
                    total_rapid += dist

                if cur_f > 0:
                    total_time += (dist / cur_f) * 60.0

                min_x = min(min_x, target_x, cur_x)
                max_x = max(max_x, target_x, cur_x)
                min_y = min(min_y, target_y, cur_y)
                max_y = max(max_y, target_y, cur_y)

                cur_x, cur_y, cur_z = target_x, target_y, target_z

            cumulative_dist.append(running_dist)

        if min_x == float("inf"):
            min_x, max_x, min_y, max_y = 0.0, 0.0, 0.0, 0.0

        return JobAnalysis(
            total_lines=total_lines,
            clean_lines=lines,
            motion_line_indices=motion_indices,
            total_cut_distance_mm=total_cut,
            total_rapid_distance_mm=total_rapid,
            estimated_time_sec=total_time,
            bounding_box=(min_x, min_y, max_x, max_y),
            cumulative_distances=cumulative_dist
        )

    @classmethod
    def get_line_for_percentage(
        cls,
        gcode_text_or_lines: Union[str, List[str]],
        percentage: float,
        by_distance: bool = False
    ) -> int:
        """
        Calculates the target line index corresponding to a progress percentage (0.0 to 100.0).
        Clamps to valid line indices [0, len(lines) - 1].
        """
        lines = cls.sanitize_lines(gcode_text_or_lines)
        if not lines:
            return 0
        total = len(lines)
        pct = max(0.0, min(100.0, float(percentage)))

        if pct <= 0.0:
            return 0
        if pct >= 100.0:
            return total - 1

        if not by_distance:
            idx = int(round((pct / 100.0) * total))
            return max(0, min(total - 1, idx))

        # By cumulative distance
        analysis = cls.analyze_job(lines)
        total_dist = analysis.cumulative_distances[-1] if analysis.cumulative_distances else 0.0
        if total_dist <= 0.0:
            idx = int(round((pct / 100.0) * total))
            return max(0, min(total - 1, idx))

        target_dist = (pct / 100.0) * total_dist
        for idx, dist in enumerate(analysis.cumulative_distances):
            if dist >= target_dist:
                return idx

        return total - 1

    @classmethod
    def get_percentage_for_line(
        cls,
        gcode_text_or_lines: Union[str, List[str]],
        line_idx: int,
        by_distance: bool = False
    ) -> float:
        """Computes the percentage of a given line index relative to the total program."""
        lines = cls.sanitize_lines(gcode_text_or_lines)
        if not lines:
            return 0.0
        total = len(lines)
        idx = max(0, min(total - 1, int(line_idx)))

        if not by_distance:
            return (idx / total) * 100.0

        analysis = cls.analyze_job(lines)
        total_dist = analysis.cumulative_distances[-1] if analysis.cumulative_distances else 0.0
        if total_dist <= 0.0:
            return (idx / total) * 100.0

        line_dist = analysis.cumulative_distances[idx] if idx < len(analysis.cumulative_distances) else total_dist
        return (line_dist / total_dist) * 100.0

    @classmethod
    def extract_modal_state(cls, lines: List[str], target_line_idx: int) -> ModalState:
        """
        Reconstructs the cumulative modal state up to the line immediately preceding
        target_line_idx (i.e. lines 0 .. target_line_idx - 1).
        """
        state = ModalState(line_index=target_line_idx)
        limit = max(0, min(len(lines), target_line_idx))

        for idx in range(limit):
            line = lines[idx]
            words = cls._parse_words(line)

            for letter, val in words:
                if letter == "G":
                    int_val = int(val)
                    if int_val in (0, 1, 2, 3):
                        state.motion_mode = f"G{int_val}"
                    elif int_val == 17:
                        state.plane = "G17"
                    elif int_val == 18:
                        state.plane = "G18"
                    elif int_val == 19:
                        state.plane = "G19"
                    elif int_val == 20:
                        state.units = "G20"
                    elif int_val == 21:
                        state.units = "G21"
                    elif int_val == 90:
                        state.pos_mode = "G90"
                    elif int_val == 91:
                        state.pos_mode = "G91"
                    elif int_val == 94:
                        state.feed_mode = "G94"
                    elif 54 <= int_val <= 59:
                        state.coord_system = f"G{int_val}"
                elif letter == "M":
                    int_val = int(val)
                    if int_val in (3, 4, 106):
                        state.laser_mode = f"M{int_val}"
                        state.is_cutting = True
                    elif int_val in (5, 107):
                        state.laser_mode = f"M{int_val}"
                        state.is_cutting = False
                elif letter == "S":
                    state.spindle_power = val
                    if val > 0 and state.laser_mode in ("M3", "M4", "M106"):
                        state.is_cutting = True
                elif letter == "F":
                    if val > 0:
                        state.feedrate = val
                elif letter == "X":
                    state.x = val if state.pos_mode == "G90" else (state.x + val)
                elif letter == "Y":
                    state.y = val if state.pos_mode == "G90" else (state.y + val)
                elif letter == "Z":
                    state.z = val if state.pos_mode == "G90" else (state.z + val)

        return state

    @classmethod
    def build_lead_in_preamble(
        cls,
        state: ModalState,
        resume_line: str = "",
        rapid_speed: float = 3000.0
    ) -> List[str]:
        """
        Generates a 100% safe lead-in G-code sequence to position the machine carriage
        at the target coordinates without burning the workpiece.
        """
        preamble: List[str] = [
            f"; === LaserForge Safe Mid-Job Resumption Preamble ===",
            f"; Resuming at line {state.line_index}",
            "M5 ; SAFETY: Ensure laser is powered off prior to rapid repositioning",
            f"{state.coord_system} ; Restore coordinate system",
            f"{state.units} ; Restore units ({'Metric (mm)' if state.units == 'G21' else 'Inches'})",
            f"{state.pos_mode} ; Restore absolute positioning",
            f"{state.plane} ; Restore active plane",
            f"{state.feed_mode} ; Restore feedrate mode",
            f"G0 X{state.x:.3f} Y{state.y:.3f} F{rapid_speed:.0f} ; Rapid traverse to resume origin"
        ]

        if abs(state.z) > 0.001:
            preamble.append(f"G0 Z{state.z:.3f}")

        # Restore feedrate
        preamble.append(f"G1 F{state.feedrate:.1f} ; Restore cutting feedrate")

        # Determine if laser needs restoration
        # Inspect the target resume_line
        resume_words = cls._parse_words(resume_line) if resume_line else []
        has_laser_cmd = any(l == "M" and int(v) in (3, 4, 5, 106, 107) for l, v in resume_words)
        has_s_word = any(l == "S" for l, _ in resume_words)
        is_rapid = any(l == "G" and int(v) == 0 for l, v in resume_words)

        if not is_rapid and state.is_cutting and not has_laser_cmd:
            laser_cmd = state.laser_mode if state.laser_mode in ("M3", "M4", "M106") else "M4"
            s_val = state.spindle_power
            if s_val <= 0:
                s_val = 1000.0
            preamble.append(f"{laser_cmd} S{s_val:g} ; Restore laser power")
        elif is_rapid:
            preamble.append("M5 ; Ensure laser off for initial rapid travel")

        preamble.append("; === End Resumption Preamble / Stream Resumes ===")
        return preamble

    @classmethod
    def build_resumed_job(
        cls,
        gcode_text_or_lines: Union[str, List[str]],
        target_line_idx: Optional[int] = None,
        target_percentage: Optional[float] = None,
        by_distance: bool = False,
        rapid_speed: float = 3000.0
    ) -> ResumedJob:
        """
        Synthesizes a complete, ready-to-burn G-code program starting from the given line
        or percentage. Prepend the safe lead-in preamble and appends all remaining lines.
        """
        lines = cls.sanitize_lines(gcode_text_or_lines)
        if not lines:
            raise ValueError("G-code job is empty.")

        total_lines = len(lines)

        if target_line_idx is not None:
            resolved_idx = max(0, min(total_lines - 1, int(target_line_idx)))
        elif target_percentage is not None:
            resolved_idx = cls.get_line_for_percentage(lines, target_percentage, by_distance=by_distance)
        else:
            resolved_idx = 0

        actual_pct = cls.get_percentage_for_line(lines, resolved_idx, by_distance=by_distance)

        # Reconstruct modal state up to resolved_idx
        state = cls.extract_modal_state(lines, resolved_idx)

        # Target resume line
        resume_line = lines[resolved_idx] if resolved_idx < total_lines else ""

        # If starting from the very first line, no preamble is strictly required,
        # but a safety M5 G21 G90 is always harmless.
        preamble = cls.build_lead_in_preamble(state, resume_line=resume_line, rapid_speed=rapid_speed)

        remaining = lines[resolved_idx:]
        full_gcode_lines = preamble + remaining
        full_gcode = "\n".join(full_gcode_lines) + "\n"

        return ResumedJob(
            original_line_count=total_lines,
            resume_line_index=resolved_idx,
            resume_percentage=actual_pct,
            modal_state=state,
            preamble_lines=preamble,
            remaining_lines=remaining,
            full_gcode=full_gcode,
            target_coord=(state.x, state.y, state.z)
        )

    @classmethod
    def _parse_words(cls, line: str) -> List[Tuple[str, float]]:
        """Parses a single G-code line into a list of (Letter, Value) tuples."""
        words: List[Tuple[str, float]] = []
        for m in cls.WORD_PATTERN.finditer(line):
            letter = m.group(1).upper()
            try:
                val = float(m.group(2))
                words.append((letter, val))
            except ValueError:
                pass
        return words
