"""
LaserForge LightBurn .lbrn2 Export Engine.
Exports LaserForge canvas entities to LightBurn project format (.lbrn2)
for bidirectional compatibility with LightBurn CAM software.
"""

import xml.etree.ElementTree as ET
from typing import List, Optional
from laserforge.core.models import (LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity, LayerCutSettings)
from laserforge.core.layer_manager import LayerManager
from laserforge.config import MachineSettings
import math


class LBRN2Exporter:
    """
    Exports LaserForge projects to LightBurn .lbrn2 XML format.
    Enables round-trip compatibility: LaserForge → LightBurn.
    """

    APP_VERSION = '1.7.00'
    FORMAT_VERSION = '1'

    @classmethod
    def export(cls, entities: List[LaserEntity], layer_manager: LayerManager,
               settings: Optional[MachineSettings] = None) -> str:
        """Exports entities to .lbrn2 XML string."""
        root = ET.Element('LightBurnProject')
        root.set('AppVersion', cls.APP_VERSION)
        root.set('FormatVersion', cls.FORMAT_VERSION)
        root.set('MaterialHeight', '0')
        root.set('MirrorX', 'False')
        root.set('MirrorY', 'False')

        # Export cut settings for each layer
        used_layer_ids = {e.layer_id for e in entities}
        for lid in sorted(used_layer_ids):
            layer = layer_manager.get_layer(lid)
            cls._export_cut_setting(root, layer)

        # Export entities
        for entity in entities:
            layer = layer_manager.get_layer(entity.layer_id)
            if isinstance(entity, RectEntity):
                cls._export_rect(root, entity, layer)
            elif isinstance(entity, CircleEntity):
                cls._export_circle(root, entity, layer)
            elif isinstance(entity, LineEntity):
                cls._export_line(root, entity, layer)
            elif isinstance(entity, PathEntity):
                cls._export_path(root, entity, layer)
            elif isinstance(entity, TextEntity):
                cls._export_text(root, entity, layer)
            elif isinstance(entity, ImageEntity):
                cls._export_image(root, entity, layer)

        ET.indent(root, space='  ')
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='unicode')

    @classmethod
    def save(cls, entities: List[LaserEntity], layer_manager: LayerManager,
             filepath: str, settings: Optional[MachineSettings] = None) -> None:
        """Exports and saves to a .lbrn2 file."""
        xml_str = cls.export(entities, layer_manager, settings)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(xml_str)

    @classmethod
    def _export_cut_setting(cls, parent: ET.Element, layer: LayerCutSettings) -> ET.Element:
        mode_map = {'Line': 'Cut', 'Fill': 'Scan', 'Fill + Line': 'Scan+Cut', 'Image': 'Image'}
        lbrn_type = mode_map.get(layer.mode, 'Cut')
        cs = ET.SubElement(parent, 'CutSetting')
        cs.set('type', lbrn_type)
        cs.set('index', str(layer.layer_id))
        _n(cs, 'index', layer.layer_id)
        _n(cs, 'name', layer.name)
        _n(cs, 'color', layer.color)
        _n(cs, 'maxPower', f'{layer.power_max:.1f}')
        _n(cs, 'minPower', f'{layer.power_min:.1f}')
        _n(cs, 'speed', f'{layer.speed:.1f}')
        _n(cs, 'numPasses', layer.passes)
        _n(cs, 'zStep', f'{layer.z_step:.3f}')
        _n(cs, 'lineInterval', f'{layer.line_interval:.4f}')
        _n(cs, 'enabled', '1' if layer.output_enabled else '0')
        return cs

    @classmethod
    def _export_rect(cls, parent, entity: 'RectEntity', layer):
        s = ET.SubElement(parent, 'Shape')
        s.set('Type', 'Rect')
        s.set('CutIndex', str(entity.layer_id))
        s.set('W', f'{entity.width:.6f}')
        s.set('H', f'{entity.height:.6f}')
        s.set('Cr', f'{entity.corner_radius:.6f}')
        xf = ET.SubElement(s, 'XForm')
        xf.text = f'1 0 0 1 {entity.x + entity.width/2:.6f} {entity.y + entity.height/2:.6f}'
        return s

    @classmethod
    def _export_circle(cls, parent, entity: 'CircleEntity', layer):
        s = ET.SubElement(parent, 'Shape')
        s.set('Type', 'Ellipse')
        s.set('CutIndex', str(entity.layer_id))
        s.set('Rx', f'{entity.radius_x:.6f}')
        s.set('Ry', f'{entity.radius_y:.6f}')
        xf = ET.SubElement(s, 'XForm')
        xf.text = f'1 0 0 1 {entity.x:.6f} {entity.y:.6f}'
        return s

    @classmethod
    def _export_line(cls, parent, entity: 'LineEntity', layer):
        s = ET.SubElement(parent, 'Shape')
        s.set('Type', 'Path')
        s.set('CutIndex', str(entity.layer_id))
        vl = ET.SubElement(s, 'VertList')
        vl.text = f'V{entity.x:.6f},{entity.y:.6f}c0,0 V{entity.x2:.6f},{entity.y2:.6f}c0,0'
        pl = ET.SubElement(s, 'PrimList')
        pl.text = 'L0,1'
        return s

    @classmethod
    def _export_path(cls, parent, entity: 'PathEntity', layer):
        s = ET.SubElement(parent, 'Shape')
        s.set('Type', 'Path')
        s.set('CutIndex', str(entity.layer_id))
        if entity.contours:
            vert_parts = []
            prim_parts = []
            idx = 0
            for contour in entity.contours:
                for pt in contour:
                    wx, wy = entity.x + pt[0], entity.y + pt[1]
                    vert_parts.append(f'V{wx:.6f},{wy:.6f}c0,0')
                n = len(contour)
                for i in range(n - 1):
                    prim_parts.append(f'L{idx+i},{idx+i+1}')
                if entity.closed and n > 2:
                    prim_parts.append(f'L{idx+n-1},{idx}')
                idx += n
            vl = ET.SubElement(s, 'VertList')
            vl.text = ' '.join(vert_parts)
            pl = ET.SubElement(s, 'PrimList')
            pl.text = ' '.join(prim_parts)
        return s

    @classmethod
    def _export_text(cls, parent, entity: 'TextEntity', layer):
        s = ET.SubElement(parent, 'Shape')
        s.set('Type', 'Text')
        s.set('CutIndex', str(entity.layer_id))
        s.set('Str', entity.text)
        s.set('Font', entity.font_family)
        s.set('H', f'{entity.font_size:.6f}')
        s.set('Bold', '1' if entity.bold else '0')
        s.set('Italic', '1' if entity.italic else '0')
        xf = ET.SubElement(s, 'XForm')
        xf.text = f'1 0 0 1 {entity.x:.6f} {entity.y:.6f}'
        return s

    @classmethod
    def _export_image(cls, parent, entity: 'ImageEntity', layer):
        s = ET.SubElement(parent, 'Shape')
        s.set('Type', 'Bitmap')
        s.set('CutIndex', str(entity.layer_id))
        s.set('W', f'{entity.width:.6f}')
        s.set('H', f'{entity.height:.6f}')
        s.set('File', entity.image_path or entity.processed_image_path or '')
        xf = ET.SubElement(s, 'XForm')
        xf.text = f'1 0 0 1 {entity.x + entity.width/2:.6f} {entity.y + entity.height/2:.6f}'
        return s


def _n(parent: ET.Element, tag: str, value) -> ET.Element:
    """Helper: create a child element with text value."""
    el = ET.SubElement(parent, tag)
    el.text = str(value)
    return el
