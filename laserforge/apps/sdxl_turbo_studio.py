"""
LaserForge SDXL Turbo Studio - Connected Standalone Generative Application.
Standalone PyQt6 desktop application window for real-time 1-4 step SDXL Turbo generation,
optimized for NVIDIA GPUs with 8GB VRAM (FP16, attention slicing, VAE tiling).
Automatically imports generated images into the active LaserForge workspace canvas.
"""

from typing import Optional, Dict, Any
import os
import sys
import json
import time
from PIL import Image

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QPixmap, QImage, QColor, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QLabel, QPushButton, QComboBox, QTextEdit, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox, QSplitter, QProgressBar,
    QFileDialog, QMessageBox, QFrame, QScrollArea, QSlider, QButtonGroup
)

from laserforge.core.sdxl_turbo_engine import (
    SDXLTurboEngine, SDXLTurboWorker, HAS_TORCH, HAS_DIFFUSERS, HAS_CUDA,
    CUDA_DEVICE_NAME, TOTAL_VRAM_GB
)

IMPORT_QUEUE_DIR = os.path.expanduser("~/.laserforge/imported_queue")
GENERATED_OUTPUT_DIR = os.path.expanduser("~/.laserforge/sdxl_outputs")


class SDXLTurboStudioWindow(QMainWindow):
    """
    Connected standalone desktop UI for SDXL Turbo generative laser art.
    Can be run independently or opened from within LaserForge.
    """
    image_imported = pyqtSignal(str)  # Emitted when an image is sent to workspace
    photo_studio_requested = pyqtSignal(str)  # Emitted to open directly in Photo Studio

    def __init__(self, parent=None, is_embedded: bool = False, initial_image_path: Optional[str] = None):
        super().__init__(parent)
        self.is_embedded = is_embedded
        self.parent_window = parent
        self.setWindowTitle("LaserForge SDXL Turbo Studio - Generative Laser Art & Photo Modification")
        self.resize(1120, 750)
        self.setMinimumSize(920, 620)
        self.setAcceptDrops(True)

        # Engine
        self.engine = SDXLTurboEngine()
        self.current_worker: Optional[SDXLTurboWorker] = None
        self.last_generated_path: Optional[str] = None
        self.input_photo_path: Optional[str] = None
        self.input_photo_image: Optional[Image.Image] = None
        self.is_img2img_mode: bool = False
        self.preview_view_mode: str = "result"  # "result", "input", "split"
        self.last_seed: int = 42

        # Create necessary directories
        os.makedirs(IMPORT_QUEUE_DIR, exist_ok=True)
        os.makedirs(GENERATED_OUTPUT_DIR, exist_ok=True)

        self._init_ui()

        if initial_image_path and os.path.isfile(initial_image_path):
            self.load_input_photo(initial_image_path)

        # VRAM monitor timer
        self.vram_timer = QTimer(self)
        self.vram_timer.setInterval(2000)
        self.vram_timer.timeout.connect(self._refresh_vram_status)
        self.vram_timer.start()
        self._refresh_vram_status()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                ext = os.path.splitext(urls[0].toLocalFile())[1].lower()
                if ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]:
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                fpath = urls[0].toLocalFile()
                ext = os.path.splitext(fpath)[1].lower()
                if ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]:
                    self.load_input_photo(fpath)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # Top Header Bar
        top_bar = QHBoxLayout()
        title_lbl = QLabel("🎨 SDXL Turbo Generative Studio")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #00e5ff;")
        top_bar.addWidget(title_lbl)

        top_bar.addStretch(1)

        # GPU Specs Badge
        vinfo = SDXLTurboEngine.get_vram_info()
        gpu_label = f"🎮 GPU: {vinfo['device_name']} ({vinfo['total_vram_gb']:.1f} GB VRAM)" if vinfo["has_cuda"] else "💻 Mode: CPU / Procedural Fallback"
        self.lbl_gpu_badge = QLabel(gpu_label)
        self.lbl_gpu_badge.setStyleSheet(
            "background-color: #1e1e2d; color: #a5d6a7; padding: 4px 10px; "
            "border-radius: 4px; font-size: 11px; font-weight: bold;"
        )
        top_bar.addWidget(self.lbl_gpu_badge)

        root_layout.addLayout(top_bar)

        # Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---------------------------------------------------------------------
        # Left Panel: Controls
        # ---------------------------------------------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(460)
        scroll.setMinimumWidth(380)

        ctrl_container = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_container)
        ctrl_layout.setSpacing(10)
        ctrl_layout.setContentsMargins(6, 6, 6, 6)

        # Mode Selection (Text2Img vs Img2Img)
        mode_grp = QGroupBox("Studio Mode")
        mode_l = QHBoxLayout(mode_grp)
        mode_l.setContentsMargins(4, 4, 4, 4)
        mode_l.setSpacing(6)

        self.btn_mode_t2i = QPushButton("✍️ Create New (Text2Img)")
        self.btn_mode_t2i.setCheckable(True)
        self.btn_mode_t2i.setChecked(True)
        self.btn_mode_t2i.setStyleSheet(
            "QPushButton { padding: 6px; font-weight: bold; border-radius: 4px; } "
            "QPushButton:checked { background-color: #00838f; color: white; }"
        )

        self.btn_mode_i2i = QPushButton("🖼️ Modify Photo (Img2Img)")
        self.btn_mode_i2i.setCheckable(True)
        self.btn_mode_i2i.setChecked(False)
        self.btn_mode_i2i.setStyleSheet(
            "QPushButton { padding: 6px; font-weight: bold; border-radius: 4px; } "
            "QPushButton:checked { background-color: #d81b60; color: white; }"
        )

        self.mode_btn_grp = QButtonGroup(self)
        self.mode_btn_grp.addButton(self.btn_mode_t2i)
        self.mode_btn_grp.addButton(self.btn_mode_i2i)

        self.btn_mode_t2i.clicked.connect(lambda: self._set_mode(False))
        self.btn_mode_i2i.clicked.connect(lambda: self._set_mode(True))

        mode_l.addWidget(self.btn_mode_t2i)
        mode_l.addWidget(self.btn_mode_i2i)
        ctrl_layout.addWidget(mode_grp)

        # Source Photo Input Group (Visible in Img2Img Mode)
        self.photo_grp = QGroupBox("📷 Source Photo to Modify")
        p_in_layout = QVBoxLayout(self.photo_grp)
        p_in_layout.setSpacing(8)

        thumb_row = QHBoxLayout()
        self.lbl_photo_thumb = QLabel("Drop Photo Here\nor Click 'Browse'")
        self.lbl_photo_thumb.setFixedSize(110, 110)
        self.lbl_photo_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_photo_thumb.setStyleSheet(
            "border: 2px dashed #00bcd4; border-radius: 6px; background-color: #1e1e24; color: #80deea; font-size: 11px;"
        )
        thumb_row.addWidget(self.lbl_photo_thumb)

        info_col = QVBoxLayout()
        self.lbl_photo_name = QLabel("No photo loaded.")
        self.lbl_photo_name.setStyleSheet("font-weight: bold; color: #eceff1;")
        self.lbl_photo_dims = QLabel("Drop or select a photo to modify")
        self.lbl_photo_dims.setStyleSheet("color: #90a4ae; font-size: 11px;")
        info_col.addWidget(self.lbl_photo_name)
        info_col.addWidget(self.lbl_photo_dims)

        b_row1 = QHBoxLayout()
        self.btn_choose_photo = QPushButton("📁 Browse...")
        self.btn_choose_photo.clicked.connect(self._on_choose_photo)
        self.btn_paste_photo = QPushButton("📋 Paste Clipboard")
        self.btn_paste_photo.clicked.connect(self._on_paste_photo)
        b_row1.addWidget(self.btn_choose_photo)
        b_row1.addWidget(self.btn_paste_photo)
        info_col.addLayout(b_row1)

        b_row2 = QHBoxLayout()
        self.btn_from_canvas = QPushButton("🎯 From Canvas")
        self.btn_from_canvas.setToolTip("Use active image from LaserForge workspace")
        self.btn_from_canvas.clicked.connect(self._on_load_from_canvas)
        self.btn_clear_photo = QPushButton("❌ Clear")
        self.btn_clear_photo.clicked.connect(self._on_clear_photo)
        b_row2.addWidget(self.btn_from_canvas)
        b_row2.addWidget(self.btn_clear_photo)
        info_col.addLayout(b_row2)

        thumb_row.addLayout(info_col)
        p_in_layout.addLayout(thumb_row)

        # Transformation Strength Slider & SpinBox
        str_grid = QGridLayout()
        str_grid.addWidget(QLabel("Modification Strength:"), 0, 0)

        str_controls = QHBoxLayout()
        self.slider_strength = QSlider(Qt.Orientation.Horizontal)
        self.slider_strength.setRange(10, 95)
        self.slider_strength.setValue(65)

        self.spin_strength = QDoubleSpinBox()
        self.spin_strength.setRange(0.10, 0.95)
        self.spin_strength.setSingleStep(0.05)
        self.spin_strength.setValue(0.65)
        self.spin_strength.setSuffix(" (65%)")
        self.spin_strength.setFixedWidth(90)

        def _on_slider(val):
            self.spin_strength.blockSignals(True)
            self.spin_strength.setValue(val / 100.0)
            self.spin_strength.setSuffix(f" ({val}%)")
            self.spin_strength.blockSignals(False)
            self._update_strength_desc(val / 100.0)

        def _on_spin(val):
            self.slider_strength.blockSignals(True)
            self.slider_strength.setValue(int(round(val * 100)))
            self.spin_strength.setSuffix(f" ({int(round(val * 100))}%)")
            self.slider_strength.blockSignals(False)
            self._update_strength_desc(val)

        self.slider_strength.valueChanged.connect(_on_slider)
        self.spin_strength.valueChanged.connect(_on_spin)

        str_controls.addWidget(self.slider_strength, 1)
        str_controls.addWidget(self.spin_strength)
        str_grid.addLayout(str_controls, 0, 1)
        p_in_layout.addLayout(str_grid)

        self.lbl_strength_desc = QLabel("Balanced (0.65): Keeps subject recognizable while applying prompt modifications")
        self.lbl_strength_desc.setStyleSheet("color: #80cbc4; font-size: 11px; font-style: italic;")
        p_in_layout.addWidget(self.lbl_strength_desc)

        self.photo_grp.setVisible(False)
        ctrl_layout.addWidget(self.photo_grp)

        # 1. Prompt Group
        prompt_grp = QGroupBox("Prompt Engineering")
        p_layout = QVBoxLayout(prompt_grp)

        self.lbl_prompt_title = QLabel("Prompt (Subject & Elements):")
        p_layout.addWidget(self.lbl_prompt_title)
        self.txt_prompt = QTextEdit()
        self.txt_prompt.setPlaceholderText(
            "e.g. Intricate roaring tiger medallion, sacred geometric patterns, ornate floral filigree..."
        )
        self.txt_prompt.setText("Intricate soaring eagle emblem, geometric sunburst, majestic wings")
        self.txt_prompt.setMaximumHeight(75)
        p_layout.addWidget(self.txt_prompt)

        p_layout.addWidget(QLabel("Laser Style Preset:"))
        self.combo_style = QComboBox()
        for preset_name in SDXLTurboEngine.STYLE_PRESETS.keys():
            self.combo_style.addItem(preset_name)
        p_layout.addWidget(self.combo_style)

        p_layout.addWidget(QLabel("Negative Prompt (Exclude):"))
        self.txt_neg_prompt = QLineEdit(SDXLTurboEngine.DEFAULT_NEGATIVE_PROMPT)
        p_layout.addWidget(self.txt_neg_prompt)

        ctrl_layout.addWidget(prompt_grp)

        # 2. Performance & 8GB VRAM Optimizations
        vram_grp = QGroupBox("8GB VRAM & Turbo Inference Settings")
        v_layout = QGridLayout(vram_grp)
        v_layout.setSpacing(6)

        v_layout.addWidget(QLabel("Inference Steps:"), 0, 0)
        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(1, 4)
        self.spin_steps.setValue(1)  # Real-time 1-step Turbo
        self.spin_steps.setSuffix(" step(s) [Turbo]")
        v_layout.addWidget(self.spin_steps, 0, 1)

        v_layout.addWidget(QLabel("Guidance Scale:"), 1, 0)
        self.spin_cfg = QDoubleSpinBox()
        self.spin_cfg.setRange(0.0, 3.0)
        self.spin_cfg.setSingleStep(0.2)
        self.spin_cfg.setValue(0.0)  # 0.0 is native Turbo
        v_layout.addWidget(self.spin_cfg, 1, 1)

        v_layout.addWidget(QLabel("Resolution:"), 2, 0)
        self.combo_res = QComboBox()
        self.combo_res.addItem("512 × 512 px (Fastest / Lowest VRAM)", (512, 512))
        self.combo_res.addItem("640 × 640 px (Medium Detail)", (640, 640))
        self.combo_res.addItem("768 × 768 px (High Detail - VAE Tiled)", (768, 768))
        v_layout.addWidget(self.combo_res, 2, 1)

        v_layout.addWidget(QLabel("Seed:"), 3, 0)
        seed_row = QHBoxLayout()
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(-1, 2147483647)
        self.spin_seed.setValue(-1)
        self.spin_seed.setSpecialValueText("-1 (Random)")
        btn_rand_seed = QPushButton("🎲")
        btn_rand_seed.setFixedWidth(30)
        btn_rand_seed.clicked.connect(lambda: self.spin_seed.setValue(-1))
        seed_row.addWidget(self.spin_seed, 1)
        seed_row.addWidget(btn_rand_seed)
        v_layout.addLayout(seed_row, 3, 1)

        # VRAM Utilization Bar
        v_layout.addWidget(QLabel("VRAM Footprint:"), 4, 0)
        self.prog_vram = QProgressBar()
        self.prog_vram.setRange(0, 100)
        self.prog_vram.setValue(15)
        self.prog_vram.setFormat("%v% VRAM")
        v_layout.addWidget(self.prog_vram, 4, 1)

        ctrl_layout.addWidget(vram_grp)

        # 3. Execution & Workflow Actions
        act_grp = QGroupBox("Generation & Automated Workspace Import")
        act_layout = QVBoxLayout(act_grp)

        self.chk_auto_import = QCheckBox("⚡ Automatically Import into LaserForge Workspace")
        self.chk_auto_import.setChecked(True)
        self.chk_auto_import.setStyleSheet("font-weight: bold; color: #00e5ff;")
        self.chk_auto_import.setToolTip("Places the generated artwork directly onto the LaserForge canvas upon completion")
        act_layout.addWidget(self.chk_auto_import)

        self.chk_auto_open_studio = QCheckBox("📷 Auto-Open in Photo Engrave Studio")
        self.chk_auto_open_studio.setChecked(False)
        self.chk_auto_open_studio.setToolTip("Automatically launches Photo Studio to dither/halftone the generated image")
        act_layout.addWidget(self.chk_auto_open_studio)

        # Big Generate Button
        self.btn_generate = QPushButton("✨  Generate Artwork (⚡ Turbo)")
        self.btn_generate.setStyleSheet(
            "background-color: #00838f; color: white; font-weight: bold; "
            "font-size: 13px; padding: 10px; border-radius: 4px;"
        )
        self.btn_generate.clicked.connect(self._on_generate_clicked)
        act_layout.addWidget(self.btn_generate)

        # Progress bar
        self.prog_gen = QProgressBar()
        self.prog_gen.setRange(0, 100)
        self.prog_gen.setValue(0)
        self.prog_gen.setTextVisible(True)
        act_layout.addWidget(self.prog_gen)

        self.lbl_status = QLabel("Ready for prompt input.")
        self.lbl_status.setStyleSheet("color: #b0bec5; font-size: 11px;")
        act_layout.addWidget(self.lbl_status)

        ctrl_layout.addWidget(act_grp)
        ctrl_layout.addStretch(1)

        scroll.setWidget(ctrl_container)
        splitter.addWidget(scroll)

        # ---------------------------------------------------------------------
        # Right Panel: Interactive Visual Preview & Actions
        # ---------------------------------------------------------------------
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Comparison View Mode Bar
        self.preview_mode_bar = QWidget()
        mode_bar_layout = QHBoxLayout(self.preview_mode_bar)
        mode_bar_layout.setContentsMargins(0, 0, 0, 0)
        mode_bar_layout.setSpacing(6)

        self.btn_view_result = QPushButton("🖼️ Modified Result")
        self.btn_view_result.setCheckable(True)
        self.btn_view_result.setChecked(True)
        self.btn_view_result.setStyleSheet(
            "QPushButton:checked { background-color: #00838f; color: white; font-weight: bold; }"
        )

        self.btn_view_input = QPushButton("📷 Original Photo")
        self.btn_view_input.setCheckable(True)
        self.btn_view_input.setStyleSheet(
            "QPushButton:checked { background-color: #00838f; color: white; font-weight: bold; }"
        )

        self.btn_view_split = QPushButton("🌓 Side-by-Side")
        self.btn_view_split.setCheckable(True)
        self.btn_view_split.setStyleSheet(
            "QPushButton:checked { background-color: #00838f; color: white; font-weight: bold; }"
        )

        self.view_grp = QButtonGroup(self)
        self.view_grp.addButton(self.btn_view_result)
        self.view_grp.addButton(self.btn_view_input)
        self.view_grp.addButton(self.btn_view_split)

        self.btn_view_result.clicked.connect(lambda: self._set_preview_view("result"))
        self.btn_view_input.clicked.connect(lambda: self._set_preview_view("input"))
        self.btn_view_split.clicked.connect(lambda: self._set_preview_view("split"))

        mode_bar_layout.addWidget(self.btn_view_result)
        mode_bar_layout.addWidget(self.btn_view_input)
        mode_bar_layout.addWidget(self.btn_view_split)
        mode_bar_layout.addStretch(1)

        self.btn_use_as_input = QPushButton("🔁 Use Result as Next Input")
        self.btn_use_as_input.setStyleSheet("background-color: #37474f; color: #eceff1; font-weight: bold;")
        self.btn_use_as_input.setToolTip("Sets the generated artwork as the source photo for another iteration of modifications")
        self.btn_use_as_input.clicked.connect(self._on_use_result_as_input)
        self.btn_use_as_input.setEnabled(False)
        mode_bar_layout.addWidget(self.btn_use_as_input)

        right_layout.addWidget(self.preview_mode_bar)

        # Preview display
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("background-color: #121216; border-radius: 4px;")
        self.lbl_preview.setText("Enter a prompt and click 'Generate Artwork'")
        right_layout.addWidget(self.lbl_preview, 1)

        # Artwork Metadata Bar
        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet("color: #00e5ff; font-family: monospace; font-size: 11px; padding: 2px;")
        self.lbl_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.lbl_meta)

        # Bottom Actions Bar
        bottom_actions = QHBoxLayout()
        bottom_actions.setSpacing(8)

        self.btn_send_workspace = QPushButton("📥 Send to Canvas")
        self.btn_send_workspace.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 12px;")
        self.btn_send_workspace.setToolTip("Add current image to LaserForge canvas workpiece")
        self.btn_send_workspace.clicked.connect(self._on_send_to_workspace)
        bottom_actions.addWidget(self.btn_send_workspace)

        self.btn_send_studio = QPushButton("📷 Send to Photo Studio...")
        self.btn_send_studio.setStyleSheet("background-color: #6a1b9a; color: white; font-weight: bold; padding: 6px 12px;")
        self.btn_send_studio.setToolTip("Send to Photo Engrave Studio for dithering, contrast and wood burn simulation")
        self.btn_send_studio.clicked.connect(self._on_send_to_photo_studio)
        bottom_actions.addWidget(self.btn_send_studio)

        bottom_actions.addStretch(1)

        btn_save = QPushButton("💾 Save Image As...")
        btn_save.clicked.connect(self._on_save_as)
        bottom_actions.addWidget(btn_save)

        right_layout.addLayout(bottom_actions)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        root_layout.addWidget(splitter, 1)

    # -------------------------------------------------------------------------
    # Logic & Handlers
    # -------------------------------------------------------------------------

    def _set_mode(self, is_img2img: bool):
        """Switches between Text2Img and Img2Img modes."""
        self.is_img2img_mode = is_img2img
        self.btn_mode_t2i.setChecked(not is_img2img)
        self.btn_mode_i2i.setChecked(is_img2img)
        self.photo_grp.setVisible(is_img2img)
        if is_img2img:
            self.lbl_prompt_title.setText("Modification Prompt (How to restyle photo):")
            self.txt_prompt.setPlaceholderText(
                "e.g. Detailed woodcut relief engraving, crisp laser lines, intricate hatching..."
            )
            self.btn_generate.setText("✨  Modify Photo with AI (⚡ Turbo)")
            self.btn_generate.setStyleSheet(
                "background-color: #ad1457; color: white; font-weight: bold; "
                "font-size: 13px; padding: 10px; border-radius: 4px;"
            )
        else:
            self.lbl_prompt_title.setText("Prompt (Subject & Elements):")
            self.txt_prompt.setPlaceholderText(
                "e.g. Intricate soaring eagle emblem, geometric sunburst, majestic wings..."
            )
            self.btn_generate.setText("✨  Generate Artwork (⚡ Turbo)")
            self.btn_generate.setStyleSheet(
                "background-color: #00838f; color: white; font-weight: bold; "
                "font-size: 13px; padding: 10px; border-radius: 4px;"
            )
        self._display_current_preview()

    def _update_strength_desc(self, val: float):
        """Updates guidance text for the transformation strength setting."""
        if val < 0.35:
            badge = f"Subtle ({val:.2f}): Preserves original photo structure with light artistic stylization"
        elif val <= 0.70:
            badge = f"Balanced ({val:.2f}): Keeps subject recognizable while applying rich prompt modifications"
        else:
            badge = f"Creative ({val:.2f}): Heavy transformation; loosely guided by photo composition"
        self.lbl_strength_desc.setText(badge)

    def load_input_photo(self, filepath: str):
        """Loads a source photo for img2img modification and updates UI."""
        if not filepath or not os.path.exists(filepath):
            return
        try:
            with Image.open(filepath) as im:
                img = im.copy()
            self.input_photo_path = filepath
            self.input_photo_image = img

            # Update thumbnail
            pix = QPixmap(filepath)
            if not pix.isNull():
                thumb = pix.scaled(106, 106, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.lbl_photo_thumb.setPixmap(thumb)

            # Update labels
            basename = os.path.basename(filepath)
            display_name = (basename[:12] + "..." + basename[-9:]) if len(basename) > 24 else basename
            self.lbl_photo_name.setText(display_name)
            self.lbl_photo_dims.setText(f"{img.width} × {img.height} px ({img.format or 'IMG'})")

            # Switch mode to Img2Img
            self._set_mode(True)
            self.lbl_status.setText(f"Loaded source photo: {os.path.basename(filepath)}")

            if not self.last_generated_path:
                self._set_preview_view("input")
            else:
                self._display_current_preview()
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Could not load image:\n{e}")

    def _on_choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Source Photo to Modify", "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tiff);;All Files (*)"
        )
        if path:
            self.load_input_photo(path)

    def _on_paste_photo(self):
        clipboard = QApplication.clipboard()
        qimg = clipboard.image()
        if not qimg.isNull():
            dest = os.path.join(GENERATED_OUTPUT_DIR, f"clipboard_input_{int(time.time())}.png")
            qimg.save(dest, "PNG")
            self.load_input_photo(dest)
            return

        mime = clipboard.mimeData()
        if mime and mime.hasUrls():
            urls = mime.urls()
            if urls and urls[0].isLocalFile():
                fpath = urls[0].toLocalFile()
                if os.path.isfile(fpath):
                    self.load_input_photo(fpath)
                    return

        QMessageBox.information(self, "Paste Clipboard", "No image found in clipboard.\nCopy an image or screenshot first, then click Paste.")

    def _on_load_from_canvas(self):
        if self.parent_window and hasattr(self.parent_window, "scene"):
            selected = self.parent_window.scene.get_selected_entities()
            img_ents = [e for e in selected if hasattr(e, "image_path") or hasattr(e, "raw_image_path")]
            if img_ents:
                src = getattr(img_ents[0], "raw_image_path", None) or getattr(img_ents[0], "image_path", None)
                if src and os.path.isfile(src):
                    self.load_input_photo(src)
                    return
        QMessageBox.information(
            self, "From Canvas",
            "Select an image on the LaserForge canvas and right-click -> '🎨 Modify Photo with AI',\n"
            "or drag & drop the photo file directly onto this window."
        )

    def _on_clear_photo(self):
        self.input_photo_path = None
        self.input_photo_image = None
        self.lbl_photo_thumb.clear()
        self.lbl_photo_thumb.setText("Drop Photo Here\nor Click 'Browse'")
        self.lbl_photo_name.setText("No photo loaded.")
        self.lbl_photo_dims.setText("Drop or select a photo to modify")
        self._set_preview_view("result")

    def _on_use_result_as_input(self):
        if self.last_generated_path and os.path.exists(self.last_generated_path):
            self.load_input_photo(self.last_generated_path)
            self.lbl_status.setText("✓ Set generated artwork as new source photo for iterative restyling!")

    def _set_preview_view(self, mode: str):
        self.preview_view_mode = mode
        self.btn_view_result.setChecked(mode == "result")
        self.btn_view_input.setChecked(mode == "input")
        self.btn_view_split.setChecked(mode == "split")
        self._display_current_preview()

    def _display_current_preview(self):
        if self.preview_view_mode == "result":
            if self.last_generated_path and os.path.exists(self.last_generated_path):
                self._display_image(self.last_generated_path)
            elif self.input_photo_path and os.path.exists(self.input_photo_path):
                self.lbl_preview.setText("Source photo loaded.\nClick '✨ Modify Photo with AI' to generate restyled artwork.")
            else:
                self.lbl_preview.setText("Enter a prompt and click 'Generate Artwork'")
        elif self.preview_view_mode == "input":
            if self.input_photo_path and os.path.exists(self.input_photo_path):
                self._display_image(self.input_photo_path)
            else:
                self.lbl_preview.setText("No source photo loaded.\nDrop or browse an image.")
        elif self.preview_view_mode == "split":
            if self.input_photo_path and self.last_generated_path and os.path.exists(self.input_photo_path) and os.path.exists(self.last_generated_path):
                self._display_split_preview(self.input_photo_path, self.last_generated_path)
            elif self.last_generated_path and os.path.exists(self.last_generated_path):
                self._display_image(self.last_generated_path)
            elif self.input_photo_path and os.path.exists(self.input_photo_path):
                self._display_image(self.input_photo_path)
            else:
                self.lbl_preview.setText("Side-by-Side comparison requires both a source photo and a generated result.")

    def _display_split_preview(self, input_path: str, result_path: str):
        if not os.path.exists(input_path) or not os.path.exists(result_path):
            return
        try:
            with Image.open(input_path) as im_in:
                img_in = im_in.convert("RGB")
            with Image.open(result_path) as im_res:
                img_res = im_res.convert("RGB")

            h = 512
            w_in = max(64, int(img_in.width * (h / max(1, img_in.height))))
            w_res = max(64, int(img_res.width * (h / max(1, img_res.height))))

            in_resized = img_in.resize((w_in, h), Image.Resampling.LANCZOS)
            res_resized = img_res.resize((w_res, h), Image.Resampling.LANCZOS)

            combined_w = w_in + w_res + 8
            combined = Image.new("RGB", (combined_w, h), (20, 20, 24))
            combined.paste(in_resized, (0, 0))
            combined.paste(res_resized, (w_in + 8, 0))

            import io
            bio = io.BytesIO()
            combined.save(bio, format="PNG")
            bio.seek(0)
            qimg = QImage()
            qimg.loadFromData(bio.getvalue())
            pix = QPixmap.fromImage(qimg)

            # Draw labels on the pixmap
            painter = QPainter(pix)
            painter.setPen(QColor("#00e5ff"))
            painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            painter.fillRect(10, 10, 130, 28, QColor(0, 0, 0, 180))
            painter.drawText(16, 29, "📷 ORIGINAL")

            painter.setPen(QColor("#ff4081"))
            painter.fillRect(w_in + 18, 10, 140, 28, QColor(0, 0, 0, 180))
            painter.drawText(w_in + 24, 29, "✨ MODIFIED AI")
            painter.end()

            max_w = max(400, self.lbl_preview.width() or 640)
            max_h = max(400, self.lbl_preview.height() or 512)
            scaled = pix.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.lbl_preview.setPixmap(scaled)
        except Exception as e:
            print(f"Error rendering split preview: {e}")

    def _refresh_vram_status(self):
        info = SDXLTurboEngine.get_vram_info()
        if info["has_cuda"] and info["total_vram_gb"] > 0:
            total_mb = info["total_vram_gb"] * 1024.0
            alloc_mb = info["allocated_vram_mb"]
            pct = int((alloc_mb / total_mb) * 100.0) if total_mb > 0 else 0
            self.prog_vram.setValue(pct)
            if alloc_mb > 0:
                self.prog_vram.setFormat(f"{alloc_mb:.0f} MB / {info['total_vram_gb']:.1f} GB ({pct}%)")
            else:
                self.prog_vram.setFormat(f"8GB VRAM Optimized ({info['device_name'][:20]})")
        else:
            self.prog_vram.setValue(0)
            self.prog_vram.setFormat("N/A (CPU Mode)")

    def _on_generate_clicked(self):
        prompt = self.txt_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "No Prompt", "Please enter a prompt to describe the artwork.")
            return

        if self.is_img2img_mode:
            if not self.input_photo_path or not os.path.exists(self.input_photo_path):
                QMessageBox.warning(self, "No Source Photo", "Please choose, paste, or drop a photo to modify.")
                return
            init_img_path = self.input_photo_path
            strength_val = self.spin_strength.value()
        else:
            init_img_path = None
            strength_val = 0.65

        self.btn_generate.setEnabled(False)
        self.prog_gen.setValue(10)
        self.lbl_status.setText("Initializing SDXL Turbo engine...")

        w, h = self.combo_res.currentData() or (512, 512)
        seed_val = self.spin_seed.value()
        if seed_val == -1:
            import random
            seed_val = random.randint(0, 2**31 - 1)
        self.last_seed = seed_val

        self.current_worker = SDXLTurboWorker(
            engine=self.engine,
            prompt=prompt,
            negative_prompt=self.txt_neg_prompt.text(),
            style_preset=self.combo_style.currentText(),
            steps=self.spin_steps.value(),
            guidance_scale=self.spin_cfg.value(),
            width=w,
            height=h,
            seed=seed_val,
            output_dir=GENERATED_OUTPUT_DIR,
            init_image_path=init_img_path,
            strength=strength_val,
        )
        self.current_worker.progress_updated.connect(self._on_worker_progress)
        self.current_worker.image_ready.connect(self._on_image_ready)
        self.current_worker.failed.connect(self._on_worker_failed)
        self.current_worker.start()

    def _on_worker_progress(self, pct: int, msg: str):
        self.prog_gen.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_image_ready(self, filepath: str):
        self.btn_generate.setEnabled(True)
        self.last_generated_path = filepath
        self.btn_use_as_input.setEnabled(True)
        self._set_preview_view("result")

        w, h = self.combo_res.currentData() or (512, 512)
        steps = self.spin_steps.value()
        mode_str = f"Img2Img (Str: {self.spin_strength.value():.2f})" if self.is_img2img_mode else "Text2Img"
        self.lbl_meta.setText(f"Mode: {mode_str}  |  Res: {w} × {h} px  |  Steps: {steps}  |  Seed: {self.last_seed}")

        # Automated import handling
        if self.chk_auto_import.isChecked():
            self._dispatch_import_to_workspace(filepath)

        if self.chk_auto_open_studio.isChecked():
            self._on_send_to_photo_studio()

    def _on_worker_failed(self, error_msg: str):
        self.btn_generate.setEnabled(True)
        self.prog_gen.setValue(0)
        self.lbl_status.setText(f"Generation error: {error_msg}")
        QMessageBox.critical(self, "Generation Error", f"Failed to generate artwork:\n{error_msg}")

    def _display_image(self, filepath: str):
        if not os.path.exists(filepath):
            return
        pix = QPixmap(filepath)
        if not pix.isNull():
            target_w = min(700, max(400, self.lbl_preview.width() or 512))
            target_h = min(700, max(400, self.lbl_preview.height() or 512))
            scaled = pix.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.lbl_preview.setPixmap(scaled)

    def _dispatch_import_to_workspace(self, image_path: str):
        """Sends the image to the active LaserForge workspace via signal or mailbox."""
        self.lbl_status.setText("✓ Imported into LaserForge workspace canvas!")

        # 1. Direct signal for connected mode
        self.image_imported.emit(image_path)

        # 2. File-based mailbox IPC for standalone mode
        try:
            ts = int(time.time() * 1000)
            meta_path = os.path.join(IMPORT_QUEUE_DIR, f"import_{ts}.json")
            with open(meta_path, "w") as f:
                json.dump({
                    "image_path": image_path,
                    "prompt": self.txt_prompt.toPlainText().strip(),
                    "seed": self.last_seed,
                    "timestamp": ts,
                    "open_photo_studio": self.chk_auto_open_studio.isChecked()
                }, f)
        except Exception as e:
            print(f"Error dispatching import file: {e}")

    def _on_send_to_workspace(self):
        if not self.last_generated_path:
            QMessageBox.warning(self, "No Image", "Please generate an image first.")
            return
        self._dispatch_import_to_workspace(self.last_generated_path)
        QMessageBox.information(self, "Imported", "Photo placed onto active LaserForge workspace canvas.")

    def _on_send_to_photo_studio(self):
        if not self.last_generated_path:
            QMessageBox.warning(self, "No Image", "Please generate an image first.")
            return
        self.photo_studio_requested.emit(self.last_generated_path)

    def _on_save_as(self):
        if not self.last_generated_path:
            QMessageBox.warning(self, "No Image", "Please generate an image first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Generated Laser Artwork", "sdxl_laser_art.png",
            "PNG Image (*.png);;JPEG Image (*.jpg);;All Files (*)"
        )
        if path:
            try:
                with Image.open(self.last_generated_path) as img:
                    img.save(path)
                QMessageBox.information(self, "Saved", f"Image successfully saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save file: {e}")


def main():
    """Standalone entry point when run as a standalone application."""
    import argparse
    parser = argparse.ArgumentParser(description="LaserForge SDXL Turbo Generative & Photo Modification Studio")
    parser.add_argument("--input-image", type=str, default=None, help="Initial photo to load for modification")
    args, _ = parser.parse_known_args()

    try:
        import torch
        has_cuda = torch.cuda.is_available()
    except ImportError:
        has_cuda = False

    pyenv_python = os.path.expanduser("~/.pyenv/versions/3.10.13/bin/python")
    if not has_cuda and os.path.isfile(pyenv_python) and os.access(pyenv_python, os.X_OK) and sys.executable != pyenv_python:
        if os.environ.get("SDXL_STUDIO_GPU_EXEC") != "1":
            os.environ["SDXL_STUDIO_GPU_EXEC"] = "1"
            os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
            os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
            os.execv(pyenv_python, [pyenv_python] + sys.argv)

    app = QApplication(sys.argv)
    window = SDXLTurboStudioWindow(initial_image_path=args.input_image)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

