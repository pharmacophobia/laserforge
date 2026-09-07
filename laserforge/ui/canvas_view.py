"""
LaserForge Interactive CAD Canvas View.
High-performance QGraphicsView with millimeter rulers, zoom, panning, workbed grid,
and real-time cursor coordinate tracking.
"""

from typing import Optional
import math
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QWheelEvent, QMouseEvent,
    QPaintEvent, QTransform
)
from PyQt6.QtWidgets import QGraphicsView, QWidget

RULER_BREADTH = 24  # Width/height of the coordinate rulers in pixels

class RulerWidget(QWidget):
    """Millimeter ruler widget along the top or left of the canvas."""
    def __init__(self, orientation: Qt.Orientation, view: "LaserCanvasView"):
        super().__init__()
        self.orientation = orientation
        self.view = view
        self.cursor_pos_mm = 0.0

    def update_cursor_pos(self, pos_mm: float):
        self.cursor_pos_mm = pos_mm
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Background
        painter.fillRect(self.rect(), QColor("#1f1f28"))

        pen_border = QPen(QColor("#36364a"), 1)
        pen_major = QPen(QColor("#a0a0b8"), 1)
        pen_minor = QPen(QColor("#54546c"), 1)

        font = QFont("Sans Serif", 7)
        painter.setFont(font)

        transform = self.view.transform()
        scale = transform.m11()  # pixels per mm

        if self.orientation == Qt.Orientation.Horizontal:
            painter.setPen(pen_border)
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

            # Visible mm range
            top_left_scene = self.view.mapToScene(0, 0)
            bottom_right_scene = self.view.mapToScene(self.width(), 0)
            min_mm = int(math.floor(top_left_scene.x() / 10.0)) * 10
            max_mm = int(math.ceil(bottom_right_scene.x() / 10.0)) * 10

            step = 10
            if scale < 1.0: step = 50
            if scale < 0.3: step = 100
            if scale > 4.0: step = 5

            for mm in range(min_mm, max_mm + step, step):
                view_x = int(self.view.mapFromScene(QPointF(mm, 0)).x())
                if 0 <= view_x <= self.width():
                    painter.setPen(pen_major)
                    painter.drawLine(view_x, self.height() - 8, view_x, self.height())
                    painter.setPen(QColor("#8c8ca8"))
                    painter.drawText(view_x + 2, self.height() - 10, str(mm))

            # Cursor marker
            cur_x = int(self.view.mapFromScene(QPointF(self.cursor_pos_mm, 0)).x())
            if 0 <= cur_x <= self.width():
                painter.setPen(QPen(QColor("#00d4ff"), 1))
                painter.drawLine(cur_x, 0, cur_x, self.height())

        else:
            painter.setPen(pen_border)
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

            top_left_scene = self.view.mapToScene(0, 0)
            bottom_right_scene = self.view.mapToScene(0, self.height())
            min_mm = int(math.floor(top_left_scene.y() / 10.0)) * 10
            max_mm = int(math.ceil(bottom_right_scene.y() / 10.0)) * 10

            step = 10
            if scale < 1.0: step = 50
            if scale < 0.3: step = 100
            if scale > 4.0: step = 5

            for mm in range(min_mm, max_mm + step, step):
                view_y = int(self.view.mapFromScene(QPointF(0, mm)).y())
                if 0 <= view_y <= self.height():
                    painter.setPen(pen_major)
                    painter.drawLine(self.width() - 8, view_y, self.width(), view_y)
                    painter.save()
                    painter.translate(self.width() - 10, view_y - 2)
                    painter.rotate(-90)
                    painter.setPen(QColor("#8c8ca8"))
                    painter.drawText(0, 0, str(mm))
                    painter.restore()

            cur_y = int(self.view.mapFromScene(QPointF(0, self.cursor_pos_mm)).y())
            if 0 <= cur_y <= self.height():
                painter.setPen(QPen(QColor("#00d4ff"), 1))
                painter.drawLine(0, cur_y, self.width(), cur_y)


