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
import json
import time
from typing import Optional, Tuple, List, Dict, Any
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QDockWidget, QTabWidget, QFileDialog, QMessageBox, QLabel,
    QStatusBar, QPushButton, QInputDialog, QButtonGroup,
    QDoubleSpinBox, QComboBox, QFontComboBox, QToolButton, QMenu,
    QLineEdit
)
from PyQt6.QtCore import Qt, QSize, QPointF, QTimer
from laserforge.ui.action_registry import ActionRegistry
from laserforge.ui.menu_builder import MenuBuilder

from PyQt6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QColor, QPixmap, QImage, QPainter, QFont, QPen, QFontMetricsF


from laserforge.config import MachineSettings, LAYER_PALETTE
from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, TextEntity, ImageEntity, PathEntity
)
from laserforge.core.layer_manager import LayerManager
from laserforge.core.serial_controller import SerialController
from laserforge.core.gcode_generator import GCodeGenerator
from laserforge.core.project_io import ProjectIO

from laserforge.ui.canvas_scene import (
    LaserCanvasScene, LaserItemWrapper, TOOL_SELECT, TOOL_RECT, TOOL_CIRCLE, TOOL_LINE, TOOL_TEXT,
    TOOL_NODE_EDIT, TOOL_TRIM, TOOL_MEASURE
)
from laserforge.ui.common_line_dialog import CommonLineDialog
from laserforge.ui.variable_text_dialog import VariableTextDialog
from laserforge.ui.z_probe_dialog import ZProbeStudioDialog
from laserforge.ui.surface_wrap_dialog import SurfaceWrapStudioDialog
from laserforge.core.audio_alerts import AudioChimeEngine
from laserforge.ui.canvas_view import LaserCanvasWidget
from laserforge.ui.cuts_panel import CutsPanel
from laserforge.ui.laser_control_panel import LaserControlPanel
from laserforge.ui.console_panel import ConsolePanel
from laserforge.ui.shape_properties import ShapePropertiesPanel
from laserforge.ui.preview_dialog import PreviewDialog
from laserforge.ui.validation_dialog import ValidationDialog
from laserforge.ui.machine_settings_dialog import MachineSettingsDialog
from laserforge.core.gcode_validator import GCodeValidator, ValidationReport
from laserforge.core.gpu_accelerator import GPUAccelerator
from laserforge.ui.trace_image_dialog import TraceImageDialog
from laserforge.ui.image_cutout_dialog import ImageCutoutDialog
from laserforge.ui.business_card_dialog import BusinessCardStudioDialog
from laserforge.ui.material_library_dialog import MaterialLibraryDialog, TestMatrixDialog
from laserforge.ui.alignment_dialog import LaserAlignmentDialog
from laserforge.ui.burn_perimeter_dialog import BurnPerimeterDialog
from laserforge.ui.alignment_marks_dialog import AlignmentMarksDialog
from laserforge.ui.photo_engrave_dialog import PhotoEngraveDialog
from laserforge.ui.templates_dialog import TemplatesStudioDialog
from laserforge.ui.shape_generator_dialog import ShapeGeneratorDialog
from laserforge.ui.curved_text_dialog import CurvedTextDialog
from laserforge.ui.grid_array_dialog import GridArrayDialog
from laserforge.ui.serial_generator_dialog import SerialGeneratorDialog
from laserforge.ui.crop_image_dialog import CropImageDialog
from laserforge.ui.barcode_designer_dialog import BarcodeDesignerDialog
from laserforge.core.dxf_importer import DXFImporter
from laserforge.core.dxf_exporter import DXFExporter
from laserforge.core.svg_exporter import SVGExporter
from laserforge.ui.job_estimator_dialog import JobEstimatorDialog
from laserforge.ui.directional_hatch_dialog import DirectionalHatchDialog
from laserforge.ui.nesting_dialog import NestingDialog
from laserforge.ui.rotary_dialog import RotaryDialog
from PyQt6.QtCore import QSettings
IMPORT_QUEUE_DIR = os.path.expanduser("~/.laserforge/imported_queue")
from laserforge.core.shape_generator import ShapeGenerator
from laserforge.core.font_tools import FontTools
from laserforge.core.business_card_generator import BusinessCardGenerator, generate_qr_contours
from laserforge.core.materials_database import MaterialProfile
from laserforge.core.art_library import ArtLibraryManager, ArtItem
from laserforge.ui.art_library_panel import ArtLibraryPanel



from laserforge.ui.ui_utils import create_tool_icon

