"""
LaserForge Interactive CAD Canvas Scene.
Manages vector CAD shapes, interactive creation tools, transformation handles,
and layer color rendering.
"""

from typing import List, Optional, Tuple, Dict, Any
import math
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QLineF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPainterPath, QFont, QPixmap, QTransform
)
from PyQt6.QtWidgets import (
    QGraphicsScene, QGraphicsItem, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsTextItem, QGraphicsPixmapItem,
    QGraphicsSceneMouseEvent
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

class LaserItemWrapper(QGraphicsItem):
    """Wrapper item for CAD entities with selection bounding box and handles."""
    def __init__(self, entity: LaserEntity, layer_manager: LayerManager):
        super().__init__()
        self.entity = entity
        self.layer_manager = layer_manager
        self._cached_rect: Optional[QRectF] = None
        self._cached_path: Optional[QPainterPath] = None
        self._cached_pixmap: Optional[QPixmap] = None
        self._cached_pixmap_path: Optional[str] = None
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
        self.setPos(self.entity.x, self.entity.y)
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
            return QRectF(min(0, dx), min(0, dy), abs(dx), abs(dy))
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
            self._cached_rect = self.raw_rect().adjusted(-3.5, -3.5, 3.5, 3.5)
        return self._cached_rect

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
            font = QFont(self.entity.font_family, int(self.entity.font_size * 2))
            font.setBold(self.entity.bold)
            font.setItalic(self.entity.italic)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.entity.text)

        elif isinstance(self.entity, ImageEntity):
            if self.entity.image_path:
                if self._cached_pixmap is None or self._cached_pixmap_path != self.entity.image_path:
                    self._cached_pixmap = QPixmap(self.entity.image_path)
                    self._cached_pixmap_path = self.entity.image_path
                if not self._cached_pixmap.isNull():
                    painter.drawPixmap(rect.toRect(), self._cached_pixmap)
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

        # Draw selection box and corner handles if selected
        if self.isSelected():
            painter.setPen(QPen(QColor("#00d4ff"), 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = rect.adjusted(-1, -1, 1, 1)
            painter.drawRect(sel_rect)

            # Draw 8 resize handles
            handle_color = QColor("#00d4ff")
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.setBrush(QBrush(handle_color))
            corners = [
                sel_rect.topLeft(), sel_rect.topRight(),
                sel_rect.bottomLeft(), sel_rect.bottomRight(),
                QPointF(sel_rect.center().x(), sel_rect.top()),
                QPointF(sel_rect.center().x(), sel_rect.bottom()),
                QPointF(sel_rect.left(), sel_rect.center().y()),
                QPointF(sel_rect.right(), sel_rect.center().y())
            ]
            for c in corners:
                painter.drawRect(QRectF(c.x() - 2.5, c.y() - 2.5, 5, 5))


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

        # Drawing state
        self._drawing = False
        self._draw_start = QPointF()
        self._temp_item: Optional[QGraphicsItem] = None

        self.selectionChanged.connect(self._on_selection_changed)

    def set_active_tool(self, tool: str):
        self.active_tool = tool
        self.clearSelection()

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

    def delete_selected(self):
        for item in self.selectedItems():
            if isinstance(item, LaserItemWrapper):
                self.removeItem(item)
        self.entity_modified.emit()

    def duplicate_selected(self):
        selected = self.get_selected_entities()
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
                new_ent = TextEntity(layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5, text=e.text, font_family=e.font_family, font_size=e.font_size, bold=e.bold, italic=e.italic)
            elif isinstance(e, PathEntity):
                new_contours = [[(p[0]+5, p[1]+5) for p in c] for c in e.contours]
                new_ent = PathEntity(layer_id=e.layer_id, name=e.name, x=e.x+5, y=e.y+5, contours=new_contours, closed=e.closed)

            if new_ent:
                wrapper = self.add_entity(new_ent)
                wrapper.setSelected(True)

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
                text_ent = TextEntity(
                    layer_id=self.active_layer_id,
                    name="Text",
                    x=sx, y=sy,
                    text="LaserForge Text",
                    font_size=15.0
                )
                self.add_entity(text_ent)
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
