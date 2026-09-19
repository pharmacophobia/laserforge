# LaserForge User Guide & Reference Manual

Welcome to the official **LaserForge** User Guide & Reference Manual. This document provides a comprehensive operational guide for makers, fabricators, and laser operators using LaserForge on Linux.

---

## Table of Contents

1. [System Overview & Workflow](#1-system-overview--workflow)
2. [CAD Canvas & Drawing Tools](#2-cad-canvas--drawing-tools)
3. [Cuts & Layer Management](#3-cuts--layer-management)
4. [Raster & Photo Engraving](#4-raster--photo-engraving)
5. [Hardware & GRBL Controller Setup](#5-hardware--grbl-controller-setup)
6. [Specialized Design Studios](#6-specialized-design-studios)
7. [Safety & Framing Procedures](#7-safety--framing-procedures)
8. [Frequently Asked Questions (FAQ) & Troubleshooting](#8-frequently-asked-questions-faq--troubleshooting)
9. [Keyboard Shortcuts Cheat Sheet](#9-keyboard-shortcuts-cheat-sheet)

---

## 1. System Overview & Workflow

LaserForge is a high-performance, LightBurn-compatible laser CAD/CAM software suite designed specifically for Linux. It supports blue diode lasers (450nm), CO₂ lasers (10.6µm), fiber/galvo marking lasers (1064nm), and Ruida DSP industrial controllers.

### Standard Production Workflow

1. **Machine Setup**: Set bed dimensions (e.g. 400×400 mm) and origin corner in **Settings** (`Ctrl+,`).
2. **Artwork Creation / Import**: Draw vector shapes on canvas or import SVG, DXF, or LightBurn `.lbrn2` projects.
3. **Layer Assignment**: Assign design elements to color-coded layers (C00–C11) to define cutting vs. engraving.
4. **CAM Parameter Configuration**: Specify feed rate (mm/min), laser power (%), passes, and air assist.
5. **Toolpath Simulation**: Verify rapid travels (G0) and cut trajectories (G1/G2/G3) in the 2D simulator (`Alt+P`).
6. **Workpiece Setup**: Place stock on the bed, set work zero (`G10 L20 P1 X0 Y0`), and run framing (`Ctrl+F`).
7. **Job Execution**: Start laser streaming (`Ctrl+R`) with active status telemetry and dynamic overrides.

---

## 2. CAD Canvas & Drawing Tools

The central CAD canvas provides high-precision vector drawing with millimeter rulers, zoom/pan navigation, and machine origin markers:

* **Select Tool (`S`)**: Click or marquee select shapes. Drag corner handles to scale (hold `Shift` for aspect lock) and top handle to rotate.
* **Rectangle Tool (`R`)**: Click and drag to create rectangles. Corner radius can be adjusted in Shape Properties.
* **Circle / Ellipse Tool (`C`)**: Click and drag to create circular or elliptical geometries.
* **Line Tool (`L`)**: Click and drag two-point linear vector segments.
* **Text Tool (`T`)**: System font vector outline extraction with instant kerning, bold, and italic styling.
* **Caliper Measurement Tool (`M`)**: Click two points on the canvas to inspect exact Euclidean distance, ΔX, ΔY, and angle.
* **Node Editor (`N`)**: Vertex-level path manipulation (insert, delete, smooth, split).
* **Trim Scissor (`X`)**: One-click deletion of intersecting vector segments.

---

## 3. Cuts & Layer Management

LaserForge features 13 LightBurn-compatible color-coded layers (C00–C11 plus T1 Tool Layer):

| Mode | Purpose | Output |
|---|---|---|
| **Line** | Vector perimeter cutting and scoring | Traces vector paths at target feed rate and power |
| **Fill** | Dense raster scanline surface engraving | Back-and-forth scanlines (default 0.1mm interval) |
| **Fill + Line** | Engrave interior + cut boundary | Raster interior first, then cuts outer perimeter |
| **Image** | Grayscale or dithered photo engraving | Floyd-Steinberg dithering or 8-bit dynamic M4 power |

### Key CAM Parameters

* **Speed (mm/min)**: Head feed rate while cutting. Diode wood cutting is typically 200–600 mm/min; engraving is 1500–4000 mm/min.
* **Power Max (%)**: Upper bound laser power (0–100%). Maps to spindle S-value: `S = max_s * (power_max / 100)`.
* **Power Min (%)**: Lower bound laser power used by GRBL `M4` dynamic mode during corner deceleration.
* **Passes & Pass Delay**: Number of repeated cut cycles. Multi-pass cuts (e.g. 2 passes at 400 mm/min) prevent deep surface charring. Set `Pass Delay (sec)` to allow diode cooling between passes.
* **Kerf Compensation**: Beam offset (typically 0.08–0.15 mm) compensating for laser spot kerf to produce tight friction-fit joints.
* **Holding Tabs / Micro-Bridges**: Leaves small uncut bridges (0.5–2.0 mm) along perimeter contours so cut pieces don't fall into honeycomb trays.
* **Corner Power Ramping**: Proactively reduces laser power around sharp corners above a threshold angle (e.g. 45°) to prevent corner charring.

---

## 4. Raster & Photo Engraving

Photo engraving converts bitmap images (PNG, JPG, BMP, WebP) into laser modulation pulses:

* **Floyd-Steinberg Dithering**: Organic error-diffusion dot patterns ideal for natural skin tones, photographs, and wood.
* **Atkinson Dithering**: High-contrast, clean-dot halftone clusters ideal for slate, anodized aluminum, and hard materials.
* **8-Bit Grayscale Dynamic Modulation (`M4`)**: Real-time laser intensity modulation where pixel darkness directly dictates instantaneous spindle speed `S`. Requires GRBL `$32=1`.
* **Physics-Based Overscan**: Calculates acceleration lead-in and lead-out margins ($d = v^2 / 2a$) outside artwork boundaries so the laser head only burns at constant target velocity, eliminating dark edge burn marks.
* **Whitespace Skipping**: Automatically detects blank spaces ($\ge 5$ mm) across scanlines and rapids at G0, reducing engraving duration by up to 60%.

---

## 5. Hardware & GRBL Controller Setup

LaserForge communicates with standard GRBL 1.1+ laser engravers over USB serial at 115200 baud.

### Critical GRBL Configuration Settings

* **`$32=1` (Laser Mode Enabled)**: **CRITICAL**. When active, GRBL allows instantaneous spindle power modulation without pausing motor motion. If set to `$32=0`, GRBL pauses for spindle ramp-up at every segment, burning severe holes.
* **`$30=1000` (Max Spindle Speed)**: Sets the maximum S value corresponding to 100% laser power. Must match `max_s_value` in LaserForge Settings.
* **`$31=0` (Min Spindle Speed)**: Sets minimum S value corresponding to 0% laser power.
* **`$100`, `$101`, `$102` (Steps/mm)**: Steps per millimeter calibration for X, Y, and Z axes.

### Linux USB Serial Access (`dialout` group)

Linux restricts direct USB serial access to the `dialout` group. If connection fails with *Permission Denied*, run:
```bash
sudo usermod -aG dialout $USER
```
Log out and log back in for permissions to take effect.

### Virtual GRBL Simulator (`VIRTUAL_GRBL`)

No physical laser machine? Select **Port $\rightarrow$ `VIRTUAL_GRBL`** to connect to LaserForge's built-in in-memory GRBL 1.1f simulator. It models motion, status telemetry (`<Idle>`, `<Run>`, `<Hold>`), overrides, and reticle tracking without hardware.

---

## 6. Specialized Design Studios

* **Parametric Box & Enclosure Studio (`Ctrl+Shift+J`)**: Generates 6-sided boxes, open bins, and sliding-lid enclosures with finger joints, dovetails, and kerf allowance.
* **Living Hinges & Lattice Flex Studio**: Parametric straight-slit, wavy torsional, and diamond honeycomb flex patterns enabling rigid plywood or acrylic to bend smoothly into curved shapes.
* **2D Nesting Optimizer Studio (`Ctrl+Shift+N`)**: Bin-packing optimizer that rotates parts (0°, 45°, 90°) and nests smaller parts inside interior holes of larger parts to maximize material yield.
* **Material Burn Test Matrix Studio (`Ctrl+Alt+T`)**: Parametric Speed (rows) $\times$ Power (columns) calibration grid with single-line Hershey numeric labels.
* **Rotary Axis Engine**: Roller and chuck rotary attachment calibration with coordinate scaling or hardware `$101` step overrides.
* **Camera Calibration & Bed Overlay**: Pinhole and fisheye lens undistortion with 4-point laser fiducial homography and floating zoom loupe.
* **Auto-Focus Z-Probe Studio**: Automated G38.2 probing cycle with plate thickness and focal offset parsing.

---

## 7. Safety & Framing Procedures

### Pre-Burn Safety Checklist

1. **Certified Eye Protection**: Always wear certified laser safety glasses (OD 5+) matched to your laser wavelength (e.g. 450nm for blue diode, 1064nm for fiber).
2. **Active Ventilation / Fume Extraction**: Wood emits smoke; acrylic emits PMMA vapor. **NEVER cut PVC, vinyl, or materials containing chlorine**, as they produce lethal chlorine gas and hydrochloric acid that destroys lungs and machinery.
3. **Fire Extinguisher**: Never leave a laser unattended during operation. Keep a CO₂ or dry-chemical fire extinguisher within reach.
4. **Framing Guide (`Ctrl+F`)**: Always run framing before starting a job. LaserForge traces the bounding box using a 0.5% visible guide beam so you can confirm alignment without burning material.

---

## 8. Frequently Asked Questions (FAQ) & Troubleshooting

### Q: Why is my laser head moving, but the beam is not firing?
* **Verify `$32=1`**: Send `$$` in the Console tab. If `$32=0`, type `$32=1` and press Enter.
* **Check Spindle Range**: Ensure `$30` matches `max_s_value` in LaserForge Settings (default 1000).
* **Layer Output**: Ensure the layer's **Output** checkbox is checked in the Cuts/Layers panel, and **Power Max** is greater than 0%.
* **Physical Interlock**: Check the hardware key switch, emergency stop button, or power supply switch on the laser module.

### Q: Why are my cut parts squished, stretched, or the wrong dimensions?
* Your machine's `$100` (X) or `$101` (Y) steps/mm setting needs calibration.
* Verify whether **Rotary Axis Mode** is accidentally active in LaserForge.

### Q: Why do corners burn deeper or get charred on sharp turns?
* As the motor decelerates into sharp corners, laser dwell time increases. Enable **Corner Power Ramping** in the layer cut settings to automatically reduce laser power around sharp bends.

### Q: How do I stop cut pieces from falling into my honeycomb tray?
* Enable **Holding Tabs** in the layer cut settings or open **Tabs Studio** (`Ctrl+Alt+T`). LaserForge will insert small, easily snappable uncut bridges along the cut path.

### Q: Can I import and export LightBurn projects?
* Yes! Use **File $\rightarrow$ Import LightBurn Project (.lbrn, .lbrn2)** (`Ctrl+Alt+L`) and **File $\rightarrow$ Export $\rightarrow$ Export LightBurn Project (.lbrn2)**. All vector shapes, layers, speed, and power settings are preserved.

### Q: What is the difference between M4 Dynamic Power and M3 Constant Power?
* **M4 (Dynamic)** throttles laser intensity proportionally to motor speed during acceleration and deceleration, preventing burnt edges. This is the recommended default for GRBL 1.1+.
* **M3 (Constant)** maintains fixed power regardless of velocity. Use M3 only for constant-speed through-cutting or legacy hardware.

---

## 9. Keyboard Shortcuts Cheat Sheet

| Category | Shortcut | Action |
|---|---|---|
| **CAD Drawing** | `S` | Select Tool |
| | `R` | Rectangle Tool |
| | `C` | Circle / Ellipse Tool |
| | `L` | Line Tool |
| | `T` | Text Tool |
| | `M` | Caliper Measurement Tool |
| | `N` | Node Edit Tool |
| | `X` | Trim Scissor Tool |
| **File & Project** | `Ctrl+N` | New Project |
| | `Ctrl+O` | Open Project |
| | `Ctrl+S` | Save Project |
| | `Ctrl+Shift+P` | Project & Profile Packager (.lfpak) |
| | `Ctrl+I` | Import SVG Vector |
| | `Ctrl+Alt+D` | Import DXF Vector |
| | `Ctrl+Alt+L` | Import LightBurn Project (.lbrn2) |
| | `Ctrl+Shift+E` | Export SVG Vector |
| | `Ctrl+Shift+M` | Job Cost & Time Estimator |
| **View & Canvas** | `Ctrl+0` / `F` | Zoom to Fit Workbed |
| | `H` | Flip Horizontally |
| | `V` | Flip Vertically |
| | `Ctrl+A` | Select All |
| | `Ctrl+D` | Duplicate Selection |
| | `Delete` | Delete Selection |
| **Machine & CAM** | `Alt+P` | Preview Toolpath Simulation |
| | `Ctrl+F` | Frame Bounding Box |
| | `Ctrl+R` | Start Laser Job |
| | `Esc` | Emergency Stop / Abort |
| | `F3` | Auto-Detect & Connect Laser |
| **Help & Onboarding**| `F1` | 📖 User Guide & FAQ |
| | `F2` | 🎓 Interactive Tutorial & Tour |
