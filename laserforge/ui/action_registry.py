"""
LaserForge Action Registry.
Centralized ownership of all QAction instances for the main application window.
Separates action definition from menu/toolbar layout and signal connection.
"""
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMainWindow


class ActionRegistry:
    """Creates and owns all QAction instances for LaserForge MainWindow."""

    def __init__(self, parent: QMainWindow):
        self._parent = parent

    def build(self) -> 'ActionRegistry':
        """Creates all actions. Call once during MainWindow initialization."""
        p = self._parent
        # File Actions
        self.new = QAction("New Project", p)
        self.new.setShortcut(QKeySequence.StandardKey.New)

        self.open = QAction("Open Project...", p)
        self.open.setShortcut(QKeySequence.StandardKey.Open)

        self.save = QAction("Save Project", p)
        self.save.setShortcut(QKeySequence.StandardKey.Save)

        self.save_as = QAction("Save Project As...", p)
        self.save_as.setShortcut(QKeySequence.StandardKey.SaveAs)

        self.bundle_packager = QAction("Project & Profile Packager Studio (.lfpak)...", p)
        self.bundle_packager.setShortcut("Ctrl+Shift+P")
        self.bundle_packager.setToolTip("Export or restore project artwork, material calibrations, and machine profiles (.lfpak) (Ctrl+Shift+P)")

        self.import_svg = QAction("Import SVG / Vector...", p)
        self.import_svg.setShortcut("Ctrl+I")

        self.import_img = QAction("Import Image...", p)

        self.trace_image = QAction("Trace Image to Vector (SVG)...", p)
        self.trace_image.setShortcut("Ctrl+T")
        self.trace_image.setToolTip("Convert bitmap image to vector paths / SVG")

        self.image_cutout = QAction("Auto Cutout to SVG...", p)
        self.image_cutout.setShortcut("Ctrl+Shift+C")
        self.image_cutout.setToolTip("Automatically convert image to vector laser cutout contour (+offset border)")

        self.import_dxf = QAction("Import DXF Vector...", p)
        self.import_dxf.setShortcut("Ctrl+Alt+D")
        self.import_dxf.setToolTip("Import AutoCAD DXF vector files from CAD / Fusion 360 (Ctrl+Alt+D)")

        self.export_svg = QAction("Export SVG File...", p)
        self.export_svg.setShortcut("Ctrl+Shift+E")
        self.export_svg.setToolTip("Export canvas artwork to standard W3C SVG vector file (Ctrl+Shift+E)")

        self.export_dxf = QAction("Export DXF File...", p)
        self.export_dxf.setToolTip("Export canvas vector paths to standard AutoCAD DXF file")

        self.export_lbrn = QAction("Export LightBurn Project (.lbrn2)...", p)
        self.export_lbrn.setToolTip("Export canvas artwork and layers to native LightBurn .lbrn2 format")

        self.job_estimator = QAction("Job Cost & Time Estimator...", p)
        self.job_estimator.setShortcut("Ctrl+Shift+M")
        self.job_estimator.setToolTip("Pre-job calculation of cutting run time, sheet area, and cost quote (Ctrl+Shift+M)")

        self.directional_hatch = QAction("Directional Vector Hatching...", p)
        self.directional_hatch.setShortcut("Ctrl+Shift+H")
        self.directional_hatch.setToolTip("Fill unconnected vector shapes with directional lines (>= 15° neighbor contrast, center-to-edge convergence) (Ctrl+Shift+H)")

        self.nesting = QAction("2D Nesting Optimizer Studio...", p)
        self.nesting.setShortcut("Ctrl+Shift+N")
        self.nesting.setToolTip("Auto-pack shapes onto sheet material to maximize cutting area and eliminate scrap waste (Ctrl+Shift+N)")

        self.rotary = QAction("Rotary Axis Studio...", p)
        self.rotary.setShortcut("Ctrl+Shift+R")
        self.rotary.setToolTip("Configure Roller and Chuck rotary attachments for cylindrical laser engraving (Ctrl+Shift+R)")

        self.box_generator = QAction("Box & Enclosure Studio...", p)
        self.box_generator.setShortcut("Ctrl+Shift+J")
        self.box_generator.setToolTip("Parametric Box & Finger-Joint Enclosure Studio (Ctrl+Shift+J)")

        self.living_hinge = QAction("Living Hinges & Lattice Flex Studio...", p)
        self.living_hinge.setShortcut("Ctrl+Alt+H")
        self.living_hinge.setToolTip("Parametric Living Hinge & Lattice Flex pattern generator for curved wood & acrylic bends (Ctrl+Alt+H)")

        self.material_test_studio = QAction("Automated Material Test Matrix Studio...", p)
        self.material_test_studio.setShortcut("Ctrl+Alt+M")
        self.material_test_studio.setToolTip("Parametric Speed vs Power calibration grid with Hershey stroke labels (Ctrl+Alt+M)")

        self.relief_studio = QAction("3D Relief & Automated Z-Step Studio...", p)
        self.relief_studio.setShortcut("Ctrl+Alt+Z")
        self.relief_studio.setToolTip("3D grayscale heightmap relief carver and motorized Z-axis multi-pass step down (Ctrl+Alt+Z)")

        self.galvo_studio = QAction("Galvo & Fiber Marking Laser Studio...", p)
        self.galvo_studio.setShortcut("Ctrl+Alt+F")
        self.galvo_studio.setToolTip("Galvanometer mirror settle delay tuning and transverse beam wobble generator (Ctrl+Alt+F)")

        self.ruida_studio = QAction("Ruida DSP Ethernet Controller & .rd Studio...", p)
        self.ruida_studio.setShortcut("Ctrl+Alt+R")
        self.ruida_studio.setToolTip("Compile Ruida .rd binary files and transmit jobs over Ethernet UDP to CO2 lasers (Ctrl+Alt+R)")

        self.web_pendant = QAction("Mobile Remote Jogger & Web Pendant...", p)
        self.web_pendant.setShortcut("Ctrl+Alt+W")
        self.web_pendant.setToolTip("Launch mobile phone / tablet touch-screen remote jogger and monitoring server (Ctrl+Alt+W)")

        self.single_line_text = QAction("Single-Line Stroke Text...", p)
        self.single_line_text.setShortcut("Ctrl+Shift+F")
        self.single_line_text.setToolTip("Generate single-stroke Hershey vector text for fast laser engraving (Ctrl+Shift+F)")

        self.kerf_test = QAction("Kerf Test Gauge Studio...", p)
        self.kerf_test.setShortcut("Ctrl+Alt+K")
        self.kerf_test.setToolTip("Generate automated parametric kerf calibration test gauges (Ctrl+Alt+K)")

        self.import_lbrn = QAction("Import LightBurn Project (.lbrn, .lbrn2)...", p)
        self.import_lbrn.setShortcut("Ctrl+Alt+L")
        self.import_lbrn.setToolTip("Import native LightBurn .lbrn2 (JSON) or .lbrn (XML) project files (Ctrl+Alt+L)")

        self.holding_tabs = QAction("Holding Tabs & Micro-Bridges Studio...", p)
        self.holding_tabs.setShortcut("Ctrl+Alt+T")
        self.holding_tabs.setToolTip("Configure structural holding tabs and uncut micro-bridges for honeycomb bed protection (Ctrl+Alt+T)")

        self.print_and_cut = QAction("Print & Cut (2-Point Optical Registration)...", p)
        self.print_and_cut.setShortcut("Ctrl+Alt+P")
        self.print_and_cut.setToolTip("Align digital cut lines to physical pre-printed stock via 2-point optical / machine registration (Ctrl+Alt+P)")

        self.corner_l_marks = QAction("Add Corner 90° L-Marks", p)
        self.corner_l_marks.setToolTip("Draw 90-degree corner L-tick alignment marks on workpiece perimeter")

        self.center_cross = QAction("Add Center '+' Registration Mark", p)
        self.center_cross.setToolTip("Draw a centered '+' registration cross mark on workpiece center")

        self.alignment_marks_studio = QAction("Alignment & Registration Marks Studio...", p)
        self.alignment_marks_studio.setToolTip("Studio for Corner 90° L-Marks and Center '+' Cross registration marks")

        self.art_library = QAction("Art & Component Library...", p)
        self.art_library.setShortcut("Alt+A")
        self.art_library.setToolTip("Open the reusable art and component library dock panel (Alt+A)")

        self.add_to_art_library = QAction("Add Selection to Art Library...", p)
        self.add_to_art_library.setShortcut("Ctrl+Shift+L")
        self.add_to_art_library.setToolTip("Save selected vector shapes to the active Art Library (Ctrl+Shift+L)")

        self.common_line = QAction("Common Line Cutting Studio...", p)
        self.common_line.setShortcut("Ctrl+Alt+O")
        self.common_line.setToolTip("Detect and eliminate coincident/touching cut lines between adjacent shapes (Ctrl+Alt+O)")

        self.variable_text = QAction("Variable Text & CSV Batch Merge...", p)
        self.variable_text.setShortcut("Ctrl+Alt+V")
        self.variable_text.setToolTip("Batch merge CSV/spreadsheet data into text template fields (Ctrl+Alt+V)")

        self.convert_to_path = QAction("Convert to Editable Vector Path", p)
        self.convert_to_path.setToolTip("Convert selected primitive rectangles, circles, or lines into vector paths for node editing")

        self.z_probe = QAction("Auto-Focus & Z-Touch Plate Studio (G38.2)...", p)
        self.z_probe.setToolTip("Automated touch plate focal calibration cycle and WCS Z-zeroing")

        self.surface_wrap = QAction("3D Curved Surface Wrapping Studio...", p)
        self.surface_wrap.setToolTip("Project 2D vector artwork onto cylindrical, spherical, and inclined non-planar surfaces")

        self.snap_grid = QAction("Snap to Grid", p)
        self.snap_grid.setCheckable(True)
        self.snap_grid.setChecked(True)
        self.snap_grid.setShortcut("Ctrl+Shift+G")
        self.snap_grid.setToolTip("Toggle automatic grid snapping for CAD objects (Ctrl+Shift+G)")

        self.toggle_guides = QAction("Show Alignment Guides", p)
        self.toggle_guides.setCheckable(True)
        self.toggle_guides.setChecked(True)
        self.toggle_guides.setShortcut("Ctrl+;")
        self.toggle_guides.setToolTip("Toggle display of alignment guide lines (Ctrl+;)")

        self.clear_guides = QAction("Clear All Alignment Guides", p)
        self.clear_guides.setToolTip("Remove all horizontal and vertical guide lines")

        self.export_gcode = QAction("Export G-Code...", p)
        self.export_gcode.setShortcut("Ctrl+E")

        # Specialized Tools Actions
        self.business_card = QAction("Business Card Studio...", p)
        self.business_card.setShortcut("Ctrl+B")
        self.business_card.setToolTip("Design business cards, vector QR codes, cutting jigs & batch arrays")

        self.material_lib = QAction("3W Material Library & Presets...", p)
        self.material_lib.setShortcut("Ctrl+M")
        self.material_lib.setToolTip("Pre-calibrated speed & power database tuned for 3W blue diode lasers")

        self.test_matrix = QAction("Generate Material Test Matrix...", p)
        self.test_matrix.setToolTip("Parametric Power vs. Speed test grid for 3W laser calibration")

        self.align_workpiece = QAction("Workpiece Alignment & Laser Targeting...", p)
        self.align_workpiece.setShortcut("Ctrl+L")
        self.align_workpiece.setToolTip("Target workpiece with low-power beam, 2-point Print & Cut rotation, corner jigs")

        self.gen_qr = QAction("Insert Vector QR Code...", p)
        self.gen_qr.setToolTip("Generate scalable vector QR code polygon loops for laser engraving")

        self.exit = QAction("Exit", p)
        self.exit.setShortcut(QKeySequence.StandardKey.Quit)

        # Edit & Undo Actions
        self.undo = QAction("Undo", p)
        self.undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo.setToolTip("Undo last canvas action (Ctrl+Z)")

        self.redo = QAction("Redo", p)
        self.redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo.setToolTip("Redo last undone canvas action (Ctrl+Y / Ctrl+Shift+Z)")

        self.select_all = QAction("Select All", p)
        self.select_all.setShortcut(QKeySequence.StandardKey.SelectAll)

        self.delete = QAction("Delete", p)
        self.delete.setShortcut(QKeySequence.StandardKey.Delete)

        self.duplicate = QAction("Duplicate", p)
        self.duplicate.setShortcut("Ctrl+D")

        # Vector Boolean CSG Actions
        self.weld = QAction("⚡ Weld / Union Shapes", p)
        self.weld.setShortcut("Ctrl+Shift+U")
        self.weld.setToolTip("Weld selected overlapping vector shapes into a single perimeter (Ctrl+Shift+U)")

        self.subtract = QAction("➖ Subtract / Difference Shapes", p)
        self.subtract.setShortcut("Ctrl+Shift+D")
        self.subtract.setToolTip("Subtract overlapping shapes from base shape (cutout / hole) (Ctrl+Shift+D)")

        self.intersect = QAction("✖ Intersect Shapes", p)
        self.intersect.setShortcut("Ctrl+Shift+X")
        self.intersect.setToolTip("Keep only common overlapping area between selected shapes (Ctrl+Shift+X)")

        self.xor = QAction("⊻ Exclusive OR (XOR) Shapes", p)
        self.xor.setToolTip("Keep non-overlapping regions between selected shapes (Symmetric Difference)")

        # Design Aid & Workflow Actions
        self.photo_studio = QAction("Photo Engrave Studio...", p)
        self.photo_studio.setShortcut("Ctrl+Shift+I")
        self.photo_studio.setToolTip("Advanced photograph conversion studio with material burn simulation")

        self.templates_studio = QAction("Project Templates & Calibration Studio...", p)
        self.templates_studio.setShortcut("Ctrl+Shift+T")
        self.templates_studio.setToolTip("Parametric templates for coasters, tumblers, keychains, tags, ornaments, and rulers")

        self.shapes_lib = QAction("Parametric Shapes Generator...", p)
        self.shapes_lib.setShortcut("Ctrl+Alt+G")
        self.shapes_lib.setToolTip("Generate regular polygons, stars, gears, hearts, slots, and rings (Ctrl+Alt+G)")

        self.offset_border = QAction("Offset / Cut Border...", p)
        self.offset_border.setShortcut("Ctrl+Shift+O")
        self.offset_border.setToolTip("Generate an outward cut contour or inward border around selected artwork")

        self.grid_array = QAction("Grid Array Duplication...", p)
        self.grid_array.setShortcut("Ctrl+Shift+A")
        self.grid_array.setToolTip("Batch duplicate selected objects into an X by Y grid with spacing")

        self.curved_text = QAction("Curved / Arc Text Tool...", p)
        self.curved_text.setToolTip("Engrave text along a circular curve or coaster rim")

        self.serial_gen = QAction("Sequential Serial Number Batch...", p)
        self.serial_gen.setToolTip("Generate serialized text numbers and tags across the bed")

        self.barcode_studio = QAction("QR Code & Barcode Studio...", p)
        self.barcode_studio.setShortcut("Ctrl+Alt+Q")
        self.barcode_studio.setToolTip("Design custom 2D QR codes (URL, Wi-Fi, vCard) and 1D barcodes (Ctrl+Alt+Q)")

        self.sdxl_turbo = QAction("SDXL Turbo Generative Studio...", p)
        self.sdxl_turbo.setShortcut("Ctrl+Alt+S")
        self.sdxl_turbo.setToolTip("Real-time AI laser artwork generator optimized for 8GB VRAM")

        self.crop_image = QAction("Crop Selected Image...", p)
        self.crop_image.setShortcut("Ctrl+K")
        self.crop_image.setToolTip("Interactively crop selected image workpiece with handles and aspect ratio presets")

        # Camera & Vision Alignment Actions
        self.camera_wizard = QAction("Camera Calibration Wizard...", p)
        self.camera_wizard.setShortcut("Ctrl+Shift+K")
        self.camera_wizard.setToolTip("Open 4-step Camera Lens Calibration & Bed Alignment Wizard (Ctrl+Shift+K)")

        self.camera_update = QAction("Update Camera Bed Overlay", p)
        self.camera_update.setShortcut("Ctrl+Shift+B")
        self.camera_update.setToolTip("Capture fresh high-resolution rectified image onto laser bed (Ctrl+Shift+B)")

        self.camera_toggle = QAction("Show Camera Overlay", p)
        self.camera_toggle.setCheckable(True)
        self.camera_toggle.setChecked(True)
        self.camera_toggle.setToolTip("Toggle camera background visibility on canvas")

        self.camera_fine_tune = QAction("Fine-Tune Camera Alignment...", p)
        self.camera_fine_tune.setShortcut("Ctrl+Shift+W")
        self.camera_fine_tune.setToolTip("Nudge, scale, rotate, and fine-tune camera bed overlay alignment live on canvas (Ctrl+Shift+W)")

        self.auto_calibrate = QAction("🤖 Auto-Calibrate Workbed & Camera...", p)
        self.auto_calibrate.setShortcut("Ctrl+Alt+A")
        self.auto_calibrate.setToolTip("Automatically align workbed with laser coordinates using overhead vision (Ctrl+Alt+A)")

        self.multi_camera = QAction("📷 Multi-Camera Bed Stitcher...", p)
        self.multi_camera.setShortcut("F6")
        self.multi_camera.setToolTip("Configure multi-camera panoramic array and seamless stitching for wide laser beds (F6)")

        self.ai_assistant = QAction("🤖 DeepSeek AI Copilot...", p)
        self.ai_assistant.setShortcut("Ctrl+Alt+I")
        self.ai_assistant.setToolTip("Open DeepSeek AI Copilot for bed alignment diagnostics, camera review, and CAD manipulation (Ctrl+Alt+I)")

        # Alignment & Distribution Actions
        self.bed_center = QAction("Center on Laser Bed", p)
        self.bed_center.setShortcut("Ctrl+Alt+C")
        self.bed_center.setToolTip("Center selected objects on laser bed (Ctrl+Alt+C)")

        self.center_in_parent = QAction("Center Inside Bounding Shape", p)

        self.distribute_h = QAction("Distribute Horizontally", p)

        self.distribute_v = QAction("Distribute Vertically", p)

        self.flip_h = QAction("↔ Flip Horizontally", p)
        self.flip_h.setShortcut("H")
        self.flip_h.setToolTip("Mirror selected shape(s) horizontally (Shortcut: H)")

        self.flip_v = QAction("↕ Flip Vertically", p)
        self.flip_v.setShortcut("V")
        self.flip_v.setToolTip("Mirror selected shape(s) vertically (Shortcut: V)")

        self.align_left = QAction("Align Left", p)

        self.align_center_x = QAction("Align Center X", p)

        self.align_right = QAction("Align Right", p)

        self.align_top = QAction("Align Top", p)

        self.align_center_y = QAction("Align Center Y", p)

        self.align_bottom = QAction("Align Bottom", p)

        # View Actions
        self.zoom_fit = QAction("Zoom to Fit Bed", p)
        self.zoom_fit.setShortcut("Ctrl+0")

        # Laser & Simulation Actions
        self.auto_connect = QAction("Auto-Detect & Connect Laser", p)
        self.auto_connect.setShortcut("F3")
        self.auto_connect.setToolTip("Scan serial ports and automatically handshake with GRBL laser (F3)")

        self.preview = QAction("Preview Toolpaths (Simulation)...", p)
        self.preview.setShortcut("Alt+P")

        self.validate_gcode = QAction("Validate G-Code (GRBL Check)...", p)
        self.validate_gcode.setShortcut("Ctrl+Shift+V")
        self.validate_gcode.setToolTip("Runs pre-flight syntax, modal group, and workbed travel safety checks")

        self.frame = QAction("Frame Bounding Box", p)
        self.frame.setShortcut("Ctrl+F")

        self.burn_perimeter = QAction("🔥 Burn Alignment Perimeter...", p)
        self.burn_perimeter.setShortcut("Ctrl+Alt+B")
        self.burn_perimeter.setToolTip("Score or burn alignment perimeter on wasteboard or stock to position workpiece (Ctrl+Alt+B)")

        self.start_job = QAction("Start Laser Job", p)
        self.start_job.setShortcut("Ctrl+R")

        self.resume_job = QAction("Resume Job from % / Line...", p)
        self.resume_job.setShortcut("Ctrl+Alt+J")
        self.resume_job.setToolTip("Resume interrupted or stopped laser job from specific percentage or line number (Ctrl+Alt+J)")

        self.pause_job = QAction("Pause / Resume Job", p)


        self.stop_job = QAction("Emergency Stop / Abort", p)
        self.stop_job.setShortcut("Esc")

        self.home = QAction("Home Machine ($H)", p)

        self.unlock = QAction("Unlock Alarm ($X)", p)

        self.settings = QAction("Machine Settings...", p)
        self.settings.setShortcut("Ctrl+,")

        self.workbed_setup = QAction("Workbed Setup & Calibration Wizard...", p)
        self.workbed_setup.setShortcut("F4")
        self.workbed_setup.setToolTip("Easily configure machine work area, origin, travel limits, test corner boundaries, and wasteboard grid (F4)")

        self.license = QAction("Commercial License & 30-Day Free Trial...", p)
        self.license.setToolTip("Activate commercial license key or view 30-day free trial status")

        self.check_updates = QAction("Check for Updates...", p)
        self.check_updates.setToolTip("Check for new LaserForge releases and updates")

        self.user_guide = QAction("📖 User Guide & FAQ Reference...", p)
        self.user_guide.setShortcut("F1")
        self.user_guide.setToolTip("Open the comprehensive LaserForge User Guide, CAM parameter manual, and FAQ directory (F1)")

        self.interactive_tutorial = QAction("🎓 Interactive Tutorial & Tour...", p)
        self.interactive_tutorial.setShortcut("F2")
        self.interactive_tutorial.setToolTip("Start the step-by-step interactive tutorial and guided workspace tour (F2)")

        self.send_feedback = QAction("💬 Message Creator / Report Issue...", p)
        self.send_feedback.setShortcut("Shift+F1")
        self.send_feedback.setToolTip("Send feedback, suggestions, or submit a bug report with diagnostics directly to the developer (Shift+F1)")

        return self