class LaserCanvasView(QGraphicsView):
    cursor_moved_mm = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setBackgroundBrush(QBrush(QColor("#16161c")))

        # Panning state
        self._is_panning = False
        self._pan_start = QPointF()

        # Workbed config (mm)
        self.bed_width = 400.0
        self.bed_height = 400.0

        # Rulers
        self.top_ruler = RulerWidget(Qt.Orientation.Horizontal, self)
        self.left_ruler = RulerWidget(Qt.Orientation.Vertical, self)

        # Scale factor (1 scene unit = 1 millimeter)
        # Initial zoom: 1.5 pixels per mm
        self.scale(1.5, 1.5)

        # Enable mouse tracking for live coordinate display
        self.setMouseTracking(True)

    def set_bed_size(self, w: float, h: float):
        self.bed_width = w
        self.bed_height = h
        self.scene().setSceneRect(-50, -50, w + 100, h + 100)
        self.update()

    def zoom_to_fit(self):
        """Fits the entire laser workbed into the view with margin."""
        if self.width() <= 50 or self.height() <= 50:
            return
        self.resetTransform()
        rect = QRectF(-15, -15, self.bed_width + 30, self.bed_height + 30)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.top_ruler.update()
        self.left_ruler.update()

    def showEvent(self, event):
        super().showEvent(event)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self.zoom_to_fit)


    def wheelEvent(self, event: QWheelEvent):
        """Smooth zooming anchored at mouse cursor."""
        zoom_factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)

        # Cursor pos in scene
        old_pos = self.mapToScene(event.position().toPoint())

        self.scale(zoom_factor, zoom_factor)

        # Reposition viewport to keep scene position under mouse
        new_pos = self.mapToScene(event.position().toPoint())
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

        self.top_ruler.update()
        self.left_ruler.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and getattr(self, "_space_pressed", False)):
            self._is_panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)


    def mouseMoveEvent(self, event: QMouseEvent):
        scene_pt = self.mapToScene(event.position().toPoint())
        self.cursor_moved_mm.emit(scene_pt.x(), scene_pt.y())
        self.top_ruler.update_cursor_pos(scene_pt.x())
        self.left_ruler.update_cursor_pos(scene_pt.y())

        if self._is_panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            self.top_ruler.update()
            self.left_ruler.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton) and self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Draws the dark workspace, workbed boundary, and millimeter grid lines."""
        # Workspace background
        painter.fillRect(rect, QColor("#16161c"))

        # Laser Workbed surface (400x400mm)
        bed_rect = QRectF(0, 0, self.bed_width, self.bed_height)
        painter.fillRect(bed_rect, QColor("#22222c"))

        # Outer bed border
        painter.setPen(QPen(QColor("#4a4a64"), 1.2))
        painter.drawRect(bed_rect)

        # Millimeter Grid lines
        scale = self.transform().m11()

        # Minor 1mm grid (only when zoomed in enough)
        if scale > 3.0:
            pen_1mm = QPen(QColor("#2a2a38"), 0.5)
            painter.setPen(pen_1mm)
            for x in range(int(self.bed_width) + 1):
                if x % 10 != 0:
                    painter.drawLine(QPointF(x, 0), QPointF(x, self.bed_height))
            for y in range(int(self.bed_height) + 1):
                if y % 10 != 0:
                    painter.drawLine(QPointF(0, y), QPointF(self.bed_width, y))

        # 10mm grid lines
        pen_10mm = QPen(QColor("#36364a"), 0.8)
        painter.setPen(pen_10mm)
        for x in range(0, int(self.bed_width) + 1, 10):
            if x % 50 != 0:
                painter.drawLine(QPointF(x, 0), QPointF(x, self.bed_height))
        for y in range(0, int(self.bed_height) + 1, 10):
            if y % 50 != 0:
                painter.drawLine(QPointF(0, y), QPointF(self.bed_width, y))

        # 50mm major grid lines
        pen_50mm = QPen(QColor("#4e4e6c"), 1.0)
        painter.setPen(pen_50mm)
        for x in range(0, int(self.bed_width) + 1, 50):
            painter.drawLine(QPointF(x, 0), QPointF(x, self.bed_height))
        for y in range(0, int(self.bed_height) + 1, 50):
            painter.drawLine(QPointF(0, y), QPointF(self.bed_width, y))

        # Laser Origin indicator marker (0, 0)
        painter.setPen(QPen(QColor("#ff2a44"), 2))
        painter.drawLine(QPointF(0, 0), QPointF(20, 0)) # X-axis
        painter.setPen(QPen(QColor("#00e676"), 2))
        painter.drawLine(QPointF(0, 0), QPointF(0, 20)) # Y-axis
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawEllipse(QPointF(0, 0), 3, 3)


class LaserCanvasWidget(QWidget):
    """Container holding the LaserCanvasView and its top/left millimeter rulers."""
    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.view = LaserCanvasView(self)
        self.view.setScene(scene)

        from PyQt6.QtWidgets import QGridLayout
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Corner box
        corner = QWidget()
        corner.setFixedSize(RULER_BREADTH, RULER_BREADTH)
        corner.setStyleSheet("background-color: #1f1f28; border-right: 1px solid #36364a; border-bottom: 1px solid #36364a;")

        self.view.top_ruler.setFixedHeight(RULER_BREADTH)
        self.view.left_ruler.setFixedWidth(RULER_BREADTH)

        layout.addWidget(corner, 0, 0)
        layout.addWidget(self.view.top_ruler, 0, 1)
        layout.addWidget(self.view.left_ruler, 1, 0)
        layout.addWidget(self.view, 1, 1)

