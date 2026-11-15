"""Tests for zero-API local earnings metric extractor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from thesis_breaker.parsers.earnings_extractor import (
    extract_earnings_metrics,
    parse_metric_number,
)
from thesis_breaker.parsers.obsidian_thesis import load_thesis_cards


class TestEarningsExtractor(unittest.TestCase):
    def test_parse_metric_number_units(self) -> None:
        self.assertEqual(parse_metric_number("62.0%"), 62.0)
        self.assertEqual(parse_metric_number("-4.5%"), -4.5)
        self.assertEqual(parse_metric_number("$11.5B"), 11.5)
        self.assertEqual(parse_metric_number("-180 bps", expected_unit="%"), -1.8)

    def test_extract_from_markdown_flash(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        extracted = extract_earnings_metrics(
            base / "earnings_q4_flash.md", cards.values()
        )
        self.assertEqual(extracted["MU"]["hbm_yield_pct"], 62.0)
        self.assertEqual(extracted["MU"]["dram_contract_qoq_pct"], -4.5)
        self.assertEqual(extracted["9988.HK"]["cloud_rev_yoy_pct"], 4.2)
        self.assertEqual(extracted["0700.HK"]["share_count_change_pct"], -2.4)

    def test_extract_from_csv_table(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        csv_text = (
            "Symbol,Metric Key,Actual\n"
            "MU,hbm_yield_pct,78.5%\n"
            "9988.HK,cloud_rev_yoy_pct,11.2%\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "q1.csv"
            p.write_text(csv_text, encoding="utf-8")
            extracted = extract_earnings_metrics(p, cards.values())
            self.assertEqual(extracted["MU"]["hbm_yield_pct"], 78.5)
            self.assertEqual(extracted["9988.HK"]["cloud_rev_yoy_pct"], 11.2)

    def test_extract_from_whitespace_aligned_pdf_paste(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        pdf_paste = (
            "## MU\n"
            "Q4 HBM3E 良率    62.0%    75.0%\n"
            "DRAM Contract QoQ\t-4.5%\t0.0%\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "pasted_pdf.md"
            p.write_text(pdf_paste, encoding="utf-8")
            extracted = extract_earnings_metrics(p, cards.values())
            self.assertEqual(extracted["MU"]["hbm_yield_pct"], 62.0)
            self.assertEqual(extracted["MU"]["dram_contract_qoq_pct"], -4.5)

    def test_short_generic_tokens_do_not_collide(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        noisy_report = (
            "## MU\n"
            "- Q4: 2026\n"
            "- YoY: 99.9%\n"
            "- Q4 HBM3E 良率: 64.5%\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "noisy.md"
            p.write_text(noisy_report, encoding="utf-8")
            extracted = extract_earnings_metrics(p, cards.values())
            self.assertEqual(extracted["MU"]["hbm_yield_pct"], 64.5)
            self.assertNotIn("dram_contract_qoq_pct", extracted["MU"])


if __name__ == "__main__":
    unittest.main()
