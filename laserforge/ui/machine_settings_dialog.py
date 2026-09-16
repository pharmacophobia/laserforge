"""
LaserForge Machine & Laser Settings Configuration Dialog.
Provides comprehensive control over workbed geometry, laser firing delays,
overscan lead-in/lead-out compensation, kinematics ($100-$122), interactive step calibration,
custom Start/End G-code scripts, air assist delays, and real-time GRBL 1.1 $$ EEPROM sync.
"""

from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
    QGroupBox, QDialogButtonBox, QCheckBox, QTabWidget,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QLineEdit, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from laserforge.config import MachineSettings
from laserforge.core.serial_controller import SerialController, GRBL_SETTING_DESCRIPTIONS
from laserforge.core.gpu_accelerator import GPUAccelerator


class MachineSettingsDialog(QDialog):
    def __init__(
        self,
        settings: MachineSettings,
        parent=None,
        serial_ctrl: Optional[SerialController] = None
    ):
        super().__init__(parent)
        self.settings = settings
        self.serial_ctrl = serial_ctrl

        self.setWindowTitle("Machine & Laser Settings - LaserForge")
        self.resize(760, 600)
        self.setMinimumSize(640, 520)

        self._init_ui()
        self._load_values()

        if self.serial_ctrl:
            self.serial_ctrl.grbl_settings_updated.connect(self._on_grbl_settings_updated)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Connection Header Banner
        self.header_banner = QFrame()
        self.header_banner.setFrameShape(QFrame.Shape.StyledPanel)
        banner_layout = QHBoxLayout(self.header_banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)

        conn_status = "Disconnected"
        conn_color = "#bdbdbd"
        conn_bg = "#424242"
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            conn_status = f"Connected to {self.serial_ctrl.port_name} (GRBL)"
            conn_color = "#a5d6a7"
            conn_bg = "#1b5e20"

        self.lbl_conn_status = QLabel(f"● Laser Controller: {conn_status}")
        self.lbl_conn_status.setStyleSheet(f"color: {conn_color}; font-weight: bold;")
        banner_layout.addWidget(self.lbl_conn_status)

        banner_layout.addStretch(1)
        self.header_banner.setStyleSheet(f"background-color: {conn_bg}; border-radius: 4px;")
        main_layout.addWidget(self.header_banner)

        # Tab Widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        # 1. Workbed & Origin Tab
        self.tabs.addTab(self._create_bed_tab(), "Workbed && Origin")

        # 2. Laser & Firing Tab
        self.tabs.addTab(self._create_laser_firing_tab(), "Laser && Firing")

        # 3. Overscan & Raster Tab
        self.tabs.addTab(self._create_overscan_tab(), "Overscan && Raster")

        # 4. Motion & Kinematics Tab
        self.tabs.addTab(self._create_motion_tab(), "Motion && Calibration")

        # 5. G-Code & Scripts Tab
        self.tabs.addTab(self._create_gcode_tab(), "G-Code && Scripts")

        # 6. Air Assist & Peripherals Tab
        self.tabs.addTab(self._create_air_tab(), "Air && Accessories")

        # 7. GPU & Performance Tab
        self.tabs.addTab(self._create_gpu_tab(), "GPU && Performance")

        # 8. GRBL Firmware ($$) Tab
        self.tabs.addTab(self._create_grbl_tab(), "GRBL Firmware ($$)")

        # Bottom Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._save_and_accept)
        btn_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply_settings)
        btn_box.rejected.connect(self.reject)
        main_layout.addWidget(btn_box)

    # -------------------------------------------------------------
    # Tab 1: Workbed & Origin
    # -------------------------------------------------------------
    def _create_bed_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # Dimensions Box
        geom_group = QGroupBox("Workbed Dimensions")
        geom_grid = QGridLayout(geom_group)

        geom_grid.addWidget(QLabel("Width X (mm):"), 0, 0)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(20.0, 5000.0)
        self.width_spin.setSuffix(" mm")
        geom_grid.addWidget(self.width_spin, 0, 1)

        geom_grid.addWidget(QLabel("Height Y (mm):"), 1, 0)
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(20.0, 5000.0)
        self.height_spin.setSuffix(" mm")
        geom_grid.addWidget(self.height_spin, 1, 1)

        geom_grid.addWidget(QLabel("Origin Corner:"), 2, 0)
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["Bottom-Left", "Top-Left", "Bottom-Right", "Top-Right"])
        geom_grid.addWidget(self.origin_combo, 2, 1)

        layout.addWidget(geom_group)

        # Software Coordinate Inversion / Mirroring
        mirror_group = QGroupBox("Software Coordinate Mirroring (CAM G-Code Output)")
        mirror_grid = QGridLayout(mirror_group)
        self.chk_soft_mirror_x = QCheckBox("Software Mirror X (Flip G-Code horizontally)")
        self.chk_soft_mirror_x.setToolTip(
            "Inverts all X coordinates in the output G-code.\n"
            "Use this if your laser prints backwards / mirrored and hardware $3 EEPROM cannot be updated (e.g. Marlin firmware)."
        )
        self.chk_soft_mirror_y = QCheckBox("Software Mirror Y (Flip G-Code vertically)")
        self.chk_soft_mirror_y.setToolTip(
            "Inverts all Y coordinates in the output G-code.\n"
            "Use this if your laser engraves upside-down."
        )
        mirror_grid.addWidget(self.chk_soft_mirror_x, 0, 0)
        mirror_grid.addWidget(self.chk_soft_mirror_y, 0, 1)
        layout.addWidget(mirror_group)

        # Finish & Park Position
        park_group = QGroupBox("Job Completion && Park Position")
        park_grid = QGridLayout(park_group)

        park_grid.addWidget(QLabel("Finish Position:"), 0, 0)
        self.finish_pos_combo = QComboBox()
        self.finish_pos_combo.addItems([
            "Origin",
            "Job Start",
            "Park Position",
            "Hold Current"
        ])
        park_grid.addWidget(self.finish_pos_combo, 0, 1, 1, 2)

        park_grid.addWidget(QLabel("Park Position X:"), 1, 0)
        self.park_x_spin = QDoubleSpinBox()
        self.park_x_spin.setRange(0.0, 5000.0)
        self.park_x_spin.setSuffix(" mm")
        park_grid.addWidget(self.park_x_spin, 1, 1)

        park_grid.addWidget(QLabel("Park Position Y:"), 2, 0)
        self.park_y_spin = QDoubleSpinBox()
        self.park_y_spin.setRange(0.0, 5000.0)
        self.park_y_spin.setSuffix(" mm")
        park_grid.addWidget(self.park_y_spin, 2, 1)

        btn_capture_park = QPushButton("📍 Set from Current Laser Pos")
        btn_capture_park.setToolTip("Sets Park coordinates to the laser's current physical position")
        btn_capture_park.clicked.connect(self._capture_current_position_for_park)
        park_grid.addWidget(btn_capture_park, 1, 2, 2, 1)

        layout.addWidget(park_group)

        # Z-Axis moves
        z_group = QGroupBox("Z-Axis Motion")
        z_layout = QVBoxLayout(z_group)
        self.chk_z_moves = QCheckBox("Enable Z-Axis plunging and focus moves (G0/G1 Z)")
        z_layout.addWidget(self.chk_z_moves)
        layout.addWidget(z_group)

        layout.addStretch(1)
        return widget

    # -------------------------------------------------------------
    # Tab 2: Laser Firing & Timing
    # -------------------------------------------------------------
    def _create_laser_firing_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        # Power & Mode Group
        mode_group = QGroupBox("Laser Mode && PWM Scaling")
        mode_grid = QGridLayout(mode_group)

        mode_grid.addWidget(QLabel("Laser Mode:"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "M4 (Dynamic Power - GRBL 1.1+ Inline S)",
            "M3 (Constant Power - GRBL / CNC Spindle)",
            "M106 / M107 (Fan PWM - Marlin & 3D Printer Laser)"
        ])
        mode_grid.addWidget(self.mode_combo, 0, 1)

        mode_grid.addWidget(QLabel("Max S-Value ($30):"), 1, 0)
        self.max_s_spin = QSpinBox()
        self.max_s_spin.setRange(1, 100000)
        self.max_s_spin.setToolTip("Maximum PWM value matching GRBL $30 (default 1000) or 255 for Marlin 8-bit PWM")
        mode_grid.addWidget(self.max_s_spin, 1, 1)

        mode_grid.addWidget(QLabel("Min S-Value ($31):"), 2, 0)
        self.min_s_spin = QSpinBox()
        self.min_s_spin.setRange(0, 1000)
        self.min_s_spin.setToolTip("Minimum PWM value matching GRBL $31 (usually 0)")
        mode_grid.addWidget(self.min_s_spin, 2, 1)

        mode_grid.addWidget(QLabel("Diode Beam Kerf (mm):"), 3, 0)
        self.kerf_spin = QDoubleSpinBox()
        self.kerf_spin.setRange(0.01, 2.0)
        self.kerf_spin.setDecimals(3)
        self.kerf_spin.setSuffix(" mm")
        self.kerf_spin.setToolTip("Diode laser spot focal width (typically 0.08 mm for 3W-5W diodes)")
        mode_grid.addWidget(self.kerf_spin, 3, 1)

        mode_grid.addWidget(QLabel("Inline Power:"), 4, 0)
        self.chk_inline_power = QCheckBox("Use Inline G1 S-power (prevents raster stuttering)")
        self.chk_inline_power.setToolTip("Embeds S-power into G1 moves to eliminate buffer stalls on GRBL and modern controllers.")
        mode_grid.addWidget(self.chk_inline_power, 4, 1)

        def _on_mode_sel(idx):
            if idx == 2 and self.max_s_spin.value() == 1000:
                self.max_s_spin.setValue(255)
            elif idx == 0 and self.max_s_spin.value() == 255:
                self.max_s_spin.setValue(1000)
        self.mode_combo.currentIndexChanged.connect(_on_mode_sel)

        layout.addWidget(mode_group)

        # Firing Delays Group
        timing_group = QGroupBox("Laser Firing Dwell && Stabilization")
        timing_grid = QGridLayout(timing_group)

        timing_grid.addWidget(QLabel("Laser Fire Dwell (ms):"), 0, 0)
        self.fire_delay_spin = QDoubleSpinBox()
        self.fire_delay_spin.setRange(0.0, 5000.0)
        self.fire_delay_spin.setSingleStep(10.0)
        self.fire_delay_spin.setSuffix(" ms")
        self.fire_delay_spin.setToolTip("Dwell delay after laser turns ON before moving (prevents missing start mark)")
        timing_grid.addWidget(self.fire_delay_spin, 0, 1)

        timing_grid.addWidget(QLabel("Laser Off Dwell (ms):"), 1, 0)
        self.off_delay_spin = QDoubleSpinBox()
        self.off_delay_spin.setRange(0.0, 5000.0)
        self.off_delay_spin.setSingleStep(10.0)
        self.off_delay_spin.setSuffix(" ms")
        self.off_delay_spin.setToolTip("Dwell delay after laser turns OFF before rapid movement")
        timing_grid.addWidget(self.off_delay_spin, 1, 1)

        layout.addWidget(timing_group)

        # Guide Beam & Pulse Test Defaults
        guide_group = QGroupBox("Framing Guide && Spot Pulse Defaults")
        guide_grid = QGridLayout(guide_group)

        guide_grid.addWidget(QLabel("Framing Beam Power (%):"), 0, 0)
        self.frame_power_spin = QDoubleSpinBox()
        self.frame_power_spin.setRange(0.01, 10.0)
        self.frame_power_spin.setDecimals(2)
        self.frame_power_spin.setSuffix(" %")
        guide_grid.addWidget(self.frame_power_spin, 0, 1)

        guide_grid.addWidget(QLabel("Framing Speed (mm/min):"), 1, 0)
        self.frame_speed_spin = QDoubleSpinBox()
        self.frame_speed_spin.setRange(100.0, 10000.0)
        self.frame_speed_spin.setSuffix(" mm/min")
        guide_grid.addWidget(self.frame_speed_spin, 1, 1)

        guide_grid.addWidget(QLabel("Default Pulse Duration (ms):"), 2, 0)
        self.pulse_dur_spin = QSpinBox()
        self.pulse_dur_spin.setRange(10, 5000)
        self.pulse_dur_spin.setSingleStep(50)
        self.pulse_dur_spin.setSuffix(" ms")
        guide_grid.addWidget(self.pulse_dur_spin, 2, 1)

        guide_grid.addWidget(QLabel("Default Pulse Power (%):"), 3, 0)
        self.pulse_pow_spin = QDoubleSpinBox()
        self.pulse_pow_spin.setRange(0.1, 100.0)
        self.pulse_pow_spin.setSuffix(" %")
        guide_grid.addWidget(self.pulse_pow_spin, 3, 1)

        layout.addWidget(guide_group)
        layout.addStretch(1)
        return widget

    # -------------------------------------------------------------
    # Tab 3: Overscan & Raster Performance
    # -------------------------------------------------------------
    def _create_overscan_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        ov_group = QGroupBox("Overscan Acceleration Compensation")
        ov_layout = QVBoxLayout(ov_group)

        self.chk_overscan = QCheckBox("Enable Overscan for Raster Engraving")
        self.chk_overscan.setToolTip(
            "Extends scanlines past image boundary so the laser carriage accelerates\n"
            "and decelerates with the laser OFF. Eliminates dark burned edges!"
        )
        ov_layout.addWidget(self.chk_overscan)

        grid = QGridLayout()
        grid.addWidget(QLabel("Overscan Calculation Mode:"), 0, 0)
        self.overscan_mode_combo = QComboBox()
        self.overscan_mode_combo.addItems(["Acceleration", "Percentage", "Fixed"])
        grid.addWidget(self.overscan_mode_combo, 0, 1)

        grid.addWidget(QLabel("Acceleration Margin Multiplier:"), 1, 0)
        self.overscan_mult_spin = QDoubleSpinBox()
        self.overscan_mult_spin.setRange(1.0, 3.0)
        self.overscan_mult_spin.setSingleStep(0.05)
        self.overscan_mult_spin.setSuffix(" x")
        self.overscan_mult_spin.setToolTip("Physics overscan distance multiplier: d = multiplier * (v² / 2a)")
        grid.addWidget(self.overscan_mult_spin, 1, 1)

        grid.addWidget(QLabel("Overscan Percentage (%):"), 2, 0)
        self.overscan_pct_spin = QDoubleSpinBox()
        self.overscan_pct_spin.setRange(0.5, 30.0)
        self.overscan_pct_spin.setSingleStep(0.5)
        self.overscan_pct_spin.setSuffix(" %")
        self.overscan_pct_spin.setToolTip("Used if mode is Percentage (e.g. 2.5% to 5.0%)")
        grid.addWidget(self.overscan_pct_spin, 2, 1)

        grid.addWidget(QLabel("Fixed Overscan Distance (mm):"), 3, 0)
        self.overscan_mm_spin = QDoubleSpinBox()
        self.overscan_mm_spin.setRange(0.5, 50.0)
        self.overscan_mm_spin.setSingleStep(0.5)
        self.overscan_mm_spin.setSuffix(" mm")
        self.overscan_mm_spin.setToolTip("Used if mode is Fixed (e.g. 2.0 mm)")
        grid.addWidget(self.overscan_mm_spin, 3, 1)

        ov_layout.addLayout(grid)

        # White-Space Skipping & Power Streaming Group
        ws_group = QGroupBox("Raster High-Speed Optimization & Power Streaming")
        ws_layout = QVBoxLayout(ws_group)

        self.chk_continuous_streaming = QCheckBox("Enable Continuous Inline Power Streaming (Zero-Stutter)")
        self.chk_continuous_streaming.setToolTip(
            "Emits power inline via G1 S... and uses G0 rapid moves for blanks, eliminating\n"
            "M5/M4 planner buffer flushes and dead stops on GRBL 1.1+."
        )
        ws_layout.addWidget(self.chk_continuous_streaming)

        self.chk_white_space_skip = QCheckBox("Enable White-Space Rapid Skipping")
        self.chk_white_space_skip.setToolTip(
            "Emits high-speed G0 rapid moves across wide gaps of empty white pixels\n"
            "instead of slowly traversing with laser off. Cuts engraving times by up to 65%!"
        )
        ws_layout.addWidget(self.chk_white_space_skip)

        ws_grid = QGridLayout()
        ws_grid.addWidget(QLabel("Minimum Gap Skip Threshold:"), 0, 0)
        self.white_space_skip_threshold_spin = QDoubleSpinBox()
        self.white_space_skip_threshold_spin.setRange(1.0, 100.0)
        self.white_space_skip_threshold_spin.setSingleStep(1.0)
        self.white_space_skip_threshold_spin.setSuffix(" mm")
        self.white_space_skip_threshold_spin.setToolTip("Minimum continuous blank gap required to emit a G0 rapid jump")
        ws_grid.addWidget(self.white_space_skip_threshold_spin, 0, 1)

        ws_grid.addWidget(QLabel("Whitespace Rapid Speed:"), 1, 0)
        self.fast_ws_speed_spin = QDoubleSpinBox()
        self.fast_ws_speed_spin.setRange(0.0, 30000.0)
        self.fast_ws_speed_spin.setSingleStep(500.0)
        self.fast_ws_speed_spin.setSuffix(" mm/min")
        self.fast_ws_speed_spin.setSpecialValueText("Auto (Machine Rapid G0)")
        self.fast_ws_speed_spin.setToolTip("Speed for whitespace rapid traversal. Set to 0 to use machine G0 rapid speed.")
        ws_grid.addWidget(self.fast_ws_speed_spin, 1, 1)

        ws_layout.addLayout(ws_grid)

        # Flood Fill Island Partitioning Group
        ff_group = QGroupBox("⚡ Flood Fill Island Engraving (Multi-Object Turbo)")
        ff_layout = QVBoxLayout(ff_group)

        self.chk_flood_fill = QCheckBox("Enable Flood Fill Island Partitioning")
        self.chk_flood_fill.setToolTip(
            "Detects disconnected burning shapes or text clusters and engraves each island\n"
            "locally before moving to the next. Eliminates sweeping across empty bed space!"
        )
        ff_layout.addWidget(self.chk_flood_fill)

        ff_grid = QGridLayout()
        ff_grid.addWidget(QLabel("Island Separation Threshold:"), 0, 0)
        self.flood_fill_sep_spin = QDoubleSpinBox()
        self.flood_fill_sep_spin.setRange(1.0, 100.0)
        self.flood_fill_sep_spin.setSingleStep(1.0)
        self.flood_fill_sep_spin.setSuffix(" mm")
        self.flood_fill_sep_spin.setToolTip("Minimum distance in millimeters between distinct shapes before splitting into separate islands.")
        ff_grid.addWidget(self.flood_fill_sep_spin, 0, 1)
        ff_layout.addLayout(ff_grid)

        # Informational Note
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_frame.setStyleSheet("background-color: #263238; border-radius: 4px; padding: 6px;")
        info_l = QVBoxLayout(info_frame)
        info_title = QLabel("ℹ️ Why use Raster Turbo & Flood Fill?")
        info_title.setStyleSheet("font-weight: bold; color: #80d8ff;")
        info_desc = QLabel(
            "• Continuous Inline Streaming keeps the controller planner buffer full, avoiding the stutter\n"
            "  and burning pauses caused by legacy M5/M4 stop commands.\n"
            "• Blank-Space skipping leaps across empty bed spaces at rapid G0 speeds rather than slow burn rates.\n"
            "• Flood Fill island engraving groups disconnected shapes/logos and engraves each locally with minimal\n"
            "  X stroke length, saving up to 80% engraving time on dispersed layouts."
        )
        info_desc.setStyleSheet("color: #b0bec5; font-size: 11px;")
        info_l.addWidget(info_title)
        info_l.addWidget(info_desc)
        ws_layout.addWidget(info_frame)

        layout.addWidget(ov_group)
        layout.addWidget(ws_group)
        layout.addWidget(ff_group)
        layout.addStretch(1)

        scroll.setWidget(widget)
        return scroll

    # -------------------------------------------------------------
    # Tab 4: Motion & Kinematics Calibration
    # -------------------------------------------------------------
    def _create_motion_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        # Speeds Group
        speed_group = QGroupBox("Speeds && Feeds")
        s_grid = QGridLayout(speed_group)

        s_grid.addWidget(QLabel("Rapid Speed G0 (mm/min):"), 0, 0)
        self.rapid_spin = QDoubleSpinBox()
        self.rapid_spin.setRange(100.0, 30000.0)
        self.rapid_spin.setSuffix(" mm/min")
        s_grid.addWidget(self.rapid_spin, 0, 1)

        s_grid.addWidget(QLabel("Manual Jog Speed (mm/min):"), 1, 0)
        self.jog_spin = QDoubleSpinBox()
        self.jog_spin.setRange(100.0, 20000.0)
        self.jog_spin.setSuffix(" mm/min")
        s_grid.addWidget(self.jog_spin, 1, 1)

        layout.addWidget(speed_group)

        # Kinematics ($100-$122) Group
        kin_group = QGroupBox("Axis Steps && Acceleration (GRBL Kinematics)")
        k_grid = QGridLayout(kin_group)

        k_grid.addWidget(QLabel("X Steps/mm ($100):"), 0, 0)
        self.x_steps_spin = QDoubleSpinBox()
        self.x_steps_spin.setRange(1.0, 10000.0)
        self.x_steps_spin.setDecimals(3)
        k_grid.addWidget(self.x_steps_spin, 0, 1)

        k_grid.addWidget(QLabel("Y Steps/mm ($101):"), 1, 0)
        self.y_steps_spin = QDoubleSpinBox()
        self.y_steps_spin.setRange(1.0, 10000.0)
        self.y_steps_spin.setDecimals(3)
        k_grid.addWidget(self.y_steps_spin, 1, 1)

        k_grid.addWidget(QLabel("Z Steps/mm ($102):"), 2, 0)
        self.z_steps_spin = QDoubleSpinBox()
        self.z_steps_spin.setRange(1.0, 10000.0)
        self.z_steps_spin.setDecimals(3)
        k_grid.addWidget(self.z_steps_spin, 2, 1)

        k_grid.addWidget(QLabel("X Max Rate ($110, mm/min):"), 3, 0)
        self.x_max_rate_spin = QDoubleSpinBox()
        self.x_max_rate_spin.setRange(100.0, 50000.0)
        k_grid.addWidget(self.x_max_rate_spin, 3, 1)

        k_grid.addWidget(QLabel("Y Max Rate ($111, mm/min):"), 4, 0)
        self.y_max_rate_spin = QDoubleSpinBox()
        self.y_max_rate_spin.setRange(100.0, 50000.0)
        k_grid.addWidget(self.y_max_rate_spin, 4, 1)

        k_grid.addWidget(QLabel("X Accel ($120, mm/sec²):"), 5, 0)
        self.x_accel_spin = QDoubleSpinBox()
        self.x_accel_spin.setRange(10.0, 10000.0)
        k_grid.addWidget(self.x_accel_spin, 5, 1)

        k_grid.addWidget(QLabel("Y Accel ($121, mm/sec²):"), 6, 0)
        self.y_accel_spin = QDoubleSpinBox()
        self.y_accel_spin.setRange(10.0, 10000.0)
        k_grid.addWidget(self.y_accel_spin, 6, 1)

        layout.addWidget(kin_group)

        # Direction & Limits Mask
        limits_group = QGroupBox("Direction Masks && Limits ($3, $20, $21, $22)")
        l_grid = QGridLayout(limits_group)

        self.chk_inv_x = QCheckBox("Invert X Direction")
        self.chk_inv_y = QCheckBox("Invert Y Direction")
        self.chk_inv_z = QCheckBox("Invert Z Direction")
        l_grid.addWidget(self.chk_inv_x, 0, 0)
        l_grid.addWidget(self.chk_inv_y, 0, 1)
        l_grid.addWidget(self.chk_inv_z, 0, 2)

        self.chk_soft_limits = QCheckBox("Soft Limits Enable ($20)")
        self.chk_hard_limits = QCheckBox("Hard Limits Enable ($21)")
        self.chk_homing = QCheckBox("Homing Cycle Enable ($22)")
        l_grid.addWidget(self.chk_soft_limits, 1, 0)
        l_grid.addWidget(self.chk_hard_limits, 1, 1)
        l_grid.addWidget(self.chk_homing, 1, 2)

        layout.addWidget(limits_group)

        # Interactive Step Calibration Calculator
        calib_group = QGroupBox("Interactive Step Calibration Calculator")
        c_layout = QVBoxLayout(calib_group)

        c_grid = QGridLayout()
        c_grid.addWidget(QLabel("Axis to Calibrate:"), 0, 0)
        self.calib_axis_combo = QComboBox()
        self.calib_axis_combo.addItems(["X Axis ($100)", "Y Axis ($101)"])
        c_grid.addWidget(self.calib_axis_combo, 0, 1)

        c_grid.addWidget(QLabel("Commanded Distance (mm):"), 1, 0)
        self.calib_cmd_spin = QDoubleSpinBox()
        self.calib_cmd_spin.setRange(1.0, 1000.0)
        self.calib_cmd_spin.setValue(100.0)
        self.calib_cmd_spin.setSuffix(" mm")
        c_grid.addWidget(self.calib_cmd_spin, 1, 1)

        c_grid.addWidget(QLabel("Actual Measured Distance (mm):"), 2, 0)
        self.calib_meas_spin = QDoubleSpinBox()
        self.calib_meas_spin.setRange(0.1, 1000.0)
        self.calib_meas_spin.setValue(100.0)
        self.calib_meas_spin.setDecimals(3)
        self.calib_meas_spin.setSuffix(" mm")
        c_grid.addWidget(self.calib_meas_spin, 2, 1)

        btn_calc = QPushButton("📏 Calculate & Apply New Steps/mm")
        btn_calc.setStyleSheet("background-color: #00838f; color: white; font-weight: bold;")
        btn_calc.clicked.connect(self._calculate_calibrated_steps)
        c_grid.addWidget(btn_calc, 3, 0, 1, 2)

        c_layout.addLayout(c_grid)
        layout.addWidget(calib_group)

        scroll.setWidget(widget)
        return scroll

    # -------------------------------------------------------------
    # Tab 5: G-Code & Custom Scripts
    # -------------------------------------------------------------
    def _create_gcode_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        # Pre-Flight Validation Settings
        val_group = QGroupBox("Pre-Flight G-Code Safety & Validation")
        val_l = QVBoxLayout(val_group)
        self.chk_validate_gcode = QCheckBox("Validate GRBL G-Code before starting jobs (Recommended)")
        self.chk_validate_gcode.setToolTip("Runs static syntax, modal group, and workbed travel checks before streaming to laser")
        val_l.addWidget(self.chk_validate_gcode)

        self.chk_strict_validation = QCheckBox("Strict validation mode (Block job on warnings as well as errors)")
        self.chk_strict_validation.setToolTip("If enabled, warnings (such as rapid burns or high power) will block execution")
        val_l.addWidget(self.chk_strict_validation)
        layout.addWidget(val_group)

        # Custom Start G-code
        start_group = QGroupBox("Custom Start G-Code (Executed before job begins)")
        start_l = QVBoxLayout(start_group)
        self.start_gcode_edit = QPlainTextEdit()
        self.start_gcode_edit.setPlaceholderText(
            "; Example:\n; M8 ; Exhaust fan on\n; G4 P0.5 ; Pause for laser power\n"
        )
        self.start_gcode_edit.setMaximumHeight(140)
        start_l.addWidget(self.start_gcode_edit)
        layout.addWidget(start_group)

        # Custom End G-code
        end_group = QGroupBox("Custom End G-Code (Executed after job finishes)")
        end_l = QVBoxLayout(end_group)
        self.end_gcode_edit = QPlainTextEdit()
        self.end_gcode_edit.setPlaceholderText(
            "; Example:\n; M9 ; Turn off exhaust / air\n; G4 P1.0 ; Let fan clear chamber\n"
        )
        self.end_gcode_edit.setMaximumHeight(140)
        end_l.addWidget(self.end_gcode_edit)
        layout.addWidget(end_group)

        # Macro reference guide
        ref_frame = QFrame()
        ref_frame.setFrameShape(QFrame.Shape.StyledPanel)
        ref_l = QVBoxLayout(ref_frame)
        ref_lbl = QLabel(
            "<b>Macro Variables & GRBL Commands Reference:</b><br>"
            "<code>M3</code> / <code>M4</code>: Laser Power ON &nbsp;|&nbsp; "
            "<code>M5</code>: Laser OFF &nbsp;|&nbsp; "
            "<code>M8</code>: Air Assist ON &nbsp;|&nbsp; "
            "<code>M9</code>: Air OFF &nbsp;|&nbsp; "
            "<code>G4 P0.5</code>: Dwell (seconds)"
        )
        ref_lbl.setStyleSheet("color: #b0bec5; font-size: 11px;")
        ref_l.addWidget(ref_lbl)
        layout.addWidget(ref_frame)

        layout.addStretch(1)
        return widget

    # -------------------------------------------------------------
    # Tab 6: Air Assist & Peripherals
    # -------------------------------------------------------------
    def _create_air_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        air_group = QGroupBox("Air Assist Configuration")
        air_grid = QGridLayout(air_group)

        self.chk_air_default = QCheckBox("Enable Air Assist by default on new layers")
        air_grid.addWidget(self.chk_air_default, 0, 0, 1, 2)

        air_grid.addWidget(QLabel("Air Assist ON Command:"), 1, 0)
        self.air_on_cmd = QLineEdit()
        self.air_on_cmd.setPlaceholderText("M8")
        air_grid.addWidget(self.air_on_cmd, 1, 1)

        air_grid.addWidget(QLabel("Air Assist OFF Command:"), 2, 0)
        self.air_off_cmd = QLineEdit()
        self.air_off_cmd.setPlaceholderText("M9")
        air_grid.addWidget(self.air_off_cmd, 2, 1)

        air_grid.addWidget(QLabel("Air Pre-Delay (seconds):"), 3, 0)
        self.air_pre_delay_spin = QDoubleSpinBox()
        self.air_pre_delay_spin.setRange(0.0, 10.0)
        self.air_pre_delay_spin.setSingleStep(0.1)
        self.air_pre_delay_spin.setSuffix(" s")
        self.air_pre_delay_spin.setToolTip("Wait time after air turns on before laser fires to allow compressor line pressurization")
        air_grid.addWidget(self.air_pre_delay_spin, 3, 1)

        air_grid.addWidget(QLabel("Air Post-Delay (seconds):"), 4, 0)
        self.air_post_delay_spin = QDoubleSpinBox()
        self.air_post_delay_spin.setRange(0.0, 30.0)
        self.air_post_delay_spin.setSingleStep(0.5)
        self.air_post_delay_spin.setSuffix(" s")
        self.air_post_delay_spin.setToolTip("Keeps air flowing after cut finishes to cool lens and clear lingering smoke")
        air_grid.addWidget(self.air_post_delay_spin, 4, 1)

        layout.addWidget(air_group)
        layout.addStretch(1)
        return widget

    # -------------------------------------------------------------
    # Tab 7: GPU & Hardware Acceleration
    # -------------------------------------------------------------
    def _create_gpu_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        info = GPUAccelerator.get_hardware_info()

        # Hardware details card
        hw_group = QGroupBox("Detected Graphics & Compute Accelerator")
        hw_layout = QVBoxLayout(hw_group)

        card = QFrame()
        card.setStyleSheet("background-color: #24242e; border-radius: 6px; padding: 12px;")
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(6)

        title = QLabel(f"<b>GPU Device:</b> <span style='color: #00e5ff; font-size: 13px;'>{info.device_name}</span>")
        vram = QLabel(f"<b>Dedicated VRAM:</b> {info.total_vram_gb:.1f} GB GDDR6")
        cuda = QLabel(f"<b>CUDA Compute Runtime:</b> {info.cuda_driver_version}")

        c_layout.addWidget(title)
        c_layout.addWidget(vram)
        c_layout.addWidget(cuda)

        # Status pills row
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(8)

        def make_pill(text: str, active: bool) -> QLabel:
            lbl = QLabel(text)
            color = "#81c784" if active else "#90a4ae"
            bg = "#1b4d2e" if active else "#37474f"
            lbl.setStyleSheet(f"background-color: {bg}; color: {color}; font-weight: bold; padding: 4px 10px; border-radius: 4px;")
            return lbl

        pills_layout.addWidget(make_pill("CUDA: Active" if info.cuda_available else "CUDA: Unavailable", info.cuda_available))
        pills_layout.addWidget(make_pill("OpenCL: Active" if info.opencl_available else "OpenCL: Unavailable", info.opencl_available))
        pills_layout.addWidget(make_pill("OpenGL: Active" if info.opengl_available else "OpenGL: Unavailable", info.opengl_available))
        pills_layout.addStretch(1)

        c_layout.addLayout(pills_layout)
        hw_layout.addWidget(card)
        layout.addWidget(hw_group)

        # Acceleration Settings
        accel_group = QGroupBox("Hardware Acceleration Controls")
        accel_layout = QVBoxLayout(accel_group)
        accel_layout.setSpacing(10)

        self.chk_gpu_compute = QCheckBox("Enable CUDA / OpenCL computation acceleration")
        self.chk_gpu_compute.setToolTip("Offloads photo engraving filters, unsharp masking, gamma adjustment, and dithering to GPU cores")
        self.chk_gpu_compute.setEnabled(info.cuda_available or info.opencl_available)
        accel_layout.addWidget(self.chk_gpu_compute)

        self.chk_opengl_canvas = QCheckBox("Enable hardware-accelerated OpenGL canvas viewport (60-120 FPS)")
        self.chk_opengl_canvas.setToolTip("Renders the CAD canvas using the RTX 2070 SUPER GPU pipeline with 4x MSAA anti-aliasing")
        self.chk_opengl_canvas.setEnabled(info.opengl_available)
        accel_layout.addWidget(self.chk_opengl_canvas)

        layout.addWidget(accel_group)
        layout.addStretch(1)
        return widget

    # -------------------------------------------------------------
    # Tab 8: GRBL Firmware ($$) Live Sync
    # -------------------------------------------------------------
    def _create_grbl_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        btn_row = QHBoxLayout()
        self.btn_read_grbl = QPushButton("📥  Read Settings from Machine ($$)")
        self.btn_read_grbl.setStyleSheet("font-weight: bold; background-color: #0288d1; color: white; padding: 6px;")
        self.btn_read_grbl.clicked.connect(self._read_grbl_from_machine)
        btn_row.addWidget(self.btn_read_grbl)

        self.btn_write_all = QPushButton("📤  Write Configuration to Controller")
        self.btn_write_all.setStyleSheet("font-weight: bold; background-color: #388e3c; color: white; padding: 6px;")
        self.btn_write_all.clicked.connect(self._write_grbl_to_machine)
        btn_row.addWidget(self.btn_write_all)

        layout.addLayout(btn_row)

        # Settings Table
        self.grbl_table = QTableWidget()
        self.grbl_table.setColumnCount(4)
        self.grbl_table.setHorizontalHeaderLabels(["Setting", "Value", "Unit", "Description"])
        self.grbl_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.grbl_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.grbl_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.grbl_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.grbl_table, 1)

        # Direct Single Param Editor
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Set Parameter:"))
        self.param_key_edit = QLineEdit()
        self.param_key_edit.setPlaceholderText("$100")
        self.param_key_edit.setFixedWidth(70)
        edit_row.addWidget(self.param_key_edit)

        edit_row.addWidget(QLabel("="))
        self.param_val_edit = QLineEdit()
        self.param_val_edit.setPlaceholderText("80.000")
        self.param_val_edit.setFixedWidth(100)
        edit_row.addWidget(self.param_val_edit)

        self.btn_write_single = QPushButton("Write $Param")
        self.btn_write_single.clicked.connect(self._write_single_grbl_param)
        edit_row.addWidget(self.btn_write_single)
        edit_row.addStretch(1)

        layout.addLayout(edit_row)

        self._populate_grbl_table()
        return widget

    # -------------------------------------------------------------
    # Value Loading & Saving
    # -------------------------------------------------------------
    def _load_values(self):
        # Workbed
        self.width_spin.setValue(self.settings.bed_width)
        self.height_spin.setValue(self.settings.bed_height)
        self.origin_combo.setCurrentText(self.settings.origin_corner)
        self.finish_pos_combo.setCurrentText(getattr(self.settings, "finish_position_mode", "Origin"))
        self.chk_soft_mirror_x.setChecked(getattr(self.settings, "software_mirror_x", False))
        self.chk_soft_mirror_y.setChecked(getattr(self.settings, "software_mirror_y", False))
        self.park_x_spin.setValue(getattr(self.settings, "park_x", 0.0))
        self.park_y_spin.setValue(getattr(self.settings, "park_y", 0.0))
        self.chk_z_moves.setChecked(getattr(self.settings, "enable_z_moves", False))

        # Laser & Firing
        cur_mode = getattr(self.settings, "laser_mode", "M4")
        if cur_mode == "M106":
            self.mode_combo.setCurrentIndex(2)
        elif cur_mode == "M3":
            self.mode_combo.setCurrentIndex(1)
        else:
            self.mode_combo.setCurrentIndex(0)
        self.chk_inline_power.setChecked(getattr(self.settings, "use_inline_power", True))
        self.max_s_spin.setValue(getattr(self.settings, "max_s_value", 1000))
        self.min_s_spin.setValue(getattr(self.settings, "min_s_value", 0))
        self.kerf_spin.setValue(getattr(self.settings, "kerf_width_mm", 0.08))
        self.fire_delay_spin.setValue(getattr(self.settings, "laser_fire_delay_ms", 0.0))
        self.off_delay_spin.setValue(getattr(self.settings, "laser_off_delay_ms", 0.0))
        self.frame_power_spin.setValue(getattr(self.settings, "framing_power_pct", 0.5))
        self.frame_speed_spin.setValue(getattr(self.settings, "framing_speed", 2000.0))
        self.pulse_dur_spin.setValue(getattr(self.settings, "test_pulse_duration_ms", 100))
        self.pulse_pow_spin.setValue(getattr(self.settings, "test_pulse_power_pct", 1.0))

        # Overscan & White-Space Skipping & Raster Turbo
        self.chk_overscan.setChecked(getattr(self.settings, "overscan_enabled", False))
        self.overscan_mode_combo.setCurrentText(getattr(self.settings, "overscan_mode", "Acceleration"))
        self.overscan_mult_spin.setValue(getattr(self.settings, "overscan_accel_multiplier", 1.2))
        self.overscan_pct_spin.setValue(getattr(self.settings, "overscan_pct", 2.5))
        self.overscan_mm_spin.setValue(getattr(self.settings, "overscan_mm", 2.0))
        self.chk_white_space_skip.setChecked(getattr(self.settings, "white_space_skip_enabled", True))
        self.white_space_skip_threshold_spin.setValue(getattr(self.settings, "white_space_skip_threshold_mm", 8.0))
        self.chk_continuous_streaming.setChecked(getattr(self.settings, "continuous_inline_streaming", True))
        self.fast_ws_speed_spin.setValue(getattr(self.settings, "raster_fast_whitespace_speed", 0.0))
        self.chk_flood_fill.setChecked(getattr(self.settings, "flood_fill_enabled", True))
        self.flood_fill_sep_spin.setValue(getattr(self.settings, "flood_fill_separation_mm", 12.0))

        # Kinematics
        self.rapid_spin.setValue(getattr(self.settings, "rapid_speed", 3000.0))
        self.jog_spin.setValue(getattr(self.settings, "jog_speed", 2000.0))
        self.x_steps_spin.setValue(getattr(self.settings, "x_steps_per_mm", 80.0))
        self.y_steps_spin.setValue(getattr(self.settings, "y_steps_per_mm", 80.0))
        self.z_steps_spin.setValue(getattr(self.settings, "z_steps_per_mm", 250.0))
        self.x_max_rate_spin.setValue(getattr(self.settings, "x_max_rate", 5000.0))
        self.y_max_rate_spin.setValue(getattr(self.settings, "y_max_rate", 5000.0))
        self.x_accel_spin.setValue(getattr(self.settings, "x_accel", 500.0))
        self.y_accel_spin.setValue(getattr(self.settings, "y_accel", 500.0))
        self.chk_inv_x.setChecked(getattr(self.settings, "invert_x_dir", False))
        self.chk_inv_y.setChecked(getattr(self.settings, "invert_y_dir", False))
        self.chk_inv_z.setChecked(getattr(self.settings, "invert_z_dir", False))
        self.chk_soft_limits.setChecked(getattr(self.settings, "soft_limits_enabled", False))
        self.chk_hard_limits.setChecked(getattr(self.settings, "hard_limits_enabled", False))
        self.chk_homing.setChecked(getattr(self.settings, "homing_enabled", False))

        # Scripts & Validation
        self.chk_validate_gcode.setChecked(getattr(self.settings, "validate_gcode_before_start", True))
        self.chk_strict_validation.setChecked(getattr(self.settings, "strict_validation", False))
        self.start_gcode_edit.setPlainText(getattr(self.settings, "custom_start_gcode", ""))
        self.end_gcode_edit.setPlainText(getattr(self.settings, "custom_end_gcode", ""))

        # Air Assist
        self.chk_air_default.setChecked(getattr(self.settings, "enable_air_assist_by_default", False))
        self.air_on_cmd.setText(getattr(self.settings, "air_assist_cmd", "M8"))
        self.air_off_cmd.setText(getattr(self.settings, "air_assist_off_cmd", "M9"))
        self.air_pre_delay_spin.setValue(getattr(self.settings, "air_assist_pre_delay_sec", 0.0))
        self.air_post_delay_spin.setValue(getattr(self.settings, "air_assist_post_delay_sec", 0.0))

        # Hardware GPU Acceleration
        self.chk_gpu_compute.setChecked(getattr(self.settings, "enable_gpu_acceleration", True))
        self.chk_opengl_canvas.setChecked(getattr(self.settings, "enable_opengl_canvas", True))

    def _apply_settings(self):
        # Workbed
        self.settings.bed_width = self.width_spin.value()
        self.settings.bed_height = self.height_spin.value()
        self.settings.origin_corner = self.origin_combo.currentText()
        self.settings.software_mirror_x = self.chk_soft_mirror_x.isChecked()
        self.settings.software_mirror_y = self.chk_soft_mirror_y.isChecked()
        self.settings.finish_position_mode = self.finish_pos_combo.currentText()
        self.settings.park_x = self.park_x_spin.value()
        self.settings.park_y = self.park_y_spin.value()
        self.settings.enable_z_moves = self.chk_z_moves.isChecked()

        # Laser & Firing
        txt = self.mode_combo.currentText()
        if "M106" in txt:
            self.settings.laser_mode = "M106"
        elif "M3" in txt:
            self.settings.laser_mode = "M3"
        else:
            self.settings.laser_mode = "M4"
        self.settings.use_inline_power = self.chk_inline_power.isChecked()
        self.settings.max_s_value = self.max_s_spin.value()
        self.settings.min_s_value = self.min_s_spin.value()
        self.settings.kerf_width_mm = self.kerf_spin.value()
        self.settings.laser_fire_delay_ms = self.fire_delay_spin.value()
        self.settings.laser_off_delay_ms = self.off_delay_spin.value()
        self.settings.framing_power_pct = self.frame_power_spin.value()
        self.settings.framing_speed = self.frame_speed_spin.value()
        self.settings.test_pulse_duration_ms = self.pulse_dur_spin.value()
        self.settings.test_pulse_power_pct = self.pulse_pow_spin.value()

        # Overscan & White-Space Skipping & Raster Turbo
        self.settings.overscan_enabled = self.chk_overscan.isChecked()
        self.settings.overscan_mode = self.overscan_mode_combo.currentText()
        self.settings.overscan_accel_multiplier = self.overscan_mult_spin.value()
        self.settings.overscan_pct = self.overscan_pct_spin.value()
        self.settings.overscan_mm = self.overscan_mm_spin.value()
        self.settings.white_space_skip_enabled = self.chk_white_space_skip.isChecked()
        self.settings.white_space_skip_threshold_mm = self.white_space_skip_threshold_spin.value()
        self.settings.continuous_inline_streaming = self.chk_continuous_streaming.isChecked()
        self.settings.raster_fast_whitespace_speed = self.fast_ws_speed_spin.value()
        self.settings.flood_fill_enabled = self.chk_flood_fill.isChecked()
        self.settings.flood_fill_separation_mm = self.flood_fill_sep_spin.value()

        # Kinematics
        self.settings.rapid_speed = self.rapid_spin.value()
        self.settings.jog_speed = self.jog_spin.value()
        self.settings.x_steps_per_mm = self.x_steps_spin.value()
        self.settings.y_steps_per_mm = self.y_steps_spin.value()
        self.settings.z_steps_per_mm = self.z_steps_spin.value()
        self.settings.x_max_rate = self.x_max_rate_spin.value()
        self.settings.y_max_rate = self.y_max_rate_spin.value()
        self.settings.x_accel = self.x_accel_spin.value()
        self.settings.y_accel = self.y_accel_spin.value()
        self.settings.invert_x_dir = self.chk_inv_x.isChecked()
        self.settings.invert_y_dir = self.chk_inv_y.isChecked()
        self.settings.invert_z_dir = self.chk_inv_z.isChecked()
        self.settings.soft_limits_enabled = self.chk_soft_limits.isChecked()
        self.settings.hard_limits_enabled = self.chk_hard_limits.isChecked()
        self.settings.homing_enabled = self.chk_homing.isChecked()

        # Scripts & Validation
        self.settings.validate_gcode_before_start = self.chk_validate_gcode.isChecked()
        self.settings.strict_validation = self.chk_strict_validation.isChecked()
        self.settings.custom_start_gcode = self.start_gcode_edit.toPlainText()
        self.settings.custom_end_gcode = self.end_gcode_edit.toPlainText()

        # Air Assist
        self.settings.enable_air_assist_by_default = self.chk_air_default.isChecked()
        self.settings.air_assist_cmd = self.air_on_cmd.text().strip() or "M8"
        self.settings.air_assist_off_cmd = self.air_off_cmd.text().strip() or "M9"
        self.settings.air_assist_pre_delay_sec = self.air_pre_delay_spin.value()
        self.settings.air_assist_post_delay_sec = self.air_post_delay_spin.value()

        # Hardware GPU Acceleration
        self.settings.enable_gpu_acceleration = self.chk_gpu_compute.isChecked()
        self.settings.enable_opengl_canvas = self.chk_opengl_canvas.isChecked()

    def _save_and_accept(self):
        self._apply_settings()
        self.accept()

    def _capture_current_position_for_park(self):
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            coords = self.serial_ctrl.wpos
            self.park_x_spin.setValue(coords[0])
            self.park_y_spin.setValue(coords[1])
            QMessageBox.information(
                self, "Position Captured",
                f"Park position captured from laser coordinates:\nX = {coords[0]:.2f} mm\nY = {coords[1]:.2f} mm"
            )
        else:
            QMessageBox.warning(
                self, "Laser Not Connected",
                "Cannot capture laser position: Laser is currently disconnected."
            )

    def _calculate_calibrated_steps(self):
        axis_name = self.calib_axis_combo.currentText()
        is_x = "X Axis" in axis_name
        cmd_dist = self.calib_cmd_spin.value()
        meas_dist = self.calib_meas_spin.value()

        if meas_dist <= 0.0001:
            QMessageBox.warning(self, "Invalid Distance", "Measured distance must be greater than zero.")
            return

        current_steps = self.x_steps_spin.value() if is_x else self.y_steps_spin.value()
        # Formula: New Steps = Current Steps * (Commanded / Measured)
        new_steps = round(current_steps * (cmd_dist / meas_dist), 3)

        ans = QMessageBox.question(
            self, "Apply Calibration",
            f"<b>Axis:</b> {'X' if is_x else 'Y'}<br>"
            f"<b>Current Steps/mm:</b> {current_steps:.3f}<br>"
            f"<b>Commanded:</b> {cmd_dist:.2f} mm &nbsp;|&nbsp; <b>Measured:</b> {meas_dist:.2f} mm<br><br>"
            f"<b>New Calibrated Steps/mm:</b> <span style='color:#00e5ff; font-weight:bold;'>{new_steps:.3f}</span><br><br>"
            "Apply this new value now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            if is_x:
                self.x_steps_spin.setValue(new_steps)
                if self.serial_ctrl and self.serial_ctrl.is_connected:
                    self.serial_ctrl.set_grbl_setting(100, new_steps)
            else:
                self.y_steps_spin.setValue(new_steps)
                if self.serial_ctrl and self.serial_ctrl.is_connected:
                    self.serial_ctrl.set_grbl_setting(101, new_steps)

    # -------------------------------------------------------------
    # GRBL Table & Communication
    # -------------------------------------------------------------
    def _populate_grbl_table(self):
        self.grbl_table.setRowCount(0)
        row = 0
        settings_dict = {}
        if self.serial_ctrl:
            settings_dict = getattr(self.serial_ctrl, "grbl_settings", {})

        for key, info in sorted(GRBL_SETTING_DESCRIPTIONS.items(), key=lambda x: int(x[0][1:])):
            name, unit, desc = info
            val = settings_dict.get(key, "-")

            self.grbl_table.insertRow(row)
            self.grbl_table.setItem(row, 0, QTableWidgetItem(key))
            self.grbl_table.setItem(row, 1, QTableWidgetItem(str(val)))
            self.grbl_table.setItem(row, 2, QTableWidgetItem(unit))
            self.grbl_table.setItem(row, 3, QTableWidgetItem(f"{name} ({desc})"))
            row += 1

    @pyqtSlot(dict)
    def _on_grbl_settings_updated(self, settings_dict: dict):
        for r in range(self.grbl_table.rowCount()):
            key_item = self.grbl_table.item(r, 0)
            if key_item:
                k = key_item.text()
                if k in settings_dict:
                    self.grbl_table.setItem(r, 1, QTableWidgetItem(str(settings_dict[k])))

    def _read_grbl_from_machine(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.warning(
                self, "Not Connected",
                "Laser is not connected. Connect via the Laser control panel before querying $$ parameters."
            )
            return

        self.serial_ctrl.query_grbl_settings()
        QMessageBox.information(
            self, "Query Sent",
            "Sent $$ request to laser controller. Parameters will update in the table automatically."
        )

    def _write_grbl_to_machine(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.warning(
                self, "Not Connected",
                "Laser is not connected. Please connect before writing configuration to EEPROM."
            )
            return

        ans = QMessageBox.question(
            self, "Confirm EEPROM Write",
            "This will write machine limits, laser mode, and kinematics directly to GRBL EEPROM.\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        # Apply GUI values
        self._apply_settings()

        # Send core parameters
        ctrl = self.serial_ctrl
        ctrl.set_grbl_setting(30, self.settings.max_s_value)
        ctrl.set_grbl_setting(31, self.settings.min_s_value)
        ctrl.set_grbl_setting(32, 1 if self.settings.laser_mode == "M4" else 0)
        ctrl.set_grbl_setting(100, self.settings.x_steps_per_mm)
        ctrl.set_grbl_setting(101, self.settings.y_steps_per_mm)
        ctrl.set_grbl_setting(102, self.settings.z_steps_per_mm)
        ctrl.set_grbl_setting(110, self.settings.x_max_rate)
        ctrl.set_grbl_setting(111, self.settings.y_max_rate)
        ctrl.set_grbl_setting(120, self.settings.x_accel)
        ctrl.set_grbl_setting(121, self.settings.y_accel)
        ctrl.set_grbl_setting(130, self.settings.bed_width)
        ctrl.set_grbl_setting(131, self.settings.bed_height)

        # Invert mask ($3)
        inv_mask = (1 if self.settings.invert_x_dir else 0) | \
                   (2 if self.settings.invert_y_dir else 0) | \
                   (4 if self.settings.invert_z_dir else 0)
        ctrl.set_grbl_setting(3, inv_mask)

        # Limits & Homing
        ctrl.set_grbl_setting(20, 1 if self.settings.soft_limits_enabled else 0)
        ctrl.set_grbl_setting(21, 1 if self.settings.hard_limits_enabled else 0)
        ctrl.set_grbl_setting(22, 1 if self.settings.homing_enabled else 0)

        QMessageBox.information(
            self, "EEPROM Updated",
            "GRBL parameters have been sent to the laser controller!"
        )

    def _write_single_grbl_param(self):
        if not self.serial_ctrl or not self.serial_ctrl.is_connected:
            QMessageBox.warning(self, "Not Connected", "Laser controller is not connected.")
            return

        key = self.param_key_edit.text().strip()
        val = self.param_val_edit.text().strip()
        if not key or not val:
            QMessageBox.warning(self, "Missing Input", "Please specify both setting number ($...) and value.")
            return

        self.serial_ctrl.set_grbl_setting(key, val)
        self.param_key_edit.clear()
        self.param_val_edit.clear()

