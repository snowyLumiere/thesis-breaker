"""Tests for zero-API local earnings metric extractor."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from thesis_breaker import cli
from thesis_breaker.engine.auditor import evaluate_kill_switch
from thesis_breaker.parsers.earnings_extractor import (
    extract_earnings_metrics,
    parse_metric_number,
)
from thesis_breaker.parsers.obsidian_thesis import load_thesis_cards, parse_thesis_card


class TestEarningsExtractor(unittest.TestCase):
    def test_chinese_currency_units_and_invalid_numeric_suffixes(self) -> None:
        for raw, unit, expected in (
            ("5000万元", "B", 0.05),
            ("5000万元", "亿元", 0.5),
            ("5亿元", "B", 0.5),
            ("1.2B元", "B", 1.2),
            ("180bps同比", "%", 1.8),
            ("500MB", "B", None),
            ("62.5percent", "%", None),
            ("1,23M", "B", None),
            ("1 000M", "B", None),
            ("1.2.3B", "B", None),
        ):
            with self.subTest(raw=raw, unit=unit):
                self.assertEqual(parse_metric_number(raw, unit), expected)

    def test_chinese_amount_does_not_hide_critical_breach(self) -> None:
        root = Path(__file__).resolve().parents[1]
        card = load_thesis_cards(root / "examples/obsidian_vault")["MU"]
        switch = card.kill_switches[0]
        switch.metric_key = "revenue_b"
        switch.unit = "B"
        switch.threshold = switch.locked_threshold = 1.0
        with tempfile.TemporaryDirectory() as tmp:
            flash = Path(tmp) / "flash.md"
            flash.write_text("## MU\n- revenue_b: 5000万元\n", encoding="utf-8")
            actuals = extract_earnings_metrics(flash, [card])["MU"]
        self.assertEqual(actuals["revenue_b"], 0.05)
        result = evaluate_kill_switch(switch, actuals)
        self.assertTrue(result.breached)
        self.assertTrue(result.kill_switch.critical)

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

    def test_parse_metric_number_cross_magnitude_units(self) -> None:
        self.assertEqual(parse_metric_number("$500M", expected_unit="B"), 0.5)
        self.assertEqual(parse_metric_number("$1.2T", expected_unit="B"), 1200.0)
        self.assertEqual(parse_metric_number("$2.5B", expected_unit="M"), 2500.0)
        self.assertEqual(parse_metric_number("5000万", expected_unit="亿"), 0.5)
        self.assertIsNone(parse_metric_number("62%", expected_unit="B"))
        self.assertIsNone(parse_metric_number("$500M", expected_unit="%"))

        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        # Also test extract --write on a card with unit "B" kill-switch + SOTP hbm_rev_b
        note_text = """---
symbol: "MU"
name: "Micron"
entry_date: "2026-06-12"
entry_price: 118.0
initial_strategy_type: "cyclical_swing"
kill_switches:
  - id: KS-1
    name: "HBM Revenue"
    metric_key: hbm_rev_b
    operator: ">="
    threshold: 1.0
    unit: "B"
    haircut_pct: 20.0
    critical: true
  - id: KS-2
    name: "Yield"
    metric_key: hbm_yield_pct
    operator: ">="
    threshold: 75.0
    unit: "%"
    haircut_pct: 15.0
  - id: KS-3
    name: "Gross Margin"
    metric_key: gross_margin_pct
    operator: ">="
    threshold: 38.0
    unit: "%"
    haircut_pct: 10.0
valuation:
  model_type: "SOTP"
  currency: "USD"
  diluted_shares: 1.12
  segments:
    - name: "HBM"
      metric_value: 14.0
      multiple: 7.5
      metric_key: hbm_rev_b
latest_actuals: {}
---
"""
        flash = "## MU\n- hbm_rev_b: $500M\n"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            note_path = tmp_path / "MU.md"
            flash_path = tmp_path / "flash.md"
            note_path.write_text(note_text, encoding="utf-8")
            flash_path.write_text(flash, encoding="utf-8")
            extracted = extract_earnings_metrics(flash_path, cards.values())
            # MU card in examples has SOTP segment metric_key hbm_rev_b -> infers unit "B"
            extracted_custom = extract_earnings_metrics(flash_path, [parse_thesis_card(note_path)])
            self.assertEqual(extracted_custom["MU"]["hbm_rev_b"], 0.5)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli.main(
                        [
                            "extract",
                            "--earnings",
                            str(flash_path),
                            "--notes",
                            str(note_path),
                            "--write",
                        ]
                    ),
                    0,
                )
            reloaded = parse_thesis_card(note_path)
            self.assertEqual(reloaded.latest_actuals["hbm_rev_b"], 0.5)
            self.assertIsNotNone(extracted)

    def test_explicit_symbol_table_not_overwritten_by_prose(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        mixed_report = (
            "## Summary\n"
            "| Symbol | Metric Key | Actual |\n"
            "| --- | --- | ---: |\n"
            "| MU | hbm_yield_pct | 62% |\n\n"
            "## MU\n"
            "- hbm_yield_pct: 78%\n"
            "- Q4 HBM3E 良率: 78%\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "mixed.md"
            p.write_text(mixed_report, encoding="utf-8")
            extracted = extract_earnings_metrics(p, cards.values())
            self.assertEqual(extracted["MU"]["hbm_yield_pct"], 62.0)

    def test_extract_handles_longbridge_and_futu_section_headings(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        cards = load_thesis_cards(base / "obsidian_vault")
        brk_card_text = (
            (base / "obsidian_vault" / "MU_Micron_SOTP.md")
            .read_text(encoding="utf-8")
            .replace("symbol: MU", 'symbol: "BRK.B"')
            .replace("hbm_yield_pct", "float_growth_pct")
        )
        report = (
            "## MU.US Micron\n"
            "- hbm_yield_pct: 61.5%\n\n"
            "## HK.00700 Tencent\n"
            "- game_rev_yoy_pct: 14.0%\n\n"
            "## BRK.B Berkshire Hathaway\n"
            "- float_growth_pct: 8.5%\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            brk_path = Path(tmp) / "BRK_B.md"
            brk_path.write_text(brk_card_text, encoding="utf-8")
            brk_card = parse_thesis_card(brk_path)
            p = Path(tmp) / "broker_headings.md"
            p.write_text(report, encoding="utf-8")
            extracted = extract_earnings_metrics(p, [*cards.values(), brk_card])
            self.assertEqual(extracted["MU"]["hbm_yield_pct"], 61.5)
            self.assertEqual(extracted["0700.HK"]["game_rev_yoy_pct"], 14.0)
            self.assertEqual(extracted["BRK.B"]["float_growth_pct"], 8.5)


if __name__ == "__main__":
    unittest.main()
