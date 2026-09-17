"""
LaserForge Interactive CAD Canvas Scene.
Manages vector CAD shapes, interactive creation tools, transformation handles,
and layer color rendering.
"""

from typing import List, Optional, Tuple, Dict, Any
import math
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QLineF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPainterPath, QFont, QFontMetricsF, QPixmap, QImage, QTransform
)
from PyQt6.QtWidgets import (
    QGraphicsScene, QGraphicsItem, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsTextItem, QGraphicsPixmapItem,
    QGraphicsSceneMouseEvent, QGraphicsSceneHoverEvent, QInputDialog
)

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
)
from laserforge.core.layer_manager import LayerManager

TOOL_SELECT = "select"
TOOL_RECT = "rect"
TOOL_CIRCLE = "circle"
TOOL_LINE = "line"
TOOL_TEXT = "text"

class GuideLineItem(QGraphicsLineItem):
    """Visual alignment guide line across the laser workbed."""
    def __init__(self, orientation: str, pos_mm: float, bed_w: float, bed_h: float):
        super().__init__()
        self.orientation = orientation  # "horizontal" or "vertical"
        self.pos_mm = pos_mm
        self.bed_w = bed_w
        self.bed_h = bed_h
        self.setZValue(-50)
        pen = QPen(QColor("#00e5ff"), 1.0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.update_geometry()

    def update_geometry(self):
        if self.orientation == "horizontal":
            self.setLine(0, self.pos_mm, self.bed_w, self.pos_mm)
        else:
            self.setLine(self.pos_mm, 0, self.pos_mm, self.bed_h)


class LaserItemWrapper(QGraphicsItem):
    """Wrapper item for CAD entities with selection bounding box and interactive handles."""
    def __init__(self, entity: LaserEntity, layer_manager: LayerManager):
        super().__init__()
        self.entity = entity
        self.layer_manager = layer_manager
        self._cached_rect: Optional[QRectF] = None
        self._cached_path: Optional[QPainterPath] = None
        self._cached_pixmap: Optional[QPixmap] = None
        self._cached_pixmap_path: Optional[str] = None
        self._resizing_handle: Optional[str] = None
        self._resize_start_scene_pos: QPointF = QPointF()
        self._initial_rect: QRectF = QRectF()
        self._initial_params: Dict[str, Any] = {}

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.sync_from_entity()

    def sync_from_entity(self):
        """Updates QGraphicsItem geometry from internal entity."""
        self.prepareGeometryChange()
        self._cached_rect = None
        self._cached_path = None
        self._cached_pixmap = None
        self._cached_pixmap_path = None
        self.setPos(self.entity.x, self.entity.y)
        if isinstance(self.entity, RectEntity):
            self.setTransformOriginPoint(self.entity.width / 2.0, self.entity.height / 2.0)
        elif isinstance(self.entity, CircleEntity):
            self.setTransformOriginPoint(0.0, 0.0)
        elif isinstance(self.entity, PathEntity):
            lx1, ly1, lx2, ly2 = self.entity.get_local_bounds()
            self.setTransformOriginPoint((lx1 + lx2) / 2.0, (ly1 + ly2) / 2.0)
        elif isinstance(self.entity, (TextEntity, ImageEntity)):
            self.setTransformOriginPoint(self.entity.width / 2.0, self.entity.height / 2.0)
        self.setRotation(self.entity.rotation)
        self.update()

    def sync_to_entity(self):
        """Updates internal entity coordinates from current QGraphicsItem pos."""
        dx = self.pos().x() - self.entity.x
        dy = self.pos().y() - self.entity.y
        if isinstance(self.entity, LineEntity):
            self.entity.x2 += dx
            self.entity.y2 += dy
        self.entity.x = self.pos().x()
        self.entity.y = self.pos().y()
        self.entity.rotation = self.rotation()

    def raw_rect(self) -> QRectF:
        """Returns exact unpadded geometry rectangle."""
        if isinstance(self.entity, RectEntity):
            return QRectF(0, 0, self.entity.width, self.entity.height)
        elif isinstance(self.entity, CircleEntity):
            return QRectF(-self.entity.radius_x, -self.entity.radius_y,
                          self.entity.radius_x * 2, self.entity.radius_y * 2)
        elif isinstance(self.entity, LineEntity):
            dx = self.entity.x2 - self.entity.x
            dy = self.entity.y2 - self.entity.y
            return QRectF(min(0, dx), min(0, dy), max(1.0, abs(dx)), max(1.0, abs(dy)))
        elif isinstance(self.entity, PathEntity):
            lx1, ly1, lx2, ly2 = self.entity.get_local_bounds()
            return QRectF(lx1, ly1, max(0.1, lx2 - lx1), max(0.1, ly2 - ly1))
        elif isinstance(self.entity, TextEntity):
            return QRectF(0, 0, self.entity.width, self.entity.height)
        elif isinstance(self.entity, ImageEntity):
            return QRectF(0, 0, self.entity.width, self.entity.height)
        return QRectF(0, 0, 10, 10)

    def boundingRect(self) -> QRectF:
        if self._cached_rect is None:
            self._cached_rect = self.raw_rect().adjusted(-6.0, -6.0, 6.0, 6.0)
        return self._cached_rect

    def get_handle_positions(self) -> Dict[str, QPointF]:
        r = self.raw_rect().adjusted(-1, -1, 1, 1)
        return {
            "TL": r.topLeft(),
            "TR": r.topRight(),
            "BL": r.bottomLeft(),
            "BR": r.bottomRight(),
            "T": QPointF(r.center().x(), r.top()),
            "B": QPointF(r.center().x(), r.bottom()),
            "L": QPointF(r.left(), r.center().y()),
            "R": QPointF(r.right(), r.center().y()),
        }

    def get_handle_at(self, pos: QPointF) -> Optional[str]:
        handles = self.get_handle_positions()
        threshold = 5.0  # mm in local coords
        for h_id, pt in handles.items():
            if math.hypot(pos.x() - pt.x(), pos.y() - pt.y()) <= threshold:
                return h_id
        return None

    def get_cursor_for_handle(self, handle: str) -> Qt.CursorShape:
        vectors = {
            "R": (1.0, 0.0),
            "BR": (1.0, 1.0),
            "B": (0.0, 1.0),
            "BL": (-1.0, 1.0),
            "L": (-1.0, 0.0),
            "TL": (-1.0, -1.0),
            "T": (0.0, -1.0),
            "TR": (1.0, -1.0),
        }
        vx, vy = vectors.get(handle, (1.0, 0.0))
        angle_deg = (math.degrees(math.atan2(vy, vx)) + self.rotation()) % 180.0
        if 22.5 <= angle_deg < 67.5:
            return Qt.CursorShape.SizeFDiagCursor
        elif 67.5 <= angle_deg < 112.5:
            return Qt.CursorShape.SizeVerCursor
        elif 112.5 <= angle_deg < 157.5:
            return Qt.CursorShape.SizeBDiagCursor
        else:
            return Qt.CursorShape.SizeHorCursor

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        if self.isSelected():
            h = self.get_handle_at(event.pos())
            if h:
                self.setCursor(self.get_cursor_for_handle(h))
                event.accept()
                return
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)

    def _store_resize_initial_state(self):
        ent = self.entity
        self._initial_rect = self.raw_rect()
        if isinstance(ent, RectEntity):
            self._initial_params = {"x": ent.x, "y": ent.y, "w": ent.width, "h": ent.height}
        elif isinstance(ent, CircleEntity):
            self._initial_params = {"x": ent.x, "y": ent.y, "rx": ent.radius_x, "ry": ent.radius_y}
        elif isinstance(ent, TextEntity):
            self._initial_params = {"x": ent.x, "y": ent.y, "w": ent.width, "h": ent.height, "font_size": ent.font_size}
        elif isinstance(ent, ImageEntity):
            self._initial_params = {"x": ent.x, "y": ent.y, "w": ent.width, "h": ent.height}
        elif isinstance(ent, PathEntity):
            self._initial_params = {
                "x": ent.x, "y": ent.y,
                "contours": [[(pt[0], pt[1]) for pt in c] for c in ent.contours],
                "bounds": ent.get_local_bounds()
            }
        elif isinstance(ent, LineEntity):
            self._initial_params = {"x": ent.x, "y": ent.y, "x2": ent.x2, "y2": ent.y2}
        else:
            self._initial_params = {}

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.isSelected():
            handle = self.get_handle_at(event.pos())
            if handle:
                self._resizing_handle = handle
                self._resize_start_scene_pos = event.scenePos()
                self._store_resize_initial_state()
                event.accept()
                return

        self._resizing_handle = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if getattr(self, "_resizing_handle", None):
            handle = self._resizing_handle
            scene_delta = event.scenePos() - self._resize_start_scene_pos
            rad = math.radians(self.entity.rotation)
            dx = scene_delta.x() * math.cos(-rad) - scene_delta.y() * math.sin(-rad)
            dy = scene_delta.x() * math.sin(-rad) + scene_delta.y() * math.cos(-rad)

            init_r = self._initial_rect
            left = init_r.left()
            top = init_r.top()
            right = init_r.right()
            bottom = init_r.bottom()
            init_w = max(0.1, init_r.width())
            init_h = max(0.1, init_r.height())
            min_size = 1.0

            new_left, new_right = left, right
            new_top, new_bottom = top, bottom

            if "R" in handle:
                new_right = max(left + min_size, right + dx)
            if "L" in handle:
                new_left = min(right - min_size, left + dx)
            if "B" in handle:
                new_bottom = max(top + min_size, bottom + dy)
            if "T" in handle:
                new_top = min(bottom - min_size, top + dy)

            # Hold Shift to lock aspect ratio on corners
            keep_aspect = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if keep_aspect and handle in ("TL", "TR", "BL", "BR"):
                aspect = init_w / init_h
                cand_w = new_right - new_left
                cand_h = new_bottom - new_top
                scale = max(cand_w / init_w, cand_h / init_h)
                target_w = init_w * scale
                target_h = init_h * scale

                if handle == "BR":
                    new_right = left + target_w
                    new_bottom = top + target_h
                elif handle == "TL":
                    new_left = right - target_w
                    new_top = bottom - target_h
                elif handle == "TR":
                    new_right = left + target_w
                    new_top = bottom - target_h
                elif handle == "BL":
                    new_left = right - target_w
                    new_bottom = top + target_h

            new_w = max(min_size, new_right - new_left)
            new_h = max(min_size, new_bottom - new_top)

            shift_local_x = new_left - left
            shift_local_y = new_top - top
            scene_shift_x = shift_local_x * math.cos(rad) - shift_local_y * math.sin(rad)
            scene_shift_y = shift_local_x * math.sin(rad) + shift_local_y * math.cos(rad)

            ent = self.entity
            if isinstance(ent, RectEntity):
                ent.x = self._initial_params["x"] + scene_shift_x
                ent.y = self._initial_params["y"] + scene_shift_y
                ent.width = new_w
                ent.height = new_h

            elif isinstance(ent, CircleEntity):
                new_rx = new_w / 2.0
                new_ry = new_h / 2.0
                local_cx = (new_left + new_right) / 2.0
                local_cy = (new_top + new_bottom) / 2.0
                scene_cx = local_cx * math.cos(rad) - local_cy * math.sin(rad)
                scene_cy = local_cx * math.sin(rad) + local_cy * math.cos(rad)
                ent.x = self._initial_params["x"] + scene_cx
                ent.y = self._initial_params["y"] + scene_cy
                ent.radius_x = new_rx
                ent.radius_y = new_ry

            elif isinstance(ent, TextEntity):
                ent.x = self._initial_params["x"] + scene_shift_x
                ent.y = self._initial_params["y"] + scene_shift_y
                ent.width = new_w
                ent.height = new_h
                orig_h = self._initial_params.get("h", 20.0)
                if orig_h > 0:
                    ent.font_size = max(2.0, self._initial_params.get("font_size", 20.0) * (new_h / orig_h))

            elif isinstance(ent, ImageEntity):
                ent.x = self._initial_params["x"] + scene_shift_x
                ent.y = self._initial_params["y"] + scene_shift_y
                ent.width = new_w
                ent.height = new_h

            elif isinstance(ent, PathEntity):
                init_bounds = self._initial_params.get("bounds", (0, 0, 1, 1))
                orig_w = max(0.001, init_bounds[2] - init_bounds[0])
                orig_h = max(0.001, init_bounds[3] - init_bounds[1])
                sx = new_w / orig_w
                sy = new_h / orig_h
                ent.x = self._initial_params["x"] + scene_shift_x
                ent.y = self._initial_params["y"] + scene_shift_y
                new_contours = []
                for c in self._initial_params.get("contours", []):
                    new_c = []
                    for px, py in c:
                        npx = init_bounds[0] + (px - init_bounds[0]) * sx
                        npy = init_bounds[1] + (py - init_bounds[1]) * sy
                        new_c.append((npx, npy))
                    new_contours.append(new_c)
                ent.contours = new_contours
                ent.invalidate_bounds()

            elif isinstance(ent, LineEntity):
                sx = new_w / init_w
                sy = new_h / init_h
                ent.x = self._initial_params["x"] + scene_shift_x
                ent.y = self._initial_params["y"] + scene_shift_y
                orig_dx = self._initial_params["x2"] - self._initial_params["x"]
                orig_dy = self._initial_params["y2"] - self._initial_params["y"]
                ent.x2 = ent.x + orig_dx * sx
                ent.y2 = ent.y + orig_dy * sy

            self.sync_from_entity()
            if self.scene() and hasattr(self.scene(), "entity_modified"):
                self.scene().entity_modified.emit()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            sc = self.scene()
            if getattr(sc, "snap_to_grid", True):
                grid = getattr(sc, "snap_grid_mm", 1.0)
                if grid > 0.05:
                    new_pos = value
                    snapped_x = round(new_pos.x() / grid) * grid
                    snapped_y = round(new_pos.y() / grid) * grid
                    return QPointF(snapped_x, snapped_y)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if getattr(self, "_resizing_handle", None):
            self._resizing_handle = None
            self.setCursor(Qt.CursorShape.SizeAllCursor if self.isSelected() else Qt.CursorShape.ArrowCursor)
            if self.scene() and hasattr(self.scene(), "entity_modified"):
                self.scene().entity_modified.emit()
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self.sync_to_entity()
        if self.scene() and hasattr(self.scene(), "entity_modified"):
            self.scene().entity_modified.emit()

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and isinstance(self.entity, TextEntity):
            sc = self.scene()
            parent_w = sc.views()[0] if sc and sc.views() else None
            new_text, ok = QInputDialog.getText(
                parent_w, "Edit Text Content",
                "Enter text to engrave / cut:",
                text=self.entity.text
            )
            if ok and new_text != self.entity.text:
                if sc and hasattr(sc, "push_undo_state"):
                    sc.push_undo_state()
                self.entity.text = new_text
                font = QFont(self.entity.font_family, max(4, int(round(self.entity.font_size * 2))))
                fm = QFontMetricsF(font)
                tw = max(10.0, fm.horizontalAdvance(new_text) + 6.0)
                self.entity.width = max(self.entity.width, tw)
                self.sync_from_entity()
                if sc and hasattr(sc, "entity_modified"):
                    sc.entity_modified.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paint(self, painter: QPainter, option, widget=None):
        layer = self.layer_manager.get_layer(self.entity.layer_id)
        color = QColor(layer.color)

        pen = QPen(color, 1.2)
        pen.setCosmetic(True)  # Keeps line crisp regardless of zoom
        painter.setPen(pen)

        # Fill preview if in fill mode
        brush = QBrush(Qt.BrushStyle.NoBrush)
        if layer.mode in ("Fill", "Fill + Line"):
            brush_color = QColor(color)
            brush_color.setAlpha(40)
            brush = QBrush(brush_color)
        painter.setBrush(brush)

        rect = self.raw_rect()

        if isinstance(self.entity, RectEntity):
            if self.entity.corner_radius > 0:
                painter.drawRoundedRect(rect, self.entity.corner_radius, self.entity.corner_radius)
            else:
                painter.drawRect(rect)

        elif isinstance(self.entity, CircleEntity):
            painter.drawEllipse(rect)

        elif isinstance(self.entity, LineEntity):
            dx = self.entity.x2 - self.entity.x
            dy = self.entity.y2 - self.entity.y
            painter.drawLine(QPointF(0, 0), QPointF(dx, dy))

        elif isinstance(self.entity, PathEntity):
            if self._cached_path is None:
                ppath = QPainterPath()
                for contour in self.entity.contours:
                    if not contour: continue
                    ppath.moveTo(contour[0][0], contour[0][1])
                    for pt in contour[1:]:
                        ppath.lineTo(pt[0], pt[1])
                    if self.entity.closed:
                        ppath.closeSubpath()
                self._cached_path = ppath
            painter.drawPath(self._cached_path)

        elif isinstance(self.entity, TextEntity):
            painter.save()
            m_h = getattr(self.entity, "is_mirrored_h", False)
            m_v = getattr(self.entity, "is_mirrored_v", False)
            if m_h or m_v:
                cx = rect.width() / 2.0
                cy = rect.height() / 2.0
                painter.translate(cx, cy)
                painter.scale(-1.0 if m_h else 1.0, -1.0 if m_v else 1.0)
                painter.translate(-cx, -cy)

            font = QFont(self.entity.font_family, max(4, int(round(self.entity.font_size * 2))))
            font.setBold(self.entity.bold)
            font.setItalic(self.entity.italic)
            font.setUnderline(getattr(self.entity, "underline", False))

            fill_mode = getattr(self.entity, "fill_mode", "Fill")
            if fill_mode == "Outline":
                # Clean vector outline cut preview
                fm = QFontMetricsF(font)
                ppath = QPainterPath()
                y_offset = rect.top() + (rect.height() - fm.height()) / 2.0 + fm.ascent()
                ppath.addText(QPointF(rect.left(), y_offset), font, self.entity.text)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(ppath)
            else:
                # Solid engraving preview
                painter.setFont(font)
                painter.setPen(pen)
                painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.entity.text)
            painter.restore()

        elif isinstance(self.entity, ImageEntity):
            painter.save()
            m_h = getattr(self.entity, "is_mirrored_h", False)
            m_v = getattr(self.entity, "is_mirrored_v", False)
            if m_h or m_v:
                cx = rect.width() / 2.0
                cy = rect.height() / 2.0
                painter.translate(cx, cy)
                painter.scale(-1.0 if m_h else 1.0, -1.0 if m_v else 1.0)
                painter.translate(-cx, -cy)

            display_path = getattr(self.entity, "processed_image_path", "") or self.entity.image_path
            if display_path:
                if self._cached_pixmap is None or self._cached_pixmap_path != display_path:
                    pix = QPixmap(display_path)
                    if pix.isNull():
                        try:
                            from PIL import Image as PILImg
                            with PILImg.open(display_path) as p_img:
                                rgba = p_img.convert("RGBA")
                                qimg = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
                                pix = QPixmap.fromImage(qimg)
                        except Exception:
                            pix = QPixmap()
                    self._cached_pixmap = pix
                    self._cached_pixmap_path = display_path
                if self._cached_pixmap and not self._cached_pixmap.isNull():
                    painter.drawPixmap(rect, self._cached_pixmap, QRectF(self._cached_pixmap.rect()))
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.restore()

        # Draw selection box and resize handles if selected
        if self.isSelected():
            painter.setPen(QPen(QColor("#00d4ff"), 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = rect.adjusted(-1, -1, 1, 1)
            painter.drawRect(sel_rect)

            # Draw 8 resize handles
            handle_color = QColor("#00d4ff")
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.setBrush(QBrush(handle_color))
            handles = self.get_handle_positions()
            for h_id, pt in handles.items():
                painter.drawRect(QRectF(pt.x() - 2.5, pt.y() - 2.5, 5, 5))


class LaserCanvasScene(QGraphicsScene):
    selection_changed = pyqtSignal()
    entity_modified = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, layer_manager: LayerManager, parent=None):
        super().__init__(parent)
        self.layer_manager = layer_manager
        self.active_tool = TOOL_SELECT
        self.active_layer_id = 0
        self.snap_grid_mm = 1.0  # Snap grid in mm (0 for off)
        self.snap_to_grid = True
        self.guides: List[GuideLineItem] = []
        self.show_guides = True
        self.bed_width = 400.0
        self.bed_height = 400.0

        # Drawing state
        self._drawing = False
        self._draw_start = QPointF()
        self._temp_item: Optional[QGraphicsItem] = None

        # Undo / Redo stacks
        self._undo_stack: List[List[LaserEntity]] = []
        self._redo_stack: List[List[LaserEntity]] = []
        self._max_undo_steps = 50

        # Camera Bed Background Overlay Item
        self._camera_overlay_item = QGraphicsPixmapItem()
        self._camera_overlay_item.setZValue(-100)
        self._camera_overlay_item.setOpacity(0.55)
        self._camera_overlay_item.setVisible(False)
        self._camera_overlay_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._camera_overlay_item.setEnabled(False)
        self.addItem(self._camera_overlay_item)

        self.selectionChanged.connect(self._on_selection_changed)

    def set_camera_overlay_pixmap(self, pixmap: QPixmap, bed_width: float, bed_height: float):
        """Sets the rectified top-down orthophoto onto the laser bed at exact millimeter scale."""
        if pixmap.isNull():
            return
        self._camera_overlay_item.setPixmap(pixmap)
        scale_x = max(1.0, bed_width) / max(1.0, float(pixmap.width()))
        scale_y = max(1.0, bed_height) / max(1.0, float(pixmap.height()))
        t = QTransform()
        t.scale(scale_x, scale_y)
        self._camera_overlay_item.setTransform(t)
        self._camera_overlay_item.setPos(0.0, 0.0)
        self._camera_overlay_item.setVisible(True)
        self.update()

    def set_camera_overlay_visible(self, visible: bool):
        self._camera_overlay_item.setVisible(visible)
        self.update()

    def set_camera_overlay_opacity(self, opacity: float):
        self._camera_overlay_item.setOpacity(max(0.0, min(1.0, opacity)))
        self.update()

    def set_active_tool(self, tool: str):
        self.active_tool = tool
        self.clearSelection()

    def add_guide(self, orientation: str, pos_mm: float):
        """Adds horizontal or vertical alignment guide line at specified millimeter position."""
        guide = GuideLineItem(orientation, pos_mm, self.bed_width, self.bed_height)
        guide.setVisible(self.show_guides)
        self.guides.append(guide)
        self.addItem(guide)
        self.update()

    def clear_guides(self):
        """Removes all alignment guide lines from the canvas."""
        for g in self.guides:
            self.removeItem(g)
        self.guides.clear()
        self.update()

    def set_guides_visible(self, visible: bool):
        """Toggles visibility of alignment guide lines."""
        self.show_guides = visible
        for g in self.guides:
            g.setVisible(visible)
        self.update()

    def set_snap_to_grid(self, enabled: bool, grid_size: float = 1.0):
        """Enables or disables automatic grid snapping."""
        self.snap_to_grid = enabled
        self.snap_grid_mm = grid_size if enabled else 0.0

    def set_active_layer(self, layer_id: int):
        self.active_layer_id = layer_id
        # Also assign selected shapes to this layer if any
        selected = self.get_selected_entities()
        if selected:
            for e in selected:
                e.layer_id = layer_id
            self.update()
            self.entity_modified.emit()

    def snap_value(self, val: float) -> float:
        if self.snap_grid_mm <= 0:
            return val
        return round(val / self.snap_grid_mm) * self.snap_grid_mm

    def add_entity(self, entity: LaserEntity) -> LaserItemWrapper:
        wrapper = LaserItemWrapper(entity, self.layer_manager)
        self.addItem(wrapper)
        self.entity_modified.emit()
        return wrapper

    def get_all_entities(self) -> List[LaserEntity]:
        entities = []
        for item in self.items():
            if isinstance(item, LaserItemWrapper):
                item.sync_to_entity()
                entities.append(item.entity)
        return entities

    def get_selected_entities(self) -> List[LaserEntity]:
        selected = []
        for item in self.selectedItems():
            if isinstance(item, LaserItemWrapper):
                item.sync_to_entity()
                selected.append(item.entity)
        return selected

    def clear_entities(self):
        for item in list(self.items()):
            if isinstance(item, LaserItemWrapper):
                self.removeItem(item)
        self.entity_modified.emit()

    def push_undo_state(self):
        """Snapshots current entity list for multi-level Undo."""
        import copy
        current_entities = copy.deepcopy(self.get_all_entities())
        self._undo_stack.append(current_entities)
        if len(self._undo_stack) > self._max_undo_steps:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        """Restores the previous canvas state."""
        if not self._undo_stack:
            self.status_message.emit("Nothing to undo")
            return
        import copy
        current_entities = copy.deepcopy(self.get_all_entities())
        self._redo_stack.append(current_entities)

        prev_entities = self._undo_stack.pop()
        self._restore_entities(prev_entities)
        self.status_message.emit("Undo performed")

    def redo(self):
        """Re-applies the previously undone canvas state."""
        if not self._redo_stack:
            self.status_message.emit("Nothing to redo")
            return
        import copy
        current_entities = copy.deepcopy(self.get_all_entities())
        self._undo_stack.append(current_entities)

        next_entities = self._redo_stack.pop()
        self._restore_entities(next_entities)
        self.status_message.emit("Redo performed")

    def _restore_entities(self, entities: List[LaserEntity]):
        self.clearSelection()
        for item in list(self.items()):
            if isinstance(item, LaserItemWrapper):
                self.removeItem(item)
        for ent in entities:
            wrapper = LaserItemWrapper(ent, self.layer_manager)
            self.addItem(wrapper)
        self.update()
        self.entity_modified.emit()

    def boolean_operation(self, mode: str) -> bool:
        """
        Executes a vector boolean operation on currently selected shapes.
        mode: 'weld' (union), 'subtract' (difference), 'intersect' (intersection)
        """
        from laserforge.core.boolean_engine import BooleanEngine

        selected_items = [i for i in self.selectedItems() if isinstance(i, LaserItemWrapper)]
        if len(selected_items) < 2:
            self.status_message.emit("Please select at least 2 vector shapes for Boolean operations")
            return False

        for item in selected_items:
            item.sync_to_entity()

        entities = [item.entity for item in selected_items]

        # Push undo before executing boolean operation
        self.push_undo_state()

        result_entities = []
        if mode in ("weld", "union"):
            result_entities = BooleanEngine.union(entities)
        elif mode in ("subtract", "difference"):
            result_entities = BooleanEngine.difference(entities[0], entities[1:])
        elif mode == "intersect":
            result_entities = BooleanEngine.intersection(entities)
        elif mode in ("xor", "symdiff"):
            result_entities = BooleanEngine.xor(entities)

        if not result_entities:
            self.status_message.emit(f"Boolean {mode} resulted in no overlapping or valid geometry")
            return False

        # Remove source items from scene
        for item in selected_items:
            self.removeItem(item)

        # Add new unified path item(s)
        self.clearSelection()
        for rent in result_entities:
            new_wrapper = self.add_entity(rent)
            new_wrapper.setSelected(True)

        self.update()
        self.entity_modified.emit()
        self.status_message.emit(f"Vector {mode.capitalize()} complete: created {len(result_entities)} shape(s)")
        return True

    def delete_selected(self):
        items_to_del = [item for item in self.selectedItems() if isinstance(item, LaserItemWrapper)]
        if not items_to_del:
            return
        self.push_undo_state()
        for item in items_to_del:
            self.removeItem(item)
        self.entity_modified.emit()

    def duplicate_selected(self):
        selected = self.get_selected_entities()
        if not selected:
            return
        self.push_undo_state()
        self.clearSelection()
        for e in selected:
            # Clone with 5mm offset
            new_ent = None
            if isinstance(e, RectEntity):
                new_ent = RectEntity(layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5, width=e.width, height=e.height, corner_radius=e.corner_radius)
            elif isinstance(e, CircleEntity):
                new_ent = CircleEntity(layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5, radius_x=e.radius_x, radius_y=e.radius_y)
            elif isinstance(e, LineEntity):
                new_ent = LineEntity(layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5, x2=e.x2+5, y2=e.y2+5)
            elif isinstance(e, TextEntity):
                new_ent = TextEntity(
                    layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5,
                    text=e.text, font_family=e.font_family, font_size=e.font_size,
                    bold=e.bold, italic=e.italic, underline=getattr(e, "underline", False),
                    fill_mode=getattr(e, "fill_mode", "Fill"),
                    width=e.width, height=e.height
                )
            elif isinstance(e, PathEntity):
                new_contours = [list(c) for c in e.contours]
                new_ent = PathEntity(layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5, contours=new_contours, closed=e.closed)
            elif isinstance(e, ImageEntity):
                new_ent = ImageEntity(
                    layer_id=e.layer_id, name=f"{e.name}_copy", x=e.x+5, y=e.y+5,
                    width=e.width, height=e.height, image_path=e.image_path,
                    dither_mode=e.dither_mode, invert=e.invert, contrast=e.contrast,
                    brightness=e.brightness, threshold_value=e.threshold_value, dpi=e.dpi
                )

            if new_ent:
                wrapper = self.add_entity(new_ent)
                wrapper.setSelected(True)

    def align_selected(self, mode: str, bed_width: float = 150.0, bed_height: float = 200.0):
        """
        Aligns, centers, or distributes selected items.
        Modes: 'left', 'center_x', 'right', 'top', 'center_y', 'bottom',
               'bed_center', 'center_in_parent', 'distribute_h', 'distribute_v'
        """
        selected_items = [i for i in self.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            return

        self.push_undo_state()

        for item in selected_items:
            item.sync_to_entity()

        if mode == "bed_center":
            boxes = [i.entity.get_bounds() for i in selected_items]
            min_x = min(b[0] for b in boxes)
            max_x = max(b[2] for b in boxes)
            min_y = min(b[1] for b in boxes)
            max_y = max(b[3] for b in boxes)
            curr_cx = (min_x + max_x) / 2.0
            curr_cy = (min_y + max_y) / 2.0
            dx = (bed_width / 2.0) - curr_cx
            dy = (bed_height / 2.0) - curr_cy
            for item in selected_items:
                item.entity.x += dx
                item.entity.y += dy
                item.sync_from_entity()
            self.entity_modified.emit()
            return

        if mode == "center_in_parent" and len(selected_items) >= 2:
            def get_area(item):
                b = item.entity.get_bounds()
                return (b[2] - b[0]) * (b[3] - b[1])
            sorted_items = sorted(selected_items, key=get_area, reverse=True)
            parent_box = sorted_items[0].entity.get_bounds()
            parent_cx = (parent_box[0] + parent_box[2]) / 2.0
            parent_cy = (parent_box[1] + parent_box[3]) / 2.0
            for item in sorted_items[1:]:
                b = item.entity.get_bounds()
                item_cx = (b[0] + b[2]) / 2.0
                item_cy = (b[1] + b[3]) / 2.0
                item.entity.x += (parent_cx - item_cx)
                item.entity.y += (parent_cy - item_cy)
                item.sync_from_entity()
            self.entity_modified.emit()
            return

        if mode in ("distribute_h", "distribute_v") and len(selected_items) >= 3:
            if mode == "distribute_h":
                sorted_items = sorted(selected_items, key=lambda it: it.entity.get_bounds()[0])
                first_b = sorted_items[0].entity.get_bounds()
                last_b = sorted_items[-1].entity.get_bounds()
                total_span = last_b[0] - first_b[0]
                step = total_span / (len(sorted_items) - 1)
                for idx, item in enumerate(sorted_items[1:-1], start=1):
                    target_x = first_b[0] + idx * step
                    b = item.entity.get_bounds()
                    item.entity.x += (target_x - b[0])
                    item.sync_from_entity()
            else:
                sorted_items = sorted(selected_items, key=lambda it: it.entity.get_bounds()[1])
                first_b = sorted_items[0].entity.get_bounds()
                last_b = sorted_items[-1].entity.get_bounds()
                total_span = last_b[1] - first_b[1]
                step = total_span / (len(sorted_items) - 1)
                for idx, item in enumerate(sorted_items[1:-1], start=1):
                    target_y = first_b[1] + idx * step
                    b = item.entity.get_bounds()
                    item.entity.y += (target_y - b[1])
                    item.sync_from_entity()
            self.entity_modified.emit()
            return

        if len(selected_items) >= 2:
            boxes = [i.entity.get_bounds() for i in selected_items]
            min_x = min(b[0] for b in boxes)
            max_x = max(b[2] for b in boxes)
            min_y = min(b[1] for b in boxes)
            max_y = max(b[3] for b in boxes)
            center_x = (min_x + max_x) / 2.0
            center_y = (min_y + max_y) / 2.0

            for item in selected_items:
                b = item.entity.get_bounds()
                w = b[2] - b[0]
                h = b[3] - b[1]
                if mode == "left":
                    item.entity.x += (min_x - b[0])
                elif mode == "right":
                    item.entity.x += (max_x - b[2])
                elif mode == "center_x":
                    item.entity.x += (center_x - (b[0] + w / 2.0))
                elif mode == "top":
                    item.entity.y += (min_y - b[1])
                elif mode == "bottom":
                    item.entity.y += (max_y - b[3])
                elif mode == "center_y":
                    item.entity.y += (center_y - (b[1] + h / 2.0))
                item.sync_from_entity()
            self.entity_modified.emit()

    def flip_selected(self, horizontal: bool = True):
        """Flips selected entities horizontally or vertically across their collective center."""
        selected_items = [i for i in self.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_items:
            return

        self.push_undo_state()

        for item in selected_items:
            item.sync_to_entity()

        all_bounds = [item.entity.get_bounds() for item in selected_items]
        min_x = min(b[0] for b in all_bounds)
        max_x = max(b[2] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_y = max(b[3] for b in all_bounds)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0

        for item in selected_items:
            e = item.entity
            if horizontal:
                if isinstance(e, (TextEntity, ImageEntity)):
                    e.is_mirrored_h = not getattr(e, "is_mirrored_h", False)
                    e.x = 2.0 * center_x - (e.x + e.width)
                elif isinstance(e, RectEntity):
                    e.x = 2.0 * center_x - (e.x + e.width)
                    e.rotation = -e.rotation
                elif isinstance(e, CircleEntity):
                    e.x = 2.0 * center_x - e.x
                    e.rotation = -e.rotation
                elif isinstance(e, LineEntity):
                    e.x = 2.0 * center_x - e.x
                    e.x2 = 2.0 * center_x - e.x2
                elif isinstance(e, PathEntity):
                    lx1, _, lx2, _ = e.get_local_bounds()
                    local_cx = (lx1 + lx2) / 2.0
                    b = e.get_bounds()
                    ecx = (b[0] + b[2]) / 2.0
                    e.x = 2.0 * center_x - ecx - (local_cx - lx1)
                    new_contours = []
                    for c in e.contours:
                        new_contours.append([(2.0 * local_cx - px, py) for px, py in c])
                    e.contours = new_contours
                    e.invalidate_bounds()
            else:
                if isinstance(e, (TextEntity, ImageEntity)):
                    e.is_mirrored_v = not getattr(e, "is_mirrored_v", False)
                    e.y = 2.0 * center_y - (e.y + e.height)
                elif isinstance(e, RectEntity):
                    e.y = 2.0 * center_y - (e.y + e.height)
                    e.rotation = -e.rotation
                elif isinstance(e, CircleEntity):
                    e.y = 2.0 * center_y - e.y
                    e.rotation = -e.rotation
                elif isinstance(e, LineEntity):
                    e.y = 2.0 * center_y - e.y
                    e.y2 = 2.0 * center_y - e.y2
                elif isinstance(e, PathEntity):
                    _, ly1, _, ly2 = e.get_local_bounds()
                    local_cy = (ly1 + ly2) / 2.0
                    b = e.get_bounds()
                    ecy = (b[1] + b[3]) / 2.0
                    e.y = 2.0 * center_y - ecy - (local_cy - ly1)
                    new_contours = []
                    for c in e.contours:
                        new_contours.append([(px, 2.0 * local_cy - py) for px, py in c])
                    e.contours = new_contours
                    e.invalidate_bounds()

            item.sync_from_entity()

        self.update()
        self.entity_modified.emit()

    def flip_selected_horizontal(self):
        self.flip_selected(horizontal=True)

    def flip_selected_vertical(self):
        self.flip_selected(horizontal=False)

    def _on_selection_changed(self):
        self.selection_changed.emit()

    # --- Mouse Event CAD Drawing Tools ---

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.scenePos()
            sx = self.snap_value(pos.x())
            sy = self.snap_value(pos.y())

            if self.active_tool == TOOL_RECT:
                self._drawing = True
                self._draw_start = QPointF(sx, sy)
                self._temp_item = QGraphicsRectItem(QRectF(sx, sy, 0, 0))
                self._temp_item.setPen(QPen(QColor("#00d4ff"), 1, Qt.PenStyle.DashLine))
                self.addItem(self._temp_item)
                event.accept()
                return

            elif self.active_tool == TOOL_CIRCLE:
                self._drawing = True
                self._draw_start = QPointF(sx, sy)
                self._temp_item = QGraphicsEllipseItem(QRectF(sx, sy, 0, 0))
                self._temp_item.setPen(QPen(QColor("#00d4ff"), 1, Qt.PenStyle.DashLine))
                self.addItem(self._temp_item)
                event.accept()
                return

            elif self.active_tool == TOOL_LINE:
                self._drawing = True
                self._draw_start = QPointF(sx, sy)
                self._temp_item = QGraphicsLineItem(QLineF(sx, sy, sx, sy))
                self._temp_item.setPen(QPen(QColor("#00d4ff"), 1, Qt.PenStyle.DashLine))
                self.addItem(self._temp_item)
                event.accept()
                return

            elif self.active_tool == TOOL_TEXT:
                parent_w = self.views()[0] if self.views() else None
                user_text, ok = QInputDialog.getText(
                    parent_w, "LaserForge Text Tool",
                    "Enter text to engrave / cut:",
                    text="LaserForge Text"
                )
                if not ok or not user_text.strip():
                    self.set_active_tool(TOOL_SELECT)
                    event.accept()
                    return

                self.push_undo_state()
                font = QFont("Sans Serif", int(round(15.0 * 2)))
                fm = QFontMetricsF(font)
                w = max(20.0, fm.horizontalAdvance(user_text) + 6.0)
                h = max(18.0, fm.height() + 4.0)
                text_ent = TextEntity(
                    layer_id=self.active_layer_id,
                    name=f"Text ({user_text[:12]})",
                    x=sx, y=sy,
                    text=user_text,
                    font_size=15.0,
                    width=w,
                    height=h
                )
                wrapper = self.add_entity(text_ent)
                self.clearSelection()
                wrapper.setSelected(True)
                self.set_active_tool(TOOL_SELECT)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._drawing and self._temp_item:
            pos = event.scenePos()
            cur_x = self.snap_value(pos.x())
            cur_y = self.snap_value(pos.y())

            # Square/Circle constraint with Shift
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                w = cur_x - self._draw_start.x()
                h = cur_y - self._draw_start.y()
                s = max(abs(w), abs(h))
                cur_x = self._draw_start.x() + (s if w >= 0 else -s)
                cur_y = self._draw_start.y() + (s if h >= 0 else -s)

            if self.active_tool == TOOL_RECT:
                rx = min(self._draw_start.x(), cur_x)
                ry = min(self._draw_start.y(), cur_y)
                rw = abs(cur_x - self._draw_start.x())
                rh = abs(cur_y - self._draw_start.y())
                self._temp_item.setRect(QRectF(rx, ry, rw, rh))

            elif self.active_tool == TOOL_CIRCLE:
                rx = min(self._draw_start.x(), cur_x)
                ry = min(self._draw_start.y(), cur_y)
                rw = abs(cur_x - self._draw_start.x())
                rh = abs(cur_y - self._draw_start.y())
                self._temp_item.setRect(QRectF(rx, ry, rw, rh))

            elif self.active_tool == TOOL_LINE:
                self._temp_item.setLine(QLineF(self._draw_start.x(), self._draw_start.y(), cur_x, cur_y))

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._drawing and self._temp_item:
            self._drawing = False
            pos = event.scenePos()
            cur_x = self.snap_value(pos.x())
            cur_y = self.snap_value(pos.y())

            self.removeItem(self._temp_item)
            self._temp_item = None

            if self.active_tool == TOOL_RECT:
                rx = min(self._draw_start.x(), cur_x)
                ry = min(self._draw_start.y(), cur_y)
                rw = abs(cur_x - self._draw_start.x())
                rh = abs(cur_y - self._draw_start.y())
                if rw > 1 and rh > 1:
                    rect_ent = RectEntity(layer_id=self.active_layer_id, name="Rectangle", x=rx, y=ry, width=rw, height=rh)
                    wrapper = self.add_entity(rect_ent)
                    wrapper.setSelected(True)

            elif self.active_tool == TOOL_CIRCLE:
                rx = min(self._draw_start.x(), cur_x)
                ry = min(self._draw_start.y(), cur_y)
                rw = abs(cur_x - self._draw_start.x())
                rh = abs(cur_y - self._draw_start.y())
                if rw > 1 and rh > 1:
                    cx = rx + rw / 2.0
                    cy = ry + rh / 2.0
                    circ_ent = CircleEntity(layer_id=self.active_layer_id, name="Ellipse", x=cx, y=cy, radius_x=rw/2.0, radius_y=rh/2.0)
                    wrapper = self.add_entity(circ_ent)
                    wrapper.setSelected(True)

            elif self.active_tool == TOOL_LINE:
                line_ent = LineEntity(layer_id=self.active_layer_id, name="Line", x=self._draw_start.x(), y=self._draw_start.y(), x2=cur_x, y2=cur_y)
                wrapper = self.add_entity(line_ent)
                wrapper.setSelected(True)

            self.set_active_tool(TOOL_SELECT)
            event.accept()
            return

        super().mouseReleaseEvent(event)
        self.entity_modified.emit()

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.scenePos(), QTransform())
            while item and not isinstance(item, LaserItemWrapper):
                item = item.parentItem()
            if isinstance(item, LaserItemWrapper) and isinstance(item.entity, TextEntity):
                tent = item.entity
                parent_w = self.views()[0] if self.views() else None
                new_text, ok = QInputDialog.getText(
                    parent_w, "Edit Text Content",
                    "Enter text to engrave / cut:",
                    text=tent.text
                )
                if ok and new_text != tent.text:
                    self.push_undo_state()
                    tent.text = new_text
                    font = QFont(tent.font_family, max(4, int(round(tent.font_size * 2))))
                    fm = QFontMetricsF(font)
                    tw = max(10.0, fm.horizontalAdvance(new_text) + 6.0)
                    tent.width = max(tent.width, tw)
                    item.sync_from_entity()
                    self.entity_modified.emit()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)
