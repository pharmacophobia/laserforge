"""
LaserForge Variable Text & Batch Production Merge Engine.
Merges external CSV / TSV / Excel data with vector design templates (name tags,
serialized asset plates, compliance tags, barcodes/QRs) into tiled production grids.
"""

from dataclasses import dataclass, field
import csv
import copy
from datetime import datetime
import io
import os
import re
import uuid
from typing import List, Dict, Any, Tuple, Optional

from laserforge.core.models import (
    LaserEntity, RectEntity, CircleEntity, LineEntity, PathEntity, TextEntity
)
from laserforge.core.business_card_generator import generate_qr_contours
from laserforge.core.barcode_generator import BarcodeGenerator


@dataclass
class VariableDataRow:
    row_index: int
    fields: Dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> str:
        return self.fields[key]

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)


@dataclass
class VariableTextDataset:
    columns: List[str] = field(default_factory=list)
    rows: List[VariableDataRow] = field(default_factory=list)

    @property
    def headers(self) -> List[str]:
        return self.columns

    @classmethod
    def from_csv_file(cls, filepath: str) -> "VariableTextDataset":
        """Loads dataset from CSV or TSV file with automatic delimiter detection."""
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return cls.from_csv_string(content)

    @classmethod
    def from_csv_string(cls, content: str) -> "VariableTextDataset":
        """Parses CSV string content with Sniffer for comma, semicolon, tab."""
        f_io = io.StringIO(content.strip())
        sample = content[:2048]

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

        f_io.seek(0)
        reader = csv.reader(f_io, delimiter=delimiter)
        raw_rows = [row for row in reader if row]

        if not raw_rows:
            return cls()

        # Clean header column names
        headers = [h.strip() for h in raw_rows[0]]
        dataset_rows: List[VariableDataRow] = []

        for idx, row in enumerate(raw_rows[1:], start=1):
            row_dict = {}
            for col_idx, col_name in enumerate(headers):
                val = row[col_idx].strip() if col_idx < len(row) else ""
                row_dict[col_name] = val
                # Also index by column number $1, $2
                row_dict[f"COL{col_idx+1}"] = val
            dataset_rows.append(VariableDataRow(row_index=idx, fields=row_dict))

        return cls(columns=headers, rows=dataset_rows)


