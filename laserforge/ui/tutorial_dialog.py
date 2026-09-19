"""
LaserForge Interactive Tutorial & Guided Onboarding Studio.
Provides a comprehensive 6-step interactive walkthrough that users can launch
at installation, on first run, or anytime from Help -> Interactive Tutorial.
"""

import os
import sys
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox, QCheckBox, QListWidget, QListWidgetItem,
    QScrollArea, QFrame, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap

from laserforge.core.models import RectEntity, CircleEntity, TextEntity, LayerCutSettings


class WelcomeOnboardingDialog(QDialog):
    """
    First-run welcome dialog presented to the user after installation or first launch.
    Allows one-click launch into the Interactive Tutorial or starting a blank project.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to LaserForge! 🚀")
        self.resize(540, 420)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: sans-serif;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 14px;
                background-color: #1e293b;
                font-weight: bold;
                color: #38bdf8;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
                line-height: 1.4;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                padding: 10px 18px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton#btnStartTutorial {
                background-color: #0284c7;
                color: #ffffff;
            }
            QPushButton#btnStartTutorial:hover {
                background-color: #0369a1;
            }
            QPushButton#btnSkip {
                background-color: #334155;
                color: #cbd5e1;
            }
            QPushButton#btnSkip:hover {
                background-color: #475569;
                color: #ffffff;
            }
            QCheckBox {
                color: #94a3b8;
                font-size: 12px;
            }
        """)

        self.start_tutorial_selected = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        # Header with Logo / Icon & Title
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_lbl = QLabel("🔥")
        icon_lbl.setFont(QFont("sans-serif", 32))
        header_layout.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        title_lbl = QLabel("<h2 style='margin:0; color:#38bdf8;'>Welcome to LaserForge</h2>")
        subtitle_lbl = QLabel("<i style='color:#94a3b8;'>Native High-Performance Laser CAD/CAM Suite for Linux</i>")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(subtitle_lbl)
        header_layout.addLayout(title_layout)
        header_layout.addStretch(1)
        layout.addLayout(header_layout)

        # Overview Card
        card = QGroupBox("Fast, Powerful & LightBurn-Compatible")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(16, 16, 16, 16)

        desc = QLabel(
            "LaserForge is engineered for diode, CO2, fiber, and galvo engravers. "
            "Whether you are cutting precision parts or engraving detailed artwork, "
            "LaserForge gives you full control from vector drawing to machine streaming."
        )
        desc.setWordWrap(True)
        card_layout.addWidget(desc)

        features = [
            "⚡ <b>13 Color-Coded Cut/Raster Layers</b> (Line, Fill, Fill+Line, Image)",
            "🎯 <b>Built-in GRBL Controller</b> + Hardware-free <b>Virtual Simulator</b>",
            "🎬 <b>Animated 2D Toolpath Simulator</b> with physics-based overscan",
            "📐 <b>Parametric Studios</b>: Boxes, Living Hinges, 2D Nesting, & Materials"
        ]
        for f in features:
            lbl = QLabel(f)
            lbl.setStyleSheet("color: #e2e8f0; font-size: 12px;")
            card_layout.addWidget(lbl)

        layout.addWidget(card)

        # Interactive Tutorial Prompt
        prompt_lbl = QLabel(
            "<b>Would you like to take a quick interactive tour?</b><br>"
            "Learn how to draw shapes, configure layers, simulate toolpaths, and test motion."
        )
        prompt_lbl.setWordWrap(True)
        layout.addWidget(prompt_lbl)

        layout.addStretch(1)

        # Checkbox: Don't show again
        self.chk_dont_show = QCheckBox("Don't show this welcome screen on startup")
        self.chk_dont_show.setChecked(True)
        layout.addWidget(self.chk_dont_show)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_skip = QPushButton("Skip & Explore Blank Canvas")
        self.btn_skip.setObjectName("btnSkip")
        self.btn_skip.clicked.connect(self._on_skip)

        self.btn_start = QPushButton("🎓 Start Interactive Tutorial")
        self.btn_start.setObjectName("btnStartTutorial")
        self.btn_start.clicked.connect(self._on_start)

        btn_layout.addWidget(self.btn_skip)
        btn_layout.addWidget(self.btn_start)
        layout.addLayout(btn_layout)

    def _on_start(self):
        self.start_tutorial_selected = True
        self._save_preference()
        self.accept()

    def _on_skip(self):
        self.start_tutorial_selected = False
        self._save_preference()
        self.reject()

    def _save_preference(self):
        if self.chk_dont_show.isChecked():
            settings = QSettings("LaserForge", "LaserForge")
            settings.setValue("tutorial_prompt_dismissed", True)


