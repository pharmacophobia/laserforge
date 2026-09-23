"""
LaserForge Laser Control Panel.
Provides machine connection controls, real-time GRBL status readouts,
8-way jog pad with configurable step increments, framing, homing, zeroing,
and job execution (Start, Pause, Stop) with progress bar.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QRadioButton, QButtonGroup,
    QProgressBar, QGroupBox, QSpinBox, QDoubleSpinBox,
    QFrame, QCheckBox, QScrollArea, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon

from laserforge.core.serial_controller import SerialController
from laserforge.core.audio_alerts import AudioChimeEngine


class JogButton(QPushButton):
    """Square icon/text jog button with consistent sizing."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(30, 26)
        font = QFont("sans-serif", 8, QFont.Weight.Bold)
        self.setFont(font)


class LaserControlPanel(QWidget):
    # Signals to parent window
    start_job_requested = pyqtSignal()
    simulate_job_requested = pyqtSignal()
    frame_job_requested = pyqtSignal()
    contour_frame_job_requested = pyqtSignal()
    burn_perimeter_requested = pyqtSignal()
    alignment_dialog_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    park_requested = pyqtSignal()
    resume_job_requested = pyqtSignal()

    def __init__(self, serial_ctrl: SerialController, parent=None, settings=None):
        super().__init__(parent)
        self.serial_ctrl = serial_ctrl
        self.settings = settings

        self.step_distance = 10.0  # mm
        self.jog_speed = 3000.0     # mm/min
        self.is_firing_test = False

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(3, 3, 3, 3)
        main_layout.setSpacing(3)

        # 1. Connection Group
        conn_group = QGroupBox("Laser Connection")
        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setContentsMargins(4, 4, 4, 4)
        conn_layout.setSpacing(2)

        port_row = QHBoxLayout()
        port_row.setSpacing(3)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if self.port_combo.lineEdit():
            self.port_combo.lineEdit().setPlaceholderText("Select port or type tcp://IP:Port")
        self.port_combo.setToolTip("Serial Port or Network Bridge (e.g. tcp://laserbridge.local:8088)")
        self.port_combo.activated.connect(self._on_port_combo_activated)
        self.refresh_ports_btn = QPushButton("⟳")
        self.refresh_ports_btn.setFixedWidth(24)
        self.refresh_ports_btn.setToolTip("Refresh Port List")
        self.refresh_ports_btn.clicked.connect(self.refresh_ports)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "250000", "57600", "38400", "9600"])
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setFixedWidth(76)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white; padding: 2px 6px;")
        self.connect_btn.clicked.connect(self._toggle_connection)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_ports_btn)
        port_row.addWidget(self.baud_combo)
        port_row.addWidget(self.connect_btn)
        conn_layout.addLayout(port_row)

        auto_row = QHBoxLayout()
        auto_row.setSpacing(4)
        self.btn_auto_connect = QPushButton("⚡ Auto-Connect")
        self.btn_auto_connect.setStyleSheet(
            "background-color: #0288d1; color: white; font-weight: bold; padding: 2px 6px; border-radius: 2px; font-size: 10px;"
        )
        self.btn_auto_connect.setToolTip("Auto-detect and handshake with connected laser engraver")
        self.btn_auto_connect.clicked.connect(self._on_auto_connect_clicked)
        auto_row.addWidget(self.btn_auto_connect)

        self.chk_auto_plug = QCheckBox("Auto-plug")
        self.chk_auto_plug.setChecked(True)
        self.chk_auto_plug.setToolTip("Automatically connect when laser is plugged in via USB or powered on")
        self.chk_auto_plug.toggled.connect(self._on_auto_plug_toggled)
        auto_row.addWidget(self.chk_auto_plug)

        self.status_badge = QLabel("Disconnected")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet(
            "background-color: #424242; color: #bdbdbd; font-weight: bold; "
            "border-radius: 2px; padding: 2px 4px; font-size: 10px;"
        )
        auto_row.addWidget(self.status_badge)

        self.pos_label = QLabel("X:0.0 Y:0.0")
        self.pos_label.setStyleSheet("font-family: monospace; font-size: 10px; color: #00e5ff;")
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        auto_row.addWidget(self.pos_label)
        conn_layout.addLayout(auto_row)

        # Scanning Progress Status
        self.lbl_scan_status = QLabel("")
        self.lbl_scan_status.setStyleSheet("color: #ffb74d; font-size: 10px; font-style: italic; padding: 1px 4px;")
        self.lbl_scan_status.setVisible(False)
        conn_layout.addWidget(self.lbl_scan_status)

        self.lbl_pin_status = QLabel("")
        self.lbl_pin_status.setStyleSheet("color: #ffb74d; font-size: 10px; font-weight: bold;")
        self.lbl_pin_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pin_status.setVisible(False)
        conn_layout.addWidget(self.lbl_pin_status)

        main_layout.addWidget(conn_group)

        # 2. Jog / Movement Controls
        jog_group = QGroupBox("Move / Jog")
        jog_layout = QVBoxLayout(jog_group)
        jog_layout.setContentsMargins(4, 4, 4, 4)
        jog_layout.setSpacing(3)

        step_row = QHBoxLayout()
        step_row.setSpacing(2)
        step_row.addWidget(QLabel("Step:"))
        self.step_btn_group = QButtonGroup(self)
        steps = [("0.1", 0.1), ("1", 1.0), ("10", 10.0), ("50", 50.0), ("100", 100.0)]
        for label, val in steps:
            rb = QRadioButton(label)
            if val == 10.0:
                rb.setChecked(True)
            self.step_btn_group.addButton(rb)
            rb.toggled.connect(lambda chk, v=val: self._set_step_dist(chk, v))
            step_row.addWidget(rb)
        step_row.addStretch(1)
        step_row.addWidget(QLabel("Speed:"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(100, 10000)
        self.speed_spin.setSingleStep(500)
        self.speed_spin.setValue(int(self.jog_speed))
        self.speed_spin.setFixedWidth(64)
        self.speed_spin.valueChanged.connect(self._on_speed_changed)
        step_row.addWidget(self.speed_spin)
        jog_layout.addLayout(step_row)

        # Jog 8-way Grid
        pad_grid = QGridLayout()
        pad_grid.setSpacing(2)
        pad_grid.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_nw = JogButton("↖")
        self.btn_n  = JogButton("▲")
        self.btn_ne = JogButton("↗")
        self.btn_w  = JogButton("◀")
        self.btn_origin = JogButton("⌂")
        self.btn_origin.setToolTip("Go to Work Origin (0,0)")
        self.btn_origin.setStyleSheet("background-color: #37474f;")
        self.btn_e  = JogButton("▶")
        self.btn_sw = JogButton("↙")
        self.btn_s  = JogButton("▼")
        self.btn_se = JogButton("↘")

        self.btn_nw.clicked.connect(lambda: self._jog(-1, 1))
        self.btn_n.clicked.connect(lambda: self._jog(0, 1))
        self.btn_ne.clicked.connect(lambda: self._jog(1, 1))
        self.btn_w.clicked.connect(lambda: self._jog(-1, 0))
        self.btn_origin.clicked.connect(lambda: self.serial_ctrl.go_to_zero(self.jog_speed))
        self.btn_e.clicked.connect(lambda: self._jog(1, 0))
        self.btn_sw.clicked.connect(lambda: self._jog(-1, -1))
        self.btn_s.clicked.connect(lambda: self._jog(0, -1))
        self.btn_se.clicked.connect(lambda: self._jog(1, -1))

        self.btn_z_up = JogButton("Z▲")
        self.btn_z_up.setToolTip("Jog Z-Axis Up")
        self.btn_z_up.setStyleSheet("background-color: #2e3b4e; font-size: 10px;")
        self.btn_z_up.clicked.connect(lambda: self._jog(0, 0, 1))

        self.btn_z_probe = JogButton("⇊")
        self.btn_z_probe.setToolTip("Autofocus Touch Probe (G38.2)")
        self.btn_z_probe.setStyleSheet("background-color: #00695c; color: white; font-weight: bold; font-size: 11px;")
        self.btn_z_probe.clicked.connect(self._on_probe_z_clicked)

        self.btn_z_down = JogButton("Z▼")
        self.btn_z_down.setToolTip("Jog Z-Axis Down")
        self.btn_z_down.setStyleSheet("background-color: #2e3b4e; font-size: 10px;")
        self.btn_z_down.clicked.connect(lambda: self._jog(0, 0, -1))

        pad_grid.addWidget(self.btn_nw, 0, 0)
        pad_grid.addWidget(self.btn_n,  0, 1)
        pad_grid.addWidget(self.btn_ne, 0, 2)
        pad_grid.addWidget(self.btn_w,  1, 0)
        pad_grid.addWidget(self.btn_origin, 1, 1)
        pad_grid.addWidget(self.btn_e,  1, 2)
        pad_grid.addWidget(self.btn_sw, 2, 0)
        pad_grid.addWidget(self.btn_s,  2, 1)
        pad_grid.addWidget(self.btn_se, 2, 2)
        pad_grid.addWidget(self.btn_z_up, 0, 3)
        pad_grid.addWidget(self.btn_z_probe, 1, 3)
        pad_grid.addWidget(self.btn_z_down, 2, 3)
        jog_layout.addLayout(pad_grid)

        # Movement Actions (Home, Unlock, Set 0, Park, Align)
        actions_grid = QGridLayout()
        actions_grid.setSpacing(2)

        self.btn_home = QPushButton("Home ($H)")
        self.btn_home.setToolTip("Run machine homing cycle ($H)")
        self.btn_home.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_home.clicked.connect(self.serial_ctrl.home)

        self.btn_unlock = QPushButton("Unlock ($X)")
        self.btn_unlock.setToolTip("Clear alarm lock ($X)")
        self.btn_unlock.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_unlock.clicked.connect(self.serial_ctrl.unlock)

        self.btn_set_origin = QPushButton("Set 0")
        self.btn_set_origin.setToolTip("Set current position as (0, 0)")
        self.btn_set_origin.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_set_origin.clicked.connect(lambda: self.serial_ctrl.set_zero(True, True, True))

        self.btn_park = QPushButton("🅿 Park")
        self.btn_park.setToolTip("Move laser to configured Park position")
        self.btn_park.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_park.clicked.connect(self._on_park_clicked)

        actions_grid.addWidget(self.btn_home, 0, 0)
        actions_grid.addWidget(self.btn_unlock, 0, 1)
        actions_grid.addWidget(self.btn_set_origin, 0, 2)
        actions_grid.addWidget(self.btn_park, 0, 3)

        self.btn_align = QPushButton("🎯 Align Workpiece Assistant...")
        self.btn_align.setToolTip("Open visual targeting, continuous framing, and 2-point alignment assistant")
        self.btn_align.setStyleSheet("font-weight: bold; background-color: #00838f; color: white; padding: 3px; font-size: 10px;")
        self.btn_align.clicked.connect(self.alignment_dialog_requested.emit)
        actions_grid.addWidget(self.btn_align, 1, 0, 1, 4)

        self.btn_burn_perimeter = QPushButton("🔥 Burn Perimeter Tool...")
        self.btn_burn_perimeter.setToolTip("Score or burn alignment perimeter on wasteboard or stock to position workpiece")
        self.btn_burn_perimeter.setStyleSheet("font-weight: bold; background-color: #d84315; color: white; padding: 3px; font-size: 10px;")
        self.btn_burn_perimeter.clicked.connect(self.burn_perimeter_requested.emit)
        actions_grid.addWidget(self.btn_burn_perimeter, 2, 0, 1, 4)
        jog_layout.addLayout(actions_grid)

        main_layout.addWidget(jog_group)

        # 2b. Laser Beam & Pulse Test Group
        beam_group = QGroupBox("Laser Spot & Pulse Test")
        beam_layout = QHBoxLayout(beam_group)
        beam_layout.setContentsMargins(4, 3, 4, 3)
        beam_layout.setSpacing(3)

        self.btn_fire_laser = QPushButton("🔦 Guide (0.5%)")
        self.btn_fire_laser.setCheckable(True)
        self.btn_fire_laser.setToolTip("Toggle low-power visible framing beam for manual positioning")
        self.btn_fire_laser.setStyleSheet("font-size: 10px; padding: 2px;")
        self.btn_fire_laser.clicked.connect(self._toggle_test_laser)
        beam_layout.addWidget(self.btn_fire_laser)

        self.pulse_pow_spin = QDoubleSpinBox()
        self.pulse_pow_spin.setRange(0.1, 100.0)
        self.pulse_pow_spin.setSingleStep(0.5)
        self.pulse_pow_spin.setValue(getattr(self.settings, "test_pulse_power_pct", 1.0) if self.settings else 1.0)
        self.pulse_pow_spin.setSuffix("%")
        self.pulse_pow_spin.setToolTip("Pulse power percentage")
        self.pulse_pow_spin.setFixedWidth(54)

        self.pulse_dur_spin = QSpinBox()
        self.pulse_dur_spin.setRange(10, 5000)
        self.pulse_dur_spin.setSingleStep(50)
        self.pulse_dur_spin.setValue(getattr(self.settings, "test_pulse_duration_ms", 100) if self.settings else 100)
        self.pulse_dur_spin.setSuffix("ms")
        self.pulse_dur_spin.setToolTip("Pulse duration in milliseconds")
        self.pulse_dur_spin.setFixedWidth(58)

        self.btn_pulse = QPushButton("⚡ Pulse")
        self.btn_pulse.setToolTip("Test fire laser beam momentarily to verify focus spot or mark reference point")
        self.btn_pulse.setStyleSheet("background-color: #ef6c00; color: white; font-weight: bold; padding: 2px 6px; font-size: 10px;")
        self.btn_pulse.clicked.connect(self._on_pulse_clicked)

        beam_layout.addWidget(self.pulse_pow_spin)
        beam_layout.addWidget(self.pulse_dur_spin)
        beam_layout.addWidget(self.btn_pulse)
        main_layout.addWidget(beam_group)

        # 3. Job Execution Group
        job_group = QGroupBox("Job Execution")
        job_layout = QVBoxLayout(job_group)
        job_layout.setContentsMargins(4, 4, 4, 4)
        job_layout.setSpacing(3)

        run_row = QHBoxLayout()
        run_row.setSpacing(3)

        self.btn_frame = QPushButton("⛶ Rect Frame")
        self.btn_frame.setToolTip("Trace rectangular bounding box with laser guide before cutting")
        self.btn_frame.setStyleSheet("font-weight: bold; padding: 4px; background-color: #00796b; color: white; font-size: 10px;")
        self.btn_frame.clicked.connect(self.frame_job_requested.emit)

        self.btn_contour_frame = QPushButton("⬡ Contour Frame")
        self.btn_contour_frame.setToolTip("Trace exact rubber-band perimeter of artwork for aligning on scrap wood/materials")
        self.btn_contour_frame.setStyleSheet("font-weight: bold; padding: 4px; background-color: #00897b; color: white; font-size: 10px;")
        self.btn_contour_frame.clicked.connect(self.contour_frame_job_requested.emit)

        self.btn_simulate = QPushButton("🎬 Simulate")
        self.btn_simulate.setToolTip("Simulate project outcomes, material finish, burn trajectory, and time breakdown (Alt+P)")
        self.btn_simulate.setStyleSheet(
            "background-color: #5c6bc0; color: white; font-weight: bold; padding: 4px; font-size: 10px;"
        )
        self.btn_simulate.clicked.connect(self.simulate_job_requested.emit)

        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 4px; font-size: 10px;"
        )
        self.btn_start.clicked.connect(self.start_job_requested.emit)

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setStyleSheet(
            "background-color: #f57f17; color: white; font-weight: bold; padding: 4px; font-size: 10px;"
        )
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setStyleSheet(
            "background-color: #c62828; color: white; font-weight: bold; padding: 4px; font-size: 10px;"
        )
        self.btn_stop.clicked.connect(self.serial_ctrl.stop_streaming)

        self.btn_resume = QPushButton("⏯ Resume %")
        self.btn_resume.setToolTip("Resume interrupted or stopped laser job from specific percentage or line")
        self.btn_resume.setStyleSheet(
            "background-color: #0284c7; color: white; font-weight: bold; padding: 4px; font-size: 10px;"
        )
        self.btn_resume.clicked.connect(self.resume_job_requested.emit)

        run_row.addWidget(self.btn_frame)
        run_row.addWidget(self.btn_contour_frame)
        run_row.addWidget(self.btn_simulate)
        run_row.addWidget(self.btn_start)
        run_row.addWidget(self.btn_pause)
        run_row.addWidget(self.btn_stop)
        run_row.addWidget(self.btn_resume)
        job_layout.addLayout(run_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(14)
        job_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Idle")
        self.progress_label.setStyleSheet("color: #9e9e9e; font-size: 9px;")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        job_layout.addWidget(self.progress_label)

        # Real-time GRBL 1.1 Overrides
        ov_group = QGroupBox("Live Speed & Power Overrides")
        ov_layout = QVBoxLayout(ov_group)
        ov_layout.setContentsMargins(4, 2, 4, 2)
        ov_layout.setSpacing(2)

        # Feed override row
        feed_row = QHBoxLayout()
        feed_row.setSpacing(2)
        self.lbl_feed_ov = QLabel("Speed: 100%")
        self.lbl_feed_ov.setStyleSheet("font-size: 9px; font-weight: bold; color: #4fc3f7; min-width: 65px;")
        btn_f_reset = QPushButton("100%")
        btn_f_reset.setToolTip("Reset feed rate to 100%")
        btn_f_reset.clicked.connect(lambda: self.serial_ctrl.set_feed_override("100"))
        btn_f_m10 = QPushButton("-10%")
        btn_f_m10.clicked.connect(lambda: self.serial_ctrl.set_feed_override("-10"))
        btn_f_p10 = QPushButton("+10%")
        btn_f_p10.clicked.connect(lambda: self.serial_ctrl.set_feed_override("+10"))
        btn_f_m1 = QPushButton("-1%")
        btn_f_m1.clicked.connect(lambda: self.serial_ctrl.set_feed_override("-1"))
        btn_f_p1 = QPushButton("+1%")
        btn_f_p1.clicked.connect(lambda: self.serial_ctrl.set_feed_override("+1"))
        for b in (btn_f_reset, btn_f_m10, btn_f_p10, btn_f_m1, btn_f_p1):
            b.setStyleSheet("padding: 1px 3px; font-size: 8px;")

        feed_row.addWidget(self.lbl_feed_ov)
        feed_row.addWidget(btn_f_m10)
        feed_row.addWidget(btn_f_m1)
        feed_row.addWidget(btn_f_reset)
        feed_row.addWidget(btn_f_p1)
        feed_row.addWidget(btn_f_p10)
        ov_layout.addLayout(feed_row)

        # Laser power override row
        power_row = QHBoxLayout()
        power_row.setSpacing(2)
        self.lbl_power_ov = QLabel("Power: 100%")
        self.lbl_power_ov.setStyleSheet("font-size: 9px; font-weight: bold; color: #ffb74d; min-width: 65px;")
        btn_p_reset = QPushButton("100%")
        btn_p_reset.setToolTip("Reset laser power to 100%")
        btn_p_reset.clicked.connect(lambda: self.serial_ctrl.set_power_override("100"))
        btn_p_m10 = QPushButton("-10%")
        btn_p_m10.clicked.connect(lambda: self.serial_ctrl.set_power_override("-10"))
        btn_p_p10 = QPushButton("+10%")
        btn_p_p10.clicked.connect(lambda: self.serial_ctrl.set_power_override("+10"))
        btn_p_m1 = QPushButton("-1%")
        btn_p_m1.clicked.connect(lambda: self.serial_ctrl.set_power_override("-1"))
        btn_p_p1 = QPushButton("+1%")
        btn_p_p1.clicked.connect(lambda: self.serial_ctrl.set_power_override("+1"))
        for b in (btn_p_reset, btn_p_m10, btn_p_p10, btn_p_m1, btn_p_p1):
            b.setStyleSheet("padding: 1px 3px; font-size: 8px;")

        power_row.addWidget(self.lbl_power_ov)
        power_row.addWidget(btn_p_m10)
        power_row.addWidget(btn_p_m1)
        power_row.addWidget(btn_p_reset)
        power_row.addWidget(btn_p_p1)
        power_row.addWidget(btn_p_p10)
        ov_layout.addLayout(power_row)

        job_layout.addWidget(ov_group)

        main_layout.addWidget(job_group)

        # Quick G-Code Macros
        macro_group = QGroupBox("Quick G-Code Macros")
        macro_layout = QGridLayout(macro_group)
        macro_layout.setContentsMargins(4, 4, 4, 4)
        macro_layout.setSpacing(4)

        macros = [
            ("Home ($H)", "$H", "#0288d1"),
            ("Air On", "M8", "#388e3c"),
            ("Air Off", "M9", "#616161"),
            ("Origin", "G90 G0 X0 Y0", "#f57c00"),
            ("Park Rear", "G90 G0 X0 Y400", "#7b1fa2"),
            ("Zero WCS", "G10 L20 P1 X0 Y0 Z0", "#c2185b"),
        ]

        for idx, (m_name, m_code, m_col) in enumerate(macros):
            row = idx // 2
            col = idx % 2
            btn_m = QPushButton(m_name)
            btn_m.setToolTip(f"Send G-code: {m_code}")
            btn_m.setStyleSheet(f"font-size: 9px; padding: 3px; font-weight: bold; background-color: {m_col}; color: white; border-radius: 3px;")
            btn_m.clicked.connect(lambda checked=False, code=m_code: self._send_macro(code))
            macro_layout.addWidget(btn_m, row, col)

        main_layout.addWidget(macro_group)

        self.btn_settings = QPushButton("⚙  Machine & Laser Settings...")
        self.btn_settings.setToolTip("Open comprehensive Machine, Laser Kinematics, Overscan, and GRBL configuration")
        self.btn_settings.setStyleSheet("font-weight: bold; padding: 3px; font-size: 10px;")
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        main_layout.addWidget(self.btn_settings)

        main_layout.addStretch(1)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

        # Populate ports initially
        self.refresh_ports()

    def _connect_signals(self):
        self.serial_ctrl.connected.connect(self._on_connected)
        self.serial_ctrl.disconnected.connect(self._on_disconnected)
        self.serial_ctrl.status_updated.connect(self._on_status_updated)
        self.serial_ctrl.job_progress.connect(self._on_job_progress)
        self.serial_ctrl.job_finished.connect(self._on_job_finished)
        self.serial_ctrl.auto_connect_started.connect(self._on_auto_connect_started)
        self.serial_ctrl.auto_connect_progress.connect(self._on_auto_connect_progress)
        self.serial_ctrl.auto_connect_finished.connect(self._on_auto_connect_finished)
        self.serial_ctrl.ports_changed.connect(lambda _: self.refresh_ports())

        # Enable USB hotplug monitoring
        self.serial_ctrl.enable_hotplug_watcher(self.chk_auto_plug.isChecked())

    def refresh_ports(self):
        current_data = self.port_combo.currentData() or self.port_combo.currentText().strip()
        if current_data and current_data.upper().startswith("VIRTUAL"):
            current_data = None
        self.port_combo.clear()
        ranked = self.serial_ctrl.get_ranked_ports(include_dummy_tty=False)
        if not ranked:
            ranked = self.serial_ctrl.get_ranked_ports(include_dummy_tty=True)

        ranked = [p for p in ranked if not p.device.upper().startswith("VIRTUAL")]

        selected_idx = 0
        if not ranked:
            self.port_combo.addItem("No serial ports found", None)
        else:
            for idx, p in enumerate(ranked):
                self.port_combo.addItem(p.display_name, p.device)
                if p.device == current_data:
                    selected_idx = idx

        # PiBridge / Network Laser options
        net_default = "tcp://laserbridge.local:8088"
        self.port_combo.addItem("🌐 PiBridge Network Laser (laserbridge.local:8088)", net_default)
        if current_data and (current_data == net_default or "laserbridge" in str(current_data)):
            selected_idx = self.port_combo.count() - 1

        self.port_combo.addItem("➕ Add Custom Network Laser (TCP)...", "__ADD_CUSTOM_NETWORK__")
        self.port_combo.setCurrentIndex(selected_idx)

    def _on_port_combo_activated(self, idx: int):
        data = self.port_combo.itemData(idx)
        if data == "__ADD_CUSTOM_NETWORK__":
            host_str, ok = QInputDialog.getText(
                self, "Add Network Laser",
                "Enter Laser Bridge Host/IP and Port:\n(e.g. laserbridge.local:8088 or 192.168.1.50:8088)",
                text="laserbridge.local:8088"
            )
            if ok and host_str.strip():
                addr = host_str.strip()
                if not addr.startswith(("tcp://", "socket://", "net://")):
                    addr = f"tcp://{addr}"
                self.port_combo.insertItem(0, f"🌐 Network Laser ({addr})", addr)
                self.port_combo.setCurrentIndex(0)
            else:
                self.port_combo.setCurrentIndex(0)

    def _toggle_connection(self):
        if self.serial_ctrl.is_connected:
            self.serial_ctrl.disconnect()
        else:
            port = self.port_combo.currentData() or self.port_combo.currentText().strip()
            if not port or port in ("No serial ports found", "No ports found", "__ADD_CUSTOM_NETWORK__"):
                return
            baud = int(self.baud_combo.currentText())
            self.serial_ctrl.connect(port, baud)

    def _on_auto_connect_clicked(self):
        if self.serial_ctrl.is_connected:
            self.serial_ctrl.disconnect()
        self.serial_ctrl.start_auto_connect()

    def _on_auto_plug_toggled(self, checked: bool):
        self.serial_ctrl.auto_reconnect_enabled = checked
        self.serial_ctrl.enable_hotplug_watcher(checked)

    def _on_auto_connect_started(self):
        self.btn_auto_connect.setText("⏳ Scanning...")
        self.btn_auto_connect.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.lbl_scan_status.setVisible(True)
        self.lbl_scan_status.setText("Scanning ports for GRBL laser...")

    def _on_auto_connect_progress(self, msg: str):
        self.lbl_scan_status.setText(msg)

    def _on_auto_connect_finished(self, success: bool, msg: str):
        self.btn_auto_connect.setText("⚡  Auto-Connect")
        self.btn_auto_connect.setEnabled(True)
        self.connect_btn.setEnabled(True)
        if success:
            self.lbl_scan_status.setText("Laser connected!")
            QTimer.singleShot(3000, lambda: self.lbl_scan_status.setVisible(False))
        else:
            self.lbl_scan_status.setText(msg)
            QTimer.singleShot(5000, lambda: self.lbl_scan_status.setVisible(False))

    def _on_connected(self, port: str):
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setStyleSheet("font-weight: bold; background-color: #c62828; color: white;")
        self.btn_auto_connect.setEnabled(False)
        self.status_badge.setText("Connected")
        self.status_badge.setStyleSheet(
            "background-color: #1b5e20; color: #a5d6a7; font-weight: bold; border-radius: 3px; padding: 3px 6px;"
        )
        # Select connected port in combo
        for i in range(self.port_combo.count()):
            if self.port_combo.itemData(i) == port or self.port_combo.itemText(i) == port:
                self.port_combo.setCurrentIndex(i)
                break

    def _on_disconnected(self):
        self.connect_btn.setText("Connect")
        self.connect_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white;")
        self.btn_auto_connect.setEnabled(True)
        self.status_badge.setText("Disconnected")
        self.status_badge.setStyleSheet(
            "background-color: #424242; color: #bdbdbd; font-weight: bold; border-radius: 3px; padding: 3px 6px;"
        )
        self.pos_label.setText("X: 0.00  Y: 0.00")
        self.btn_fire_laser.setChecked(False)
        self.btn_fire_laser.setText("Fire Laser")

    def _on_status_updated(self, status: dict):
        state = status.get("state", "Idle")
        mpos = status.get("mpos", [0.0, 0.0, 0.0])
        wpos = status.get("wpos", [0.0, 0.0, 0.0])
        pins = status.get("pins", "")

        color_map = {
            "Idle": ("#1b5e20", "#a5d6a7"),
            "Run":  ("#01579b", "#81d4fa"),
            "Hold": ("#e65100", "#ffcc80"),
            "Alarm":("#b71c1c", "#ef9a9a"),
            "Home": ("#4a148c", "#ce93d8"),
        }
        bg, fg = color_map.get(state, ("#37474f", "#cfd8dc"))
        self.status_badge.setText(state.upper())
        self.status_badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; font-weight: bold; border-radius: 3px; padding: 3px 6px;"
        )

        x_val = wpos[0] if (wpos and len(wpos) > 0) else 0.0
        y_val = wpos[1] if (wpos and len(wpos) > 1) else 0.0
        z_val = wpos[2] if (wpos and len(wpos) > 2) else 0.0
        self.pos_label.setText(f"X:{x_val:.1f} Y:{y_val:.1f} Z:{z_val:.1f}")

        # Update real-time overrides readout if provided
        overrides = status.get("overrides")
        if overrides:
            feed_pct = overrides.get("feed", 100)
            power_pct = overrides.get("power", 100)
            self.lbl_feed_ov.setText(f"Speed: {feed_pct}%")
            self.lbl_power_ov.setText(f"Power: {power_pct}%")

        # Check for active hardware limit switches in Pn:
        limit_axes = [ax for ax in ("X", "Y", "Z") if ax in pins]
        if limit_axes:
            self.lbl_pin_status.setText(f"⚠️ Limit {'+'.join(limit_axes)} Switch Closed (Move off endstop)")
            self.lbl_pin_status.setVisible(True)
        else:
            self.lbl_pin_status.setVisible(False)

        if state == "Alarm":
            self.btn_unlock.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; border: 1px solid #ff8a80;")
        elif state == "Idle":
            self.btn_unlock.setStyleSheet("")

    def _set_step_dist(self, checked: bool, val: float):
        if checked:
            self.step_distance = val

    def _on_speed_changed(self, val: int):
        self.jog_speed = float(val)

    def _jog(self, x_dir: int, y_dir: int, z_dir: int = 0):
        dx = x_dir * self.step_distance
        dy = y_dir * self.step_distance
        dz = z_dir * self.step_distance
        self.serial_ctrl.jog(dx, dy, dz, self.jog_speed)

    def _on_probe_z_clicked(self):
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Run Z-Probe Autofocus",
            "Ensure the touch plate or focus probe is connected and positioned directly beneath the laser nozzle.\n\n"
            "The laser head will probe downward until electrical contact.\n\n"
            "Proceed with Z-probe?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.serial_ctrl.probe_z(max_travel_mm=40.0, feed=50.0, plate_thickness_mm=0.0)

    def _toggle_test_laser(self):
        self.is_firing_test = self.btn_fire_laser.isChecked()
        if self.is_firing_test:
            self.btn_fire_laser.setText("🔦 Laser ON (0.5%)")
            self.btn_fire_laser.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
            self.serial_ctrl.toggle_test_laser(True, power_s=5) # 5 / 1000 = 0.5%
        else:
            self.btn_fire_laser.setText("🔦 Continuous Guide Beam (0.5%)")
            self.btn_fire_laser.setStyleSheet("")
            self.serial_ctrl.toggle_test_laser(False)

    def _on_pulse_clicked(self):
        power_pct = self.pulse_pow_spin.value()
        duration_ms = self.pulse_dur_spin.value()
        self.btn_pulse.setEnabled(False)
        self.btn_pulse.setText("⚡ Pulsing...")
        self.btn_pulse.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; padding: 2px 6px; font-size: 10px;")
        self.serial_ctrl.pulse_laser(power_pct=power_pct, duration_ms=duration_ms)
        QTimer.singleShot(duration_ms + 150, self._restore_pulse_btn)

    def _restore_pulse_btn(self):
        self.btn_pulse.setEnabled(True)
        self.btn_pulse.setText("⚡ Pulse")
        self.btn_pulse.setStyleSheet("background-color: #ef6c00; color: white; font-weight: bold; padding: 2px 6px; font-size: 10px;")

    def _on_park_clicked(self):
        if self.settings:
            self.serial_ctrl.go_to_park(
                getattr(self.settings, "park_x", 0.0),
                getattr(self.settings, "park_y", 0.0),
                getattr(self.settings, "rapid_speed", 3000.0)
            )
        else:
            self.park_requested.emit()

    def _toggle_pause(self):
        if not self.serial_ctrl.is_streaming:
            return
        if self.serial_ctrl.is_paused:
            self.serial_ctrl.resume_job()
            self.btn_pause.setText("⏸ Pause")
        else:
            self.serial_ctrl.pause_job()
            self.btn_pause.setText("▶ Resume")

    def _on_job_progress(self, pct: float, cur: int, total: int):
        self.progress_bar.setValue(int(pct))
        self.progress_label.setText(f"Line {cur} / {total} ({pct:.1f}%)")

    def _on_job_finished(self, success: bool, msg: str):
        self.progress_bar.setValue(100 if success else 0)
        self.progress_label.setText(msg)
        self.btn_pause.setText("⏸ Pause")
        if not success:
            self.progress_label.setStyleSheet("color: #ef5350; font-size: 10px; font-weight: bold;")
            if "ALARM" in msg or "alarm" in msg:
                self.btn_unlock.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; border: 1px solid #ff8a80;")
            AudioChimeEngine.play_chime("alarm")
        else:
            self.progress_label.setStyleSheet("color: #81c784; font-size: 10px; font-weight: bold;")
            self.btn_unlock.setStyleSheet("")
            AudioChimeEngine.play_chime("job_complete")

    def _send_macro(self, gcode: str):
        if self.serial_ctrl and self.serial_ctrl.is_connected:
            self.serial_ctrl.send_command(gcode)
        else:
            QMessageBox.information(self, "Quick Macro", "Laser is not connected. Please connect before sending macros.")
