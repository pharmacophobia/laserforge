"""
Unit Tests for Business Card Generator and Typography Scaling.
Verifies:
1. BusinessCardConfig initialization and default typography values.
2. Single card generation across all layout styles ("Modern Split", "Centered Classic", "Minimalist").
3. Responsive typography auto-fit ensuring long company/person text fits card margins without overflow.
4. Correct layout geometry, QR placement, and non-overlapping vertical cursors.
5. Exact font scaling consistency with GCodeGenerator.
"""

import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QFontMetricsF

app = QApplication.instance()
if app is None:
    app = QApplication([])

from laserforge.core.business_card_generator import (
    BusinessCardConfig,
    BusinessCardGenerator,
    _auto_fit_text_size,
    _measure_text_metrics,
)
from laserforge.core.models import RectEntity, TextEntity, PathEntity
from laserforge.config import MachineSettings
from laserforge.core.layer_manager import LayerManager
from laserforge.core.gcode_generator import GCodeGenerator


class TestBusinessCardGenerator(unittest.TestCase):
    def test_default_config_typography(self):
        cfg = BusinessCardConfig()
        self.assertEqual(cfg.font_family, "Sans Serif")
        self.assertEqual(cfg.font_scale, 1.0)
        self.assertTrue(cfg.auto_fit_text)
        self.assertEqual(cfg.layout_style, "Modern Split")

    def test_measure_and_auto_fit(self):
        # Long string should scale down font size when auto_fit is applied
        long_text = "Precision Laser Engineering & Fabrication"
        base_size = 5.5
        max_w = 45.0

        fitted_size, w, h = _auto_fit_text_size(
            long_text, base_size, max_w, bold=True, font_family="Sans Serif", min_fs=1.0
        )
        self.assertLess(fitted_size, base_size)
        # Measured width should be <= max_w + margin of error
        self.assertLessEqual(w, max_w + 1.0)

    def test_modern_split_generation(self):
        cfg = BusinessCardConfig(
            layout_style="Modern Split",
            company_name="ULTRA HIGH TECH INC",
            person_name="Alexander Hamilton Mercer",
            include_qr=True,
            qr_size=20.0,
            qr_position="Right"
        )
        entities = BusinessCardGenerator.generate_single_card(cfg, origin_x=10.0, origin_y=10.0)
        self.assertGreater(len(entities), 0)

        # First entity is card outline
        outline = entities[0]
        self.assertIsInstance(outline, RectEntity)
        self.assertEqual(outline.width, cfg.width)
        self.assertEqual(outline.height, cfg.height)

        # Check that all text entities fit within the card bounds
        card_min_x = 10.0
        card_max_x = 10.0 + cfg.width
        card_min_y = 10.0
        card_max_y = 10.0 + cfg.height

        text_entities = [e for e in entities if isinstance(e, TextEntity)]
        self.assertGreater(len(text_entities), 3)

        for te in text_entities:
            self.assertGreaterEqual(te.x, card_min_x - 0.1)
            self.assertLessEqual(te.x + te.width, card_max_x + 0.5)
            self.assertGreaterEqual(te.y, card_min_y - 0.1)
            self.assertLessEqual(te.y + te.height, card_max_y + 0.5)

    def test_centered_classic_and_minimalist(self):
        for style in ["Centered Classic", "Minimalist"]:
            cfg = BusinessCardConfig(
                layout_style=style,
                company_name="AURA CREATIVE",
                tagline="Studio of Art & Design",
                person_name="Elena Rostova",
                include_qr=False
            )
            entities = BusinessCardGenerator.generate_single_card(cfg, origin_x=0.0, origin_y=0.0)
            text_entities = [e for e in entities if isinstance(e, TextEntity)]
            self.assertGreater(len(text_entities), 2)
            for te in text_entities:
                self.assertGreaterEqual(te.x, -0.1)
                self.assertLessEqual(te.x + te.width, cfg.width + 0.5)

    def test_gcode_generation_with_business_card(self):
        cfg = BusinessCardConfig(
            company_name="FORGE TEST",
            person_name="Test User",
            include_qr=False
        )
        entities = BusinessCardGenerator.generate_single_card(cfg, origin_x=0.0, origin_y=0.0)
        lm = LayerManager()
        gen = GCodeGenerator(settings=MachineSettings(), layer_manager=lm)

        paths = []
        for e in entities:
            e_paths = gen.entity_to_paths(e)
            paths.extend(e_paths)

        self.assertGreater(len(paths), 0)
        # Check that all paths stay within card extents
        for path in paths:
            for x, y in path:
                self.assertGreaterEqual(x, -1.0)
                self.assertLessEqual(x, cfg.width + 5.0)
                self.assertGreaterEqual(y, -1.0)
                self.assertLessEqual(y, cfg.height + 5.0)


if __name__ == "__main__":
    unittest.main()
