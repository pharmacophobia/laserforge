"""
LaserForge Common Line Cutting Studio Dialog.
Interactively detects and eliminates coincident / overlapping cut seams between adjacent
tiled or nested vector parts, providing cutting telemetry and 1-click canvas replacement.
"""

from typing import List, Optional
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPen, QPainter
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox,
    QGroupBox, QFormLayout, QGraphicsView, QGraphicsScene, QCheckBox,
    QMessageBox, QSplitter, QWidget
)

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity
)
from laserforge.core.common_line_engine import CommonLineEngine, CommonLineResult


class CommonLinePreviewCanvas(QGraphicsView):
    """Visual preview rendering original vs optimized common-line toolpaths."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setBackgroundBrush(QColor("#1a1a24"))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setMinimumHeight(240)

    def display_result(self, orig_paths: List[List], result: Optional[CommonLineResult]):
        self.scene.clear()
        if not orig_paths and not result:
            return

        pen_orig = QPen(QColor("#455a64"), 1.0, Qt.PenStyle.DashLine)
        pen_optimized = QPen(QColor("#00e5ff"), 2.0, Qt.PenStyle.SolidLine)

        # Draw original faint dashed outlines
        for path in orig_paths:
            for i in range(len(path) - 1):
                self.scene.addLine(path[i][0], path[i][1], path[i+1][0], path[i+1][1], pen_orig)

        # Draw optimized toolpaths
        if result and result.optimized_paths:
            for path in result.optimized_paths:
                for i in range(len(path) - 1):
                    self.scene.addLine(path[i][0], path[i][1], path[i+1][0], path[i+1][1], pen_optimized)

        self.setSceneRect(self.scene.itemsBoundingRect().adjusted(-10, -10, 10, 10))
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class CommonLineDialog(QDialog):
    """Common Line Cutting & Edge De-duplication Studio Dialog."""

    paths_optimized = pyqtSignal(list, bool)  # Emits (list of PathEntity, replace_existing)

    def __init__(self, entities: List[LaserEntity], cut_speed_mm_min: float = 1000.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Common Line Cutting & Edge De-duplication Studio")
        self.resize(700, 520)
        self.entities = entities
        self.cut_speed = max(100.0, cut_speed_mm_min)
        self.raw_paths: List[List[tuple]] = []
        self.closed_flags: List[bool] = []
        self.latest_result: Optional[CommonLineResult] = None

        self._extract_entity_paths()
        self._init_ui()
        self._run_optimization()

    def _extract_entity_paths(self):
        """Converts entities to raw coordinate paths for analysis."""
        self.raw_paths = []
        self.closed_flags = []
        for e in self.entities:
            if isinstance(e, RectEntity):
                pts = [
                    (e.x, e.y), (e.x + e.width, e.y),
                    (e.x + e.width, e.y + e.height), (e.x, e.y + e.height),
                    (e.x, e.y)
                ]
                self.raw_paths.append(pts)
                self.closed_flags.append(True)
            elif isinstance(e, PathEntity):
                for c in e.contours:
                    if len(c) >= 2:
                        self.raw_paths.append([(e.x + pt[0], e.y + pt[1]) for pt in c])
                        self.closed_flags.append(e.closed)
            elif isinstance(e, LineEntity):
                self.raw_paths.append([(e.x, e.y), (e.x2, e.y2)])
                self.closed_flags.append(False)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header description
        lbl_info = QLabel(
            "Detects and eliminates shared cut lines between touching adjacent parts. "
            "Cuts the seam once instead of twice to prevent edge scorching and slash cutting times."
        )
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #b0bec5; font-size: 11px;")
        layout.addWidget(lbl_info)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Controls & Telemetry
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        grp_params = QGroupBox("Tolerance Settings")
        form_params = QFormLayout(grp_params)
        self.spin_tol = QDoubleSpinBox()
        self.spin_tol.setRange(0.01, 1.00)
        self.spin_tol.setValue(0.08)
        self.spin_tol.setSingleStep(0.01)
        self.spin_tol.setSuffix(" mm")
        self.spin_tol.setToolTip("Maximum distance gap between collinear edges to consider them coincident.")
        self.spin_tol.valueChanged.connect(self._run_optimization)
        form_params.addRow("Collinear Tolerance:", self.spin_tol)
        left_layout.addWidget(grp_params)

        grp_stats = QGroupBox("Cutting Optimization Telemetry")
        form_stats = QFormLayout(grp_stats)
        self.lbl_orig_segs = QLabel("0")
        self.lbl_opt_segs = QLabel("0")
        self.lbl_shared_elim = QLabel("0")
        self.lbl_shared_elim.setStyleSheet("color: #00e5ff; font-weight: bold;")
        self.lbl_saved_len = QLabel("0 mm")
        self.lbl_saved_len.setStyleSheet("color: #00e676; font-weight: bold;")
        self.lbl_saved_time = QLabel("0.0 s")
        self.lbl_saved_time.setStyleSheet("color: #ffab00; font-weight: bold;")

        form_stats.addRow("Original Cut Segments:", self.lbl_orig_segs)
        form_stats.addRow("Optimized Cut Segments:", self.lbl_opt_segs)
        form_stats.addRow("Shared Seams Eliminated:", self.lbl_shared_elim)
        form_stats.addRow("Cutting Travel Saved:", self.lbl_saved_len)
        form_stats.addRow("Runtime Saved (at cut speed):", self.lbl_saved_time)
        left_layout.addWidget(grp_stats)

        self.chk_replace = QCheckBox("Replace selected shapes on canvas with common lines")
        self.chk_replace.setChecked(True)
        left_layout.addWidget(self.chk_replace)

        left_layout.addStretch()
        splitter.addWidget(left_widget)

        # Right Visual Canvas Preview
        self.preview_canvas = CommonLinePreviewCanvas(self)
        splitter.addWidget(self.preview_canvas)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter, 1)

        # Bottom Buttons
        h_btn = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_apply = QPushButton("⚡ Apply Common Line Cutpaths")
        btn_apply.setStyleSheet("background-color: #00b0ff; color: #000000; font-weight: bold; padding: 6px 16px;")
        btn_apply.clicked.connect(self._apply_and_accept)

        h_btn.addStretch()
        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(btn_apply)
        layout.addLayout(h_btn)

    def _run_optimization(self):
        tol = self.spin_tol.value()
        self.latest_result = CommonLineEngine.deduplicate_common_lines(
            self.raw_paths,
            closed_flags=self.closed_flags,
            tolerance=tol
        )

        res = self.latest_result
        self.lbl_orig_segs.setText(str(res.original_segment_count))
        self.lbl_opt_segs.setText(str(res.optimized_segment_count))
        self.lbl_shared_elim.setText(str(res.shared_lines_count))

        pct_saved = 0.0
        if res.original_cutting_length_mm > 0:
            pct_saved = (res.saved_cutting_length_mm / res.original_cutting_length_mm) * 100.0
        self.lbl_saved_len.setText(f"{res.saved_cutting_length_mm:.1f} mm ({pct_saved:.1f}%)")

        saved_time_sec = (res.saved_cutting_length_mm / self.cut_speed) * 60.0
        self.lbl_saved_time.setText(f"{saved_time_sec:.1f} seconds")

        self.preview_canvas.display_result(self.raw_paths, res)

    def _apply_and_accept(self):
        if not self.latest_result or not self.latest_result.optimized_paths:
            QMessageBox.warning(self, "No Result", "No toolpaths available to apply.")
            return

        # Convert optimized coordinate chains into PathEntity objects
        path_entities = []
        layer_id = self.entities[0].layer_id if self.entities else 0
        for i, chain in enumerate(self.latest_result.optimized_paths):
            if len(chain) >= 2:
                is_closed = (chain[0] == chain[-1] and len(chain) > 2)
                p_ent = PathEntity(
                    layer_id=layer_id,
                    name=f"CommonLine_{i+1}",
                    x=0.0,
                    y=0.0,
                    contours=[chain],
                    closed=is_closed
                )
                path_entities.append(p_ent)

        self.paths_optimized.emit(path_entities, self.chk_replace.isChecked())
        self.accept()
