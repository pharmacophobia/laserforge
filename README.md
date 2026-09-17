# LaserForge ⚡

**A High-Performance LightBurn Alternative for Linux and GRBL Laser Engravers**

LaserForge is a full-featured desktop laser engraving and cutting suite built natively for Linux. Designed with a familiar LightBurn-style workflow, it combines interactive 2D CAD design, multi-layer CAM processing, image dithering engines, and real-time USB machine control.

---

## Key Features

- **Interactive 2D CAD Canvas**:
  - Millimeter top and left coordinate rulers with live cursor crosshairs.
  - Configurable workbed grid (1 mm minor, 10 mm medium, 50 mm major) and machine origin marker.
  - Vector creation tools: Selection, Rectangle, Circle/Ellipse, Line, and Text.
  - Real-time transform handles, bounding box snapping, and rotation.
  - Multi-shape alignment tools (Left, Right, Top, Bottom, Centers, and Bed Center).
  - Multi-level **Undo / Redo** (`Ctrl+Z`, `Ctrl+Y`) with snapshot state history across transforms and edits.
- **Vector Booleans CSG Operations (Weld, Subtract, Intersect)**:
  - **Weld / Union** (`Ctrl+Shift+U`): Merges overlapping vector geometries and text into a continuous outer perimeter.
  - **Subtract / Difference** (`Ctrl+Shift+D`): Subtracts top overlapping shapes from the base shape (creating cutouts, mortises, and stencil holes).
  - **Intersect** (`Ctrl+Shift+X`): Retains only the overlapping intersections between shapes.
  - Preserves layer attributes, path direction, and automatic inner-first cutout detection.
- **High-Speed Raster Acceleration CAM & Rapid Blank-Space Skipping**:
  - **Physics-Based Overscan ($d = \frac{v^2}{2a}$)**: Dynamically calculates required acceleration lead-in and lead-out travel based on cut feedrate and machine $X$-axis acceleration, eliminating edge turnaround burns and deceleration scorch marks.
  - **Whitespace Rapid Skipping**: Automatically detects blank-space gaps ($\ge 8$ mm default) between shapes along scanlines and executes high-speed $G0$ non-burning rapids instead of slow $G1$ traversals, slashing sparse multi-part raster times.
  - Automatic clamping to machine bed boundaries $[0, \text{bed\_width}]$ to prevent soft/hard limit alarm trips.
- **Two-Point Corner Alignment & Precision Motor Controller Studio**:
  - **Left & Right Corner Alignment ("Print & Cut")**: Captures or sets physical Left Corner ($P_1$) and Right Corner ($P_2$) of crooked or angled stock. Computes exact rotation angle $\theta$, physical distance, delta, and optional proportional auto-scaling.
  - **Precision Motor Controller**: Built-in 8-direction jog pad with multi-rate step increments (0.01 mm ultra-fine, 0.05, 0.1, 0.5, 1, 5, 10, 50 mm, or custom step distance), adjustable feedrate, and keyboard arrow key navigation (Shift = 5x coarse, Ctrl = 0.1x micro-step).
  - **Automated Spot Dispatch**: Direct one-click motor positioning to drive the laser head directly to Left Corner, Right Corner, Midpoint, or design corners, plus direct numerical `(X, Y)` dispatch.
  - **Interactive Real-Time Visual Diagram**: Live graphical canvas showing machine bed, design envelope, Left/Right target markers, measured dimension vector, aligned preview envelope, and live laser head crosshair reticle.
  - **Physical Edge Tracing & Work Zero**: Traces along the physical workpiece edge with low-power visible guide beam (`M3 G1 S5`) and sets machine work coordinate zero ($G10 L20 P1$) at Left Corner with full multi-level Undo (`Ctrl+Z`).
