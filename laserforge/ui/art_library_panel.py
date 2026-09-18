"""
LaserForge Art & Component Library Dock Panel.
Provides an interactive visual manager for reusable vector graphics, hardware hole cutouts,
fasteners, and brackets with drag-and-drop placement onto the 2D CAD canvas.
"""

import base64
import os
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import (
    Qt, pyqtSignal, QSize, QMimeData, QPoint, QByteArray
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QImage, QDrag, QCursor, QAction
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QListWidget, QListWidgetItem, QMenu, QDialog,
    QFormLayout, QTextEdit, QMessageBox, QFileDialog, QInputDialog,
    QToolButton, QFrame
)

from laserforge.core.art_library import (
    ArtItem, ArtLibrary, ArtLibraryManager, render_entities_thumbnail
)
from laserforge.core.models import LaserEntity

MIME_ART_ITEM = "application/x-laserforge-artitem"


class ArtListWidget(QListWidget):
    """Custom QListWidget providing smooth dragging of ArtItems onto the canvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(96, 96))
        self.setGridSize(QSize(116, 134))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(6)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setStyleSheet("""
            QListWidget {
                background-color: #1a1a24;
                border: 1px solid #2d2d3f;
                border-radius: 4px;
                color: #e0e0e0;
                padding: 4px;
            }
            QListWidget::item {
                background-color: #242432;
                border: 1px solid #36364a;
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
                color: #b0bec5;
            }
            QListWidget::item:hover {
                background-color: #2e2e42;
                border: 1px solid #00e5ff;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #383852;
                border: 2px solid #00e5ff;
                color: #ffffff;
            }
        """)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        art_item: Optional[ArtItem] = item.data(Qt.ItemDataRole.UserRole)
        if not art_item:
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData(MIME_ART_ITEM, QByteArray(art_item.id.encode("utf-8")))
        mime_data.setText(art_item.name)
        drag.setMimeData(mime_data)

        # Set drag preview icon
        pix = item.icon().pixmap(QSize(64, 64))
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(32, 32))

        drag.exec(Qt.DropAction.CopyAction)


class AddArtItemDialog(QDialog):
    """Dialog allowing user to save selected canvas shapes into the Art Library."""

    def __init__(self, entities: List[LaserEntity], existing_categories: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Selection to Art Library")
        self.resize(380, 420)
        self.entities = entities
        self.thumbnail_b64 = render_entities_thumbnail(entities)

        self._init_ui(existing_categories)

    def _init_ui(self, existing_categories: List[str]):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Thumbnail preview
        lbl_preview = QLabel()
        lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_preview.setFixedHeight(128)
        lbl_preview.setStyleSheet("background-color: #1e222b; border: 1px solid #36364a; border-radius: 6px;")

        if self.thumbnail_b64:
            img_data = base64.b64decode(self.thumbnail_b64)
            pix = QPixmap()
            pix.loadFromData(img_data)
            lbl_preview.setPixmap(pix.scaled(112, 112, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        layout.addWidget(lbl_preview)

        form = QFormLayout()
        form.setSpacing(8)

        self.txt_name = QLineEdit("My Component")
        form.addRow("Item Name:", self.txt_name)

        self.combo_cat = QComboBox()
        self.combo_cat.setEditable(True)
        cats = [c for c in existing_categories if c != "All Categories"]
        if not cats:
            cats = ["General", "Fasteners", "Mounts & Hangers", "Boxes & Enclosures", "Jewelry & Crafts"]
        self.combo_cat.addItems(cats)
        form.addRow("Category:", self.combo_cat)

        self.txt_tags = QLineEdit("hardware, bracket, cutout")
        form.addRow("Tags (comma-separated):", self.txt_tags)

        self.txt_desc = QTextEdit()
        self.txt_desc.setMaximumHeight(60)
        self.txt_desc.setPlaceholderText("Optional description or specs...")
        form.addRow("Description:", self.txt_desc)

        layout.addLayout(form)

        # Buttons
        h_btn = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 Save to Library")
        btn_save.setStyleSheet("background-color: #00b0ff; color: #000000; font-weight: bold; padding: 6px 16px;")
        btn_save.clicked.connect(self._validate_and_accept)

        h_btn.addStretch()
        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(btn_save)
        layout.addLayout(h_btn)

    def _validate_and_accept(self):
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Please provide a name for the library component.")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        tags = [t.strip() for t in self.txt_tags.text().split(",") if t.strip()]
        return {
            "name": self.txt_name.text().strip(),
            "category": self.combo_cat.currentText().strip() or "General",
            "tags": tags,
            "description": self.txt_desc.toPlainText().strip()
        }


class ArtLibraryPanel(QWidget):
    """
    Dockable Art & Component Library Panel.
    Integrates directly with LaserForge canvas, allowing drag-and-drop insertion
    and one-click saving of canvas selections into user libraries.
    """

    insert_item_requested = pyqtSignal(object)  # Emits ArtItem
    selection_add_requested = pyqtSignal()

    def __init__(self, library_manager: Optional[ArtLibraryManager] = None, parent=None):
        super().__init__(parent)
        self.manager = library_manager or ArtLibraryManager()
        self._init_ui()
        self.refresh_libraries_list()
        self.refresh_items_grid()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 1. Top Header: Library Selector + Manage Menu
        h_top = QHBoxLayout()
        h_top.setSpacing(4)

        lbl_lib = QLabel("Library:")
        lbl_lib.setStyleSheet("font-weight: bold; color: #b0bec5;")
        h_top.addWidget(lbl_lib)

        self.combo_libraries = QComboBox()
        self.combo_libraries.currentIndexChanged.connect(self._on_library_changed)
        h_top.addWidget(self.combo_libraries, 1)

        self.btn_manage = QToolButton()
        self.btn_manage.setText("⚙")
        self.btn_manage.setToolTip("Manage Art Libraries (New, Load, Export, Unload)")
        self.btn_manage.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._create_manage_menu()
        h_top.addWidget(self.btn_manage)

        layout.addLayout(h_top)

        # 2. Filter & Search Row
        h_filter = QHBoxLayout()
        h_filter.setSpacing(4)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search items or tags...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self.refresh_items_grid)
        h_filter.addWidget(self.txt_search, 1)

        self.combo_categories = QComboBox()
        self.combo_categories.currentIndexChanged.connect(self.refresh_items_grid)
        h_filter.addWidget(self.combo_categories)

        layout.addLayout(h_filter)

        # 3. Grid of Art Items
        self.list_items = ArtListWidget(self)
        self.list_items.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_items.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_items.customContextMenuRequested.connect(self._show_item_context_menu)
        layout.addWidget(self.list_items, 1)

        # 4. Bottom Action Bar
        h_actions = QHBoxLayout()
        h_actions.setSpacing(4)

        self.btn_add_selection = QPushButton("➕ Add Selection")
        self.btn_add_selection.setToolTip("Save currently selected canvas shapes to the active library (Ctrl+Shift+L)")
        self.btn_add_selection.setStyleSheet("background-color: #2e7d32; color: #ffffff; font-weight: bold; padding: 5px;")
        self.btn_add_selection.clicked.connect(self.selection_add_requested.emit)
        h_actions.addWidget(self.btn_add_selection)

        self.btn_insert = QPushButton("⬇ Insert on Bed")
        self.btn_insert.setToolTip("Insert selected component onto laser workbed center")
        self.btn_insert.setStyleSheet("background-color: #0277bd; color: #ffffff; font-weight: bold; padding: 5px;")
        self.btn_insert.clicked.connect(self._insert_current_item)
        h_actions.addWidget(self.btn_insert)

        layout.addLayout(h_actions)

    def _create_manage_menu(self):
        menu = QMenu(self)

        act_new = menu.addAction("➕ New Library...")
        act_new.triggered.connect(self._on_new_library)

        act_load = menu.addAction("📂 Open / Load Library (.lflib)...")
        act_load.triggered.connect(self._on_load_library)

        act_export = menu.addAction("📤 Export Active Library...")
        act_export.triggered.connect(self._on_export_library)

        menu.addSeparator()
        act_unload = menu.addAction("❌ Unload Active Library")
        act_unload.triggered.connect(self._on_unload_library)

        act_reset_std = menu.addAction("🔄 Reload Standard Components")
        act_reset_std.triggered.connect(self._on_reload_standard_library)

        self.btn_manage.setMenu(menu)

    def refresh_libraries_list(self):
        """Populates the library selector dropdown."""
        self.combo_libraries.blockSignals(True)
        self.combo_libraries.clear()

        for lib_name in sorted(self.manager.loaded_libraries.keys()):
            self.combo_libraries.addItem(lib_name)

        if self.manager.active_library_name:
            idx = self.combo_libraries.findText(self.manager.active_library_name)
            if idx >= 0:
                self.combo_libraries.setCurrentIndex(idx)

        self.combo_libraries.blockSignals(False)
        self._refresh_categories_combo()

    def _refresh_categories_combo(self):
        active_lib = self.manager.get_active_library()
        self.combo_categories.blockSignals(True)
        self.combo_categories.clear()

        if active_lib:
            for cat in active_lib.get_categories():
                self.combo_categories.addItem(cat)
        else:
            self.combo_categories.addItem("All Categories")

        self.combo_categories.blockSignals(False)

    def refresh_items_grid(self):
        """Filters and populates the ArtItems visual grid."""
        self.list_items.clear()
        active_lib = self.manager.get_active_library()
        if not active_lib:
            return

        query = self.txt_search.text().strip()
        cat = self.combo_categories.currentText()

        items = active_lib.filter_items(query=query, category=cat)

        for it in items:
            item_widget = QListWidgetItem()
            item_widget.setText(f"{it.name}\n({it.width_mm:.1f}×{it.height_mm:.1f}mm)")
            item_widget.setToolTip(
                f"<b>{it.name}</b><br/>"
                f"<b>Category:</b> {it.category}<br/>"
                f"<b>Dimensions:</b> {it.width_mm:.1f} × {it.height_mm:.1f} mm<br/>"
                f"<b>Tags:</b> {', '.join(it.tags)}<br/>"
                f"<i>{it.description}</i><br/><br/>"
                f"<i>Drag onto canvas or double-click to insert</i>"
            )

            # Thumbnail Icon
            if it.thumbnail_b64:
                img_bytes = base64.b64decode(it.thumbnail_b64)
                pix = QPixmap()
                pix.loadFromData(img_bytes)
                item_widget.setIcon(QIcon(pix))
            else:
                pix = QPixmap(96, 96)
                pix.fill(Qt.GlobalColor.transparent)
                item_widget.setIcon(QIcon(pix))

            item_widget.setData(Qt.ItemDataRole.UserRole, it)
            self.list_items.addItem(item_widget)

    def _on_library_changed(self, index: int):
        lib_name = self.combo_libraries.currentText()
        if lib_name and self.manager.set_active_library(lib_name):
            self._refresh_categories_combo()
            self.refresh_items_grid()

    def _on_item_double_clicked(self, item: QListWidgetItem):
        art_item = item.data(Qt.ItemDataRole.UserRole)
        if art_item:
            self.insert_item_requested.emit(art_item)

    def _insert_current_item(self):
        item = self.list_items.currentItem()
        if item:
            art_item = item.data(Qt.ItemDataRole.UserRole)
            if art_item:
                self.insert_item_requested.emit(art_item)

    def _show_item_context_menu(self, pos: QPoint):
        item = self.list_items.itemAt(pos)
        if not item:
            return

        art_item: ArtItem = item.data(Qt.ItemDataRole.UserRole)
        if not art_item:
            return

        menu = QMenu(self)

        act_insert = menu.addAction("⬇ Insert on Canvas")
        act_insert.triggered.connect(lambda: self.insert_item_requested.emit(art_item))

        menu.addSeparator()

        act_edit = menu.addAction("✏ Edit Name & Tags...")
        act_edit.triggered.connect(lambda: self._edit_item_metadata(art_item))

        act_del = menu.addAction("🗑 Delete from Library")
        act_del.triggered.connect(lambda: self._delete_item(art_item))

        menu.exec(self.list_items.mapToGlobal(pos))

    def _edit_item_metadata(self, art_item: ArtItem):
        new_name, ok = QInputDialog.getText(self, "Edit Name", "Component Name:", text=art_item.name)
        if not ok or not new_name.strip():
            return
        art_item.name = new_name.strip()

        new_tags, ok = QInputDialog.getText(
            self, "Edit Tags", "Tags (comma-separated):", text=", ".join(art_item.tags)
        )
        if ok:
            art_item.tags = [t.strip() for t in new_tags.split(",") if t.strip()]

        active_lib = self.manager.get_active_library()
        if active_lib:
            active_lib.save()

        self.refresh_items_grid()

    def _delete_item(self, art_item: ArtItem):
        confirm = QMessageBox.question(
            self,
            "Delete Component",
            f"Are you sure you want to remove '{art_item.name}' from the active library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            active_lib = self.manager.get_active_library()
            if active_lib:
                active_lib.remove_item(art_item.id)
                active_lib.save()
                self.refresh_items_grid()

    def _on_new_library(self):
        name, ok = QInputDialog.getText(self, "New Art Library", "Enter library name (e.g. Custom_Brackets):")
        if not ok or not name.strip():
            return
        self.manager.create_new_library(name.strip())
        self.refresh_libraries_list()
        self.refresh_items_grid()

    def _on_load_library(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Open Art Library", self.manager.libraries_dir, "LaserForge Art Library (*.lflib);;All Files (*.*)"
        )
        if fpath:
            lib = self.manager.load_external_library(fpath)
            if lib:
                self.refresh_libraries_list()
                self.refresh_items_grid()

    def _on_export_library(self):
        active_lib = self.manager.get_active_library()
        if not active_lib:
            return
        fpath, _ = QFileDialog.getSaveFileName(
            self, "Export Art Library", f"{active_lib.name}.lflib", "LaserForge Art Library (*.lflib)"
        )
        if fpath:
            active_lib.save(fpath)
            QMessageBox.information(self, "Library Exported", f"Successfully exported library to:\n{fpath}")

    def _on_unload_library(self):
        active_lib = self.manager.get_active_library()
        if not active_lib:
            return
        if active_lib.name == "Standard Hardware & Laser Components":
            QMessageBox.warning(self, "Protected Library", "The built-in Standard Hardware library cannot be unloaded.")
            return

        self.manager.unload_library(active_lib.name)
        self.refresh_libraries_list()
        self.refresh_items_grid()

    def _on_reload_standard_library(self):
        std_path = os.path.join(self.manager.libraries_dir, "Standard_Hardware.lflib")
        from laserforge.core.art_library import create_default_standard_library
        lib = create_default_standard_library(std_path)
        lib.save()
        self.manager.loaded_libraries[lib.name] = lib
        self.manager.set_active_library(lib.name)
        self.refresh_libraries_list()
        self.refresh_items_grid()
        QMessageBox.information(self, "Standard Library Reloaded", "Default standard hardware components have been restored.")

    def add_entities_to_active_library(self, entities: List[LaserEntity]):
        """Prompts user to save the given canvas entities into the active library."""
        if not entities:
            QMessageBox.information(self, "No Selection", "Please select one or more shapes on the canvas first.")
            return

        active_lib = self.manager.get_active_library()
        if not active_lib:
            QMessageBox.warning(self, "No Active Library", "Please create or select an active library first.")
            return

        dlg = AddArtItemDialog(entities, active_lib.get_categories(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            item = active_lib.add_item_from_entities(
                name=data["name"],
                entities=entities,
                category=data["category"],
                tags=data["tags"],
                description=data["description"]
            )
            active_lib.save()
            self._refresh_categories_combo()
            self.refresh_items_grid()
            QMessageBox.information(self, "Component Saved", f"'{item.name}' added to {active_lib.name}!")
