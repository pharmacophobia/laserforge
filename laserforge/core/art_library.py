"""
LaserForge Art & Component Library Engine.
Manages reusable vector clip-art, hardware hole cutouts, brackets, latches,
and design components with thumbnail previews, categorization, and drag-and-drop support.
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import os
import uuid
import base64
from typing import List, Dict, Any, Tuple, Optional, Union

from PyQt6.QtCore import Qt, QBuffer, QIODevice, QPointF, QRectF
from PyQt6.QtGui import (
    QImage, QPainter, QColor, QPen, QBrush, QFont, QPainterPath
)

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
)


def render_entities_thumbnail(
    entities: List[LaserEntity],
    width: int = 128,
    height: int = 128,
    bg_color: str = "#1e222b"
) -> str:
    """
    Renders an offscreen antialiased vector thumbnail of the given entities
    scaled and centered into a square preview image, returning a base64-encoded PNG string.
    """
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(bg_color))

    if not entities:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return base64.b64encode(buf.data()).decode("utf-8")

    # Compute bounding box across all entities
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for e in entities:
        bx1, by1, bx2, by2 = e.get_bounds()
        if bx1 < min_x: min_x = bx1
        if by1 < min_y: min_y = by1
        if bx2 > max_x: max_x = bx2
        if by2 > max_y: max_y = by2

    w_mm = max(0.1, max_x - min_x)
    h_mm = max(0.1, max_y - min_y)

    margin = 14.0  # pixels
    drawable_w = width - 2 * margin
    drawable_h = height - 2 * margin

    scale = min(drawable_w / w_mm, drawable_h / h_mm)
    cx_mm = (min_x + max_x) / 2.0
    cy_mm = (min_y + max_y) / 2.0

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    def to_px(x_mm: float, y_mm: float) -> QPointF:
        px = (width / 2.0) + (x_mm - cx_mm) * scale
        py = (height / 2.0) + (y_mm - cy_mm) * scale
        return QPointF(px, py)

    pen_cyan = QPen(QColor("#00e5ff"), 2.0, Qt.PenStyle.SolidLine)
    pen_amber = QPen(QColor("#ffab00"), 1.8, Qt.PenStyle.SolidLine)
    pen_coral = QPen(QColor("#ff5252"), 1.8, Qt.PenStyle.DashLine)

    for e in entities:
        # Assign color by layer or type
        if e.layer_id == 0:
            painter.setPen(pen_cyan)
        elif e.layer_id == 1:
            painter.setPen(pen_amber)
        else:
            painter.setPen(pen_coral)

        painter.setBrush(Qt.BrushStyle.NoBrush)

        if isinstance(e, RectEntity):
            p1 = to_px(e.x, e.y)
            p2 = to_px(e.x + e.width, e.y + e.height)
            rw = abs(p2.x() - p1.x())
            rh = abs(p2.y() - p1.y())
            rx = min(p1.x(), p2.x())
            ry = min(p1.y(), p2.y())
            if e.corner_radius > 0:
                rad_px = e.corner_radius * scale
                painter.drawRoundedRect(QRectF(rx, ry, rw, rh), rad_px, rad_px)
            else:
                painter.drawRect(QRectF(rx, ry, rw, rh))

        elif isinstance(e, CircleEntity):
            center_px = to_px(e.x, e.y)
            r_px_x = e.radius_x * scale
            r_px_y = e.radius_y * scale
            painter.drawEllipse(center_px, r_px_x, r_px_y)

        elif isinstance(e, LineEntity):
            p1 = to_px(e.x, e.y)
            p2 = to_px(e.x2, e.y2)
            painter.drawLine(p1, p2)

        elif isinstance(e, PathEntity):
            for contour in e.contours:
                if not contour:
                    continue
                path = QPainterPath()
                start_p = to_px(e.x + contour[0][0], e.y + contour[0][1])
                path.moveTo(start_p)
                for pt in contour[1:]:
                    path.lineTo(to_px(e.x + pt[0], e.y + pt[1]))
                if e.closed and len(contour) > 2:
                    path.closeSubpath()
                painter.drawPath(path)

        elif isinstance(e, TextEntity):
            p = to_px(e.x, e.y)
            font = QFont(e.font_family, max(8, int(e.font_size * scale * 0.4)))
            font.setBold(e.bold)
            font.setItalic(e.italic)
            painter.setFont(font)
            painter.drawText(int(p.x()), int(p.y() + e.font_size * scale), e.text)

    painter.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(buf.data()).decode("utf-8")


@dataclass
class ArtItem:
    """Individual reusable component or artwork item in a library."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Component"
    category: str = "General"
    tags: List[str] = field(default_factory=list)
    description: str = ""
    width_mm: float = 0.0
    height_mm: float = 0.0
    entities_data: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail_b64: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "tags": self.tags,
            "description": self.description,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "entities_data": self.entities_data,
            "thumbnail_b64": self.thumbnail_b64,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtItem":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "Component"),
            category=data.get("category", "General"),
            tags=data.get("tags", []),
            description=data.get("description", ""),
            width_mm=float(data.get("width_mm", 0.0)),
            height_mm=float(data.get("height_mm", 0.0)),
            entities_data=data.get("entities_data", []),
            thumbnail_b64=data.get("thumbnail_b64", ""),
            created_at=data.get("created_at", datetime.now().isoformat())
        )

    def instantiate_entities(self, target_x: float = 0.0, target_y: float = 0.0, center: bool = True) -> List[LaserEntity]:
        """
        Reconstructs live LaserEntity objects from the stored templates,
        assigns new unique entity IDs, and offsets coordinates to target_x, target_y.
        If center=True, target_x and target_y define the center of the bounding box.
        """
        if not self.entities_data:
            return []

        # Offset calculation
        offset_x = target_x
        offset_y = target_y
        if center:
            offset_x -= self.width_mm / 2.0
            offset_y -= self.height_mm / 2.0

        res: List[LaserEntity] = []
        for d in self.entities_data:
            etype = d.get("type", "RectEntity")
            base_kwargs = {
                "id": str(uuid.uuid4())[:8],
                "layer_id": int(d.get("layer_id", 0)),
                "name": f"{self.name} - {d.get('name', 'Part')}",
                "x": float(d.get("x", 0.0)) + offset_x,
                "y": float(d.get("y", 0.0)) + offset_y,
                "rotation": float(d.get("rotation", 0.0)),
                "locked": bool(d.get("locked", False)),
                "override_speed": float(d["override_speed"]) if d.get("override_speed") is not None else None,
                "override_power": float(d["override_power"]) if d.get("override_power") is not None else None
            }

            if etype == "RectEntity":
                res.append(RectEntity(
                    **base_kwargs,
                    width=float(d.get("width", 10.0)),
                    height=float(d.get("height", 10.0)),
                    corner_radius=float(d.get("corner_radius", 0.0))
                ))
            elif etype == "CircleEntity":
                res.append(CircleEntity(
                    **base_kwargs,
                    radius_x=float(d.get("radius_x", 5.0)),
                    radius_y=float(d.get("radius_y", 5.0))
                ))
            elif etype == "LineEntity":
                res.append(LineEntity(
                    **base_kwargs,
                    x2=float(d.get("x2", 10.0)) + offset_x,
                    y2=float(d.get("y2", 10.0)) + offset_y
                ))
            elif etype == "PathEntity":
                contours = [[(float(pt[0]), float(pt[1])) for pt in c] for c in d.get("contours", [])]
                res.append(PathEntity(
                    **base_kwargs,
                    contours=contours,
                    closed=bool(d.get("closed", True))
                ))
            elif etype == "TextEntity":
                res.append(TextEntity(
                    **base_kwargs,
                    text=str(d.get("text", "Text")),
                    font_family=str(d.get("font_family", "Sans Serif")),
                    font_size=float(d.get("font_size", 10.0)),
                    bold=bool(d.get("bold", False)),
                    italic=bool(d.get("italic", False)),
                    underline=bool(d.get("underline", False)),
                    fill_mode=str(d.get("fill_mode", "Fill")),
                    width=float(d.get("width", 20.0)),
                    height=float(d.get("height", 10.0))
                ))

        return res