- **Overhead USB Camera Vision & Bed Alignment Overlay**:
  - **4-Step Calibration Wizard** (`Ctrl+Shift+K`): OpenCV checkerboard lens undistortion ($K, D$) and 4-point laser-burned fiducial homography ($H$).
  - **Live Rectified Bed Overlay** (`Ctrl+Shift+B`): Projects an orthophoto background image of the physical workbed directly onto the 2D CAD canvas at $1:1$ millimeter scale for rapid visual stock alignment.
  - Adjustable overlay opacity slider, toggle switch, and built-in simulator camera for headless systems.
- **Decoupled Standalone AI Companion Studio**:
  - Independent desktop application launcher (`laserforge-ai.desktop` / `bin/laserforge-ai`).
  - Completely decouples PyTorch and CUDA dependencies from core LaserForge, keeping core startup instant ($<0.2$ s).
  - Generates 8GB VRAM-optimized SDXL Turbo laser art and transfers directly into LaserForge via IPC mailbox.
- **LightBurn-Style Cuts / Layers**:
  - Color-coded layers (C00 to C11 + T1 Tool Layer).
  - Independent per-layer cut modes: `Line` (vector cut/score), `Fill` (raster engraving), `Fill + Line` (combined fill with crisp perimeter outline), and `Image` (photo engraving).
  - Configurable speeds (mm/min), min/max laser powers (%), pass counts, Z-step per pass, line intervals, and air assist (`M8`/`M9`).
- **Advanced Raster & Photo Dithering**:
  - Floyd-Steinberg error diffusion for photo engraving on wood, slate, and acrylic.
  - Atkinson dithering for high-contrast, clean-dot halftone aesthetics.
  - Grayscale 8-bit dynamic laser power modulation (GRBL `$32=1` `M4` spindle speed mode).
  - Contrast, brightness, invert, and threshold controls.
- **CAD Exchange & Industry Vector Formats**:
  - **AutoCAD DXF Import & Export (`.dxf`)**: High-fidelity bidirectional exchange using `ezdxf` (supporting AutoCAD R12 and R2000+ versions, Polylines, Lines, Circles, Arcs, LWPolylines, and Splines with layer and color preservation).
  - **Full Canvas SVG Export (`.svg`)**: Exports the entire active project canvas to standard scalable vector graphics with millimeter precision, per-layer grouping, styling, and transform hierarchies.
  - **Advanced SVG `<defs>` and `<use>` Support**: Full parsing and dereferencing of re-usable symbols, definitions, and linked shapes during vector import.
- **Directional Vector Hatching Studio**:
  - Converts any closed vector polygon, text outline, or compound shape into dense, laser-optimized vector hatch toolpaths.
  - Configurable hatch angle ($0^\circ$ to $360^\circ$), line spacing/interval (down to $0.05$ mm), boundary offset margin, and optional cross-hatching ($90^\circ$ dual pass).
  - Preserves underlying shape geometry while generating dedicated fill toolpaths on selectable laser layers.
- **Contour Offset Image Cutout Generator**:
  - Automated silhouette and alpha boundary extraction for imported bitmap artwork and laser engravings.
  - Generates smooth outer cutting perimeters with dial-in millimeter offset margin (e.g. $+2.5$ mm badge boundary) and curve smoothing.
  - Supports hole inclusion/suppression and continuous closed toolpath generation for sticker and wooden cutout manufacturing.
- **Kerf Compensation & Pierce Lead-In / Lead-Out Controls**:
  - **Auto-Directional Kerf Offsetting**: Automatically differentiates outer perimeters from internal cutouts and holes, applying positive $+k/2$ or negative $-k/2$ toolpath dilation to achieve exact press-fit tolerances on mortise and tenon joints.
  - **Pierce Lead-Ins & Lead-Outs**: Eliminates start-point burn marks and pierce craters with configurable lead-in vectors (Linear, Arc, and Perpendicular) originating safely in scrap waste.
  - **Continuous Overcut Margin**: Extends cutting toolpaths past the 360° closing vertex before laser extinction (`M5`), guaranteeing parts drop out cleanly without manual trimming.
