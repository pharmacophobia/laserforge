"""
LaserForge Toolbar Builder.
Constructs the CAD drawing toolbar, top operations toolbar, and font toolbar
from the ActionRegistry. Keeps toolbar layout separate from business logic.
"""
from PyQt6.QtWidgets import QMainWindow, QToolBar, QButtonGroup, QDoubleSpinBox, QComboBox, QFontComboBox, QToolButton, QPushButton, QLabel, QLineEdit, QMenu
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QActionGroup, QAction

from laserforge.ui.action_registry import ActionRegistry
from laserforge.ui.ui_utils import create_tool_icon
from laserforge.ui.canvas_scene import TOOL_SELECT, TOOL_RECT, TOOL_CIRCLE, TOOL_LINE, TOOL_TEXT, TOOL_NODE_EDIT, TOOL_TRIM, TOOL_MEASURE


class ToolbarBuilder:
    """Builds all toolbars for the LaserForge MainWindow."""

    def __init__(self, window: QMainWindow, actions: ActionRegistry):
        self._window = window
        self._actions = actions

    def build_cad_toolbar(self) -> QToolBar:
        """Creates and returns the left-side CAD drawing tools toolbar."""
        cad_tb = QToolBar("CAD Drawing Tools")
        cad_tb.setMovable(False)
        cad_tb.setOrientation(Qt.Orientation.Vertical)
        cad_tb.setIconSize(QSize(30, 30))
        self._window.addToolBar(Qt.ToolBarArea.LeftToolBarArea, cad_tb)

        self._window.cad_tool_actions = {}
        action_group = QActionGroup(self._window)
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
            action = QAction(create_tool_icon(icon_char, fg_color=color), tip, self._window)
            action.setCheckable(True)
            if tool_id == TOOL_SELECT:
                action.setChecked(True)
            # Use default argument binding so tool_id doesn't change
            action.triggered.connect(lambda checked, tid=tool_id: self._window.scene.set_active_tool(tid))
            action_group.addAction(action)
            cad_tb.addAction(action)
            self._window.cad_tool_actions[tool_id] = action

        self._window.scene.tool_changed.connect(self._window._on_scene_tool_changed)

        cad_tb.addSeparator()

        # Image Import Action
        act_img = QAction(create_tool_icon("🖼", fg_color="#40c4ff"), "Insert Image", self._window)
        act_img.triggered.connect(self._window.import_image)
        cad_tb.addAction(act_img)

        # SVG Import Action
        act_svg = QAction(create_tool_icon("SVG", fg_color="#b388ff"), "Import SVG Vector", self._window)
        act_svg.triggered.connect(self._window.import_svg)
        cad_tb.addAction(act_svg)

        # DXF Import Action
        act_dxf = QAction(create_tool_icon("DXF", fg_color="#00e676"), "Import AutoCAD DXF (Ctrl+Alt+D)", self._window)
        act_dxf.setToolTip("Import AutoCAD DXF vector files from CAD / Fusion 360 (Ctrl+Alt+D)")
        act_dxf.triggered.connect(lambda: self._window.import_dxf())
        cad_tb.addAction(act_dxf)

        # Trace Image Action
        act_trace = QAction(create_tool_icon("⚡", fg_color="#ffd600"), "Trace Image to Vector (SVG)", self._window)
        act_trace.triggered.connect(self._window.trace_image)
        cad_tb.addAction(act_trace)

        # Auto Cutout Action
        act_cutout = QAction(create_tool_icon("✂️", fg_color="#ff5252"), "Auto Cutout to SVG (Ctrl+Shift+C)", self._window)
        act_cutout.setToolTip("Auto Cutout to SVG: generate laser cut line around image (Ctrl+Shift+C)")
        act_cutout.triggered.connect(lambda: self._window.auto_image_cutout())
        cad_tb.addAction(act_cutout)

        # Directional Vector Hatching Action
        act_cad_hatch = QAction(create_tool_icon("📐", fg_color="#00e5ff"), "Directional Vector Hatching (Ctrl+Shift+H)", self._window)
        act_cad_hatch.setToolTip("Directional Vector Hatching: multi-angle infill with >= 15° neighbor contrast (Ctrl+Shift+H)")
        act_cad_hatch.triggered.connect(self._window.open_directional_hatching)
        cad_tb.addAction(act_cad_hatch)

        # 2D Nesting Optimizer Action
        act_cad_nest = QAction(create_tool_icon("📦", fg_color="#00e676"), "2D Nesting Optimizer Studio (Ctrl+Shift+N)", self._window)
        act_cad_nest.setToolTip("2D Nesting Optimizer: pack shapes onto sheet material to eliminate scrap waste (Ctrl+Shift+N)")
        act_cad_nest.triggered.connect(self._window.open_nesting_studio)
        cad_tb.addAction(act_cad_nest)

        # Job Cost & Time Estimator Action
        act_cad_est = QAction(create_tool_icon("⏱️", fg_color="#ffab00"), "Job Cost & Time Estimator (Ctrl+Shift+M)", self._window)
        act_cad_est.setToolTip("Pre-job calculation of cutting run time, sheet area, and cost quote (Ctrl+Shift+M)")
        act_cad_est.triggered.connect(self._window.open_job_estimator)
        cad_tb.addAction(act_cad_est)

        # Business Card quick tool
        act_cad_cards = QAction(create_tool_icon("📇", fg_color="#00e5ff"), "Business Card Studio (Ctrl+B)", self._window)
        act_cad_cards.triggered.connect(self._window.open_business_card_studio)
        cad_tb.addAction(act_cad_cards)

        # Workpiece Alignment quick tool
        act_cad_align = QAction(create_tool_icon("🎯", fg_color="#ff4081"), "Align Workpiece (Ctrl+L)", self._window)
        act_cad_align.triggered.connect(self._window.open_alignment_assistant)
        cad_tb.addAction(act_cad_align)

        # Rotary Axis Studio quick tool
        act_cad_rotary = QAction(create_tool_icon("🔄", fg_color="#64b5f6"), "Rotary Axis Studio (Ctrl+Shift+R)", self._window)
        act_cad_rotary.setToolTip("Configure Roller and Chuck rotary attachments for cylindrical laser engraving (Ctrl+Shift+R)")
        act_cad_rotary.triggered.connect(self._window.open_rotary_studio)
        cad_tb.addAction(act_cad_rotary)

        # Box & Enclosure Studio quick tool
        act_cad_box = QAction(create_tool_icon("📦", fg_color="#b388ff"), "Box & Enclosure Studio (Ctrl+Shift+J)", self._window)
        act_cad_box.setToolTip("Parametric Box & Finger-Joint Enclosure Studio (Ctrl+Shift+J)")
        act_cad_box.triggered.connect(self._window.open_box_studio)
        cad_tb.addAction(act_cad_box)

        # Single-Line Stroke Font quick tool
        act_cad_single_line = QAction(create_tool_icon("✍️", fg_color="#18ffff"), "Single-Line Stroke Text (Ctrl+Shift+F)", self._window)
        act_cad_single_line.setToolTip("Generate single-stroke Hershey vector text for fast laser engraving (Ctrl+Shift+F)")
        act_cad_single_line.triggered.connect(self._window.open_single_line_text_studio)
        cad_tb.addAction(act_cad_single_line)

        # Kerf Test Gauge quick tool
        act_cad_kerf = QAction(create_tool_icon("📏", fg_color="#00e676"), "Kerf Test Studio (Ctrl+Alt+K)", self._window)
        act_cad_kerf.setToolTip("Generate automated parametric kerf calibration test gauges (Ctrl+Alt+K)")
        act_cad_kerf.triggered.connect(self._window.open_kerf_test_studio)
        cad_tb.addAction(act_cad_kerf)

        # Photo Studio quick tool
        act_cad_photo = QAction(create_tool_icon("📷", fg_color="#e040fb"), "Photo Engrave Studio (Ctrl+Shift+I)", self._window)
        act_cad_photo.triggered.connect(lambda: self._window.open_photo_studio())
        cad_tb.addAction(act_cad_photo)

        # Crop Image quick tool
        act_cad_crop = QAction(create_tool_icon("✂️", fg_color="#ffd54f"), "Crop Selected Image (Ctrl+K)", self._window)
        act_cad_crop.triggered.connect(self._window.open_crop_tool_for_selected)
        cad_tb.addAction(act_cad_crop)

        # Barcode & QR quick tool
        act_cad_bc = QAction(create_tool_icon("📱", fg_color="#00e5ff"), "QR Code & Barcode Studio (Ctrl+Q)", self._window)
        act_cad_bc.triggered.connect(self._window.open_barcode_designer)
        cad_tb.addAction(act_cad_bc)

        # SDXL Turbo quick tool
        act_cad_sdxl = QAction(create_tool_icon("🎨", fg_color="#ff4081"), "SDXL Turbo Generative Studio (Ctrl+Alt+S)", self._window)
        act_cad_sdxl.triggered.connect(self._window.open_sdxl_turbo_studio)
        cad_tb.addAction(act_cad_sdxl)

        # Templates Studio quick tool
        act_cad_templates = QAction(create_tool_icon("📐", fg_color="#ffab40"), "Templates Studio (Ctrl+Shift+T)", self._window)
        act_cad_templates.triggered.connect(self._window.open_templates_studio)
        cad_tb.addAction(act_cad_templates)

        # Shapes Generator quick tool
        act_cad_shapes = QAction(create_tool_icon("⭐", fg_color="#69f0ae"), "Shapes Generator (Ctrl+Shift+S)", self._window)
        act_cad_shapes.triggered.connect(lambda: self._window.open_shapes_library(0))
        cad_tb.addAction(act_cad_shapes)

        # Offset Border quick tool
        act_cad_offset = QAction(create_tool_icon("⭕", fg_color="#ff4081"), "Offset / Cut Border (Ctrl+Shift+O)", self._window)
        act_cad_offset.triggered.connect(lambda: self._window.open_shapes_library(1))
        cad_tb.addAction(act_cad_offset)

        # Grid Array quick tool
        act_cad_array = QAction(create_tool_icon("⊞", fg_color="#00e5ff"), "Grid Array Matrix (Ctrl+Shift+A)", self._window)
        act_cad_array.triggered.connect(self._window.open_grid_array_dialog)
        cad_tb.addAction(act_cad_array)

        # Alignment & Registration Marks quick tool
        act_cad_align_marks = QAction(create_tool_icon("📐", fg_color="#ff9100"), "Alignment & Registration Marks Studio...", self._window)
        act_cad_align_marks.setToolTip("Generate 90° corner L-marks and center '+' registration marks for stock alignment")
        act_cad_align_marks.triggered.connect(lambda: self._window.open_alignment_marks_studio())
        cad_tb.addAction(act_cad_align_marks)

        cad_tb.addSeparator()

        # Zoom Fit
        act_fit = QAction(create_tool_icon("⛶", fg_color="#fff"), "Fit Workbed in View", self._window)
        act_fit.triggered.connect(self._window.canvas_widget.view.zoom_to_fit)
        cad_tb.addAction(act_fit)

        # Duplicate
        act_dup = QAction(create_tool_icon("❐", fg_color="#81d4fa"), "Duplicate (Ctrl+D)", self._window)
        act_dup.triggered.connect(self._window.scene.duplicate_selected)
        cad_tb.addAction(act_dup)

        # Delete
        act_del = QAction(create_tool_icon("✕", fg_color="#ff5252"), "Delete (Del)", self._window)
        act_del.triggered.connect(self._window.scene.delete_selected)
        cad_tb.addAction(act_del)

        return cad_tb

    def build_top_toolbar(self) -> QToolBar:
        """Creates and returns the top operations and file toolbar."""
        # 1. Main File & Project Controls Toolbar
        tb_file = QToolBar("File Controls")
        tb_file.setMovable(True)
        tb_file.setIconSize(QSize(20, 20))
        self._window.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_file)

        def add_file_btn(act, text, tooltip):
            btn = QPushButton(text)
            btn.setStyleSheet("font-weight: 500; padding: 3px 6px; font-size: 11px;")
            btn.setToolTip(tooltip)
            btn.clicked.connect(act.trigger)
            tb_file.addWidget(btn)

        add_file_btn(self._actions.new, "📄 New", "New Project (Ctrl+N)")
        add_file_btn(self._actions.open, "📂 Open", "Open Project (Ctrl+O)")
        add_file_btn(self._actions.save, "💾 Save", "Save Project (Ctrl+S)")
        add_file_btn(self._actions.bundle_packager, "📦 Package", "Project & Profile Packager (.lfpak) (Ctrl+Shift+P)")
        tb_file.addSeparator()
        add_file_btn(self._actions.undo, "↩ Undo", "Undo Last Action (Ctrl+Z)")
        add_file_btn(self._actions.redo, "↪ Redo", "Redo (Ctrl+Y / Ctrl+Shift+Z)")
        tb_file.addSeparator()
        add_file_btn(self._actions.import_svg, "📐 SVG", "Import SVG / Vector (Ctrl+I)")
        add_file_btn(self._actions.import_img, "🖼 Image", "Import Bitmap Image")
        add_file_btn(self._actions.trace_image, "⚡ Trace", "Trace Image to Vector (Ctrl+T)")
        tb_file.addSeparator()
        add_file_btn(self._actions.zoom_fit, "🔍 Fit Bed", "Zoom to Fit Bed (F)")
        tb_file.addSeparator()
        add_file_btn(self._actions.flip_h, "↔ Flip H", "Mirror Selected Horizontally (H)")
        add_file_btn(self._actions.flip_v, "↕ Flip V", "Mirror Selected Vertically (V)")
        tb_file.addSeparator()

        # Preview Button on top
        btn_preview = QPushButton("👁 Preview")
        btn_preview.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_preview.setToolTip("Preview laser path simulation & time estimate (Alt+P)")
        btn_preview.clicked.connect(self._window.preview_simulation)
        tb_file.addWidget(btn_preview)

        # 2. Design Studios & Specialized Tools Toolbar
        tb_studios = QToolBar("Laser Studios")
        tb_studios.setMovable(True)
        tb_studios.setIconSize(QSize(20, 20))
        self._window.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_studios)
        self._window.studio_toolbar = tb_studios

        # Business Card Studio Button
        btn_cards = QPushButton("📇 Cards")
        btn_cards.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_cards.setToolTip("Business Card Studio (Ctrl+B) - Metal blanks, QR codes & multi-pocket cutting jigs")
        btn_cards.clicked.connect(self._window.open_business_card_studio)
        tb_studios.addWidget(btn_cards)

        # Photo Studio Button
        btn_photo = QPushButton("📷 Photo")
        btn_photo.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_photo.setToolTip("Photo Engrave Studio (Ctrl+Shift+I) - Advanced photograph laser preparation & simulation")
        btn_photo.clicked.connect(lambda: self._window.open_photo_studio())
        tb_studios.addWidget(btn_photo)

        # QR Code & Barcode Studio Button
        btn_barcode = QPushButton("📱 QR/Barcode")
        btn_barcode.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_barcode.setToolTip("QR Code & Barcode Studio (Ctrl+Q) - Custom 2D QR codes and 1D barcodes")
        btn_barcode.clicked.connect(self._window.open_barcode_designer)
        tb_studios.addWidget(btn_barcode)

        # SDXL Turbo Generative Studio Button
        btn_sdxl = QPushButton("🎨 SDXL Turbo")
        btn_sdxl.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_sdxl.setToolTip("SDXL Turbo Generative Studio (Ctrl+Alt+S) - 8GB VRAM optimized AI laser art")
        btn_sdxl.clicked.connect(self._window.open_sdxl_turbo_studio)
        tb_studios.addWidget(btn_sdxl)

        # Templates Studio Button
        btn_templates = QPushButton("📐 Templates")
        btn_templates.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_templates.setToolTip("Project Templates Studio (Ctrl+Shift+T) - Coasters, tumblers, keychains, ornaments & rulers")
        btn_templates.clicked.connect(self._window.open_templates_studio)
        tb_studios.addWidget(btn_templates)

        # Living Hinges Button
        btn_hinges = QPushButton("〰 Hinges")
        btn_hinges.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_hinges.setToolTip("Living Hinges & Lattice Flex Studio (Ctrl+Alt+H) - Curved wood and acrylic bends")
        btn_hinges.clicked.connect(self._window.open_living_hinge_studio)
        tb_studios.addWidget(btn_hinges)

        # Shapes & Offset Button
        btn_shapes = QPushButton("⭐ Shapes")
        btn_shapes.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_shapes.setToolTip("Parametric Shapes & Contour Offset Border Tool (Ctrl+Shift+S / Ctrl+Shift+O)")
        btn_shapes.clicked.connect(lambda: self._window.open_shapes_library(0))
        tb_studios.addWidget(btn_shapes)

        # Grid Array Button
        btn_array = QPushButton("⊞ Array")
        btn_array.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_array.setToolTip("Grid Array Matrix Duplication Tool (Ctrl+Shift+A)")
        btn_array.clicked.connect(self._window.open_grid_array_dialog)
        tb_studios.addWidget(btn_array)

        # 3W Material Library Button
        btn_mat = QPushButton("⚡ Materials")
        btn_mat.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_mat.setToolTip("3W Diode Laser Material Library (Ctrl+M) - Calibrated speeds, powers & test grids")
        btn_mat.clicked.connect(self._window.open_material_library)
        tb_studios.addWidget(btn_mat)

        # Material Matrix Studio Button
        btn_matrix = QPushButton("🧪 Matrix")
        btn_matrix.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_matrix.setToolTip("Automated Material Test Matrix Studio (Ctrl+Alt+M)")
        btn_matrix.clicked.connect(self._window.open_material_test_studio)
        tb_studios.addWidget(btn_matrix)

        # Mobile Web Jogger Pendant Button
        btn_pendant = QPushButton("📱 Jogger")
        btn_pendant.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_pendant.setToolTip("Mobile Remote Jogger & Web Pendant (Ctrl+Alt+W)")
        btn_pendant.clicked.connect(self._window.open_web_pendant_dialog)
        tb_studios.addWidget(btn_pendant)

        # Workpiece Alignment Button
        btn_align = QPushButton("🎯 Align")
        btn_align.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_align.setToolTip("Workpiece Alignment Assistant (Ctrl+L) - 5-point targeting & 2-point Print & Cut")
        btn_align.clicked.connect(self._window.open_alignment_assistant)
        tb_studios.addWidget(btn_align)

        # Machine Settings Button
        btn_set = QPushButton("⚙ Settings")
        btn_set.setStyleSheet("padding: 3px 6px; font-size: 11px;")
        btn_set.setToolTip("Machine & GRBL Settings (Ctrl+,)")
        btn_set.clicked.connect(self._window.open_machine_settings)
        tb_studios.addWidget(btn_set)

        # Camera Vision Alignment Button
        btn_cam = QToolButton()
        btn_cam.setText("📷 Cam Overlay")
        btn_cam.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px;")
        btn_cam.setToolTip("Capture Camera Bed Overlay (Ctrl+Shift+B) / Calibration Wizard (Ctrl+Shift+K)")
        btn_cam.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn_cam.clicked.connect(self._window.update_camera_overlay)
        cam_menu = QMenu(btn_cam)
        cam_menu.addAction(self._actions.camera_update)
        cam_menu.addAction(self._actions.camera_wizard)
        cam_menu.addAction(self._actions.camera_fine_tune)
        cam_menu.addAction(self._actions.camera_toggle)
        btn_cam.setMenu(cam_menu)
        tb_studios.addWidget(btn_cam)

        # 3. Vector Booleans CSG Toolbar
        tb_booleans = QToolBar("Vector Booleans")
        tb_booleans.setMovable(True)
        tb_booleans.setIconSize(QSize(20, 20))
        self._window.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_booleans)

        btn_weld = QPushButton("⚡ Weld")
        btn_weld.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px; color: #69f0ae;")
        btn_weld.setToolTip("Weld / Union selected vector shapes into one perimeter (Ctrl+Shift+U)")
        btn_weld.clicked.connect(self._actions.weld.trigger)
        tb_booleans.addWidget(btn_weld)

        btn_sub = QPushButton("➖ Subtract")
        btn_sub.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px; color: #ff5252;")
        btn_sub.setToolTip("Subtract top selected shapes from base shape (cutout / hole) (Ctrl+Shift+D)")
        btn_sub.clicked.connect(self._actions.subtract.trigger)
        tb_booleans.addWidget(btn_sub)

        btn_inter = QPushButton("✖ Intersect")
        btn_inter.setStyleSheet("font-weight: bold; padding: 3px 6px; font-size: 11px; color: #ffd740;")
        btn_inter.setToolTip("Keep overlapping intersection between selected shapes (Ctrl+Shift+X)")
        btn_inter.clicked.connect(self._actions.intersect.trigger)
        tb_booleans.addWidget(btn_inter)

        return tb_file

    def build_font_toolbar(self) -> QToolBar:
        """Creates and returns the text font formatting toolbar."""
        font_toolbar = QToolBar("Typography & Font Tools")
        font_toolbar.setMovable(False)
        self._window.addToolBar(Qt.ToolBarArea.TopToolBarArea, font_toolbar)
        self._window.font_toolbar = font_toolbar

        lbl = QLabel(" Text: ")
        lbl.setStyleSheet("color: #b0bec5; font-weight: bold; font-size: 11px;")
        font_toolbar.addWidget(lbl)

        # 0. Text Content Input Box
        self._window.tb_text_input = QLineEdit()
        self._window.tb_text_input.setPlaceholderText("Enter text here...")
        self._window.tb_text_input.setToolTip("Edit text content for selected text element")
        self._window.tb_text_input.setMinimumWidth(150)
        self._window.tb_text_input.setMaximumWidth(280)
        self._window.tb_text_input.textChanged.connect(self._window._on_tb_text_changed)
        self._window.tb_text_input.editingFinished.connect(self._window._on_tb_text_editing_finished)
        font_toolbar.addWidget(self._window.tb_text_input)

        font_toolbar.addSeparator()

        lbl_font = QLabel(" Font: ")
        lbl_font.setStyleSheet("color: #b0bec5; font-size: 11px;")
        font_toolbar.addWidget(lbl_font)

        # 1. Font Family Combo
        self._window.tb_font_combo = QFontComboBox()
        self._window.tb_font_combo.setToolTip("Font Style / Family")
        self._window.tb_font_combo.setMaximumWidth(160)
        self._window.tb_font_combo.currentFontChanged.connect(self._window._on_tb_font_family_changed)
        font_toolbar.addWidget(self._window.tb_font_combo)

        # 2. Font Size Spinbox
        lbl_sz = QLabel(" Size: ")
        lbl_sz.setStyleSheet("color: #b0bec5; font-size: 11px;")
        font_toolbar.addWidget(lbl_sz)

        self._window.tb_font_size_spin = QDoubleSpinBox()
        self._window.tb_font_size_spin.setRange(1.0, 500.0)
        self._window.tb_font_size_spin.setValue(15.0)
        self._window.tb_font_size_spin.setSingleStep(1.0)
        self._window.tb_font_size_spin.setDecimals(1)
        self._window.tb_font_size_spin.setSuffix(" mm")
        self._window.tb_font_size_spin.setToolTip("Font Size (mm)")
        self._window.tb_font_size_spin.valueChanged.connect(self._window._on_tb_font_size_changed)
        font_toolbar.addWidget(self._window.tb_font_size_spin)

        font_toolbar.addSeparator()

        # 3. Bold, Italic, Underline
        self._window.tb_btn_bold = QToolButton()
        self._window.tb_btn_bold.setText("B")
        self._window.tb_btn_bold.setCheckable(True)
        self._window.tb_btn_bold.setToolTip("Bold (B)")
        self._window.tb_btn_bold.setStyleSheet("font-weight: bold; font-size: 12px; min-width: 24px; min-height: 22px;")
        self._window.tb_btn_bold.toggled.connect(self._window._on_tb_bold_toggled)
        font_toolbar.addWidget(self._window.tb_btn_bold)

        self._window.tb_btn_italic = QToolButton()
        self._window.tb_btn_italic.setText("I")
        self._window.tb_btn_italic.setCheckable(True)
        self._window.tb_btn_italic.setToolTip("Italic (I)")
        self._window.tb_btn_italic.setStyleSheet("font-style: italic; font-size: 12px; font-family: serif; min-width: 24px; min-height: 22px;")
        self._window.tb_btn_italic.toggled.connect(self._window._on_tb_italic_toggled)
        font_toolbar.addWidget(self._window.tb_btn_italic)

        self._window.tb_btn_underline = QToolButton()
        self._window.tb_btn_underline.setText("U")
        self._window.tb_btn_underline.setCheckable(True)
        self._window.tb_btn_underline.setToolTip("Underline (U)")
        self._window.tb_btn_underline.setStyleSheet("text-decoration: underline; font-size: 12px; min-width: 24px; min-height: 22px;")
        self._window.tb_btn_underline.toggled.connect(self._window._on_tb_underline_toggled)
        font_toolbar.addWidget(self._window.tb_btn_underline)

        font_toolbar.addSeparator()

        # 4. Outlined vs Fill Mode
        self._window.tb_mode_combo = QComboBox()
        self._window.tb_mode_combo.addItems(["Fill (Solid Engrave)", "Outlined (Vector Cut)"])
        self._window.tb_mode_combo.setToolTip("Text Rendering: Solid raster engraving vs vector contour cut")
        self._window.tb_mode_combo.currentIndexChanged.connect(self._window._on_tb_mode_changed)
        font_toolbar.addWidget(self._window.tb_mode_combo)

        font_toolbar.addSeparator()

        # 5. Quick Style Presets
        lbl_style = QLabel(" Style: ")
        lbl_style.setStyleSheet("color: #b0bec5; font-size: 11px;")
        font_toolbar.addWidget(lbl_style)

        self._window.tb_quick_style_combo = QComboBox()
        self._window.tb_quick_style_combo.addItem("Presets...", None)
        self._window.tb_quick_style_combo.addItem("Modern Clean (Sans)", "modern")
        self._window.tb_quick_style_combo.addItem("Industrial Bold (Cut)", "industrial")
        self._window.tb_quick_style_combo.addItem("Classic Serif", "serif")
        self._window.tb_quick_style_combo.addItem("Calligraphy (Script)", "script")
        self._window.tb_quick_style_combo.addItem("Monogram Initial", "monogram")
        self._window.tb_quick_style_combo.currentIndexChanged.connect(self._window._on_quick_style_selected)
        font_toolbar.addWidget(self._window.tb_quick_style_combo)

        font_toolbar.addSeparator()

        # 6. Curved Text & Serial Batch
        btn_arc_text = QToolButton()
        btn_arc_text.setText("⌒ Arc Text...")
        btn_arc_text.setToolTip("Curved / Circular Arc Text Tool (text along a radius)")
        btn_arc_text.setStyleSheet("font-weight: bold; font-size: 11px; padding: 3px 6px;")
        btn_arc_text.clicked.connect(self._window.open_curved_text_dialog)
        font_toolbar.addWidget(btn_arc_text)

        btn_serial = QToolButton()
        btn_serial.setText("123 Serial...")
        btn_serial.setToolTip("Sequential Serial Number Batch Generator")
        btn_serial.setStyleSheet("font-weight: bold; font-size: 11px; padding: 3px 6px;")
        btn_serial.clicked.connect(self._window.open_serial_generator_dialog)
        font_toolbar.addWidget(btn_serial)

        btn_center_in_parent = QToolButton()
        btn_center_in_parent.setText("🎯 In Shape")
        btn_center_in_parent.setToolTip("Center text inside selected parent shape")
        btn_center_in_parent.setStyleSheet("font-weight: bold; font-size: 11px; padding: 3px 6px;")
        btn_center_in_parent.clicked.connect(lambda: self._window.scene.align_selected("center_in_parent"))
        font_toolbar.addWidget(btn_center_in_parent)

        # Initially disabled until text is selected
        font_toolbar.setEnabled(False)

        return font_toolbar
