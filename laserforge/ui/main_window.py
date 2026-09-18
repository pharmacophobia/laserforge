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
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QDockWidget, QTabWidget, QFileDialog, QMessageBox, QLabel,
    QStatusBar, QPushButton, QInputDialog, QButtonGroup,
    QDoubleSpinBox, QComboBox, QFontComboBox, QToolButton, QMenu,
    QLineEdit
)
from PyQt6.QtCore import Qt, QSize, QPointF, QTimer
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
        from laserforge.core.camera_engine import CameraEngine
        self.camera_engine = CameraEngine()

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
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self._create_font_toolbar()
        self._create_dock_panels()
        self._create_bottom_palette_dock()
        self._create_status_bar()

        # Connect event signals
        self._connect_signals()

        # Set canvas bed bounds
        self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height)
        self.canvas_widget.view.zoom_to_fit()

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

        # Maximize to fit display cleanly
        self.showMaximized()

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

        self.act_bundle_packager = QAction("Project & Profile Packager Studio (.lfpak)...", self)
        self.act_bundle_packager.setShortcut("Ctrl+Shift+P")
        self.act_bundle_packager.setToolTip("Export or restore project artwork, material calibrations, and machine profiles (.lfpak) (Ctrl+Shift+P)")
        self.act_bundle_packager.triggered.connect(self.open_bundle_packager_studio)

        self.act_import_svg = QAction("Import SVG / Vector...", self)
        self.act_import_svg.setShortcut("Ctrl+I")
        self.act_import_svg.triggered.connect(self.import_svg)

        self.act_import_img = QAction("Import Image...", self)
        self.act_import_img.triggered.connect(self.import_image)

        self.act_trace_image = QAction("Trace Image to Vector (SVG)...", self)
        self.act_trace_image.setShortcut("Ctrl+T")
        self.act_trace_image.setToolTip("Convert bitmap image to vector paths / SVG")
        self.act_trace_image.triggered.connect(self.trace_image)

        self.act_image_cutout = QAction("Auto Cutout to SVG...", self)
        self.act_image_cutout.setShortcut("Ctrl+Shift+C")
        self.act_image_cutout.setToolTip("Automatically convert image to vector laser cutout contour (+offset border)")
        self.act_image_cutout.triggered.connect(lambda: self.auto_image_cutout())

        self.act_import_dxf = QAction("Import DXF Vector...", self)
        self.act_import_dxf.setShortcut("Ctrl+Alt+D")
        self.act_import_dxf.setToolTip("Import AutoCAD DXF vector files from CAD / Fusion 360 (Ctrl+Alt+D)")
        self.act_import_dxf.triggered.connect(lambda: self.import_dxf())

        self.act_export_svg = QAction("Export SVG File...", self)
        self.act_export_svg.setShortcut("Ctrl+Shift+E")
        self.act_export_svg.setToolTip("Export canvas artwork to standard W3C SVG vector file (Ctrl+Shift+E)")
        self.act_export_svg.triggered.connect(self.export_svg)

        self.act_export_dxf = QAction("Export DXF File...", self)
        self.act_export_dxf.setToolTip("Export canvas vector paths to standard AutoCAD DXF file")
        self.act_export_dxf.triggered.connect(self.export_dxf)

        self.act_job_estimator = QAction("Job Cost & Time Estimator...", self)
        self.act_job_estimator.setShortcut("Ctrl+Shift+M")
        self.act_job_estimator.setToolTip("Pre-job calculation of cutting run time, sheet area, and cost quote (Ctrl+Shift+M)")
        self.act_job_estimator.triggered.connect(self.open_job_estimator)

        self.act_directional_hatch = QAction("Directional Vector Hatching...", self)
        self.act_directional_hatch.setShortcut("Ctrl+Shift+H")
        self.act_directional_hatch.setToolTip("Fill unconnected vector shapes with directional lines (>= 15° neighbor contrast, center-to-edge convergence) (Ctrl+Shift+H)")
        self.act_directional_hatch.triggered.connect(self.open_directional_hatching)

        self.act_nesting = QAction("2D Nesting Optimizer Studio...", self)
        self.act_nesting.setShortcut("Ctrl+Shift+N")
        self.act_nesting.setToolTip("Auto-pack shapes onto sheet material to maximize cutting area and eliminate scrap waste (Ctrl+Shift+N)")
        self.act_nesting.triggered.connect(self.open_nesting_studio)

        self.act_rotary = QAction("Rotary Axis Studio...", self)
        self.act_rotary.setShortcut("Ctrl+Shift+R")
        self.act_rotary.setToolTip("Configure Roller and Chuck rotary attachments for cylindrical laser engraving (Ctrl+Shift+R)")
        self.act_rotary.triggered.connect(self.open_rotary_studio)

        self.act_box_generator = QAction("Box & Enclosure Studio...", self)
        self.act_box_generator.setShortcut("Ctrl+Shift+J")
        self.act_box_generator.setToolTip("Parametric Box & Finger-Joint Enclosure Studio (Ctrl+Shift+J)")
        self.act_box_generator.triggered.connect(self.open_box_studio)

        self.act_living_hinge = QAction("Living Hinges & Lattice Flex Studio...", self)
        self.act_living_hinge.setShortcut("Ctrl+Alt+H")
        self.act_living_hinge.setToolTip("Parametric Living Hinge & Lattice Flex pattern generator for curved wood & acrylic bends (Ctrl+Alt+H)")
        self.act_living_hinge.triggered.connect(self.open_living_hinge_studio)

        self.act_material_test_studio = QAction("Automated Material Test Matrix Studio...", self)
        self.act_material_test_studio.setShortcut("Ctrl+Alt+M")
        self.act_material_test_studio.setToolTip("Parametric Speed vs Power calibration grid with Hershey stroke labels (Ctrl+Alt+M)")
        self.act_material_test_studio.triggered.connect(self.open_material_test_studio)

        self.act_relief_studio = QAction("3D Relief & Automated Z-Step Studio...", self)
        self.act_relief_studio.setShortcut("Ctrl+Alt+Z")
        self.act_relief_studio.setToolTip("3D grayscale heightmap relief carver and motorized Z-axis multi-pass step down (Ctrl+Alt+Z)")
        self.act_relief_studio.triggered.connect(self.open_relief_studio)

        self.act_galvo_studio = QAction("Galvo & Fiber Marking Laser Studio...", self)
        self.act_galvo_studio.setShortcut("Ctrl+Alt+F")
        self.act_galvo_studio.setToolTip("Galvanometer mirror settle delay tuning and transverse beam wobble generator (Ctrl+Alt+F)")
        self.act_galvo_studio.triggered.connect(self.open_galvo_studio)

        self.act_ruida_studio = QAction("Ruida DSP Ethernet Controller & .rd Studio...", self)
        self.act_ruida_studio.setShortcut("Ctrl+Alt+R")
        self.act_ruida_studio.setToolTip("Compile Ruida .rd binary files and transmit jobs over Ethernet UDP to CO2 lasers (Ctrl+Alt+R)")
        self.act_ruida_studio.triggered.connect(self.open_ruida_studio)

        self.act_web_pendant = QAction("Mobile Remote Jogger & Web Pendant...", self)
        self.act_web_pendant.setShortcut("Ctrl+Alt+W")
        self.act_web_pendant.setToolTip("Launch mobile phone / tablet touch-screen remote jogger and monitoring server (Ctrl+Alt+W)")
        self.act_web_pendant.triggered.connect(self.open_web_pendant_dialog)

        self.act_single_line_text = QAction("Single-Line Stroke Text...", self)
        self.act_single_line_text.setShortcut("Ctrl+Shift+F")
        self.act_single_line_text.setToolTip("Generate single-stroke Hershey vector text for fast laser engraving (Ctrl+Shift+F)")
        self.act_single_line_text.triggered.connect(self.open_single_line_text_studio)

        self.act_kerf_test = QAction("Kerf Test Gauge Studio...", self)
        self.act_kerf_test.setShortcut("Ctrl+Alt+K")
        self.act_kerf_test.setToolTip("Generate automated parametric kerf calibration test gauges (Ctrl+Alt+K)")
        self.act_kerf_test.triggered.connect(self.open_kerf_test_studio)

        self.act_import_lbrn = QAction("Import LightBurn Project (.lbrn, .lbrn2)...", self)
        self.act_import_lbrn.setShortcut("Ctrl+Alt+L")
        self.act_import_lbrn.setToolTip("Import native LightBurn .lbrn2 (JSON) or .lbrn (XML) project files (Ctrl+Alt+L)")
        self.act_import_lbrn.triggered.connect(self.import_lbrn)

        self.act_holding_tabs = QAction("Holding Tabs & Micro-Bridges Studio...", self)
        self.act_holding_tabs.setShortcut("Ctrl+Alt+T")
        self.act_holding_tabs.setToolTip("Configure structural holding tabs and uncut micro-bridges for honeycomb bed protection (Ctrl+Alt+T)")
        self.act_holding_tabs.triggered.connect(self.open_holding_tabs_studio)

        self.act_print_and_cut = QAction("Print & Cut (2-Point Optical Registration)...", self)
        self.act_print_and_cut.setShortcut("Ctrl+Alt+P")
        self.act_print_and_cut.setToolTip("Align digital cut lines to physical pre-printed stock via 2-point optical / machine registration (Ctrl+Alt+P)")
        self.act_print_and_cut.triggered.connect(self.open_print_and_cut_studio)

        self.act_corner_l_marks = QAction("Add Corner 90° L-Marks", self)
        self.act_corner_l_marks.setToolTip("Draw 90-degree corner L-tick alignment marks on workpiece perimeter")
        self.act_corner_l_marks.triggered.connect(self.add_corner_l_marks_quick)

        self.act_center_cross = QAction("Add Center '+' Registration Mark", self)
        self.act_center_cross.setToolTip("Draw a centered '+' registration cross mark on workpiece center")
        self.act_center_cross.triggered.connect(self.add_center_cross_quick)

        self.act_alignment_marks_studio = QAction("Alignment & Registration Marks Studio...", self)
        self.act_alignment_marks_studio.setToolTip("Studio for Corner 90° L-Marks and Center '+' Cross registration marks")
        self.act_alignment_marks_studio.triggered.connect(lambda: self.open_alignment_marks_studio())

        self.act_art_library = QAction("Art & Component Library...", self)
        self.act_art_library.setShortcut("Alt+A")
        self.act_art_library.setToolTip("Open the reusable art and component library dock panel (Alt+A)")
        self.act_art_library.triggered.connect(self.show_art_library_dock)

        self.act_add_to_art_library = QAction("Add Selection to Art Library...", self)
        self.act_add_to_art_library.setShortcut("Ctrl+Shift+L")
        self.act_add_to_art_library.setToolTip("Save selected vector shapes to the active Art Library (Ctrl+Shift+L)")
        self.act_add_to_art_library.triggered.connect(self.add_selection_to_art_library)

        self.act_common_line = QAction("Common Line Cutting Studio...", self)
        self.act_common_line.setShortcut("Ctrl+Alt+O")
        self.act_common_line.setToolTip("Detect and eliminate coincident/touching cut lines between adjacent shapes (Ctrl+Alt+O)")
        self.act_common_line.triggered.connect(self.open_common_line_studio)

        self.act_variable_text = QAction("Variable Text & CSV Batch Merge...", self)
        self.act_variable_text.setShortcut("Ctrl+Alt+V")
        self.act_variable_text.setToolTip("Batch merge CSV/spreadsheet data into text template fields (Ctrl+Alt+V)")
        self.act_variable_text.triggered.connect(self.open_variable_text_studio)

        self.act_convert_to_path = QAction("Convert to Editable Vector Path", self)
        self.act_convert_to_path.setToolTip("Convert selected primitive rectangles, circles, or lines into vector paths for node editing")
        self.act_convert_to_path.triggered.connect(self.convert_selected_to_path)

        self.act_z_probe = QAction("Auto-Focus & Z-Touch Plate Studio (G38.2)...", self)
        self.act_z_probe.setToolTip("Automated touch plate focal calibration cycle and WCS Z-zeroing")
        self.act_z_probe.triggered.connect(self.open_z_probe_studio)

        self.act_surface_wrap = QAction("3D Curved Surface Wrapping Studio...", self)
        self.act_surface_wrap.setToolTip("Project 2D vector artwork onto cylindrical, spherical, and inclined non-planar surfaces")
        self.act_surface_wrap.triggered.connect(self.open_surface_wrap_studio)

        self.act_snap_grid = QAction("Snap to Grid", self)
        self.act_snap_grid.setCheckable(True)
        self.act_snap_grid.setChecked(True)
        self.act_snap_grid.setShortcut("Ctrl+Shift+G")
        self.act_snap_grid.setToolTip("Toggle automatic grid snapping for CAD objects (Ctrl+Shift+G)")
        self.act_snap_grid.toggled.connect(self._on_snap_grid_toggled)

        self.act_toggle_guides = QAction("Show Alignment Guides", self)
        self.act_toggle_guides.setCheckable(True)
        self.act_toggle_guides.setChecked(True)
        self.act_toggle_guides.setShortcut("Ctrl+;")
        self.act_toggle_guides.setToolTip("Toggle display of alignment guide lines (Ctrl+;)")
        self.act_toggle_guides.toggled.connect(self._on_toggle_guides)

        self.act_clear_guides = QAction("Clear All Alignment Guides", self)
        self.act_clear_guides.setToolTip("Remove all horizontal and vertical guide lines")
        self.act_clear_guides.triggered.connect(lambda: self.scene.clear_guides())

        self.act_export_gcode = QAction("Export G-Code...", self)
        self.act_export_gcode.setShortcut("Ctrl+E")
        self.act_export_gcode.triggered.connect(self.export_gcode)

        # Specialized Tools Actions
        self.act_business_card = QAction("Business Card Studio...", self)
        self.act_business_card.setShortcut("Ctrl+B")
        self.act_business_card.setToolTip("Design business cards, vector QR codes, cutting jigs & batch arrays")
        self.act_business_card.triggered.connect(self.open_business_card_studio)

        self.act_material_lib = QAction("3W Material Library & Presets...", self)
        self.act_material_lib.setShortcut("Ctrl+M")
        self.act_material_lib.setToolTip("Pre-calibrated speed & power database tuned for 3W blue diode lasers")
        self.act_material_lib.triggered.connect(self.open_material_library)

        self.act_test_matrix = QAction("Generate Material Test Matrix...", self)
        self.act_test_matrix.setToolTip("Parametric Power vs. Speed test grid for 3W laser calibration")
        self.act_test_matrix.triggered.connect(self.open_test_matrix_dialog)

        self.act_align_workpiece = QAction("Workpiece Alignment & Laser Targeting...", self)
        self.act_align_workpiece.setShortcut("Ctrl+L")
        self.act_align_workpiece.setToolTip("Target workpiece with low-power beam, 2-point Print & Cut rotation, corner jigs")
        self.act_align_workpiece.triggered.connect(self.open_alignment_assistant)

        self.act_gen_qr = QAction("Insert Vector QR Code...", self)
        self.act_gen_qr.setToolTip("Generate scalable vector QR code polygon loops for laser engraving")
        self.act_gen_qr.triggered.connect(self.generate_vector_qr_code)

        self.act_exit = QAction("Exit", self)
        self.act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_exit.triggered.connect(self.close)

        # Edit & Undo Actions
        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setToolTip("Undo last canvas action (Ctrl+Z)")
        self.act_undo.triggered.connect(self.scene.undo)

        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.setToolTip("Redo last undone canvas action (Ctrl+Y / Ctrl+Shift+Z)")
        self.act_redo.triggered.connect(self.scene.redo)

        self.act_select_all = QAction("Select All", self)
        self.act_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.act_select_all.triggered.connect(lambda: [i.setSelected(True) for i in self.scene.items()])

        self.act_delete = QAction("Delete", self)
        self.act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self.act_delete.triggered.connect(self.scene.delete_selected)

        self.act_duplicate = QAction("Duplicate", self)
        self.act_duplicate.setShortcut("Ctrl+D")
        self.act_duplicate.triggered.connect(self.scene.duplicate_selected)

        # Vector Boolean CSG Actions
        self.act_weld = QAction("⚡ Weld / Union Shapes", self)
        self.act_weld.setShortcut("Ctrl+Shift+U")
        self.act_weld.setToolTip("Weld selected overlapping vector shapes into a single perimeter (Ctrl+Shift+U)")
        self.act_weld.triggered.connect(lambda: self.scene.boolean_operation("weld"))

        self.act_subtract = QAction("➖ Subtract / Difference Shapes", self)
        self.act_subtract.setShortcut("Ctrl+Shift+D")
        self.act_subtract.setToolTip("Subtract overlapping shapes from base shape (cutout / hole) (Ctrl+Shift+D)")
        self.act_subtract.triggered.connect(lambda: self.scene.boolean_operation("subtract"))

        self.act_intersect = QAction("✖ Intersect Shapes", self)
        self.act_intersect.setShortcut("Ctrl+Shift+X")
        self.act_intersect.setToolTip("Keep only common overlapping area between selected shapes (Ctrl+Shift+X)")
        self.act_intersect.triggered.connect(lambda: self.scene.boolean_operation("intersect"))

        self.act_xor = QAction("⊻ Exclusive OR (XOR) Shapes", self)
        self.act_xor.setToolTip("Keep non-overlapping regions between selected shapes (Symmetric Difference)")
        self.act_xor.triggered.connect(lambda: self.scene.boolean_operation("xor"))

        # Design Aid & Workflow Actions
        self.act_photo_studio = QAction("Photo Engrave Studio...", self)
        self.act_photo_studio.setShortcut("Ctrl+Shift+I")
        self.act_photo_studio.setToolTip("Advanced photograph conversion studio with material burn simulation")
        self.act_photo_studio.triggered.connect(lambda: self.open_photo_studio())

        self.act_templates_studio = QAction("Project Templates & Calibration Studio...", self)
        self.act_templates_studio.setShortcut("Ctrl+Shift+T")
        self.act_templates_studio.setToolTip("Parametric templates for coasters, tumblers, keychains, tags, ornaments, and rulers")
        self.act_templates_studio.triggered.connect(self.open_templates_studio)

        self.act_shapes_lib = QAction("Parametric Shapes Generator...", self)
        self.act_shapes_lib.setShortcut("Ctrl+Alt+G")
        self.act_shapes_lib.setToolTip("Generate regular polygons, stars, gears, hearts, slots, and rings (Ctrl+Alt+G)")
        self.act_shapes_lib.triggered.connect(lambda: self.open_shapes_library(0))

        self.act_offset_border = QAction("Offset / Cut Border...", self)
        self.act_offset_border.setShortcut("Ctrl+Shift+O")
        self.act_offset_border.setToolTip("Generate an outward cut contour or inward border around selected artwork")
        self.act_offset_border.triggered.connect(lambda: self.open_shapes_library(1))

        self.act_grid_array = QAction("Grid Array Duplication...", self)
        self.act_grid_array.setShortcut("Ctrl+Shift+A")
        self.act_grid_array.setToolTip("Batch duplicate selected objects into an X by Y grid with spacing")
        self.act_grid_array.triggered.connect(self.open_grid_array_dialog)

        self.act_curved_text = QAction("Curved / Arc Text Tool...", self)
        self.act_curved_text.setToolTip("Engrave text along a circular curve or coaster rim")
        self.act_curved_text.triggered.connect(self.open_curved_text_dialog)

        self.act_serial_gen = QAction("Sequential Serial Number Batch...", self)
        self.act_serial_gen.setToolTip("Generate serialized text numbers and tags across the bed")
        self.act_serial_gen.triggered.connect(self.open_serial_generator_dialog)

        self.act_barcode_studio = QAction("QR Code & Barcode Studio...", self)
        self.act_barcode_studio.setShortcut("Ctrl+Alt+Q")
        self.act_barcode_studio.setToolTip("Design custom 2D QR codes (URL, Wi-Fi, vCard) and 1D barcodes (Ctrl+Alt+Q)")
        self.act_barcode_studio.triggered.connect(self.open_barcode_designer)

        self.act_sdxl_turbo = QAction("SDXL Turbo Generative Studio...", self)
        self.act_sdxl_turbo.setShortcut("Ctrl+Alt+S")
        self.act_sdxl_turbo.setToolTip("Real-time AI laser artwork generator optimized for 8GB VRAM")
        self.act_sdxl_turbo.triggered.connect(self.open_sdxl_turbo_studio)

        self.act_crop_image = QAction("Crop Selected Image...", self)
        self.act_crop_image.setShortcut("Ctrl+K")
        self.act_crop_image.setToolTip("Interactively crop selected image workpiece with handles and aspect ratio presets")
        self.act_crop_image.triggered.connect(self.open_crop_tool_for_selected)

        # Camera & Vision Alignment Actions
        self.act_camera_wizard = QAction("Camera Calibration Wizard...", self)
        self.act_camera_wizard.setShortcut("Ctrl+Shift+K")
        self.act_camera_wizard.setToolTip("Open 4-step Camera Lens Calibration & Bed Alignment Wizard (Ctrl+Shift+K)")
        self.act_camera_wizard.triggered.connect(self.open_camera_wizard)

        self.act_camera_update = QAction("Update Camera Bed Overlay", self)
        self.act_camera_update.setShortcut("Ctrl+Shift+B")
        self.act_camera_update.setToolTip("Capture fresh high-resolution rectified image onto laser bed (Ctrl+Shift+B)")
        self.act_camera_update.triggered.connect(self.update_camera_overlay)

        self.act_camera_toggle = QAction("Show Camera Overlay", self)
        self.act_camera_toggle.setCheckable(True)
        self.act_camera_toggle.setChecked(True)
        self.act_camera_toggle.setToolTip("Toggle camera background visibility on canvas")
        self.act_camera_toggle.toggled.connect(self.scene.set_camera_overlay_visible)

        # Alignment & Distribution Actions
        self.act_bed_center = QAction("Center on Laser Bed", self)
        self.act_bed_center.setShortcut("Ctrl+Alt+C")
        self.act_bed_center.setToolTip("Center selected objects on laser bed (Ctrl+Alt+C)")
        self.act_bed_center.triggered.connect(lambda: self.scene.align_selected("bed_center", self.settings.bed_width, self.settings.bed_height))

        self.act_center_in_parent = QAction("Center Inside Bounding Shape", self)
        self.act_center_in_parent.triggered.connect(lambda: self.scene.align_selected("center_in_parent"))

        self.act_distribute_h = QAction("Distribute Horizontally", self)
        self.act_distribute_h.triggered.connect(lambda: self.scene.align_selected("distribute_h"))

        self.act_distribute_v = QAction("Distribute Vertically", self)
        self.act_distribute_v.triggered.connect(lambda: self.scene.align_selected("distribute_v"))

        self.act_flip_h = QAction("↔ Flip Horizontally", self)
        self.act_flip_h.setShortcut("H")
        self.act_flip_h.setToolTip("Mirror selected shape(s) horizontally (Shortcut: H)")
        self.act_flip_h.triggered.connect(self.scene.flip_selected_horizontal)

        self.act_flip_v = QAction("↕ Flip Vertically", self)
        self.act_flip_v.setShortcut("V")
        self.act_flip_v.setToolTip("Mirror selected shape(s) vertically (Shortcut: V)")
        self.act_flip_v.triggered.connect(self.scene.flip_selected_vertical)

        self.act_align_left = QAction("Align Left", self)
        self.act_align_left.triggered.connect(lambda: self.scene.align_selected("left"))

        self.act_align_center_x = QAction("Align Center X", self)
        self.act_align_center_x.triggered.connect(lambda: self.scene.align_selected("center_x"))

        self.act_align_right = QAction("Align Right", self)
        self.act_align_right.triggered.connect(lambda: self.scene.align_selected("right"))

        self.act_align_top = QAction("Align Top", self)
        self.act_align_top.triggered.connect(lambda: self.scene.align_selected("top"))

        self.act_align_center_y = QAction("Align Center Y", self)
        self.act_align_center_y.triggered.connect(lambda: self.scene.align_selected("center_y"))

        self.act_align_bottom = QAction("Align Bottom", self)
        self.act_align_bottom.triggered.connect(lambda: self.scene.align_selected("bottom"))

        # View Actions
        self.act_zoom_fit = QAction("Zoom to Fit Bed", self)
        self.act_zoom_fit.setShortcut("Ctrl+0")
        self.act_zoom_fit.triggered.connect(self.canvas_widget.view.zoom_to_fit)

        # Laser & Simulation Actions
        self.act_auto_connect = QAction("Auto-Detect & Connect Laser", self)
        self.act_auto_connect.setShortcut("F3")
        self.act_auto_connect.setToolTip("Scan serial ports and automatically handshake with GRBL laser (F3)")
        self.act_auto_connect.triggered.connect(lambda: self.serial_ctrl.start_auto_connect(
            self.settings.last_connected_port if (self.settings.last_connected_port and not self.settings.last_connected_port.upper().startswith("VIRTUAL")) else None
        ))

        self.act_preview = QAction("Preview Toolpaths (Simulation)...", self)
        self.act_preview.setShortcut("Alt+P")
        self.act_preview.triggered.connect(self.preview_simulation)

        self.act_validate_gcode = QAction("Validate G-Code (GRBL Check)...", self)
        self.act_validate_gcode.setShortcut("Ctrl+Shift+V")
        self.act_validate_gcode.setToolTip("Runs pre-flight syntax, modal group, and workbed travel safety checks")
        self.act_validate_gcode.triggered.connect(self.validate_current_job)

        self.act_frame = QAction("Frame Bounding Box", self)
        self.act_frame.setShortcut("Ctrl+F")
        self.act_frame.triggered.connect(self.frame_job)

        self.act_burn_perimeter = QAction("🔥 Burn Alignment Perimeter...", self)
        self.act_burn_perimeter.setShortcut("Ctrl+Alt+B")
        self.act_burn_perimeter.setToolTip("Score or burn alignment perimeter on wasteboard or stock to position workpiece (Ctrl+Alt+B)")
        self.act_burn_perimeter.triggered.connect(lambda: self.open_burn_perimeter_tool())

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

        self.act_license = QAction("Commercial License & 30-Day Free Trial...", self)
        self.act_license.setToolTip("Activate commercial license key or view 30-day free trial status")
        self.act_license.triggered.connect(self.open_license_dialog)

        self.act_check_updates = QAction("Check for Updates...", self)
        self.act_check_updates.setToolTip("Check for new LaserForge releases and updates")
        self.act_check_updates.triggered.connect(self.check_for_updates)

    def _create_menus(self):
        menubar = self.menuBar()

        # File Menu
        menu_file = menubar.addMenu("&File")
        menu_file.addAction(self.act_new)
        menu_file.addAction(self.act_open)
        self.menu_recent = menu_file.addMenu("Open &Recent")
        self._update_recent_menu()
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_save_as)
        menu_file.addAction(self.act_bundle_packager)
        menu_file.addSeparator()
        menu_file.addAction(self.act_import_svg)
        menu_file.addAction(self.act_import_dxf)
        menu_file.addAction(self.act_import_lbrn)
        menu_file.addAction(self.act_import_img)
        menu_file.addAction(self.act_trace_image)
        menu_file.addAction(self.act_image_cutout)
        menu_file.addSeparator()
        menu_file.addAction(self.act_export_gcode)
        menu_file.addAction(self.act_export_svg)
        menu_file.addAction(self.act_export_dxf)
        menu_file.addSeparator()
        menu_file.addAction(self.act_exit)

        # Edit Menu
        menu_edit = menubar.addMenu("&Edit")
        menu_edit.addAction(self.act_undo)
        menu_edit.addAction(self.act_redo)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_select_all)
        menu_edit.addAction(self.act_duplicate)
        menu_edit.addAction(self.act_delete)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_flip_h)
        menu_edit.addAction(self.act_flip_v)
        menu_edit.addSeparator()

        # Vector Booleans submenu & actions
        menu_bool = menu_edit.addMenu("📐 Vector Booleans (CSG)")
        menu_bool.addAction(self.act_weld)
        menu_bool.addAction(self.act_subtract)
        menu_bool.addAction(self.act_intersect)
        menu_bool.addAction(self.act_xor)
        menu_edit.addAction(self.act_weld)
        menu_edit.addAction(self.act_subtract)
        menu_edit.addAction(self.act_intersect)
        menu_edit.addAction(self.act_xor)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_add_to_art_library)
        menu_edit.addAction(self.act_convert_to_path)

        # Laser Menu
        menu_laser = menubar.addMenu("&Laser")
        menu_laser.addAction(self.act_auto_connect)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_preview)
        menu_laser.addAction(self.act_job_estimator)
        menu_laser.addAction(self.act_validate_gcode)
        menu_laser.addAction(self.act_frame)
        menu_laser.addAction(self.act_burn_perimeter)
        menu_laser.addAction(self.act_start_job)
        menu_laser.addAction(self.act_pause_job)
        menu_laser.addAction(self.act_stop_job)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_align_workpiece)
        menu_laser.addAction(self.act_rotary)
        menu_laser.addAction(self.act_material_lib)
        menu_laser.addAction(self.act_material_test_studio)
        menu_laser.addAction(self.act_ruida_studio)
        menu_laser.addAction(self.act_web_pendant)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_camera_wizard)
        menu_laser.addAction(self.act_camera_update)
        menu_laser.addAction(self.act_camera_toggle)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_home)
        menu_laser.addAction(self.act_unlock)
        menu_laser.addSeparator()
        menu_laser.addAction(self.act_settings)

        # Tools Menu
        menu_tools = menubar.addMenu("&Tools")
        menu_tools.addAction(self.act_camera_wizard)
        menu_tools.addAction(self.act_camera_update)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_job_estimator)
        menu_tools.addAction(self.act_photo_studio)
        menu_tools.addAction(self.act_templates_studio)
        menu_tools.addAction(self.act_shapes_lib)
        menu_tools.addAction(self.act_offset_border)
        menu_tools.addAction(self.act_grid_array)
        menu_tools.addAction(self.act_common_line)
        menu_tools.addAction(self.act_variable_text)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_curved_text)
        menu_tools.addAction(self.act_serial_gen)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_business_card)
        menu_tools.addAction(self.act_barcode_studio)
        menu_tools.addAction(self.act_sdxl_turbo)
        menu_tools.addAction(self.act_crop_image)
        menu_tools.addAction(self.act_gen_qr)
        menu_tools.addAction(self.act_trace_image)
        menu_tools.addAction(self.act_image_cutout)
        menu_tools.addAction(self.act_directional_hatch)
        menu_tools.addAction(self.act_holding_tabs)
        menu_tools.addAction(self.act_print_and_cut)
        menu_tools.addAction(self.act_nesting)
        menu_tools.addAction(self.act_rotary)
        menu_tools.addAction(self.act_box_generator)
        menu_tools.addAction(self.act_living_hinge)
        menu_tools.addAction(self.act_single_line_text)
        menu_tools.addAction(self.act_material_test_studio)
        menu_tools.addAction(self.act_relief_studio)
        menu_tools.addAction(self.act_galvo_studio)
        menu_tools.addAction(self.act_ruida_studio)
        menu_tools.addAction(self.act_web_pendant)
        menu_tools.addAction(self.act_bundle_packager)
        menu_tools.addAction(self.act_art_library)
        menu_tools.addAction(self.act_z_probe)
        menu_tools.addAction(self.act_surface_wrap)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_material_lib)
        menu_tools.addAction(self.act_test_matrix)
        menu_tools.addAction(self.act_kerf_test)
        menu_tools.addAction(self.act_align_workpiece)
        menu_tools.addAction(self.act_burn_perimeter)
        menu_tools.addAction(self.act_alignment_marks_studio)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_preview)
        menu_tools.addAction(self.act_zoom_fit)

        # View & CAD Snapping Menu
        menu_view = menubar.addMenu("&View")
        menu_view.addAction(self.act_zoom_fit)
        menu_view.addSeparator()
        menu_view.addAction(self.act_snap_grid)
        menu_view.addAction(self.act_toggle_guides)
        menu_view.addAction(self.act_clear_guides)
        menu_view.addSeparator()
        self.menu_view_docks = menu_view.addMenu("📁 Docks & Panels")

        # Arrange & Design Aids Menu
        menu_arrange = menubar.addMenu("&Arrange")
        menu_arrange.addAction(self.act_bed_center)
        menu_arrange.addAction(self.act_center_in_parent)
        menu_arrange.addAction(self.act_common_line)
        menu_arrange.addSeparator()
        menu_arrange.addAction(self.act_align_left)
        menu_arrange.addAction(self.act_align_center_x)
        menu_arrange.addAction(self.act_align_right)
        menu_arrange.addAction(self.act_align_top)
        menu_arrange.addAction(self.act_align_center_y)
        menu_arrange.addAction(self.act_align_bottom)
        menu_arrange.addSeparator()
        menu_arrange.addAction(self.act_distribute_h)
        menu_arrange.addAction(self.act_distribute_v)
        menu_arrange.addSeparator()
        menu_arrange.addAction(self.act_flip_h)
        menu_arrange.addAction(self.act_flip_v)
        menu_arrange.addSeparator()
        menu_arrange.addAction(self.act_grid_array)
        menu_arrange.addAction(self.act_offset_border)
        menu_arrange.addSeparator()
        menu_arrange.addAction(self.act_corner_l_marks)
        menu_arrange.addAction(self.act_center_cross)
        menu_arrange.addAction(self.act_alignment_marks_studio)

        # Help Menu
        menu_help = menubar.addMenu("&Help")
        menu_help.addAction(self.act_license)
        menu_help.addAction(self.act_check_updates)
        menu_help.addSeparator()
        act_about = QAction("About LaserForge...", self)
        act_about.triggered.connect(self._show_about)
        menu_help.addAction(act_about)

    def _create_top_toolbar(self):
        # 1. Main File & Project Controls Toolbar
        tb_file = QToolBar("File Controls")
        tb_file.setMovable(True)
        tb_file.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_file)

        def add_file_btn(act, text, tooltip):
            btn = QPushButton(text)
            btn.setStyleSheet("font-weight: 500; padding: 3px 6px; font-size: 11px;")
            btn.setToolTip(tooltip)
            btn.clicked.connect(act.trigger)
            tb_file.addWidget(btn)

        add_file_btn(self.act_new, "📄 New", "New Project (Ctrl+N)")
        add_file_btn(self.act_open, "📂 Open", "Open Project (Ctrl+O)")
        add_file_btn(self.act_save, "💾 Save", "Save Project (Ctrl+S)")
        add_file_btn(self.act_bundle_packager, "📦 Package", "Project & Profile Packager (.lfpak) (Ctrl+Shift+P)")
        tb_file.addSeparator()
        add_file_btn(self.act_undo, "↩ Undo", "Undo Last Action (Ctrl+Z)")
        add_file_btn(self.act_redo, "↪ Redo", "Redo (Ctrl+Y / Ctrl+Shift+Z)")
        tb_file.addSeparator()
        add_file_btn(self.act_import_svg, "📐 SVG", "Import SVG / Vector (Ctrl+I)")
        add_file_btn(self.act_import_img, "🖼 Image", "Import Bitmap Image")
        add_file_btn(self.act_trace_image, "⚡ Trace", "Trace Image to Vector (Ctrl+T)")
        tb_file.addSeparator()
        add_file_btn(self.act_zoom_fit, "🔍 Fit Bed", "Zoom to Fit Bed (F)")
        tb_file.addSeparator()
        add_file_btn(self.act_flip_h, "↔ Flip H", "Mirror Selected Horizontally (H)")
        add_file_btn(self.act_flip_v, "↕ Flip V", "Mirror Selected Vertically (V)")
        tb_file.addSeparator()

        # Preview Button on top
        btn_preview = QPushButton("👁 Preview")
        btn_preview.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_preview.setToolTip("Preview laser path simulation & time estimate (Alt+P)")
        btn_preview.clicked.connect(self.preview_simulation)
        tb_file.addWidget(btn_preview)

        # 2. Design Studios & Specialized Tools Toolbar
        tb_studios = QToolBar("Laser Studios")
        tb_studios.setMovable(True)
        tb_studios.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_studios)
        self.studio_toolbar = tb_studios

        # Business Card Studio Button
        btn_cards = QPushButton("📇 Cards")
        btn_cards.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_cards.setToolTip("Business Card Studio (Ctrl+B) - Metal blanks, QR codes & multi-pocket cutting jigs")
        btn_cards.clicked.connect(self.open_business_card_studio)
        tb_studios.addWidget(btn_cards)

        # Photo Studio Button
        btn_photo = QPushButton("📷 Photo")
        btn_photo.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_photo.setToolTip("Photo Engrave Studio (Ctrl+Shift+I) - Advanced photograph laser preparation & simulation")
        btn_photo.clicked.connect(lambda: self.open_photo_studio())
        tb_studios.addWidget(btn_photo)

        # QR Code & Barcode Studio Button
        btn_barcode = QPushButton("📱 QR/Barcode")
        btn_barcode.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_barcode.setToolTip("QR Code & Barcode Studio (Ctrl+Q) - Custom 2D QR codes and 1D barcodes")
        btn_barcode.clicked.connect(self.open_barcode_designer)
        tb_studios.addWidget(btn_barcode)

        # SDXL Turbo Generative Studio Button
        btn_sdxl = QPushButton("🎨 SDXL Turbo")
        btn_sdxl.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_sdxl.setToolTip("SDXL Turbo Generative Studio (Ctrl+Alt+S) - 8GB VRAM optimized AI laser art")
        btn_sdxl.clicked.connect(self.open_sdxl_turbo_studio)
        tb_studios.addWidget(btn_sdxl)

        # Templates Studio Button
        btn_templates = QPushButton("📐 Templates")
        btn_templates.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_templates.setToolTip("Project Templates Studio (Ctrl+Shift+T) - Coasters, tumblers, keychains, ornaments & rulers")
        btn_templates.clicked.connect(self.open_templates_studio)
        tb_studios.addWidget(btn_templates)

        # Living Hinges Button
        btn_hinges = QPushButton("〰 Hinges")
        btn_hinges.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_hinges.setToolTip("Living Hinges & Lattice Flex Studio (Ctrl+Alt+H) - Curved wood and acrylic bends")
        btn_hinges.clicked.connect(self.open_living_hinge_studio)
        tb_studios.addWidget(btn_hinges)

        # Shapes & Offset Button
        btn_shapes = QPushButton("⭐ Shapes")
        btn_shapes.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_shapes.setToolTip("Parametric Shapes & Contour Offset Border Tool (Ctrl+Shift+S / Ctrl+Shift+O)")
        btn_shapes.clicked.connect(lambda: self.open_shapes_library(0))
        tb_studios.addWidget(btn_shapes)

        # Grid Array Button
        btn_array = QPushButton("⊞ Array")
        btn_array.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_array.setToolTip("Grid Array Matrix Duplication Tool (Ctrl+Shift+A)")
        btn_array.clicked.connect(self.open_grid_array_dialog)
        tb_studios.addWidget(btn_array)

        # 3W Material Library Button
        btn_mat = QPushButton("⚡ Materials")
        btn_mat.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_mat.setToolTip("3W Diode Laser Material Library (Ctrl+M) - Calibrated speeds, powers & test grids")
        btn_mat.clicked.connect(self.open_material_library)
        tb_studios.addWidget(btn_mat)

        # Material Matrix Studio Button
        btn_matrix = QPushButton("🧪 Matrix")
        btn_matrix.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_matrix.setToolTip("Automated Material Test Matrix Studio (Ctrl+Alt+M)")
        btn_matrix.clicked.connect(self.open_material_test_studio)
        tb_studios.addWidget(btn_matrix)

        # Mobile Web Jogger Pendant Button
        btn_pendant = QPushButton("📱 Jogger")
        btn_pendant.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_pendant.setToolTip("Mobile Remote Jogger & Web Pendant (Ctrl+Alt+W)")
        btn_pendant.clicked.connect(self.open_web_pendant_dialog)
        tb_studios.addWidget(btn_pendant)

        # Workpiece Alignment Button
        btn_align = QPushButton("🎯 Align")
        btn_align.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_align.setToolTip("Workpiece Alignment Assistant (Ctrl+L) - 5-point targeting & 2-point Print & Cut")
        btn_align.clicked.connect(self.open_alignment_assistant)
        tb_studios.addWidget(btn_align)

        # Machine Settings Button
        btn_set = QPushButton("⚙ Settings")
        btn_set.setStyleSheet("padding: 3px 6px; font-size: 11px;")
        btn_set.setToolTip("Machine & GRBL Settings (Ctrl+,)")
        btn_set.clicked.connect(self.open_machine_settings)
        tb_studios.addWidget(btn_set)

        # Camera Vision Alignment Button
        btn_cam = QToolButton()
        btn_cam.setText("📷 Cam Overlay")
        btn_cam.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_cam.setToolTip("Capture Camera Bed Overlay (Ctrl+Shift+B) / Calibration Wizard (Ctrl+Shift+K)")
        btn_cam.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn_cam.clicked.connect(self.update_camera_overlay)
        cam_menu = QMenu(btn_cam)
        cam_menu.addAction(self.act_camera_update)
        cam_menu.addAction(self.act_camera_wizard)
        cam_menu.addAction(self.act_camera_toggle)
        btn_cam.setMenu(cam_menu)
        tb_studios.addWidget(btn_cam)

        # 3. Vector Booleans CSG Toolbar
        tb_booleans = QToolBar("Vector Booleans")
        tb_booleans.setMovable(True)
        tb_booleans.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_booleans)

        btn_weld = QPushButton("⚡ Weld")
        btn_weld.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px; color: #69f0ae;")
        btn_weld.setToolTip("Weld / Union selected vector shapes into one perimeter (Ctrl+Shift+U)")
        btn_weld.clicked.connect(self.act_weld.trigger)
        tb_booleans.addWidget(btn_weld)

        btn_sub = QPushButton("➖ Subtract")
        btn_sub.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px; color: #ff5252;")
        btn_sub.setToolTip("Subtract top selected shapes from base shape (cutout / hole) (Ctrl+Shift+D)")
        btn_sub.clicked.connect(self.act_subtract.trigger)
        tb_booleans.addWidget(btn_sub)

        btn_inter = QPushButton("✖ Intersect")
        btn_inter.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px; color: #ffd740;")
        btn_inter.setToolTip("Keep overlapping intersection between selected shapes (Ctrl+Shift+X)")
        btn_inter.clicked.connect(self.act_intersect.trigger)
        tb_booleans.addWidget(btn_inter)

    def _create_font_toolbar(self):
        """Creates the LightBurn-style typography and font formatting toolbar."""
        self.font_toolbar = QToolBar("Typography & Font Tools")
        self.font_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.font_toolbar)

        lbl = QLabel(" Text: ")
        lbl.setStyleSheet("color: #b0bec5; font-weight: bold; font-size: 11px;")
        self.font_toolbar.addWidget(lbl)

        # 0. Text Content Input Box
        self.tb_text_input = QLineEdit()
        self.tb_text_input.setPlaceholderText("Enter text here...")
        self.tb_text_input.setToolTip("Edit text content for selected text element")
        self.tb_text_input.setMinimumWidth(150)
        self.tb_text_input.setMaximumWidth(280)
        self.tb_text_input.textChanged.connect(self._on_tb_text_changed)
        self.tb_text_input.editingFinished.connect(self._on_tb_text_editing_finished)
        self.font_toolbar.addWidget(self.tb_text_input)

        self.font_toolbar.addSeparator()

        lbl_font = QLabel(" Font: ")
        lbl_font.setStyleSheet("color: #b0bec5; font-size: 11px;")
        self.font_toolbar.addWidget(lbl_font)

        # 1. Font Family Combo
        self.tb_font_combo = QFontComboBox()
        self.tb_font_combo.setToolTip("Font Style / Family")
        self.tb_font_combo.setMaximumWidth(160)
        self.tb_font_combo.currentFontChanged.connect(self._on_tb_font_family_changed)
        self.font_toolbar.addWidget(self.tb_font_combo)

        # 2. Font Size Spinbox
        lbl_sz = QLabel(" Size: ")
        lbl_sz.setStyleSheet("color: #b0bec5; font-size: 11px;")
        self.font_toolbar.addWidget(lbl_sz)

        self.tb_font_size_spin = QDoubleSpinBox()
        self.tb_font_size_spin.setRange(1.0, 500.0)
        self.tb_font_size_spin.setValue(15.0)
        self.tb_font_size_spin.setSingleStep(1.0)
        self.tb_font_size_spin.setDecimals(1)
        self.tb_font_size_spin.setSuffix(" mm")
        self.tb_font_size_spin.setToolTip("Font Size (mm)")
        self.tb_font_size_spin.valueChanged.connect(self._on_tb_font_size_changed)
        self.font_toolbar.addWidget(self.tb_font_size_spin)

        self.font_toolbar.addSeparator()

        # 3. Bold, Italic, Underline
        self.tb_btn_bold = QToolButton()
        self.tb_btn_bold.setText("B")
        self.tb_btn_bold.setCheckable(True)
        self.tb_btn_bold.setToolTip("Bold (B)")
        self.tb_btn_bold.setStyleSheet("font-weight: bold; font-size: 12px; min-width: 24px; min-height: 22px;")
        self.tb_btn_bold.toggled.connect(self._on_tb_bold_toggled)
        self.font_toolbar.addWidget(self.tb_btn_bold)

        self.tb_btn_italic = QToolButton()
        self.tb_btn_italic.setText("I")
        self.tb_btn_italic.setCheckable(True)
        self.tb_btn_italic.setToolTip("Italic (I)")
        self.tb_btn_italic.setStyleSheet("font-style: italic; font-size: 12px; font-family: serif; min-width: 24px; min-height: 22px;")
        self.tb_btn_italic.toggled.connect(self._on_tb_italic_toggled)
        self.font_toolbar.addWidget(self.tb_btn_italic)

        self.tb_btn_underline = QToolButton()
        self.tb_btn_underline.setText("U")
        self.tb_btn_underline.setCheckable(True)
        self.tb_btn_underline.setToolTip("Underline (U)")
        self.tb_btn_underline.setStyleSheet("text-decoration: underline; font-size: 12px; min-width: 24px; min-height: 22px;")
        self.tb_btn_underline.toggled.connect(self._on_tb_underline_toggled)
        self.font_toolbar.addWidget(self.tb_btn_underline)

        self.font_toolbar.addSeparator()

        # 4. Outlined vs Fill Mode
        self.tb_mode_combo = QComboBox()
        self.tb_mode_combo.addItems(["Fill (Solid Engrave)", "Outlined (Vector Cut)"])
        self.tb_mode_combo.setToolTip("Text Rendering: Solid raster engraving vs vector contour cut")
        self.tb_mode_combo.currentIndexChanged.connect(self._on_tb_mode_changed)
        self.font_toolbar.addWidget(self.tb_mode_combo)

        self.font_toolbar.addSeparator()

        # 5. Quick Style Presets
        lbl_style = QLabel(" Style: ")
        lbl_style.setStyleSheet("color: #b0bec5; font-size: 11px;")
        self.font_toolbar.addWidget(lbl_style)

        self.tb_quick_style_combo = QComboBox()
        self.tb_quick_style_combo.addItem("Presets...", None)
        self.tb_quick_style_combo.addItem("Modern Clean (Sans)", "modern")
        self.tb_quick_style_combo.addItem("Industrial Bold (Cut)", "industrial")
        self.tb_quick_style_combo.addItem("Classic Serif", "serif")
        self.tb_quick_style_combo.addItem("Calligraphy (Script)", "script")
        self.tb_quick_style_combo.addItem("Monogram Initial", "monogram")
        self.tb_quick_style_combo.currentIndexChanged.connect(self._on_quick_style_selected)
        self.font_toolbar.addWidget(self.tb_quick_style_combo)

        self.font_toolbar.addSeparator()

        # 6. Curved Text & Serial Batch
        btn_arc_text = QToolButton()
        btn_arc_text.setText("⌒ Arc Text...")
        btn_arc_text.setToolTip("Curved / Circular Arc Text Tool (text along a radius)")
        btn_arc_text.setStyleSheet("font-weight: bold; font-size: 11px; padding: 3px 6px;")
        btn_arc_text.clicked.connect(self.open_curved_text_dialog)
        self.font_toolbar.addWidget(btn_arc_text)

        btn_serial = QToolButton()
        btn_serial.setText("123 Serial...")
        btn_serial.setToolTip("Sequential Serial Number Batch Generator")
        btn_serial.setStyleSheet("font-weight: bold; font-size: 11px; padding: 3px 6px;")
        btn_serial.clicked.connect(self.open_serial_generator_dialog)
        self.font_toolbar.addWidget(btn_serial)

        btn_center_in_parent = QToolButton()
        btn_center_in_parent.setText("🎯 In Shape")
        btn_center_in_parent.setToolTip("Center text inside selected parent shape")
        btn_center_in_parent.setStyleSheet("font-weight: bold; font-size: 11px; padding: 3px 6px;")
        btn_center_in_parent.clicked.connect(lambda: self.scene.align_selected("center_in_parent"))
        self.font_toolbar.addWidget(btn_center_in_parent)

        # Initially disabled until text is selected
        self.font_toolbar.setEnabled(False)

    def _create_cad_toolbar(self):
        cad_tb = QToolBar("CAD Drawing Tools")
        cad_tb.setMovable(False)
        cad_tb.setOrientation(Qt.Orientation.Vertical)
        cad_tb.setIconSize(QSize(30, 30))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, cad_tb)

        self.cad_tool_actions: Dict[str, QAction] = {}
        action_group = QActionGroup(self)
        action_group.setExclusive(True)

        tools = [
            ("Select (S)", TOOL_SELECT, "↖", "#00e5ff"),
            ("Node Edit (N)", TOOL_NODE_EDIT, "☩", "#ff4081"),
            ("Trim Scissor (X)", TOOL_TRIM, "✂", "#ff9100"),
            ("Measure Caliper (M)", TOOL_MEASURE, "📐", "#ffd600"),
            ("Rectangle (R)", TOOL_RECT, "▭", "#69f0ae"),
            ("Circle (C)", TOOL_CIRCLE, "◯", "#ffd740"),
            ("Line (L)", TOOL_LINE, "╱", "#00e676"),
            ("Text (T)", TOOL_TEXT, "A", "#e040fb"),
        ]

        for tip, tool_id, icon_char, color in tools:
            action = QAction(create_tool_icon(icon_char, fg_color=color), tip, self)
            action.setCheckable(True)
            if tool_id == TOOL_SELECT:
                action.setChecked(True)
            action.triggered.connect(lambda checked, tid=tool_id: self.scene.set_active_tool(tid))
            action_group.addAction(action)
            cad_tb.addAction(action)
            self.cad_tool_actions[tool_id] = action

        self.scene.tool_changed.connect(self._on_scene_tool_changed)

        cad_tb.addSeparator()

        # Image Import Action
        act_img = QAction(create_tool_icon("🖼", fg_color="#40c4ff"), "Insert Image", self)
        act_img.triggered.connect(self.import_image)
        cad_tb.addAction(act_img)

        # SVG Import Action
        act_svg = QAction(create_tool_icon("SVG", fg_color="#b388ff"), "Import SVG Vector", self)
        act_svg.triggered.connect(self.import_svg)
        cad_tb.addAction(act_svg)

        # DXF Import Action
        act_dxf = QAction(create_tool_icon("DXF", fg_color="#00e676"), "Import AutoCAD DXF (Ctrl+Alt+D)", self)
        act_dxf.setToolTip("Import AutoCAD DXF vector files from CAD / Fusion 360 (Ctrl+Alt+D)")
        act_dxf.triggered.connect(lambda: self.import_dxf())
        cad_tb.addAction(act_dxf)

        # Trace Image Action
        act_trace = QAction(create_tool_icon("⚡", fg_color="#ffd600"), "Trace Image to Vector (SVG)", self)
        act_trace.triggered.connect(self.trace_image)
        cad_tb.addAction(act_trace)

        # Auto Cutout Action
        act_cutout = QAction(create_tool_icon("✂️", fg_color="#ff5252"), "Auto Cutout to SVG (Ctrl+Shift+C)", self)
        act_cutout.setToolTip("Auto Cutout to SVG: generate laser cut line around image (Ctrl+Shift+C)")
        act_cutout.triggered.connect(lambda: self.auto_image_cutout())
        cad_tb.addAction(act_cutout)

        # Directional Vector Hatching Action
        act_cad_hatch = QAction(create_tool_icon("📐", fg_color="#00e5ff"), "Directional Vector Hatching (Ctrl+Shift+H)", self)
        act_cad_hatch.setToolTip("Directional Vector Hatching: multi-angle infill with >= 15° neighbor contrast (Ctrl+Shift+H)")
        act_cad_hatch.triggered.connect(self.open_directional_hatching)
        cad_tb.addAction(act_cad_hatch)

        # 2D Nesting Optimizer Action
        act_cad_nest = QAction(create_tool_icon("📦", fg_color="#00e676"), "2D Nesting Optimizer Studio (Ctrl+Shift+N)", self)
        act_cad_nest.setToolTip("2D Nesting Optimizer: pack shapes onto sheet material to eliminate scrap waste (Ctrl+Shift+N)")
        act_cad_nest.triggered.connect(self.open_nesting_studio)
        cad_tb.addAction(act_cad_nest)

        # Job Cost & Time Estimator Action
        act_cad_est = QAction(create_tool_icon("⏱️", fg_color="#ffab00"), "Job Cost & Time Estimator (Ctrl+Shift+M)", self)
        act_cad_est.setToolTip("Pre-job calculation of cutting run time, sheet area, and cost quote (Ctrl+Shift+M)")
        act_cad_est.triggered.connect(self.open_job_estimator)
        cad_tb.addAction(act_cad_est)

        # Business Card quick tool
        act_cad_cards = QAction(create_tool_icon("📇", fg_color="#00e5ff"), "Business Card Studio (Ctrl+B)", self)
        act_cad_cards.triggered.connect(self.open_business_card_studio)
        cad_tb.addAction(act_cad_cards)

        # Workpiece Alignment quick tool
        act_cad_align = QAction(create_tool_icon("🎯", fg_color="#ff4081"), "Align Workpiece (Ctrl+L)", self)
        act_cad_align.triggered.connect(self.open_alignment_assistant)
        cad_tb.addAction(act_cad_align)

        # Rotary Axis Studio quick tool
        act_cad_rotary = QAction(create_tool_icon("🔄", fg_color="#64b5f6"), "Rotary Axis Studio (Ctrl+Shift+R)", self)
        act_cad_rotary.setToolTip("Configure Roller and Chuck rotary attachments for cylindrical laser engraving (Ctrl+Shift+R)")
        act_cad_rotary.triggered.connect(self.open_rotary_studio)
        cad_tb.addAction(act_cad_rotary)

        # Box & Enclosure Studio quick tool
        act_cad_box = QAction(create_tool_icon("📦", fg_color="#b388ff"), "Box & Enclosure Studio (Ctrl+Shift+J)", self)
        act_cad_box.setToolTip("Parametric Box & Finger-Joint Enclosure Studio (Ctrl+Shift+J)")
        act_cad_box.triggered.connect(self.open_box_studio)
        cad_tb.addAction(act_cad_box)

        # Single-Line Stroke Font quick tool
        act_cad_single_line = QAction(create_tool_icon("✍️", fg_color="#18ffff"), "Single-Line Stroke Text (Ctrl+Shift+F)", self)
        act_cad_single_line.setToolTip("Generate single-stroke Hershey vector text for fast laser engraving (Ctrl+Shift+F)")
        act_cad_single_line.triggered.connect(self.open_single_line_text_studio)
        cad_tb.addAction(act_cad_single_line)

        # Kerf Test Gauge quick tool
        act_cad_kerf = QAction(create_tool_icon("📏", fg_color="#00e676"), "Kerf Test Studio (Ctrl+Alt+K)", self)
        act_cad_kerf.setToolTip("Generate automated parametric kerf calibration test gauges (Ctrl+Alt+K)")
        act_cad_kerf.triggered.connect(self.open_kerf_test_studio)
        cad_tb.addAction(act_cad_kerf)

        # Photo Studio quick tool
        act_cad_photo = QAction(create_tool_icon("📷", fg_color="#e040fb"), "Photo Engrave Studio (Ctrl+Shift+I)", self)
        act_cad_photo.triggered.connect(lambda: self.open_photo_studio())
        cad_tb.addAction(act_cad_photo)

        # Crop Image quick tool
        act_cad_crop = QAction(create_tool_icon("✂️", fg_color="#ffd54f"), "Crop Selected Image (Ctrl+K)", self)
        act_cad_crop.triggered.connect(self.open_crop_tool_for_selected)
        cad_tb.addAction(act_cad_crop)

        # Barcode & QR quick tool
        act_cad_bc = QAction(create_tool_icon("📱", fg_color="#00e5ff"), "QR Code & Barcode Studio (Ctrl+Q)", self)
        act_cad_bc.triggered.connect(self.open_barcode_designer)
        cad_tb.addAction(act_cad_bc)

        # SDXL Turbo quick tool
        act_cad_sdxl = QAction(create_tool_icon("🎨", fg_color="#ff4081"), "SDXL Turbo Generative Studio (Ctrl+Alt+S)", self)
        act_cad_sdxl.triggered.connect(self.open_sdxl_turbo_studio)
        cad_tb.addAction(act_cad_sdxl)

        # Templates Studio quick tool
        act_cad_templates = QAction(create_tool_icon("📐", fg_color="#ffab40"), "Templates Studio (Ctrl+Shift+T)", self)
        act_cad_templates.triggered.connect(self.open_templates_studio)
        cad_tb.addAction(act_cad_templates)

        # Shapes Generator quick tool
        act_cad_shapes = QAction(create_tool_icon("⭐", fg_color="#69f0ae"), "Shapes Generator (Ctrl+Shift+S)", self)
        act_cad_shapes.triggered.connect(lambda: self.open_shapes_library(0))
        cad_tb.addAction(act_cad_shapes)

        # Offset Border quick tool
        act_cad_offset = QAction(create_tool_icon("⭕", fg_color="#ff4081"), "Offset / Cut Border (Ctrl+Shift+O)", self)
        act_cad_offset.triggered.connect(lambda: self.open_shapes_library(1))
        cad_tb.addAction(act_cad_offset)

        # Grid Array quick tool
        act_cad_array = QAction(create_tool_icon("⊞", fg_color="#00e5ff"), "Grid Array Matrix (Ctrl+Shift+A)", self)
        act_cad_array.triggered.connect(self.open_grid_array_dialog)
        cad_tb.addAction(act_cad_array)

        # Alignment & Registration Marks quick tool
        act_cad_align_marks = QAction(create_tool_icon("📐", fg_color="#ff9100"), "Alignment & Registration Marks Studio...", self)
        act_cad_align_marks.setToolTip("Generate 90° corner L-marks and center '+' registration marks for stock alignment")
        act_cad_align_marks.triggered.connect(lambda: self.open_alignment_marks_studio())
        cad_tb.addAction(act_cad_align_marks)

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

    def _on_laser_status_for_canvas(self, status: dict):
        """Updates the physical laser head position crosshair on the CAD canvas."""
        wpos = status.get("wpos", [0.0, 0.0, 0.0])
        state = status.get("state", "Idle")
        x = wpos[0] if (wpos and len(wpos) > 0) else 0.0
        y = wpos[1] if (wpos and len(wpos) > 1) else 0.0
        self.scene.update_laser_position(x, y, state, self.serial_ctrl.is_connected)

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
            self._add_recent_file(path)
            self.setWindowTitle(f"LaserForge - {os.path.basename(path)}")
            self.statusBar().showMessage(f"Project saved to {path}", 3000)
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
        dlg.patterns_generated.connect(self._on_living_hinge_patterns_generated)
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
            self.canvas_widget.view.set_bed_size(self.settings.bed_width, self.settings.bed_height)
            self.canvas_widget.view.set_opengl_acceleration(getattr(self.settings, "enable_opengl_canvas", True))
            self.canvas_widget.view.zoom_to_fit()
            self.statusBar().showMessage("Machine & Laser settings updated.", 3000)

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

    def update_camera_overlay(self):
        """Captures a rectified top-down frame and maps it to the canvas bed background."""
        try:
            ortho = self.camera_engine.rectify_bed_image()
            if ortho is not None and ortho.size > 0:
                h, w, ch = ortho.shape
                bytes_per_line = ch * w
                qimg = QImage(ortho.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                pix = QPixmap.fromImage(qimg)
                self.scene.set_camera_overlay_pixmap(pix, self.settings.bed_width, self.settings.bed_height)
                self.act_camera_toggle.setChecked(True)
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