- **2D Nesting Optimizer Studio (`Ctrl+Shift+N`)**:
  - Automated 2D bin packing engine maximizing sheet material utilization and slashing scrap waste.
  - Evaluates discrete rotational orientations ($0^\circ$, $90^\circ$, or $45^\circ$ increments).
  - **Cavity & Hole Nesting**: Automatically identifies internal cutout cavities in larger parts and nests smaller components inside them.
  - Live interactive preview showing placed geometries, unplaced parts, compute times, and total packing density ($\%$).
- **Rotary Axis Studio for Rollers & Chucks (`Ctrl+Shift+R`)**:
  - Dedicated cylindrical engraving studio with support for both drive roller wheels and direct-drive 3-jaw chucks.
  - **Dual-Mode Calibration**: Non-destructive software G-code coordinate scaling (safe, leaves machine untouched) or direct GRBL `$101` steps/mm EEPROM override.
  - Automatic diameter and circumference calculator ($C = \pi D$) with live 3D cylinder visualizer.
  - **360° Calibration Test Jog**: Dispatches an exact 1-turn rotation move and returns to verify zero motor slip.
- **Holding Tabs & Bridges (Micro-Tabs)**:
  - Automatically leaves small structural uncut bridges ($0.5$–$2.0$ mm) along closed cutting contours to prevent small cut parts from dropping through honeycomb slats or tipping into the laser nozzle.
  - Slices contours into precision sub-paths with either complete laser cutouts (`G0` rapid across bridge) or configurable skin bridge laser power (`> 0%` micro-tabs for easy clean breakout).
- **Parametric Box & Finger-Joint Enclosure Studio (`Ctrl+Shift+J`)**:
  - Interactive CAD studio generating 2D flat interlocking panels for 6-sided enclosed boxes, 5-sided open-top bins, and sliding-lid cases with finger joints.
  - Fully adjustable material thickness ($1.0$–$25.0$ mm), finger joint pitch, and laser kerf compensation for snug friction press-fits without glue.
  - Real-time 2D canvas preview with sheet footprint telemetry and automated panel layout with text labels.
- **Single-Line Stroke (Hershey Vector) Fonts (`Ctrl+Shift+F`)**:
  - True centerline single-pass vector stroke fonts for rapid laser engraving of serial numbers, scales, dials, and small text.
  - Eliminates dual-pass outline perimeter cutting and melts, cutting marking runtimes by up to 60%.
  - Full ASCII glyph coverage with adjustable cap height, character spacing, and line spacing.
- **2D Vector Boolean CSG Operations**:
  - Native **Weld / Union** (`Ctrl+Shift+U`), **Subtract / Difference** (`Ctrl+Shift+D`), **Intersect** (`Ctrl+Shift+X`), and **Exclusive OR (XOR)** directly on the canvas powered by Shapely.
  - Seamlessly handles multi-polygon islands and interior cavities with full undo/redo integration.
- **Cross-Platform Standalone Packaging & Distribution**:
  - **Debian Package (`.deb`)**: Native installable package (`dist/laserforge_1.2.0_amd64.deb`) with start menu icons, dialout permissions, and `.laserproj` MIME types.
  - **Universal Linux AppImage**: Self-contained portable executable running seamlessly across Ubuntu, Debian, Fedora, Arch, and Mint.
  - **Windows Portable Executable**: Standalone build automation (`packaging/build_windows.bat` & `packaging/laserforge_windows.spec`) producing `LaserForge.exe`.
  - **Local System Installer**: Simple one-click desktop installer (`install.sh` and `uninstall.sh`).
- **Production Job Cost & Time Estimator**:
  - Physics-based job duration estimation modeling cut lengths, rapid travels, and machine acceleration limits.
  - Detailed financial breakdown calculating laser tube/diode wear ($\$/\text{hr}$), electricity power consumption ($\text{kW}\cdot\text{h}$ rates), and sheet stock material costs.
  - Instant production quoting and profitability analysis before firing the laser.
