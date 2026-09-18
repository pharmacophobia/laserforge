"""
Unit and Integration Tests for LaserForge Variable Text & Batch CSV Production Merge Engine.
Verifies CSV/TSV loading, template variable scanning, formatted placeholder substitution,
grid array placement, boundary validation, and VariableTextDialog UI integration.
"""

import os
import tempfile
import unittest
from PyQt6.QtWidgets import QApplication

from laserforge.core.models import RectEntity, TextEntity
from laserforge.core.variable_text_engine import (
    VariableTextDataset, VariableTextEngine
)
from laserforge.ui.variable_text_dialog import VariableTextDialog

app = QApplication.instance() or QApplication([])


class TestVariableTextEngine(unittest.TestCase):

    def setUp(self):
        self.temp_csv = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv")
        self.temp_csv.write("NAME,ROLE,DEPARTMENT\nAlice,Lead Engineer,R&D\nBob,QA Lead,Operations\nCharlie,Product Designer,UX\n")
        self.temp_csv.close()

    def tearDown(self):
        if os.path.exists(self.temp_csv.name):
            os.unlink(self.temp_csv.name)

    def test_csv_loading_and_dataset(self):
        """Tests dialect sniffing, column detection, and row parsing."""
        ds = VariableTextDataset.from_csv_file(self.temp_csv.name)
        self.assertEqual(len(ds.headers), 3)
        self.assertIn("NAME", ds.headers)
        self.assertIn("ROLE", ds.headers)
        self.assertIn("DEPARTMENT", ds.headers)
        self.assertEqual(len(ds.rows), 3)
        self.assertEqual(ds.rows[0]["NAME"], "Alice")
        self.assertEqual(ds.rows[1]["ROLE"], "QA Lead")
        self.assertEqual(ds.rows[2]["DEPARTMENT"], "UX")

    def test_variable_scanner_and_substitution(self):
        """Tests detection of template placeholders and formatted string substitution."""
        t1 = TextEntity(text="Badge: %NAME% (%ROLE%)")
        t2 = TextEntity(text="ID: SN-%SERIAL:04d% / %DATE%")
        r1 = RectEntity(width=60.0, height=30.0)

        vars_found = VariableTextEngine.find_template_variables([t1, t2, r1])
        self.assertIn("NAME", vars_found)
        self.assertIn("ROLE", vars_found)
        self.assertIn("SERIAL:04d", vars_found)
        self.assertIn("DATE", vars_found)

        # Substitute for row 1 (Alice)
        row_data = {"NAME": "Alice", "ROLE": "Lead Engineer"}
        res1 = VariableTextEngine.substitute_variables("Badge: %NAME% (%ROLE%)", row_data, row_index=1, serial_start=42)
        self.assertEqual(res1, "Badge: Alice (Lead Engineer)")

        # Formatted serial number: %SERIAL:04d% with serial_start=42 -> "0042"
        res2 = VariableTextEngine.substitute_variables("ID: SN-%SERIAL:04d%", row_data, row_index=1, serial_start=42)
        self.assertEqual(res2, "ID: SN-0042")

    def test_batch_grid_array_placement(self):
        """Tests multi-item production grid array placement and bed boundary checking."""
        badge_box = RectEntity(x=0.0, y=0.0, width=50.0, height=25.0)
        badge_text = TextEntity(x=5.0, y=10.0, text="Staff: %NAME%", font_size=10.0, width=40.0, height=10.0)

        ds = VariableTextDataset.from_csv_file(self.temp_csv.name)

        # Bed is 200x200 mm, 3 items fit easily in 2 columns
        batch_entities, meta = VariableTextEngine.generate_batch_array(
            template_entities=[badge_box, badge_text],
            dataset=ds,
            bed_width=200.0,
            bed_height=200.0,
            spacing_x=10.0,
            spacing_y=10.0,
            margin_x=10.0,
            margin_y=10.0,
            columns=2
        )

        # 3 rows * 2 template items = 6 entities generated
        self.assertEqual(len(batch_entities), 6)
        self.assertEqual(meta["total_dataset_rows"], 3)
        self.assertEqual(meta["placed_items"], 3)
        self.assertEqual(meta["unplaced_items"], 0)
        self.assertTrue(meta["bed_fit"])

        # Verify generated text contents
        text_ents = [e for e in batch_entities if isinstance(e, TextEntity)]
        self.assertEqual(len(text_ents), 3)
        self.assertEqual(text_ents[0].text, "Staff: Alice")
        self.assertEqual(text_ents[1].text, "Staff: Bob")
        self.assertEqual(text_ents[2].text, "Staff: Charlie")

    def test_variable_text_dialog_ui(self):
        """Tests VariableTextDialog table view, variable listing, and batch signal emission."""
        badge_text = TextEntity(x=5.0, y=10.0, text="Staff: %NAME%", font_size=10.0, width=40.0, height=10.0)
        dlg = VariableTextDialog([badge_text], bed_width=300.0, bed_height=300.0)

        self.assertIn("NAME", dlg.detected_vars)

        # Load CSV into dialog
        ds = VariableTextDataset.from_csv_file(self.temp_csv.name)
        dlg.load_dataset(ds)

        self.assertEqual(dlg.table.rowCount(), 3)
        self.assertEqual(dlg.table.columnCount(), 3)

        emitted_batch = []
        dlg.batch_generated.connect(lambda ents: emitted_batch.extend(ents))
        dlg._on_generate_batch()

        self.assertEqual(len(emitted_batch), 3)
        self.assertEqual(emitted_batch[0].text, "Staff: Alice")


if __name__ == "__main__":
    unittest.main()
