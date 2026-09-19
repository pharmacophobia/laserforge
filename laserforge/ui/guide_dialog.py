"""
LaserForge In-App User Guide, Documentation & FAQ Studio.
Provides a comprehensive searchable reference manual, troubleshooting FAQ,
and keyboard shortcut directory accessible directly from the Help menu (F1).
"""

import os
from typing import Optional, Dict, List, Tuple

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTextBrowser, QPushButton, QFrame,
    QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon


GUIDE_SECTIONS: List[Dict[str, str]] = [
    {
        "id": "getting_started",
        "title": "🚀 Getting Started & Workflow",
        "keywords": "start quickstart workflow import export new project setup origin canvas rulers units",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">🚀 Getting Started & Production Workflow</h2>
        <p>Welcome to <b>LaserForge</b> — the high-performance, native laser CAD/CAM software suite designed specifically for Linux. LaserForge supports diode, CO₂, fiber/galvo, and industrial Ruida lasers.</p>
        
        <div style="background-color:#1e293b; border-left:4px solid #38bdf8; padding:12px; margin:14px 0; border-radius:4px;">
            <b style="color:#38bdf8;">Standard 7-Step Production Workflow:</b>
            <ol style="margin:6px 0 0 0; padding-left:20px; line-height:1.6;">
                <li><b>Machine Bed Setup:</b> Open <i>Settings (Ctrl+,)</i> to set your workbed dimensions (e.g. 400×400 mm) and machine origin corner.</li>
                <li><b>Draw or Import:</b> Use CAD tools (S, R, C, L, T) or import SVG, DXF, or LightBurn (.lbrn2) artwork.</li>
                <li><b>Assign Layers:</b> Place cutting outlines on C00 (Line) and engravings on C01 (Fill) via the Cuts/Layers table.</li>
                <li><b>Configure CAM Speeds & Powers:</b> Dial in target feed rate (mm/min), max power %, and pass count for your material.</li>
                <li><b>2D Simulation Pre-Flight:</b> Press <i>Alt+P</i> to preview the animated toolpath, rapid travels (G0), and verify cut ordering.</li>
                <li><b>Frame Bounding Box:</b> Place material on the laser bed, set work zero (G10 L20 P1), and press <i>Ctrl+F</i> to trace the visible guide beam.</li>
                <li><b>Start Burn:</b> Press <i>Ctrl+R</i> to stream G-code with live status telemetry and dynamic speed/power override sliders.</li>
            </ol>
        </div>

        <h3 style="color:#7dd3fc;">CAD Canvas & View Navigation</h3>
        <ul>
            <li><b>Pan:</b> Hold middle mouse button or Spacebar and drag.</li>
            <li><b>Zoom:</b> Scroll mouse wheel (zooms centered on cursor).</li>
            <li><b>Zoom to Fit:</b> Press <code>Ctrl+0</code> or <code>F</code> to instantly fit the entire workbed on screen.</li>
            <li><b>Snap to Grid:</b> Toggle 1mm minor grid snapping from the <i>View</i> menu for precision alignment.</li>
            <li><b>Guides:</b> Drag alignment guides from the top and left rulers to align multiple parts.</li>
        </ul>
        """
    },
    {
        "id": "cuts_layers",
        "title": "🎨 Cuts, Layers & CAM Settings",
        "keywords": "layer mode line fill scan cut passes speed power kerf tabs delay assist air",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">🎨 Cuts, Layers & CAM Parameter Guide</h2>
        <p>LaserForge features <b>13 LightBurn-compatible color-coded layers (C00–C11 + T1 Tool Layer)</b>. Each layer independently governs how the laser treats assigned vector paths.</p>

        <table style="width:100%; border-collapse:collapse; margin:12px 0;">
            <tr style="background-color:#1e293b; color:#38bdf8; text-align:left;">
                <th style="padding:8px; border:1px solid #334155;">Cut Mode</th>
                <th style="padding:8px; border:1px solid #334155;">Operation</th>
                <th style="padding:8px; border:1px solid #334155;">Typical Use Case</th>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><b>Line</b></td>
                <td style="padding:8px; border:1px solid #334155;">Vector stroke cutting & scoring</td>
                <td style="padding:8px; border:1px solid #334155;">Cutting through plywood, acrylic, cardstock; scoring fold lines</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><b>Fill</b></td>
                <td style="padding:8px; border:1px solid #334155;">Raster scanline surface engraving</td>
                <td style="padding:8px; border:1px solid #334155;">Dark surface engraving of text, filled logos, and solid graphics</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><b>Fill + Line</b></td>
                <td style="padding:8px; border:1px solid #334155;">Interior raster + perimeter cut</td>
                <td style="padding:8px; border:1px solid #334155;">Clean badges: engraves interior, then traces crisp outer boundary</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><b>Image</b></td>
                <td style="padding:8px; border:1px solid #334155;">Dithered or grayscale photo engraving</td>
                <td style="padding:8px; border:1px solid #334155;">Photographs on wood, slate, leather, acrylic, anodized aluminum</td>
            </tr>
        </table>

        <h3 style="color:#7dd3fc;">Advanced CAM Parameters</h3>
        <ul>
            <li><b>Speed (mm/min):</b> Feed rate while cutting. Diode laser wood cutting is typically 200–600 mm/min; engraving is 1500–4000 mm/min.</li>
            <li><b>Power Max (%):</b> Peak laser intensity (0–100%). Maps directly to GRBL spindle S-value: <code>S = max_s * (power / 100)</code>.</li>
            <li><b>Passes & Pass Delay:</b> Repeated cutting passes. Multi-pass cuts (e.g. 2 passes at 400 mm/min vs 1 slow pass at 200 mm/min) produce cleaner cuts with significantly less edge charring. <i>Pass Delay (sec)</i> gives the diode module time to cool between cycles.</li>
            <li><b>Kerf Compensation:</b> The physical laser beam has width (~0.08–0.15 mm). Automatic kerf offsets outer perimeters outward and inner cutouts inward for perfect friction-fit box joints and inlays.</li>
            <li><b>Holding Tabs:</b> Leaves tiny uncut bridges (0.5–2.0 mm) along perimeter cuts so lightweight cutouts don't drop or tilt into the honeycomb tray.</li>
            <li><b>Corner Power Ramping:</b> Automatically throttles laser power down around sharp turns to prevent over-burning corner vertices.</li>
        </ul>
        """
    },
    {
        "id": "photo_raster",
        "title": "🖼 Raster & Photo Engraving",
        "keywords": "image photo raster dither floyd atkinson overscan whitespace dpi grayscale",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">🖼 Raster & Photo Engraving Studio</h2>
        <p>LaserForge transforms bitmap images (PNG, JPG, BMP, WebP) into high-definition laser engraving programs with sub-millimeter precision.</p>

        <h3 style="color:#7dd3fc;">Dithering Modes</h3>
        <ul>
            <li><b>Floyd-Steinberg Dithering:</b> Organic error diffusion producing smooth photographic gradients, skin tones, and soft shadows. Best for natural wood grain and portraits.</li>
            <li><b>Atkinson Dithering:</b> High-contrast clean-dot halftone pattern with distinct negative space. Best for hard surfaces like slate, marble, leather, and anodized aluminum.</li>
            <li><b>Grayscale 8-bit Dynamic Modulation:</b> Uses GRBL <code>M4</code> dynamic laser mode to modulate the laser tube/diode PWM in real time based on pixel darkness (0–255). Requires GRBL <code>$32=1</code>.</li>
        </ul>

        <div style="background-color:#1e293b; border-left:4px solid #10b981; padding:12px; margin:14px 0; border-radius:4px;">
            <b style="color:#10b981;">Physics-Based Acceleration & Overscan:</b>
            <p style="margin:4px 0 0 0;">Because stepper motors cannot stop or change direction instantaneously, engraving without overscan causes dark, over-burned edges as the head decelerates at the turnaround points. LaserForge applies physics-based overscan:
            <br><code>distance = velocity² / (2 * acceleration)</code>
            <br>This guarantees the laser only burns when the head is traveling at constant target velocity!</p>
        </div>

        <h3 style="color:#7dd3fc;">Whitespace Skipping</h3>
        <p>When engraving designs with wide blank spaces between elements, LaserForge automatically switches to rapid G0 traversal across non-burning gaps (&ge; 5 mm), cutting total engraving time by up to <b>60%</b>.</p>
        """
    },
    {
        "id": "hardware_grbl",
        "title": "🔌 Laser Hardware & GRBL Setup",
        "keywords": "grbl usb serial connection baud rate 115200 virtual simulator port dialout $32 $30 $h $x jog",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">🔌 Laser Hardware, Serial & GRBL Setup</h2>
        <p>LaserForge connects to any GRBL 1.1+ laser engraver over USB serial at <b>115200 baud</b> (standard for Ortur, Sculpfun, Atomstack, xTool, TwoTrees, Creality Falcon, Neje, and custom CNC controllers).</p>

        <div style="background-color:#1e293b; border-left:4px solid #f59e0b; padding:12px; margin:14px 0; border-radius:4px;">
            <b style="color:#f59e0b;">CRITICAL: GRBL Configuration Requirements:</b>
            <ul style="margin:6px 0 0 0; padding-left:20px; line-height:1.6;">
                <li><b><code>$32=1</code> (Laser Mode Enabled):</b> MUST be enabled. In laser mode, GRBL modulates laser power instantaneously without waiting for spindle acceleration delays. If set to <code>$32=0</code>, the machine will pause at every line segment, burning deep holes.</li>
                <li><b><code>$30=1000</code> (Max Spindle Speed):</b> Sets the S-value scale (0–1000). Must match <i>Max S Value</i> in LaserForge Settings.</li>
                <li><b><code>$31=0</code> (Min Spindle Speed):</b> Sets the minimum S-value (laser off).</li>
            </ul>
        </div>

        <h3 style="color:#7dd3fc;">Linux USB Serial Permissions (dialout Group)</h3>
        <p>Linux restricts access to USB serial devices (<code>/dev/ttyUSB0</code>, <code>/dev/ttyACM0</code>) to members of the <b>dialout</b> group. If LaserForge reports <i>Permission Denied</i> on connect, run this command in terminal:</p>
        <pre style="background-color:#0f172a; padding:8px 12px; border-radius:4px; border:1px solid #334155; color:#38bdf8;">sudo usermod -aG dialout $USER</pre>
        <p>Log out and log back in for changes to take effect.</p>

        <h3 style="color:#7dd3fc;">Hardware-Free Testing: VIRTUAL_GRBL Simulator</h3>
        <p>You can design and test without a laser machine plugged in. In the Laser tab, select port <b>VIRTUAL_GRBL</b> and click <i>Connect</i>. LaserForge will launch an in-memory GRBL 1.1f loopback engine that responds to homing, jogging, status polling, and G-code streaming with real-time reticle tracking.</p>
        """
    },
    {
        "id": "design_studios",
        "title": "🧰 Specialized Design Studios",
        "keywords": "studios box hinge nesting rotary material test galvo ruida relief probe business card",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">🧰 Specialized Parametric Design Studios</h2>
        <p>LaserForge includes a full suite of parametric CAD/CAM studios accessible from the <i>Tools</i> menu:</p>

        <ul>
            <li><b>📦 Box & Enclosure Studio (Ctrl+Shift+J):</b> Generates flat-pack 6-sided boxes, open-top bins, and sliding-lid enclosures with customizable finger joints, dovetail pins, and kerf allowance.</li>
            <li><b>🪗 Living Hinges & Lattice Flex Studio:</b> Generates flexible straight-slit, wavy torsional, and diamond lattice patterns allowing rigid 3mm wood or acrylic to bend smoothly into 90° and 180° curved enclosures.</li>
            <li><b>🧩 2D Nesting Optimizer Studio (Ctrl+Shift+N):</b> Automatic bin-packing algorithm that rotates parts (0°, 45°, 90°) and nests smaller parts inside the interior cutouts of larger shapes to minimize material waste.</li>
            <li><b>📊 Material Test Matrix Studio (Ctrl+Alt+T):</b> Generates a parametric Speed (rows) &times; Power (columns) calibration grid with single-line Hershey numeric labels to find the ideal burn settings for new materials.</li>
            <li><b>🔄 Rotary Axis Engine:</b> Supports roller and chuck rotary attachments with automatic Y-axis coordinate scaling or hardware steps/rev overrides for tumblers, glasses, and pens.</li>
            <li><b>📐 Caliper Measurement Tool (M):</b> Click any two points on the canvas to inspect exact Euclidean distance, &Delta;X, &Delta;Y, and angle.</li>
            <li><b>📷 Camera Calibration Studio:</b> Calibrates USB overhead cameras using OpenCV checkerboard lens undistortion and 4-point laser fiducial homography for millimeter-accurate bed overlay projection.</li>
        </ul>
        """
    },
    {
        "id": "safety_framing",
        "title": "🦺 Safety, Framing & Best Practices",
        "keywords": "safety framing goggles glasses fire smoke ventilation pvc vinyl toxic emergency stop",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">🦺 Safety, Framing & Best Practices</h2>
        <p>Laser engraving and cutting involves high-energy coherent radiation and intense thermal decomposition. Always follow these safety protocols:</p>

        <div style="background-color:#1e293b; border-left:4px solid #ef4444; padding:12px; margin:14px 0; border-radius:4px;">
            <b style="color:#ef4444;">CRITICAL: Materials That Must NEVER Be Cut:</b>
            <ul style="margin:4px 0 0 0; padding-left:20px; line-height:1.5;">
                <li><b>PVC / Vinyl / Artificial Leather:</b> Emits lethal <b>chlorine gas</b> and hydrochloric acid that destroys lung tissue and permanently rusts laser rails and optical lenses within hours.</li>
                <li><b>Polycarbonate / Lexan:</b> Cuts poorly, discolors, and catches fire rapidly.</li>
                <li><b>ABS:</b> Emits toxic cyanide gas and creates severe fumes.</li>
                <li><b>HDPE / Milk Jugs:</b> Melts into burning liquid plastic and catches fire.</li>
                <li><b>Carbon Fiber / Fiberglass:</b> Emits hazardous resin fumes and toxic glass particulate.</li>
            </ul>
        </div>

        <h3 style="color:#7dd3fc;">Pre-Burn Checklist</h3>
        <ol style="line-height:1.6;">
            <li><b>Laser Safety Glasses:</b> Always wear certified eye protection with Optical Density &ge; OD 5+ matched to your laser's wavelength (450 nm for blue diode; 10600 nm for CO₂).</li>
            <li><b>Active Exhaust Ventilation:</b> Ensure fumes and smoke are actively vented outdoors or filtered through activated carbon and HEPA scrubbers.</li>
            <li><b>Fire Extinguisher:</b> NEVER leave an operating laser unattended. Keep a CO₂ or dry-chemical fire extinguisher within reach at all times.</li>
            <li><b>Frame Bounding Box (Ctrl+F):</b> Always trace the bounding box before cutting. LaserForge uses a 0.5% visible guide beam to confirm stock placement without burning.</li>
            <li><b>Emergency Stop:</b> Press <b>Esc</b> or click <i>Stop</i> to immediately halt motor motion and kill laser power.</li>
        </ol>
        """
    },
    {
        "id": "faq_troubleshooting",
        "title": "❓ Frequently Asked Questions (FAQ)",
        "keywords": "faq question help troubleshoot fire beam move dimension squish lightburn m3 m4 license",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">❓ Frequently Asked Questions & Troubleshooting</h2>

        <div style="margin-bottom:16px;">
            <b style="color:#38bdf8; font-size:14px;">Q: The laser head is moving, but the laser beam is not firing. Why?</b>
            <p style="margin:4px 0 0 0; color:#cbd5e1;">
            1. <b>Verify GRBL Laser Mode:</b> Open the <i>Console</i> tab, type <code>$$</code>, and press Enter. Ensure <code>$32=1</code>. If it says <code>$32=0</code>, type <code>$32=1</code>.<br>
            2. <b>Check Spindle Scale:</b> Ensure <code>$30</code> matches <i>Max S Value</i> in LaserForge Settings (default 1000).<br>
            3. <b>Check Layer Output:</b> In the Cuts/Layers table, make sure the layer's <i>Output</i> box is checked and <i>Max Power</i> is greater than 0%.<br>
            4. <b>Hardware Interlock:</b> Check physical key switches, emergency stop buttons, or laser module 12V/24V power cables.
            </p>
        </div>

        <div style="margin-bottom:16px;">
            <b style="color:#38bdf8; font-size:14px;">Q: Why are my engraved dimensions stretched, squished, or the wrong size?</b>
            <p style="margin:4px 0 0 0; color:#cbd5e1;">
            Your controller's steps per millimeter setting (<code>$100</code> for X, <code>$101</code> for Y) needs calibration, or <i>Rotary Axis Mode</i> is accidentally enabled in Machine Settings.
            </p>
        </div>

        <div style="margin-bottom:16px;">
            <b style="color:#38bdf8; font-size:14px;">Q: How do I stop sharp corners from getting charred or burnt?</b>
            <p style="margin:4px 0 0 0; color:#cbd5e1;">
            When the machine slows down to change direction at sharp vertices, dwell time increases. Enable <b>Corner Power Ramping</b> in the layer cut settings. LaserForge will automatically ramp down laser power proportional to deceleration.
            </p>
        </div>

        <div style="margin-bottom:16px;">
            <b style="color:#38bdf8; font-size:14px;">Q: Can I open LightBurn files in LaserForge, and export back to LightBurn?</b>
            <p style="margin:4px 0 0 0; color:#cbd5e1;">
            Yes! LaserForge provides bidirectional LightBurn support. Use <b>File &rarr; Import LightBurn Project (.lbrn, .lbrn2)</b> to import projects, and <b>File &rarr; Export &rarr; Export LightBurn Project (.lbrn2)</b> to save native LightBurn project files.
            </p>
        </div>

        <div style="margin-bottom:16px;">
            <b style="color:#38bdf8; font-size:14px;">Q: What is the difference between M4 Dynamic Mode and M3 Constant Mode?</b>
            <p style="margin:4px 0 0 0; color:#cbd5e1;">
            <b>M4 Dynamic Mode</b> throttles laser power in real time as the motor accelerates and decelerates, ensuring completely uniform burn density across curves and corners. <b>M3 Constant Mode</b> maintains fixed power regardless of velocity, which is only recommended for constant-speed through-cutting.
            </p>
        </div>

        <div style="margin-bottom:16px;">
            <b style="color:#38bdf8; font-size:14px;">Q: How does the commercial license work?</b>
            <p style="margin:4px 0 0 0; color:#cbd5e1;">
            LaserForge offers a full 30-day free trial. Commercial activation uses cryptographic HMAC-SHA256 offline license keys bound to your hardware fingerprint. <b>LaserForge never connects to external servers or phones home</b>, preserving complete privacy and working in 100% air-gapped workshops.
            </p>
        </div>
        """
    },
    {
        "id": "keyboard_shortcuts",
        "title": "⌨️ Keyboard Shortcuts Reference",
        "keywords": "shortcuts keys keyboard hotkeys ctrl alt shift key reference",
        "html": """
        <h2 style="color:#38bdf8; margin-top:0;">⌨️ Keyboard Shortcuts Reference Directory</h2>
        
        <table style="width:100%; border-collapse:collapse; margin:12px 0;">
            <tr style="background-color:#1e293b; color:#38bdf8; text-align:left;">
                <th style="padding:8px; border:1px solid #334155;">Category</th>
                <th style="padding:8px; border:1px solid #334155;">Key / Shortcut</th>
                <th style="padding:8px; border:1px solid #334155;">Function</th>
            </tr>
            <tr>
                <td rowspan="8" style="padding:8px; border:1px solid #334155; vertical-align:top;"><b>CAD Tools</b></td>
                <td style="padding:8px; border:1px solid #334155;"><code>S</code></td>
                <td style="padding:8px; border:1px solid #334155;">Select & Transform Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>R</code></td>
                <td style="padding:8px; border:1px solid #334155;">Rectangle Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>C</code></td>
                <td style="padding:8px; border:1px solid #334155;">Circle / Ellipse Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>L</code></td>
                <td style="padding:8px; border:1px solid #334155;">Line Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>T</code></td>
                <td style="padding:8px; border:1px solid #334155;">Text Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>M</code></td>
                <td style="padding:8px; border:1px solid #334155;">Interactive Caliper Measuring Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>N</code></td>
                <td style="padding:8px; border:1px solid #334155;">Vector Node Edit Tool</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>X</code></td>
                <td style="padding:8px; border:1px solid #334155;">Trim Scissor Intersection Tool</td>
            </tr>

            <tr style="background-color:#0f172a;">
                <td rowspan="6" style="padding:8px; border:1px solid #334155; vertical-align:top;"><b>File & Project</b></td>
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+N</code></td>
                <td style="padding:8px; border:1px solid #334155;">New Project</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+O</code></td>
                <td style="padding:8px; border:1px solid #334155;">Open Project</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+S</code></td>
                <td style="padding:8px; border:1px solid #334155;">Save Project</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+I</code></td>
                <td style="padding:8px; border:1px solid #334155;">Import SVG / Vector</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+Alt+D</code></td>
                <td style="padding:8px; border:1px solid #334155;">Import DXF Vector</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+Alt+L</code></td>
                <td style="padding:8px; border:1px solid #334155;">Import LightBurn Project (.lbrn2)</td>
            </tr>

            <tr>
                <td rowspan="5" style="padding:8px; border:1px solid #334155; vertical-align:top;"><b>Machine & CAM</b></td>
                <td style="padding:8px; border:1px solid #334155;"><code>Alt+P</code></td>
                <td style="padding:8px; border:1px solid #334155;">Preview Toolpath Simulation</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+F</code></td>
                <td style="padding:8px; border:1px solid #334155;">Frame Bounding Box (Visible Guide Beam)</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>Ctrl+R</code></td>
                <td style="padding:8px; border:1px solid #334155;">Start Laser Job</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>Esc</code></td>
                <td style="padding:8px; border:1px solid #334155;">Emergency Stop / Abort Job</td>
            </tr>
            <tr>
                <td style="padding:8px; border:1px solid #334155;"><code>F3</code></td>
                <td style="padding:8px; border:1px solid #334155;">Auto-Detect & Connect Laser</td>
            </tr>

            <tr style="background-color:#0f172a;">
                <td rowspan="2" style="padding:8px; border:1px solid #334155; vertical-align:top;"><b>Help & Learning</b></td>
                <td style="padding:8px; border:1px solid #334155;"><code>F1</code></td>
                <td style="padding:8px; border:1px solid #334155;">User Guide & FAQ Manual</td>
            </tr>
            <tr style="background-color:#0f172a;">
                <td style="padding:8px; border:1px solid #334155;"><code>F2</code></td>
                <td style="padding:8px; border:1px solid #334155;">Interactive Tutorial & Tour</td>
            </tr>
        </table>
        """
    }
]


class UserGuideDialog(QDialog):
    """
    Searchable user guide and troubleshooting manual for LaserForge.
    Accessible from Help -> User Guide & FAQ (F1).
    """

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("LaserForge User Guide & Documentation 📖")
        self.resize(920, 640)
        self.setMinimumSize(780, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: sans-serif;
            }
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 8px 12px;
                color: #f8fafc;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
            QListWidget {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-bottom: 1px solid #293548;
            }
            QListWidget::item:selected {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: bold;
                border-radius: 4px;
            }
            QTextBrowser {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 16px;
                color: #e2e8f0;
                font-size: 13px;
                line-height: 1.6;
            }
            QPushButton {
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton#btnPrimary {
                background-color: #0284c7;
                color: #ffffff;
            }
            QPushButton#btnPrimary:hover {
                background-color: #0369a1;
            }
            QPushButton#btnSecondary {
                background-color: #334155;
                color: #cbd5e1;
            }
            QPushButton#btnSecondary:hover {
                background-color: #475569;
                color: #ffffff;
            }
            code {
                background-color: #0f172a;
                color: #38bdf8;
                padding: 2px 5px;
                border-radius: 3px;
                font-family: monospace;
            }
        """)

        self._init_ui()
        self._populate_list()
        self.list_sections.setCurrentRow(0)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        # Header Search Row
        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)

        icon_lbl = QLabel("📖")
        icon_lbl.setFont(QFont("sans-serif", 20))
        search_layout.addWidget(icon_lbl)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search guide, topics, or FAQs... (e.g. 'kerf', 'M4', 'dither', 'baud', 'steps')")
        self.search_edit.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_edit, 1)

        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("btnSecondary")
        btn_clear.clicked.connect(lambda: self.search_edit.clear())
        search_layout.addWidget(btn_clear)

        layout.addLayout(search_layout)

        # Main Splitter (Left: Topics List, Right: Text Browser)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.list_sections = QListWidget()
        self.list_sections.setFixedWidth(270)
        self.list_sections.currentRowChanged.connect(self._on_section_selected)
        splitter.addWidget(self.list_sections)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        splitter.addWidget(self.browser)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        # Footer Row with Quick Actions
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        btn_tut = QPushButton("🎓 Launch Interactive Tutorial")
        btn_tut.setObjectName("btnPrimary")
        btn_tut.clicked.connect(self._launch_tutorial)
        footer_layout.addWidget(btn_tut)

        btn_feedback = QPushButton("💬 Message Developer / Report Bug")
        btn_feedback.setObjectName("btnSecondary")
        btn_feedback.clicked.connect(self._open_feedback)
        footer_layout.addWidget(btn_feedback)

        footer_layout.addStretch(1)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("btnSecondary")
        btn_close.clicked.connect(self.accept)
        footer_layout.addWidget(btn_close)

        layout.addLayout(footer_layout)

    def _populate_list(self):
        self.list_sections.clear()
        for s in GUIDE_SECTIONS:
            item = QListWidgetItem(s["title"])
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.list_sections.addItem(item)

    def _on_section_selected(self, row: int):
        if row < 0 or row >= len(GUIDE_SECTIONS):
            return
        section = GUIDE_SECTIONS[row]
        self.browser.setHtml(section["html"])

    def _on_search_changed(self, text: str):
        query = text.strip().lower()
        if not query:
            # Restore all items
            for i in range(self.list_sections.count()):
                self.list_sections.item(i).setHidden(False)
            current = self.list_sections.currentRow()
            if current >= 0:
                self._on_section_selected(current)
            return

        # Search matching sections
        first_match_row = -1
        for i, s in enumerate(GUIDE_SECTIONS):
            combined_text = (s["title"] + " " + s["keywords"] + " " + s["html"]).lower()
            match = query in combined_text
            self.list_sections.item(i).setHidden(not match)
            if match and first_match_row == -1:
                first_match_row = i

        if first_match_row != -1:
            self.list_sections.setCurrentRow(first_match_row)
        else:
            self.browser.setHtml(
                f"<div style='text-align:center; padding:40px 20px;'>"
                f"<h3 style='color:#f59e0b;'>No matching topics found for '{text}'</h3>"
                f"<p style='color:#94a3b8;'>Try searching for terms like <i>kerf</i>, <i>M4</i>, <i>dither</i>, <i>tabs</i>, <i>rotary</i>, or <i>speed</i>.</p>"
                f"</div>"
            )

    def _launch_tutorial(self):
        if self.main_window and hasattr(self.main_window, "start_interactive_tutorial"):
            self.main_window.start_interactive_tutorial()

    def _open_feedback(self):
        if self.main_window and hasattr(self.main_window, "open_feedback_dialog"):
            self.main_window.open_feedback_dialog()
