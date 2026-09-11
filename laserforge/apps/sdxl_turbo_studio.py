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
from PyQt6.QtGui import QPixmap, QImage, QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QLabel, QPushButton, QComboBox, QTextEdit, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox, QSplitter, QProgressBar,
    QFileDialog, QMessageBox, QFrame, QScrollArea
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

    def __init__(self, parent=None, is_embedded: bool = False):
        super().__init__(parent)
        self.is_embedded = is_embedded
        self.setWindowTitle("LaserForge SDXL Turbo Studio - Generative Laser Art (8GB VRAM)")
        self.resize(1080, 720)
        self.setMinimumSize(880, 580)

        # Engine
        self.engine = SDXLTurboEngine()
        self.current_worker: Optional[SDXLTurboWorker] = None
        self.last_generated_path: Optional[str] = None
        self.last_seed: int = 42

        # Create necessary directories
        os.makedirs(IMPORT_QUEUE_DIR, exist_ok=True)
        os.makedirs(GENERATED_OUTPUT_DIR, exist_ok=True)

        self._init_ui()

        # VRAM monitor timer
        self.vram_timer = QTimer(self)
        self.vram_timer.setInterval(2000)
        self.vram_timer.timeout.connect(self._refresh_vram_status)
        self.vram_timer.start()
        self._refresh_vram_status()

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

        # 1. Prompt Group
        prompt_grp = QGroupBox("Prompt Engineering")
        p_layout = QVBoxLayout(prompt_grp)

        p_layout.addWidget(QLabel("Prompt (Subject & Elements):"))
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
            output_dir=GENERATED_OUTPUT_DIR
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
        self._display_image(filepath)

        w, h = self.combo_res.currentData() or (512, 512)
        steps = self.spin_steps.value()
        self.lbl_meta.setText(f"Dimensions: {w} × {h} px  |  Steps: {steps}  |  Seed: {self.last_seed}")

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
            target_w = min(600, self.lbl_preview.width() or 512)
            target_h = min(600, self.lbl_preview.height() or 512)
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
                img = Image.open(self.last_generated_path)
                img.save(path)
                QMessageBox.information(self, "Saved", f"Image successfully saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save file: {e}")


def main():
    """Standalone entry point when run as a standalone application."""
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
    window = SDXLTurboStudioWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