class InteractiveTutorialDialog(QDialog):
    """
    6-step interactive tutorial and guided tour for LaserForge.
    Can be run modeless alongside the main canvas so the user can see actions
    in real time and click 'Try It' buttons that directly interact with the app.
    """

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("LaserForge Interactive Tutorial & Tour 🎓")
        self.resize(760, 560)
        self.setMinimumSize(680, 500)
        # Modeless dialog so user can interact with canvas
        self.setModal(False)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: sans-serif;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 12px;
                background-color: #1e293b;
                font-weight: bold;
                color: #38bdf8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
                line-height: 1.4;
            }
            QListWidget {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #283548;
            }
            QListWidget::item:selected {
                background-color: #0369a1;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton {
                border: none;
                border-radius: 5px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton#btnAction {
                background-color: #0284c7;
                color: #ffffff;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton#btnAction:hover {
                background-color: #0369a1;
            }
            QPushButton#btnNav {
                background-color: #334155;
                color: #f8fafc;
            }
            QPushButton#btnNav:hover {
                background-color: #475569;
            }
            QPushButton#btnFinish {
                background-color: #16a34a;
                color: #ffffff;
            }
            QPushButton#btnFinish:hover {
                background-color: #15803d;
            }
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 4px;
                text-align: center;
                background-color: #1e293b;
                color: #38bdf8;
                font-weight: bold;
                height: 14px;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #0284c7;
                border-radius: 3px;
            }
        """)

        self.current_step = 0
        self.steps_data = self._build_steps_data()
        self._init_ui()
        self.show_step(0)

    def _build_steps_data(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "welcome_workspace",
                "sidebar_title": "1. Workspace Tour",
                "badge": "STEP 1 OF 6",
                "title": "Welcome to LaserForge & Workspace Tour",
                "icon": "🏠",
                "summary": (
                    "LaserForge gives you a full LightBurn-compatible CAM workflow designed specifically for Linux. "
                    "Let's explore the primary functional areas of your workspace:"
                ),
                "details": [
                    ("📐 <b>CAD Workbed Canvas</b>", "Center area with real-time millimeter rulers, grid snap, crosshairs, and machine origin marker."),
                    ("🎨 <b>Cuts / Layers Panel</b>", "Right top panel managing 13 color-coded layers (C00–C11 + T1 Tool Layer) with independent cut speeds, power, and passes."),
                    ("🎮 <b>Laser & Operations Dock</b>", "Right bottom panel for GRBL USB connection, 8-directional motor jog pad, status telemetry, and emergency controls."),
                    ("🛠 <b>CAD Drawing Toolbars</b>", "Top and left toolbars providing Selection (S), Rectangle (R), Circle (C), Line (L), Text (T), and Measuring Calipers.")
                ],
                "action_title": "Interactive Playground",
                "action_desc": "Highlight the workspace panels to locate all key interface elements.",
                "action_btn_text": "🔍 Highlight Workspace Panels",
                "action_handler": self._action_highlight_workspace
            },
            {
                "id": "drawing_vectors",
                "sidebar_title": "2. Drawing Vectors",
                "badge": "STEP 2 OF 6",
                "title": "Drawing & Transforming Vector Geometry",
                "icon": "✏️",
                "summary": (
                    "Every laser job starts with vector geometry. In LaserForge, you can draw primitives, "
                    "import SVGs/DXFs, or generate parametric shapes with millimeter precision:"
                ),
                "details": [
                    ("🔲 <b>Primitives</b>", "Press <b>R</b> for Rectangle, <b>C</b> for Circle/Ellipse, <b>L</b> for Line, <b>T</b> for Text."),
                    ("🔄 <b>Transform Handles</b>", "Select any shape to view bounding box handles. Drag corners to scale (hold Shift for aspect lock), top circle to rotate."),
                    ("📏 <b>Shape Properties Dock</b>", "Use the Properties tab in the lower-right dock to enter exact numeric X, Y, Width, Height, and Rotation values."),
                    ("🧩 <b>Art & Component Library</b>", "Tabbed alongside Cuts/Layers is the Art Library (`Ctrl+Shift+L`) with reusable fasteners, holes, and fiducials.")
                ],
                "action_title": "Interactive Playground",
                "action_desc": "Place a multi-part keychain badge onto the canvas to practice vector selection and inspection.",
                "action_btn_text": "➕ Place Tutorial Badge on Canvas",
                "action_handler": self._action_place_sample_shapes
            },
            {
                "id": "cuts_layers",
                "sidebar_title": "3. Cuts & Layers",
                "badge": "STEP 3 OF 6",
                "title": "Mastering Cut & Engrave Layer Modes",
                "icon": "🎨",
                "summary": (
                    "LaserForge organizes your design into 13 color-coded layers (C00–C11). "
                    "Each layer controls how the laser interacts with your material:"
                ),
                "details": [
                    ("✂️ <b>Line Mode</b>", "Vector contour cutting and scoring. Traces paths at high power and controlled speed to cut through material."),
                    ("⬛ <b>Fill Mode</b>", "Raster scanline engraving. Scans back and forth at 0.1 mm line interval to engrave dark graphics and text."),
                    ("🔲 <b>Fill + Line Mode</b>", "Hybrid mode: first engraves the interior with raster lines, then traces the perimeter for a razor-sharp outline."),
                    ("🖼 <b>Image Mode</b>", "Photo engraving using Floyd-Steinberg dithering or 8-bit dynamic M4 laser power modulation.")
                ],
                "action_title": "Interactive Playground",
                "action_desc": "Configure Layer C00 (Black) as an acrylic cut path and C01 (Blue) as a high-speed text fill.",
                "action_btn_text": "🎨 Apply Recommended Cut & Engrave Settings",
                "action_handler": self._action_configure_layers
            },
            {
                "id": "simulation_preview",
                "sidebar_title": "4. 2D Simulation",
                "badge": "STEP 4 OF 6",
                "title": "Pre-Flight 2D Toolpath Simulation",
                "icon": "🎬",
                "summary": (
                    "Before firing the laser, always verify your job in the interactive 2D simulation preview (Alt+P). "
                    "This protects against unexpected collisions, out-of-bounds bed crashes, and ruined stock:"
                ),
                "details": [
                    ("🔄 <b>Inner-First Ordering</b>", "LaserForge automatically sorts internal holes and cavities to cut before outer boundaries so parts don't drop prematurely."),
                    ("⚡ <b>Rapid Travel Minimization</b>", "TSP nearest-neighbor optimization orders contours to minimize idle G0 rapid moves."),
                    ("🔴 <b>Color Coded Toolpaths</b>", "Red dashed lines indicate rapid travels (G0); colored solid lines represent burning cuts (G1/G2/G3)."),
                    ("⏱ <b>Physics-Based Run Time</b>", "Calculates exact job duration taking machine acceleration and overscan margins into account.")
                ],
                "action_title": "Interactive Playground",
                "action_desc": "Compile the current canvas entities to G-code and launch the animated 2D toolpath simulator.",
                "action_btn_text": "🎬 Launch 2D Simulation Preview",
                "action_handler": self._action_preview_simulation
            },
            {
                "id": "virtual_grbl",
                "sidebar_title": "5. Virtual Hardware",
                "badge": "STEP 5 OF 6",
                "title": "Machine Control & Virtual GRBL Simulator",
                "icon": "⚡",
                "summary": (
                    "LaserForge communicates with any GRBL 1.1+ laser machine over USB serial (115200 baud). "
                    "Best of all, you don't even need physical hardware to test your setups:"
                ),
                "details": [
                    ("🤖 <b>Virtual GRBL Simulator</b>", "LaserForge includes an internal in-memory GRBL 1.1f loopback engine (`VIRTUAL_GRBL`) simulating motion, MPos/WPos, and overrides."),
                    ("🕹 <b>8-Direction Jog Pad</b>", "Precision motor jogging with configurable step distances (0.1 mm fine through 100 mm coarse) and keyboard arrow keys."),
                    ("📍 <b>Work Coordinate Zero</b>", "Click 'Set Work Zero' (G10 L20 P1) to set your origin (0,0) directly at the corner of your physical stock workpiece."),
                    ("🔴 <b>Reticle Tracking</b>", "Watch the live laser reticle move across the CAD canvas in real-time as coordinates are polled.")
                ],
                "action_title": "Interactive Playground",
                "action_desc": "Connect to the Virtual GRBL simulator right now to see the reticle and status telemetry activate.",
                "action_btn_text": "⚡ Connect to Virtual Laser Simulator",
                "action_handler": self._action_connect_virtual_simulator
            },
            {
                "id": "framing_burning",
                "sidebar_title": "6. Framing & Burning",
                "badge": "STEP 6 OF 6",
                "title": "Framing, Safety & Starting the Job",
                "icon": "🚀",
                "summary": (
                    "You are now ready to produce laser-crafted projects! Follow this simple 3-step checklist "
                    "every time before cutting:"
                ),
                "details": [
                    ("1️⃣ <b>Frame Bounding Box (`Ctrl+F`)</b>", "Safely traces the rectangular job envelope using a 0.5% visible guide beam so you can verify stock alignment without burning."),
                    ("2️⃣ <b>Contour Frame</b>", "Traces the exact convex perimeter of irregular parts to squeeze designs into odd-shaped offcut scraps."),
                    ("3️⃣ <b>Start Job (`Ctrl+R`)</b>", "Streams G-code with real-time status, line counts, elapsed time, and dynamic speed/power override sliders."),
                    ("🛑 <b>Emergency Stop (`Esc`)</b>", "Instantly halts all motor motion and kills laser power at any time.")
                ],
                "action_title": "Interactive Playground",
                "action_desc": "Load the complete, ready-to-burn Welcome Keychain project file onto the canvas.",
                "action_btn_text": "📂 Load Complete Welcome Project",
                "action_handler": self._action_load_welcome_project
            }
        ]

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # Left Sidebar: Step Navigation
        sidebar_frame = QFrame()
        sidebar_frame.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)

        sidebar_title = QLabel("<b>Tutorial Steps</b>")
        sidebar_title.setStyleSheet("color: #94a3b8; font-size: 11px; text-transform: uppercase;")
        sidebar_layout.addWidget(sidebar_title)

        self.step_list = QListWidget()
        for idx, step in enumerate(self.steps_data):
            item = QListWidgetItem(f"{step['sidebar_title']}")
            self.step_list.addItem(item)
        self.step_list.currentRowChanged.connect(self.show_step)
        sidebar_layout.addWidget(self.step_list)

        # Quick Tip in Sidebar
        tip_box = QGroupBox("💡 Pro Tip")
        tip_layout = QVBoxLayout(tip_box)
        self.lbl_tip = QLabel("You can keep this tutorial window open while interacting with the CAD canvas.")
        self.lbl_tip.setWordWrap(True)
        self.lbl_tip.setStyleSheet("font-size: 11px; color: #94a3b8;")
        tip_layout.addWidget(self.lbl_tip)
        sidebar_layout.addWidget(tip_box)

        main_layout.addWidget(sidebar_frame)

        # Right Content Area
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # Progress bar & Step indicator
        progress_layout = QHBoxLayout()
        self.lbl_step_badge = QLabel("STEP 1 OF 6")
        self.lbl_step_badge.setStyleSheet(
            "background-color: #0369a1; color: #ffffff; font-size: 10px; "
            "font-weight: bold; border-radius: 3px; padding: 2px 6px;"
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(self.steps_data))
        self.progress_bar.setValue(1)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.lbl_step_badge)
        progress_layout.addWidget(self.progress_bar, 1)
        content_layout.addLayout(progress_layout)

        # Step Title
        self.lbl_title = QLabel("Step Title")
        self.lbl_title.setStyleSheet("color: #38bdf8; font-size: 18px; font-weight: bold;")
        content_layout.addWidget(self.lbl_title)

        # Scrollable description area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.scroll_layout.addWidget(self.lbl_summary)

        # Details list container
        self.details_container = QWidget()
        self.details_layout = QVBoxLayout(self.details_container)
        self.details_layout.setContentsMargins(4, 4, 4, 4)
        self.details_layout.setSpacing(8)
        self.scroll_layout.addWidget(self.details_container)

        # Interactive Playground Card
        self.action_box = QGroupBox("Interactive Playground")
        action_layout = QVBoxLayout(self.action_box)
        action_layout.setSpacing(8)
        action_layout.setContentsMargins(12, 14, 12, 12)

        self.lbl_action_desc = QLabel("")
        self.lbl_action_desc.setWordWrap(True)
        self.lbl_action_desc.setStyleSheet("color: #e2e8f0;")
        action_layout.addWidget(self.lbl_action_desc)

        action_btn_layout = QHBoxLayout()
        self.btn_action = QPushButton("Execute Action")
        self.btn_action.setObjectName("btnAction")
        action_btn_layout.addWidget(self.btn_action)
        action_btn_layout.addStretch(1)
        action_layout.addLayout(action_btn_layout)

        self.lbl_action_status = QLabel("")
        self.lbl_action_status.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: bold;")
        self.lbl_action_status.setVisible(False)
        action_layout.addWidget(self.lbl_action_status)

        self.scroll_layout.addWidget(self.action_box)
        self.scroll_layout.addStretch(1)

        scroll.setWidget(scroll_content)
        content_layout.addWidget(scroll, 1)

        # Footer Controls: Startup preference and Navigation Buttons
        footer_layout = QHBoxLayout()
        self.chk_startup = QCheckBox("Show tutorial prompt on startup")
        settings = QSettings("LaserForge", "LaserForge")
        dismissed = settings.value("tutorial_prompt_dismissed", False, type=bool)
        self.chk_startup.setChecked(not dismissed)
        self.chk_startup.toggled.connect(self._on_startup_toggled)
        footer_layout.addWidget(self.chk_startup)

        footer_layout.addStretch(1)

        self.btn_prev = QPushButton("⟵ Back")
        self.btn_prev.setObjectName("btnNav")
        self.btn_prev.clicked.connect(self._on_prev)
        footer_layout.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Next ⟶")
        self.btn_next.setObjectName("btnNav")
        self.btn_next.clicked.connect(self._on_next)
        footer_layout.addWidget(self.btn_next)

        self.btn_finish = QPushButton("Finish Tour 🚀")
        self.btn_finish.setObjectName("btnFinish")
        self.btn_finish.clicked.connect(self.accept)
        footer_layout.addWidget(self.btn_finish)

        content_layout.addLayout(footer_layout)
        main_layout.addWidget(content_frame, 1)

    def show_step(self, index: int):
        if index < 0 or index >= len(self.steps_data):
            return
        self.current_step = index

        # Sync sidebar selection without recursion
        if self.step_list.currentRow() != index:
            self.step_list.setCurrentRow(index)

        step = self.steps_data[index]
        total = len(self.steps_data)

        # Update progress and title
        self.lbl_step_badge.setText(f"STEP {index + 1} OF {total}")
        self.progress_bar.setValue(index + 1)
        self.lbl_title.setText(f"{step['icon']}  {step['title']}")
        self.lbl_summary.setText(f"<p style='font-size:13px; color:#e2e8f0;'>{step['summary']}</p>")

        # Clear and repopulate details
        while self.details_layout.count():
            child = self.details_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for term, explanation in step["details"]:
            row_lbl = QLabel(f"• {term}: <span style='color:#cbd5e1;'>{explanation}</span>")
            row_lbl.setWordWrap(True)
            self.details_layout.addWidget(row_lbl)

        # Update interactive action box
        self.action_box.setTitle(f"Interactive Playground — {step['action_title']}")
        self.lbl_action_desc.setText(step["action_desc"])
        self.btn_action.setText(step["action_btn_text"])
        try:
            self.btn_action.clicked.disconnect()
        except TypeError:
            pass
        self.btn_action.clicked.connect(step["action_handler"])
        self.lbl_action_status.setVisible(False)

        # Update navigation buttons
        self.btn_prev.setEnabled(index > 0)
        is_last = (index == total - 1)
        self.btn_next.setVisible(not is_last)
        self.btn_finish.setVisible(is_last)

    def _on_next(self):
        if self.current_step < len(self.steps_data) - 1:
            self.show_step(self.current_step + 1)

    def _on_prev(self):
        if self.current_step > 0:
            self.show_step(self.current_step - 1)

    def _on_startup_toggled(self, checked: bool):
        settings = QSettings("LaserForge", "LaserForge")
        settings.setValue("tutorial_prompt_dismissed", not checked)

    # ---------------------------------------------------------------------------
    # Interactive Actions Handlers
    # ---------------------------------------------------------------------------

    def _action_highlight_workspace(self):
        """Highlights key docks and focuses the CAD canvas."""
        mw = self.main_window
        if not mw:
            self._show_status("Highlighting only available when main window is active.")
            return

        if hasattr(mw, "cuts_dock") and mw.cuts_dock:
            mw.cuts_dock.raise_()
        if hasattr(mw, "statusBar"):
            mw.statusBar().showMessage("🎯 Workspace Tour: Canvas, Cuts/Layers, and Laser Control panels active!", 4000)
        self._show_status("✅ Workspace active! Observe the central Canvas, right-hand Layers, and lower-right Laser tabs.")

    def _action_place_sample_shapes(self):
        """Places sample badge geometry onto the canvas."""
        mw = self.main_window
        if not mw:
            self._show_status("Canvas placement requires main window.")
            return

        # Create keychain badge outline (Rect on C00)
        badge = RectEntity(
            layer_id=0,
            name="Keychain Outer",
            x=60.0,
            y=60.0,
            width=80.0,
            height=45.0,
            corner_radius=6.0
        )
        # Create lanyard hole (Circle on C00)
        hole = CircleEntity(
            layer_id=0,
            name="Lanyard Hole",
            x=70.0,
            y=82.5,
            radius_x=3.5,
            radius_y=3.5
        )
        # Create engraved text logo (Text on C01)
        logo = TextEntity(
            layer_id=1,
            name="Logo Text",
            x=82.0,
            y=76.0,
            text="LaserForge",
            font_family="Ubuntu",
            font_size=10.0,
            bold=True
        )

        mw.scene.clear_entities()
        mw.scene.add_entity(badge)
        mw.scene.add_entity(hole)
        mw.scene.add_entity(logo)
        mw.canvas_widget.view.zoom_to_fit()
        if hasattr(mw, "statusBar"):
            mw.statusBar().showMessage("Added Tutorial Badge to canvas (C00 Outer & Hole, C01 Logo)", 3000)
        self._show_status("✅ Tutorial badge placed! Notice the outer perimeter and hole on C00, and logo text on C01.")

    def _action_configure_layers(self):
        """Applies cut & engrave parameters to C00 and C01."""
        mw = self.main_window
        if not mw:
            self._show_status("Layer manager requires main window.")
            return

        lm = mw.layer_manager
        # Configure C00 (Black) as Cut line
        c00 = lm.get_layer(0)
        if c00:
            c00.mode = "Line"
            c00.speed = 400.0
            c00.power_max = 90.0
            c00.power_min = 20.0
            c00.passes = 2
            c00.air_assist = True

        # Configure C01 (Blue) as Raster Fill
        c01 = lm.get_layer(1)
        if c01:
            c01.mode = "Fill"
            c01.speed = 3000.0
            c01.power_max = 35.0
            c01.power_min = 12.0
            c01.line_interval = 0.1
            c01.passes = 1
            c01.air_assist = False

        if hasattr(mw, "cuts_panel") and mw.cuts_panel:
            mw.cuts_panel.refresh_table()
        if hasattr(mw, "statusBar"):
            mw.statusBar().showMessage("Configured C00 (Line Cut: 400mm/min @ 90%) and C01 (Raster Fill: 3000mm/min @ 35%)", 4000)
        self._show_status("✅ Layers updated! Look at the Cuts/Layers table: C00 is Line (Cut) and C01 is Fill (Engrave).")

    def _action_preview_simulation(self):
        """Compiles toolpath and opens the 2D simulation dialog."""
        mw = self.main_window
        if not mw:
            self._show_status("Simulation preview requires main window.")
            return

        entities = mw.scene.get_all_entities()
        if not entities:
            self._action_place_sample_shapes()
            entities = mw.scene.get_all_entities()

        try:
            from laserforge.ui.preview_dialog import PreviewDialog
            job = mw.gcode_gen.generate_job(entities)
            dlg = PreviewDialog(job, parent=mw)
            self._show_status("✅ 2D simulation opened! Press Play or drag the scrubber to watch laser motion.")
            dlg.exec()
        except Exception as e:
            self._show_status(f"Preview error: {e}")

    def _action_connect_virtual_simulator(self):
        """Connects serial controller to VIRTUAL_GRBL loopback."""
        mw = self.main_window
        if not mw:
            self._show_status("Serial connection requires main window.")
            return

        try:
            ok = mw.serial_ctrl.connect("VIRTUAL_GRBL", 115200)
            if ok:
                if hasattr(mw, "right_tab_widget"):
                    mw.right_tab_widget.setCurrentIndex(0)  # Switch to Laser tab
                if hasattr(mw, "statusBar"):
                    mw.statusBar().showMessage("Connected to VIRTUAL_GRBL laser simulator!", 3000)
                self._show_status("✅ Connected to VIRTUAL_GRBL! The laser reticle is active on canvas and jog pad is enabled.")
            else:
                self._show_status("Could not initialize virtual simulator.")
        except Exception as e:
            self._show_status(f"Connection error: {e}")

    def _action_load_welcome_project(self):
        """Loads the welcome_laserforge.laserproj project file."""
        mw = self.main_window
        if not mw:
            self._show_status("Project loading requires main window.")
            return

        # Find welcome project path
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "examples", "welcome_laserforge.laserproj"),
            os.path.expanduser("~/LaserForge/examples/welcome_laserforge.laserproj")
        ]
        proj_path = None
        for c in candidates:
            c = os.path.abspath(c)
            if os.path.isfile(c):
                proj_path = c
                break

        if proj_path and os.path.exists(proj_path):
            mw.load_project_file(proj_path)
            self._show_status("✅ Welcome project loaded! You now have a complete, ready-to-burn multi-layer badge.")
        else:
            self._action_place_sample_shapes()
            self._show_status("✅ Tutorial sample shapes loaded on canvas!")

    def _show_status(self, text: str):
        self.lbl_action_status.setText(text)
        self.lbl_action_status.setVisible(True)
