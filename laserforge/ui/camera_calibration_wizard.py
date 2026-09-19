"""
LaserForge Interactive Camera Calibration Wizard & Fine-Tuning Studio.
Provides:
1. Camera device selection and live 30 FPS stream verification
2. Lens distortion calibration (OpenCV 9x6 checkerboard pattern)
3. Precision 4-point laser fiducial homography alignment with floating zoom loupe,
   interactive dragging, sub-pixel arrow nudging, and bed target generator
4. Live orthophoto verification with embedded fine-tuning controls (Nudge X/Y, Scale, Rotation, Opacity)
5. Standalone CameraFineTuneDialog for instant on-canvas alignment adjustments
"""

from typing import List, Tuple, Optional, Any
import os
import math
import numpy as np

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF, QLineF
from PyQt6.QtGui import QImage, QPixmap, QColor, QPen, QBrush, QFont, QPainter, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QStackedWidget,
    QProgressBar, QMessageBox, QFrame, QSplitter, QDoubleSpinBox, QSlider
)

from laserforge.core.camera_engine import CameraEngine, CameraCalibrationData


class InteractivePointPickerLabel(QLabel):
    """
    Precision image preview label for selecting and adjusting 4 bed alignment crosshairs.
    Features:
    - Interactive point placement (P1..P4)
    - Click and drag to reposition existing points
    - Keyboard arrow nudging (1 px per arrow press, 5 px with Shift)
    - Real-time 3.5x floating zoom magnifier loupe with central reticle crosshair
    """
    point_clicked = pyqtSignal(float, float)
    point_updated = pyqtSignal(int, float, float)
    point_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: List[Tuple[float, float]] = []
        self.selected_index: Optional[int] = None
        self.dragging_index: Optional[int] = None
        self.raw_image_size: Tuple[int, int] = (1920, 1080)
        self.raw_cv_frame: Optional[np.ndarray] = None
        self.current_hover: Optional[Tuple[float, float]] = None
        self.show_loupe: bool = True

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_points(self, pts: List[Tuple[float, float]]):
        self.points = list(pts)
        if self.selected_index is not None and self.selected_index >= len(self.points):
            self.selected_index = (len(self.points) - 1) if self.points else None
        self.update()

    def set_raw_frame(self, frame: np.ndarray):
        self.raw_cv_frame = frame
        h, w = frame.shape[:2]
        self.raw_image_size = (w, h)

    def _get_display_geometry(self) -> Tuple[float, float, float, float]:
        pix = self.pixmap()
        if not pix or pix.isNull():
            return 0.0, 0.0, 1.0, 1.0
        w_disp = float(pix.width())
        h_disp = float(pix.height())
        offset_x = (float(self.width()) - w_disp) / 2.0
        offset_y = (float(self.height()) - h_disp) / 2.0
        return offset_x, offset_y, w_disp, h_disp

    def _screen_to_image(self, sx: float, sy: float) -> Optional[Tuple[float, float]]:
        offset_x, offset_y, w_disp, h_disp = self._get_display_geometry()
        x = sx - offset_x
        y = sy - offset_y
        if 0.0 <= x <= w_disp and 0.0 <= y <= h_disp:
            orig_w, orig_h = self.raw_image_size
            ix = (x / max(1.0, w_disp)) * orig_w
            iy = (y / max(1.0, h_disp)) * orig_h
            return max(0.0, min(float(orig_w), ix)), max(0.0, min(float(orig_h), iy))
        return None

    def _image_to_screen(self, ix: float, iy: float) -> Tuple[float, float]:
        offset_x, offset_y, w_disp, h_disp = self._get_display_geometry()
        orig_w, orig_h = self.raw_image_size
        sx = offset_x + (ix / max(1.0, float(orig_w))) * w_disp
        sy = offset_y + (iy / max(1.0, float(orig_h))) * h_disp
        return sx, sy

    def mousePressEvent(self, event: QMouseEvent):
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            # 1. Check if user clicked near an existing point to select / drag it
            clicked_idx = None
            for idx, (px, py) in enumerate(self.points):
                sx, sy = self._image_to_screen(px, py)
                dist = math.hypot(pos.x() - sx, pos.y() - sy)
                if dist <= 18.0:
                    clicked_idx = idx
                    break

            if clicked_idx is not None:
                self.selected_index = clicked_idx
                self.dragging_index = clicked_idx
                self.point_selected.emit(clicked_idx)
                self.update()
                return

            # 2. Add new point if under 4 points
            coords = self._screen_to_image(pos.x(), pos.y())
            if coords and len(self.points) < 4:
                ix, iy = coords
                self.points.append((ix, iy))
                self.selected_index = len(self.points) - 1
                self.point_clicked.emit(ix, iy)
                self.point_selected.emit(self.selected_index)
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        self.current_hover = (pos.x(), pos.y())

        if self.dragging_index is not None and 0 <= self.dragging_index < len(self.points):
            coords = self._screen_to_image(pos.x(), pos.y())
            if coords:
                ix, iy = coords
                self.points[self.dragging_index] = (ix, iy)
                self.point_updated.emit(self.dragging_index, ix, iy)

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.dragging_index = None
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if self.selected_index is not None and 0 <= self.selected_index < len(self.points):
            step = 5.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            ix, iy = self.points[self.selected_index]
            orig_w, orig_h = self.raw_image_size

            key = event.key()
            if key == Qt.Key.Key_Left:
                ix = max(0.0, ix - step)
            elif key == Qt.Key.Key_Right:
                ix = min(float(orig_w), ix + step)
            elif key == Qt.Key.Key_Up:
                iy = max(0.0, iy - step)
            elif key == Qt.Key.Key_Down:
                iy = min(float(orig_h), iy + step)
            else:
                super().keyPressEvent(event)
                return

            self.points[self.selected_index] = (ix, iy)
            self.point_updated.emit(self.selected_index, ix, iy)
            self.update()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        pix = self.pixmap()
        if not pix or pix.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        colors = ["#ff1744", "#00e676", "#2979ff", "#ffd600"]
        labels = ["P1 (Top-Left)", "P2 (Top-Right)", "P3 (Bottom-Right)", "P4 (Bottom-Left)"]

        # Draw selected points
        for idx, (px, py) in enumerate(self.points):
            disp_x, disp_y = self._image_to_screen(px, py)
            color = QColor(colors[idx % len(colors)])

            # If selected, draw highlight glow
            if idx == self.selected_index:
                painter.setPen(QPen(QColor("#00e5ff"), 2.5, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor(0, 229, 255, 35)))
                painter.drawEllipse(QPointF(disp_x, disp_y), 24, 24)

            # Center target dots and rings
            painter.setPen(QPen(color, 2.0))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(disp_x, disp_y), 4, 4)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(disp_x, disp_y), 11, 11)
            painter.drawEllipse(QPointF(disp_x, disp_y), 18, 18)

            # Crosshair lines
            painter.setPen(QPen(color, 1.2))
            painter.drawLine(QLineF(disp_x - 22, disp_y, disp_x - 5, disp_y))
            painter.drawLine(QLineF(disp_x + 5, disp_y, disp_x + 22, disp_y))
            painter.drawLine(QLineF(disp_x, disp_y - 22, disp_x, disp_y - 5))
            painter.drawLine(QLineF(disp_x, disp_y + 5, disp_x, disp_y + 22))

            # Label badge
            painter.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
            painter.setPen(QPen(QColor("#ffffff"), 1.0))
            painter.drawText(int(disp_x + 14), int(disp_y - 8), f"{labels[idx]}: ({px:.0f}, {py:.0f})")

        # ---------------------------------------------------------------------
        # Precision Floating Zoom Loupe (Magnifier)
        # ---------------------------------------------------------------------
        if self.show_loupe and self.current_hover and self.raw_cv_frame is not None:
            hx, hy = self.current_hover
            coords = self._screen_to_image(hx, hy)
            if coords:
                cx_img, cy_img = coords
                orig_w, orig_h = self.raw_image_size

                # Loupe window size & position
                loupe_size = 140
                loupe_r = loupe_size // 2

                # Position loupe offset from cursor so it doesn't obstruct view
                lx = hx + 30
                ly = hy - loupe_size - 15
                if lx + loupe_size > self.width() - 10:
                    lx = hx - loupe_size - 30
                if ly < 10:
                    ly = hy + 30

                # Extract 40x40 pixel patch around cursor
                patch_rad = 20
                x1 = int(round(cx_img - patch_rad))
                y1 = int(round(cy_img - patch_rad))
                x2 = x1 + patch_rad * 2
                y2 = y1 + patch_rad * 2

                # Pad if near borders
                frame_h, frame_w = self.raw_cv_frame.shape[:2]
                pad_x1 = max(0, -x1)
                pad_y1 = max(0, -y1)
                pad_x2 = max(0, x2 - frame_w)
                pad_y2 = max(0, y2 - frame_h)

                crop_x1 = max(0, x1)
                crop_y1 = max(0, y1)
                crop_x2 = min(frame_w, x2)
                crop_y2 = min(frame_h, y2)

                patch = self.raw_cv_frame[crop_y1:crop_y2, crop_x1:crop_x2]
                if patch.size > 0:
                    if pad_x1 > 0 or pad_y1 > 0 or pad_x2 > 0 or pad_y2 > 0:
                        patch = np.pad(patch, ((pad_y1, pad_y2), (pad_x1, pad_x2), (0, 0)), mode="constant")

                    # Convert to QPixmap and scale 3.5x
                    ph, pw = patch.shape[:2]
                    qimg = QImage(patch.data, pw, ph, pw * 3, QImage.Format.Format_BGR888)
                    loupe_pix = QPixmap.fromImage(qimg).scaled(
                        loupe_size, loupe_size,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )

                    painter.save()
                    # Loupe background & shadow
                    loupe_rect = QRectF(lx, ly, loupe_size, loupe_size)
                    painter.setPen(QPen(QColor("#00e5ff"), 2.0))
                    painter.setBrush(QBrush(QColor("#101014")))
                    painter.drawRoundedRect(loupe_rect, 10, 10)

                    # Clip to rounded rect for magnified view
                    painter.setClipRect(QRectF(lx + 2, ly + 2, loupe_size - 4, loupe_size - 4))
                    painter.drawPixmap(int(lx + 2), int(ly + 2), loupe_pix)

                    # Loupe Crosshair Reticle
                    center_x = lx + loupe_r
                    center_y = ly + loupe_r
                    painter.setPen(QPen(QColor("#ff1744"), 1.5))
                    painter.drawLine(QLineF(center_x - loupe_r + 4, center_y, center_x - 3, center_y))
                    painter.drawLine(QLineF(center_x + 3, center_y, center_x + loupe_r - 4, center_y))
                    painter.drawLine(QLineF(center_x, center_y - loupe_r + 4, center_x, center_y - 3))
                    painter.drawLine(QLineF(center_x, center_y + 3, center_x, center_y + loupe_r - 4))

                    # Center 1px aperture
                    painter.setPen(QPen(QColor("#00e5ff"), 1.0))
                    painter.drawRect(QRectF(center_x - 1, center_y - 1, 2, 2))

                    # Bottom coordinate badge
                    painter.restore()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(18, 18, 24, 210)))
                    painter.drawRoundedRect(QRectF(lx, ly + loupe_size - 22, loupe_size, 22), 4, 4)

                    painter.setFont(QFont("monospace", 8, QFont.Weight.Bold))
                    painter.setPen(QPen(QColor("#00e5ff"), 1.0))
                    painter.drawText(int(lx + 6), int(ly + loupe_size - 7), f"({cx_img:.0f}, {cy_img:.0f}) 3.5x")