class ArtLibrary:
    """A collection of ArtItem objects stored as a single .lflib file."""

    def __init__(self, name: str = "Custom Library", filepath: Optional[str] = None, description: str = ""):
        self.name = name
        self.filepath = filepath or ""
        self.description = description
        self.version = "1.0"
        self.items: Dict[str, ArtItem] = {}

    def add_item_from_entities(
        self,
        name: str,
        entities: List[LaserEntity],
        category: str = "General",
        tags: Optional[List[str]] = None,
        description: str = ""
    ) -> Optional[ArtItem]:
        """
        Creates an ArtItem from canvas entities, normalizes their positions to (0, 0),
        generates a high-quality thumbnail, and adds it to the library.
        """
        if not entities:
            return None

        # Determine total bounds
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")

        for e in entities:
            bx1, by1, bx2, by2 = e.get_bounds()
            if bx1 < min_x: min_x = bx1
            if by1 < min_y: min_y = by1
            if bx2 > max_x: max_x = bx2
            if by2 > max_y: max_y = by2

        w_mm = round(max(0.1, max_x - min_x), 3)
        h_mm = round(max(0.1, max_y - min_y), 3)

        # Generate thumbnail
        thumb_b64 = render_entities_thumbnail(entities)

        # Serialize entities with normalized coordinates (origin at min_x, min_y)
        serialized_entities = []
        for e in entities:
            edata = {
                "type": e.__class__.__name__,
                "layer_id": e.layer_id,
                "name": e.name,
                "x": round(e.x - min_x, 4),
                "y": round(e.y - min_y, 4),
                "rotation": e.rotation,
                "locked": e.locked
            }
            if e.override_speed is not None:
                edata["override_speed"] = float(e.override_speed)
            if e.override_power is not None:
                edata["override_power"] = float(e.override_power)

            if isinstance(e, RectEntity):
                edata.update({
                    "width": e.width,
                    "height": e.height,
                    "corner_radius": e.corner_radius
                })
            elif isinstance(e, CircleEntity):
                edata.update({
                    "radius_x": e.radius_x,
                    "radius_y": e.radius_y
                })
            elif isinstance(e, LineEntity):
                edata.update({
                    "x2": round(e.x2 - min_x, 4),
                    "y2": round(e.y2 - min_y, 4)
                })
            elif isinstance(e, PathEntity):
                edata.update({
                    "contours": e.contours,
                    "closed": e.closed
                })
            elif isinstance(e, TextEntity):
                edata.update({
                    "text": e.text,
                    "font_family": e.font_family,
                    "font_size": e.font_size,
                    "bold": e.bold,
                    "italic": e.italic,
                    "underline": getattr(e, "underline", False),
                    "fill_mode": getattr(e, "fill_mode", "Fill"),
                    "width": e.width,
                    "height": e.height
                })

            serialized_entities.append(edata)

        item = ArtItem(
            name=name,
            category=category or "General",
            tags=tags or [],
            description=description,
            width_mm=w_mm,
            height_mm=h_mm,
            entities_data=serialized_entities,
            thumbnail_b64=thumb_b64
        )

        self.items[item.id] = item
        return item

    def remove_item(self, item_id: str) -> bool:
        if item_id in self.items:
            del self.items[item_id]
            return True
        return False

    def get_item(self, item_id: str) -> Optional[ArtItem]:
        return self.items.get(item_id)

    def filter_items(
        self,
        query: str = "",
        category: str = "",
        tag: str = ""
    ) -> List[ArtItem]:
        """Filters library items matching search keyword, category, or tag."""
        q = query.lower().strip()
        cat = category.strip()
        tg = tag.strip().lower()

        results: List[ArtItem] = []
        for it in self.items.values():
            if cat and cat != "All Categories" and it.category != cat:
                continue
            if tg and not any(tg == t.lower() for t in it.tags):
                continue
            if q:
                match_name = q in it.name.lower()
                match_desc = q in it.description.lower()
                match_tags = any(q in t.lower() for t in it.tags)
                match_cat = q in it.category.lower()
                if not (match_name or match_desc or match_tags or match_cat):
                    continue
            results.append(it)

        # Sort alphabetically by name
        results.sort(key=lambda x: x.name.lower())
        return results

    def get_categories(self) -> List[str]:
        cats = sorted({it.category for it in self.items.values() if it.category})
        return ["All Categories"] + cats

    def get_tags(self) -> List[str]:
        tags = set()
        for it in self.items.values():
            tags.update(it.tags)
        return sorted(tags)

    def save(self, filepath: Optional[str] = None):
        """Saves library to JSON .lflib format."""
        target_path = filepath or self.filepath
        if not target_path:
            raise ValueError("No filepath specified for saving ArtLibrary.")

        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

        payload = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "items": [it.to_dict() for it in self.items.values()]
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        self.filepath = target_path

    @classmethod
    def load(cls, filepath: str) -> "ArtLibrary":
        """Loads an ArtLibrary from a .lflib file."""
        with open(filepath, "r", encoding="utf-8") as f:
            payload = json.load(f)

        lib = cls(
            name=payload.get("name", os.path.splitext(os.path.basename(filepath))[0]),
            filepath=filepath,
            description=payload.get("description", "")
        )
        lib.version = payload.get("version", "1.0")

        for idata in payload.get("items", []):
            item = ArtItem.from_dict(idata)
            lib.items[item.id] = item

        return lib