class VariableTextEngine:
    """
    Evaluates placeholder variable tags and performs high-throughput
    tiled grid batch generation for commercial personalization runs.
    """

    VAR_PATTERN = re.compile(r"%([A-Za-z0-9_:]+)%")

    @staticmethod
    def extract_variables(text: str) -> List[str]:
        """Finds all %VARIABLE% tags in a text string."""
        return VariableTextEngine.VAR_PATTERN.findall(text)

    @staticmethod
    def find_template_variables(entities: List[LaserEntity]) -> List[str]:
        """Scans all TextEntities in template to discover used variable placeholders."""
        found = set()
        for e in entities:
            if isinstance(e, TextEntity):
                vars_in_text = VariableTextEngine.extract_variables(e.text)
                found.update(vars_in_text)
        return sorted(found)

    @staticmethod
    def substitute_variables(
        template_text: str,
        row_data: Dict[str, str],
        row_index: int = 1,
        serial_start: int = 1,
        serial_step: int = 1
    ) -> str:
        """
        Replaces %TAG% placeholders with row values, auto-serial, or date/time macros.
        Supports format specifiers like %SERIAL:04d% -> '0001'.
        """
        now = datetime.now()

        def repl(match):
            tag_raw = match.group(1)
            fmt = None
            if ":" in tag_raw:
                parts = tag_raw.split(":", 1)
                tag_name = parts[0]
                fmt = parts[1]
            else:
                tag_name = tag_raw

            tag_upper = tag_name.upper()

            # Built-in dynamic macros
            if tag_upper == "ROW":
                val = row_index
            elif tag_upper == "SERIAL":
                val = serial_start + (row_index - 1) * serial_step
            elif tag_upper == "DATE":
                return now.strftime("%Y-%m-%d")
            elif tag_upper == "TIME":
                return now.strftime("%H:%M:%S")
            elif tag_upper == "YEAR":
                return str(now.year)
            else:
                # Search in row fields (case-insensitive lookup)
                matched_key = next((k for k in row_data if k.lower() == tag_name.lower()), None)
                if matched_key:
                    return str(row_data[matched_key])
                return match.group(0)  # Keep unchanged if not found

            # Apply formatting (e.g. 04d)
            if fmt:
                try:
                    return f"{val:{fmt}}"
                except Exception:
                    pass
            return str(val)

        return VariableTextEngine.VAR_PATTERN.sub(repl, template_text)

    @staticmethod
    def generate_batch_array(
        template_entities: List[LaserEntity],
        dataset: VariableTextDataset,
        bed_width: float = 400.0,
        bed_height: float = 400.0,
        spacing_x: float = 5.0,
        spacing_y: float = 5.0,
        margin_x: float = 10.0,
        margin_y: float = 10.0,
        columns: Optional[int] = None,
        rows: Optional[int] = None,
        serial_start: int = 1,
        serial_step: int = 1,
        max_items: Optional[int] = None
    ) -> Tuple[List[LaserEntity], Dict[str, Any]]:
        """
        Renders a full tiled grid of personalized parts on the laser bed.
        Returns (generated_entities, telemetry_summary).
        """
        if not template_entities or not dataset.rows:
            return [], {}

        # 1. Determine template bounding box
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")

        for e in template_entities:
            bx1, by1, bx2, by2 = e.get_bounds()
            if bx1 < min_x: min_x = bx1
            if by1 < min_y: min_y = by1
            if bx2 > max_x: max_x = bx2
            if by2 > max_y: max_y = by2

        t_width = max(1.0, max_x - min_x)
        t_height = max(1.0, max_y - min_y)

        # 2. Determine grid dimensions
        total_items = len(dataset.rows)
        if max_items:
            total_items = min(total_items, max_items)

        # Auto-calculate columns and rows if not specified
        avail_w = bed_width - 2 * margin_x
        avail_h = bed_height - 2 * margin_y

        max_cols_possible = max(1, int((avail_w + spacing_x) / (t_width + spacing_x)))
        max_rows_possible = max(1, int((avail_h + spacing_y) / (t_height + spacing_y)))

        cols = columns if (columns and columns > 0) else max_cols_possible
        # Bound cols
        cols = max(1, min(cols, total_items))

        # 3. Generate batch instances
        generated_entities: List[LaserEntity] = []
        placed_count = 0

        for idx, row in enumerate(dataset.rows[:total_items], start=1):
            c = (idx - 1) % cols
            r = (idx - 1) // cols

            target_x = margin_x + c * (t_width + spacing_x)
            target_y = margin_y + r * (t_height + spacing_y)

            # Check bed boundary
            if (target_x + t_width > bed_width + 0.1) or (target_y + t_height > bed_height + 0.1):
                # Out of bounds on bed
                break

            offset_x = target_x - min_x
            offset_y = target_y - min_y

            for orig_ent in template_entities:
                cloned = copy.deepcopy(orig_ent)
                cloned.id = str(uuid.uuid4())[:8]
                cloned.name = f"{orig_ent.name}_R{idx}"
                cloned.x = round(cloned.x + offset_x, 3)
                cloned.y = round(cloned.y + offset_y, 3)

                if isinstance(cloned, LineEntity):
                    cloned.x2 = round(cloned.x2 + offset_x, 3)
                    cloned.y2 = round(cloned.y2 + offset_y, 3)

                elif isinstance(cloned, TextEntity):
                    # Substitute dynamic variables
                    new_text = VariableTextEngine.substitute_variables(
                        cloned.text,
                        row.fields,
                        row_index=idx,
                        serial_start=serial_start,
                        serial_step=serial_step
                    )
                    cloned.text = new_text

                generated_entities.append(cloned)

            placed_count += 1

        telemetry = {
            "total_dataset_rows": len(dataset.rows),
            "placed_items": placed_count,
            "unplaced_items": total_items - placed_count,
            "columns": cols,
            "rows": (placed_count + cols - 1) // cols if cols else 1,
            "item_width_mm": round(t_width, 2),
            "item_height_mm": round(t_height, 2),
            "bed_fit": (placed_count == total_items)
        }

        return generated_entities, telemetry
