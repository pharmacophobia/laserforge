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
    QPaintEvent, QTransform, QFontMetricsF
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

            origin = getattr(self.view, "origin_corner", "Bottom-Left")
            if getattr(self.view, "settings", None):
                origin = getattr(self.view.settings, "origin_corner", origin)
            is_right_origin = "Right" in origin
            bed_w = getattr(self.view, "bed_width", 400.0)
            if getattr(self.view, "settings", None):
                bed_w = getattr(self.view.settings, "bed_width", bed_w)

            for mm in range(min_mm, max_mm + step, step):
                view_x = int(self.view.mapFromScene(QPointF(mm, 0)).x())
                if 0 <= view_x <= self.width():
                    painter.setPen(pen_major)
                    painter.drawLine(view_x, self.height() - 8, view_x, self.height())
                    painter.setPen(QColor("#8c8ca8"))
                    disp_val = int(round(bed_w - mm)) if is_right_origin else mm
                    painter.drawText(view_x + 2, self.height() - 10, str(disp_val))

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

            origin = getattr(self.view, "origin_corner", "Bottom-Left")
            if getattr(self.view, "settings", None):
                origin = getattr(self.view.settings, "origin_corner", origin)
            is_bottom_origin = "Bottom" in origin
            bed_h = getattr(self.view, "bed_height", 400.0)
            if getattr(self.view, "settings", None):
                bed_h = getattr(self.view.settings, "bed_height", bed_h)

            for mm in range(min_mm, max_mm + step, step):
                view_y = int(self.view.mapFromScene(QPointF(0, mm)).y())
                if 0 <= view_y <= self.height():
                    painter.setPen(pen_major)
                    painter.drawLine(self.width() - 8, view_y, self.width(), view_y)
                    painter.save()
                    painter.translate(self.width() - 10, view_y - 2)
                    painter.rotate(-90)
                    painter.setPen(QColor("#8c8ca8"))
                    disp_val = int(round(bed_h - mm)) if is_bottom_origin else mm
                    painter.drawText(0, 0, str(disp_val))
                    painter.restore()

            cur_y = int(self.view.mapFromScene(QPointF(0, self.cursor_pos_mm)).y())
            if 0 <= cur_y <= self.height():
                painter.setPen(QPen(QColor("#00d4ff"), 1))
                painter.drawLine(0, cur_y, self.width(), cur_y)