class ArtLibraryManager:
    """
    Manages active, loaded, and user libraries stored in ~/.laserforge/libraries/.
    Automatically provides built-in Standard Hardware & Laser Components.
    """

    DEFAULT_DIR = os.path.expanduser("~/.laserforge/libraries")

    def __init__(self, libraries_dir: Optional[str] = None):
        self.libraries_dir = libraries_dir or self.DEFAULT_DIR
        os.makedirs(self.libraries_dir, exist_ok=True)
        self.loaded_libraries: Dict[str, ArtLibrary] = {}
        self.active_library_name: str = ""

        # Initialize standard library and scan existing libraries
        self._ensure_standard_library()
        self.scan_libraries()

    def _ensure_standard_library(self):
        """Creates the default Standard Hardware & Cutouts library if it doesn't exist."""
        std_path = os.path.join(self.libraries_dir, "Standard_Hardware.lflib")
        if not os.path.exists(std_path):
            std_lib = create_default_standard_library(std_path)
            std_lib.save()

    def scan_libraries(self):
        """Scans the libraries directory for .lflib files and loads them."""
        if not os.path.exists(self.libraries_dir):
            return

        for fname in sorted(os.listdir(self.libraries_dir)):
            if fname.endswith(".lflib"):
                fpath = os.path.join(self.libraries_dir, fname)
                try:
                    lib = ArtLibrary.load(fpath)
                    self.loaded_libraries[lib.name] = lib
                    if not self.active_library_name:
                        self.active_library_name = lib.name
                except Exception as ex:
                    print(f"Failed to load library {fname}: {ex}")

        # Ensure active library is valid
        if self.loaded_libraries and (not self.active_library_name or self.active_library_name not in self.loaded_libraries):
            self.active_library_name = next(iter(self.loaded_libraries.keys()))

    def get_active_library(self) -> Optional[ArtLibrary]:
        return self.loaded_libraries.get(self.active_library_name)

    def set_active_library(self, name: str) -> bool:
        if name in self.loaded_libraries:
            self.active_library_name = name
            return True
        return False

    def create_new_library(self, name: str, description: str = "") -> ArtLibrary:
        clean_name = name.strip().replace(" ", "_")
        fpath = os.path.join(self.libraries_dir, f"{clean_name}.lflib")
        lib = ArtLibrary(name=name, filepath=fpath, description=description)
        lib.save()
        self.loaded_libraries[name] = lib
        self.active_library_name = name
        return lib

    def load_external_library(self, filepath: str) -> Optional[ArtLibrary]:
        lib = ArtLibrary.load(filepath)
        self.loaded_libraries[lib.name] = lib
        self.active_library_name = lib.name
        return lib

    def unload_library(self, name: str) -> bool:
        if name in self.loaded_libraries:
            del self.loaded_libraries[name]
            if self.active_library_name == name:
                self.active_library_name = next(iter(self.loaded_libraries.keys())) if self.loaded_libraries else ""
            return True
        return False


