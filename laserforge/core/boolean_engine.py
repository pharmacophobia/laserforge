"""
LaserForge 2D Vector Boolean Operations Engine.
Provides CAD boolean operations (Union/Weld, Difference/Subtract, Intersection, XOR)
directly on canvas vector entities using Shapely.
"""

from __future__ import annotations
from typing import List, Tuple, Optional, Any
import math

try:
    from shapely.geometry import Polygon, MultiPolygon, Point, box
    from shapely.ops import unary_union
    import shapely.affinity
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    Polygon = None
    MultiPolygon = None
    Point = None
    box = None
    unary_union = None

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity
)


class BooleanEngine:
    """Performs 2D constructive solid geometry (CSG) operations on LaserEntities."""

    @classmethod
    def entity_to_shapely(cls, entity: LaserEntity) -> Optional[Any]:
        """Converts any 2D LaserEntity into a Shapely Polygon or MultiPolygon."""
        geom = None

        if isinstance(entity, RectEntity):
            if entity.width <= 0 or entity.height <= 0:
                return None
            geom = box(entity.x, entity.y, entity.x + entity.width, entity.y + entity.height)

        elif isinstance(entity, CircleEntity):
            rx = entity.radius_x
            ry = entity.radius_y
            if rx <= 0 or ry <= 0:
                return None
            if abs(rx - ry) < 1e-4:
                geom = Point(entity.x, entity.y).buffer(rx, quad_segs=32)
            else:
                # Ellipse: unit circle scaled by (rx, ry)
                unit_c = Point(0, 0).buffer(1.0, quad_segs=32)
                scaled = shapely.affinity.scale(unit_c, xfact=rx, yfact=ry, origin=(0, 0))
                geom = shapely.affinity.translate(scaled, xoff=entity.x, yoff=entity.y)

        elif isinstance(entity, PathEntity):
            if not entity.contours:
                return None

            # Filter valid contours (at least 3 points)
            valid_contours = [c for c in entity.contours if len(c) >= 3]
            if not valid_contours:
                return None

            # First contour is exterior; subsequent are holes if interior
            exterior = valid_contours[0]
            interiors = valid_contours[1:]
            try:
                geom = Polygon(exterior, interiors)
                if not geom.is_valid:
                    geom = geom.buffer(0)
            except Exception:
                return None

        elif isinstance(entity, LineEntity):
            # 1D line has zero area, cannot participate in 2D area booleans
            return None

        else:
            # Check for generic boundary method
            if hasattr(entity, "get_points"):
                pts = entity.get_points()
                if len(pts) >= 3:
                    try:
                        geom = Polygon(pts).buffer(0)
                    except Exception:
                        return None

        if geom is None or geom.is_empty:
            return None

        # Apply rotation if present
        if getattr(entity, "rotation", 0.0) != 0.0:
            cx, cy = geom.centroid.x, geom.centroid.y
            geom = shapely.affinity.rotate(geom, entity.rotation, origin=(cx, cy))

        return geom

    @classmethod
    def shapely_to_entities(cls, geom: Any, layer_id: int = 0, name_prefix: str = "Boolean") -> List[PathEntity]:
        """Converts a Shapely geometry result back into LaserForge PathEntity objects."""
        if geom is None or geom.is_empty:
            return []

        polygons: List[Polygon] = []
        if isinstance(geom, Polygon):
            polygons.append(geom)
        elif isinstance(geom, MultiPolygon):
            polygons.extend(geom.geoms)
        elif hasattr(geom, "geoms"):
            # GeometryCollection: extract only 2D polygons
            for g in geom.geoms:
                if isinstance(g, Polygon):
                    polygons.append(g)
                elif isinstance(g, MultiPolygon):
                    polygons.extend(g.geoms)

        results: List[PathEntity] = []
        for idx, poly in enumerate(polygons):
            if poly.is_empty:
                continue

            # Ensure polygon is valid and clean
            clean_poly = poly.buffer(0) if not poly.is_valid else poly
            if clean_poly.is_empty:
                continue

            poly_list = [clean_poly] if isinstance(clean_poly, Polygon) else list(clean_poly.geoms)
            for p_idx, p in enumerate(poly_list):
                ext_coords = list(p.exterior.coords)
                # Ensure closed
                if ext_coords and ext_coords[0] != ext_coords[-1]:
                    ext_coords.append(ext_coords[0])

                all_contours = [ext_coords]
                for interior in p.interiors:
                    int_coords = list(interior.coords)
                    if int_coords and int_coords[0] != int_coords[-1]:
                        int_coords.append(int_coords[0])
                    all_contours.append(int_coords)

                ent_name = f"{name_prefix}_{idx + 1}" if len(polygons) > 1 else name_prefix
                min_x, min_y, max_x, max_y = p.bounds
                ent = PathEntity(
                    layer_id=layer_id,
                    name=ent_name,
                    x=min_x,
                    y=min_y,
                    contours=all_contours,
                    closed=True
                )
                results.append(ent)

        return results

    @classmethod
    def union(cls, entities: List[LaserEntity]) -> List[PathEntity]:
        """Welds all selected entities into unified contour(s)."""
        if not entities:
            return []
        geoms = [cls.entity_to_shapely(e) for e in entities]
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        if not geoms:
            return []

        result_geom = unary_union(geoms)
        target_layer = entities[0].layer_id
        return cls.shapely_to_entities(result_geom, layer_id=target_layer, name_prefix="Union")

    @classmethod
    def difference(cls, base_entity: LaserEntity, subtractors: List[LaserEntity]) -> List[PathEntity]:
        """Subtracts all subtractor entities from the base entity."""
        base_geom = cls.entity_to_shapely(base_entity)
        if base_geom is None or base_geom.is_empty:
            return []

        sub_geoms = [cls.entity_to_shapely(e) for e in subtractors]
        sub_geoms = [g for g in sub_geoms if g is not None and not g.is_empty]
        if not sub_geoms:
            return cls.shapely_to_entities(base_geom, layer_id=base_entity.layer_id, name_prefix=base_entity.name)

        combined_sub = unary_union(sub_geoms)
        result_geom = base_geom.difference(combined_sub)
        return cls.shapely_to_entities(result_geom, layer_id=base_entity.layer_id, name_prefix="Difference")

    @classmethod
    def intersection(cls, entities: List[LaserEntity]) -> List[PathEntity]:
        """Finds the common intersecting geometry among all selected entities."""
        if len(entities) < 2:
            return []
        geoms = [cls.entity_to_shapely(e) for e in entities]
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        if len(geoms) < 2:
            return []

        curr = geoms[0]
        for g in geoms[1:]:
            curr = curr.intersection(g)
            if curr.is_empty:
                break

        return cls.shapely_to_entities(curr, layer_id=entities[0].layer_id, name_prefix="Intersection")

    @classmethod
    def xor(cls, entities: List[LaserEntity]) -> List[PathEntity]:
        """Computes the symmetric difference (XOR) among all selected entities."""
        if len(entities) < 2:
            return []
        geoms = [cls.entity_to_shapely(e) for e in entities]
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        if len(geoms) < 2:
            return []

        curr = geoms[0]
        for g in geoms[1:]:
            curr = curr.symmetric_difference(g)

        return cls.shapely_to_entities(curr, layer_id=entities[0].layer_id, name_prefix="XOR")
