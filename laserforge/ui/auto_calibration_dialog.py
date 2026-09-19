"""
LaserForge Interactive Workbed Auto-Calibration Studio Dialog.

Provides:
1. One-click automated optical workbed alignment and camera homography calibration.
2. Real-time visual feedback with sub-pixel marker tracking, target reticles, and bed outline polygons.
3. Multi-mode fiducial support:
   - ArUco tags (DICT_4X4_50)
   - Concentric circular targets / bullseyes
   - Laser-burned dots on scrap stock
   - Crosshair reticles
   - Simulated/synthetic camera test markers
4. Comprehensive kinematic diagnostics:
   - Reprojection RMS error in millimeters and sensor pixels
   - Gantry non-orthogonality / skew angle analysis (gantry racking diagnosis)
   - Independent X and Y axis scaling ratios
   - Workbed rotation and origin offsets
   - Quality confidence rating (0% to 100%)
5. Physical laser integration:
   - Parametric calibration G-code generator
   - Direct 1-click calibration burn to scrap stock via SerialController
   - Automated laser head parking to clear camera field of view
   - 1-click CAD canvas target generator on Tool Layer
6. Instant apply and persistent save to ~/.laserforge/camera_calibration.json.
"""

from typing import Optional, Tuple, List, Dict, Any
import math
import numpy as np

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QPen, QBrush, QFont
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QDoubleSpinBox,
    QProgressBar, QMessageBox, QFrame, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog
)

from laserforge.config import MachineSettings
from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData
from laserforge.core.serial_controller import SerialController
from laserforge.core.auto_calibration import (
    AutoCalibrationEngine, AutoCalibrationConfig, AutoCalibrationResult, CalibrationPoint
)


class AutoCalibrationVisualWidget(QLabel):
    """
    Renders camera preview with live auto-calibration detection overlays,
    marker bounding reticles, canonical P1..P4 labels, and bed perimeter polygons.
    """

    point_hovered = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #101014; border: 1px solid #2e2e3e; border-radius: 4px;")
        self.setMinimumSize(560, 360)
        self.raw_frame: Optional[np.ndarray] = None
        self.annotated_pixmap: Optional[QPixmap] = None
        self.setMouseTracking(True)

    def set_display_frame(self, frame: np.ndarray, result: Optional[AutoCalibrationResult] = None):
        """Renders raw frame and optional annotated overlay."""
        self.raw_frame = frame
        if frame is None or frame.size == 0:
            self.clear()
            self.setText("No Camera Feed Available")
            return

        h, w = frame.shape[:2]
        ch = frame.shape[2] if len(frame.shape) == 3 else 1

        if ch == 3:
            # OpenCV BGR -> Qt RGB
            rgb = np.ascontiguousarray(frame[:, :, ::-1])
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        else:
            qimg = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)

        pix = QPixmap.fromImage(qimg)
        # Scale smoothly while preserving aspect ratio
        scaled = pix.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.annotated_pixmap = scaled
        self.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.raw_frame is not None:
            self.set_display_frame(self.raw_frame)


