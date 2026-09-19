# Changelog

All notable changes to LaserForge are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbering follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- **Automated Workbed & Laser Vision Calibration Engine** (`AutoCalibrationEngine`, `FiducialDetector`, `AutoCalibrationDialog`):
  Autonomous alignment between physical laser coordinates and overhead camera vision. Supports multi-mode optical
  fiducial detection (ArUco 4x4 dictionaries, concentric circular bullseyes, laser burn marks, crosshairs, and
  synthetic simulator markers) with sub-pixel corner and centroid moments refinement. Computes 3x3 perspective
  homography matrices with RANSAC outlier filtering, bi-directional coordinate transformation (`camera_to_laser`,
  `laser_to_camera`), parametric G-code calibration target burner with automated laser head parking, gantry
  non-orthogonality (skew) diagnostics, and 1-click studio UI integrated into `MainWindow` (`Ctrl+Alt+A`),
  `CameraCalibrationWizardDialog` (Step 3 auto-detect), and `WorkbedSetupDialog`.
- **Interactive Tutorial & Onboarding Studio** (`InteractiveTutorialDialog`, `WelcomeOnboardingDialog`):
  6-step guided interactive walkthrough with live in-app action triggers covering workspace orientation,
  vector drawing and transforms, cut/raster layer parameter presets, animated 2D toolpath simulation,
  hardware-free `VIRTUAL_GRBL` connection with reticle tracking, and pre-flight framing checks.
- **Install & First-Launch Experience**: Added `--tutorial` / `-t` command-line launch flag, interactive
  prompt at the conclusion of `install.sh`, first-run welcome dialog, and persistent `Help -> 🎓 Interactive Tutorial & Tour...`
  menu entry (`F2`).
- **LightBurn Project Exporter** (`LBRN2Exporter`): Full `.lbrn2` project file export supporting rectangle,
  circle, line, path, and text geometry, complete with layer cut settings (Line, Fill, Fill+Line). Wired
  into `File -> Export -> Export LightBurn Project (.lbrn2)...`.
- **User Guide & FAQ Studio** (`UserGuideDialog`, `docs/user_guide.md`):
  Comprehensive searchable documentation and troubleshooting reference manual accessible via
  `Help -> 📖 User Guide & FAQ Reference...` (`F1`). Covers CAD workflow, layer CAM settings,
  raster overscan math, GRBL kinematics, safety protocols, common failure diagnoses, and keyboard cheat sheets.
- **Multi-Camera Workbed Panoramic Stitching Studio** (`MultiCameraEngine`, `MultiCameraConfig`, `CameraSlotConfig`, `MultiCameraSetupDialog`):
  Array support for dual and multi-camera setups covering wide-format laser beds (>900 mm). Independent intrinsic
  lens undistortion and perspective homography calibration per camera slot, sub-pixel perspective warping into unified
  bed coordinate space, and advanced photometric seam blending strategies (`LinearFeather`, `DistanceTransform` Voronoi
  blending, `MaxPriority`, and `HardSeam`). Includes an interactive studio dialog (`Ctrl+Alt+M`), live seam contour
  demarcation overlays, synthetic panoramic generator, and 1-click push to main canvas background overlay.
- **Live Laser Reticle Tracking in Vision Engine** (`CameraEngine.laser_to_camera`, `camera_to_laser`, `draw_laser_reticle_on_frame`):
  Bi-directional homography projection mapping physical laser head coordinates onto overhead camera streams with
  sub-pixel accuracy. Renders high-visibility animated target rings, crosshairs with center aperture gaps, and floating
  telemetry HUD badges showing real-time $(X, Y)$ machine coordinates and controller execution state (`Run`, `Hold`,
  `Jog`, `Alarm`, `Idle`).
