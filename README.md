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
- **LightBurn-Style Cuts / Layers**:
  - Color-coded layers (C00 to C11 + T1 Tool Layer).
  - Independent per-layer cut modes: `Line` (vector cut/score), `Fill` (raster engraving), `Fill + Line` (combined fill with crisp perimeter outline), and `Image` (photo engraving).
  - Configurable speeds (mm/min), min/max laser powers (%), pass counts, Z-step per pass, line intervals, and air assist (`M8`/`M9`).
- **Advanced Raster & Photo Dithering**:
  - Floyd-Steinberg error diffusion for photo engraving on wood, slate, and acrylic.
  - Atkinson dithering for high-contrast, clean-dot halftone aesthetics.
  - Grayscale 8-bit dynamic laser power modulation (GRBL `$32=1` `M4` spindle speed mode).
  - Contrast, brightness, invert, and threshold controls.
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
| **Export G-Code** | `Ctrl + E` |
| **Select Tool** | `S` |
| **Rectangle Tool** | `R` |
| **Circle Tool** | `C` |
| **Line Tool** | `L` |
| **Text Tool** | `T` |
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
All 10 test suites verify:
- Geometric entity definitions and boundary math
- Multi-layer parameter configuration
- Floyd-Steinberg and Atkinson dithering
- G-code generation and dynamic M4 spindle modulation
- Framing bounding box generation
- Project serialization (`.laserproj`) and SVG vector import
- Inner-first contour nesting and TSP rapid travel optimization
