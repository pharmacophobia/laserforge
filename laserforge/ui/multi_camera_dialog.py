"""
LaserForge Multi-Camera Panoramic Bed Setup & Seam Stitching Studio.

Provides an interactive GUI to configure:
1. Dual and multi-camera arrays for wide laser beds (>900 mm).
2. Per-camera slot device index, bounds, orientation, and calibration homography.
3. Photometric seam blending strategies (LinearFeather, DistanceTransform, MaxPriority, HardSeam).
4. Live composite orthophoto preview with seam line demarcation overlays.
5. Push stitched panoramic orthophoto directly to the LaserForge canvas overlay.
"""

import os
from typing import Optional, List, Dict, Tuple
import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF
from PyQt6.QtGui import QImage, QPixmap, QColor, QPen, QBrush, QFont, QPainter
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QMessageBox, QDoubleSpinBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame
)

from laserforge.core.multi_camera_engine import (
    MultiCameraEngine, MultiCameraConfig, CameraSlotConfig, DEFAULT_MULTI_CAMERA_CONFIG_PATH
)
from laserforge.core.camera_engine import HAS_CV2, CameraEngine
from laserforge.ui.camera_calibration_wizard import CameraCalibrationWizardDialog


class PanoramicPreviewWidget(QFrame):
    """Interactive preview canvas for panoramic stitched bed composite orthophotos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.setMinimumSize(480, 300)
        self.setStyleSheet("background-color: #1a1a24; border: 1px solid #333348; border-radius: 4px;")
        self._pixmap: Optional[QPixmap] = None
        self._status_text: str = "No stitched image captured yet"

    def set_frame(self, cv_img: Optional[np.ndarray], status: str = ""):
        self._status_text = status
        if cv_img is None or cv_img.size == 0:
            self._pixmap = None
        else:
            h, w, ch = cv_img.shape
            bytes_per_line = ch * w
            qimg = QImage(cv_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
            self._pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                w - 16, h - 36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            px = (w - scaled.width()) // 2
            py = (h - 24 - scaled.height()) // 2 + 10
            painter.drawPixmap(px, py, scaled)

            # Draw subtle border around scaled image
            painter.setPen(QPen(QColor(0, 229, 255, 120), 1))
            painter.drawRect(px, py, scaled.width(), scaled.height())
        else:
            # Placeholder text
            painter.setPen(QPen(QColor(130, 140, 160)))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(
                QRectF(0, 0, w, h - 30),
                Qt.AlignmentFlag.AlignCenter,
                "No Stitched Orthophoto Available\nClick 'Simulate Test Pattern' or 'Capture & Stitch Live'"
            )

        # Bottom status bar
        if self._status_text:
            painter.setPen(QPen(QColor(0, 229, 255)))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(
                QRectF(12, h - 26, w - 24, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._status_text
            )
        painter.end()


class MultiCameraSetupDialog(QDialog):
    """Configuration Studio for Multi-Camera Panoramic Bed Stitching."""

    panoramic_stitched_ready = pyqtSignal(np.ndarray)
    config_saved = pyqtSignal(MultiCameraConfig)

    def __init__(self, engine: Optional[MultiCameraEngine] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📷 Panoramic Multi-Camera Bed Stitcher Studio")
        self.resize(1100, 680)

        self.engine = engine or MultiCameraEngine()
        self.config = MultiCameraConfig.from_dict(self.engine.config.to_dict())
        self._last_stitched_frame: Optional[np.ndarray] = None

        self._init_ui()
        self._load_config_to_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header description
        header = QLabel(
            "<b>Multi-Camera Bed Panoramic Stitching Studio</b><br>"
            "<span style='color: #90a4ae; font-size: 11px;'>"
            "Combine overlapping camera streams into a single high-resolution orthophoto for wide beds (>900 mm). "
            "Supports per-camera perspective homography, lens undistortion, and seamless photometric blending.</span>"
        )
        main_layout.addWidget(header)

        # Splitter between left setup controls and right panoramic preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # -------------------------------------------------------------
        # LEFT PANE: Master Settings & Slot Table
        # -------------------------------------------------------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        # Master settings box
        grp_master = QGroupBox("Master Panoramic Settings")
        grid_master = QGridLayout(grp_master)
        grid_master.setSpacing(6)

        self.chk_enable_multi = QCheckBox("Enable Multi-Camera Stitching on Canvas")
        self.chk_enable_multi.setStyleSheet("font-weight: bold; color: #00e5ff;")
        grid_master.addWidget(self.chk_enable_multi, 0, 0, 1, 2)

        grid_master.addWidget(QLabel("Bed Width (mm):"), 1, 0)
        self.spin_bed_w = QDoubleSpinBox()
        self.spin_bed_w.setRange(100.0, 5000.0)
        self.spin_bed_w.setValue(1000.0)
        self.spin_bed_w.setSuffix(" mm")
        grid_master.addWidget(self.spin_bed_w, 1, 1)

        grid_master.addWidget(QLabel("Bed Height (mm):"), 2, 0)
        self.spin_bed_h = QDoubleSpinBox()
        self.spin_bed_h.setRange(100.0, 3000.0)
        self.spin_bed_h.setValue(600.0)
        self.spin_bed_h.setSuffix(" mm")
        grid_master.addWidget(self.spin_bed_h, 2, 1)

        grid_master.addWidget(QLabel("Resolution Scale:"), 3, 0)
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.5, 10.0)
        self.spin_scale.setSingleStep(0.5)
        self.spin_scale.setValue(2.5)
        self.spin_scale.setSuffix(" px/mm")
        grid_master.addWidget(self.spin_scale, 3, 1)

        grid_master.addWidget(QLabel("Seam Blend Mode:"), 4, 0)
        self.combo_blend = QComboBox()
        self.combo_blend.addItems([
            "LinearFeather",
            "DistanceTransform",
            "MaxPriority",
            "HardSeam"
        ])
        grid_master.addWidget(self.combo_blend, 4, 1)

        grid_master.addWidget(QLabel("Seam Feather Overlap:"), 5, 0)
        self.spin_feather = QDoubleSpinBox()
        self.spin_feather.setRange(2.0, 200.0)
        self.spin_feather.setValue(40.0)
        self.spin_feather.setSuffix(" mm")
        grid_master.addWidget(self.spin_feather, 5, 1)

        left_layout.addWidget(grp_master)

        # Slot Management Box
        grp_slots = QGroupBox("Camera Array Slots")
        v_slots = QVBoxLayout(grp_slots)
        v_slots.setSpacing(6)

        self.table_slots = QTableWidget(0, 5)
        self.table_slots.setHorizontalHeaderLabels(["ID / Name", "Device", "Bed X Span (mm)", "Calibrated", "Flip"])
        self.table_slots.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_slots.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_slots.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_slots.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_slots.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_slots.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_slots.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v_slots.addWidget(self.table_slots)

        btn_slot_row = QHBoxLayout()
        self.btn_add_slot = QPushButton("➕ Add Camera Slot")
        self.btn_add_slot.clicked.connect(self._add_slot)
        btn_slot_row.addWidget(self.btn_add_slot)

        self.btn_remove_slot = QPushButton("🗑 Remove Slot")
        self.btn_remove_slot.clicked.connect(self._remove_selected_slot)
        btn_slot_row.addWidget(self.btn_remove_slot)

        self.btn_calibrate_slot = QPushButton("🎯 Calibrate Slot...")
        self.btn_calibrate_slot.setStyleSheet("font-weight: bold; color: #00e5ff;")
        self.btn_calibrate_slot.clicked.connect(self._calibrate_selected_slot)
        btn_slot_row.addWidget(self.btn_calibrate_slot)

        v_slots.addLayout(btn_slot_row)
        left_layout.addWidget(grp_slots, 1)

        splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # RIGHT PANE: Stitched Panoramic Preview & Live Verification
        # -------------------------------------------------------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        right_top_row = QHBoxLayout()
        right_top_row.addWidget(QLabel("<b>Stitched Bed Panoramic Composite Preview:</b>"))
        right_top_row.addStretch()

        self.chk_show_seams = QCheckBox("Show Seam Boundary Contours")
        self.chk_show_seams.setChecked(True)
        self.chk_show_seams.toggled.connect(self._refresh_preview)
        right_top_row.addWidget(self.chk_show_seams)

        right_layout.addLayout(right_top_row)

        self.preview_widget = PanoramicPreviewWidget()
        right_layout.addWidget(self.preview_widget, 1)

        # Preview action buttons
        preview_btn_row = QHBoxLayout()
        self.btn_simulate = QPushButton("🎨 Simulate Panoramic Pattern")
        self.btn_simulate.setToolTip("Generate synthetic multi-camera overlapping test pattern without hardware")
        self.btn_simulate.clicked.connect(self._simulate_test_pattern)
        preview_btn_row.addWidget(self.btn_simulate)

        self.btn_capture_live = QPushButton("📷 Capture & Stitch Live")
        self.btn_capture_live.setStyleSheet("font-weight: bold;")
        self.btn_capture_live.setToolTip("Capture synchronized frames across all active camera slots and stitch")
        self.btn_capture_live.clicked.connect(self._capture_and_stitch_live)
        preview_btn_row.addWidget(self.btn_capture_live)

        self.btn_push_canvas = QPushButton("🚀 Push Stitched Bed to Canvas")
        self.btn_push_canvas.setStyleSheet("background-color: #00838f; color: white; font-weight: bold;")
        self.btn_push_canvas.clicked.connect(self._push_to_canvas)
        preview_btn_row.addWidget(self.btn_push_canvas)

        right_layout.addLayout(preview_btn_row)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        main_layout.addWidget(splitter, 1)

        # -------------------------------------------------------------
        # Bottom Dialog Action Buttons
        # -------------------------------------------------------------
        bottom_row = QHBoxLayout()
        self.lbl_overall_status = QLabel("Ready")
        self.lbl_overall_status.setStyleSheet("color: #81d4fa; font-size: 11px;")
        bottom_row.addWidget(self.lbl_overall_status, 1)

        self.btn_save = QPushButton("Save & Apply")
        self.btn_save.setStyleSheet("background-color: #00c853; color: white; font-weight: bold; min-width: 110px;")
        self.btn_save.clicked.connect(self._save_and_apply)
        bottom_row.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("Close")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(self.btn_cancel)

        main_layout.addLayout(bottom_row)

    def _load_config_to_ui(self):
        """Loads self.config values into GUI inputs."""
        self.chk_enable_multi.setChecked(self.config.enabled)
        self.spin_bed_w.setValue(self.config.bed_width_mm)
        self.spin_bed_h.setValue(self.config.bed_height_mm)
        self.spin_scale.setValue(self.config.scale_px_per_mm)
        idx = self.combo_blend.findText(self.config.blend_mode)
        if idx >= 0:
            self.combo_blend.setCurrentIndex(idx)
        self.spin_feather.setValue(self.config.feather_overlap_mm)

        self._populate_slots_table()
        # Automatically generate test pattern for instant feedback
        self._simulate_test_pattern()

    def _populate_slots_table(self):
        self.table_slots.setRowCount(len(self.config.slots))
        for row, slot in enumerate(self.config.slots):
            # ID / Name
            item_name = QTableWidgetItem(f"{slot.slot_id} ({slot.name})")
            item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_slots.setItem(row, 0, item_name)

            # Device
            item_dev = QTableWidgetItem(f"Device {slot.device_index}")
            self.table_slots.setItem(row, 1, item_dev)

            # Bed X Span
            span_text = f"{slot.target_bounds_mm[0]:.0f} - {slot.target_bounds_mm[2]:.0f} mm"
            item_span = QTableWidgetItem(span_text)
            self.table_slots.setItem(row, 2, item_span)

            # Calibrated
            eng = self.engine.get_slot_engine(slot.slot_id)
            is_cal = eng.calibration.is_bed_aligned() if eng else False
            cal_str = "✅ Aligned" if is_cal else "⚠️ Uncalibrated"
            item_cal = QTableWidgetItem(cal_str)
            item_cal.setForeground(QColor(0, 200, 83) if is_cal else QColor(255, 179, 0))
            self.table_slots.setItem(row, 3, item_cal)

            # Flip
            flip_str = "H" if slot.flip_horizontal else ""
            if slot.flip_vertical:
                flip_str += ("/" if flip_str else "") + "V"
            item_flip = QTableWidgetItem(flip_str or "None")
            self.table_slots.setItem(row, 4, item_flip)

        if self.table_slots.rowCount() > 0:
            self.table_slots.selectRow(0)

    def _sync_ui_to_config(self):
        """Reads GUI inputs back into self.config."""
        self.config.enabled = self.chk_enable_multi.isChecked()
        self.config.bed_width_mm = self.spin_bed_w.value()
        self.config.bed_height_mm = self.spin_bed_h.value()
        self.config.scale_px_per_mm = self.spin_scale.value()
        self.config.blend_mode = self.combo_blend.currentText()
        self.config.feather_overlap_mm = self.spin_feather.value()
        self.engine.config = self.config
        self.engine._init_camera_engines()

    def _add_slot(self):
        new_idx = len(self.config.slots) + 1
        slot = CameraSlotConfig(
            slot_id=f"cam_{new_idx}",
            name=f"Camera #{new_idx}",
            device_index=new_idx - 1,
            resolution=(1920, 1080),
            target_bounds_mm=(0.0, 0.0, self.config.bed_width_mm, self.config.bed_height_mm),
            enabled=True
        )
        self.config.slots.append(slot)
        self.engine.config = self.config
        self.engine._init_camera_engines()
        self._populate_slots_table()
        self.table_slots.selectRow(len(self.config.slots) - 1)

    def _remove_selected_slot(self):
        row = self.table_slots.currentRow()
        if 0 <= row < len(self.config.slots):
            del self.config.slots[row]
            self.engine.config = self.config
            self.engine._init_camera_engines()
            self._populate_slots_table()

    def _calibrate_selected_slot(self):
        row = self.table_slots.currentRow()
        if not (0 <= row < len(self.config.slots)):
            QMessageBox.information(self, "Select Slot", "Please select a camera slot to calibrate.")
            return

        slot = self.config.slots[row]
        eng = self.engine.get_slot_engine(slot.slot_id)
        if not eng:
            QMessageBox.warning(self, "Error", f"No engine available for {slot.slot_id}.")
            return

        # Open CameraCalibrationWizardDialog for this slot
        wiz = CameraCalibrationWizardDialog(
            camera_engine=eng,
            bed_width_mm=self.config.bed_width_mm,
            bed_height_mm=self.config.bed_height_mm,
            parent=self
        )
        if wiz.exec() == QDialog.DialogCode.Accepted:
            slot.calibration = eng.calibration
            self._populate_slots_table()
            self.lbl_overall_status.setText(f"Calibrated {slot.name} successfully.")

    def _simulate_test_pattern(self):
        self._sync_ui_to_config()
        pattern = self.engine.generate_synthetic_stitched_test_pattern()
        self._last_stitched_frame = pattern
        h, w, _ = pattern.shape
        self.preview_widget.set_frame(pattern, f"Synthetic Dual-Camera Test Pattern ({w}x{h} px)")
        self.lbl_overall_status.setText(f"Synthetic preview ready ({w}x{h} px).")

    def _refresh_preview(self):
        if self._last_stitched_frame is not None:
            self._simulate_test_pattern()

    def _capture_and_stitch_live(self):
        self._sync_ui_to_config()
        if not HAS_CV2:
            QMessageBox.warning(self, "OpenCV Missing", "OpenCV (cv2) is required for camera capture and stitching.")
            return

        draw_seams = self.chk_show_seams.isChecked()
        stitched = self.engine.stitch_orthophoto(draw_seams=draw_seams)
        if stitched is not None and stitched.size > 0:
            self._last_stitched_frame = stitched
            h, w, _ = stitched.shape
            self.preview_widget.set_frame(stitched, f"Live Stitched Bed ({w}x{h} px, Mode: {self.config.blend_mode})")
            self.lbl_overall_status.setText(f"Successfully stitched {len(self.config.slots)} cameras ({w}x{h} px).")
        else:
            # Fall back to simulated test pattern if hardware feeds aren't available
            self.lbl_overall_status.setText("Hardware cameras not accessible — displaying calibrated synthetic preview.")
            self._simulate_test_pattern()

    def _push_to_canvas(self):
        if self._last_stitched_frame is None:
            self._simulate_test_pattern()

        if self._last_stitched_frame is not None:
            self.panoramic_stitched_ready.emit(self._last_stitched_frame)
            self.lbl_overall_status.setText("Pushed stitched panoramic orthophoto to main canvas overlay.")
            QMessageBox.information(self, "Canvas Updated", "Stitched panoramic bed orthophoto has been pushed to the main canvas background!")

    def _save_and_apply(self):
        self._sync_ui_to_config()
        self.config.save_to_file()
        self.config_saved.emit(self.config)
        if self._last_stitched_frame is not None and self.config.enabled:
            self.panoramic_stitched_ready.emit(self._last_stitched_frame)
        self.accept()