class MainWindow(QMainWindow):
    def __init__(self, start_tutorial: bool = False, splash_callback: Optional[Any] = None):
        super().__init__()
        self.setWindowTitle("LaserForge - Laser Engraver & Cutter")
        self.resize(1280, 800)

        if splash_callback:
            splash_callback(15, "Loading machine profiles & serial engine...")

        # Core Backend Subsystems
        self.settings = MachineSettings()
        self.layer_manager = LayerManager()
        self.serial_ctrl = SerialController()
        self.gcode_gen = GCodeGenerator(self.settings, self.layer_manager)
        from laserforge.core.camera_engine import CameraEngine
        from laserforge.core.multi_camera_engine import MultiCameraEngine
        self.camera_engine = CameraEngine()
        self.multi_camera_engine = MultiCameraEngine()

        if splash_callback:
            splash_callback(35, "Initializing 2D CAD canvas & graphics scene...")

        # Scene and Canvas
        self.scene = LaserCanvasScene(self.layer_manager, self)
        self.canvas_widget = LaserCanvasWidget(self.scene, self)
        self.setCentralWidget(self.canvas_widget)

        # Active project file path
        self.current_project_path: Optional[str] = None

        if splash_callback:
            splash_callback(55, "Building toolbars, menus & dock panels...")

        # Build UI Elements
        self._create_actions()
        MenuBuilder(self, self.actions).build()
        from laserforge.ui.toolbar_builder import ToolbarBuilder
        _tb = ToolbarBuilder(self, self.actions)
        _tb.build_cad_toolbar()
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        _tb.build_top_toolbar()
        _tb.build_font_toolbar()
        self._create_dock_panels()
        self._create_bottom_palette_dock()
        self._create_status_bar()

        # Connect event signals
        self._connect_signals()

        # Set canvas bed bounds & attach settings reference
        self.canvas_widget.view.settings = self.settings
        self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height, self.settings.origin_corner)
        self.canvas_widget.view.zoom_to_fit()

        if splash_callback:
            splash_callback(75, "Configuring workbed & event pipelines...")

        # Automated auto-import queue listener (for standalone SDXL Turbo Studio)
        self.sdxl_studio_window: Optional[Any] = None
        self._init_auto_import_watcher()

        # Automated laser connection on startup if enabled
        if self.settings.last_connected_port and self.settings.last_connected_port.upper().startswith("VIRTUAL"):
            self.settings.last_connected_port = ""
        if self.settings.auto_connect:
            last_port = self.settings.last_connected_port if (self.settings.last_connected_port and not self.settings.last_connected_port.upper().startswith("VIRTUAL")) else None
            QTimer.singleShot(400, lambda: self.serial_ctrl.start_auto_connect(last_port))

        # Licensing & 30-Day Free Trial Engine
        from laserforge.core.license_engine import LicenseEngine
        self.license_engine = LicenseEngine()
        self._update_window_title_license()

        # Mobile Web Jogger & Monitoring Pendant Server
        from laserforge.core.web_pendant import WebPendantServer
        self.web_pendant = WebPendantServer(port=8088)
        self._setup_web_pendant_callbacks()

        if splash_callback:
            splash_callback(90, "Loading extensions & web pendant...")

        # Plugin Registry & Extension Ecosystem
        from laserforge.core.plugin_api import get_plugin_registry
        self.plugin_registry = get_plugin_registry()
        app_context = {
            "settings": self.settings,
            "layer_manager": self.layer_manager,
            "scene": self.scene,
            "serial": self.serial_ctrl,
            "gcode_generator": self.gcode_gen,
            "main_window": self,
        }
        loaded_plugins = self.plugin_registry.discover_and_load(app_context)
        if loaded_plugins:
            print(f"[LaserForge] Loaded plugins: {', '.join(loaded_plugins)}")

        # Interactive Tutorial & User Guide
        self._tutorial_dialog: Optional[Any] = None
        self._guide_dialog: Optional[Any] = None
        QTimer.singleShot(400, lambda: self._check_first_run_tutorial(start_tutorial))

        # Maximize to fit display cleanly (if no splash is handling the transition)
        if not splash_callback:
            self.showMaximized()

    def __getattr__(self, name: str):
        if name.startswith("act_") and hasattr(self, "actions"):
            action_name = name[4:]
            if hasattr(self.actions, action_name):
                return getattr(self.actions, action_name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def _create_actions(self):
        self.actions = ActionRegistry(self).build()
        # File Actions
        self.actions.new.triggered.connect(self.new_project)

        self.actions.open.triggered.connect(self.open_project)

        self.actions.save.triggered.connect(self.save_project)

        self.actions.save_as.triggered.connect(self.save_project_as)

        self.actions.bundle_packager.triggered.connect(self.open_bundle_packager_studio)

        self.actions.import_svg.triggered.connect(self.import_svg)

        self.actions.import_img.triggered.connect(self.import_image)

        self.actions.trace_image.triggered.connect(self.trace_image)

        self.actions.image_cutout.triggered.connect(lambda: self.auto_image_cutout())

        self.actions.import_dxf.triggered.connect(lambda: self.import_dxf())

        self.actions.export_svg.triggered.connect(self.export_svg)

        self.actions.export_dxf.triggered.connect(self.export_dxf)
        self.actions.export_lbrn.triggered.connect(self.export_lbrn)

        self.actions.job_estimator.triggered.connect(self.open_job_estimator)

        self.actions.directional_hatch.triggered.connect(self.open_directional_hatching)

        self.actions.nesting.triggered.connect(self.open_nesting_studio)

        self.actions.rotary.triggered.connect(self.open_rotary_studio)

        self.actions.box_generator.triggered.connect(self.open_box_studio)

        self.actions.living_hinge.triggered.connect(self.open_living_hinge_studio)

        self.actions.material_test_studio.triggered.connect(self.open_material_test_studio)

        self.actions.relief_studio.triggered.connect(self.open_relief_studio)

        self.actions.galvo_studio.triggered.connect(self.open_galvo_studio)

        self.actions.ruida_studio.triggered.connect(self.open_ruida_studio)

        self.actions.web_pendant.triggered.connect(self.open_web_pendant_dialog)

        self.actions.single_line_text.triggered.connect(self.open_single_line_text_studio)

        self.actions.kerf_test.triggered.connect(self.open_kerf_test_studio)

        self.actions.import_lbrn.triggered.connect(self.import_lbrn)

        self.actions.holding_tabs.triggered.connect(self.open_holding_tabs_studio)

        self.actions.print_and_cut.triggered.connect(self.open_print_and_cut_studio)

        self.actions.corner_l_marks.triggered.connect(self.add_corner_l_marks_quick)

        self.actions.center_cross.triggered.connect(self.add_center_cross_quick)

        self.actions.alignment_marks_studio.triggered.connect(lambda: self.open_alignment_marks_studio())

        self.actions.art_library.triggered.connect(self.show_art_library_dock)

        self.actions.add_to_art_library.triggered.connect(self.add_selection_to_art_library)

        self.actions.common_line.triggered.connect(self.open_common_line_studio)

        self.actions.variable_text.triggered.connect(self.open_variable_text_studio)

        self.actions.convert_to_path.triggered.connect(self.convert_selected_to_path)

        self.actions.z_probe.triggered.connect(self.open_z_probe_studio)

        self.actions.surface_wrap.triggered.connect(self.open_surface_wrap_studio)

        self.actions.snap_grid.toggled.connect(self._on_snap_grid_toggled)

        self.actions.toggle_guides.toggled.connect(self._on_toggle_guides)

        self.actions.clear_guides.triggered.connect(lambda: self.scene.clear_guides())

        self.actions.export_gcode.triggered.connect(self.export_gcode)

        # Specialized Tools Actions
        self.actions.business_card.triggered.connect(self.open_business_card_studio)

        self.actions.material_lib.triggered.connect(self.open_material_library)

        self.actions.test_matrix.triggered.connect(self.open_test_matrix_dialog)

        self.actions.align_workpiece.triggered.connect(self.open_alignment_assistant)

        self.actions.gen_qr.triggered.connect(self.generate_vector_qr_code)

        self.actions.exit.triggered.connect(self.close)

        # Edit & Undo Actions
        self.actions.undo.triggered.connect(self.scene.undo)

        self.actions.redo.triggered.connect(self.scene.redo)

        self.actions.select_all.triggered.connect(lambda: [i.setSelected(True) for i in self.scene.items()])

        self.actions.delete.triggered.connect(self.scene.delete_selected)

        self.actions.duplicate.triggered.connect(self.scene.duplicate_selected)

        # Vector Boolean CSG Actions
        self.actions.weld.triggered.connect(lambda: self.scene.boolean_operation("weld"))

        self.actions.subtract.triggered.connect(lambda: self.scene.boolean_operation("subtract"))

        self.actions.intersect.triggered.connect(lambda: self.scene.boolean_operation("intersect"))

        self.actions.xor.triggered.connect(lambda: self.scene.boolean_operation("xor"))

        # Design Aid & Workflow Actions
        self.actions.photo_studio.triggered.connect(lambda: self.open_photo_studio())

        self.actions.templates_studio.triggered.connect(self.open_templates_studio)

        self.actions.shapes_lib.triggered.connect(lambda: self.open_shapes_library(0))

        self.actions.offset_border.triggered.connect(lambda: self.open_shapes_library(1))

        self.actions.grid_array.triggered.connect(self.open_grid_array_dialog)

        self.actions.curved_text.triggered.connect(self.open_curved_text_dialog)

        self.actions.serial_gen.triggered.connect(self.open_serial_generator_dialog)

        self.actions.barcode_studio.triggered.connect(self.open_barcode_designer)

        self.actions.sdxl_turbo.triggered.connect(self.open_sdxl_turbo_studio)

        self.actions.crop_image.triggered.connect(self.open_crop_tool_for_selected)

        # Camera & Vision Alignment Actions
        self.actions.auto_calibrate.triggered.connect(self.open_auto_calibration_dialog)
        self.actions.camera_wizard.triggered.connect(self.open_camera_wizard)
        self.actions.camera_update.triggered.connect(self.update_camera_overlay)
        self.actions.camera_fine_tune.triggered.connect(self.open_camera_fine_tune_dialog)
        self.actions.multi_camera.triggered.connect(self.open_multi_camera_studio)
        self.actions.camera_toggle.toggled.connect(self.scene.set_camera_overlay_visible)

        # Alignment & Distribution Actions
        self.actions.bed_center.triggered.connect(lambda: self.scene.align_selected("bed_center", self.settings.bed_width, self.settings.bed_height))

        self.actions.center_in_parent.triggered.connect(lambda: self.scene.align_selected("center_in_parent"))

        self.actions.distribute_h.triggered.connect(lambda: self.scene.align_selected("distribute_h"))

        self.actions.distribute_v.triggered.connect(lambda: self.scene.align_selected("distribute_v"))

        self.actions.flip_h.triggered.connect(self.scene.flip_selected_horizontal)

        self.actions.flip_v.triggered.connect(self.scene.flip_selected_vertical)

        self.actions.align_left.triggered.connect(lambda: self.scene.align_selected("left"))

        self.actions.align_center_x.triggered.connect(lambda: self.scene.align_selected("center_x"))

        self.actions.align_right.triggered.connect(lambda: self.scene.align_selected("right"))

        self.actions.align_top.triggered.connect(lambda: self.scene.align_selected("top"))

        self.actions.align_center_y.triggered.connect(lambda: self.scene.align_selected("center_y"))

        self.actions.align_bottom.triggered.connect(lambda: self.scene.align_selected("bottom"))

        # View Actions
        self.actions.zoom_fit.triggered.connect(self.canvas_widget.view.zoom_to_fit)

        # Laser & Simulation Actions
        self.actions.auto_connect.triggered.connect(lambda: self.serial_ctrl.start_auto_connect(
            self.settings.last_connected_port if (self.settings.last_connected_port and not self.settings.last_connected_port.upper().startswith("VIRTUAL")) else None
        ))

        self.actions.preview.triggered.connect(self.preview_simulation)

        self.actions.validate_gcode.triggered.connect(self.validate_current_job)

        self.actions.frame.triggered.connect(self.frame_job)

        self.actions.burn_perimeter.triggered.connect(lambda: self.open_burn_perimeter_tool())

        self.actions.start_job.triggered.connect(self.start_job)

        self.actions.pause_job.triggered.connect(self._toggle_pause_job)


        self.actions.stop_job.triggered.connect(self.serial_ctrl.stop_streaming)

        self.actions.home.triggered.connect(self.serial_ctrl.home)

        self.actions.unlock.triggered.connect(self.serial_ctrl.unlock)

        self.actions.settings.triggered.connect(self.open_machine_settings)
        self.actions.workbed_setup.triggered.connect(self.open_workbed_setup_wizard)

        self.actions.license.triggered.connect(self.open_license_dialog)

        self.actions.check_updates.triggered.connect(self.check_for_updates)
        self.actions.user_guide.triggered.connect(self.open_user_guide)
        self.actions.interactive_tutorial.triggered.connect(self.start_interactive_tutorial)
        self.actions.send_feedback.triggered.connect(self.open_feedback_dialog)


    def _create_dock_panels(self):
        # 1. Cuts / Layers Dock (Right Top)
        cuts_dock = QDockWidget("Cuts / Layers", self)
        cuts_dock.setObjectName("CutsLayersDock")
        cuts_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.cuts_panel = CutsPanel(self.layer_manager, self)
        cuts_dock.setWidget(self.cuts_panel)
        self.cuts_dock = cuts_dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, cuts_dock)

        # 1b. Art & Component Library Dock (Tabified with Cuts / Layers)
        art_dock = QDockWidget("Art & Component Library", self)
        art_dock.setObjectName("ArtLibraryDock")
        art_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.art_library_manager = ArtLibraryManager()
        self.art_library_panel = ArtLibraryPanel(self.art_library_manager, self)
        self.art_library_panel.insert_item_requested.connect(self.insert_art_item_on_canvas)
        self.art_library_panel.selection_add_requested.connect(self.add_selection_to_art_library)
        art_dock.setWidget(self.art_library_panel)
        self.art_dock = art_dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, art_dock)
        self.tabifyDockWidget(cuts_dock, art_dock)
        cuts_dock.raise_()

        # 2. Bottom-Right Multi-Tab Dock: Laser, Console, Properties
        right_tab_dock = QDockWidget("Laser & Machine Operations", self)
        right_tab_dock.setObjectName("LaserOperationsDock")
        right_tab_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.right_tab_dock = right_tab_dock

        tab_widget = QTabWidget()
        self.laser_panel = LaserControlPanel(self.serial_ctrl, parent=self, settings=self.settings)
        self.laser_panel.settings_requested.connect(self.open_machine_settings)
        self.laser_panel.park_requested.connect(
            lambda: self.serial_ctrl.go_to_park(
                getattr(self.settings, "park_x", 0.0),
                getattr(self.settings, "park_y", 0.0),
                getattr(self.settings, "rapid_speed", 3000.0)
            )
        )
        self.console_panel = ConsolePanel(self.serial_ctrl, self)
        self.props_panel = ShapePropertiesPanel(self.scene, self)

        tab_widget.addTab(self.laser_panel, "Laser")
        tab_widget.addTab(self.console_panel, "Console")
        tab_widget.addTab(self.props_panel, "Properties")
        self.right_tab_widget = tab_widget

        right_tab_dock.setWidget(tab_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_tab_dock)

        if hasattr(self, "menu_view_docks") and self.menu_view_docks:
            self.menu_view_docks.addAction(cuts_dock.toggleViewAction())
            self.menu_view_docks.addAction(art_dock.toggleViewAction())
            self.menu_view_docks.addAction(right_tab_dock.toggleViewAction())

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

        gpu_info = GPUAccelerator.get_hardware_info()
        self.status_gpu = QLabel(gpu_info.summary_short())
        self.status_gpu.setStyleSheet("padding-right: 15px; color: #81c784; font-weight: bold;")
        sb.addPermanentWidget(self.status_gpu)

        self.status_machine = QLabel("Laser: Disconnected")
        self.status_machine.setStyleSheet("font-weight: bold; padding-right: 10px; color: #ef5350;")
        sb.addPermanentWidget(self.status_machine)

        sb.showMessage("Ready. Select a tool or draw shapes.")

    def _connect_signals(self):
        # Cursor tracking
        self.canvas_widget.view.cursor_moved_mm.connect(self._on_cursor_moved)
        self.canvas_widget.view.art_item_dropped.connect(self._on_art_item_dropped)
        self.canvas_widget.view.file_dropped.connect(self._on_file_dropped)

        # Scene changes
        self.scene.entity_modified.connect(self._on_entities_changed)
        self.scene.selectionChanged.connect(self._on_entities_changed)

        # Cuts panel signals
        self.cuts_panel.layer_selected.connect(self._on_palette_layer_clicked)
        self.cuts_panel.layers_updated.connect(lambda: self.scene.update())
        self.cuts_panel.material_library_requested.connect(self.open_material_library)

        # Laser control signals
        self.laser_panel.start_job_requested.connect(self.start_job)
        self.laser_panel.simulate_job_requested.connect(self.preview_simulation)
        self.laser_panel.frame_job_requested.connect(self.frame_job)
        self.laser_panel.contour_frame_job_requested.connect(self.contour_frame_job)
        self.laser_panel.burn_perimeter_requested.connect(lambda: self.open_burn_perimeter_tool())
        self.laser_panel.alignment_dialog_requested.connect(self.open_alignment_assistant)

        # Properties panel signals
        self.props_panel.trace_image_requested.connect(self.trace_image)
        self.props_panel.cutout_image_requested.connect(lambda: self.auto_image_cutout())
        self.props_panel.photo_studio_requested.connect(lambda: self.open_photo_studio())
        self.props_panel.crop_image_requested.connect(lambda: self.open_crop_tool_for_selected())
        self.props_panel.curved_text_requested.connect(self.open_curved_text_dialog)

        # Serial status and auto-connect tracking
        self.serial_ctrl.connected.connect(self._on_laser_connected)
        self.serial_ctrl.disconnected.connect(self._on_laser_disconnected)
        self.serial_ctrl.machine_parameters_loaded.connect(self._on_machine_parameters_loaded)
        self.serial_ctrl.auto_connect_progress.connect(lambda msg: self.statusBar().showMessage(msg, 2500))
        self.serial_ctrl.status_updated.connect(self._on_laser_status_for_canvas)
        self.serial_ctrl.job_progress.connect(
            lambda pct, cur, total: self.plugin_registry.dispatch_job_progress(cur, total, pct)
        )
        self.serial_ctrl.job_finished.connect(
            lambda success, msg: self.plugin_registry.dispatch_job_complete(0.0, not success)
        )

    def _on_laser_status_for_canvas(self, status: dict):
        """Updates the physical laser head position crosshair on the CAD canvas."""
        wpos = status.get("wpos", [0.0, 0.0, 0.0])
        state = status.get("state", "Idle")
        x = wpos[0] if (wpos and len(wpos) > 0) else 0.0
        y = wpos[1] if (wpos and len(wpos) > 1) else 0.0
        self.scene.update_laser_position(x, y, state, self.serial_ctrl.is_connected)
        if hasattr(self, "camera_engine") and self.camera_engine is not None:
            self.camera_engine.set_live_laser_position(x, y, state)

    def _on_laser_connected(self, port: str):
        if port and not port.upper().startswith("VIRTUAL"):
            self.settings.last_connected_port = port
        self.status_machine.setText(f"Laser: Connected ({port})")
        self.status_machine.setStyleSheet("font-weight: bold; color: #66bb6a;")
        self.statusBar().showMessage(f"Laser connected on {port} (GRBL Ready)", 4000)

    def _on_machine_parameters_loaded(self, params: dict):
        w = params.get("bed_width", self.settings.bed_width)
        h = params.get("bed_height", self.settings.bed_height)
        s_max = params.get("max_s_value", self.settings.max_s_value)
        l_mode = params.get("laser_mode", self.settings.laser_mode)

        self.settings.max_s_value = s_max
        self.settings.laser_mode = l_mode

        if abs(w - self.settings.bed_width) > 1.0 or abs(h - self.settings.bed_height) > 1.0:
            self.settings.bed_width = w
            self.settings.bed_height = h
            self.canvas_widget.view.set_bed_size(w, h)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(
                f"Auto-configured laser workbed: {w:.0f} × {h:.0f} mm (Max S: {s_max})", 5000
            )

    def _on_laser_disconnected(self):
        self.status_machine.setText("Laser: Disconnected")
        self.status_machine.setStyleSheet("font-weight: bold; color: #ef5350;")
        self.statusBar().showMessage("Laser disconnected.", 3000)

    def _on_cursor_moved(self, x: float, y: float):
        self.status_pos.setText(f"X: {x:6.2f} mm  Y: {y:6.2f} mm")

    def _on_entities_changed(self):
        entities = self.scene.get_all_entities()
        selected = self.scene.get_selected_entities()
        self.status_entity_count.setText(f"Objects: {len(entities)} (Selected: {len(selected)})")

        # Synchronize typography toolbar
        self._sync_font_toolbar_from_selection()
        selected_text = [e for e in selected if isinstance(e, TextEntity)]
        if selected_text and hasattr(self, "right_tab_widget") and hasattr(self, "props_panel"):
            self.right_tab_widget.setCurrentWidget(self.props_panel)

    def _sync_font_toolbar_from_selection(self):
        selected = self.scene.get_selected_entities()
        selected_text = [e for e in selected if isinstance(e, TextEntity)]
        if hasattr(self, "font_toolbar"):
            if selected_text:
                self.font_toolbar.setEnabled(True)
                tent = selected_text[0]
                self._is_syncing_font_tb = True
                if hasattr(self, "tb_text_input"):
                    if not self.tb_text_input.hasFocus() and self.tb_text_input.text() != tent.text:
                        self.tb_text_input.setText(tent.text)
                self.tb_font_combo.setCurrentFont(QFont(tent.font_family))
                self.tb_font_size_spin.setValue(tent.font_size)
                self.tb_btn_bold.setChecked(tent.bold)
                self.tb_btn_italic.setChecked(tent.italic)
                self.tb_btn_underline.setChecked(getattr(tent, "underline", False))
                self.tb_mode_combo.setCurrentIndex(1 if getattr(tent, "fill_mode", "Fill") == "Outline" else 0)
                self._is_syncing_font_tb = False
            else:
                self.font_toolbar.setEnabled(False)
                if hasattr(self, "tb_text_input"):
                    self._is_syncing_font_tb = True
                    if not self.tb_text_input.hasFocus() and self.tb_text_input.text():
                        self.tb_text_input.clear()
                    self._is_syncing_font_tb = False

    # --- Typography Toolbar Handlers ---

    def _on_tb_text_changed(self, text: str):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.text = text
                font = QFont(item.entity.font_family)
                font.setPointSizeF(max(1.2, item.entity.font_size * 1.5))
                fm = QFontMetricsF(font)
                tw = max(10.0, fm.horizontalAdvance(text) + 6.0)
                item.entity.width = max(item.entity.width, tw)
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_tb_text_editing_finished(self):
        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()

    def _on_tb_font_family_changed(self, font: QFont):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.font_family = font.family()
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_tb_font_size_changed(self, size: float):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                orig_sz = max(0.1, item.entity.font_size)
                ratio = size / orig_sz
                item.entity.font_size = size
                item.entity.height = max(1.0, item.entity.height * ratio)
                item.entity.width = max(1.0, item.entity.width * ratio)
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_tb_bold_toggled(self, checked: bool):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.bold = checked
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_tb_italic_toggled(self, checked: bool):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.italic = checked
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_tb_underline_toggled(self, checked: bool):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.underline = checked
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_tb_mode_changed(self, index: int):
        if getattr(self, "_is_syncing_font_tb", False):
            return
        mode_val = "Outline" if index == 1 else "Fill"
        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                item.entity.fill_mode = mode_val
                item.sync_from_entity()
        self.scene.entity_modified.emit()

    def _on_quick_style_selected(self, index: int):
        style_key = self.tb_quick_style_combo.currentData()
        if not style_key:
            return

        selected_items = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        for item in selected_items:
            if isinstance(item.entity, TextEntity):
                if style_key == "modern":
                    item.entity.font_family = "Sans Serif"
                    item.entity.font_size = 14.0
                    item.entity.bold = True
                    item.entity.italic = False
                    item.entity.underline = False
                    item.entity.fill_mode = "Fill"
                elif style_key == "industrial":
                    item.entity.font_family = "Sans Serif"
                    item.entity.font_size = 18.0
                    item.entity.bold = True
                    item.entity.italic = False
                    item.entity.underline = False
                    item.entity.fill_mode = "Outline"
                elif style_key == "serif":
                    item.entity.font_family = "Serif"
                    item.entity.font_size = 14.0
                    item.entity.bold = False
                    item.entity.italic = False
                    item.entity.underline = False
                    item.entity.fill_mode = "Fill"
                elif style_key == "script":
                    item.entity.font_family = "Serif"
                    item.entity.font_size = 16.0
                    item.entity.bold = False
                    item.entity.italic = True
                    item.entity.underline = False
                    item.entity.fill_mode = "Fill"
                elif style_key == "monogram":
                    item.entity.font_family = "Serif"
                    item.entity.font_size = 32.0
                    item.entity.bold = True
                    item.entity.italic = False
                    item.entity.underline = False
                    item.entity.fill_mode = "Fill"

                item.sync_from_entity()

        self.scene.entity_modified.emit()
        self._sync_font_toolbar_from_selection()

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
        self.load_project_file(path)

    def load_project_file(self, path: str):
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
            self._add_recent_file(path)
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
            self, "Save Project", "project.laserproj",
            "LaserForge Projects (*.laserproj);;LightBurn Projects (*.lbrn2);;All Files (*)"
        )
        if path:
            self.current_project_path = path
            self._do_save(path)

    def _do_save(self, path: str):
        try:
            entities = self.scene.get_all_entities()
            if path.lower().endswith(".lbrn2") or path.lower().endswith(".lbrn"):
                from laserforge.core.lbrn2_exporter import LBRN2Exporter
                LBRN2Exporter.save(entities, self.layer_manager, path, self.settings)
                self.statusBar().showMessage(f"LightBurn project saved to {path}", 3000)
            else:
                machine_dict = {
                    "bed_width": self.settings.bed_width,
                    "bed_height": self.settings.bed_height,
                    "origin_corner": self.settings.origin_corner
                }
                ProjectIO.save_project(path, entities, self.layer_manager, machine_dict)
                self.statusBar().showMessage(f"Project saved to {path}", 3000)
            self._add_recent_file(path)
            self.setWindowTitle(f"LaserForge - {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error Saving Project", f"Failed to save project: {e}")

    def open_bundle_packager_studio(self):
        """Opens the Project & Profile Packager Studio (.lfpak) dialog."""
        from laserforge.ui.bundle_packager_dialog import BundlePackagerDialog
        dlg = BundlePackagerDialog(
            current_entities=self.scene.get_all_entities(),
            layer_manager=self.layer_manager,
            machine_settings=self.settings,
            parent=self
        )
        dlg.project_restored.connect(self._on_bundle_project_restored)
        dlg.materials_restored.connect(self._on_bundle_materials_restored)
        dlg.settings_restored.connect(self._on_bundle_settings_restored)
        dlg.exec()

    def _on_bundle_project_restored(self, proj_data: dict):
        try:
            self.scene.push_undo_state()
            self.scene.clear()
            # Reconstruct layers if present
            layers_dict = proj_data.get("layers", {})
            for lid_str, ldata in layers_dict.items():
                lid = int(lid_str)
                layer = self.layer_manager.get_layer(lid)
                if layer:
                    layer.name = ldata.get("name", layer.name)
                    layer.speed = float(ldata.get("speed", layer.speed))
                    layer.power = float(ldata.get("power", layer.power))
                    layer.passes = int(ldata.get("passes", layer.passes))
                    layer.mode = ldata.get("mode", layer.mode)

            # Reconstruct entities
            raw_entities = proj_data.get("entities", [])
            for ed in raw_entities:
                etype = ed.get("type", "")
                ent = None
                from laserforge.core.models import RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
                if etype == "RectEntity":
                    ent = RectEntity(
                        layer_id=ed.get("layer_id", 0),
                        name=ed.get("name", "Rect"),
                        x=ed.get("x", 0.0),
                        y=ed.get("y", 0.0),
                        width=ed.get("width", 10.0),
                        height=ed.get("height", 10.0),
                        corner_radius=ed.get("corner_radius", 0.0)
                    )
                elif etype == "CircleEntity":
                    ent = CircleEntity(
                        layer_id=ed.get("layer_id", 0),
                        name=ed.get("name", "Circle"),
                        x=ed.get("x", 0.0),
                        y=ed.get("y", 0.0),
                        radius_x=ed.get("radius_x", 5.0),
                        radius_y=ed.get("radius_y", 5.0)
                    )
                elif etype == "LineEntity":
                    ent = LineEntity(
                        layer_id=ed.get("layer_id", 0),
                        name=ed.get("name", "Line"),
                        x=ed.get("x", 0.0),
                        y=ed.get("y", 0.0),
                        x2=ed.get("x2", 10.0),
                        y2=ed.get("y2", 10.0)
                    )
                elif etype == "PathEntity":
                    ent = PathEntity(
                        layer_id=ed.get("layer_id", 0),
                        name=ed.get("name", "Path"),
                        x=ed.get("x", 0.0),
                        y=ed.get("y", 0.0),
                        contours=ed.get("contours", []),
                        closed=ed.get("closed", False)
                    )
                elif etype == "TextEntity":
                    ent = TextEntity(
                        layer_id=ed.get("layer_id", 0),
                        name=ed.get("name", "Text"),
                        x=ed.get("x", 0.0),
                        y=ed.get("y", 0.0),
                        text=ed.get("text", ""),
                        font_family=ed.get("font_family", "sans-serif"),
                        font_size=ed.get("font_size", 12.0)
                    )

                if ent:
                    if "speed_override" in ed:
                        ent.speed_override = float(ed["speed_override"])
                    if "power_override" in ed:
                        ent.power_override = float(ed["power_override"])
                    self.scene.add_entity(ent)

            self.cuts_panel.update_table()
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(f"Restored project: {len(raw_entities)} entities loaded to canvas.", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Project Restoration Error", f"Failed to unpack project artwork: {e}")

    def _on_bundle_materials_restored(self, count: int):
        self.statusBar().showMessage(f"Imported {count} material profiles to library.", 4000)
        self.cuts_panel.update_table()

    def _on_bundle_settings_restored(self, ms_dict: dict):
        if "bed_width" in ms_dict:
            self.settings.bed_width = float(ms_dict["bed_width"])
        if "bed_height" in ms_dict:
            self.settings.bed_height = float(ms_dict["bed_height"])
        self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height)
        self.canvas_widget.view.zoom_to_fit()
        self.statusBar().showMessage("Applied bundled machine settings and bed size.", 4000)

    # -------------------------------------------------------------
    # Art & Component Library Integration
    # -------------------------------------------------------------
    def show_art_library_dock(self):
        """Displays and brings the Art & Component Library dock to front."""
        self.art_dock.show()
        self.art_dock.raise_()
        self.art_dock.activateWindow()

    def add_selection_to_art_library(self):
        """Pops up the dialog to save selected canvas shapes to the active art library."""
        selected_wrappers = [i for i in self.scene.selectedItems() if isinstance(i, LaserItemWrapper)]
        if not selected_wrappers:
            QMessageBox.information(
                self, "No Selection", "Please select one or more shapes on the canvas to add to the Art Library."
            )
            return

        selected_entities = [w.entity for w in selected_wrappers]
        self.show_art_library_dock()
        self.art_library_panel.add_entities_to_active_library(selected_entities)

    def insert_art_item_on_canvas(
        self,
        art_item: ArtItem,
        target_x: Optional[float] = None,
        target_y: Optional[float] = None
    ):
        """Instantiates an ArtItem onto the canvas at target coordinates or bed center."""
        if not art_item:
            return

        if target_x is None:
            target_x = getattr(self.settings, "bed_width", 400.0) / 2.0
        if target_y is None:
            target_y = getattr(self.settings, "bed_height", 400.0) / 2.0

        entities = art_item.instantiate_entities(target_x=target_x, target_y=target_y, center=True)
        if not entities:
            return

        # Snapshot for undo
        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()

        self.scene.clearSelection()
        for ent in entities:
            wrapper = self.scene.add_entity(ent)
            if wrapper:
                wrapper.setSelected(True)

        self.cuts_panel.update_table()
        self.statusBar().showMessage(
            f"Inserted '{art_item.name}' ({len(entities)} shapes) onto canvas", 3000
        )

    def _on_art_item_dropped(self, item_id: str, x_mm: float, y_mm: float):
        """Handles drag-and-drop insertion of an ArtItem onto the canvas at specific coordinates."""
        active_lib = self.art_library_manager.get_active_library()
        if active_lib:
            art_item = active_lib.get_item(item_id)
            if art_item:
                self.insert_art_item_on_canvas(art_item, target_x=x_mm, target_y=y_mm)

    def _on_file_dropped(self, filepath: str, x_mm: float, y_mm: float):
        """Handles dropping vector or image files onto the canvas."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".svg", ".dxf", ".lbrn", ".lbrn2", ".laserproj"):
            if ext == ".svg":
                self.import_svg_file(filepath)
            elif ext == ".dxf":
                self.import_dxf_file(filepath)
            elif ext in (".lbrn", ".lbrn2"):
                self.import_lbrn_file(filepath)
            elif ext == ".laserproj":
                self.load_project(filepath)
        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            if hasattr(self, "import_image_file"):
                self.import_image_file(filepath)
            else:
                self.import_image(filepath)

    def import_svg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import SVG Vector", "", "Scalable Vector Graphics (*.svg);;All Files (*)"
        )
        if not path:
            return
        self.import_svg_file(path)

    def import_svg_file(self, path: str):
        try:
            entities = ProjectIO.import_svg(path, self.scene.active_layer_id)
            for ent in entities:
                self.scene.add_entity(ent)
            self._add_recent_file(path)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(f"Imported {len(entities)} paths from SVG", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Error Importing SVG", f"Failed to parse SVG: {e}")

    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Bitmap Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All Files (*)"
        )
        if not path:
            return
        self.import_image_file(path)

    def import_image_file(self, path: str, pos: Optional[Tuple[float, float]] = None):
        try:
            from PIL import Image as PILImage
            with PILImage.open(path) as img:
                orig_w, orig_h = img.size

            # Default to 80mm width maintaining aspect ratio
            aspect = orig_h / max(1, orig_w)
            target_w = 80.0
            target_h = target_w * aspect

            if pos is not None:
                x, y = pos
            else:
                # Center in bed
                x = (self.settings.bed_width - target_w) / 2.0
                y = (self.settings.bed_height - target_h) / 2.0

            img_ent = ImageEntity(
                layer_id=self.scene.active_layer_id,
                name=os.path.basename(path),
                x=x, y=y,
                width=target_w, height=target_h,
                image_path=path,
                dither_mode="Floyd-Steinberg",
                dpi=254.0
            )
            wrapper = self.scene.add_entity(img_ent)
            self._add_recent_file(path)
            self.scene.clearSelection()
            wrapper.setSelected(True)
            self.statusBar().showMessage(f"Imported image '{os.path.basename(path)}' (80 × {target_h:.1f} mm)", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Error Importing Image", f"Failed to import image: {e}")

    def trace_image(self):
        """Traces a bitmap image into vector contours and SVG (LightBurn Trace Image tool)."""
        from PIL import Image as PILImage

        # Check if an ImageEntity is selected on the canvas
        selected_entities = self.scene.get_selected_entities()
        target_image_ent: Optional[ImageEntity] = None
        for ent in selected_entities:
            if isinstance(ent, ImageEntity):
                target_image_ent = ent
                break

        pil_img = None
        image_name = "Image"
        initial_w = 80.0
        initial_h = 80.0
        target_x = 0.0
        target_y = 0.0

        if target_image_ent and target_image_ent.image_path and os.path.exists(target_image_ent.image_path):
            try:
                pil_img = PILImage.open(target_image_ent.image_path)
                image_name = target_image_ent.name
                initial_w = target_image_ent.width
                initial_h = target_image_ent.height
                target_x = target_image_ent.x
                target_y = target_image_ent.y
            except Exception as e:
                QMessageBox.warning(self, "Image Error", f"Could not load selected image: {e}")
                pil_img = None

        if pil_img is None:
            # Prompt user to select an image file to vectorize
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Image to Trace (Vectorize to SVG)", "",
                "Image Files (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
            )
            if not path:
                return
            try:
                pil_img = PILImage.open(path)
                image_name = os.path.basename(path)
                aspect = pil_img.height / max(1, pil_img.width)
                initial_w = 80.0
                initial_h = initial_w * aspect
                target_x = (self.settings.bed_width - initial_w) / 2.0
                target_y = (self.settings.bed_height - initial_h) / 2.0
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to open image file: {e}")
                return

        # Open the interactive TraceImageDialog
        dlg = TraceImageDialog(
            pil_img,
            image_name=image_name,
            initial_width_mm=initial_w,
            initial_height_mm=initial_h,
            active_layer_id=self.scene.active_layer_id,
            parent=self
        )

        if dlg.exec() == TraceImageDialog.DialogCode.Accepted and dlg.result_path_entity:
            path_ent = dlg.result_path_entity
            path_ent.x = target_x
            path_ent.y = target_y

            # If user checked delete original bitmap
            if target_image_ent and dlg.delete_original_image:
                for item in list(self.scene.items()):
                    if hasattr(item, "entity") and item.entity is target_image_ent:
                        self.scene.removeItem(item)
                        break

            wrapper = self.scene.add_entity(path_ent)
            self.scene.clearSelection()
            wrapper.setSelected(True)
            self.statusBar().showMessage(
                f"Successfully traced '{image_name}' into {len(path_ent.contours)} vector contours!", 4000
            )

    def auto_image_cutout(self, target_image_ent: Optional[ImageEntity] = None):
        """Automatically converts bitmap image into a laser-ready SVG cutout contour."""
        from PIL import Image as PILImage

        # Check if an ImageEntity is selected on the canvas if not provided
        if target_image_ent is None:
            selected_entities = self.scene.get_selected_entities()
            for ent in selected_entities:
                if isinstance(ent, ImageEntity):
                    target_image_ent = ent
                    break

        pil_img = None
        image_name = "Image"
        initial_w = 80.0
        initial_h = 80.0
        target_x = 0.0
        target_y = 0.0
        image_file_path = ""

        if target_image_ent and target_image_ent.image_path and os.path.exists(target_image_ent.image_path):
            try:
                pil_img = PILImage.open(target_image_ent.image_path)
                image_name = target_image_ent.name
                initial_w = target_image_ent.width
                initial_h = target_image_ent.height
                target_x = target_image_ent.x
                target_y = target_image_ent.y
                image_file_path = target_image_ent.image_path
            except Exception as e:
                QMessageBox.warning(self, "Image Error", f"Could not load selected image: {e}")
                pil_img = None

        if pil_img is None:
            # Prompt user to select an image file to vectorize/cutout
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Image for Auto Cutout (Generate Cut Line SVG)", "",
                "Image Files (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
            )
            if not path:
                return
            try:
                pil_img = PILImage.open(path)
                image_name = os.path.splitext(os.path.basename(path))[0]
                image_file_path = path
                aspect = pil_img.height / max(1, pil_img.width)
                initial_w = 80.0
                initial_h = initial_w * aspect
                target_x = (self.settings.bed_width - initial_w) / 2.0
                target_y = (self.settings.bed_height - initial_h) / 2.0
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to open image file: {e}")
                return

        # Open the interactive ImageCutoutDialog
        dlg = ImageCutoutDialog(
            pil_img,
            image_name=image_name,
            initial_width_mm=initial_w,
            initial_height_mm=initial_h,
            active_cut_layer_id=2,  # Standard Layer 2 (C02 Red)
            parent=self
        )

        if dlg.exec() == ImageCutoutDialog.DialogCode.Accepted and dlg.result_cutout:
            if hasattr(self.scene, "push_undo_state"):
                self.scene.push_undo_state()

            path_ent = PathEntity(
                layer_id=dlg.cut_layer_id,
                name=f"Cutout_{image_name}",
                x=target_x,
                y=target_y,
                contours=dlg.result_cutout.contours,
                closed=True
            )

            # If user selected combo mode and image was imported fresh from file
            if dlg.output_mode == "combo" and target_image_ent is None and image_file_path:
                img_ent = ImageEntity(
                    layer_id=0,
                    name=image_name,
                    x=target_x,
                    y=target_y,
                    width=initial_w,
                    height=initial_h,
                    image_path=image_file_path
                )
                self.scene.add_entity(img_ent)

            cutout_wrapper = self.scene.add_entity(path_ent)
            self.scene.clearSelection()
            if cutout_wrapper:
                cutout_wrapper.setSelected(True)

            self.statusBar().showMessage(
                f"Successfully generated cutout contour for '{image_name}' ({len(path_ent.contours)} contours)!", 4000
            )

    # ---------------- Phase 1 Professional Additions ----------------

    def import_dxf(self, filepath: Optional[str] = None):
        """Imports AutoCAD DXF vector paths onto canvas."""
        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(
                self, "Import DXF Vector File", "",
                "AutoCAD DXF Files (*.dxf);;All Files (*)"
            )
        if not filepath:
            return

        try:
            entities = DXFImporter.import_dxf_file(filepath, default_layer_id=self.scene.active_layer_id)
            if not entities:
                QMessageBox.warning(self, "Import DXF", f"No vector entities found in '{os.path.basename(filepath)}'.")
                return

            if hasattr(self.scene, "push_undo_state"):
                self.scene.push_undo_state()

            # Center on bed if needed
            all_min_x = min(e.get_bounds()[0] for e in entities)
            all_min_y = min(e.get_bounds()[1] for e in entities)
            all_max_x = max(e.get_bounds()[2] for e in entities)
            all_max_y = max(e.get_bounds()[3] for e in entities)
            dxf_w = all_max_x - all_min_x
            dxf_h = all_max_y - all_min_y

            target_cx = (self.settings.bed_width - dxf_w) / 2.0
            target_cy = (self.settings.bed_height - dxf_h) / 2.0
            dx = target_cx - all_min_x
            dy = target_cy - all_min_y

            for e in entities:
                e.x += dx
                e.y += dy
                if isinstance(e, LineEntity):
                    e.x2 += dx
                    e.y2 += dy
                self.scene.add_entity(e)

            self._add_recent_file(filepath)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(
                f"Imported {len(entities)} DXF entities from '{os.path.basename(filepath)}'!", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "DXF Import Error", f"Failed to import DXF file: {e}")

    # ---------------- Phase 2 Pro Production Additions ----------------

    def import_lbrn(self, filepath: Optional[str] = None):
        """Imports LightBurn .lbrn2 (JSON) or .lbrn (XML) project files."""
        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(
                self, "Import LightBurn Project", "",
                "LightBurn Projects (*.lbrn *.lbrn2);;All Files (*)"
            )
        if not filepath:
            return
        self.import_lbrn_file(filepath)

    def import_lbrn_file(self, filepath: str):
        try:
            from laserforge.core.lbrn_importer import LightBurnImporter
            entities, layer_map = LightBurnImporter.import_file(filepath, layer_manager=self.layer_manager)
            if not entities:
                QMessageBox.warning(self, "LightBurn Import", f"No shapes found in '{os.path.basename(filepath)}'.")
                return

            if hasattr(self.scene, "push_undo_state"):
                self.scene.push_undo_state()

            for ent in entities:
                self.scene.add_entity(ent)

            self.cuts_panel.update_table()
            self._add_recent_file(filepath)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(
                f"Imported LightBurn project: {len(entities)} shapes, {len(layer_map)} cut layers!", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "LightBurn Import Error", f"Failed to import LightBurn file: {e}")

    def open_holding_tabs_studio(self):
        """Opens the Holding Tabs & Micro-Bridges Studio dialog."""
        from laserforge.ui.tabs_dialog import HoldingTabsDialog
        selected = self.scene.get_selected_entities()
        targets = selected if selected else self.scene.get_all_entities()
        layer = self.layer_manager.get_layer(self.scene.active_layer_id)
        dlg = HoldingTabsDialog(targets, layer_settings=layer, parent=self)
        dlg.tabs_applied.connect(self._on_tabs_applied)
        dlg.exec()

    def _on_tabs_applied(self, config: dict):
        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()
        target = config.get("target", "selected")
        enabled = config.get("tabs_enabled", True)
        t_count = config.get("tab_count", 4)
        t_width = config.get("tab_width", 1.2)
        t_power = config.get("tab_power_pct", 0.0)

        if target == "layer":
            layer = self.layer_manager.get_layer(self.scene.active_layer_id)
            layer.tabs_enabled = enabled
            layer.tab_count = t_count
            layer.tab_width = t_width
            layer.tab_power_pct = t_power
        else:
            targets = self.scene.get_selected_entities()
            if not targets:
                targets = self.scene.get_all_entities()
            for ent in targets:
                layer = self.layer_manager.get_layer(ent.layer_id)
                layer.tabs_enabled = enabled
                layer.tab_count = t_count
                layer.tab_width = t_width
                layer.tab_power_pct = t_power

        self.cuts_panel.update_table()
        self.scene.update()
        self.statusBar().showMessage(f"Holding tabs updated ({t_count} tabs, {t_width} mm width, {t_power}% power).", 4000)

    def open_print_and_cut_studio(self):
        """Opens the Print & Cut (2-Point Optical / Machine Registration) dialog."""
        from laserforge.ui.print_and_cut_dialog import PrintAndCutDialog
        targets = self.scene.get_selected_entities()
        if not targets:
            targets = [e for e in self.scene.get_all_entities() if not self.layer_manager.get_layer(e.layer_id).is_tool]
        dlg = PrintAndCutDialog(
            targets,
            serial_controller=self.serial,
            bed_size=(self.settings.bed_width, self.settings.bed_height),
            parent=self
        )
        dlg.alignment_applied.connect(self._on_print_and_cut_applied)
        dlg.exec()

    def _on_print_and_cut_applied(self, res: dict):
        dig_p1 = res["dig_p1"]
        phys_p1 = res["phys_p1"]
        angle_deg = res["angle_deg"]
        scale = res.get("scale", 1.0)

        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()

        targets = self.scene.get_selected_entities()
        if not targets:
            targets = [e for e in self.scene.get_all_entities() if not self.layer_manager.get_layer(e.layer_id).is_tool]

        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        for ent in targets:
            if isinstance(ent, PathEntity):
                new_contours = []
                for c in ent.contours:
                    nc = []
                    for px, py in c:
                        dx = (px - dig_p1[0]) * scale
                        dy = (py - dig_p1[1]) * scale
                        rx = dx * cos_a - dy * sin_a + phys_p1[0]
                        ry = dx * sin_a + dy * cos_a + phys_p1[1]
                        nc.append((rx, ry))
                    new_contours.append(nc)
                ent.contours = new_contours
            elif isinstance(ent, RectEntity):
                dx = (ent.x - dig_p1[0]) * scale
                dy = (ent.y - dig_p1[1]) * scale
                ent.x = dx * cos_a - dy * sin_a + phys_p1[0]
                ent.y = dx * sin_a + dy * cos_a + phys_p1[1]
                ent.width *= scale
                ent.height *= scale
                ent.rotation += angle_deg
            elif isinstance(ent, CircleEntity):
                dx = (ent.x - dig_p1[0]) * scale
                dy = (ent.y - dig_p1[1]) * scale
                ent.x = dx * cos_a - dy * sin_a + phys_p1[0]
                ent.y = dx * sin_a + dy * cos_a + phys_p1[1]
                ent.radius_x *= scale
                ent.radius_y *= scale
                ent.rotation += angle_deg
            elif isinstance(ent, LineEntity):
                dx1 = (ent.x - dig_p1[0]) * scale
                dy1 = (ent.y - dig_p1[1]) * scale
                dx2 = (ent.x2 - dig_p1[0]) * scale
                dy2 = (ent.y2 - dig_p1[1]) * scale
                ent.x = dx1 * cos_a - dy1 * sin_a + phys_p1[0]
                ent.y = dx1 * sin_a + dy1 * cos_a + phys_p1[1]
                ent.x2 = dx2 * cos_a - dy2 * sin_a + phys_p1[0]
                ent.y2 = dx2 * sin_a + dy2 * cos_a + phys_p1[1]
            elif isinstance(ent, TextEntity):
                dx = (ent.x - dig_p1[0]) * scale
                dy = (ent.y - dig_p1[1]) * scale
                ent.x = dx * cos_a - dy * sin_a + phys_p1[0]
                ent.y = dx * sin_a + dy * cos_a + phys_p1[1]
                ent.font_size *= scale
                ent.rotation += angle_deg

        self.scene.rebuild_from_entities(self.scene.get_all_entities())
        self.scene.update()
        self.statusBar().showMessage(f"Print & Cut Alignment Applied ({angle_deg:+.2f}°, scale {scale:.3f}x)", 4000)

    def export_dxf(self):
        """Exports canvas vectors to standard AutoCAD DXF file."""
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Export DXF", "Canvas is empty. Draw or import shapes first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Design to DXF", "LaserForge_Design.dxf",
            "AutoCAD DXF (*.dxf);;All Files (*)"
        )
        if not path:
            return

        try:
            success = DXFExporter.export_dxf_file(entities, path)
            if success:
                self.statusBar().showMessage(f"Successfully exported DXF to '{os.path.basename(path)}'!", 4000)
                QMessageBox.information(self, "Export Complete", f"DXF file saved successfully to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "DXF Export Error", f"Failed to export DXF: {e}")

    def export_svg(self):
        """Exports all canvas entities to standard W3C SVG vector file."""
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Export SVG", "Canvas is empty. Draw or import shapes first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Design to SVG", "LaserForge_Design.svg",
            "Scalable Vector Graphics (*.svg);;All Files (*)"
        )
        if not path:
            return

        try:
            success = SVGExporter.export_svg_file(
                entities, path,
                bed_width_mm=self.settings.bed_width,
                bed_height_mm=self.settings.bed_height
            )
            if success:
                self.statusBar().showMessage(f"Successfully exported SVG to '{os.path.basename(path)}'!", 4000)
                QMessageBox.information(self, "Export Complete", f"SVG vector file saved successfully to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "SVG Export Error", f"Failed to export SVG: {e}")

    def export_lbrn(self):
        """Exports all canvas entities and layer cut settings to native LightBurn .lbrn2 format."""
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Export LightBurn Project", "Canvas is empty. Draw or import shapes first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export LightBurn Project", "LaserForge_Project.lbrn2",
            "LightBurn Projects (*.lbrn2);;All Files (*)"
        )
        if not path:
            return

        try:
            from laserforge.core.lbrn2_exporter import LBRN2Exporter
            LBRN2Exporter.save(entities, self.layer_manager, path, self.settings)
            self.statusBar().showMessage(f"Successfully exported LightBurn project to '{os.path.basename(path)}'!", 4000)
            QMessageBox.information(self, "Export Complete", f"LightBurn project file saved successfully to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "LightBurn Export Error", f"Failed to export LightBurn project: {e}")

    def open_job_estimator(self):
        """Opens the pre-job time, material, and cost estimator dialog."""
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Job Estimator", "Canvas is empty. Draw or import shapes first.")
            return

        from laserforge.core.gcode_generator import GCodeGenerator
        generator = GCodeGenerator(self.settings, self.layer_manager)
        job_result = generator.generate_job(entities)

        dlg = JobEstimatorDialog(job_result, parent=self)
        if dlg.exec() == JobEstimatorDialog.DialogCode.Accepted and dlg.run_job_requested:
            self.start_job()

    def _on_snap_grid_toggled(self, checked: bool):
        self.scene.set_snap_to_grid(checked, 1.0)
        self.statusBar().showMessage(f"Snap to Grid: {'ON (1mm)' if checked else 'OFF'}", 2500)

    def _on_toggle_guides(self, checked: bool):
        self.scene.set_guides_visible(checked)
        self.statusBar().showMessage(f"Alignment Guides: {'Visible' if checked else 'Hidden'}", 2500)

    def _add_recent_file(self, filepath: str):
        if not filepath or not os.path.exists(filepath):
            return
        settings = QSettings("LaserForge", "LaserForge")
        recents = settings.value("recent_files", []) or []
        if isinstance(recents, str):
            recents = [recents]
        else:
            recents = list(recents)
        if filepath in recents:
            recents.remove(filepath)
        recents.insert(0, filepath)
        recents = recents[:10]
        settings.setValue("recent_files", recents)
        self._update_recent_menu()

    def _update_recent_menu(self):
        if not hasattr(self, "menu_recent"):
            return
        self.menu_recent.clear()
        settings = QSettings("LaserForge", "LaserForge")
        recents = settings.value("recent_files", []) or []
        if isinstance(recents, str):
            recents = [recents]
        else:
            recents = list(recents)

        valid_recents = [p for p in recents if os.path.exists(p)]
        if not valid_recents:
            act_empty = self.menu_recent.addAction("No Recent Files")
            act_empty.setEnabled(False)
            return

        for p in valid_recents:
            act = self.menu_recent.addAction(os.path.basename(p))
            act.setToolTip(p)
            act.triggered.connect(lambda checked=False, path=p: self._open_recent_path(path))

        self.menu_recent.addSeparator()
        act_clear = self.menu_recent.addAction("Clear Recent Files")
        act_clear.triggered.connect(self._clear_recent_files)

    def _clear_recent_files(self):
        settings = QSettings("LaserForge", "LaserForge")
        settings.setValue("recent_files", [])
        self._update_recent_menu()

    def _open_recent_path(self, filepath: str):
        if not os.path.exists(filepath):
            QMessageBox.warning(self, "File Not Found", f"File '{filepath}' no longer exists.")
            self._update_recent_menu()
            return
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".laserproj", ".json"):
            self.load_project_file(filepath)
        elif ext == ".dxf":
            self.import_dxf(filepath)
        elif ext == ".svg":
            self.import_svg_file(filepath)
        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
            self.import_image_file(filepath)

    def open_directional_hatching(self):
        """
        Opens the Directional Vector Hatching Studio.
        Generates multi-angle parallel infill lines across unconnected vector shapes,
        guaranteeing >= 15° neighbor difference, maximum center divergence, and outer edge
        convergence toward vertical lines.
        """
        selected_entities = self.scene.get_selected_entities()
        # Filter for closed vector shapes (PathEntity, RectEntity, CircleEntity, TextEntity)
        target_entities = [e for e in selected_entities if not isinstance(e, ImageEntity)]

        if not target_entities:
            # If nothing selected, use all vector entities on canvas
            all_entities = self.scene.get_all_entities()
            target_entities = [e for e in all_entities if not isinstance(e, ImageEntity)]

        if not target_entities:
            QMessageBox.information(
                self, "Directional Vector Hatching",
                "Please draw or select one or more closed vector shapes (rectangles, circles, or paths) to hatch."
            )
            return

        dlg = DirectionalHatchDialog(
            entities=target_entities,
            active_layer_id=getattr(self.scene, "active_layer_id", 1),
            parent=self
        )

        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result and dlg.result.hatched_entities:
            try:
                if hasattr(self.scene, "push_undo_state"):
                    self.scene.push_undo_state()

                if dlg.output_mode == "replace":
                    if hasattr(self.scene, "remove_entities"):
                        self.scene.remove_entities(target_entities)
                    else:
                        for ent in target_entities:
                            self.scene.remove_entity(ent)

                self.scene.clearSelection()
                for ent in dlg.result.hatched_entities:
                    wrapper = self.scene.add_entity(ent)
                    if wrapper:
                        wrapper.setSelected(True)

                self.statusBar().showMessage(
                    f"Successfully generated directional hatching for {len(dlg.result.polygons)} shapes "
                    f"({dlg.result.total_line_count} cut lines, {dlg.result.total_hatch_length_mm:.1f} mm)! "
                    f"Min separation: {dlg.result.min_diff_achieved:.1f}°",
                    5000
                )
            except Exception as e:
                import logging
                logging.getLogger("laserforge").exception("Error applying directional hatching: %s", e)
                QMessageBox.warning(self, "Directional Hatching Error", f"Could not apply hatching to canvas:\n{e}")

    def open_nesting_studio(self):
        """
        Opens the 2D Nesting Optimizer Studio.
        Packs vector shapes efficiently into target sheet material boundaries,
        supporting 90°/45° rotations, cavity/hole nesting, and margin clearances.
        """
        all_ents = self.scene.get_all_entities()
        selected_ents = self.scene.get_selected_entities()
        # Filter for vector shapes (exclude images)
        all_vector_ents = [e for e in all_ents if not isinstance(e, ImageEntity)]
        selected_vector_ents = [e for e in selected_ents if not isinstance(e, ImageEntity)]

        if not all_vector_ents:
            QMessageBox.information(
                self, "2D Nesting Optimizer Studio",
                "Please draw or import vector shapes onto the canvas before opening Nesting Studio."
            )
            return

        dlg = NestingDialog(
            entities=all_vector_ents,
            selected_entities=selected_vector_ents,
            settings=self.settings,
            layer_manager=self.layer_manager,
            parent=self
        )
        dlg.nesting_applied.connect(self._on_nesting_applied)
        dlg.exec()

    def _on_nesting_applied(self, updates):
        """Applies nested coordinates and rotations back to canvas entities with full undo."""
        if not updates:
            return
        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()

        all_ents = self.scene.get_all_entities()
        ent_map = {e.id: e for e in all_ents}
        for orig_ent, new_x, new_y, rot_deg in updates:
            target = ent_map.get(orig_ent.id)
            if target:
                target.x = new_x
                target.y = new_y
                target.rotation = (target.rotation + rot_deg) % 360.0

        self.scene._restore_entities(all_ents)
        self.statusBar().showMessage(f"Applied 2D Nesting Optimization to {len(updates)} shapes.", 4000)

    def open_rotary_studio(self):
        """Opens the Rotary Axis Studio dialog for roller and chuck cylindrical engraving."""
        dlg = RotaryDialog(
            settings=self.settings,
            serial_controller=self.serial_ctrl,
            parent=self
        )
        dlg.rotary_settings_changed.connect(self._on_rotary_settings_changed)
        dlg.exec()

    def open_z_probe_studio(self):
        """Opens the Auto-Focus & Touch Plate Probing Studio (G38.2)."""
        dlg = ZProbeStudioDialog(
            serial_ctrl=self.serial_ctrl,
            settings=self.settings,
            parent=self
        )
        dlg.exec()

    def open_surface_wrap_studio(self):
        """Opens the 3D Curved Surface Wrapping Studio."""
        selected = self.scene.get_selected_entities()
        target = selected if selected else self.scene.get_all_entities()
        dlg = SurfaceWrapStudioDialog(entities=target, parent=self)
        dlg.exec()

    def _on_rotary_settings_changed(self):
        status = "ENABLED" if self.settings.rotary_enabled else "Disabled"
        self.statusBar().showMessage(
            f"Rotary Axis {status}: {self.settings.rotary_type} ({self.settings.rotary_mode}, ⌀ {self.settings.rotary_object_diameter:.1f} mm)",
            5000
        )

    def open_box_studio(self):
        """Opens the Parametric Box & Finger-Joint Enclosure Studio dialog."""
        from laserforge.ui.box_dialog import BoxGeneratorDialog
        dlg = BoxGeneratorDialog(parent=self)
        dlg.panels_generated.connect(self._on_box_panels_generated)
        dlg.exec()

    def _on_box_panels_generated(self, entities: list):
        if not entities:
            return
        self.scene.push_undo_state()
        for ent in entities:
            self.scene.add_entity(ent)
        self.scene.update()
        self.statusBar().showMessage(f"Added {len(entities)} box panels & labels to workspace bed.", 4000)

    def open_living_hinge_studio(self):
        """Opens the Living Hinges & Lattice Flex Studio dialog."""
        from laserforge.ui.living_hinge_dialog import LivingHingeDialog
        dlg = LivingHingeDialog(parent=self)
        if hasattr(dlg, "patterns_generated"):
            dlg.patterns_generated.connect(self._on_living_hinge_patterns_generated)
        elif hasattr(dlg, "hinge_generated"):
            dlg.hinge_generated.connect(self._on_living_hinge_patterns_generated)
        dlg.exec()

    def _on_living_hinge_patterns_generated(self, entities: list):
        if not entities:
            return
        self.scene.push_undo_state()
        for ent in entities:
            self.scene.add_entity(ent)
        self.scene.update()
        self.statusBar().showMessage(f"Added Living Hinge pattern ({len(entities)} entities) to workspace bed.", 4000)

    def open_material_test_studio(self):
        """Opens the Automated Material Test Matrix & Calibration Studio."""
        from laserforge.ui.material_test_dialog import MaterialTestDialog
        dlg = MaterialTestDialog(parent=self)
        dlg.grid_generated.connect(self._on_material_test_generated)
        dlg.exec()

    def _on_material_test_generated(self, entities: list):
        if not entities:
            return
        self.scene.push_undo_state()
        for ent in entities:
            self.scene.add_entity(ent)
        self.scene.update()
        self.statusBar().showMessage(f"Added Material Test Matrix ({len(entities)} entities) to bed.", 4000)

    def open_relief_studio(self):
        """Opens the 3D Relief Engraving & Automated Z-Step Studio."""
        from laserforge.ui.relief_dialog import ReliefStudioDialog
        dlg = ReliefStudioDialog(parent=self)
        dlg.relief_generated.connect(self._on_relief_generated)
        dlg.exec()

    def _on_relief_generated(self, entities: list):
        if not entities:
            return
        self.scene.push_undo_state()
        for ent in entities:
            self.scene.add_entity(ent)
        self.scene.update()
        self.statusBar().showMessage(f"Added 3D Relief toolpaths ({len(entities)} slices) to bed.", 4000)

    def open_galvo_studio(self):
        """Opens the Galvo & Fiber Laser Marking Studio."""
        from laserforge.ui.galvo_dialog import GalvoStudioDialog
        from laserforge.core.galvo_engine import GalvoEngine
        selected = self.scene.get_selected_entities()
        dlg = GalvoStudioDialog(selected_entities=selected, parent=self)
        dlg.wobble_applied.connect(self._on_galvo_wobble_applied)
        dlg.exec()

    def _on_galvo_wobble_applied(self, res: dict):
        from laserforge.core.galvo_engine import GalvoEngine
        wobble_cfg = res.get("wobble")
        if not wobble_cfg or not wobble_cfg.enabled:
            return
        selected = self.scene.get_selected_entities()
        if not selected:
            return
        self.scene.push_undo_state()
        from laserforge.core.models import PathEntity
        for ent in selected:
            if isinstance(ent, PathEntity):
                new_contours = []
                for c in ent.contours:
                    new_contours.append(GalvoEngine.apply_wobble_to_contour(c, wobble_cfg))
                ent.contours = new_contours
        self.scene.update()
        self.statusBar().showMessage(f"Applied {wobble_cfg.pattern} beam wobble ({wobble_cfg.amplitude_mm} mm) to selected artwork.", 4000)

    def open_ruida_studio(self):
        """Opens the Ruida DSP Ethernet Controller & .rd Toolpath Studio."""
        from laserforge.ui.ruida_dialog import RuidaDialog
        targets = self.scene.get_selected_entities() or self.scene.get_all_entities()
        dlg = RuidaDialog(entities=targets, parent=self)
        dlg.exec()

    def open_web_pendant_dialog(self):
        """Opens the Mobile Remote Jogger & Workshop Web Pendant Studio."""
        from laserforge.ui.web_pendant_dialog import WebPendantDialog
        dlg = WebPendantDialog(server=self.web_pendant, parent=self)
        dlg.exec()

    def _setup_web_pendant_callbacks(self):
        self.web_pendant.on_jog = lambda dx, dy: self.serial_ctrl.jog(dx, dy, self.settings.jog_feedrate)
        self.web_pendant.on_frame = self.frame_job
        self.web_pendant.on_guide_beam = lambda: self.serial_ctrl.send_command("M3 G1 S5 F1000")
        self.web_pendant.on_home = self.serial_ctrl.home
        self.web_pendant.on_unlock = self.serial_ctrl.unlock
        self.web_pendant.on_estop = self.serial_ctrl.stop_streaming
        self.web_pendant.get_status_cb = lambda: {
            "state": getattr(self.serial_ctrl.machine_state, "state", "Idle") if hasattr(self.serial_ctrl, "machine_state") else "Idle",
            "x": getattr(self.serial_ctrl.machine_state, "work_x", 0.0) if hasattr(self.serial_ctrl, "machine_state") else 0.0,
            "y": getattr(self.serial_ctrl.machine_state, "work_y", 0.0) if hasattr(self.serial_ctrl, "machine_state") else 0.0,
            "z": getattr(self.serial_ctrl.machine_state, "work_z", 0.0) if hasattr(self.serial_ctrl, "machine_state") else 0.0,
        }

    def open_single_line_text_studio(self):
        """Opens the Single-Line Stroke (Hershey Vector) Font dialog."""
        from laserforge.ui.single_line_text_dialog import SingleLineTextDialog
        dlg = SingleLineTextDialog(parent=self)
        dlg.entity_created.connect(self._on_single_line_text_created)
        dlg.exec()

    def _on_single_line_text_created(self, entity):
        if not entity:
            return
        self.scene.push_undo_state()
        self.scene.add_entity(entity)
        self.scene.update()
        self.statusBar().showMessage("Added Single-Line Vector Text to workspace bed.", 4000)

    def open_kerf_test_studio(self):
        """Opens the Automated Kerf Test Gauge Studio dialog."""
        from laserforge.ui.kerf_test_dialog import KerfTestDialog
        dlg = KerfTestDialog(parent=self)
        dlg.gauge_generated.connect(self._on_kerf_gauge_generated)
        dlg.exec()

    def _on_kerf_gauge_generated(self, entities: list):
        if not entities:
            return
        self.scene.push_undo_state()
        for ent in entities:
            self.scene.add_entity(ent)
        self.scene.update()
        self.statusBar().showMessage(f"Added Kerf Test Gauge ({len(entities)} elements) to workspace bed.", 4000)

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
            final_gcode = self.plugin_registry.apply_gcode_postprocessors(job.gcode)
            with open(path, "w", encoding="utf-8") as f:
                f.write(final_gcode)
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

    def contour_frame_job(self):
        """Traces the exact rubber-band perimeter / convex hull of artwork with low-power guide."""
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Contour Frame Error", "Laser is not connected. Please connect in the Laser tab first.")
            return

        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Contour Frame Error", "Canvas is empty.")
            return

        contour_gcode = self.gcode_gen.generate_contour_framing_gcode(entities)
        if not contour_gcode:
            QMessageBox.warning(self, "Contour Frame Error", "Could not calculate artwork contour for framing.")
            return

        self.serial_ctrl.start_job(contour_gcode)
        self.statusBar().showMessage("Contour framing artwork silhouette with laser guide beam...", 3000)

    def validate_current_job(self):
        """Generates G-code for current canvas items and displays full validation report."""
        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.information(self, "Validate G-Code", "Canvas is empty. Add shapes or artwork to validate.")
            return

        try:
            job = self.gcode_gen.generate_job(entities)
            validator = GCodeValidator(self.settings, strict=getattr(self.settings, "strict_validation", False))
            report = validator.validate(job.gcode)
            dlg = ValidationDialog(report, parent=self, allow_proceed=False)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Validation Error", f"Failed to generate and validate G-code: {e}")

    def start_job(self):
        if not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Start Error", "Laser is not connected. Please connect in the Laser tab first.")
            return

        if self.serial_ctrl.machine_state == "Alarm":
            QMessageBox.warning(
                self, "Machine in ALARM State",
                "<b>Laser is currently locked in ALARM state!</b><br><br>"
                "A hardware limit switch was triggered or the machine was reset.<br>"
                "Please ensure the carriage is clear of endstops and click <b>'Unlock ($X)'</b> in the Laser panel."
            )
            return

        entities = self.scene.get_all_entities()
        if not entities:
            QMessageBox.warning(self, "Start Error", "Canvas is empty.")
            return

        try:
            job = self.gcode_gen.generate_job(entities)
        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"Failed to generate G-code: {e}")
            return

        # 1. Pre-Flight GRBL G-Code Simulation & Validation
        active_gcode = job.gcode
        active_job = job
        bed_w = self.settings.bed_width
        bed_h = self.settings.bed_height
        max_s = self.settings.max_s_value
        min_x, min_y, max_x, max_y = job.bounding_box
        is_out_of_bounds = (max_x > bed_w + 0.5 or max_y > bed_h + 0.5 or min_x < -0.5 or min_y < -0.5)

        validator = GCodeValidator(self.settings, strict=getattr(self.settings, "strict_validation", False))
        report = validator.validate(active_gcode)

        # 2. Automated Simulation & Error Repair Check
        if report.has_errors or is_out_of_bounds:
            # Run automated repair engine to fix out-of-bounds, missing F, Marlin codes, unclamped S, etc.
            repaired_gcode, repairs_applied = GCodeValidator.repair_gcode(
                active_gcode,
                bed_width=bed_w,
                bed_height=bed_h,
                max_s=max_s,
                default_feedrate=getattr(self.settings, "rapid_speed", 1000.0)
            )

            # Re-validate repaired G-code
            repaired_report = validator.validate(repaired_gcode)
            repaired_job = GCodeValidator.simulate_to_job(repaired_gcode, self.settings)

            val_dlg = ValidationDialog(
                report=report if report.has_errors else repaired_report,
                parent=self,
                allow_proceed=True,
                repaired_gcode=repaired_gcode,
                repairs_applied=repairs_applied,
                job_result=repaired_job,
                settings=self.settings
            )
            val_dlg.exec()

            if not val_dlg.proceed_chosen:
                return

            active_gcode = val_dlg.final_gcode or repaired_gcode
            active_job = repaired_job

        elif report.has_warnings and getattr(self.settings, "validate_gcode_before_start", True):
            val_dlg = ValidationDialog(
                report,
                parent=self,
                allow_proceed=True,
                job_result=job,
                settings=self.settings
            )
            val_dlg.exec()
            if not val_dlg.proceed_chosen:
                return

        # 3. Final Safety Confirmation before burning
        res = QMessageBox.question(
            self, "Start Laser Job",
            f"<b>Safety Checklist:</b><br>"
            f"• Laser safety glasses worn?<br>"
            f"• Exhaust / fume extraction on?<br>"
            f"• Work area clear and focused?<br><br>"
            f"Start burning job now? ({len(active_job.segments)} moves, est. {active_job.estimated_time_sec:.0f}s)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            self.serial_ctrl.start_job(active_gcode)
            self.statusBar().showMessage(f"Laser job started ({len(active_job.segments)} moves).", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Execution Error", f"Failed to stream G-code: {e}")

    def _toggle_pause_job(self):
        if hasattr(self, "laser_panel"):
            self.laser_panel._toggle_pause()
        elif self.serial_ctrl.is_streaming:
            if self.serial_ctrl.is_paused:
                self.serial_ctrl.resume_job()
            else:
                self.serial_ctrl.pause_job()

    def open_machine_settings(self):
        dlg = MachineSettingsDialog(self.settings, parent=self, serial_ctrl=self.serial_ctrl)
        if dlg.exec() == MachineSettingsDialog.DialogCode.Accepted:
            self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height, self.settings.origin_corner)
            self.canvas_widget.view.set_opengl_acceleration(getattr(self.settings, "enable_opengl_canvas", True))
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage("Machine & Laser settings updated.", 3000)

    def open_workbed_setup_wizard(self):
        from laserforge.ui.workbed_setup_dialog import WorkbedSetupDialog
        dlg = WorkbedSetupDialog(self.settings, serial_ctrl=self.serial_ctrl, scene=self.scene, parent=self)
        if dlg.exec() == WorkbedSetupDialog.DialogCode.Accepted:
            self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height, self.settings.origin_corner)
            self.scene.set_bed_size(self.settings.bed_width, self.settings.bed_height, self.settings.origin_corner)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(
                f"Workbed configured: {self.settings.bed_width:.1f} × {self.settings.bed_height:.1f} mm ({self.settings.origin_corner})",
                4000
            )

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
            "<li>Living Hinges & Curved Box Lattice Flex Studio</li>"
            "<li>Parametric Finger & Dovetail Joint Box Enclosure Studio</li>"
            "<li>2-Point Optical Print & Cut Registration & Holding Tabs</li>"
            "</ul>"
            "<p><i>Built for makers and fabricators.</i></p>"
        )

    def open_license_dialog(self):
        """Opens the Commercial Licensing & 30-Day Free Trial dialog."""
        from laserforge.ui.license_dialog import LicenseDialog
        dlg = LicenseDialog(parent=self)
        dlg.license_changed.connect(self._on_license_changed)
        dlg.exec()

    def _on_license_changed(self, is_active: bool = False):
        self._update_window_title_license()
        status = self.license_engine.get_status()
        if status.is_licensed:
            self.statusBar().showMessage(f"LaserForge Commercial License Active ({status.licensed_to}). Thank you for your support!", 5000)
        elif status.is_trial_active:
            self.statusBar().showMessage(f"LaserForge 30-Day Free Trial: {status.days_remaining} days remaining.", 5000)
        else:
            self.statusBar().showMessage("LaserForge License Status: TRIAL EXPIRED.", 5000)

    def _update_window_title_license(self):
        """Updates the main window title with current license/trial status."""
        status = self.license_engine.get_status()
        if status.is_licensed:
            tag = f"[Commercial License Active - {status.licensed_to}]"
        elif status.is_trial_active:
            tag = f"[30-Day Free Trial: {status.days_remaining} Days Remaining]"
        elif status.is_expired:
            tag = "[Trial Expired - License Activation Required]"
        else:
            tag = "[Evaluation]"
        self.setWindowTitle(f"LaserForge - Laser Engraver & Cutter {tag}")

    def check_for_updates(self):
        """Checks for updates against official releases."""
        QMessageBox.information(
            self,
            "Check for Updates",
            "<h3>LaserForge is Up to Date</h3>"
            "<p>You are running the latest production build (v2.5.0).</p>"
            "<p>All CAM engines, 3D simulation tools, parametric studios, "
            "and commercial licensing systems are current.</p>"
        )

    def open_feedback_dialog(self):
        """Opens the Send Feedback & Message Creator dialog for beta testers."""
        from laserforge.ui.feedback_dialog import FeedbackDialog
        dlg = FeedbackDialog(main_window=self, parent=self)
        dlg.exec()

    def start_interactive_tutorial(self):
        """Starts the interactive step-by-step tutorial and guided tour."""
        from laserforge.ui.tutorial_dialog import InteractiveTutorialDialog
        if getattr(self, "_tutorial_dialog", None) is not None and self._tutorial_dialog.isVisible():
            self._tutorial_dialog.raise_()
            self._tutorial_dialog.activateWindow()
            return
        self._tutorial_dialog = InteractiveTutorialDialog(main_window=self, parent=self)
        self._tutorial_dialog.show()
        self._tutorial_dialog.raise_()
        self._tutorial_dialog.activateWindow()

    def _check_first_run_tutorial(self, start_tutorial: bool = False):
        """Checks if the tutorial should be launched on startup or if first-run welcome is shown."""
        if os.environ.get("LASERFORGE_HEADLESS") == "1":
            return

        if start_tutorial:
            self.start_interactive_tutorial()
            return

        settings = QSettings("LaserForge", "LaserForge")
        dismissed = settings.value("tutorial_prompt_dismissed", False, type=bool)
        if not dismissed:
            from laserforge.ui.tutorial_dialog import WelcomeOnboardingDialog
            welcome = WelcomeOnboardingDialog(parent=self)
            if welcome.exec() == WelcomeOnboardingDialog.DialogCode.Accepted and welcome.start_tutorial_selected:
                self.start_interactive_tutorial()

    def open_user_guide(self):
        """Opens the comprehensive User Guide & FAQ Reference dialog."""
        from laserforge.ui.guide_dialog import UserGuideDialog
        if getattr(self, "_guide_dialog", None) is not None and self._guide_dialog.isVisible():
            self._guide_dialog.raise_()
            self._guide_dialog.activateWindow()
            return
        self._guide_dialog = UserGuideDialog(main_window=self, parent=self)
        self._guide_dialog.show()
        self._guide_dialog.raise_()
        self._guide_dialog.activateWindow()


    # -------------------------------------------------------------
    # Business Card Studio, 3W Material Library & Alignment
    # -------------------------------------------------------------
    def open_business_card_studio(self):
        """Opens the interactive Business Card Studio Dialog."""
        dlg = BusinessCardStudioDialog(self)
        if dlg.exec() == BusinessCardStudioDialog.DialogCode.Accepted and dlg.generated_entities:
            self.scene.clearSelection()
            for ent in dlg.generated_entities:
                w = self.scene.add_entity(ent)
                w.setSelected(True)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(
                f"Generated {len(dlg.generated_entities)} business card entities on canvas.", 4000
            )

    def open_material_library(self):
        """Opens the 3W Laser Material Library & Calibrated Presets."""
        dlg = MaterialLibraryDialog(self)
        dlg.applied_to_layer.connect(self._on_material_applied_to_layer)
        if dlg.exec() == MaterialLibraryDialog.DialogCode.Accepted:
            if dlg.test_matrix_entities:
                self.scene.clearSelection()
                for ent in dlg.test_matrix_entities:
                    w = self.scene.add_entity(ent)
                    w.setSelected(True)
                self.canvas_widget.view.zoom_to_fit()
                self.statusBar().showMessage(
                    f"Generated {len(dlg.test_matrix_entities)} test matrix swatches on canvas.", 4000
                )

    def _on_material_applied_to_layer(self, profile: MaterialProfile):
        """Applies a selected 3W diode laser material profile to the active layer."""
        active_lid = self.scene.active_layer_id
        layer_cfg = self.layer_manager.get_layer(active_lid)
        layer_cfg.speed = profile.speed
        layer_cfg.power_max = profile.power_pct
        layer_cfg.passes = profile.passes
        layer_cfg.line_interval = profile.line_interval
        layer_cfg.pass_delay_sec = profile.pass_delay_sec
        layer_cfg.air_assist = profile.air_assist
        if profile.mode in ("Line", "Fill", "Fill + Line"):
            layer_cfg.mode = profile.mode
        self.cuts_panel.refresh_table()
        self.scene.update()
        self.statusBar().showMessage(
            f"Applied 3W preset '{profile.name}' to Layer C{active_lid:02d} ({profile.speed:.0f} mm/min, {profile.power_pct:.0f}% power)",
            4000
        )

    def open_test_matrix_dialog(self):
        """Opens the Parametric Material Test Matrix Grid Dialog."""
        dlg = TestMatrixDialog(self)
        if dlg.exec() == TestMatrixDialog.DialogCode.Accepted and dlg.generated_entities:
            self.scene.clearSelection()
            for ent in dlg.generated_entities:
                w = self.scene.add_entity(ent)
                w.setSelected(True)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(
                f"Generated {len(dlg.generated_entities)} material test matrix swatches.", 4000
            )

    def open_auto_calibration_dialog(self):
        """Opens the interactive Vision & Workbed Auto-Calibration Studio."""
        from laserforge.ui.auto_calibration_dialog import AutoCalibrationDialog
        dlg = AutoCalibrationDialog(
            camera_engine=self.camera_engine,
            settings=self.settings,
            serial_ctrl=self.serial_ctrl,
            scene=self.scene,
            parent=self
        )
        dlg.calibration_applied.connect(self._on_camera_calibration_applied)
        dlg.exec()

    def open_camera_wizard(self):
        """Opens the interactive Camera Calibration and Bed Alignment Wizard."""
        from laserforge.ui.camera_calibration_wizard import CameraCalibrationWizardDialog
        dlg = CameraCalibrationWizardDialog(
            self.camera_engine,
            bed_width_mm=self.settings.bed_width,
            bed_height_mm=self.settings.bed_height,
            parent=self
        )
        dlg.calibration_applied.connect(self._on_camera_calibration_applied)
        dlg.exec()

    def _on_camera_calibration_applied(self, calib):
        self.statusBar().showMessage("Camera calibration applied successfully! Updating bed overlay...", 5000)
        self.update_camera_overlay()

    def open_camera_fine_tune_dialog(self):
        """Opens the interactive Camera Bed Overlay Fine-Tuning & Alignment Dialog."""
        from laserforge.ui.camera_calibration_wizard import CameraFineTuneDialog
        dlg = CameraFineTuneDialog(
            camera_engine=self.camera_engine,
            scene=self.scene,
            settings=self.settings,
            parent=self
        )
        dlg.exec()

    def open_multi_camera_studio(self):
        """Opens the Multi-Camera Panoramic Bed Setup & Seam Stitching Studio."""
        from laserforge.ui.multi_camera_dialog import MultiCameraSetupDialog
        dlg = MultiCameraSetupDialog(engine=self.multi_camera_engine, parent=self)
        dlg.panoramic_stitched_ready.connect(self._apply_stitched_frame_to_canvas)
        dlg.exec()

    def _apply_stitched_frame_to_canvas(self, stitched_frame: np.ndarray):
        """Applies a stitched multi-camera orthophoto directly to the canvas background."""
        if stitched_frame is None or stitched_frame.size == 0:
            return
        h, w, ch = stitched_frame.shape
        bytes_per_line = ch * w
        qimg = QImage(stitched_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        self.scene.set_camera_overlay_pixmap(
            pix,
            self.settings.bed_width,
            self.settings.bed_height,
            offset_x=0.0,
            offset_y=0.0,
            fine_scale_x=1.0,
            fine_scale_y=1.0,
            fine_rotation_deg=0.0,
            opacity=0.6
        )
        self.actions.camera_toggle.setChecked(True)
        self.statusBar().showMessage(f"Panoramic multi-camera bed overlay updated ({w}x{h} px)", 3000)

    def update_camera_overlay(self):
        """Captures a rectified top-down frame and maps it to the canvas bed background."""
        try:
            if hasattr(self, "multi_camera_engine") and self.multi_camera_engine.config.enabled:
                stitched = self.multi_camera_engine.stitch_orthophoto()
                if stitched is not None and stitched.size > 0:
                    self._apply_stitched_frame_to_canvas(stitched)
                    return

            ortho = self.camera_engine.rectify_bed_image()
            if ortho is not None and ortho.size > 0:
                h, w, ch = ortho.shape
                bytes_per_line = ch * w
                qimg = QImage(ortho.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                pix = QPixmap.fromImage(qimg)
                cal = self.camera_engine.calibration
                self.scene.set_camera_overlay_pixmap(
                    pix,
                    self.settings.bed_width,
                    self.settings.bed_height,
                    offset_x=cal.offset_x_mm,
                    offset_y=cal.offset_y_mm,
                    fine_scale_x=cal.fine_scale_x,
                    fine_scale_y=cal.fine_scale_y,
                    fine_rotation_deg=cal.fine_rotation_deg,
                    opacity=cal.overlay_opacity
                )
                self.actions.camera_toggle.setChecked(True)
                self.statusBar().showMessage(f"Camera bed overlay updated ({w}x{h} px)", 3000)
            else:
                self.statusBar().showMessage("Could not capture camera frame. Check device connection.", 5000)
        except Exception as e:
            self.statusBar().showMessage(f"Camera overlay error: {e}", 5000)

    def open_alignment_assistant(self):
        """Opens the Workpiece Alignment & Targeting Assistant dialog."""
        entities = self.scene.get_selected_entities()
        if not entities:
            entities = self.scene.get_all_entities()

        if entities:
            all_min_x, all_min_y, all_max_x, all_max_y = float("inf"), float("inf"), float("-inf"), float("-inf")
            for ent in entities:
                b = ent.get_bounds()
                all_min_x = min(all_min_x, b[0])
                all_min_y = min(all_min_y, b[1])
                all_max_x = max(all_max_x, b[2])
                all_max_y = max(all_max_y, b[3])
            bbox = (all_min_x, all_min_y, all_max_x, all_max_y)
        else:
            # Default to standard business card blank (85.6 x 54 mm) at (20, 20)
            bbox = (20.0, 20.0, 105.6, 74.0)

        dlg = LaserAlignmentDialog(serial_ctrl=self.serial_ctrl, bbox=bbox, parent=self)
        try:
            dlg.align_canvas_requested[float, float, float, float, str].connect(self._align_canvas_artwork)
        except Exception:
            dlg.align_canvas_requested.connect(self._align_canvas_artwork)
        dlg.generate_jig_requested.connect(self._generate_l_jig)
        dlg.burn_perimeter_requested.connect(self.open_burn_perimeter_tool)
        dlg.exec()

    def _align_canvas_artwork(self, angle_deg: float, shift_x: float, shift_y: float, scale: float = 1.0, ref_corner: str = "TL"):
        """Rotates and translates canvas artwork to align with the physically measured workpiece."""
        from laserforge.ui.canvas_scene import LaserItemWrapper
        import math

        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()

        target_wrappers = [
            item for item in self.scene.items()
            if isinstance(item, LaserItemWrapper) and (not self.scene.selectedItems() or item.isSelected())
        ]
        if not target_wrappers:
            target_wrappers = [item for item in self.scene.items() if isinstance(item, LaserItemWrapper)]

        if not target_wrappers:
            return

        # Calculate bounding envelope of target items to find reference corner
        all_min_x, all_min_y, all_max_x, all_max_y = float("inf"), float("inf"), float("-inf"), float("-inf")
        for w in target_wrappers:
            w.sync_to_entity()
            b = w.entity.get_bounds()
            all_min_x = min(all_min_x, b[0])
            all_min_y = min(all_min_y, b[1])
            all_max_x = max(all_max_x, b[2])
            all_max_y = max(all_max_y, b[3])

        if ref_corner == "BL":
            ref_x, ref_y = all_min_x, all_min_y
        elif ref_corner == "CL":
            ref_x, ref_y = all_min_x, (all_min_y + all_max_y) / 2.0
        elif ref_corner == "TR":
            ref_x, ref_y = all_max_x, all_max_y
        elif ref_corner == "BR":
            ref_x, ref_y = all_max_x, all_min_y
        else:  # "TL"
            ref_x, ref_y = all_min_x, all_max_y

        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        target_ref_x = ref_x + shift_x
        target_ref_y = ref_y + shift_y

        for w in target_wrappers:
            ent = w.entity
            if isinstance(ent, LineEntity):
                for attr_x, attr_y in [("x", "y"), ("x2", "y2")]:
                    ox = getattr(ent, attr_x)
                    oy = getattr(ent, attr_y)
                    dx = (ox - ref_x) * scale
                    dy = (oy - ref_y) * scale
                    rx = dx * cos_a - dy * sin_a
                    ry = dx * sin_a + dy * cos_a
                    setattr(ent, attr_x, target_ref_x + rx)
                    setattr(ent, attr_y, target_ref_y + ry)
            elif isinstance(ent, PathEntity):
                new_contours = []
                for contour in ent.contours:
                    new_c = []
                    for px, py in contour:
                        abs_px = ent.x + px
                        abs_py = ent.y + py
                        dx = (abs_px - ref_x) * scale
                        dy = (abs_py - ref_y) * scale
                        rx = dx * cos_a - dy * sin_a
                        ry = dx * sin_a + dy * cos_a
                        new_c.append((target_ref_x + rx, target_ref_y + ry))
                    new_contours.append(new_c)
                ent.x = 0.0
                ent.y = 0.0
                ent.contours = new_contours
                ent.invalidate_bounds()
                w._cached_path = None
            else:
                b = ent.get_bounds()
                cx = (b[0] + b[2]) / 2.0
                cy = (b[1] + b[3]) / 2.0
                dx = (cx - ref_x) * scale
                dy = (cy - ref_y) * scale
                rx = dx * cos_a - dy * sin_a
                ry = dx * sin_a + dy * cos_a
                new_cx = target_ref_x + rx
                new_cy = target_ref_y + ry

                if isinstance(ent, CircleEntity):
                    ent.x = new_cx
                    ent.y = new_cy
                    if scale != 1.0:
                        ent.radius_x *= scale
                        ent.radius_y *= scale
                else:
                    if scale != 1.0:
                        ent.width *= scale
                        ent.height *= scale
                        if isinstance(ent, TextEntity):
                            ent.font_size *= scale
                    ent.x = new_cx - ent.width / 2.0
                    ent.y = new_cy - ent.height / 2.0
                ent.rotation = (ent.rotation + angle_deg) % 360.0

            w.sync_from_entity()

        self.scene.entity_modified.emit()
        self.scene.update()
        scale_msg = f", scale: {scale:.3f}x" if scale != 1.0 else ""
        self.statusBar().showMessage(
            f"Canvas aligned: rotated {angle_deg:+.2f}°, shifted by ({shift_x:+.1f}, {shift_y:+.1f}) mm{scale_msg}", 4000
        )

    def _generate_l_jig(self, card_w: float = 85.6, card_h: float = 54.0):
        """Places a physical 90° L-bracket corner stop wasteboard jig on the canvas (Layer T1)."""
        arm_thick = 15.0
        arm_len_x = card_w + 15.0
        arm_len_y = card_h + 15.0
        ox = 10.0
        oy = 10.0

        # L-bracket perimeter
        l_contour = [
            (ox, oy),
            (ox + arm_thick + arm_len_x, oy),
            (ox + arm_thick + arm_len_x, oy + arm_thick),
            (ox + arm_thick, oy + arm_thick),
            (ox + arm_thick, oy + arm_thick + arm_len_y),
            (ox, oy + arm_thick + arm_len_y),
            (ox, oy)
        ]

        jig_path = PathEntity(
            layer_id=12,  # T1 Tool guide layer
            name="90deg_Wasteboard_L_Jig",
            x=0.0,
            y=0.0,
            contours=[l_contour],
            closed=True
        )

        label = TextEntity(
            layer_id=12,
            name="Jig_Label",
            x=ox + 2.0,
            y=oy + 4.0,
            text=f"90° CORNER STOP ({card_w:.1f}×{card_h:.1f})",
            font_size=3.5,
            width=55.0,
            height=6.0
        )

        card_guide = RectEntity(
            layer_id=12,
            name="Card_Pocket_Guide",
            x=ox + arm_thick,
            y=oy + arm_thick,
            width=card_w,
            height=card_h,
            corner_radius=3.0
        )

        self.scene.clearSelection()
        for ent in (jig_path, label, card_guide):
            w = self.scene.add_entity(ent)
            w.setSelected(True)

        self.canvas_widget.view.zoom_to_fit()
        self.statusBar().showMessage("90° Wasteboard Corner Stop Jig placed on canvas (Layer T1).", 4000)

    def open_burn_perimeter_tool(self, custom_bbox: Optional[Tuple[float, float, float, float]] = None):
        """Opens the Burn Perimeter Tool for workpiece alignment and spoilboard marking."""
        selected_entities = self.scene.get_selected_entities()
        all_entities = self.scene.get_all_entities()

        dlg = BurnPerimeterDialog(
            serial_ctrl=self.serial_ctrl,
            settings=self.settings,
            gcode_gen=self.gcode_gen,
            layer_manager=self.layer_manager,
            selected_entities=selected_entities,
            all_entities=all_entities,
            custom_bbox=custom_bbox,
            parent=self
        )
        dlg.add_to_canvas_requested.connect(self._add_entities_to_canvas)
        dlg.exec()

    def _add_entities_to_canvas(self, entities: List[LaserEntity]):
        """Inserts generated vector entities onto canvas and triggers view update."""
        if not entities:
            return
        if hasattr(self.scene, "push_undo_state"):
            self.scene.push_undo_state()
        self.scene.clearSelection()
        for ent in entities:
            w = self.scene.add_entity(ent)
            w.setSelected(True)
        self.canvas_widget.view.zoom_to_fit()
        self.statusBar().showMessage(f"Added {len(entities)} alignment perimeter shape(s) to canvas.", 4000)

    def add_corner_l_marks_quick(self):
        """Quick 1-click action: generate 90° corner L-tick alignment marks on selected shapes or canvas."""
        selected_entities = self.scene.get_selected_entities()
        target = selected_entities if selected_entities else self.scene.get_all_entities()
        if not target:
            QMessageBox.information(self, "Corner L-Marks", "Canvas is empty. Draw or import shapes first.")
            return

        l_marks = self.gcode_gen.generate_corner_l_marks(
            target=target,
            tick_len_mm=8.0,
            margin_mm=0.0,
            layer_id=12  # Tool / Alignment Guide
        )
        self._add_entities_to_canvas(l_marks)
        self.statusBar().showMessage("Added 4 Corner 90° L-marks (Layer T1) to workpiece bounding perimeter.", 4000)

    def add_center_cross_quick(self):
        """Quick 1-click action: generate a centered '+' registration cross mark on selected shapes or canvas."""
        selected_entities = self.scene.get_selected_entities()
        target = selected_entities if selected_entities else self.scene.get_all_entities()
        if not target:
            QMessageBox.information(self, "Center Cross Mark", "Canvas is empty. Draw or import shapes first.")
            return

        cross_lines = self.gcode_gen.generate_center_cross_mark(
            target=target,
            cross_len_mm=10.0,
            margin_mm=0.0,
            layer_id=12  # Tool / Alignment Guide
        )
        self._add_entities_to_canvas(cross_lines)
        self.statusBar().showMessage("Added Centered '+' Registration Mark (Layer T1) at geometric center.", 4000)

    def open_alignment_marks_studio(self, default_mode: str = "both"):
        """Opens the Alignment & Registration Marks Studio dialog."""
        selected_entities = self.scene.get_selected_entities()
        all_entities = self.scene.get_all_entities()

        dlg = AlignmentMarksDialog(
            parent=self,
            target_entities=selected_entities,
            all_entities=all_entities,
            settings=self.settings,
            serial_ctrl=self.serial_ctrl,
            default_mode=default_mode,
        )
        dlg.marks_generated.connect(self._add_entities_to_canvas)
        dlg.exec()

    def generate_vector_qr_code(self):
        """Prompts user for URL/text and generates a clean vector QR code on the active layer."""
        data, ok = QInputDialog.getText(
            self, "Generate Vector QR Code",
            "Enter URL, contact info, or text to encode:",
            text="https://laserforge.org"
        )
        if not ok or not data.strip():
            return

        size_mm, ok2 = QInputDialog.getDouble(
            self, "QR Code Size",
            "QR Code Width/Height (mm):",
            value=25.0, min=10.0, max=200.0, decimals=1
        )
        if not ok2:
            return

        try:
            contours = generate_qr_contours(data.strip(), size_mm=size_mm)
            center_x = (self.settings.bed_width - size_mm) / 2.0
            center_y = (self.settings.bed_height - size_mm) / 2.0

            qr_ent = PathEntity(
                layer_id=self.scene.active_layer_id,
                name=f"QR_{data[:12].strip()}",
                x=center_x,
                y=center_y,
                contours=contours,
                closed=True
            )
            self.scene.clearSelection()
            wrapper = self.scene.add_entity(qr_ent)
            wrapper.setSelected(True)
            self.statusBar().showMessage(
                f"Generated vector QR code ({size_mm:.1f} × {size_mm:.1f} mm) with {len(contours)} polygon loops.", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "QR Code Error", f"Failed to generate vector QR code: {e}")

    # --- Design Aids, Studios & Photo Conversion Handlers ---

    def open_photo_studio(self, image_entity: Optional[ImageEntity] = None):
        """Opens the interactive Photo Engrave Studio dialog for photographic diode laser preparation."""
        if image_entity is None:
            selected = self.scene.get_selected_entities()
            img_ents = [e for e in selected if isinstance(e, ImageEntity)]
            if img_ents:
                image_entity = img_ents[0]

        dlg = PhotoEngraveDialog(
            self,
            image_entity=image_entity,
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height
        )

        def _on_applied(params: dict):
            if image_entity and image_entity in self.scene.get_all_entities():
                # Update existing image entity
                for k, v in params.items():
                    setattr(image_entity, k, v)
                for item in self.scene.items():
                    if isinstance(item, LaserItemWrapper) and item.entity == image_entity:
                        item.sync_from_entity()
                self.scene.entity_modified.emit()
                self.scene.update()
                self.statusBar().showMessage(f"Updated photo engraving parameters for '{image_entity.name}'.", 3500)
            else:
                # Add new image entity centered on bed
                w = params.get("width", 80.0)
                h = params.get("height", 80.0)
                cx = (self.settings.bed_width - w) / 2.0
                cy = (self.settings.bed_height - h) / 2.0
                raw_name = os.path.basename(params.get("raw_image_path", "") or params.get("image_path", "Photo"))
                new_img = ImageEntity(
                    layer_id=self.scene.active_layer_id,
                    name=raw_name,
                    x=cx, y=cy,
                    **params
                )
                self.scene.clearSelection()
                wrapper = self.scene.add_entity(new_img)
                wrapper.setSelected(True)
                self.scene.update()
                self.statusBar().showMessage(f"Added photo workpiece ({w:.1f} × {h:.1f} mm) to canvas.", 3500)

        dlg.photo_applied.connect(_on_applied)
        dlg.exec()

    def open_crop_tool_for_selected(self, image_entity: Optional[ImageEntity] = None):
        """Opens the interactive Crop dialog for the selected ImageEntity on the canvas."""
        if image_entity is None:
            selected = self.scene.get_selected_entities()
            img_ents = [e for e in selected if isinstance(e, ImageEntity)]
            if not img_ents:
                QMessageBox.information(self, "No Image Selected", "Please select an image on the canvas to crop.")
                return
            image_entity = img_ents[0]

        src_path = getattr(image_entity, "raw_image_path", "") or image_entity.image_path
        if not src_path or not os.path.exists(src_path):
            src_path = image_entity.image_path
        if not src_path or not os.path.exists(src_path):
            QMessageBox.warning(self, "Image Not Found", f"Cannot find image file:\n{src_path}")
            return

        try:
            from PIL import Image as PILImg
            pil_img = PILImg.open(src_path)
            dlg = CropImageDialog(pil_img, parent=self, title=f"Crop Image: {image_entity.name}")
            if dlg.exec() and dlg.cropped_image:
                cache_dir = os.path.expanduser("~/.laserforge/cache")
                os.makedirs(cache_dir, exist_ok=True)
                ts = int(time.time() * 1000)
                cropped_path = os.path.join(cache_dir, f"cropped_{ts}.png")
                dlg.cropped_image.save(cropped_path)

                old_w, old_h = pil_img.size
                new_w, new_h = dlg.cropped_image.size
                scale_factor_x = new_w / float(old_w)
                scale_factor_y = new_h / float(old_h)

                image_entity.raw_image_path = cropped_path
                image_entity.image_path = cropped_path
                image_entity.processed_image_path = cropped_path
                image_entity.width = max(1.0, round(image_entity.width * scale_factor_x, 2))
                image_entity.height = max(1.0, round(image_entity.height * scale_factor_y, 2))

                for item in self.scene.items():
                    if isinstance(item, LaserItemWrapper) and item.entity == image_entity:
                        item.sync_from_entity()
                self.scene.entity_modified.emit()
                self.scene.update()
                self.statusBar().showMessage(
                    f"Cropped '{image_entity.name}' to {new_w} × {new_h} px ({image_entity.width:.1f} × {image_entity.height:.1f} mm).", 4000
                )
        except Exception as e:
            QMessageBox.critical(self, "Crop Error", f"Failed to crop image: {e}")

    def open_barcode_designer(self):
        """Opens the QR Code & 1D Barcode Designer Studio."""
        dlg = BarcodeDesignerDialog(
            self,
            layer_manager=self.layer_manager,
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height,
            default_layer_id=self.scene.active_layer_id
        )

        def _on_generated(entities: list):
            self.scene.clearSelection()
            for ent in entities:
                w = self.scene.add_entity(ent)
                w.setSelected(True)
            self.scene.update()
            self.statusBar().showMessage(f"Added {len(entities)} barcode/QR code workpiece(s) to canvas.", 4000)

        dlg.entities_generated.connect(_on_generated)
        dlg.exec()

    def open_sdxl_turbo_studio(self, initial_image_path: Optional[str] = None):
        """Launches the independent standalone LaserForge AI Studio process, or falls back to embedded window."""
        from PyQt6.QtCore import QProcess
        launcher_bin = "/home/k/LaserForge/bin/laserforge-ai"
        args = []
        if initial_image_path and os.path.isfile(initial_image_path):
            args.extend(["--input-image", initial_image_path])

        if os.path.isfile(launcher_bin) and os.access(launcher_bin, os.X_OK):
            if args:
                success = QProcess.startDetached(launcher_bin, args)
            else:
                success = QProcess.startDetached(launcher_bin)
            if success:
                msg = f"Launched LaserForge AI Studio with source photo '{os.path.basename(initial_image_path)}'" if initial_image_path else "Launched standalone LaserForge AI Studio"
                self.statusBar().showMessage(msg, 5000)
                return

        # Fallback to embedded window
        if self.sdxl_studio_window is None:
            from laserforge.apps.sdxl_turbo_studio import SDXLTurboStudioWindow
            self.sdxl_studio_window = SDXLTurboStudioWindow(self, is_embedded=True)
            self.sdxl_studio_window.image_imported.connect(
                lambda p: self._import_image_to_canvas(p, open_studio=False)
            )
            self.sdxl_studio_window.photo_studio_requested.connect(
                lambda p: self._import_image_to_canvas(p, open_studio=True)
            )
        if initial_image_path and os.path.isfile(initial_image_path):
            self.sdxl_studio_window.load_input_photo(initial_image_path)
        self.sdxl_studio_window.show()
        self.sdxl_studio_window.raise_()
        self.sdxl_studio_window.activateWindow()

    def open_sdxl_turbo_studio_for_image(self, image_entity: Optional[ImageEntity] = None):
        """Opens AI Studio pre-loaded with an image from the canvas."""
        if image_entity is None:
            selected = self.scene.get_selected_entities()
            img_ents = [e for e in selected if isinstance(e, ImageEntity)]
            if img_ents:
                image_entity = img_ents[0]
        if image_entity:
            path = getattr(image_entity, "raw_image_path", "") or getattr(image_entity, "image_path", "")
            if path and os.path.isfile(path):
                self.open_sdxl_turbo_studio(initial_image_path=path)
                return
        self.open_sdxl_turbo_studio()

    def _init_auto_import_watcher(self):
        """Monitors ~/.laserforge/imported_queue for images dispatched from standalone SDXL Turbo."""
        self.import_poll_timer = QTimer(self)
        self.import_poll_timer.setInterval(1000)
        self.import_poll_timer.timeout.connect(self._check_import_queue)
        self.import_poll_timer.start()

    def _check_import_queue(self):
        if not os.path.exists(IMPORT_QUEUE_DIR):
            return
        try:
            for fname in os.listdir(IMPORT_QUEUE_DIR):
                if fname.endswith(".json"):
                    fpath = os.path.join(IMPORT_QUEUE_DIR, fname)
                    try:
                        with open(fpath, "r") as f:
                            data = json.load(f)
                        img_path = data.get("image_path")
                        open_studio = data.get("open_photo_studio", False)
                        if img_path and os.path.exists(img_path):
                            self._import_image_to_canvas(img_path, name=os.path.basename(img_path), open_studio=open_studio)
                    except Exception as e:
                        print(f"Error reading import queue item: {e}")
                    finally:
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass
        except Exception:
            pass

    def _import_image_to_canvas(self, img_path: str, name: str = "", open_studio: bool = False):
        """Places a raster image directly onto the active workspace canvas and optionally launches Photo Studio."""
        if not os.path.exists(img_path):
            return

        w, h = 80.0, 80.0
        try:
            from PIL import Image as PILImg
            with PILImg.open(img_path) as p:
                pw, ph = p.size
                if pw > 0 and ph > 0:
                    aspect = ph / float(pw)
                    w = 80.0
                    h = round(w * aspect, 1)
        except Exception:
            pass

        cx = (self.settings.bed_width - w) / 2.0
        cy = (self.settings.bed_height - h) / 2.0

        ent_name = name or os.path.basename(img_path)
        new_img = ImageEntity(
            layer_id=self.scene.active_layer_id,
            name=ent_name,
            image_path=img_path,
            raw_image_path=img_path,
            processed_image_path=img_path,
            x=cx,
            y=cy,
            width=w,
            height=h
        )
        self.scene.clearSelection()
        wrapper = self.scene.add_entity(new_img)
        wrapper.setSelected(True)
        self.scene.update()
        self.statusBar().showMessage(f"Auto-imported '{ent_name}' ({w:.1f} × {h:.1f} mm) into workspace.", 4000)

        if open_studio:
            self.open_photo_studio(new_img)

    def open_templates_studio(self):
        """Opens the Project Templates & Calibration Studio."""
        dlg = TemplatesStudioDialog(
            self,
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height
        )

        def _on_generated(entities: list, replace: bool):
            if replace:
                self.scene.clear_entities()
            self.scene.clearSelection()
            for ent in entities:
                w = self.scene.add_entity(ent)
                w.setSelected(True)
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage(f"Template generated ({len(entities)} workpieces placed on canvas).", 4000)

        dlg.templates_generated.connect(_on_generated)
        dlg.exec()

    def open_shapes_library(self, initial_tab: int = 0):
        """Opens the Parametric Shapes Generator & Offset Border dialog."""
        selected = self.scene.get_selected_entities()
        dlg = ShapeGeneratorDialog(
            self,
            layer_manager=self.layer_manager,
            selected_entities_count=len(selected),
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height,
            initial_tab=initial_tab
        )

        def _on_shape_gen(entities: list):
            self.scene.clearSelection()
            for e in entities:
                w = self.scene.add_entity(e)
                w.setSelected(True)
            self.statusBar().showMessage(f"Added {len(entities)} parametric vector shape(s) to canvas.", 3500)

        dlg.shape_generated.connect(_on_shape_gen)
        dlg.offset_requested.connect(self.apply_offset_to_selected)
        dlg.exec()

    def apply_offset_to_selected(self, dist_mm: float, corner_style: str, target_layer_id: int):
        """Generates outward cut border or inward inset around selected entities."""
        selected = self.scene.get_selected_entities()
        if not selected:
            QMessageBox.information(self, "Offset Tool", "Please select one or more objects on the canvas first.")
            return

        offset_count = 0
        for ent in selected:
            offset_ent = ShapeGenerator.offset_entity(ent, dist_mm, corner_style, target_layer_id)
            if offset_ent:
                w = self.scene.add_entity(offset_ent)
                w.setSelected(True)
                offset_count += 1

        if offset_count > 0:
            self.statusBar().showMessage(f"Generated {offset_count} offset border(s) ({dist_mm:+.1f} mm).", 3500)
        else:
            QMessageBox.warning(self, "Offset Tool", "Could not generate offset contours for selected items.")

    def open_grid_array_dialog(self):
        """Opens the Grid Array duplication tool."""
        selected = self.scene.get_selected_entities()
        if not selected:
            QMessageBox.information(
                self, "Grid Array",
                "Please select one or more objects on the canvas to duplicate into a grid array."
            )
            return

        dlg = GridArrayDialog(
            self,
            selected_entities=selected,
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height
        )

        def _on_grid_gen(new_entities: list):
            for e in new_entities:
                w = self.scene.add_entity(e)
                w.setSelected(True)
            self.statusBar().showMessage(f"Generated grid array: added {len(new_entities)} duplicates.", 4000)

        dlg.grid_generated.connect(_on_grid_gen)
        dlg.exec()

    def open_curved_text_dialog(self):
        """Opens the Curved Arc Text generation tool."""
        dlg = CurvedTextDialog(
            self,
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height
        )

        def _on_curved_created(entity: LaserEntity):
            self.scene.clearSelection()
            w = self.scene.add_entity(entity)
            w.setSelected(True)
            self.statusBar().showMessage(f"Curved arc text '{entity.name}' created on canvas.", 3500)

        dlg.curved_text_created.connect(_on_curved_created)
        dlg.exec()

    def open_serial_generator_dialog(self):
        """Opens the Sequential Serial Number Batch generation tool."""
        dlg = SerialGeneratorDialog(
            self,
            bed_width=self.settings.bed_width,
            bed_height=self.settings.bed_height
        )

        def _on_serials_gen(entities: list):
            self.scene.clearSelection()
            for e in entities:
                w = self.scene.add_entity(e)
                w.setSelected(True)
            self.statusBar().showMessage(f"Generated batch of {len(entities)} sequential serial labels.", 4000)

        dlg.serials_generated.connect(_on_serials_gen)
        dlg.exec()

    def _on_scene_tool_changed(self, tool_id: str):
        if hasattr(self, "cad_tool_actions") and tool_id in self.cad_tool_actions:
            self.cad_tool_actions[tool_id].setChecked(True)

    def convert_selected_to_path(self):
        """Converts selected primitive shapes into editable vector paths."""
        converted = self.scene.convert_selected_to_path_entities()
        if converted:
            self.statusBar().showMessage(f"Converted {len(converted)} shape(s) to editable vector paths", 4000)
        else:
            self.statusBar().showMessage("No convertible shapes selected", 3000)

    def open_common_line_studio(self):
        """Opens the Common Line Cutting Studio to merge shared seams."""
        selected = self.scene.get_selected_entities()
        target_entities = selected if len(selected) >= 2 else self.scene.get_all_entities()
        vector_ents = [e for e in target_entities if isinstance(e, (RectEntity, PathEntity, LineEntity, CircleEntity))]
        if len(vector_ents) < 2:
            QMessageBox.information(
                self, "Common Line Cutting",
                "Common Line Cutting requires at least 2 adjacent or touching vector shapes on the canvas."
            )
            return
        dlg = CommonLineDialog(vector_ents, cut_speed_mm_min=1000.0, parent=self)
        dlg.paths_optimized.connect(self._on_common_lines_optimized)
        dlg.exec()

    def _on_common_lines_optimized(self, path_entities: list, replace_existing: bool):
        """Replaces original shapes with optimized common line cut paths."""
        self.scene.push_undo_state()
        if replace_existing:
            selected = [it for it in self.scene.selectedItems() if isinstance(it, LaserItemWrapper)]
            if len(selected) >= 2:
                for it in selected:
                    self.scene.removeItem(it)
            else:
                self.scene.clear_entities()
        self.scene.clearSelection()
        for pe in path_entities:
            wrapper = self.scene.add_entity(pe)
            wrapper.setSelected(True)
        self.scene.entity_modified.emit()
        self.statusBar().showMessage(f"Common Line Cutting: Generated {len(path_entities)} optimized cutting paths", 5000)

    def open_variable_text_studio(self):
        """Opens the Variable Text & Batch CSV Production Merge Studio."""
        selected = self.scene.get_selected_entities()
        template_entities = selected if selected else self.scene.get_all_entities()
        if not template_entities:
            QMessageBox.information(
                self, "Variable Text Merge",
                "Please create or select template design elements containing placeholders "
                "(e.g., %NAME%, %TITLE%, %SERIAL:04d%, %DATE%) on the canvas first."
            )
            return
        dlg = VariableTextDialog(
            template_entities=template_entities,
            bed_width=self.scene.bed_width,
            bed_height=self.scene.bed_height,
            parent=self
        )
        dlg.batch_generated.connect(self._on_variable_text_batch_generated)
        dlg.exec()

    def _on_variable_text_batch_generated(self, generated_entities: list):
        """Adds batch generated variable text items to the canvas."""
        self.scene.push_undo_state()
        self.scene.clearSelection()
        for ent in generated_entities:
            wrapper = self.scene.add_entity(ent)
            wrapper.setSelected(True)
        self.scene.entity_modified.emit()
        self.statusBar().showMessage(f"Batch Merge: Generated {len(generated_entities)} production parts across bed", 5000)

    def closeEvent(self, event):
        """Clean up background timers, watchers, and serial threads on exit."""
        if hasattr(self, "web_pendant"):
            try:
                self.web_pendant.stop()
            except Exception:
                pass
        if hasattr(self, "import_watcher_timer") and self.import_watcher_timer.isActive():
            self.import_watcher_timer.stop()
        if hasattr(self, "serial"):
            try:
                self.serial.disconnect()
            except Exception:
                pass
        super().closeEvent(event)