class AutoCalibrationDialog(QDialog):
    """
    Main Studio Dialog for Automated Workbed & Camera Coordinate Calibration.
    """

    calibration_applied = pyqtSignal(CameraCalibrationData)

    def __init__(
        self,
        camera_engine: CameraEngine,
        settings: Optional[MachineSettings] = None,
        serial_ctrl: Optional[SerialController] = None,
        scene: Optional[Any] = None,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("LaserForge Auto-Calibration Studio — Workbed & Laser Vision Alignment")
        self.resize(1080, 680)

        self.camera_engine = camera_engine
        self.settings = settings or MachineSettings()
        self.serial_ctrl = serial_ctrl
        self.scene = scene

        # Setup AutoCalibrationEngine
        cfg = AutoCalibrationConfig(
            bed_width_mm=self.settings.bed_width,
            bed_height_mm=self.settings.bed_height,
            fiducial_inset_mm=getattr(self.camera_engine.calibration, "fiducial_inset_mm", 40.0),
            scale_px_per_mm=getattr(self.camera_engine.calibration, "scale_px_per_mm", 3.0),
            pattern_type="auto"
        )
        self.engine = AutoCalibrationEngine(cfg)
        self.current_result: Optional[AutoCalibrationResult] = None

        # Camera polling timer for live stream
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._on_camera_tick)

        self._build_ui()
        self._start_camera_feed()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(8)

        # Header bar
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #1a1a24; border-bottom: 2px solid #00e5ff; padding: 6px;")
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 4, 8, 4)

        lbl_title = QLabel("🤖 Workbed & Laser Vision Auto-Calibration Studio")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #00e5ff;")
        h_layout.addWidget(lbl_title)

        h_layout.addStretch(1)

        self.lbl_cam_status = QLabel(f"Camera: {self.camera_engine.calibration.device_name}")
        self.lbl_cam_status.setStyleSheet("color: #90a4ae; font-size: 11px;")
        h_layout.addWidget(self.lbl_cam_status)

        root_layout.addWidget(header_frame)

        # Main splitter (Camera View on Left, Diagnostics/Controls on Right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Column: Visual Preview & Live Controls
        left_widget = QWidget()
        l_layout = QVBoxLayout(left_widget)
        l_layout.setContentsMargins(0, 0, 0, 0)

        self.visual_view = AutoCalibrationVisualWidget()
        l_layout.addWidget(self.visual_view, 1)

        # View toolbar
        view_bar = QHBoxLayout()
        self.chk_live_stream = QCheckBox("Live Camera Feed")
        self.chk_live_stream.setChecked(True)
        self.chk_live_stream.toggled.connect(self._toggle_live_feed)
        view_bar.addWidget(self.chk_live_stream)

        self.btn_capture_still = QPushButton("📸 Capture Frame")
        self.btn_capture_still.clicked.connect(self._capture_still_frame)
        view_bar.addWidget(self.btn_capture_still)

        view_bar.addStretch(1)

        self.lbl_status_msg = QLabel("Ready for auto-detection.")
        self.lbl_status_msg.setStyleSheet("color: #cfd8dc; font-weight: bold;")
        view_bar.addWidget(self.lbl_status_msg)

        l_layout.addLayout(view_bar)
        splitter.addWidget(left_widget)

        # Right Column: Configuration, Execution & Telemetry
        right_widget = QWidget()
        r_layout = QVBoxLayout(right_widget)
        r_layout.setContentsMargins(0, 0, 0, 0)

        # Section 1: Parameters Group
        param_group = QGroupBox("Calibration Parameters")
        param_group.setStyleSheet("QGroupBox { font-weight: bold; color: #00e5ff; }")
        p_grid = QGridLayout(param_group)

        p_grid.addWidget(QLabel("Bed Width (mm):"), 0, 0)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(50.0, 3000.0)
        self.spin_width.setValue(self.settings.bed_width)
        self.spin_width.valueChanged.connect(self._on_params_changed)
        p_grid.addWidget(self.spin_width, 0, 1)

        p_grid.addWidget(QLabel("Bed Height (mm):"), 0, 2)
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(50.0, 3000.0)
        self.spin_height.setValue(self.settings.bed_height)
        self.spin_height.valueChanged.connect(self._on_params_changed)
        p_grid.addWidget(self.spin_height, 0, 3)

        p_grid.addWidget(QLabel("Corner Inset (mm):"), 1, 0)
        self.spin_inset = QDoubleSpinBox()
        self.spin_inset.setRange(5.0, 200.0)
        self.spin_inset.setValue(self.engine.config.fiducial_inset_mm)
        self.spin_inset.valueChanged.connect(self._on_params_changed)
        p_grid.addWidget(self.spin_inset, 1, 1)

        p_grid.addWidget(QLabel("Marker Pattern:"), 1, 2)
        self.combo_pattern = QComboBox()
        self.combo_pattern.addItems([
            "✨ Auto-Detect All",
            "🎯 Concentric Circles / Bullseyes",
            "🏷️ ArUco Markers (4x4)",
            "⚫ Laser Burn Dots",
            "➕ Crosshairs / Reticles"
        ])
        self.combo_pattern.currentIndexChanged.connect(self._on_pattern_type_changed)
        p_grid.addWidget(self.combo_pattern, 1, 3)

        r_layout.addWidget(param_group)

        # Section 2: Automated Actions & Machine Controls
        act_group = QGroupBox("Auto-Calibration Workflow")
        act_group.setStyleSheet("QGroupBox { font-weight: bold; color: #ffd600; }")
        a_layout = QVBoxLayout(act_group)

        # Primary 1-Click Action
        self.btn_auto_detect = QPushButton("✨ Auto-Detect Markers & Align Bed")
        self.btn_auto_detect.setStyleSheet("""
            QPushButton {
                background-color: #00b4d8;
                color: #000000;
                font-size: 13px;
                font-weight: bold;
                padding: 10px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #00e5ff; }
        """)
        self.btn_auto_detect.clicked.connect(self._run_auto_detect_and_align)
        a_layout.addWidget(self.btn_auto_detect)

        btn_row = QHBoxLayout()
        self.btn_burn_targets = QPushButton("🔥 Burn Target Pattern")
        self.btn_burn_targets.setToolTip("Streams G-code to burn 4 calibration targets on scrap stock at exact coordinates")
        self.btn_burn_targets.clicked.connect(self._on_burn_targets_clicked)
        btn_row.addWidget(self.btn_burn_targets)

        self.btn_park_head = QPushButton("🅿️ Park Laser Out of View")
        self.btn_park_head.setToolTip("Rapid moves laser head to safe park coordinate so camera view is clear")
        self.btn_park_head.clicked.connect(self._on_park_laser_head)
        btn_row.addWidget(self.btn_park_head)

        self.btn_add_cad_targets = QPushButton("📋 Add Targets to CAD")
        self.btn_add_cad_targets.setToolTip("Adds 4 fiducials to the canvas scene on Tool Layer (Layer 12)")
        self.btn_add_cad_targets.clicked.connect(self._on_add_cad_targets)
        btn_row.addWidget(self.btn_add_cad_targets)

        a_layout.addLayout(btn_row)

        r_layout.addWidget(act_group)

        # Section 3: Kinematic Diagnostics & Telemetry
        diag_group = QGroupBox("Kinematics & Alignment Telemetry")
        diag_group.setStyleSheet("QGroupBox { font-weight: bold; color: #00e676; }")
        d_layout = QVBoxLayout(diag_group)

        # Telemetry cards row
        cards_layout = QHBoxLayout()

        self.badge_quality = QLabel("Quality: —")
        self.badge_quality.setStyleSheet("background-color: #263238; color: #b0bec5; font-weight: bold; padding: 6px; border-radius: 4px;")
        cards_layout.addWidget(self.badge_quality)

        self.lbl_rms = QLabel("RMS Error: —")
        self.lbl_rms.setStyleSheet("background-color: #263238; color: #b0bec5; font-weight: bold; padding: 6px; border-radius: 4px;")
        cards_layout.addWidget(self.lbl_rms)

        self.lbl_skew = QLabel("Gantry Skew: —")
        self.lbl_skew.setStyleSheet("background-color: #263238; color: #b0bec5; font-weight: bold; padding: 6px; border-radius: 4px;")
        cards_layout.addWidget(self.lbl_skew)

        self.lbl_scale = QLabel("Scale X/Y: —")
        self.lbl_scale.setStyleSheet("background-color: #263238; color: #b0bec5; font-weight: bold; padding: 6px; border-radius: 4px;")
        cards_layout.addWidget(self.lbl_scale)

        d_layout.addLayout(cards_layout)

        # Residuals table
        self.table_residuals = QTableWidget(4, 5)
        self.table_residuals.setHorizontalHeaderLabels([
            "Fiducial", "Camera (px)", "Laser (mm)", "Residual (mm)", "Error (px)"
        ])
        self.table_residuals.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_residuals.verticalHeader().setVisible(False)
        self.table_residuals.setStyleSheet("background-color: #14141a; font-size: 11px;")
        self.table_residuals.setFixedHeight(120)
        d_layout.addWidget(self.table_residuals)

        r_layout.addWidget(diag_group)

        # Section 4: Action Footer
        r_layout.addStretch(1)

        footer_box = QHBoxLayout()
        self.btn_export_gcode = QPushButton("💾 Export G-Code...")
        self.btn_export_gcode.clicked.connect(self._on_export_gcode)
        footer_box.addWidget(self.btn_export_gcode)

        footer_box.addStretch(1)

        self.btn_apply = QPushButton("✅ Apply Calibration to Bed")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #00e676;
                color: #000000;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #69f0ae; }
            QPushButton:disabled { background-color: #37474f; color: #78909c; }
        """)
        self.btn_apply.clicked.connect(self._on_apply_calibration)
        footer_box.addWidget(self.btn_apply)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        footer_box.addWidget(self.btn_close)

        r_layout.addLayout(footer_box)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root_layout.addWidget(splitter)

    # -------------------------------------------------------------------------
    # Camera Stream & Polling
    # -------------------------------------------------------------------------
    def _start_camera_feed(self):
        if self.chk_live_stream.isChecked():
            self.poll_timer.start(50)  # 20 FPS

    def _stop_camera_feed(self):
        self.poll_timer.stop()

    def _toggle_live_feed(self, enabled: bool):
        if enabled:
            self._start_camera_feed()
        else:
            self._stop_camera_feed()

    def _on_camera_tick(self):
        try:
            frame = self.camera_engine.capture_frame(draw_guides=True)
            if frame is not None:
                # If we have an active calibration result, keep showing annotated frame
                if self.current_result and self.current_result.annotated_frame is not None and not self.chk_live_stream.isChecked():
                    self.visual_view.set_display_frame(self.current_result.annotated_frame)
                else:
                    self.visual_view.set_display_frame(frame)
        except Exception as e:
            self.lbl_status_msg.setText(f"Camera frame error: {e}")

    def _capture_still_frame(self):
        self.chk_live_stream.setChecked(False)
        frame = self.camera_engine.capture_frame(draw_guides=True)
        if frame is not None:
            self.visual_view.set_display_frame(frame)
            self.lbl_status_msg.setText("Captured still camera frame.")

    # -------------------------------------------------------------------------
    # Auto-Detection & Calibration Execution
    # -------------------------------------------------------------------------
    def _on_params_changed(self):
        self.engine.config.bed_width_mm = self.spin_width.value()
        self.engine.config.bed_height_mm = self.spin_height.value()
        self.engine.config.fiducial_inset_mm = self.spin_inset.value()

    def _on_pattern_type_changed(self, index: int):
        modes = ["auto", "concentric_circle", "aruco", "burn_dot", "crosshair"]
        self.engine.config.pattern_type = modes[index] if index < len(modes) else "auto"

    def _run_auto_detect_and_align(self):
        """Executes full automated detection, matching, homography, and kinematics solve."""
        self._on_params_changed()
        self.lbl_status_msg.setText("Detecting optical fiducials...")

        frame = self.camera_engine.capture_frame(draw_guides=True)
        if frame is None:
            QMessageBox.warning(self, "Camera Error", "No frame available from camera stream.")
            return

        result = self.engine.calibrate_from_frame(frame, self.camera_engine)
        self.current_result = result

        if not result.success:
            self.lbl_status_msg.setText("❌ Auto-detection failed.")
            self.badge_quality.setText("Quality: Failed")
            self.badge_quality.setStyleSheet("background-color: #b71c1c; color: #ffffff; font-weight: bold; padding: 6px; border-radius: 4px;")
            QMessageBox.warning(
                self,
                "Auto-Calibration Notice",
                f"Could not automatically complete workbed calibration:\n\n{result.message}\n\n"
                "Tip: Ensure the 4 calibration marks are visible and unobstructed on the workbed, "
                "or click '🔥 Burn Target Pattern' to place precision targets."
            )
            return

        # Display annotated frame
        if result.annotated_frame is not None:
            self.visual_view.set_display_frame(result.annotated_frame)

        # Update telemetry badges
        q_color = "#00e676" if result.quality_score >= 80.0 else "#ffd600" if result.quality_score >= 60.0 else "#ff5252"
        self.badge_quality.setText(f"Quality: {result.quality_score:.1f}%")
        self.badge_quality.setStyleSheet(f"background-color: #1b2e23; color: {q_color}; font-weight: bold; padding: 6px; border-radius: 4px; border: 1px solid {q_color};")

        self.lbl_rms.setText(f"RMS: {result.reprojection_error_rms_mm:.2f}mm ({result.reprojection_error_rms_px:.1f}px)")
        self.lbl_rms.setStyleSheet("background-color: #1a2228; color: #00e5ff; font-weight: bold; padding: 6px; border-radius: 4px;")

        skew_col = "#00e676" if abs(result.gantry_skew_deg) <= 0.5 else "#ffd600" if abs(result.gantry_skew_deg) <= 1.5 else "#ff5252"
        self.lbl_skew.setText(f"Skew: {result.gantry_skew_deg:+.2f}°")
        self.lbl_skew.setStyleSheet(f"background-color: #1a2228; color: {skew_col}; font-weight: bold; padding: 6px; border-radius: 4px;")

        self.lbl_scale.setText(f"Scale: {result.scale_x:.3f} / {result.scale_y:.3f}")
        self.lbl_scale.setStyleSheet("background-color: #1a2228; color: #cfd8dc; font-weight: bold; padding: 6px; border-radius: 4px;")

        # Populate residuals table
        for row, pt in enumerate(result.points):
            self.table_residuals.setItem(row, 0, QTableWidgetItem(pt.label.split()[0]))
            self.table_residuals.setItem(row, 1, QTableWidgetItem(f"({pt.camera_point[0]:.1f}, {pt.camera_point[1]:.1f})"))
            self.table_residuals.setItem(row, 2, QTableWidgetItem(f"({pt.laser_point_mm[0]:.1f}, {pt.laser_point_mm[1]:.1f})"))
            self.table_residuals.setItem(row, 3, QTableWidgetItem(f"{pt.reprojection_error_mm:.3f} mm"))
            self.table_residuals.setItem(row, 4, QTableWidgetItem(f"{pt.reprojection_error_px:.2f} px"))

        self.btn_apply.setEnabled(True)
        self.lbl_status_msg.setText("✅ Auto-calibration complete!")

    # -------------------------------------------------------------------------
    # Physical Machine & CAD Actions
    # -------------------------------------------------------------------------
    def _on_burn_targets_clicked(self):
        """Streams calibration G-code to laser machine via SerialController."""
        if not self.serial_ctrl or not getattr(self.serial_ctrl, "is_connected", False):
            QMessageBox.information(
                self,
                "Machine Not Connected",
                "Laser machine is not connected via USB serial.\n\n"
                "You can use '💾 Export G-Code...' to save the calibration toolpath file, "
                "or connect to your laser in the Laser Control Panel."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Burn Calibration Targets",
            "This will burn 4 alignment targets on scrap material placed on your laser bed.\n\n"
            f"Feed Rate: {self.engine.config.burn_feed_rate} mm/min\n"
            f"Power: {self.engine.config.burn_power_pct}%\n"
            f"Bed Size: {self.spin_width.value()} × {self.spin_height.value()} mm\n\n"
            "Ensure scrap material is positioned and protective eyewear is worn.\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        gcode = self.engine.generate_calibration_gcode(
            bed_width_mm=self.spin_width.value(),
            bed_height_mm=self.spin_height.value(),
            inset_mm=self.spin_inset.value(),
            feed_rate=self.engine.config.burn_feed_rate,
            power_pct=self.engine.config.burn_power_pct
        )

        for line in gcode.splitlines():
            line = line.strip()
            if line and not line.startswith(";"):
                self.serial_ctrl.send_command(line)

        self.lbl_status_msg.setText("🔥 Burning targets on laser bed...")

    def _on_park_laser_head(self):
        """Rockets laser head out of the camera's field of view."""
        if not self.serial_ctrl or not getattr(self.serial_ctrl, "is_connected", False):
            QMessageBox.information(
                self,
                "Machine Not Connected",
                "Cannot park laser head: machine is not connected via serial."
            )
            return

        park_x, park_y = self.engine.config.park_position
        cmd = f"G90 G0 X{park_x:.3f} Y{park_y:.3f} F3000"
        self.serial_ctrl.send_command(cmd)
        self.lbl_status_msg.setText(f"🅿️ Parked laser at X{park_x:.1f} Y{park_y:.1f}")

    def _on_add_cad_targets(self):
        """Adds 4 fiducials to the canvas scene on Tool Layer (Layer 12)."""
        if not self.scene:
            QMessageBox.information(self, "No Canvas", "Canvas scene reference is not available.")
            return

        ents = self.engine.generate_calibration_entities(
            bed_width_mm=self.spin_width.value(),
            bed_height_mm=self.spin_height.value(),
            inset_mm=self.spin_inset.value(),
            layer_id=12
        )
        for ent in ents:
            self.scene.add_entity(ent)

        QMessageBox.information(
            self,
            "Targets Added",
            f"Placed {len(ents)} alignment target shapes on Tool Layer (Layer 12 / T1)."
        )

    def _on_export_gcode(self):
        """Saves generated calibration G-code to a .nc file."""
        gcode = self.engine.generate_calibration_gcode(
            bed_width_mm=self.spin_width.value(),
            bed_height_mm=self.spin_height.value(),
            inset_mm=self.spin_inset.value()
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration G-Code", "workbed_auto_calibration.nc", "G-Code Files (*.nc *.gcode)"
        )
        if path:
            try:
                with open(path, "w") as f:
                    f.write(gcode)
                QMessageBox.information(self, "Export Successful", f"Saved calibration G-code to:\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "Export Error", f"Could not save file: {e}")

    def _on_apply_calibration(self):
        """Applies auto-calibration to CameraEngine and emits calibration_applied."""
        if not self.current_result or not self.current_result.success:
            return

        self.engine.apply_to_camera_calibration(
            self.camera_engine.calibration, self.current_result
        )
        self.camera_engine.calibration.save_to_file()
        self.calibration_applied.emit(self.camera_engine.calibration)

        QMessageBox.information(
            self,
            "Calibration Applied",
            "Auto-calibration successfully applied and saved!\n\n"
            f"Quality Score: {self.current_result.quality_score:.1f}%\n"
            f"RMS Error: {self.current_result.reprojection_error_rms_mm:.2f} mm ({self.current_result.reprojection_error_rms_px:.1f} px)\n"
            f"Gantry Skew: {self.current_result.gantry_skew_deg:+.2f}°\n\n"
            "The camera workbed overlay has been updated."
        )
        self.accept()

    def closeEvent(self, event):
        self._stop_camera_feed()
        super().closeEvent(event)
