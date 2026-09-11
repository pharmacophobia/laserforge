"""
LaserForge Photo Engrave Studio Dialog.
Specialized interactive photograph conversion and preparation studio for diode lasers.
Features live side-by-side material simulation preview, Jarvis/Stucki/Halftone screening,
CLAHE adaptive equalization, unsharp masking, gamma curves, and material presets.
"""

import os
import time
import tempfile
from typing import Optional, Dict, Any, Tuple
import numpy as np
from PIL import Image

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon, QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSlider, QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QFileDialog, QMessageBox, QTabWidget, QWidget, QSplitter, QScrollArea,
    QFrame
)

from laserforge.core.raster_processor import RasterProcessor
from laserforge.core.models import ImageEntity
from laserforge.ui.crop_image_dialog import CropImageDialog


class PhotoEngraveDialog(QDialog):
    """
    Dedicated studio dialog for photographic laser engraving preparation.
    """
    photo_applied = pyqtSignal(dict)  # Returns dict of parameters to update or create ImageEntity

    def __init__(
        self,
        parent=None,
        image_entity: Optional[ImageEntity] = None,
        initial_image_path: str = "",
        bed_width: float = 150.0,
        bed_height: float = 200.0
    ):
        super().__init__(parent)
        self.setWindowTitle("LaserForge Photo Engrave Studio - Diode Laser Image Preparation")
        self.resize(1100, 720)
        self.setMinimumSize(850, 580)

        self.bed_width = bed_width
        self.bed_height = bed_height
        self.image_entity = image_entity
        self.raw_image_path = getattr(image_entity, "raw_image_path", "") or (image_entity.image_path if image_entity else initial_image_path)
        if self.raw_image_path and os.path.exists(self.raw_image_path):
            self.image_path = self.raw_image_path
        else:
            self.image_path = initial_image_path or (image_entity.image_path if image_entity else "")
        self.original_pil_img: Optional[Image.Image] = None
        self._original_uncropped_img: Optional[Image.Image] = None
        self.current_processed_arr: Optional[np.ndarray] = None
        self.current_preview_img: Optional[Image.Image] = None

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._reprocess_and_render)

        self._init_ui()

        if self.image_path and os.path.exists(self.image_path):
            self._load_image(self.image_path)
        else:
            self._set_placeholder_state()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header Bar
        top_bar = QHBoxLayout()
        btn_open = QPushButton("📂 Open Photo File...")
        btn_open.setStyleSheet("padding: 6px 12px; font-weight: bold;")
        btn_open.clicked.connect(self._on_browse_file)
        top_bar.addWidget(btn_open)

        btn_crop = QPushButton("✂️ Crop Photo...")
        btn_crop.setToolTip("Interactively crop workpiece to focus area or standard aspect ratio")
        btn_crop.setStyleSheet("padding: 6px 12px; font-weight: bold; background-color: #37474f; color: white;")
        btn_crop.clicked.connect(self._on_open_crop)
        top_bar.addWidget(btn_crop)

        btn_reset_crop = QPushButton("🔄 Reset Crop")
        btn_reset_crop.setToolTip("Restore full uncropped photograph")
        btn_reset_crop.clicked.connect(self._on_reset_crop)
        top_bar.addWidget(btn_reset_crop)

        self.lbl_filename = QLabel("No photo loaded" if not self.image_path else os.path.basename(self.image_path))
        self.lbl_filename.setStyleSheet("color: #80d8ff; font-weight: bold; font-size: 13px; padding-left: 6px;")
        top_bar.addWidget(self.lbl_filename)

        top_bar.addStretch(1)

        btn_export = QPushButton("💾 Export Processed Bitmap...")
        btn_export.setToolTip("Export the high-resolution prepared 1-bit or grayscale image")
        btn_export.clicked.connect(self._on_export_processed)
        top_bar.addWidget(btn_export)

        main_layout.addLayout(top_bar)

        # Splitter: Controls Left, Previews Right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left Panel: Scrollable Controls ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(360)
        scroll_area.setMaximumWidth(440)

        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setSpacing(10)
        ctrl_layout.setContentsMargins(8, 8, 8, 8)

        # 1. Material Presets Group
        preset_grp = QGroupBox("Material & Diode Laser Optimization")
        preset_layout = QVBoxLayout(preset_grp)
        preset_lbl = QLabel("1-Click Material Preset:")
        preset_lbl.setStyleSheet("color: #b0bec5; font-size: 11px;")
        preset_layout.addWidget(preset_lbl)

        self.combo_presets = QComboBox()
        self.combo_presets.addItem("Custom", None)
        for name in RasterProcessor.MATERIAL_PRESETS.keys():
            self.combo_presets.addItem(name, name)
        self.combo_presets.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.combo_presets)
        ctrl_layout.addWidget(preset_grp)

        # 2. Dimensions & Resolution
        dim_grp = QGroupBox("Workpiece Size & Resolution")
        dim_grid = QGridLayout(dim_grp)
        dim_grid.setSpacing(6)

        dim_grid.addWidget(QLabel("Width (mm):"), 0, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(5.0, self.bed_width)
        self.spin_width.setValue(80.0 if not self.image_entity else self.image_entity.width)
        self.spin_width.setSingleStep(1.0)
        self.spin_width.setSuffix(" mm")
        self.spin_width.valueChanged.connect(self._on_width_changed)
        dim_grid.addWidget(self.spin_width, 0, 1)

        dim_grid.addWidget(QLabel("Height (mm):"), 1, 0)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(5.0, self.bed_height)
        self.spin_height.setValue(80.0 if not self.image_entity else self.image_entity.height)
        self.spin_height.setSingleStep(1.0)
        self.spin_height.setSuffix(" mm")
        self.spin_height.valueChanged.connect(self._on_height_changed)
        dim_grid.addWidget(self.spin_height, 1, 1)

        self.chk_lock_aspect = QCheckBox("Lock Aspect Ratio")
        self.chk_lock_aspect.setChecked(True)
        dim_grid.addWidget(self.chk_lock_aspect, 2, 0, 1, 2)

        dim_grid.addWidget(QLabel("Resolution (DPI):"), 3, 0)
        self.combo_dpi = QComboBox()
        self.combo_dpi.addItem("254 DPI (0.100 mm - Standard Diode)", 254.0)
        self.combo_dpi.addItem("318 DPI (0.080 mm - High Detail)", 318.0)
        self.combo_dpi.addItem("508 DPI (0.050 mm - Ultra Fine)", 508.0)
        self.combo_dpi.addItem("127 DPI (0.200 mm - Fast Coarse)", 127.0)
        self.combo_dpi.currentIndexChanged.connect(self._schedule_reprocess)
        dim_grid.addWidget(self.combo_dpi, 3, 1)

        ctrl_layout.addWidget(dim_grp)

        # 3. Engraving / Dithering Algorithm
        dither_grp = QGroupBox("Laser Engraving & Dither Mode")
        dither_layout = QVBoxLayout(dither_grp)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Floyd-Steinberg (Classic General)", "Floyd-Steinberg")
        self.combo_mode.addItem("Jarvis (Smooth Tone / Portraits)", "Jarvis")
        self.combo_mode.addItem("Stucki (Sharp Detail & Textures)", "Stucki")
        self.combo_mode.addItem("Atkinson (High Contrast / Clean Wood)", "Atkinson")
        self.combo_mode.addItem("Halftone Screen (45° AM Dot Grid)", "Halftone")
        self.combo_mode.addItem("Grayscale (Dynamic PWM Power)", "Grayscale")
        self.combo_mode.addItem("Threshold (Silhouettes / Stamps)", "Threshold")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        dither_layout.addWidget(self.combo_mode)

        # Halftone options
        self.halftone_frame = QFrame()
        ht_layout = QHBoxLayout(self.halftone_frame)
        ht_layout.setContentsMargins(0, 4, 0, 0)
        ht_layout.addWidget(QLabel("Dot Spacing:"))
        self.spin_ht_cell = QDoubleSpinBox()
        self.spin_ht_cell.setRange(2.0, 30.0)
        self.spin_ht_cell.setValue(6.0)
        self.spin_ht_cell.setSuffix(" px")
        self.spin_ht_cell.valueChanged.connect(self._schedule_reprocess)
        ht_layout.addWidget(self.spin_ht_cell)

        ht_layout.addWidget(QLabel("Angle:"))
        self.spin_ht_angle = QDoubleSpinBox()
        self.spin_ht_angle.setRange(0.0, 90.0)
        self.spin_ht_angle.setValue(45.0)
        self.spin_ht_angle.setSuffix("°")
        self.spin_ht_angle.valueChanged.connect(self._schedule_reprocess)
        ht_layout.addWidget(self.spin_ht_angle)
        self.halftone_frame.setVisible(False)
        dither_layout.addWidget(self.halftone_frame)

        ctrl_layout.addWidget(dither_grp)

        # 4. Photographic Enhancements (Contrast, Gamma, Unsharp Mask)
        photo_grp = QGroupBox("Photographic Tone & Edge Tuning")
        photo_grid = QGridLayout(photo_grp)
        photo_grid.setSpacing(6)

        # Contrast
        photo_grid.addWidget(QLabel("Contrast:"), 0, 0)
        self.slider_contrast = QSlider(Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(20, 250)
        self.slider_contrast.setValue(100)
        self.slider_contrast.valueChanged.connect(self._on_slider_contrast_changed)
        photo_grid.addWidget(self.slider_contrast, 0, 1)
        self.lbl_contrast_val = QLabel("1.00×")
        self.lbl_contrast_val.setMinimumWidth(40)
        photo_grid.addWidget(self.lbl_contrast_val, 0, 2)

        # Brightness
        photo_grid.addWidget(QLabel("Brightness:"), 1, 0)
        self.slider_bright = QSlider(Qt.Orientation.Horizontal)
        self.slider_bright.setRange(-100, 100)
        self.slider_bright.setValue(0)
        self.slider_bright.valueChanged.connect(self._on_slider_bright_changed)
        photo_grid.addWidget(self.slider_bright, 1, 1)
        self.lbl_bright_val = QLabel("0%")
        self.lbl_bright_val.setMinimumWidth(40)
        photo_grid.addWidget(self.lbl_bright_val, 1, 2)

        # Gamma Curve
        photo_grid.addWidget(QLabel("Gamma (Lift Mids):"), 2, 0)
        self.slider_gamma = QSlider(Qt.Orientation.Horizontal)
        self.slider_gamma.setRange(50, 250)
        self.slider_gamma.setValue(100)
        self.slider_gamma.valueChanged.connect(self._on_slider_gamma_changed)
        photo_grid.addWidget(self.slider_gamma, 2, 1)
        self.lbl_gamma_val = QLabel("1.00")
        self.lbl_gamma_val.setMinimumWidth(40)
        photo_grid.addWidget(self.lbl_gamma_val, 2, 2)

        # Sharpening / Unsharp Mask
        photo_grid.addWidget(QLabel("Unsharp Mask:"), 3, 0)
        self.slider_sharpen = QSlider(Qt.Orientation.Horizontal)
        self.slider_sharpen.setRange(0, 300)
        self.slider_sharpen.setValue(0)
        self.slider_sharpen.valueChanged.connect(self._on_slider_sharpen_changed)
        photo_grid.addWidget(self.slider_sharpen, 3, 1)
        self.lbl_sharpen_val = QLabel("0.0×")
        self.lbl_sharpen_val.setMinimumWidth(40)
        photo_grid.addWidget(self.lbl_sharpen_val, 3, 2)

        # White Cutoff (Clean background)
        photo_grid.addWidget(QLabel("White Clean Cutoff:"), 4, 0)
        self.slider_white_clip = QSlider(Qt.Orientation.Horizontal)
        self.slider_white_clip.setRange(150, 255)
        self.slider_white_clip.setValue(255)
        self.slider_white_clip.valueChanged.connect(self._on_slider_white_clip_changed)
        photo_grid.addWidget(self.slider_white_clip, 4, 1)
        self.lbl_white_clip_val = QLabel("255")
        self.lbl_white_clip_val.setMinimumWidth(40)
        photo_grid.addWidget(self.lbl_white_clip_val, 4, 2)

        # Toggles
        self.chk_equalize = QCheckBox("Adaptive Histogram Equalization (CLAHE)")
        self.chk_equalize.setToolTip("Balances shadows and highlights so facial features don't get lost")
        self.chk_equalize.stateChanged.connect(self._schedule_reprocess)
        photo_grid.addWidget(self.chk_equalize, 5, 0, 1, 3)

        self.chk_invert = QCheckBox("Invert Colors (Light Mark on Dark Substrate)")
        self.chk_invert.setToolTip("Essential for Black Slate, Anodized Metal, and Dark Acrylic")
        self.chk_invert.stateChanged.connect(self._schedule_reprocess)
        photo_grid.addWidget(self.chk_invert, 6, 0, 1, 3)

        ctrl_layout.addWidget(photo_grp)
        ctrl_layout.addStretch(1)

        scroll_area.setWidget(ctrl_widget)
        splitter.addWidget(scroll_area)

        # --- Right Panel: Interactive Previews ---
        preview_container = QWidget()
        prev_layout = QVBoxLayout(preview_container)
        prev_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()

        # Tab 1: Realistic Material Simulation
        self.lbl_sim_preview = QLabel()
        self.lbl_sim_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sim_preview.setStyleSheet("background-color: #121212;")
        sim_scroll = QScrollArea()
        sim_scroll.setWidgetResizable(True)
        sim_scroll.setWidget(self.lbl_sim_preview)
        self.tabs.addTab(sim_scroll, "✨ Material Engraving Simulation")

        # Tab 2: 1-Bit Laser Burn Mask
        self.lbl_mask_preview = QLabel()
        self.lbl_mask_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_mask_preview.setStyleSheet("background-color: #212121;")
        mask_scroll = QScrollArea()
        mask_scroll.setWidgetResizable(True)
        mask_scroll.setWidget(self.lbl_mask_preview)
        self.tabs.addTab(mask_scroll, "⬛ Pure Laser Burn Mask (1-Bit)")

        prev_layout.addWidget(self.tabs)

        # Status Bar Info
        self.lbl_stats = QLabel("Load an image to preview conversion.")
        self.lbl_stats.setStyleSheet("color: #b0bec5; font-size: 11px; padding: 4px;")
        prev_layout.addWidget(self.lbl_stats)

        splitter.addWidget(preview_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 1)

        # Bottom Dialog Actions
        bottom_bar = QHBoxLayout()

        # Preview Style selector for canvas
        bottom_bar.addWidget(QLabel("Canvas View:"))
        self.combo_canvas_style = QComboBox()
        self.combo_canvas_style.addItem("✨ Material Burn Simulation", "sim")
        self.combo_canvas_style.addItem("⬛ Monochrome Laser Mask (B&W)", "mono")
        self.combo_canvas_style.setToolTip("Select whether the canvas displays a realistic material burn or pure 1-bit laser mask")
        bottom_bar.addWidget(self.combo_canvas_style)

        bottom_bar.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_cancel)

        btn_apply = QPushButton("✨ Apply to Canvas")
        btn_apply.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 18px;")
        btn_apply.clicked.connect(self._on_apply)
        bottom_bar.addWidget(btn_apply)

        main_layout.addLayout(bottom_bar)

        # If image_entity was provided, load its existing parameters
        if self.image_entity:
            self._load_from_entity(self.image_entity)

    def _set_placeholder_state(self):
        self.lbl_sim_preview.setText("Click 'Open Photo File...' to begin.")
        self.lbl_mask_preview.setText("No photo loaded.")

    def _on_open_crop(self):
        if not self.original_pil_img:
            QMessageBox.warning(self, "No Photo Loaded", "Please load a photo file first before cropping.")
            return
        dlg = CropImageDialog(self.original_pil_img, parent=self)
        if dlg.exec() and dlg.cropped_image:
            self.original_pil_img = dlg.cropped_image
            orig_w, orig_h = self.original_pil_img.size
            if self.chk_lock_aspect.isChecked() and orig_w > 0:
                aspect = orig_h / float(orig_w)
                current_w = self.spin_width.value()
                self.spin_height.blockSignals(True)
                self.spin_height.setValue(round(current_w * aspect, 1))
                self.spin_height.blockSignals(False)
            self._schedule_reprocess()
            self.lbl_stats.setText(f"Photo cropped to {orig_w} × {orig_h} px.")

    def _on_reset_crop(self):
        if getattr(self, "_original_uncropped_img", None):
            self.original_pil_img = self._original_uncropped_img.copy()
            orig_w, orig_h = self.original_pil_img.size
            if self.chk_lock_aspect.isChecked() and orig_w > 0:
                aspect = orig_h / float(orig_w)
                current_w = self.spin_width.value()
                self.spin_height.blockSignals(True)
                self.spin_height.setValue(round(current_w * aspect, 1))
                self.spin_height.blockSignals(False)
            self._schedule_reprocess()
            self.lbl_stats.setText(f"Restored original uncropped photo ({orig_w} × {orig_h} px).")

    def _load_image(self, path: str):
        try:
            self.image_path = path
            self.lbl_filename.setText(os.path.basename(path))
            self.original_pil_img = Image.open(path)
            self._original_uncropped_img = self.original_pil_img.copy()
            orig_w, orig_h = self.original_pil_img.size

            # Update dimensions preserving aspect ratio
            if self.chk_lock_aspect.isChecked() and orig_w > 0:
                aspect = orig_h / float(orig_w)
                current_w = self.spin_width.value()
                self.spin_height.blockSignals(True)
                self.spin_height.setValue(round(current_w * aspect, 1))
                self.spin_height.blockSignals(False)

            self._schedule_reprocess()
        except Exception as e:
            QMessageBox.critical(self, "Image Load Error", f"Could not load image file:\n{e}")

    def _load_from_entity(self, ent: ImageEntity):
        src_path = getattr(ent, "raw_image_path", "") or ent.image_path
        if src_path and os.path.exists(src_path):
            self.raw_image_path = src_path
            self._load_image(src_path)
        elif ent.image_path and os.path.exists(ent.image_path):
            self._load_image(ent.image_path)

        self.spin_width.setValue(ent.width)
        self.spin_height.setValue(ent.height)
        self.chk_invert.setChecked(ent.invert)
        self.slider_contrast.setValue(int(round(ent.contrast * 100)))
        self.slider_bright.setValue(int(round(ent.brightness * 100)))
        self.slider_gamma.setValue(int(round(getattr(ent, "gamma", 1.0) * 100)))
        self.slider_sharpen.setValue(int(round(getattr(ent, "sharpen", 0.0) * 100)))
        self.chk_equalize.setChecked(getattr(ent, "equalize", False))
        self.slider_white_clip.setValue(getattr(ent, "white_clip", 255))
        self.spin_ht_cell.setValue(getattr(ent, "halftone_cell_size", 6.0))
        self.spin_ht_angle.setValue(getattr(ent, "halftone_angle_deg", 45.0))

        mode = ent.dither_mode
        idx = self.combo_mode.findData(mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)

        if getattr(ent, "dpi", None):
            dpi_idx = self.combo_dpi.findData(float(ent.dpi))
            if dpi_idx >= 0:
                self.combo_dpi.setCurrentIndex(dpi_idx)

    def _on_browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Photograph for Laser Engraving", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;All Files (*)"
        )
        if path:
            self._load_image(path)

    def _on_width_changed(self, val: float):
        if self.chk_lock_aspect.isChecked() and self.original_pil_img:
            ow, oh = self.original_pil_img.size
            if ow > 0:
                aspect = oh / float(ow)
                self.spin_height.blockSignals(True)
                self.spin_height.setValue(round(val * aspect, 1))
                self.spin_height.blockSignals(False)
        self._schedule_reprocess()

    def _on_height_changed(self, val: float):
        if self.chk_lock_aspect.isChecked() and self.original_pil_img:
            ow, oh = self.original_pil_img.size
            if oh > 0:
                aspect = ow / float(oh)
                self.spin_width.blockSignals(True)
                self.spin_width.setValue(round(val * aspect, 1))
                self.spin_width.blockSignals(False)
        self._schedule_reprocess()

    def _on_preset_changed(self, idx: int):
        preset_name = self.combo_presets.currentData()
        if not preset_name:
            return
        preset = RasterProcessor.MATERIAL_PRESETS.get(preset_name)
        if not preset:
            return

        self.blockSignals(True)
        # Apply preset settings
        m_idx = self.combo_mode.findData(preset["mode"])
        if m_idx >= 0:
            self.combo_mode.setCurrentIndex(m_idx)
        self.slider_contrast.setValue(int(round(preset["contrast"] * 100)))
        self.lbl_contrast_val.setText(f"{preset['contrast']:.2f}×")
        self.slider_bright.setValue(int(round(preset["brightness"] * 100)))
        self.lbl_bright_val.setText(f"{int(round(preset['brightness'] * 100))}%")
        self.slider_gamma.setValue(int(round(preset["gamma"] * 100)))
        self.lbl_gamma_val.setText(f"{preset['gamma']:.2f}")
        self.slider_sharpen.setValue(int(round(preset["sharpen"] * 100)))
        self.lbl_sharpen_val.setText(f"{preset['sharpen']:.1f}×")
        self.chk_invert.setChecked(preset["invert"])
        self.chk_equalize.setChecked(preset["equalize"])
        self.blockSignals(False)

        self._schedule_reprocess()

    def _on_mode_changed(self, idx: int):
        mode = self.combo_mode.currentData()
        self.halftone_frame.setVisible(mode == "Halftone")
        self._schedule_reprocess()

    def _on_slider_contrast_changed(self, val: int):
        self.lbl_contrast_val.setText(f"{val / 100.0:.2f}×")
        self._schedule_reprocess()

    def _on_slider_bright_changed(self, val: int):
        self.lbl_bright_val.setText(f"{val}%")
        self._schedule_reprocess()

    def _on_slider_gamma_changed(self, val: int):
        self.lbl_gamma_val.setText(f"{val / 100.0:.2f}")
        self._schedule_reprocess()

    def _on_slider_sharpen_changed(self, val: int):
        self.lbl_sharpen_val.setText(f"{val / 100.0:.1f}×")
        self._schedule_reprocess()

    def _on_slider_white_clip_changed(self, val: int):
        self.lbl_white_clip_val.setText(str(val))
        self._schedule_reprocess()

    def _schedule_reprocess(self):
        self._debounce_timer.start()

    def _reprocess_and_render(self):
        if not self.original_pil_img:
            return

        target_w_mm = self.spin_width.value()
        target_h_mm = self.spin_height.value()
        dpi = float(self.combo_dpi.currentData())
        line_interval_mm = 25.4 / dpi

        mode = self.combo_mode.currentData()
        invert = self.chk_invert.isChecked()
        contrast = self.slider_contrast.value() / 100.0
        brightness = self.slider_bright.value() / 100.0
        gamma = self.slider_gamma.value() / 100.0
        sharpen = self.slider_sharpen.value() / 100.0
        equalize = self.chk_equalize.isChecked()
        white_clip = self.slider_white_clip.value()
        ht_cell = self.spin_ht_cell.value()
        ht_angle = self.spin_ht_angle.value()

        # Execute conversion pipeline
        processed_arr = RasterProcessor.process_image(
            img=self.original_pil_img,
            target_width_mm=target_w_mm,
            target_height_mm=target_h_mm,
            line_interval_mm=line_interval_mm,
            mode=mode,
            invert=invert,
            contrast=contrast,
            brightness=brightness,
            gamma=gamma,
            sharpen=sharpen,
            equalize=equalize,
            white_clip=white_clip,
            halftone_cell_size=ht_cell,
            halftone_angle_deg=ht_angle
        )
        self.current_processed_arr = processed_arr

        # Generate realistic material preview
        preset_name = self.combo_presets.currentData() or "Wood / Birch Plywood"
        sim_img = RasterProcessor.generate_simulated_burn_preview(processed_arr, preset_name)
        self.current_preview_img = sim_img

        # Convert sim_img to QPixmap
        sim_data = sim_img.convert("RGBA").tobytes("raw", "RGBA")
        q_sim = QImage(sim_data, sim_img.width, sim_img.height, QImage.Format.Format_RGBA8888)
        pix_sim = QPixmap.fromImage(q_sim)
        self.lbl_sim_preview.setPixmap(pix_sim)

        # Generate 1-bit mask preview
        if processed_arr.max() > 1:
            # Grayscale PWM
            mask_mono = 255 - processed_arr
        else:
            # 1 = burn (black), 0 = no burn (white)
            mask_mono = np.where(processed_arr == 1, 0, 255).astype(np.uint8)

        mask_img = Image.fromarray(mask_mono, mode="L").convert("RGBA")
        mask_data = mask_img.tobytes("raw", "RGBA")
        q_mask = QImage(mask_data, mask_img.width, mask_img.height, QImage.Format.Format_RGBA8888)
        pix_mask = QPixmap.fromImage(q_mask)
        self.lbl_mask_preview.setPixmap(pix_mask)

        # Update stats
        rows, cols = processed_arr.shape
        burned_px = int(np.sum(processed_arr > 0))
        total_px = rows * cols
        coverage_pct = (burned_px / max(1, total_px)) * 100.0
        self.lbl_stats.setText(
            f"Resolution: {cols} × {rows} px  |  Size: {target_w_mm:.1f} × {target_h_mm:.1f} mm  |  "
            f"Line Pitch: {line_interval_mm:.3f} mm ({dpi:.0f} DPI)  |  "
            f"Laser Density: {coverage_pct:.1f}% ({burned_px:,} pulses)"
        )

    def _on_export_processed(self):
        if self.current_processed_arr is None:
            QMessageBox.warning(self, "No Image", "Please load and process a photo first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Laser Processed Bitmap", "laser_engrave_ready.png",
            "PNG Image (*.png);;BMP Image (*.bmp);;All Files (*)"
        )
        if not path:
            return

        try:
            if self.current_processed_arr.max() > 1:
                out_img = Image.fromarray(255 - self.current_processed_arr, mode="L")
            else:
                mono = np.where(self.current_processed_arr == 1, 0, 255).astype(np.uint8)
                out_img = Image.fromarray(mono, mode="L").convert("1")
            out_img.save(path)
            QMessageBox.information(self, "Export Complete", f"Successfully exported laser-ready bitmap to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to save image: {e}")

    def _on_apply(self):
        if not self.image_path:
            QMessageBox.warning(self, "No Photo Loaded", "Please load a photo file first.")
            return

        # Ensure active processed arrays exist
        if self.current_processed_arr is None and self.original_pil_img:
            self._reprocess_and_render()

        # Save active processed bitmap to permanent cache for WYSIWYG canvas display
        cache_dir = os.path.expanduser("~/.laserforge/cache")
        os.makedirs(cache_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        processed_path = os.path.join(cache_dir, f"photo_processed_{timestamp}.png")

        style = self.combo_canvas_style.currentData() if hasattr(self, "combo_canvas_style") else "sim"
        try:
            if style == "mono" or self.tabs.currentIndex() == 1:
                if self.current_processed_arr is not None:
                    if self.current_processed_arr.max() > 1:
                        out_img = Image.fromarray((255 - self.current_processed_arr).astype(np.uint8))
                    else:
                        mono = np.where(self.current_processed_arr == 1, 0, 255).astype(np.uint8)
                        out_img = Image.fromarray(mono)
                    out_img.save(processed_path)
                elif self.current_preview_img is not None:
                    self.current_preview_img.save(processed_path)
            else:
                if self.current_preview_img is not None:
                    self.current_preview_img.save(processed_path)
                elif self.current_processed_arr is not None:
                    mono = np.where(self.current_processed_arr == 1, 0, 255).astype(np.uint8)
                    out_img = Image.fromarray(mono)
                    out_img.save(processed_path)
        except Exception as e:
            print(f"Error caching processed image: {e}")
            processed_path = self.image_path

        dpi = float(self.combo_dpi.currentData())
        params = {
            "image_path": processed_path,
            "processed_image_path": processed_path,
            "raw_image_path": getattr(self, "raw_image_path", None) or self.image_path,
            "width": self.spin_width.value(),
            "height": self.spin_height.value(),
            "dither_mode": self.combo_mode.currentData(),
            "invert": self.chk_invert.isChecked(),
            "contrast": self.slider_contrast.value() / 100.0,
            "brightness": self.slider_bright.value() / 100.0,
            "gamma": self.slider_gamma.value() / 100.0,
            "sharpen": self.slider_sharpen.value() / 100.0,
            "equalize": self.chk_equalize.isChecked(),
            "white_clip": self.slider_white_clip.value(),
            "dpi": dpi,
            "halftone_cell_size": self.spin_ht_cell.value(),
            "halftone_angle_deg": self.spin_ht_angle.value()
        }
        if self.image_entity:
            for k, v in params.items():
                if hasattr(self.image_entity, k):
                    setattr(self.image_entity, k, v)
        self.photo_applied.emit(params)
        self.accept()
