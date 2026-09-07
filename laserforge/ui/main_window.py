"""
LaserForge Main Application Window.
LightBurn-inspired layout integrating:
- 2D CAD Canvas with mm rulers, zoom/pan, grid, and drawing tools
- Left CAD Toolbar (Select, Rect, Circle, Line, Text, Image, SVG)
- Right Cuts / Layers Dock with per-layer settings and bottom palette
- Right Bottom Dock with Laser Controls, Terminal Console, and Shape Properties
- Simulation Toolpath Preview and GRBL G-Code Generator
"""

import os
from typing import Optional
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QDockWidget, QTabWidget, QFileDialog, QMessageBox, QLabel,
    QStatusBar, QPushButton, QInputDialog, QButtonGroup
)
from PyQt6.QtCore import Qt, QSize, QPointF
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QColor, QPixmap, QPainter, QFont, QPen


from laserforge.config import MachineSettings, LAYER_PALETTE
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, TextEntity, ImageEntity, PathEntity
)
from laserforge.core.layer_manager import LayerManager
from laserforge.core.serial_controller import SerialController
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.project_io import ProjectIO

from laserforge.ui.canvas_scene import (
    LaserCanvasScene, TOOL_SELECT, TOOL_RECT, TOOL_CIRCLE, TOOL_LINE, TOOL_TEXT
)
from laserforge.ui.canvas_view import LaserCanvasWidget
from laserforge.ui.cuts_panel import CutsPanel
from laserforge.ui.laser_control_panel import LaserControlPanel
from laserforge.ui.console_panel import ConsolePanel
from laserforge.ui.shape_properties import ShapePropertiesPanel
from laserforge.ui.preview_dialog import PreviewDialog
from laserforge.ui.machine_settings_dialog import MachineSettingsDialog


