"""
LaserForge Layer Manager.
Manages color layers, cut parameters, and material presets.
"""

from typing import Dict, List, Optional
from laserforge.config import LAYER_PALETTE
from laserforge.core.models import LayerCutSettings

class LayerManager:
    def __init__(self):
        self.layers: Dict[int, LayerCutSettings] = {}
        self.init_default_layers()

    def init_default_layers(self):
        """Initializes standard LightBurn color layers with default parameters.

        All layers start with conservative safe defaults (1000 mm/min / 30% power).
        Use the Material Library to apply calibrated presets for specific materials.
        """
        for p in LAYER_PALETTE:
            lid = p["id"]
            is_tool = p.get("is_tool", False)
            mode = "Line" if not is_tool else "Tool"

            self.layers[lid] = LayerCutSettings(
                layer_id=lid,
                name=p["name"],
                color=p["color"],
                mode=mode,
                speed=1000.0,
                power_max=30.0,
                power_min=10.0,
                passes=1,
                line_interval=0.085,
                fill_angle=0.0,
                air_assist=False,
                output_enabled=not is_tool,
                show_on_canvas=True,
                is_tool=is_tool
            )

    def get_layer(self, layer_id: int) -> LayerCutSettings:
        if layer_id not in self.layers:
            # Fallback
            self.layers[layer_id] = LayerCutSettings(layer_id=layer_id)
        return self.layers[layer_id]

    def set_layer(self, layer_id: int, settings: LayerCutSettings):
        self.layers[layer_id] = settings

    def get_all_layers(self) -> List[LayerCutSettings]:
        return sorted(self.layers.values(), key=lambda l: l.layer_id)

    def get_color(self, layer_id: int) -> str:
        return self.get_layer(layer_id).color

    def get_active_layers(self, used_layer_ids: List[int]) -> List[LayerCutSettings]:
        """Returns only layers that have shapes on the canvas."""
        return [self.get_layer(lid) for lid in sorted(set(used_layer_ids)) if lid in self.layers]