def create_default_standard_library(filepath: str) -> ArtLibrary:
    """
    Constructs an industrial-grade Standard Hardware & Laser Components library
    containing indispensable laser maker cutouts (M3/M4/M5 holes, keyhole slots,
    earring loops, finger pulls, and registration marks).
    """
    lib = ArtLibrary(
        name="Standard Hardware & Laser Components",
        filepath=filepath,
        description="Built-in collection of precision hardware cutouts, mounting slots, and laser fiducials."
    )

    # 1. M3 Screw Clearance Hole with Head Clearance Marker
    # Center at (0, 0): Inner cutout radius 1.6mm (diameter 3.2mm), outer score 3.0mm (diameter 6.0mm)
    m3_entities = [
        CircleEntity(name="Through Hole (3.2mm)", layer_id=0, x=3.0, y=3.0, radius_x=1.6, radius_y=1.6),
        CircleEntity(name="Head Clearance (6.0mm)", layer_id=1, x=3.0, y=3.0, radius_x=3.0, radius_y=3.0)
    ]
    lib.add_item_from_entities(
        name="M3 Screw Clearance Hole",
        entities=m3_entities,
        category="Fasteners",
        tags=["m3", "screw", "hole", "hardware", "mounting"],
        description="3.2mm through-cut clearance hole with 6.0mm outer head clearance score ring."
    )

    # 2. M4 Screw Clearance Hole
    m4_entities = [
        CircleEntity(name="Through Hole (4.3mm)", layer_id=0, x=4.0, y=4.0, radius_x=2.15, radius_y=2.15),
        CircleEntity(name="Head Clearance (8.0mm)", layer_id=1, x=4.0, y=4.0, radius_x=4.0, radius_y=4.0)
    ]
    lib.add_item_from_entities(
        name="M4 Screw Clearance Hole",
        entities=m4_entities,
        category="Fasteners",
        tags=["m4", "screw", "hole", "hardware", "mounting"],
        description="4.3mm through-cut clearance hole with 8.0mm outer head clearance score ring."
    )

    # 3. M5 Screw Clearance Hole
    m5_entities = [
        CircleEntity(name="Through Hole (5.3mm)", layer_id=0, x=5.0, y=5.0, radius_x=2.65, radius_y=2.65),
        CircleEntity(name="Head Clearance (10.0mm)", layer_id=1, x=5.0, y=5.0, radius_x=5.0, radius_y=5.0)
    ]
    lib.add_item_from_entities(
        name="M5 Screw Clearance Hole",
        entities=m5_entities,
        category="Fasteners",
        tags=["m5", "screw", "hole", "hardware", "mounting"],
        description="5.3mm through-cut clearance hole with 10.0mm outer head clearance score ring."
    )

    # 4. Standard Wall Keyhole Hanger Slot
    # 8.0mm wide entry hole at bottom, narrowing to 4.0mm slot, 15.0mm tall
    keyhole_pts = [
        (-2.0, 0.0), (2.0, 0.0), (2.0, 8.0),
        (4.0, 8.0), (4.0, 15.0), (-4.0, 15.0), (-4.0, 8.0), (-2.0, 8.0)
    ]
    keyhole_entities = [
        PathEntity(name="Keyhole Cutout", layer_id=0, x=4.0, y=0.0, contours=[keyhole_pts], closed=True)
    ]
    lib.add_item_from_entities(
        name="Keyhole Wall Mount Slot",
        entities=keyhole_entities,
        category="Mounts & Hangers",
        tags=["keyhole", "hanger", "wall", "plaque", "sign", "slot"],
        description="Standard 8mm entry / 4mm neck keyhole slot for flush wall-hanging plaques and signs."
    )

    # 5. Oval Cable-Tie Pass-Through Slot (3.5 x 12.0 mm)
    cable_slot = [
        RectEntity(name="Cable Tie Slot", layer_id=0, x=0.0, y=0.0, width=12.0, height=3.5, corner_radius=1.75)
    ]
    lib.add_item_from_entities(
        name="Cable Tie Pass-Through Slot",
        entities=cable_slot,
        category="Fasteners",
        tags=["cable", "zip-tie", "slot", "wire", "management"],
        description="12x3.5mm rounded stadium slot for routing zip-ties and harness cables."
    )

    # 6. Earring / Keychain Loop Tab
    # 8mm round outer tab with 3mm centered hole
    keyring_tab = [
        CircleEntity(name="Outer Tab", layer_id=0, x=4.0, y=4.0, radius_x=4.0, radius_y=4.0),
        CircleEntity(name="Hole", layer_id=0, x=4.0, y=4.0, radius_x=1.5, radius_y=1.5)
    ]
    lib.add_item_from_entities(
        name="Keychain / Earring Loop Tab",
        entities=keyring_tab,
        category="Jewelry & Crafts",
        tags=["keychain", "earring", "loop", "tab", "hole", "ring"],
        description="8mm outer loop tab with 3mm inner hole for jump rings, keyrings, and lanyard cords."
    )

    # 7. Sliding Box Lid Finger Pull Notch (25 x 12.5 mm semi-circular notch)
    notch_pts = []
    # Semi-circle arc
    for deg in range(0, 181, 10):
        rad = deg * 3.14159265 / 180.0
        notch_pts.append((round(12.5 - 12.5 * math.cos(rad), 3), round(12.5 * math.sin(rad), 3)))
    notch_pts.append((0.0, 0.0))
    finger_notch = [
        PathEntity(name="Finger Pull", layer_id=0, x=0.0, y=0.0, contours=[notch_pts], closed=True)
    ]
    lib.add_item_from_entities(
        name="Sliding Box Lid Finger Pull",
        entities=finger_notch,
        category="Boxes & Enclosures",
        tags=["finger", "pull", "box", "lid", "sliding", "notch"],
        description="25mm smooth semi-circular thumb pull cutout for sliding acrylic and wood box lids."
    )

    # 8. Corner Precision L-Fiducial Crosshair
    l_mark = [
        LineEntity(name="L Horizontal", layer_id=1, x=0.0, y=0.0, x2=10.0, y2=0.0),
        LineEntity(name="L Vertical", layer_id=1, x=0.0, y=0.0, x2=0.0, y2=10.0),
        CircleEntity(name="Fiducial Dot", layer_id=1, x=0.0, y=0.0, radius_x=0.5, radius_y=0.5)
    ]
    lib.add_item_from_entities(
        name="90° Corner Alignment Fiducial",
        entities=l_mark,
        category="Calibration & Jigging",
        tags=["fiducial", "crosshair", "alignment", "corner", "jig", "registration"],
        description="10mm 90-degree corner L-marker with center registration pin for jigs and workpiece alignment."
    )

    # 9. Heart Charm Vector
    # Parametric heart path
    heart_pts = []
    for deg in range(0, 360, 10):
        t = deg * 3.14159265 / 180.0
        hx = 16.0 * (math.sin(t) ** 3)
        hy = -(13.0 * math.cos(t) - 5.0 * math.cos(2*t) - 2.0 * math.cos(3*t) - math.cos(4*t))
        # scale down to ~20mm
        heart_pts.append((round(hx * 0.6 + 12.0, 3), round(hy * 0.6 + 12.0, 3)))
    heart_entities = [
        PathEntity(name="Heart Cutout", layer_id=0, x=0.0, y=0.0, contours=[heart_pts], closed=True)
    ]
    lib.add_item_from_entities(
        name="Heart Charm Cutout",
        entities=heart_entities,
        category="Jewelry & Crafts",
        tags=["heart", "charm", "love", "gift", "craft", "jewelry"],
        description="Smooth 24x20mm parametric heart cutout for personalized tags, gifts, and earrings."
    )

    # 10. Star Ornament with Hanging Loop
    star_pts = []
    outer_r = 15.0
    inner_r = 6.0
    for i in range(10):
        ang = (i * 36 - 90) * 3.14159265 / 180.0
        r = outer_r if i % 2 == 0 else inner_r
        star_pts.append((round(15.0 + r * math.cos(ang), 3), round(15.0 + r * math.sin(ang), 3)))
    star_entities = [
        PathEntity(name="Star Perimeter", layer_id=0, x=0.0, y=0.0, contours=[star_pts], closed=True),
        CircleEntity(name="Hanging Hole", layer_id=0, x=15.0, y=3.0, radius_x=1.5, radius_y=1.5)
    ]
    lib.add_item_from_entities(
        name="5-Point Star Ornament Tab",
        entities=star_entities,
        category="Jewelry & Crafts",
        tags=["star", "ornament", "christmas", "holiday", "hanger"],
        description="30mm 5-point decorative star with 3mm integrated ribbon hanging hole."
    )

    return lib