def create_tool_icon(text: str, bg_color: str = "#2b2b36", fg_color: str = "#00e5ff") -> QIcon:
    """Generates a high-contrast procedural icon for toolbar actions."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(bg_color))
    painter.setPen(QPen(QColor("#3d3d4d"), 1))
    painter.drawRoundedRect(2, 2, 28, 28, 4, 4)

    painter.setPen(QColor(fg_color))
    font = QFont("sans-serif", 12, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LaserForge - Laser Engraver & Cutter")
        self.resize(1280, 800)

        # Core Backend Subsystems
        self.settings = MachineSettings()
        self.layer_manager = LayerManager()
        self.serial_ctrl = SerialController()
        self.gcode_gen = GCodeGenerator(self.settings, self.layer_manager)

        # Scene and Canvas
        self.scene = LaserCanvasScene(self.layer_manager, self)
        self.canvas_widget = LaserCanvasWidget(self.scene, self)
        self.setCentralWidget(self.canvas_widget)

        # Active project file path
        self.current_project_path: Optional[str] = None

        # Build UI Elements
        self._create_actions()
        self._create_menus()
        self._create_cad_toolbar()
        self._create_top_toolbar()
        self._create_dock_panels()
        self._create_bottom_palette_dock()
        self._create_status_bar()

        # Connect event signals
        self._connect_signals()

        # Set canvas bed bounds
        self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height)
        self.canvas_widget.view.zoom_to_fit()

    def _create_actions(self):
        # File Actions
        self.act_new = QAction("New Project", self)
        self.act_new.setShortcut(QKeySequence.StandardKey.New)
        self.act_new.triggered.connect(self.new_project)

        self.act_open = QAction("Open Project...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.open_project)

        self.act_save = QAction("Save Project", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self.save_project)

        self.act_save_as = QAction("Save Project As...", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self.save_project_as)

        self.act_import_svg = QAction("Import SVG / Vector...", self)
        self.act_import_svg.setShortcut("Ctrl+I")
        self.act_import_svg.triggered.connect(self.import_svg)

        self.act_import_img = QAction("Import Image...", self)
        self.act_import_img.triggered.connect(self.import_image)

        self.act_export_gcode = QAction("Export G-Code...", self)
        self.act_export_gcode.setShortcut("Ctrl+E")
        self.act_export_gcode.triggered.connect(self.export_gcode)

        self.act_exit = QAction("Exit", self)
        self.act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_exit.triggered.connect(self.close)

        # Edit Actions
        self.act_select_all = QAction("Select All", self)
        self.act_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.act_select_all.triggered.connect(lambda: [i.setSelected(True) for i in self.scene.items()])

        self.act_delete = QAction("Delete", self)
        self.act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self.act_delete.triggered.connect(self.scene.delete_selected)

        self.act_duplicate = QAction("Duplicate", self)
        self.act_duplicate.setShortcut("Ctrl+D")
        self.act_duplicate.triggered.connect(self.scene.duplicate_selected)

        # View Actions
        self.act_zoom_fit = QAction("Zoom to Fit Bed", self)
        self.act_zoom_fit.setShortcut("Ctrl+0")
        self.act_zoom_fit.triggered.connect(self.canvas_widget.view.zoom_to_fit)

        # Laser & Simulation Actions
        self.act_preview = QAction("Preview Toolpaths (Simulation)...", self)
        self.act_preview.setShortcut("Alt+P")
        self.act_preview.triggered.connect(self.preview_simulation)

        self.act_frame = QAction("Frame Bounding Box", self)
        self.act_frame.setShortcut("Ctrl+F")
        self.act_frame.triggered.connect(self.frame_job)

        self.act_start_job = QAction("Start Laser Job", self)
        self.act_start_job.setShortcut("Ctrl+R")
        self.act_start_job.triggered.connect(self.start_job)

        self.act_pause_job = QAction("Pause / Resume Job", self)
        self.act_pause_job.triggered.connect(self._toggle_pause_job)


        self.act_stop_job = QAction("Emergency Stop / Abort", self)
        self.act_stop_job.setShortcut("Esc")
        self.act_stop_job.triggered.connect(self.serial_ctrl.stop_streaming)

        self.act_home = QAction("Home Machine ($H)", self)
        self.act_home.triggered.connect(self.serial_ctrl.home)

        self.act_unlock = QAction("Unlock Alarm ($X)", self)
        self.act_unlock.triggered.connect(self.serial_ctrl.unlock)

        self.act_settings = QAction("Machine Settings...", self)
        self.act_settings.setShortcut("Ctrl+,")
        self.act_settings.triggered.connect(self.open_machine_settings)

    def _create_menus(self):
        menubar = self.menuBar()

        # File Menu
        menu_file = menubar.addMenu("&File")
        menu_file.addAction(self.act_new)
        menu_file.addAction(self.act_open)
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_save_as)
        menu_file.addSeparator()
        menu_file.addAction(self.act_import_svg)
        menu_file.addAction(self.act_import_img)
        menu_file.addSeparator()
        menu_file.addAction(self.act_export_gcode)
        menu_file.addSeparator()
        menu_file.addAction(self.act_exit)

        # Edit Menu
        menu_edit = menubar.addMenu("&Edit")
        menu_edit.addAction(self.act_select_all)
        menu_edit.addAction(self.act_duplicate)
        menu_edit.addAction(self.act_delete)

        # Laser Menu
        menu_laser = menubar.addMenu("&Laser")
        menu_laser.addAction(self.act_preview)
        menu_laser.addAction(self.act_frame)
        menu_laser.addAction(self.act_start_job)
        menu_laser.addAction(self.act_pause_job)
        menu_laser.addAction(self.act_stop_job)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_home)
        menu_laser.addAction(self.act_unlock)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_settings)

        # Tools Menu
        menu_tools = menubar.addMenu("&Tools")
        menu_tools.addAction(self.act_preview)
        menu_tools.addAction(self.act_zoom_fit)

        # Help Menu
        menu_help = menubar.addMenu("&Help")
        act_about = QAction("About LaserForge...", self)
        act_about.triggered.connect(self._show_about)
        menu_help.addAction(act_about)

    def _create_top_toolbar(self):
        tb = QToolBar("Main Controls")
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        tb.addAction(self.act_new)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        tb.addAction(self.act_import_svg)
        tb.addAction(self.act_import_img)
        tb.addSeparator()
        tb.addAction(self.act_zoom_fit)
        tb.addSeparator()

        # Preview Button on top
        btn_preview = QPushButton("  Preview (Alt+P)")
        btn_preview.setIcon(create_tool_icon("👁", fg_color="#ffd600"))
        btn_preview.setStyleSheet("font-weight: bold; padding: 4px 8px;")
        btn_preview.clicked.connect(self.preview_simulation)
        tb.addWidget(btn_preview)

        # Machine Settings Button
        btn_set = QPushButton("  Settings")
        btn_set.setIcon(create_tool_icon("⚙", fg_color="#b0bec5"))
        btn_set.setStyleSheet("padding: 4px 8px;")
        btn_set.clicked.connect(self.open_machine_settings)
        tb.addWidget(btn_set)

    def _create_cad_toolbar(self):
        cad_tb = QToolBar("CAD Drawing Tools")
        cad_tb.setMovable(False)
        cad_tb.setOrientation(Qt.Orientation.Vertical)
        cad_tb.setIconSize(QSize(30, 30))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, cad_tb)

        tool_group = QButtonGroup(self)
        tool_group.setExclusive(True)

        tools = [
            ("Select (S)", TOOL_SELECT, "↖", "#00e5ff"),
            ("Rectangle (R)", TOOL_RECT, "▭", "#69f0ae"),
            ("Circle (C)", TOOL_CIRCLE, "◯", "#ffd740"),
            ("Line (L)", TOOL_LINE, "╱", "#ff4081"),
            ("Text (T)", TOOL_TEXT, "A", "#e040fb"),
        ]

        for tip, tool_id, icon_char, color in tools:
            action = QAction(create_tool_icon(icon_char, fg_color=color), tip, self)
            action.setCheckable(True)
            if tool_id == TOOL_SELECT:
                action.setChecked(True)
            action.triggered.connect(lambda checked, tid=tool_id: self.scene.set_active_tool(tid))
            cad_tb.addAction(action)

        cad_tb.addSeparator()

        # Image Import Action
        act_img = QAction(create_tool_icon("🖼", fg_color="#40c4ff"), "Insert Image", self)
        act_img.triggered.connect(self.import_image)
        cad_tb.addAction(act_img)

        # SVG Import Action
        act_svg = QAction(create_tool_icon("SVG", fg_color="#b388ff"), "Import SVG Vector", self)
        act_svg.triggered.connect(self.import_svg)
        cad_tb.addAction(act_svg)

        cad_tb.addSeparator()

        # Zoom Fit
        act_fit = QAction(create_tool_icon("⛶", fg_color="#fff"), "Fit Workbed in View", self)
        act_fit.triggered.connect(self.canvas_widget.view.zoom_to_fit)
        cad_tb.addAction(act_fit)

        # Duplicate
        act_dup = QAction(create_tool_icon("❐", fg_color="#81d4fa"), "Duplicate (Ctrl+D)", self)
        act_dup.triggered.connect(self.scene.duplicate_selected)
        cad_tb.addAction(act_dup)

        # Delete
        act_del = QAction(create_tool_icon("✕", fg_color="#ff5252"), "Delete (Del)", self)
        act_del.triggered.connect(self.scene.delete_selected)
        cad_tb.addAction(act_del)

    def _create_dock_panels(self):
        # 1. Cuts / Layers Dock (Right Top)
        cuts_dock = QDockWidget("Cuts / Layers", self)
        cuts_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.cuts_panel = CutsPanel(self.layer_manager, self)
        cuts_dock.setWidget(self.cuts_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, cuts_dock)

        # 2. Bottom-Right Multi-Tab Dock: Laser, Console, Properties
        right_tab_dock = QDockWidget("Laser & Machine Operations", self)
        right_tab_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)

        tab_widget = QTabWidget()
        self.laser_panel = LaserControlPanel(self.serial_ctrl, self)
        self.console_panel = ConsolePanel(self.serial_ctrl, self)
        self.props_panel = ShapePropertiesPanel(self.scene, self)

        tab_widget.addTab(self.laser_panel, "Laser")
        tab_widget.addTab(self.console_panel, "Console")
        tab_widget.addTab(self.props_panel, "Properties")

        right_tab_dock.setWidget(tab_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_tab_dock)

    def _create_bottom_palette_dock(self):
        """Creates the signature bottom LightBurn quick color swatch palette."""
        palette_toolbar = QToolBar("Quick Layer Palette")
        palette_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, palette_toolbar)

        lbl = QLabel(" Active Layer: ")
        lbl.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        palette_toolbar.addWidget(lbl)

        for p in LAYER_PALETTE:
            lid = p["id"]
            color_hex = p["color"]
            btn = QPushButton(p["name"])
            btn.setFixedSize(38, 22)
            btn.setToolTip(f"Layer {p['name']} ({p['label']})")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color_hex};
                    color: {'#000000' if lid in (4, 11) else '#ffffff'};
                    font-weight: bold;
                    font-size: 9px;
                    border: 1px solid #444444;
                    border-radius: 2px;
                    margin: 0px 1px;
                }}
                QPushButton:hover {{
                    border: 2px solid #ffffff;
                }}
            """)
            btn.clicked.connect(lambda checked, layer_id=lid: self._on_palette_layer_clicked(layer_id))
            palette_toolbar.addWidget(btn)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.status_pos = QLabel("X: 0.00 mm  Y: 0.00 mm")
        self.status_pos.setStyleSheet("font-family: monospace; padding-right: 15px; color: #00e5ff;")
        sb.addPermanentWidget(self.status_pos)

        self.status_entity_count = QLabel("Objects: 0")
        self.status_entity_count.setStyleSheet("padding-right: 15px; color: #cfd8dc;")
        sb.addPermanentWidget(self.status_entity_count)

        self.status_machine = QLabel("Laser: Disconnected")
        self.status_machine.setStyleSheet("font-weight: bold; padding-right: 10px; color: #ef5350;")
        sb.addPermanentWidget(self.status_machine)

        sb.showMessage("Ready. Select a tool or draw shapes.")

    def _connect_signals(self):
        # Cursor tracking
        self.canvas_widget.view.cursor_moved_mm.connect(self._on_cursor_moved)

        # Scene changes
        self.scene.entity_modified.connect(self._on_entities_changed)
        self.scene.selectionChanged.connect(self._on_entities_changed)

        # Cuts panel signals
        self.cuts_panel.layer_selected.connect(self._on_palette_layer_clicked)
        self.cuts_panel.layers_updated.connect(lambda: self.scene.update())

        # Laser control signals
        self.laser_panel.start_job_requested.connect(self.start_job)
        self.laser_panel.frame_job_requested.connect(self.frame_job)

        # Serial status badge
        self.serial_ctrl.connected.connect(lambda p: self.status_machine.setText(f"Laser: Connected ({p})"))
        self.serial_ctrl.connected.connect(lambda: self.status_machine.setStyleSheet("font-weight: bold; color: #66bb6a;"))
        self.serial_ctrl.disconnected.connect(lambda: self.status_machine.setText("Laser: Disconnected"))
        self.serial_ctrl.disconnected.connect(lambda: self.status_machine.setStyleSheet("font-weight: bold; color: #ef5350;"))

    def _on_cursor_moved(self, x: float, y: float):
        self.status_pos.setText(f"X: {x:6.2f} mm  Y: {y:6.2f} mm")

    def _on_entities_changed(self):
        entities = self.scene.get_all_entities()
        selected = self.scene.get_selected_entities()
        self.status_entity_count.setText(f"Objects: {len(entities)} (Selected: {len(selected)})")

    def _on_palette_layer_clicked(self, layer_id: int):
        self.scene.set_active_layer(layer_id)
        self.statusBar().showMessage(f"Active Layer set to C{layer_id:02d}", 2500)

    # File Operations
    def new_project(self):
        if self.scene.get_all_entities():
            res = QMessageBox.question(
                self, "New Project", "Clear current project workspace?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res != QMessageBox.StandardButton.Yes:
                return
        self.scene.clear_entities()
        self.current_project_path = None
        self.setWindowTitle("LaserForge - Untitled Project")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open LaserForge Project", "", "LaserForge Projects (*.laserproj *.json);;All Files (*)"
        )
        if not path:
            return

        try:
            entities, layer_settings, machine_cfg = ProjectIO.load_project(path, self.layer_manager)
            self.scene.clear_entities()

            for ent in entities:
                self.scene.add_entity(ent)

            if "bed_width" in machine_cfg and "bed_height" in machine_cfg:
                self.settings.bed_width = machine_cfg["bed_width"]
                self.settings.bed_height = machine_cfg["bed_height"]
                self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height)

            self.cuts_panel.refresh_table()
            self.current_project_path = path
            self.setWindowTitle(f"LaserForge - {os.path.basename(path)}")
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(f"Loaded project {path}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Project", f"Failed to load project: {e}")

    def save_project(self):
        if not self.current_project_path:
            self.save_project_as()
        else:
            self._do_save(self.current_project_path)

    def save_project_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save LaserForge Project", "project.laserproj", "LaserForge Projects (*.laserproj);;All Files (*)"
        )
        if path:
            self.current_project_path = path
            self._do_save(path)

    def _do_save(self, path: str):
        try:
            entities = self.scene.get_all_entities()
            machine_dict = {
                "bed_width": self.settings.bed_width,
                "bed_height": self.settings.bed_height,
                "origin_corner": self.settings.origin_corner
            }
            ProjectIO.save_project(path, entities, self.layer_manager, machine_dict)
            self.setWindowTitle(f"LaserForge - {os.path.basename(path)}")
            self.statusBar().showMessage(f"Project saved to {path}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Error Saving Project", f"Failed to save project: {e}")

    def import_svg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import SVG Vector", "", "Scalable Vector Graphics (*.svg);;All Files (*)"
        )
        if not path:
            return

        try:
            entities = ProjectIO.import_svg(path, self.scene.active_layer_id)
            for ent in entities:
                self.scene.add_entity(ent)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(f"Imported {len(entities)} paths from SVG", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Error Importing SVG", f"Failed to parse SVG: {e}")

    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Bitmap Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )
        if not path:
            return

        try:
            from PIL import Image as PILImage
            with PILImage.open(path) as img:
                orig_w, orig_h = img.size

            # Default to 80mm width maintaining aspect ratio
            aspect = orig_h / max(1, orig_w)
            target_w = 80.0
            target_h = target_w * aspect

            # Center in bed
            x = (self.settings.bed_width - target_w) / 2.0
            y = (self.settings.bed_height - target_h) / 2.0

            img_ent = ImageEntity(
                layer_id=self.scene.active_layer_id,
                name=os.path.basename(path),
                x=x, y=y,
                width=target_w, height=target_h,
                image_path=path,
                dither_mode="floyd_steinberg",
                dpi=254.0 # 0.1mm interval
            )
            self.scene.add_entity(img_ent)
            self.statusBar().showMessage(f"Imported image {os.path.basename(path)}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Error Importing Image", f"Failed to import image: {e}")

    def export_gcode(self):
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Export G-Code", "Canvas is empty. Draw or import shapes first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export G-Code", "laser_job.nc", "G-Code Files (*.nc *.gcode);;All Files (*)"
        )
        if not path:
            return

        try:
            job = self.gcode_gen.generate_job(entities)
            with open(path, "w", encoding="utf-8") as f:
                f.write(job.gcode)
            self.statusBar().showMessage(f"G-Code exported successfully to {path}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to generate G-Code: {e}")

    # Laser Operations
    def preview_simulation(self):
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.information(self, "Preview", "Canvas is empty. Add shapes to preview.")
            return

        try:
            job = self.gcode_gen.generate_job(entities)
            dlg = PreviewDialog(job, self)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Preview Error", f"Failed to generate preview: {e}")

    def frame_job(self):
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Frame Error", "Laser is not connected. Please connect in the Laser tab first.")
            return

        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Frame Error", "Canvas is empty.")
            return

        frame_gcode = self.gcode_gen.generate_framing_gcode(entities)
        if not frame_gcode:
            QMessageBox.warning(self, "Frame Error", "Could not calculate bounding box for framing.")
            return

        self.serial_ctrl.start_job(frame_gcode)
        self.statusBar().showMessage("Framing bounding box with laser guide beam...", 3000)

    def start_job(self):
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Start Error", "Laser is not connected. Please connect in the Laser tab first.")
            return

        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Start Error", "Canvas is empty.")
            return

        # Confirm job execution
        res = QMessageBox.question(
            self, "Start Job",
            "Are laser safety glasses on and work area clear?\nStart laser engraving job now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            job = self.gcode_gen.generate_job(entities)
            self.serial_ctrl.start_job(job.gcode)
            self.statusBar().showMessage("Laser job streaming started.", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Execution Error", f"Failed to generate and stream G-code: {e}")

    def _toggle_pause_job(self):
        if hasattr(self, "laser_panel"):
            self.laser_panel._toggle_pause()
        elif self.serial_ctrl.is_streaming:
            if self.serial_ctrl.is_paused:
                self.serial_ctrl.resume_job()
            else:
                self.serial_ctrl.pause_job()

    def open_machine_settings(self):

        dlg = MachineSettingsDialog(self.settings, self)
        if dlg.exec() == MachineSettingsDialog.DialogCode.Accepted:
            self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage("Machine settings updated.", 3000)

    def _show_about(self):
        QMessageBox.about(
            self, "About LaserForge",
            "<h3>LaserForge - Laser Engraving & Cutting Suite</h3>"
            "<p>A professional LightBurn alternative for Linux and GRBL laser engravers.</p>"
            "<ul>"
            "<li>Interactive 2D CAD with millimeter rulers and grid</li>"
            "<li>Multi-layer Cut/Fill/Image CAM engine</li>"
            "<li>Floyd-Steinberg & Atkinson photo dithering</li>"
            "<li>Real-time USB Serial GRBL controller with 8-way jogging</li>"
            "<li>Animated toolpath simulation preview & ETA calculator</li>"
            "</ul>"
            "<p><i>Built for makers and fabricators.</i></p>"
        )
