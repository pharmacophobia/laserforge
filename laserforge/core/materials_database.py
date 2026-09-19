"""
LaserForge 3W Diode Laser Material Database & Test Matrix Engine.
Stores pre-calibrated laser speed/power parameters tuned specifically for 3W blue diode lasers (450nm),
user material persistence, and automated parametric power vs speed test matrix generation.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import json
import os

from laserforge.core.models import (
    LaserEntity, RectEntity, TextEntity, LineEntity
)

MATERIALS_CONFIG_PATH = os.path.expanduser("~/.laserforge_materials.json")


@dataclass
class MaterialProfile:
    id: str
    name: str
    category: str  # "Metal / Card Blanks", "Wood / Veneer", "Paper / Cardstock", "Leather", "Plastics", "Stone"
    operation: str  # "Surface Engrave / Mark", "Vector Cut", "Deep Engrave"
    mode: str = "Fill"  # "Fill", "Line", "Fill + Line"
    speed: float = 1200.0  # mm/min
    power_pct: float = 100.0  # %
    passes: int = 1
    line_interval: float = 0.08  # mm
    pass_delay_sec: float = 0.0  # Cooldown between passes
    air_assist: bool = False
    description: str = ""
    target_3w_laser: bool = True
    laser_type: str = "Diode (450nm)"
    laser_wattage: float = 3.0
    thickness_mm: float = 0.0
    author: str = "LaserForge Community"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MaterialProfile":
        valid_keys = {
            "id", "name", "category", "operation", "mode", "speed",
            "power_pct", "passes", "line_interval", "pass_delay_sec",
            "air_assist", "description", "target_3w_laser",
            "laser_type", "laser_wattage", "thickness_mm", "author"
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


# Pre-calibrated material database specifically optimized for 3W diode lasers (450nm)
DEFAULT_3W_MATERIALS: List[MaterialProfile] = [
    MaterialProfile(
        id="metal_anodized_card",
        name="Anodized Aluminum Business Card (Black / Color)",
        category="Metal / Card Blanks",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=1200.0,
        power_pct=100.0,
        passes=1,
        line_interval=0.08,
        description="Ablates colored dye cleanly revealing brilliant frosted white metal. 3W diode optical sweet spot.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="metal_coated_card",
        name="Coated / Painted Metal Card Blank",
        category="Metal / Card Blanks",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=1000.0,
        power_pct=90.0,
        passes=1,
        line_interval=0.08,
        description="Removes thin polymer coating on metal cards with sharp contrast.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="wood_veneer_card_engrave",
        name="Wood Business Card (0.6 - 1.0mm Birch/Bamboo)",
        category="Wood / Veneer",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=1600.0,
        power_pct=60.0,
        passes=1,
        line_interval=0.10,
        description="Rich dark brown engraving on real wood veneer card blanks without scorching the edges.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="wood_veneer_card_cut",
        name="Wood Business Card Cut (0.6 - 1.0mm Veneer)",
        category="Wood / Veneer",
        operation="Vector Cut",
        mode="Line",
        speed=180.0,
        power_pct=100.0,
        passes=2,
        pass_delay_sec=2.0,
        line_interval=0.10,
        air_assist=True,
        description="Cuts thin wood veneer blanks cleanly. 2 passes at 180 mm/min with 2s diode cooling delay.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="basswood_ply_15_engrave",
        name="Basswood Plywood 1.5 - 2mm (Engrave)",
        category="Wood / Veneer",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=1400.0,
        power_pct=70.0,
        passes=1,
        line_interval=0.10,
        description="Clean, deep brown fill engraving for wooden badges, signs, and box lids.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="basswood_ply_15_cut",
        name="Basswood Plywood 1.5 - 2mm (Cut)",
        category="Wood / Veneer",
        operation="Vector Cut",
        mode="Line",
        speed=120.0,
        power_pct=100.0,
        passes=3,
        pass_delay_sec=3.0,
        line_interval=0.10,
        air_assist=True,
        description="3-pass cutting with 3s inter-pass thermal delay to prevent 3W diode module overheating.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="cardstock_300gsm_cut",
        name="Heavy Kraft Paper / Cardstock (300 gsm)",
        category="Paper / Cardstock",
        operation="Vector Cut",
        mode="Line",
        speed=550.0,
        power_pct=80.0,
        passes=1,
        line_interval=0.10,
        air_assist=True,
        description="Crisp 1-pass cut for custom paper business cards, stencils, and greeting card inserts.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="cardstock_300gsm_engrave",
        name="Heavy Kraft Paper (Surface Engrave)",
        category="Paper / Cardstock",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=2200.0,
        power_pct=30.0,
        passes=1,
        line_interval=0.12,
        description="Subtle dark brown char mark on heavy paper without burning through.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="leather_engrave",
        name="Genuine Leather / Leatherette (Engrave)",
        category="Leather",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=1800.0,
        power_pct=45.0,
        passes=1,
        line_interval=0.10,
        description="High-contrast dark embossed mark on wallet leather, patches, and card cases.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="acrylic_black_engrave",
        name="Black Cast Acrylic 3mm (Surface Frost)",
        category="Plastics",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=1200.0,
        power_pct=60.0,
        passes=1,
        line_interval=0.08,
        description="Uniform matte frosted surface engraving on opaque dark acrylic sheets.",
        target_3w_laser=True
    ),
    MaterialProfile(
        id="slate_coaster_engrave",
        name="Natural Slate Coaster / Plaque",
        category="Stone",
        operation="Surface Engrave / Mark",
        mode="Fill",
        speed=900.0,
        power_pct=100.0,
        passes=1,
        line_interval=0.075,
        description="Fractures microscopic stone surface creating bright white high-contrast photographic marks.",
        target_3w_laser=True
    ),
]


class MaterialDatabase:
    """Manages system and custom material profiles, JSON persistence, and test matrix generation."""

    def __init__(self):
        self.materials: List[MaterialProfile] = []
        self.load()

    def load(self):
        self.materials = list(DEFAULT_3W_MATERIALS)
        if os.path.exists(MATERIALS_CONFIG_PATH):
            try:
                with open(MATERIALS_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                custom_profiles = [MaterialProfile.from_dict(item) if isinstance(item, dict) else item for item in data]
                # Merge or replace existing IDs
                existing_ids = {m.id for m in self.materials}
                for cp in custom_profiles:
                    if cp.id not in existing_ids:
                        self.materials.append(cp)
            except Exception:
                pass

    def save(self):
        try:
            with open(MATERIALS_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump([asdict(m) for m in self.materials], f, indent=2)
        except Exception:
            pass

    def get_all(self) -> List[MaterialProfile]:
        return list(self.materials)

    def get_categories(self) -> List[str]:
        cats = sorted(list({m.category for m in self.materials}))
        return cats

    def get_by_category(self, cat: str) -> List[MaterialProfile]:
        return [m for m in self.materials if m.category == cat]

    def add_material(self, prof: MaterialProfile):
        self.materials.append(prof)
        self.save()

    def delete_material(self, mat_id: str):
        self.materials = [m for m in self.materials if m.id != mat_id]
        self.save()

    @staticmethod
    def generate_test_matrix_entities(
        speeds: List[float],
        powers: List[float],
        swatch_size: float = 8.0,
        spacing: float = 3.0,
        test_type: str = "Fill",  # "Fill", "Line", "Both"
        start_x: float = 30.0,
        start_y: float = 30.0
    ) -> List[LaserEntity]:
        """
        Generates a parametric Power vs Speed test grid directly onto the canvas.
        Columns = Speeds, Rows = Powers.
        Allows testing new materials (e.g. metal card blanks) to find the perfect speed and power in minutes.
        """
        entities: List[LaserEntity] = []

        cols = len(speeds)
        rows = len(powers)

        total_grid_w = cols * (swatch_size + spacing) - spacing
        total_grid_h = rows * (swatch_size + spacing) - spacing

        # Title Label
        entities.append(TextEntity(
            layer_id=0,
            name="TestMatrix_Title",
            x=start_x,
            y=start_y - 12.0,
            width=total_grid_w,
            height=4.5,
            font_size=4.5,
            bold=True,
            text=f"LaserForge 3W Test Matrix ({test_type})"
        ))

        # Column Headers: Speeds across the top
        for c, spd in enumerate(speeds):
            sx = start_x + 18.0 + c * (swatch_size + spacing)
            sy = start_y - 4.0
            entities.append(TextEntity(
                layer_id=0,
                name=f"Col_Speed_{int(spd)}",
                x=sx,
                y=sy,
                width=swatch_size + 4.0,
                height=2.8,
                font_size=2.5,
                text=f"{int(spd)}"
            ))

        # Axis label top: "Speed (mm/min)"
        entities.append(TextEntity(
            layer_id=0,
            name="Axis_Speed",
            x=start_x + 18.0,
            y=start_y - 8.0,
            width=total_grid_w,
            height=2.8,
            font_size=2.8,
            bold=True,
            text="Speed (mm/min) →"
        ))

        # Rows: Powers and swatches
        for r, pwr in enumerate(powers):
            sy = start_y + r * (swatch_size + spacing)

            # Row Header: Power along left side
            entities.append(TextEntity(
                layer_id=0,
                name=f"Row_Power_{int(pwr)}",
                x=start_x,
                y=sy + 2.0,
                width=16.0,
                height=3.0,
                font_size=2.8,
                bold=True,
                text=f"{int(pwr)}%"
            ))

            # Swatches for each column
            for c, spd in enumerate(speeds):
                sx = start_x + 18.0 + c * (swatch_size + spacing)

                # Assign layer ID based on power/speed or use standard
                # Swatches can be RectEntity with fill or cut
                swatch = RectEntity(
                    layer_id=0,
                    name=f"Swatch_S{int(spd)}_P{int(pwr)}",
                    x=sx,
                    y=sy,
                    width=swatch_size,
                    height=swatch_size,
                    corner_radius=0.5,
                    override_speed=float(spd),
                    override_power=float(pwr)
                )
                entities.append(swatch)

                # If test_type is "Both", add inner concentric cut test box
                if test_type == "Both":
                    inner_swatch = RectEntity(
                        layer_id=2,  # Cut layer C02
                        name=f"CutTest_S{int(spd)}_P{int(pwr)}",
                        x=sx + 2.0,
                        y=sy + 2.0,
                        width=swatch_size - 4.0,
                        height=swatch_size - 4.0,
                        corner_radius=0.0,
                        override_speed=float(spd),
                        override_power=float(pwr)
                    )
                    entities.append(inner_swatch)

        # Border around test coupon
        coupon_margin = 4.0
        border_rect = RectEntity(
            layer_id=12,  # T1 Guide
            name="Coupon_Boundary",
            x=start_x - coupon_margin,
            y=start_y - 15.0,
            width=total_grid_w + 22.0 + coupon_margin * 2.0,
            height=total_grid_h + 20.0 + coupon_margin * 2.0,
            corner_radius=3.0
        )
        entities.append(border_rect)

        return entities
