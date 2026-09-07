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
    QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon

from laserforge.core.serial_controller import SerialController


class JogButton(QPushButton):
    """Square icon/text jog button with consistent sizing."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(42, 38)
        font = QFont("sans-serif", 11, QFont.Weight.Bold)
        self.setFont(font)


class LaserControlPanel(QWidget):
    # Signals to parent window
    start_job_requested = pyqtSignal()
    frame_job_requested = pyqtSignal()

    def __init__(self, serial_ctrl: SerialController, parent=None):
        super().__init__(parent)
        self.serial_ctrl = serial_ctrl

        self.step_distance = 10.0  # mm
        self.jog_speed = 3000.0     # mm/min
        self.is_firing_test = False

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 1. Connection Group
        conn_group = QGroupBox("Laser Connection")
        conn_layout = QVBoxLayout(conn_group)
        conn_layout.setContentsMargins(6, 8, 6, 6)
        conn_layout.setSpacing(4)

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setToolTip("Serial Port (e.g. /dev/ttyUSB0)")
        self.refresh_ports_btn = QPushButton("⟳")
        self.refresh_ports_btn.setFixedWidth(28)
        self.refresh_ports_btn.setToolTip("Refresh Port List")
        self.refresh_ports_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_ports_btn)
        conn_layout.addLayout(port_row)

        baud_row = QHBoxLayout()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "250000", "57600", "38400", "9600"])
        self.baud_combo.setCurrentText("115200")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white;")
        self.connect_btn.clicked.connect(self._toggle_connection)
        baud_row.addWidget(QLabel("Baud:"))
        baud_row.addWidget(self.baud_combo)
        baud_row.addWidget(self.connect_btn)
        conn_layout.addLayout(baud_row)

        # Status & Coordinates Banner
        status_row = QHBoxLayout()
        self.status_badge = QLabel("Disconnected")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setStyleSheet(
            "background-color: #424242; color: #bdbdbd; font-weight: bold; "
            "border-radius: 3px; padding: 3px 6px;"
        )
        status_row.addWidget(self.status_badge)

        self.pos_label = QLabel("X: 0.00  Y: 0.00")
        self.pos_label.setStyleSheet("font-family: monospace; font-size: 11px; color: #00e5ff;")
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.pos_label)
        conn_layout.addLayout(status_row)

        main_layout.addWidget(conn_group)

        # 2. Jog / Movement Controls
        jog_group = QGroupBox("Move / Jog")
        jog_layout = QVBoxLayout(jog_group)
        jog_layout.setContentsMargins(6, 6, 6, 6)
        jog_layout.setSpacing(6)

        # Jog Step Selection
        step_row = QHBoxLayout()
        step_row.setSpacing(2)
        self.step_btn_group = QButtonGroup(self)
        steps = [("0.1", 0.1), ("1", 1.0), ("10", 10.0), ("50", 50.0), ("100", 100.0)]
        for label, val in steps:
            rb = QRadioButton(label)
            if val == 10.0:
                rb.setChecked(True)
            self.step_btn_group.addButton(rb)
            rb.toggled.connect(lambda chk, v=val: self._set_step_dist(chk, v))
            step_row.addWidget(rb)
        jog_layout.addLayout(step_row)

        # Jog 8-way Grid
        pad_grid = QGridLayout()
        pad_grid.setSpacing(4)
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

        pad_grid.addWidget(self.btn_nw, 0, 0)
        pad_grid.addWidget(self.btn_n,  0, 1)
        pad_grid.addWidget(self.btn_ne, 0, 2)
        pad_grid.addWidget(self.btn_w,  1, 0)
        pad_grid.addWidget(self.btn_origin, 1, 1)
        pad_grid.addWidget(self.btn_e,  1, 2)
        pad_grid.addWidget(self.btn_sw, 2, 0)
        pad_grid.addWidget(self.btn_s,  2, 1)
        pad_grid.addWidget(self.btn_se, 2, 2)
        jog_layout.addLayout(pad_grid)

        # Jog Speed Spinbox
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed (mm/min):"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(100, 10000)
        self.speed_spin.setSingleStep(500)
        self.speed_spin.setValue(int(self.jog_speed))
        self.speed_spin.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_spin)
        jog_layout.addLayout(speed_row)

        # Movement Actions
        actions_grid = QGridLayout()
        actions_grid.setSpacing(4)

        self.btn_home = QPushButton("Home ($H)")
        self.btn_home.setToolTip("Run machine homing cycle ($H)")
        self.btn_home.clicked.connect(self.serial_ctrl.home)

        self.btn_unlock = QPushButton("Unlock ($X)")
        self.btn_unlock.setToolTip("Clear alarm lock ($X)")
        self.btn_unlock.clicked.connect(self.serial_ctrl.unlock)

        self.btn_set_origin = QPushButton("Set Origin")
        self.btn_set_origin.setToolTip("Set current position as (0, 0)")
        self.btn_set_origin.clicked.connect(lambda: self.serial_ctrl.set_zero(True, True, True))

        self.btn_fire_laser = QPushButton("Fire Laser")
        self.btn_fire_laser.setCheckable(True)
        self.btn_fire_laser.setToolTip("Toggle low-power test beam (0.5% power) for focusing")
        self.btn_fire_laser.clicked.connect(self._toggle_test_laser)

        actions_grid.addWidget(self.btn_home, 0, 0)
        actions_grid.addWidget(self.btn_unlock, 0, 1)
        actions_grid.addWidget(self.btn_set_origin, 1, 0)
        actions_grid.addWidget(self.btn_fire_laser, 1, 1)
        jog_layout.addLayout(actions_grid)

        main_layout.addWidget(jog_group)

        # 3. Job Execution Group
        job_group = QGroupBox("Job Execution")
        job_layout = QVBoxLayout(job_group)
        job_layout.setContentsMargins(6, 6, 6, 6)
        job_layout.setSpacing(6)

        # Frame Button
        self.btn_frame = QPushButton("⛶  Frame Bounding Box")
        self.btn_frame.setToolTip("Trace job boundary with laser guide before cutting")
        self.btn_frame.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_frame.clicked.connect(self.frame_job_requested.emit)
        job_layout.addWidget(self.btn_frame)

        # Big Run / Pause / Stop Buttons
        run_row = QHBoxLayout()
        run_row.setSpacing(4)

        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 8px; font-size: 12px;"
        )
        self.btn_start.clicked.connect(self.start_job_requested.emit)

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setStyleSheet(
            "background-color: #f57f17; color: white; font-weight: bold; padding: 8px; font-size: 12px;"
        )
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setStyleSheet(
            "background-color: #c62828; color: white; font-weight: bold; padding: 8px; font-size: 12px;"
        )
        self.btn_stop.clicked.connect(self.serial_ctrl.stop_streaming)

        run_row.addWidget(self.btn_start, 2)
        run_row.addWidget(self.btn_pause, 1)
        run_row.addWidget(self.btn_stop, 1)
        job_layout.addLayout(run_row)

        # Progress Bar & Info
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        job_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Idle")
        self.progress_label.setStyleSheet("color: #9e9e9e; font-size: 10px;")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        job_layout.addWidget(self.progress_label)

        main_layout.addWidget(job_group)
        main_layout.addStretch(1)

        # Populate ports initially
        self.refresh_ports()

    def _connect_signals(self):
        self.serial_ctrl.connected.connect(self._on_connected)
        self.serial_ctrl.disconnected.connect(self._on_disconnected)
        self.serial_ctrl.status_updated.connect(self._on_status_updated)
        self.serial_ctrl.job_progress.connect(self._on_job_progress)
        self.serial_ctrl.job_finished.connect(self._on_job_finished)

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = self.serial_ctrl.list_available_ports()
        if not ports:
            self.port_combo.addItem("No ports found")
        else:
            self.port_combo.addItems(ports)
            if current in ports:
                self.port_combo.setCurrentText(current)
            elif "/dev/ttyUSB0" in ports:
                self.port_combo.setCurrentText("/dev/ttyUSB0")

    def _toggle_connection(self):
        if self.serial_ctrl.is_connected:
            self.serial_ctrl.disconnect()
        else:
            port = self.port_combo.currentText()
            if not port or port == "No ports found":
                return
            baud = int(self.baud_combo.currentText())
            self.serial_ctrl.connect(port, baud)

    def _on_connected(self, port: str):
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setStyleSheet("font-weight: bold; background-color: #c62828; color: white;")
        self.status_badge.setText("Connected")
        self.status_badge.setStyleSheet(
            "background-color: #1b5e20; color: #a5d6a7; font-weight: bold; border-radius: 3px; padding: 3px 6px;"
        )

    def _on_disconnected(self):
        self.connect_btn.setText("Connect")
        self.connect_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white;")
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

        self.pos_label.setText(f"X: {wpos[0]:.2f}  Y: {wpos[1]:.2f}")

    def _set_step_dist(self, checked: bool, val: float):
        if checked:
            self.step_distance = val

    def _on_speed_changed(self, val: int):
        self.jog_speed = float(val)

    def _jog(self, x_dir: int, y_dir: int):
        dx = x_dir * self.step_distance
        dy = y_dir * self.step_distance
        self.serial_ctrl.jog(dx, dy, 0.0, self.jog_speed)

    def _toggle_test_laser(self):
        self.is_firing_test = self.btn_fire_laser.isChecked()
        if self.is_firing_test:
            self.btn_fire_laser.setText("Laser ON (0.5%)")
            self.btn_fire_laser.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold;")
            self.serial_ctrl.toggle_test_laser(True, power_s=5) # 5 / 1000 = 0.5%
        else:
            self.btn_fire_laser.setText("Fire Laser")
            self.btn_fire_laser.setStyleSheet("")
            self.serial_ctrl.toggle_test_laser(False)

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
