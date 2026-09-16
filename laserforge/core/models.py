"""
LaserForge Core Data Models.
Defines vector shapes, layers, cut settings, and geometric primitives.
"""

from dataclasses import dataclass, field
import math
import uuid
from typing import List, Tuple, Optional, Dict, Any

@dataclass
class LayerCutSettings:
    layer_id: int
    name: str = "C00"
    color: str = "#000000"
    mode: str = "Line"  # "Line", "Fill", "Fill + Line", "Image"
    speed: float = 1000.0  # mm/min
    power_max: float = 80.0  # % (0-100)
    power_min: float = 20.0  # % (0-100)
    passes: int = 1
    z_step: float = 0.0  # mm step down per pass
    line_interval: float = 0.1  # mm spacing for raster fill (~254 DPI)
    fill_angle: float = 0.0  # degrees
    cross_hatch: bool = False
    air_assist: bool = False
    output_enabled: bool = True
    show_on_canvas: bool = True
    overscan_pct: float = 3.0  # % overscan acceleration margin for raster
    is_tool: bool = False  # If true, framing/tool guide layer (not cut)
    pass_delay_sec: float = 0.0  # Seconds to pause between multi-pass cuts for diode cooldown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "name": self.name,
            "color": self.color,
            "mode": self.mode,
            "speed": self.speed,
            "power_max": self.power_max,
            "power_min": self.power_min,
            "passes": self.passes,
            "z_step": self.z_step,
            "line_interval": self.line_interval,
            "fill_angle": self.fill_angle,
            "cross_hatch": self.cross_hatch,
            "air_assist": self.air_assist,
            "output_enabled": self.output_enabled,
            "show_on_canvas": self.show_on_canvas,
            "overscan_pct": self.overscan_pct,
            "is_tool": self.is_tool,
            "pass_delay_sec": self.pass_delay_sec
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LayerCutSettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LaserEntity:
    """Base class for all canvas objects."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    layer_id: int = 0
    name: str = "Shape"
    x: float = 0.0  # Top-left or center in mm
    y: float = 0.0
    rotation: float = 0.0  # Degrees
    selected: bool = False
    locked: bool = False

    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Returns (min_x, min_y, max_x, max_y) in mm."""
        raise NotImplementedError


@dataclass
class RectEntity(LaserEntity):
    width: float = 50.0
    height: float = 30.0
    corner_radius: float = 0.0

    def get_bounds(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class CircleEntity(LaserEntity):
    radius_x: float = 25.0
    radius_y: float = 25.0

    def get_bounds(self) -> Tuple[float, float, float, float]:
        return (self.x - self.radius_x, self.y - self.radius_y,
                self.x + self.radius_x, self.y + self.radius_y)


@dataclass
class LineEntity(LaserEntity):
    x2: float = 50.0
    y2: float = 50.0

    def get_bounds(self) -> Tuple[float, float, float, float]:
        min_x = min(self.x, self.x2)
        min_y = min(self.y, self.y2)
        max_x = max(self.x, self.x2)
        max_y = max(self.y, self.y2)
        return (min_x, min_y, max_x, max_y)


@dataclass
class PathEntity(LaserEntity):
    """General vector path consisting of sub-paths of (x, y) segments."""
    # List of contours, where each contour is a list of (x, y) points relative to (x, y)
    contours: List[List[Tuple[float, float]]] = field(default_factory=list)
    closed: bool = True
    _cached_local_bounds: Optional[Tuple[float, float, float, float]] = field(default=None, repr=False, compare=False)

    def get_local_bounds(self) -> Tuple[float, float, float, float]:
        if self._cached_local_bounds is not None:
            return self._cached_local_bounds
        if not self.contours:
            return (0.0, 0.0, 0.0, 0.0)
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        for c in self.contours:
            for pt in c:
                if pt[0] < min_x: min_x = pt[0]
                if pt[0] > max_x: max_x = pt[0]
                if pt[1] < min_y: min_y = pt[1]
                if pt[1] > max_y: max_y = pt[1]
        if math.isinf(min_x):
            res = (0.0, 0.0, 0.0, 0.0)
        else:
            res = (min_x, min_y, max_x, max_y)
        self._cached_local_bounds = res
        return res

    def get_bounds(self) -> Tuple[float, float, float, float]:
        lx1, ly1, lx2, ly2 = self.get_local_bounds()
        return (self.x + lx1, self.y + ly1, self.x + lx2, self.y + ly2)

    def invalidate_bounds(self):
        self._cached_local_bounds = None


@dataclass
class TextEntity(LaserEntity):
    text: str = "LaserForge"
    font_family: str = "Sans Serif"
    font_size: float = 20.0  # mm
    bold: bool = False
    italic: bool = False
    underline: bool = False
    fill_mode: str = "Fill"  # "Fill" (solid engrave) or "Outline" (vector cut)
    width: float = 60.0
    height: float = 20.0
    is_mirrored_h: bool = False
    is_mirrored_v: bool = False

    def get_bounds(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class ImageEntity(LaserEntity):
    image_path: str = ""
    raw_image_path: str = ""
    processed_image_path: str = ""
    width: float = 80.0   # mm on bed
    height: float = 80.0  # mm on bed
    dither_mode: str = "Floyd-Steinberg"  # "Floyd-Steinberg", "Atkinson", "Threshold", "Grayscale"
    invert: bool = False
    contrast: float = 1.0
    brightness: float = 0.0
    threshold_value: int = 128  # 0-255
    dpi: float = 254.0
    gamma: float = 1.0
    sharpen: float = 0.0
    equalize: bool = False
    white_clip: int = 255
    black_clip: int = 0
    halftone_cell_size: float = 6.0
    halftone_angle_deg: float = 45.0
    is_mirrored_h: bool = False
    is_mirrored_v: bool = False

    def get_bounds(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)