- **CAM Toolpath Optimization**:
  - **Inner-First Nesting Sort**: Automatically cuts interior holes, dropouts, and slots before exterior perimeters to prevent loose material shifting.
  - **Traveling Salesperson (TSP) Optimizer**: Minimizes non-cutting rapid travel movements using nearest-neighbor Euclidean distance.
  - Accurate run-time ETA estimation based on cut length, rapid travel, and acceleration limits.
- **Image to SVG Vector Tracer (LightBurn-Style Trace Tool)**:
  - Vectorizes bitmap images (PNG, JPG, BMP, WebP) into clean vector paths and SVG files.
  - **Marching Squares Boundary Tracing**: Extracts topological outer contours and inner cutouts.
  - **Otsu Auto-Thresholding**: Automatically calculates the optimal binarization threshold.
  - **RDP Curve Smoothing**: Simplifies pixel stairstep noise into smooth vector polygons.
  - **Dust / Speckle Filter**: Rejects speckle noise smaller than configurable pixel threshold.
  - **Interactive Tracing Studio**: Real-time side-by-side / overlay preview with image fade slider, threshold adjustment, invert toggle, and layer assignment.
  - **Export to SVG**: One-click export to standalone `.svg` vector files or direct insertion onto the cutting bed.
- **Design Studio & Production Tools**:
  - **Material Library & Test Matrix Generator**: Pre-calibrated material profiles for 3W blue diode lasers, custom material persistence, and automatic parametric Power vs. Speed test grid generator.
  - **Parametric Barcode & QR Code Designer**: Vector and raster barcode generator supporting Code 128, Code 39, EAN-13, UPC-A, and 2D QR codes with direct laser hatching.
  - **Curved Text on Path & Typography**: Wraps text along arcs and custom curves with adjustable radius and letter spacing.
  - **Parametric Templates & Shape Generator**: Parametric box joint maker, living hinges, test cards, stars, gears, and polygons.
  - **Pre-Flight G-Code Safety Validator**: Inspects generated G-code programs to prevent machine alarms, out-of-bounds bed crashes, and unconstrained laser dwell burns.
- **Interactive Toolpath Simulation Preview**:
  - Real-time 2D animated simulation canvas showing rapid moves (red dotted) and laser burn moves (layer colored).
  - Animated laser head scrubber slider with Play / Pause / Reset and speed multipliers (1x to 50x).
  - Raw G-code viewer with one-click export (`.nc` / `.gcode`) and clipboard copy.
- **Real-Time Machine Controller**:
  - Background threaded USB serial communications with GRBL 1.1+.
  - 8-directional jog pad with configurable step sizes (0.1, 1, 10, 50, 100 mm) and speed control.
  - Status telemetry decoding (`<Idle>`, `<Run>`, `<Hold>`, `<Alarm>`, MPos/WPos).
  - Homing (`$H`), Alarm Unlock (`$X`), Soft Reset (`Ctrl+X`), Work Zero (`G10 L20 P1`), and Go to Origin.
  - **Framing Guide**: Safely traces the job bounding box with a 0.5% low-power visible guide beam before burning.
  - Real-time serial terminal console with colored TX/RX/error logs and command prompt.

---

## Machine Connection & Permissions

LaserForge communicates directly with GRBL-based diode, CO2, and fiber laser engravers via USB serial (e.g. `/dev/ttyUSB0` or `/dev/ttyACM0`).

To grant standard Linux user permissions to access the serial port without `sudo`:
```bash
sudo usermod -aG dialout $USER
```
*(Log out and log back in for changes to take effect).*

---

## Quickstart

### 1. Launch via Desktop Menu
LaserForge is registered in your desktop application menu under **Graphics** and **Engineering**. You can also launch it directly from the desktop shortcut:
- Open your Application Menu and search for **LaserForge**.

### 2. Launch via Terminal
```bash
/home/k/LaserForge/run.sh
```
Or with Python:
```bash
cd /home/k/LaserForge
python3 -m laserforge.main
```

---

## Included Sample Projects