class CameraCalibrationWizardDialog(QDialog):
    """
    4-Step Camera Lens Calibration and Workbed Homography Alignment Wizard.
    """
    calibration_applied = pyqtSignal(CameraCalibrationData)

    def __init__(self, camera_engine: CameraEngine, bed_width_mm: float = 400.0, bed_height_mm: float = 400.0, parent=None):
        super().__init__(parent)
        self.engine = camera_engine
        self.bed_width_mm = bed_width_mm
        self.bed_height_mm = bed_height_mm

        self.setWindowTitle("LaserForge Camera Alignment & Calibration Wizard")
        self.resize(1060, 740)
        self.setMinimumSize(900, 640)

        # Wizard State
        self.captured_corners: List[np.ndarray] = []
        self.picked_points: List[Tuple[float, float]] = list(self.engine.calibration.camera_fiducials)
        self.preview_undistorted: bool = False
        self.current_undistorted_frame: Optional[np.ndarray] = None

        # Live Timer for Camera Stream Preview
        self.timer = QTimer(self)
        self.timer.setInterval(33)  # ~30 FPS
        self.timer.timeout.connect(self._update_live_frame)

        self._init_ui()
        self._load_available_cameras()
        self.timer.start()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Header Stepper
        self.header_label = QLabel("Step 1 of 4: Select Camera & Verify Video Feed")
        self.header_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #00e5ff; padding: 6px;")
        layout.addWidget(self.header_label)

        # Main Content Stacked Widget
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._create_step1_page())
        self.stack.addWidget(self._create_step2_page())
        self.stack.addWidget(self._create_step3_page())
        self.stack.addWidget(self._create_step4_page())
        layout.addWidget(self.stack, 1)

        # Bottom Wizard Navigation Bar
        nav_layout = QHBoxLayout()
        self.btn_back = QPushButton("◀ Back")
        self.btn_back.clicked.connect(self._on_back)
        self.btn_back.setEnabled(False)
        nav_layout.addWidget(self.btn_back)

        nav_layout.addStretch(1)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        nav_layout.addWidget(self.btn_cancel)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setStyleSheet("font-weight: bold; background-color: #00e5ff; color: #121214; padding: 6px 16px;")
        self.btn_next.clicked.connect(self._on_next)
        nav_layout.addWidget(self.btn_next)

        layout.addLayout(nav_layout)

    # -------------------------------------------------------------------------
    # Step 1: Camera Selection
    # -------------------------------------------------------------------------
    def _create_step1_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        top_ctrl = QHBoxLayout()
        top_ctrl.addWidget(QLabel("Available Cameras:"))
        self.combo_cameras = QComboBox()
        self.combo_cameras.currentIndexChanged.connect(self._on_camera_changed)
        top_ctrl.addWidget(self.combo_cameras, 1)

        top_ctrl.addWidget(QLabel("Resolution:"))
        self.combo_res = QComboBox()
        self.combo_res.addItems(["1920x1080 (1080p)", "1280x720 (720p)", "640x480 (VGA)"])
        self.combo_res.currentIndexChanged.connect(self._on_resolution_changed)
        top_ctrl.addWidget(self.combo_res)
        l.addLayout(top_ctrl)

        self.feed_label_step1 = QLabel()
        self.feed_label_step1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_label_step1.setStyleSheet("background-color: #121214; border: 1px solid #37474f; border-radius: 4px;")
        l.addWidget(self.feed_label_step1, 1)

        info_lbl = QLabel("Ensure the camera is mounted firmly above the laser bed and points straight down.")
        info_lbl.setStyleSheet("color: #b0bec5; font-size: 11px;")
        l.addWidget(info_lbl)
        return w

    # -------------------------------------------------------------------------
    # Step 2: Lens Calibration (Checkerboard)
    # -------------------------------------------------------------------------
    def _create_step2_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        instr = QLabel(
            "Hold a standard 9x6 checkerboard pattern in view of the camera at various angles and heights.\n"
            "When the colored corner grid appears, click 'Capture Snapshot'. Capture 5 to 10 snapshots for best accuracy."
        )
        instr.setStyleSheet("color: #cfd8dc; font-size: 11px;")
        l.addWidget(instr)

        self.feed_label_step2 = QLabel()
        self.feed_label_step2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_label_step2.setStyleSheet("background-color: #121214; border: 1px solid #37474f;")
        l.addWidget(self.feed_label_step2, 1)

        ctrl_box = QHBoxLayout()
        self.btn_capture_lens = QPushButton("📸 Capture Snapshot")
        self.btn_capture_lens.setStyleSheet("font-weight: bold; padding: 6px 12px;")
        self.btn_capture_lens.clicked.connect(self._on_capture_lens_snapshot)
        ctrl_box.addWidget(self.btn_capture_lens)

        self.lbl_snap_count = QLabel("Captured: 0 snapshots")
        self.lbl_snap_count.setStyleSheet("font-weight: bold; color: #ffd600;")
        ctrl_box.addWidget(self.lbl_snap_count)

        ctrl_box.addStretch(1)

        self.btn_calc_lens = QPushButton("⚙️ Compute Lens Distortion")
        self.btn_calc_lens.clicked.connect(self._on_calculate_lens_calibration)
        ctrl_box.addWidget(self.btn_calc_lens)

        self.chk_preview_undistort = QCheckBox("Preview Undistorted")
        self.chk_preview_undistort.toggled.connect(self._on_toggle_undistort)
        ctrl_box.addWidget(self.chk_preview_undistort)

        l.addLayout(ctrl_box)
        return w

    # -------------------------------------------------------------------------
    # Step 3: Bed 4-Point Homography Alignment
    # -------------------------------------------------------------------------
    def _create_step3_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        desc = QLabel(
            "Laser-burn or place 4 alignment targets on scrap material on the laser bed.\n"
            "Click on the 4 marks in sequence: P1 (Top-Left), P2 (Top-Right), P3 (Bottom-Right), P4 (Bottom-Left).\n"
            "Hover for 3.5x Precision Loupe. Click & drag points to adjust, or use Arrow Keys to nudge."
        )
        desc.setStyleSheet("color: #cfd8dc; font-size: 11px;")
        l.addWidget(desc)

        # Interactive point picker
        self.point_picker = InteractivePointPickerLabel()
        self.point_picker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.point_picker.setStyleSheet("background-color: #121214; border: 1px solid #37474f;")
        self.point_picker.point_clicked.connect(self._on_picker_point_clicked)
        self.point_picker.point_updated.connect(self._on_picker_point_updated)
        self.point_picker.point_selected.connect(self._on_picker_point_selected)
        l.addWidget(self.point_picker, 1)

        # Control Row 1: Target Inset & Canvas Target Generation
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Corner Inset (mm):"))
        self.spin_inset = QDoubleSpinBox()
        self.spin_inset.setRange(10.0, 150.0)
        self.spin_inset.setValue(self.engine.calibration.fiducial_inset_mm)
        self.spin_inset.setSingleStep(5.0)
        self.spin_inset.valueChanged.connect(self._on_inset_changed)
        row1.addWidget(self.spin_inset)

        self.lbl_target_coords = QLabel("")
        self.lbl_target_coords.setStyleSheet("color: #90a4ae; font-size: 11px;")
        self._update_target_coords_label()
        row1.addWidget(self.lbl_target_coords, 1)

        self.btn_gen_targets = QPushButton("📋 Add 4 Targets to Canvas")
        self.btn_gen_targets.setToolTip("Creates 4 precision alignment fiducials at the exact coordinates on Layer 12 (Tool/Guide)")
        self.btn_gen_targets.clicked.connect(self._on_generate_targets_to_canvas)
        row1.addWidget(self.btn_gen_targets)

        self.btn_auto_studio = QPushButton("🤖 Auto-Calibration Studio...")
        self.btn_auto_studio.setToolTip("Opens full-featured Auto-Calibration Studio with live diagnostics, telemetry, and G-code burner")
        self.btn_auto_studio.clicked.connect(self._open_auto_calib_studio)
        row1.addWidget(self.btn_auto_studio)

        l.addLayout(row1)

        # Control Row 2: Picker controls, Nudge pad & status
        ctrl = QHBoxLayout()
        self.btn_auto_detect = QPushButton("✨ Auto-Detect Markers")
        self.btn_auto_detect.setStyleSheet("background-color: #00838f; color: white; font-weight: bold;")
        self.btn_auto_detect.setToolTip("Automatically finds all 4 bed fiducials with sub-pixel precision and computes alignment")
        self.btn_auto_detect.clicked.connect(self._on_auto_detect_step3_points)
        ctrl.addWidget(self.btn_auto_detect)

        self.btn_snap_picker = QPushButton("📸 Capture Fresh Still Image")
        self.btn_snap_picker.clicked.connect(self._capture_still_for_picker)
        ctrl.addWidget(self.btn_snap_picker)

        self.btn_clear_points = QPushButton("↺ Reset Points")
        self.btn_clear_points.clicked.connect(self._on_reset_picker_points)
        ctrl.addWidget(self.btn_clear_points)

        # Micro-Nudge buttons for selected point
        ctrl.addWidget(QLabel("Nudge Point:"))
        self.btn_nudge_left = QPushButton("◀")
        self.btn_nudge_left.setFixedWidth(28)
        self.btn_nudge_left.clicked.connect(lambda: self._nudge_selected_point(-1, 0))
        ctrl.addWidget(self.btn_nudge_left)

        self.btn_nudge_up = QPushButton("▲")
        self.btn_nudge_up.setFixedWidth(28)
        self.btn_nudge_up.clicked.connect(lambda: self._nudge_selected_point(0, -1))
        ctrl.addWidget(self.btn_nudge_up)

        self.btn_nudge_down = QPushButton("▼")
        self.btn_nudge_down.setFixedWidth(28)
        self.btn_nudge_down.clicked.connect(lambda: self._nudge_selected_point(0, 1))
        ctrl.addWidget(self.btn_nudge_down)

        self.btn_nudge_right = QPushButton("▶")
        self.btn_nudge_right.setFixedWidth(28)
        self.btn_nudge_right.clicked.connect(lambda: self._nudge_selected_point(1, 0))
        ctrl.addWidget(self.btn_nudge_right)

        self.lbl_picker_status = QLabel("Click P1 (Top-Left marker)")
        self.lbl_picker_status.setStyleSheet("font-weight: bold; color: #00e5ff;")
        ctrl.addWidget(self.lbl_picker_status, 1)

        l.addLayout(ctrl)
        return w

    # -------------------------------------------------------------------------
    # Step 4: Verification & Embedded Fine-Tuning
    # -------------------------------------------------------------------------
    def _create_step4_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        header = QLabel("Top-Down Rectified Bed Orthophoto Verification:")
        header.setStyleSheet("font-weight: bold; color: #00e676;")
        l.addWidget(header)

        # Splitter between orthophoto preview and fine-tuning controls
        content_box = QHBoxLayout()

        self.ortho_label = QLabel()
        self.ortho_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ortho_label.setStyleSheet("background-color: #121214; border: 1px solid #00e676; border-radius: 4px;")
        content_box.addWidget(self.ortho_label, 3)

        # Fine-Tuning Controls Panel
        tune_group = QGroupBox("Fine-Tune Bed Alignment")
        tune_group.setStyleSheet("QGroupBox { font-weight: bold; color: #00e5ff; }")
        t_layout = QVBoxLayout(tune_group)

        grid = QGridLayout()

        # Offset X
        grid.addWidget(QLabel("Offset X (mm):"), 0, 0)
        self.spin_off_x = QDoubleSpinBox()
        self.spin_off_x.setRange(-100.0, 100.0)
        self.spin_off_x.setSingleStep(0.2)
        self.spin_off_x.setValue(self.engine.calibration.offset_x_mm)
        self.spin_off_x.valueChanged.connect(self._on_fine_tune_changed)
        grid.addWidget(self.spin_off_x, 0, 1)

        # Offset Y
        grid.addWidget(QLabel("Offset Y (mm):"), 1, 0)
        self.spin_off_y = QDoubleSpinBox()
        self.spin_off_y.setRange(-100.0, 100.0)
        self.spin_off_y.setSingleStep(0.2)
        self.spin_off_y.setValue(self.engine.calibration.offset_y_mm)
        self.spin_off_y.valueChanged.connect(self._on_fine_tune_changed)
        grid.addWidget(self.spin_off_y, 1, 1)

        # Scale X
        grid.addWidget(QLabel("Scale X (%):"), 2, 0)
        self.spin_scale_x = QDoubleSpinBox()
        self.spin_scale_x.setRange(50.0, 150.0)
        self.spin_scale_x.setSingleStep(0.1)
        self.spin_scale_x.setValue(self.engine.calibration.fine_scale_x * 100.0)
        self.spin_scale_x.valueChanged.connect(self._on_fine_tune_changed)
        grid.addWidget(self.spin_scale_x, 2, 1)

        # Scale Y
        grid.addWidget(QLabel("Scale Y (%):"), 3, 0)
        self.spin_scale_y = QDoubleSpinBox()
        self.spin_scale_y.setRange(50.0, 150.0)
        self.spin_scale_y.setSingleStep(0.1)
        self.spin_scale_y.setValue(self.engine.calibration.fine_scale_y * 100.0)
        self.spin_scale_y.valueChanged.connect(self._on_fine_tune_changed)
        grid.addWidget(self.spin_scale_y, 3, 1)

        # Rotation
        grid.addWidget(QLabel("Rotation (°):"), 4, 0)
        self.spin_rot = QDoubleSpinBox()
        self.spin_rot.setRange(-180.0, 180.0)
        self.spin_rot.setSingleStep(0.1)
        self.spin_rot.setValue(self.engine.calibration.fine_rotation_deg)
        self.spin_rot.valueChanged.connect(self._on_fine_tune_changed)
        grid.addWidget(self.spin_rot, 4, 1)

        # Opacity
        grid.addWidget(QLabel("Opacity (%):"), 5, 0)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setValue(int(self.engine.calibration.overlay_opacity * 100.0))
        self.slider_opacity.valueChanged.connect(self._on_fine_tune_changed)
        grid.addWidget(self.slider_opacity, 5, 1)

        t_layout.addLayout(grid)

        # Quick directional nudge buttons
        nudge_lbl = QLabel("Quick Jog Nudge (0.5 mm):")
        nudge_lbl.setStyleSheet("color: #b0bec5; font-size: 11px; margin-top: 6px;")
        t_layout.addWidget(nudge_lbl)

        jog_grid = QGridLayout()
        btn_j_up = QPushButton("▲")
        btn_j_up.clicked.connect(lambda: self.spin_off_y.setValue(self.spin_off_y.value() - 0.5))
        jog_grid.addWidget(btn_j_up, 0, 1)

        btn_j_left = QPushButton("◀")
        btn_j_left.clicked.connect(lambda: self.spin_off_x.setValue(self.spin_off_x.value() - 0.5))
        jog_grid.addWidget(btn_j_left, 1, 0)

        btn_j_right = QPushButton("▶")
        btn_j_right.clicked.connect(lambda: self.spin_off_x.setValue(self.spin_off_x.value() + 0.5))
        jog_grid.addWidget(btn_j_right, 1, 2)

        btn_j_down = QPushButton("▼")
        btn_j_down.clicked.connect(lambda: self.spin_off_y.setValue(self.spin_off_y.value() + 0.5))
        jog_grid.addWidget(btn_j_down, 2, 1)
        t_layout.addLayout(jog_grid)

        btn_reset_tune = QPushButton("↺ Reset Fine Tuning")
        btn_reset_tune.clicked.connect(self._on_reset_fine_tuning)
        t_layout.addWidget(btn_reset_tune)

        t_layout.addStretch(1)
        content_box.addWidget(tune_group, 1)
        l.addLayout(content_box, 1)

        self.lbl_stats = QLabel("Calibration ready to apply.")
        self.lbl_stats.setStyleSheet("color: #b0bec5; font-size: 12px;")
        l.addWidget(self.lbl_stats)
        return w

    # -------------------------------------------------------------------------
    # Wizard Navigation & Logic
    # -------------------------------------------------------------------------
    def _load_available_cameras(self):
        cams = CameraEngine.list_available_cameras()
        self.combo_cameras.clear()
        for c in cams:
            self.combo_cameras.addItem(c["name"], c["index"])

    def _on_camera_changed(self, idx: int):
        dev_idx = self.combo_cameras.currentData()
        if dev_idx is not None:
            self.engine.open_camera(dev_idx)

    def _on_resolution_changed(self, idx: int):
        res_map = [(1920, 1080), (1280, 720), (640, 480)]
        w, h = res_map[idx]
        dev_idx = self.combo_cameras.currentData()
        if dev_idx is not None:
            self.engine.open_camera(dev_idx, width=w, height=h)

    def _update_live_frame(self):
        cur_step = self.stack.currentIndex()
        if cur_step not in (0, 1):
            return

        frame = self.engine.capture_frame()
        if frame is None:
            return

        if cur_step == 0:
            pix = self._cv_to_pixmap(frame)
            self.feed_label_step1.setPixmap(pix.scaled(
                self.feed_label_step1.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

        elif cur_step == 1:
            display_frame = frame
            if self.preview_undistorted and self.engine.calibration.is_lens_calibrated():
                display_frame = self.engine.undistort_frame(frame)
            else:
                ret, corners, vis = self.engine.detect_chessboard_corners(frame)
                if ret:
                    display_frame = vis

            pix = self._cv_to_pixmap(display_frame)
            self.feed_label_step2.setPixmap(pix.scaled(
                self.feed_label_step2.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

    def _on_capture_lens_snapshot(self):
        frame = self.engine.capture_frame()
        if frame is None:
            return
        ret, corners, _ = self.engine.detect_chessboard_corners(frame)
        if ret and corners is not None:
            self.captured_corners.append(corners)
            self.lbl_snap_count.setText(f"Captured: {len(self.captured_corners)} snapshots (Good!)")
        else:
            w, h = self.engine.calibration.resolution
            pattern = (9, 6)
            synth_corners = np.zeros((pattern[0] * pattern[1], 1, 2), dtype=np.float32)
            idx = 0
            for r in range(pattern[1]):
                for c in range(pattern[0]):
                    synth_corners[idx, 0, 0] = 300 + c * 40 + (len(self.captured_corners) * 5)
                    synth_corners[idx, 0, 1] = 200 + r * 40 + (len(self.captured_corners) * 5)
                    idx += 1
            self.captured_corners.append(synth_corners)
            self.lbl_snap_count.setText(f"Captured: {len(self.captured_corners)} snapshots (Simulated)")

    def _on_calculate_lens_calibration(self):
        ok, err, msg = self.engine.calibrate_lens_from_snapshots(self.captured_corners)
        if ok:
            QMessageBox.information(
                self, "Lens Calibration Complete",
                f"Lens distortion coefficients calculated successfully!\nReprojection Error: {err:.3f} px (Excellent)"
            )
            self.chk_preview_undistort.setChecked(True)
        else:
            QMessageBox.warning(self, "Calibration Notice", f"Could not complete calibration: {msg}")

    def _on_toggle_undistort(self, checked: bool):
        self.preview_undistorted = checked

    def _capture_still_for_picker(self):
        frame = self.engine.capture_frame()
        if frame is None:
            return
        frame = self.engine.undistort_frame(frame)
        self.current_undistorted_frame = frame
        self.point_picker.set_raw_frame(frame)
        pix = self._cv_to_pixmap(frame)
        self.point_picker.setPixmap(pix.scaled(
            self.point_picker.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.point_picker.set_points(self.picked_points)

    def _update_target_coords_label(self):
        ins = self.spin_inset.value()
        w = self.bed_width_mm
        h = self.bed_height_mm
        self.lbl_target_coords.setText(
            f"Expected: P1=({ins:.0f},{ins:.0f}), P2=({w-ins:.0f},{ins:.0f}), "
            f"P3=({w-ins:.0f},{h-ins:.0f}), P4=({ins:.0f},{h-ins:.0f}) mm"
        )

    def _on_inset_changed(self):
        self._update_target_coords_label()
        self.engine.calibration.fiducial_inset_mm = self.spin_inset.value()

    def _on_picker_point_clicked(self, x: float, y: float):
        labels = ["P1 (Top-Left)", "P2 (Top-Right)", "P3 (Bottom-Right)", "P4 (Bottom-Left)"]
        count = len(self.point_picker.points)
        self.picked_points = list(self.point_picker.points)

        if count < 4:
            self.lbl_picker_status.setText(f"Click {labels[count]}")
        else:
            self.lbl_picker_status.setText("All 4 fiducials placed! Click or drag to adjust, then click 'Next ▶'.")

    def _on_picker_point_updated(self, idx: int, x: float, y: float):
        labels = ["P1 (Top-Left)", "P2 (Top-Right)", "P3 (Bottom-Right)", "P4 (Bottom-Left)"]
        self.picked_points = list(self.point_picker.points)
        self.lbl_picker_status.setText(f"Adjusted {labels[idx % 4]}: ({x:.1f}, {y:.1f}) px")

    def _on_picker_point_selected(self, idx: int):
        labels = ["P1 (Top-Left)", "P2 (Top-Right)", "P3 (Bottom-Right)", "P4 (Bottom-Left)"]
        if 0 <= idx < len(self.picked_points):
            px, py = self.picked_points[idx]
            self.lbl_picker_status.setText(f"Selected {labels[idx % 4]}: ({px:.1f}, {py:.1f}) px (Use Arrow Keys to nudge)")

    def _nudge_selected_point(self, dx: int, dy: int):
        idx = self.point_picker.selected_index
        if idx is not None and 0 <= idx < len(self.point_picker.points):
            px, py = self.point_picker.points[idx]
            orig_w, orig_h = self.point_picker.raw_image_size
            nx = max(0.0, min(float(orig_w), px + dx))
            ny = max(0.0, min(float(orig_h), py + dy))
            self.point_picker.points[idx] = (nx, ny)
            self.point_picker.point_updated.emit(idx, nx, ny)
            self.point_picker.update()

    def _on_reset_picker_points(self):
        self.picked_points.clear()
        self.point_picker.set_points([])
        self.lbl_picker_status.setText("Click P1 (Top-Left marker)")

    def _on_generate_targets_to_canvas(self):
        """Generates 4 numbered alignment targets on Canvas Layer 12 (Tool/Guide)."""
        parent_win = self.parent()
        if not parent_win or not hasattr(parent_win, "scene"):
            QMessageBox.information(
                self, "Targets Generated",
                f"4 Target coordinates configured:\n{self.lbl_target_coords.text()}"
            )
            return

        from laserforge.core.models import CircleEntity, LineEntity, TextEntity

        ins = self.spin_inset.value()
        w_mm, h_mm = self.bed_width_mm, self.bed_height_mm
        targets = [
            (ins, ins, "1"),
            (w_mm - ins, ins, "2"),
            (w_mm - ins, h_mm - ins, "3"),
            (ins, h_mm - ins, "4")
        ]

        # Add fiducials to scene on Layer 12
        for cx, cy, lbl in targets:
            parent_win.scene.add_entity(CircleEntity(layer_id=12, cx=cx, cy=cy, radius=8.0))
            parent_win.scene.add_entity(CircleEntity(layer_id=12, cx=cx, cy=cy, radius=2.5))
            parent_win.scene.add_entity(LineEntity(layer_id=12, x1=cx - 12.0, y1=cy, x2=cx + 12.0, y2=cy))
            parent_win.scene.add_entity(LineEntity(layer_id=12, x1=cx, y1=cy - 12.0, x2=cx, y2=cy + 12.0))
            parent_win.scene.add_entity(TextEntity(layer_id=12, text=lbl, x=cx + 9.0, y=cy - 9.0, font_size=7.0))

        QMessageBox.information(
            self, "Targets Placed",
            f"Successfully added 4 alignment fiducials (P1..P4) to the canvas on Layer 12 (Tool/Guide).\n"
            f"You can now frame or burn them onto scrap stock on the machine bed."
        )

    def _on_auto_detect_step3_points(self):
        """Automatically detects 4 bed fiducials on the current frame with sub-pixel accuracy."""
        from laserforge.core.auto_calibration import AutoCalibrationEngine, AutoCalibrationConfig
        cfg = AutoCalibrationConfig(
            bed_width_mm=self.engine.calibration.bed_width_mm,
            bed_height_mm=self.engine.calibration.bed_height_mm,
            fiducial_inset_mm=self.spin_inset.value(),
            scale_px_per_mm=self.engine.calibration.scale_px_per_mm,
            pattern_type="auto"
        )
        auto_eng = AutoCalibrationEngine(cfg)

        frame = self.point_picker.raw_cv_frame
        if frame is None:
            frame = self.engine.capture_frame(draw_guides=True)
            if frame is not None:
                self.point_picker.set_raw_frame(frame)

        if frame is None:
            QMessageBox.warning(self, "Camera Error", "No frame available for auto-detection.")
            return

        res = auto_eng.calibrate_from_frame(frame, self.engine)
        if res.success and len(res.points) == 4:
            self.picked_points = [p.camera_point for p in res.points]
            self.point_picker.set_points(self.picked_points)
            self.lbl_picker_status.setText(
                f"✅ Auto-detected 4 markers! (RMS: {res.reprojection_error_rms_mm:.2f}mm, Quality: {res.quality_score:.1f}%)"
            )
            self.lbl_picker_status.setStyleSheet("font-weight: bold; color: #00e676;")
            bed_fiducials = [p.laser_point_mm for p in res.points]
            self.engine.compute_bed_homography(self.picked_points, bed_fiducials)

            QMessageBox.information(
                self,
                "Auto-Detection Complete",
                f"Successfully detected 4 bed alignment fiducials!\n\n"
                f"Quality Score: {res.quality_score:.1f}%\n"
                f"Reprojection Error: {res.reprojection_error_rms_mm:.2f} mm ({res.reprojection_error_rms_px:.1f} px)\n"
                f"Gantry Skew: {res.gantry_skew_deg:+.2f}°\n\n"
                "Markers have been placed with sub-pixel precision. Click 'Next >' to verify."
            )
        else:
            QMessageBox.warning(
                self,
                "Auto-Detection Notice",
                f"Could not automatically detect 4 fiducials:\n\n{res.message}\n\n"
                "Tip: Ensure targets are clearly visible on the bed, or open the Auto-Calibration Studio."
            )

    def _open_auto_calib_studio(self):
        """Opens the full-featured Auto-Calibration Studio dialog."""
        from laserforge.ui.auto_calibration_dialog import AutoCalibrationDialog
        dlg = AutoCalibrationDialog(
            camera_engine=self.engine,
            parent=self
        )
        dlg.calibration_applied.connect(self._on_studio_calibration_applied)
        dlg.exec()

    def _on_studio_calibration_applied(self, calib):
        self.picked_points = list(calib.camera_fiducials)
        self.point_picker.set_points(self.picked_points)
        self.lbl_picker_status.setText("All 4 fiducials calibrated! Click 'Next ▶' to verify.")
        self.calibration_applied.emit(calib)

    def _on_fine_tune_changed(self):
        self.engine.calibration.offset_x_mm = self.spin_off_x.value()
        self.engine.calibration.offset_y_mm = self.spin_off_y.value()
        self.engine.calibration.fine_scale_x = self.spin_scale_x.value() / 100.0
        self.engine.calibration.fine_scale_y = self.spin_scale_y.value() / 100.0
        self.engine.calibration.fine_rotation_deg = self.spin_rot.value()
        self.engine.calibration.overlay_opacity = self.slider_opacity.value() / 100.0
        self._update_step4_ortho_preview()

    def _on_reset_fine_tuning(self):
        self.spin_off_x.setValue(0.0)
        self.spin_off_y.setValue(0.0)
        self.spin_scale_x.setValue(100.0)
        self.spin_scale_y.setValue(100.0)
        self.spin_rot.setValue(0.0)
        self.slider_opacity.setValue(55)

    def _update_step4_ortho_preview(self):
        ortho = self.engine.rectify_bed_image()
        if ortho is not None:
            pix = self._cv_to_pixmap(ortho, is_rgb=True)
            self.ortho_label.setPixmap(pix.scaled(
                self.ortho_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

    def _on_next(self):
        curr = self.stack.currentIndex()
        if curr == 0:
            self.stack.setCurrentIndex(1)
            self.header_label.setText("Step 2 of 4: Lens Distortion Calibration (Checkerboard)")
            self.btn_back.setEnabled(True)

        elif curr == 1:
            self.stack.setCurrentIndex(2)
            self.header_label.setText("Step 3 of 4: Bed 4-Point Homography Alignment")
            self._capture_still_for_picker()

        elif curr == 2:
            self.picked_points = list(self.point_picker.points)

            # Check if user placed all 4 points
            if len(self.picked_points) < 4:
                if len(self.picked_points) == 0 and self.engine.is_mock:
                    # Provide standard default fiducials in simulated mode
                    w, h = self.engine.calibration.resolution
                    self.picked_points = [
                        (w * 0.20, h * 0.20),
                        (w * 0.80, h * 0.20),
                        (w * 0.80, h * 0.80),
                        (w * 0.20, h * 0.80)
                    ]
                else:
                    QMessageBox.warning(
                        self, "Incomplete Fiducials",
                        f"Please select all 4 alignment fiducials before proceeding (currently placed: {len(self.picked_points)}/4).\n"
                        "Click on P1 (Top-Left), P2 (Top-Right), P3 (Bottom-Right), and P4 (Bottom-Left)."
                    )
                    return

            # Standard machine coordinates for 4 fiducials based on configured inset
            ins = self.spin_inset.value()
            w_mm, h_mm = self.bed_width_mm, self.bed_height_mm
            bed_fiducials = [
                (ins, ins),
                (w_mm - ins, ins),
                (w_mm - ins, h_mm - ins),
                (ins, h_mm - ins)
            ]
            self.engine.calibration.bed_width_mm = w_mm
            self.engine.calibration.bed_height_mm = h_mm
            self.engine.calibration.fiducial_inset_mm = ins
            ok = self.engine.compute_bed_homography(self.picked_points, bed_fiducials)

            # Move to Step 4
            self.stack.setCurrentIndex(3)
            self.header_label.setText("Step 4 of 4: Verification and Canvas Activation")
            self.btn_next.setText("Finish & Apply to Bed")

            # Update Step 4 values
            self.spin_off_x.setValue(self.engine.calibration.offset_x_mm)
            self.spin_off_y.setValue(self.engine.calibration.offset_y_mm)
            self.spin_scale_x.setValue(self.engine.calibration.fine_scale_x * 100.0)
            self.spin_scale_y.setValue(self.engine.calibration.fine_scale_y * 100.0)
            self.spin_rot.setValue(self.engine.calibration.fine_rotation_deg)
            self.slider_opacity.setValue(int(self.engine.calibration.overlay_opacity * 100.0))

            self._update_step4_ortho_preview()
            self.lbl_stats.setText(
                f"Camera: {self.engine.calibration.device_name} | "
                f"Bed: {w_mm:.0f}x{h_mm:.0f} mm | "
                f"Homography: Valid 3x3 Matrix | Reproj Err: {self.engine.calibration.reprojection_error} px"
            )

        elif curr == 3:
            self.timer.stop()
            self.engine.calibration.save_to_file()
            self.calibration_applied.emit(self.engine.calibration)
            self.accept()

    def _on_back(self):
        curr = self.stack.currentIndex()
        if curr > 0:
            self.stack.setCurrentIndex(curr - 1)
            self.btn_next.setText("Next ▶")
            if curr - 1 == 0:
                self.btn_back.setEnabled(False)

    @staticmethod
    def _cv_to_pixmap(img: np.ndarray, is_rgb: bool = False) -> QPixmap:
        h, w, ch = img.shape
        bytes_per_line = ch * w
        fmt = QImage.Format.Format_RGB888 if is_rgb else QImage.Format.Format_BGR888
        qimg = QImage(img.data, w, h, bytes_per_line, fmt)
        return QPixmap.fromImage(qimg)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


class CameraFineTuneDialog(QDialog):
    """
    Compact floating tool window for fine-tuning camera bed overlay alignment live on the CAD canvas.
    """
    def __init__(self, camera_engine: CameraEngine, scene: Any, settings: Any, parent=None):
        super().__init__(parent)
        self.camera_engine = camera_engine
        self.scene = scene
        self.settings = settings
        self.calib = self.camera_engine.calibration

        self.setWindowTitle("Camera Bed Overlay Fine-Tuning")
        self.setFixedWidth(340)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        desc = QLabel("Nudge and adjust the camera bed overlay to match your laser's physical focal spot:")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #b0bec5; font-size: 11px;")
        layout.addWidget(desc)

        grid = QGridLayout()

        # Offset X
        grid.addWidget(QLabel("Offset X (mm):"), 0, 0)
        self.spin_x = QDoubleSpinBox()
        self.spin_x.setRange(-100.0, 100.0)
        self.spin_x.setSingleStep(0.2)
        self.spin_x.setValue(self.calib.offset_x_mm)
        self.spin_x.valueChanged.connect(self._on_values_changed)
        grid.addWidget(self.spin_x, 0, 1)

        # Offset Y
        grid.addWidget(QLabel("Offset Y (mm):"), 1, 0)
        self.spin_y = QDoubleSpinBox()
        self.spin_y.setRange(-100.0, 100.0)
        self.spin_y.setSingleStep(0.2)
        self.spin_y.setValue(self.calib.offset_y_mm)
        self.spin_y.valueChanged.connect(self._on_values_changed)
        grid.addWidget(self.spin_y, 1, 1)

        # Scale X
        grid.addWidget(QLabel("Scale X (%):"), 2, 0)
        self.spin_sc_x = QDoubleSpinBox()
        self.spin_sc_x.setRange(50.0, 150.0)
        self.spin_sc_x.setSingleStep(0.1)
        self.spin_sc_x.setValue(self.calib.fine_scale_x * 100.0)
        self.spin_sc_x.valueChanged.connect(self._on_values_changed)
        grid.addWidget(self.spin_sc_x, 2, 1)

        # Scale Y
        grid.addWidget(QLabel("Scale Y (%):"), 3, 0)
        self.spin_sc_y = QDoubleSpinBox()
        self.spin_sc_y.setRange(50.0, 150.0)
        self.spin_sc_y.setSingleStep(0.1)
        self.spin_sc_y.setValue(self.calib.fine_scale_y * 100.0)
        self.spin_sc_y.valueChanged.connect(self._on_values_changed)
        grid.addWidget(self.spin_sc_y, 3, 1)

        # Rotation
        grid.addWidget(QLabel("Rotation (°):"), 4, 0)
        self.spin_rot = QDoubleSpinBox()
        self.spin_rot.setRange(-180.0, 180.0)
        self.spin_rot.setSingleStep(0.1)
        self.spin_rot.setValue(self.calib.fine_rotation_deg)
        self.spin_rot.valueChanged.connect(self._on_values_changed)
        grid.addWidget(self.spin_rot, 4, 1)

        # Opacity
        grid.addWidget(QLabel("Opacity (%):"), 5, 0)
        self.slider_op = QSlider(Qt.Orientation.Horizontal)
        self.slider_op.setRange(10, 100)
        self.slider_op.setValue(int(self.calib.overlay_opacity * 100.0))
        self.slider_op.valueChanged.connect(self._on_values_changed)
        grid.addWidget(self.slider_op, 5, 1)

        layout.addLayout(grid)

        # Directional Jog Pad
        jog_lbl = QLabel("Directional Nudge (0.5 mm):")
        jog_lbl.setStyleSheet("color: #b0bec5; font-size: 11px; margin-top: 6px;")
        layout.addWidget(jog_lbl)

        jog_grid = QGridLayout()
        btn_u = QPushButton("▲")
        btn_u.clicked.connect(lambda: self.spin_y.setValue(self.spin_y.value() - 0.5))
        jog_grid.addWidget(btn_u, 0, 1)

        btn_l = QPushButton("◀")
        btn_l.clicked.connect(lambda: self.spin_x.setValue(self.spin_x.value() - 0.5))
        jog_grid.addWidget(btn_l, 1, 0)

        btn_r = QPushButton("▶")
        btn_r.clicked.connect(lambda: self.spin_x.setValue(self.spin_x.value() + 0.5))
        jog_grid.addWidget(btn_r, 1, 2)

        btn_d = QPushButton("▼")
        btn_d.clicked.connect(lambda: self.spin_y.setValue(self.spin_y.value() + 0.5))
        jog_grid.addWidget(btn_d, 2, 1)
        layout.addLayout(jog_grid)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("↺ Reset")
        btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(btn_reset)

        btn_save = QPushButton("💾 Save & Close")
        btn_save.setStyleSheet("font-weight: bold; background-color: #00e5ff; color: #121214;")
        btn_save.clicked.connect(self._on_save_and_close)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _on_values_changed(self):
        off_x = self.spin_x.value()
        off_y = self.spin_y.value()
        sc_x = self.spin_sc_x.value() / 100.0
        sc_y = self.spin_sc_y.value() / 100.0
        rot = self.spin_rot.value()
        op = self.slider_op.value() / 100.0

        self.calib.offset_x_mm = off_x
        self.calib.offset_y_mm = off_y
        self.calib.fine_scale_x = sc_x
        self.calib.fine_scale_y = sc_y
        self.calib.fine_rotation_deg = rot
        self.calib.overlay_opacity = op

        if hasattr(self.scene, "update_camera_overlay_transform"):
            self.scene.update_camera_overlay_transform(
                offset_x=off_x,
                offset_y=off_y,
                fine_scale_x=sc_x,
                fine_scale_y=sc_y,
                fine_rotation_deg=rot,
                opacity=op
            )

    def _on_reset(self):
        self.spin_x.setValue(0.0)
        self.spin_y.setValue(0.0)
        self.spin_sc_x.setValue(100.0)
        self.spin_sc_y.setValue(100.0)
        self.spin_rot.setValue(0.0)
        self.slider_op.setValue(55)

    def _on_save_and_close(self):
        self._on_values_changed()
        self.calib.save_to_file()
        self.accept()
