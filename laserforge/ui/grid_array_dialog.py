"""
LaserForge Grid Array & Matrix Duplicate Tool.
Duplicates selected CAD entities into a multi-row and multi-column production grid with exact spacing.
"""

from typing import List, Tuple, Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QComboBox, QGroupBox, QMessageBox
)

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity, ImageEntity
)


class GridArrayDialog(QDialog):
    grid_generated = pyqtSignal(list)  # Emits list of new LaserEntity duplicates

    def __init__(
        self,
        parent=None,
        selected_entities: Optional[List[LaserEntity]] = None,
        bed_width: float = 150.0,
        bed_height: float = 200.0
    ):
        super().__init__(parent)
        self.setWindowTitle("Grid Array & Matrix Duplication Tool")
        self.resize(440, 380)
        self.selected_entities = selected_entities or []
        self.bed_width = bed_width
        self.bed_height = bed_height

        self._calc_selection_bounds()
        self._init_ui()
        self._update_stats()

    def _calc_selection_bounds(self):
        if not self.selected_entities:
            self.sel_w = 40.0
            self.sel_h = 40.0
            self.min_x = 0.0
            self.min_y = 0.0
            return

        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for ent in self.selected_entities:
            b = ent.get_bounds()
            min_x = min(min_x, b[0])
            min_y = min(min_y, b[1])
            max_x = max(max_x, b[2])
            max_y = max(max_y, b[3])

        self.min_x = min_x
        self.min_y = min_y
        self.sel_w = max(1.0, max_x - min_x)
        self.sel_h = max(1.0, max_y - min_y)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl_desc = QLabel(
            f"Duplicating {len(self.selected_entities)} selected object(s) "
            f"({self.sel_w:.1f} × {self.sel_h:.1f} mm) into a batch production matrix."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #80d8ff; font-weight: bold;")
        layout.addWidget(lbl_desc)

        grid = QGridLayout()
        grid.setSpacing(8)

        # Rows & Columns
        grid.addWidget(QLabel("Columns (X count):"), 0, 0)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 50)
        self.spin_cols.setValue(3)
        self.spin_cols.valueChanged.connect(self._update_stats)
        grid.addWidget(self.spin_cols, 0, 1)

        grid.addWidget(QLabel("Rows (Y count):"), 1, 0)
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 50)
        self.spin_rows.setValue(3)
        self.spin_rows.valueChanged.connect(self._update_stats)
        grid.addWidget(self.spin_rows, 1, 1)

        # Spacing mode
        grid.addWidget(QLabel("Spacing Mode:"), 2, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Gap Margin Between Objects", "gap")
        self.combo_mode.addItem("Center-to-Center Pitch", "pitch")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        grid.addWidget(self.combo_mode, 2, 1)

        grid.addWidget(QLabel("X Spacing (mm):"), 3, 0)
        self.spin_x_spacing = QDoubleSpinBox()
        self.spin_x_spacing.setRange(0.0, 100.0)
        self.spin_x_spacing.setValue(5.0)
        self.spin_x_spacing.setSuffix(" mm")
        self.spin_x_spacing.valueChanged.connect(self._update_stats)
        grid.addWidget(self.spin_x_spacing, 3, 1)

        grid.addWidget(QLabel("Y Spacing (mm):"), 4, 0)
        self.spin_y_spacing = QDoubleSpinBox()
        self.spin_y_spacing.setRange(0.0, 100.0)
        self.spin_y_spacing.setValue(5.0)
        self.spin_y_spacing.setSuffix(" mm")
        self.spin_y_spacing.valueChanged.connect(self._update_stats)
        grid.addWidget(self.spin_y_spacing, 4, 1)

        layout.addLayout(grid)

        # Footprint stats
        stat_grp = QGroupBox("Total Matrix Footprint")
        stat_layout = QVBoxLayout(stat_grp)
        self.lbl_matrix_size = QLabel()
        self.lbl_matrix_size.setStyleSheet("font-size: 11px;")
        stat_layout.addWidget(self.lbl_matrix_size)
        layout.addWidget(stat_grp)

        layout.addStretch(1)

        # Actions
        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_create = QPushButton("✨ Generate Grid Array")
        btn_create.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; padding: 6px 16px;")
        btn_create.clicked.connect(self._on_create)
        btn_box.addWidget(btn_create)

        layout.addLayout(btn_box)

    def _on_mode_changed(self, idx: int):
        mode = self.combo_mode.currentData()
        if mode == "pitch":
            self.spin_x_spacing.setValue(self.sel_w + 5.0)
            self.spin_y_spacing.setValue(self.sel_h + 5.0)
        else:
            self.spin_x_spacing.setValue(5.0)
            self.spin_y_spacing.setValue(5.0)
        self._update_stats()

    def _update_stats(self):
        cols = self.spin_cols.value()
        rows = self.spin_rows.value()
        mode = self.combo_mode.currentData()

        if mode == "gap":
            gap_x = self.spin_x_spacing.value()
            gap_y = self.spin_y_spacing.value()
            total_w = cols * self.sel_w + (cols - 1) * gap_x
            total_h = rows * self.sel_h + (rows - 1) * gap_y
        else:
            pitch_x = self.spin_x_spacing.value()
            pitch_y = self.spin_y_spacing.value()
            total_w = (cols - 1) * pitch_x + self.sel_w
            total_h = (rows - 1) * pitch_y + self.sel_h

        fits = (total_w <= self.bed_width and total_h <= self.bed_height)
        fit_status = "✅ Fits Laser Bed" if fits else "⚠️ Exceeds Laser Bed!"
        color = "#69f0ae" if fits else "#ff5252"

        self.lbl_matrix_size.setText(
            f"Total Dimensions: {total_w:.1f} × {total_h:.1f} mm  |  "
            f"Copies: {cols * rows} items  |  "
            f"<font color='{color}'><b>{fit_status}</b></font>"
        )

    def _on_create(self):
        cols = self.spin_cols.value()
        rows = self.spin_rows.value()
        mode = self.combo_mode.currentData()

        if mode == "gap":
            step_x = self.sel_w + self.spin_x_spacing.value()
            step_y = self.sel_h + self.spin_y_spacing.value()
        else:
            step_x = self.spin_x_spacing.value()
            step_y = self.spin_y_spacing.value()

        new_entities: List[LaserEntity] = []

        for r in range(rows):
            for c in range(cols):
                if r == 0 and c == 0:
                    continue  # Original is at (0, 0)
                dx = c * step_x
                dy = r * step_y

                for e in self.selected_entities:
                    new_e = None
                    if isinstance(e, RectEntity):
                        new_e = RectEntity(layer_id=e.layer_id, name=f"{e.name}_{c}_{r}", x=e.x + dx, y=e.y + dy, width=e.width, height=e.height, corner_radius=e.corner_radius)
                    elif isinstance(e, CircleEntity):
                        new_e = CircleEntity(layer_id=e.layer_id, name=f"{e.name}_{c}_{r}", x=e.x + dx, y=e.y + dy, radius_x=e.radius_x, radius_y=e.radius_y)
                    elif isinstance(e, LineEntity):
                        new_e = LineEntity(layer_id=e.layer_id, name=f"{e.name}_{c}_{r}", x=e.x + dx, y=e.y + dy, x2=e.x2 + dx, y2=e.y2 + dy)
                    elif isinstance(e, TextEntity):
                        new_e = TextEntity(
                            layer_id=e.layer_id, name=f"{e.name}_{c}_{r}", x=e.x + dx, y=e.y + dy,
                            text=e.text, font_family=e.font_family, font_size=e.font_size,
                            bold=e.bold, italic=e.italic, underline=getattr(e, "underline", False),
                            fill_mode=getattr(e, "fill_mode", "Fill"),
                            width=e.width, height=e.height
                        )
                    elif isinstance(e, PathEntity):
                        new_contours = [list(cnt) for cnt in e.contours]
                        new_e = PathEntity(layer_id=e.layer_id, name=f"{e.name}_{c}_{r}", x=e.x + dx, y=e.y + dy, contours=new_contours, closed=e.closed)
                    elif isinstance(e, ImageEntity):
                        new_e = ImageEntity(
                            layer_id=e.layer_id, name=f"{e.name}_{c}_{r}", x=e.x + dx, y=e.y + dy,
                            width=e.width, height=e.height, image_path=e.image_path,
                            dither_mode=e.dither_mode, invert=e.invert, contrast=e.contrast,
                            brightness=e.brightness, threshold_value=e.threshold_value, dpi=e.dpi,
                            gamma=getattr(e, "gamma", 1.0), sharpen=getattr(e, "sharpen", 0.0),
                            equalize=getattr(e, "equalize", False), white_clip=getattr(e, "white_clip", 255),
                            halftone_cell_size=getattr(e, "halftone_cell_size", 6.0),
                            halftone_angle_deg=getattr(e, "halftone_angle_deg", 45.0)
                        )
                    if new_e:
                        new_entities.append(new_e)

        self.grid_generated.emit(new_entities)
        self.accept()