- **Community & Cloud Materials Preset Exchange & Multi-Laser Library** (`CommunityPresetCatalog`, `MaterialPresetPack`, `CommunityPackBrowserDialog`):
  Multi-technology curated preset catalogs supporting High-Power Diodes (10W-40W), CO2 Laser Tubes (40W-100W), and
  Fiber/MOPA Metal Marking (20W-50W). Portable `.lfmat` / `.lfpak` preset pack packaging with 1-click import into
  active local libraries, collision detection and overwrite controls, search/filtering by laser technology and wattage,
  and pack export studio.
- **UI Modularization & Action Architecture**: Decoupled `MainWindow` into `ActionRegistry`, `MenuBuilder`,
  and `ToolbarBuilder` for clean maintainability.

### Fixed
- **Workbed Coordinate & Axis Inversion across Reticle, Canvas, and Properties**:
  - **Laser Head Reticle Positioning**: Resolved Y-axis inversion in [`LaserCanvasScene.update_laser_position`](file:///home/k/LaserForge/laserforge/ui/canvas_scene.py) where GRBL machine coordinates $(0, 0)$ previously mapped to the Qt scene top-left rather than the configured origin beacon. Coordinates are now mapped to scene space based on `origin_corner` while preserving machine coordinates on the floating HUD badge. Jogging in $+Y$ now moves the reticle in the correct visual direction away from the origin beacon.
  - **Shape Properties Coordinate Synchronicity**: Fixed [`ShapePropertiesPanel`](file:///home/k/LaserForge/laserforge/ui/shape_properties.py) displaying and modifying raw Qt scene coordinates. X and Y spin boxes now display and update position relative to the active workbed origin, matching rulers and status bar coordinates.
  - **Workbed Setup Studio Preview Widget**: Updated [`WorkbedPreviewWidget`](file:///home/k/LaserForge/laserforge/ui/workbed_setup_dialog.py) to accurately place origin beacons, calibration points, and live laser head crosshairs across all 4 origin corners (`Bottom-Left`, `Top-Left`, `Bottom-Right`, `Top-Right`).
  - **Workbed Corner Jump Navigation**: Updated [`_jump_to_corner`](file:///home/k/LaserForge/laserforge/ui/workbed_setup_dialog.py) to calculate physical corner targets in machine space corresponding to the selected origin corner.

---

## [2.5.0] — 2026-09-18

### Added

#### Phase 5 & 6 — Advanced Studio Features
- **Auto-Focus Z-Probe Cycle Engine** (`ZProbeEngine`, `ZProbeStudioDialog`): Full G38.2/G38.3
  probing cycle with configurable feed rate, max travel, plate thickness, and focal offset.
  Parses GRBL `[PRB:x,y,z:ok]` responses to set work coordinate zero after probing.
  Dedicated studio dialog with retract distance spin controls.
- **Interactive Caliper & Dimension Measuring Tool** (`TOOL_MEASURE`): Canvas-level measurement
  tool that places two anchor points and displays live Euclidean distance, ΔX, ΔY, and angle
  in a graphical overlay with dimension lines and arrowheads (5-item child group).
- **Ultra-Wide Fisheye Lens Calibration** (`FisheyeRectifier`, `FisheyeCalibrationData`):
  OpenCV fisheye model (k1–k4) lens undistortion distinct from the standard pinhole camera
  calibration workflow. Supports cameras with FOV up to 220°.
- **3D Curved Surface Toolpath Projection** (`SurfaceParameters`, `Surface3DProjector`):
  Generates non-planar G-code with Z-axis elevation offsets for engraving on cylinders and
  spheres. Contour subdivision (`subdivide_contour`) with configurable max step ensures
  smooth arc approximation. Outputs `M4 Sxxx` / `M5` sequences with per-segment Z coordinates.
- **Workshop Audio Chime Engine** (`AudioChimeEngine`): Synthesizes WAV notification tones
  for `job_complete`, `probe_trigger`, and error events. Files are cached to disk on first
  generation for sub-millisecond playback latency.
- **Surface Wrap Studio** (`SurfaceWrapStudioDialog`): GUI for configuring and previewing
  non-planar toolpaths. Drives `Surface3DProjector` with live 2D canvas preview.

#### Phase 4 — Advanced Hardware & Specialty Machines
- **Ruida DSP Controller & `.rd` Binary Pipeline** (`RuidaCompiler`, `RuidaUDPClient`):
  Compiles vector paths to native Ruida DSP binary scancode format (`.rd`, `.ud5`) for
  industrial CO₂ laser cutters. Broadcasts jobs over Ethernet UDP to port 50200.
  Remote job upload, status diagnostics ping, and one-click burn execution.
- **Mobile Remote Jogger & Web Pendant** (`WebPendantServer`): Embedded HTTP/JSON server
  on port 8088 hosting a touch-optimized mobile web app. Provides 8-direction jog pad,
  live coordinate telemetry, frame job, laser guide beam toggle, and emergency stop.
  Auto-generates QR code for quick workshop network access.
- **Galvo & Fiber Marking Laser Engine** (`GalvoEngine`, `GalvoDelays`, `WobbleConfig`):
  Precision mirror inertia delay compensation (laser ON/OFF delay, mark settle, jump rapid,
  polygon corner dwell — all configurable in µs). Transverse beam wobble generator with
  circular, figure-8 (lemniscate), and sinusoidal oscillation modes.
- **3D Relief Engraving & Z-Step Down** (`ReliefEngine`, `ZStepConfig`, `ReliefCarveConfig`):
  Multi-pass depth calculations (`G0 Z-{pass*step}`) maintaining focal spot through thick
  material. 3D grayscale heightmap slicer converting 8-bit/16-bit depth maps to discrete
  Z carving slices with bidirectional scanline optimization.
- **Material Test Matrix Generator** (`MaterialTestGenerator`, `MaterialTestGridConfig`):
  Parametric 2D grid varying Speed (rows) vs Power (columns). Dual cut modes (perimeter /
  internal hatching). Burns single-line Hershey numeric labels for each row/column cell.
  Optional perimeter drop-out cutout frame.

#### Phase 3 — Commercial & Specialty Features
- **Commercial License Engine** (`LicenseEngine`, `LicenseStatus`): Cryptographic HMAC-SHA256
  offline license key verification (`LF-XXXX-XXXX-XXXX-XXXX`). Hardware fingerprinting via
  CPU architecture and network node hashing (no cloud phone-home). 30-day free trial with
  anti-tamper clock rollback detection. License stored at `~/.laserforge/license.json`.
- **Living Hinges & Curved Box Lattice Flex Studio** (`LivingHingeEngine`, `LivingHingeConfig`):
  Parametric flexible lattice hinge generator for rigid sheet materials. Supports straight
  slit, sinuous wavy (torsional), and diamond honeycomb flex geometries. Arc-length bend
  calculator (`L = R·θ`) with dial-in slit lengths, bridge gaps, and column pitch.

#### Phase 2 — Precision Workflow
- **Holding Tabs & Micro-Bridges** (`TabEngine`): Slices closed contours into sub-paths
  leaving small uncut bridges (0.5–2.0 mm) to prevent cut parts from dropping. Configurable
  tab count, width, and laser power across the bridge. Supports both G0 rapid (full tab) and
  partial power skin bridges.
- **Print & Cut 2-Point Registration** (`LaserAlignmentDialog`): Captures Left Corner (P₁)
  and Right Corner (P₂) physical positions. Computes rotation angle θ, physical distance,
  delta, and optional proportional auto-scaling for crooked/angled stock alignment.
- **LightBurn Project Importer** (`LightBurnImporter`): Full `.lbrn2` (JSON) and `.lbrn`
  (XML) format parsing preserving layer color, cut settings, and entity geometry.
- **Smart Color-to-Layer Mapping**: SVG import resolves hex `#RRGGBB`, `rgb(r,g,b)`, and
  named CSS colors to the nearest LaserForge C00–C11 layer by Euclidean color distance.
- **Dynamic Corner Deceleration Power Ramping**: `GCodeGenerator` proactively ramps laser
  power down around sharp decelerating corners above a configurable angle threshold to
  prevent corner charring.
- **OpenCV Fisheye Camera Lens Undistortion**: Full 4-coefficient fisheye model in the
  camera calibration wizard, separate from standard barrel distortion.

#### Phase 1 — Professional Completeness
- **DXF Import & Export** (`DXFImporter`, `DXFExporter`): Bidirectional AutoCAD DXF exchange
  via `ezdxf` supporting R12 and R2000+ versions. Preserves Polylines, Lines, Circles, Arcs,
  LWPolylines, Splines, layer, and color data.
- **Full Canvas SVG Export** (`SVGExporter`): Exports entire canvas to standards-compliant
  SVG with mm precision, per-layer `<g>` grouping, and transform hierarchies.
- **SVG `<defs>` and `<use>` Support**: `SVGImporter` fully dereferences reusable symbol
  definitions. Each `<use>` element instantiates an independent canvas entity; raw `<defs>`
  are suppressed from direct placement.
- **Job Cost & Time Estimator** (`JobEstimatorDialog`): Physics-based duration estimation
  modeling cut lengths, rapid travels, and acceleration limits. Financial breakdown for
  tube/diode wear ($/hr), electricity (kWh rates), and sheet material costs.
- **Serial Streaming Guards & Z-Probe**: `SerialController` blocks `go_to_pos()`,
  `go_to_zero()`, and all motor moves while `is_streaming` is active. `probe_z()` dispatches
  G38.2 probe cycle, G10 L20 P1 work zero, G0 retract, and G90 absolute mode sequence.
- **Snap-to-Grid & Alignment Guides** (`LaserCanvasScene`): Configurable grid snap with
  mm precision. Named horizontal/vertical guides with toggle visibility and bulk clear.

### Changed
- `MachineSettings` expanded with full rotary axis parameters (roller diameter, object
  diameter, steps/rev, axis selection, software vs hardware mode), Z-probe settings
  (command, feed, travel, retract, plate thickness, focal offset, auto-zero), audio chime
  controls, and fisheye camera calibration coefficients (k1–k4).
- `LayerCutSettings` extended with corner power ramping fields (`corner_power_ramping`,
  `corner_ramp_angle_deg`, `corner_min_power_pct`).

---

## [2.0.0] — 2025-12-01

### Added

#### Core CAD/CAM Engine
- **Multi-layer cut system** (`LayerManager`, `LayerCutSettings`): 13 LightBurn-compatible
  color-coded layers (C00–C11 + T1 Tool Layer). Independent per-layer mode (`Line`, `Fill`,
  `Fill + Line`, `Image`), speed, min/max power, pass count, Z-step, line interval, fill
  angle, and air assist (`M8`/`M9`).
- **G-code Generator** (`GCodeGenerator`): Full GRBL 1.1+ G-code output with M4 dynamic
  laser power, M3 constant power, and M106 modes. Inner-first contour nesting sort,
  nearest-neighbor TSP rapid travel optimizer, and G2/G3 native arc emission.
- **Raster Fill Engine** (`raster_processor`): Bidirectional scanline raster fill for `Fill`
  and `Fill + Line` layers. Floyd-Steinberg and Atkinson dithering. 8-bit grayscale dynamic
  laser power modulation for `Image` layer photo engraving.
- **GRBL Serial Controller** (`SerialController`, `QThread`): Background-threaded USB serial
  communications with GRBL 1.1+. High-speed buffered G-code streaming. Real-time status
  telemetry decoding (`<Idle>`, `<Run>`, `<Hold>`, `<Alarm>`, MPos/WPos). Full GRBL error
  and alarm code lookup tables. Homing (`$H`), Alarm Unlock (`$X`), Soft Reset, work zero.
- **Toolpath Simulation Preview** (`PreviewDialog`): Real-time 2D animated simulation canvas
  with animated laser head scrubber, Play/Pause/Reset, and 1×–50× speed multipliers. Rapid
  moves shown in red dotted lines; cut moves in layer color.
- **G-code Validator** (`GCodeValidator`, `ValidationReport`): Pre-flight safety inspection
  detecting out-of-bounds bed crashes, unconstrained laser dwell, and missing feed rates.
- **Project I/O** (`ProjectIO`): JSON-based `.laserproj` format serializing all entity types
  (Rect, Circle, Line, Path, Text, Image), layer configurations, and machine settings.
- **SVG Importer** (`SVGImporter`): Parses SVG paths, rects, circles, lines, text, and use/
  defs. Color-to-layer assignment. Coordinate transform normalization.
- **Kerf Compensation Engine** (`kerf_engine`): Auto-directional kerf offsetting differentiating
  outer perimeters (+kerf/2) from internal cutouts (−kerf/2). Pierce lead-ins (Linear, Arc,
  Perpendicular) and continuous overcut margin for clean part dropout.
- **Directional Hatching** (`directional_hatch`): Converts closed vectors and text outlines
  into dense vector hatch toolpaths. Configurable hatch angle (0°–360°), line spacing,
  boundary offset margin, and cross-hatching (dual 90° pass).
- **2D Nesting Optimizer** (`nesting_engine`): Bin-packing engine evaluating 0°, 90°, and
  45° rotational orientations. Cavity & hole nesting (smaller parts inside internal cutouts
  of larger parts). Live preview with placed/unplaced parts and packing density %.
- **Vector Boolean CSG** (`geometry_boolean`, `boolean_engine`): Native Weld/Union
  (`Ctrl+Shift+U`), Subtract/Difference (`Ctrl+Shift+D`), Intersect (`Ctrl+Shift+X`), and
  XOR via Shapely. Handles multi-polygon islands and interior cavities with full undo/redo.
- **GPU Accelerator** (`gpu_accelerator`): CUDA/OpenCL hardware acceleration for raster
  filtering, dithering, and contour tracing. CPU fallback for systems without compatible GPU.
- **Auto-Connect** (`auto_connect`): USB hotplug watcher (`USBHotplugWatcher`) and ranked
  port detector (`PortDetector`, `RankedPort`) for automatic laser connection on startup.

#### Design Tools
- **Contour Offset Image Cutout** (`image_cutout`): Automated alpha boundary extraction
  for bitmap artwork generating smooth cutting perimeters with configurable mm offset margin
  and curve smoothing. Hole inclusion/suppression support.
- **Image Tracer** (`image_tracer`): Bitmap-to-vector tracer using marching squares boundary
  tracing, Otsu auto-thresholding, RDP curve smoothing, and dust/speckle filter.
- **Barcode & QR Code Generator** (`barcode_generator`): Supports Code 128, Code 39, EAN-13,
  UPC-A, and 2D QR codes. Vector and raster output with direct laser hatching.
- **Shape Generator** (`shape_generator`): Parametric stars, gears, regular polygons, and
  custom profile shapes placed directly onto the canvas.
- **Font Tools** (`font_tools`): System font enumeration and text outline path extraction.
- **Materials Database** (`materials_database`, `MaterialProfile`): Pre-calibrated material
  profiles for 3W blue diode lasers. Custom material persistence and test matrix generation.
- **Art & Component Library** (`art_library`, `ArtLibraryManager`, `ArtItem`): `.lflib`
  JSON format storing vector components with base64-encoded thumbnails and tag metadata.
  Drag-and-drop canvas insertion. Built-in Standard Hardware library (M3/M4/M5 holes,
  keyhole slots, zip-tie pass-throughs, corner fiducials).
- **Rotary Axis Engine** (`rotary_engine`): Software G-code coordinate scaling and hardware
  GRBL `$101` steps/mm override for roller and chuck rotary attachments.
- **Box & Enclosure Studio** (`box_engine`): Parametric flat-pack 6-sided boxes, open-top
  bins, and sliding-lid cases with finger joints and dovetail joints.
- **Hershey Single-Line Fonts** (`hershey_font`): True centerline single-pass vector stroke
  fonts for rapid engraving of serial numbers, scales, and small text. Full ASCII coverage.
- **Camera Engine** (`camera_engine`): OpenCV checkerboard lens undistortion (K, D matrices)
  and 4-point laser-burned fiducial homography (H) for bed overlay projection.
- **Bundle Packager** (`bundle_packager`): `.lfpak` ZIP archives bundling project artwork,
  materials library, and machine settings. SHA256 tamper-detection checksums.
- **Template Generator** (`template_generator`): Parametric template library for boxes,
  living hinges, test cards, gears, and polygon shapes.
- **Common Line Engine** (`common_line_engine`): Detects collinear/overlapping edges across
  arrays and tiled parts. Deduplicates shared edges to a single cut pass.
- **Variable Text Engine** (`variable_text_engine`): CSV/TSV batch production merge with
  placeholder substitution (`%NAME%`, `%SERIAL:04d%`, `%DATE%`, `%ROW%`).
- **Node Editor** (`node_editor`): Vertex-level CAD manipulation — select, move, insert,
  delete, smooth, and split path vertices. Trim scissor intersection detection.
- **SDXL Turbo AI Engine** (`sdxl_turbo_engine`): Decoupled standalone AI companion with
  IPC mailbox for image transfer into the canvas import queue.

### Changed
- `LaserEntity` base dataclass extended with `override_speed`, `override_power`, and `tabs`
  per-entity override fields.
- `LayerCutSettings` extended with kerf offset, kerf direction, lead-in/lead-out type and
  length, overcut length, tab settings, and pass delay fields.
- `MachineSettings` extended with overscan controls, whitespace skip, flood fill, inline
  streaming, kerf width, test pulse, full GRBL kinematics ($0–$132), job workflow positioning,
  air assist, GPU/OpenGL flags, and rotary axis parameters.

---

## [1.5.0] — 2025-06-15

### Added

#### Raster & Photo Engraving
- **Floyd-Steinberg Error Diffusion Dithering**: Full error propagation kernel for photo
  engraving on wood, slate, and acrylic producing organic dot patterns.
- **Atkinson Dithering**: High-contrast halftone aesthetics for clean-dot engraving.
- **Grayscale 8-bit Dynamic Laser Power Modulation**: GRBL `$32=1` laser mode with `M4`
  spindle speed encoding pixel brightness into `S` values (0–`$30`).
- **Image Entity & Photo Engraving Workflow** (`ImageEntity`): Import and place bitmap images
  on the canvas (PNG, JPG, BMP, WebP). Per-image controls: dither mode, invert, contrast,
  brightness, threshold, DPI, gamma, sharpen, histogram equalization, white/black clip,
  halftone cell size and angle, horizontal/vertical mirror.
- **High-Speed Raster Acceleration CAM** (`raster_processor`): Physics-based overscan using
  `d = v²/(2a)` to calculate lead-in/lead-out preventing edge burn marks.
- **Whitespace Rapid Skipping**: Detects blank-space gaps (≥ 5 mm default) between shapes
  along scanlines and executes G0 non-burning rapids instead of slow G1 traversals.
- **Precision Motor Controller Studio**: 8-direction jog pad with multi-rate step increments
  (0.01 mm ultra-fine through 50 mm coarse), adjustable feedrate, and keyboard arrow key
  navigation (Shift = 5× coarse, Ctrl = 0.1× micro-step).
- **Framing Guide**: Safely traces job bounding box with 0.5% low-power visible guide beam
  before burning (`DEFAULT_FRAMING_POWER = 0.5`, `DEFAULT_FRAMING_SPEED = 2000`).

### Changed
- `GCodeGenerator` adds `M4` (dynamic) vs `M3` (constant) laser mode selection.
- `MachineSettings` adds `min_s_value`, `laser_mode`, `use_inline_power`, `enable_arcs`,
  `laser_fire_delay_ms`, `laser_off_delay_ms`, `overscan_*`, and `white_space_skip_*` fields.

---

## [1.0.0] — 2025-01-20

### Added

#### Initial Release — Basic Vector Drawing & G-code Export

- **Interactive 2D CAD Canvas** (`LaserCanvasScene`, `LaserCanvasWidget`): Millimeter rulers
  on top and left with live cursor crosshairs. Configurable workbed grid (1 mm minor,
  10 mm medium, 50 mm major) and machine origin marker.
- **Vector Drawing Tools**: Selection (`S`), Rectangle (`R`), Circle/Ellipse (`C`), Line
  (`L`), and Text (`T`) primitive creation tools.
- **Core Entity Data Models** (`models.py`): `LaserEntity` base class with `id`, `layer_id`,
  `name`, `x`, `y`, `rotation`, `selected`, `locked`. Concrete types: `RectEntity`,
  `CircleEntity`, `LineEntity`, `PathEntity`, `TextEntity`.
- **Real-Time Transform Handles**: Bounding box drag handles, aspect-ratio-locked scaling,
  and free rotation. Multi-shape selection with Shift+click and rubber-band marquee.
- **Multi-shape Alignment Tools**: Align Left, Right, Top, Bottom, Center Horizontal, Center
  Vertical, and Center on Bed.
- **Multi-level Undo / Redo** (`Ctrl+Z` / `Ctrl+Y`): Snapshot state history across all
  transforms, property edits, and drawing operations.
- **LightBurn-style Cuts / Layers Panel** (`CutsPanel`): Color palette (C00–C11, T1 tool
  layer). Per-layer mode, speed, power (min/max), pass count, and line interval editing.
- **G-code Generator** (`GCodeGenerator`): Basic vector-to-G-code conversion. Line layer
  produces G1 cut moves; Fill layer produces raster scanline sweeps.
- **Machine Settings** (`MachineSettings`): Bed width/height, origin corner, baud rate,
  `max_s_value`, rapid speed, jog speed, framing power/speed.
- **Project Save/Load** (`ProjectIO`): JSON `.laserproj` format. Saves/restores all entity
  types, layer settings, and machine configuration.
- **Serial Connection Panel** (`LaserControlPanel`, `ConsolePanel`): Port selection and
  connect/disconnect. Real-time serial terminal with colored TX/RX/error log. Basic GRBL
  status polling.
- **G-code Export**: Export generated G-code to `.nc` / `.gcode` file or clipboard copy.
- **SVG Import** (`SVGImporter`): Basic SVG path, rect, circle, and line import. Viewbox
  and coordinate normalization.
- **Shape Properties Panel** (`ShapePropertiesPanel`): X, Y, width, height, rotation, and
  layer assignment numeric editing for selected entities.
- **Zoom & Pan**: Mouse wheel zoom, middle-button pan, `Ctrl+0` zoom-to-fit-bed.
- **Desktop Integration**: `.desktop` launcher, `run.sh` wrapper, and `install.sh` /
  `uninstall.sh` system installer.
- **Example Projects**: `welcome_laserforge.laserproj` keychain badge demonstrating
  multi-layer C00/C01/C02 workflow. `test_cut_grid.svg` calibration target.

---

[Unreleased]: https://github.com/laserforge/laserforge/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/laserforge/laserforge/compare/v2.0.0...v2.5.0
[2.0.0]: https://github.com/laserforge/laserforge/compare/v1.5.0...v2.0.0
[1.5.0]: https://github.com/laserforge/laserforge/compare/v1.0.0...v1.5.0
[1.0.0]: https://github.com/laserforge/laserforge/releases/tag/v1.0.0