class LaserCanvasView(QGraphicsView):
    cursor_moved_mm = pyqtSignal(float, float)
    art_item_dropped = pyqtSignal(str, float, float)
    file_dropped = pyqtSignal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
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
        self.origin_corner = "Bottom-Left"
        self.settings = None

        # Rulers
        self.top_ruler = RulerWidget(Qt.Orientation.Horizontal, self)
        self.left_ruler = RulerWidget(Qt.Orientation.Vertical, self)

        # Scale factor (1 scene unit = 1 millimeter)
        # Initial zoom: 1.5 pixels per mm
        self.scale(1.5, 1.5)

        # Enable mouse tracking for live coordinate display
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # Hardware OpenGL Viewport Acceleration
        self.opengl_enabled = False
        self.set_opengl_acceleration(True)

    def set_opengl_acceleration(self, enable: bool):
        """Enables or disables hardware-accelerated OpenGL rendering for canvas viewport."""
        if enable:
            try:
                from PyQt6.QtOpenGLWidgets import QOpenGLWidget
                from PyQt6.QtGui import QSurfaceFormat
                fmt = QSurfaceFormat()
                fmt.setSamples(4)  # 4x Multi-Sample Anti-Aliasing (MSAA)
                fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
                gl_widget = QOpenGLWidget()
                gl_widget.setFormat(fmt)
                self.setViewport(gl_widget)
                self.opengl_enabled = True
            except Exception:
                self.setViewport(QWidget())
                self.opengl_enabled = False
        else:
            self.setViewport(QWidget())
            self.opengl_enabled = False

    def set_bed_size(self, w: float, h: float, origin_corner: Optional[str] = None):
        self.bed_width = float(w)
        self.bed_height = float(h)
        if origin_corner:
            self.origin_corner = origin_corner
        elif self.settings:
            self.origin_corner = getattr(self.settings, "origin_corner", "Bottom-Left")
        if self.scene() and hasattr(self.scene(), "set_bed_size"):
            self.scene().set_bed_size(w, h, self.origin_corner)
        elif self.scene():
            self.scene().bed_width = float(w)
            self.scene().bed_height = float(h)
            self.scene().origin_corner = self.origin_corner
        self.scene().setSceneRect(-50, -50, w + 100, h + 100)
        self.update()
        self.top_ruler.update()
        self.left_ruler.update()

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
        origin = getattr(self, "origin_corner", "Bottom-Left")
        if self.settings:
            origin = getattr(self.settings, "origin_corner", origin)

        disp_x = (self.bed_width - scene_pt.x()) if "Right" in origin else scene_pt.x()
        disp_y = (self.bed_height - scene_pt.y()) if "Bottom" in origin else scene_pt.y()

        self.cursor_moved_mm.emit(disp_x, disp_y)
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

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            import os
            main_win = self.window()
            for url in event.mimeData().urls():
                filepath = url.toLocalFile()
                if not filepath or not os.path.exists(filepath):
                    continue
                ext = os.path.splitext(filepath)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
                    scene_pos = self.mapToScene(event.position().toPoint())
                    if hasattr(main_win, "import_image_file"):
                        main_win.import_image_file(filepath, pos=(scene_pos.x(), scene_pos.y()))
                elif ext in (".svg",):
                    if hasattr(main_win, "import_svg_file"):
                        main_win.import_svg_file(filepath)
                elif ext in (".laserproj", ".json"):
                    if hasattr(main_win, "load_project_file"):
                        main_win.load_project_file(filepath)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu, QInputDialog
        from laserforge.ui.canvas_scene import LaserItemWrapper
        from laserforge.core.models import ImageEntity, TextEntity

        menu = QMenu(self)
        scene_pos = self.mapToScene(event.pos())
        clicked_item = self.scene().itemAt(scene_pos, self.transform())
        main_win = self.window()

        selected_text_ent = None
        selected_text_item = None
        if isinstance(clicked_item, LaserItemWrapper) and isinstance(clicked_item.entity, TextEntity):
            selected_text_item = clicked_item
            selected_text_ent = clicked_item.entity
        else:
            selected_items = [i for i in self.scene().selectedItems() if isinstance(i, LaserItemWrapper) and isinstance(i.entity, TextEntity)]
            if selected_items:
                selected_text_item = selected_items[0]
                selected_text_ent = selected_text_item.entity

        if selected_text_ent and selected_text_item:
            def _do_edit_text():
                new_text, ok = QInputDialog.getText(
                    self, "Edit Text Content",
                    "Enter text to engrave / cut:",
                    text=selected_text_ent.text
                )
                if ok and new_text != selected_text_ent.text:
                    if hasattr(self.scene(), "push_undo_state"):
                        self.scene().push_undo_state()
                    selected_text_ent.text = new_text
                    font = QFont(selected_text_ent.font_family)
                    font.setPointSizeF(max(1.2, selected_text_ent.font_size * 1.5))
                    fm = QFontMetricsF(font)
                    tw = max(10.0, fm.horizontalAdvance(new_text) + 6.0)
                    selected_text_ent.width = max(selected_text_ent.width, tw)
                    selected_text_item.sync_from_entity()
                    if hasattr(self.scene(), "entity_modified"):
                        self.scene().entity_modified.emit()

            act_edit_txt = menu.addAction("✏️ Edit Text Content...")
            act_edit_txt.triggered.connect(_do_edit_text)
            menu.addSeparator()

        selected_image = None
        if isinstance(clicked_item, LaserItemWrapper) and isinstance(clicked_item.entity, ImageEntity):
            selected_image = clicked_item.entity
        else:
            selected_ents = getattr(self.scene(), "get_selected_entities", lambda: [])()
            img_ents = [e for e in selected_ents if isinstance(e, ImageEntity)]
            if img_ents:
                selected_image = img_ents[0]

        if selected_image:
            act_crop = menu.addAction("✂️ Crop Image...")
            act_crop.triggered.connect(lambda: getattr(main_win, "open_crop_tool_for_selected", lambda e: None)(selected_image))

            act_photo = menu.addAction("📷 Open in Photo Engrave Studio...")
            act_photo.triggered.connect(lambda: getattr(main_win, "open_photo_studio", lambda e: None)(selected_image))

            act_sdxl_mod = menu.addAction("🎨 Modify Photo with AI (SDXL Turbo)...")
            act_sdxl_mod.triggered.connect(lambda: getattr(main_win, "open_sdxl_turbo_studio_for_image", lambda e: None)(selected_image))

            act_trace = menu.addAction("⚡ Trace Image to SVG...")
            act_trace.triggered.connect(lambda: getattr(main_win, "trace_image", lambda: None)())

            act_cutout = menu.addAction("✂️ Auto Cutout to SVG (Cut Line)...")
            act_cutout.triggered.connect(lambda: getattr(main_win, "auto_image_cutout", lambda e=None: None)(selected_image))
            menu.addSeparator()

        act_qr = menu.addAction("📱 QR Code & Barcode Studio...")
        act_qr.triggered.connect(lambda: getattr(main_win, "open_barcode_designer", lambda: None)())

        act_sdxl = menu.addAction("🎨 SDXL Turbo Generative Studio...")
        act_sdxl.triggered.connect(lambda: getattr(main_win, "open_sdxl_turbo_studio", lambda: None)())

        selected_ents = getattr(self.scene(), "get_selected_entities", lambda: [])()
        if len(selected_ents) >= 1:
            act_hatch = menu.addAction("📐 Directional Vector Hatching... (Ctrl+Shift+H)")
            act_hatch.triggered.connect(lambda: getattr(main_win, "open_directional_hatching", lambda: None)())

        if len(selected_ents) >= 2:
            act_weld = menu.addAction("⚡ Weld / Union Shapes (Ctrl+Shift+U)")
            act_weld.triggered.connect(lambda: getattr(self.scene(), "boolean_operation", lambda m: None)("weld"))

            act_sub = menu.addAction("➖ Subtract / Difference Shapes (Ctrl+Shift+D)")
            act_sub.triggered.connect(lambda: getattr(self.scene(), "boolean_operation", lambda m: None)("subtract"))

            act_inter = menu.addAction("✖ Intersect Shapes (Ctrl+Shift+X)")
            act_inter.triggered.connect(lambda: getattr(self.scene(), "boolean_operation", lambda m: None)("intersect"))
            menu.addSeparator()

        menu.addSeparator()
        align_marks_menu = menu.addMenu("📐 Alignment & Registration Marks")
        act_add_l = align_marks_menu.addAction("📐 Add Corner 90° L-Marks")
        act_add_l.setToolTip("Draw 90-degree corner L-tick alignment marks on perimeter corners")
        act_add_l.triggered.connect(lambda: getattr(main_win, "add_corner_l_marks_quick", lambda: None)())

        act_add_c = align_marks_menu.addAction("➕ Add Center '+' Mark")
        act_add_c.setToolTip("Draw a centered '+' registration cross mark on workpiece center")
        act_add_c.triggered.connect(lambda: getattr(main_win, "add_center_cross_quick", lambda: None)())

        align_marks_menu.addSeparator()
        act_marks_studio = align_marks_menu.addAction("🎯 Alignment Marks Studio...")
        act_marks_studio.setToolTip("Open full studio for Corner L-Marks and Center '+' Cross configuration")
        act_marks_studio.triggered.connect(lambda: getattr(main_win, "open_alignment_marks_studio", lambda: None)())

        guide_menu = menu.addMenu("📏 Alignment Guides")
        act_add_hg = guide_menu.addAction(f"Add Horizontal Guide @ Y={scene_pos.y():.1f}mm")
        act_add_hg.triggered.connect(lambda: getattr(self.scene(), "add_guide", lambda o, p: None)("horizontal", scene_pos.y()))
        act_add_vg = guide_menu.addAction(f"Add Vertical Guide @ X={scene_pos.x():.1f}mm")
        act_add_vg.triggered.connect(lambda: getattr(self.scene(), "add_guide", lambda o, p: None)("vertical", scene_pos.x()))
        guide_menu.addSeparator()
        act_toggle_guides = guide_menu.addAction("Toggle Guides Visibility")
        act_toggle_guides.triggered.connect(lambda: getattr(self.scene(), "set_guides_visible", lambda v: None)(not getattr(self.scene(), "show_guides", True)))
        act_clear_guides = guide_menu.addAction("Clear All Guides")
        act_clear_guides.triggered.connect(lambda: getattr(self.scene(), "clear_guides", lambda: None)())

        act_undo = menu.addAction("↩ Undo (Ctrl+Z)")
        act_undo.triggered.connect(lambda: getattr(self.scene(), "undo", lambda: None)())

        act_redo = menu.addAction("↪ Redo (Ctrl+Y)")
        act_redo.triggered.connect(lambda: getattr(self.scene(), "redo", lambda: None)())

        menu.addSeparator()
        if selected_ents:
            act_flip_h = menu.addAction("↔ Flip Horizontally (H)")
            act_flip_h.triggered.connect(lambda: getattr(self.scene(), "flip_selected_horizontal", lambda: None)())

            act_flip_v = menu.addAction("↕ Flip Vertically (V)")
            act_flip_v.triggered.connect(lambda: getattr(self.scene(), "flip_selected_vertical", lambda: None)())

            act_add_art = menu.addAction("📦 Add Selection to Art Library (Ctrl+Shift+L)...")
            act_add_art.triggered.connect(lambda: getattr(self.window(), "add_selection_to_art_library", lambda: None)())
            menu.addSeparator()

        act_dup = menu.addAction("Duplicate (Ctrl+D)")
        act_dup.triggered.connect(lambda: getattr(self.scene(), "duplicate_selected", lambda: None)())

        act_del = menu.addAction("Delete (Del)")
        act_del.triggered.connect(lambda: getattr(self.scene(), "delete_selected", lambda: None)())

        menu.addSeparator()
        act_fit = menu.addAction("Fit Workbed in View (Ctrl+0)")
        act_fit.triggered.connect(self.zoom_to_fit)

        menu.exec(event.globalPos())

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-laserforge-artitem") or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-laserforge-artitem") or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        pos_px = event.position().toPoint() if hasattr(event, "position") else event.pos()
        scene_pos = self.mapToScene(pos_px)
        x_mm = float(scene_pos.x())
        y_mm = float(scene_pos.y())

        if event.mimeData().hasFormat("application/x-laserforge-artitem"):
            item_id = bytes(event.mimeData().data("application/x-laserforge-artitem")).decode("utf-8")
            self.art_item_dropped.emit(item_id, x_mm, y_mm)
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                fpath = url.toLocalFile()
                if fpath:
                    self.file_dropped.emit(fpath, x_mm, y_mm)
                    event.acceptProposedAction()
                    break
        else:
            super().dropEvent(event)

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
        origin = getattr(self, "origin_corner", "Bottom-Left")
        if self.settings:
            origin = getattr(self.settings, "origin_corner", origin)

        if origin == "Bottom-Left":
            orig_pt = QPointF(0, self.bed_height)
            x_end = QPointF(24, self.bed_height)
            y_end = QPointF(0, self.bed_height - 24)
            lbl_pos = QPointF(6, self.bed_height - 6)
        elif origin == "Top-Left":
            orig_pt = QPointF(0, 0)
            x_end = QPointF(24, 0)
            y_end = QPointF(0, 24)
            lbl_pos = QPointF(6, 16)
        elif origin == "Bottom-Right":
            orig_pt = QPointF(self.bed_width, self.bed_height)
            x_end = QPointF(self.bed_width - 24, self.bed_height)
            y_end = QPointF(self.bed_width, self.bed_height - 24)
            lbl_pos = QPointF(self.bed_width - 70, self.bed_height - 6)
        else:  # Top-Right
            orig_pt = QPointF(self.bed_width, 0)
            x_end = QPointF(self.bed_width - 24, 0)
            y_end = QPointF(self.bed_width, 24)
            lbl_pos = QPointF(self.bed_width - 70, 16)

        # Draw axis lines
        painter.setPen(QPen(QColor("#ff3355"), 2.2))
        painter.drawLine(orig_pt, x_end)  # +X axis (Red)
        painter.setPen(QPen(QColor("#00e676"), 2.2))
        painter.drawLine(orig_pt, y_end)  # +Y axis (Green)

        # Draw glowing origin beacon
        painter.setPen(QPen(QColor("#00e5ff"), 1.8))
        painter.setBrush(QBrush(QColor(0, 229, 255, 70)))
        painter.drawEllipse(orig_pt, 7, 7)
        painter.setBrush(QBrush(QColor("#00ff88")))
        painter.drawEllipse(orig_pt, 3, 3)

        # Origin text badge
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#00ff88"), 1))
        painter.drawText(lbl_pos, "ORIGIN (0,0)")


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