- **Welcome Keychain Badge**: [`examples/welcome_laserforge.laserproj`](file:///home/k/LaserForge/examples/welcome_laserforge.laserproj)
  - Demonstrates multi-layer operation: C00 outer cut, C02 inner hole cut, and C01 logo engrave fill.
- **Calibration Grid**: [`examples/test_cut_grid.svg`](file:///home/k/LaserForge/examples/test_cut_grid.svg)
  - Calibration target with square dimensions, diagonal lines, and corner fiducials.

---

## Keyboard Shortcuts

| Action | Shortcut |
|---|---|
| **New Project** | `Ctrl + N` |
| **Open Project** | `Ctrl + O` |
| **Save Project** | `Ctrl + S` |
| **Import SVG Vector** | `Ctrl + I` |
| **Import AutoCAD DXF** | `Ctrl + Alt + D` |
| **Export G-Code** | `Ctrl + E` |
| **Export Canvas to SVG** | `Ctrl + Shift + E` |
| **Auto Cutout to SVG** | `Ctrl + Shift + C` |
| **Directional Hatching** | `Ctrl + Shift + H` |
| **2D Nesting Optimizer** | `Ctrl + Shift + N` |
| **Rotary Axis Studio** | `Ctrl + Shift + R` |
| **Box & Enclosure Studio** | `Ctrl + Shift + J` |
| **Single-Line Stroke Text** | `Ctrl + Shift + F` |
| **Job Cost & Time Estimator** | `Ctrl + Shift + M` |
| **Select Tool** | `S` |
| **Rectangle Tool** | `R` |
| **Circle Tool** | `C` |
| **Line Tool** | `L` |
| **Text Tool** | `T` |
| **Undo** | `Ctrl + Z` |
| **Redo** | `Ctrl + Y` |
| **Weld / Union** | `Ctrl + Shift + U` |
| **Subtract / Difference** | `Ctrl + Shift + D` |
| **Intersect** | `Ctrl + Shift + X` |
| **Camera Calibration Wizard** | `Ctrl + Shift + K` |
| **Update Camera Bed Overlay** | `Ctrl + Shift + B` |
| **Center on Laser Bed** | `Ctrl + Alt + C` |
| **Burn Alignment Perimeter** | `Ctrl + Alt + B` |
| **QR & Barcode Studio** | `Ctrl + Alt + Q` |
| **Parametric Shapes Generator** | `Ctrl + Alt + G` |
| **Select All** | `Ctrl + A` |
| **Duplicate Selected** | `Ctrl + D` |
| **Delete Selected** | `Delete` |
| **Zoom to Fit Bed** | `Ctrl + 0` |
| **Toolpath Preview** | `Alt + P` |
| **Frame Bounding Box** | `Ctrl + F` |
| **Start Laser Job** | `Ctrl + R` |
| **Emergency Abort** | `Escape` |
| **Machine Settings** | `Ctrl + ,` |

---

## Running Unit & Integration Tests

```bash
cd /home/k/LaserForge
python3 -m unittest discover tests
```
All automated test suites (186+ unit tests) verify:
- Geometric entity definitions and boundary math
- Multi-layer parameter configuration
- Floyd-Steinberg and Atkinson dithering
- G-code generation with Dynamic Laser Power (M4)
- Framing bounding box generation
- Project serialization (`.laserproj`) and SVG vector import
- AutoCAD DXF import/export fidelity (`ezdxf` R12/R2000) and full-canvas SVG export
- Directional vector hatching and boundary offset algorithms
- Bitmap contour cutout generation with dilation margins
- Job duration, machine acceleration limits, and financial costing calculations
- Inner-first contour nesting and TSP rapid travel optimization
- Constructive Solid Geometry (CSG) vector booleans (Weld, Subtract, Intersect) and Undo/Redo stacks
- High-speed raster acceleration overscan calculations and whitespace rapid skipping
- OpenCV camera lens calibration, perspective homography rectification, and canvas orthophoto overlays
- GRBL G-code program pre-flight safety and limits validation
- GPU / CPU accelerated raster calculations and SDXL Turbo procedural fallbacks
