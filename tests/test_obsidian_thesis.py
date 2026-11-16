"""Tests for pure-Python YAML parser and Obsidian ThesisCard loader."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from thesis_breaker import cli
from thesis_breaker.parsers.obsidian_thesis import (
    load_thesis_cards,
    parse_thesis_card,
    update_thesis_card_frontmatter,
)
from thesis_breaker.parsers.simple_yaml import (
    _dump_yaml_builtin,
    _parse_yaml_builtin,
    dump_yaml,
    parse_yaml,
)


class TestObsidianThesisParser(unittest.TestCase):
    def test_simple_yaml_roundtrip(self) -> None:
        sample = """
symbol: "MU"
entry_price: 118.0
thesis_lock_sha256: null
kill_switches:
  - id: KS-1
    name: "Q4 HBM 良率"
    threshold: 75.0
    critical: true
    aliases: ["HBM yield", "良率"]
latest_actuals: {}
"""
        parsed = parse_yaml(sample)
        self.assertEqual(parsed["symbol"], "MU")
        self.assertEqual(parsed["entry_price"], 118.0)
        self.assertIsNone(parsed["thesis_lock_sha256"])
        self.assertEqual(parsed["kill_switches"][0]["aliases"], ["HBM yield", "良率"])
        self.assertTrue(parsed["kill_switches"][0]["critical"])
        dumped = dump_yaml(parsed)
        reparsed = parse_yaml(dumped)
        self.assertEqual(reparsed["kill_switches"][0]["id"], "KS-1")

    def test_load_example_vault(self) -> None:
        vault = Path(__file__).resolve().parents[1] / "examples" / "obsidian_vault"
        cards = load_thesis_cards(vault)
        self.assertEqual(set(cards.keys()), {"MU", "9988.HK", "0700.HK"})
        self.assertEqual(len(cards["MU"].kill_switches), 3)
        self.assertEqual(cards["0700.HK"].valuation.model_type, "FCFE")
        self.assertIn("超级周期", cards["MU"].latest_review_notes)

    def test_reject_under_three_kill_switches(self) -> None:
        note = """---
symbol: NVDA
name: NVIDIA
entry_price: 120.0
initial_strategy_type: cyclical_swing
kill_switches:
  - id: KS-1
    name: "Data Center YoY"
    metric_key: dc_yoy
    operator: ">="
    threshold: 30.0
valuation:
  model_type: SOTP
  currency: USD
  diluted_shares: 24.5
  segments:
    - name: DC
      metric_value: 100.0
      multiple: 25.0
---

## Core Thesis
Only 1 kill switch provided.
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "NVDA.md"
            p.write_text(note, encoding="utf-8")
            card = parse_thesis_card(p)
            self.assertIsNotNone(card)
            self.assertTrue(card.validation_errors)
            self.assertIn("3 条", card.validation_errors[0])

            update_thesis_card_frontmatter(
                p, lambda m: {**m, "thesis_lock_sha256": "abc123"}
            )
            reloaded = parse_thesis_card(p)
            self.assertEqual(reloaded.thesis_lock_sha256, "abc123")
            self.assertIn("Only 1 kill switch", reloaded.core_thesis_summary)

    def test_multiline_block_scalar_preserved_on_lock_and_extract_write(self) -> None:
        raw_yaml = """
symbol: "NVDA"
description: |
  Line 1: AI GPU cycle
  # Keep literal hash inside block scalar

  Line 3 with trailing paragraph
summary_folded: >-
  Folded line one
  line two
extra_flow: {owner: "desk", tier: 1}
entry_price: 120.0
"""
        parsed = _parse_yaml_builtin(raw_yaml)
        self.assertEqual(
            parsed["description"],
            "Line 1: AI GPU cycle\n# Keep literal hash inside block scalar\n\nLine 3 with trailing paragraph\n",
        )
        self.assertEqual(parsed["summary_folded"], "Folded line one line two")
        self.assertEqual(parsed["extra_flow"], {"owner": "desk", "tier": 1})
        self.assertEqual(parsed["entry_price"], 120.0)

        chomp_variants = _parse_yaml_builtin(
            "lit_strip: |-\n  a\n  b\nlit_keep: |+\n  a\n\nfold_clip: >\n  x\n  y\n"
        )
        self.assertEqual(chomp_variants["lit_strip"], "a\nb")
        self.assertEqual(chomp_variants["lit_keep"], "a\n\n")
        self.assertEqual(chomp_variants["fold_clip"], "x y\n")

        note = """---
symbol: "NVDA"
name: "NVIDIA"
entry_date: "2026-01-15"
entry_price: 120.0
initial_strategy_type: "cyclical_swing"
current_claimed_style: "cyclical_swing"
thesis_lock_sha256: null
description: |
  核心买入原因: Blackwell 放量
  # 注意不能被当成注释丢掉

  二级要点: 关注毛利率底线
custom_tag: "keep_after_description"
kill_switches:
  - id: KS-1
    name: "Data Center YoY"
    metric_key: dc_yoy_pct
    operator: ">="
    threshold: 30.0
    locked_threshold: null
    unit: "%"
    haircut_pct: 20.0
    critical: true
  - id: KS-2
    name: "Gross Margin"
    metric_key: gross_margin_pct
    operator: ">="
    threshold: 70.0
    locked_threshold: null
    unit: "%"
    haircut_pct: 15.0
    critical: false
  - id: KS-3
    name: "Capex Ceiling"
    metric_key: capex_b
    operator: "<="
    threshold: 5.0
    locked_threshold: null
    unit: "B"
    haircut_pct: 10.0
    critical: false
valuation:
  model_type: "SOTP"
  currency: "USD"
  diluted_shares: 24.5
  net_cash: 30.0
  required_mos_pct: 20.0
  segments:
    - name: "Data Center"
      metric_value: 100.0
      multiple: 25.0
      ownership_pct: 100.0
latest_actuals: {}
---

## Core Thesis
Blackwell thesis.
"""
        earnings = """## NVDA
- dc_yoy_pct: 42.0%
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            note_path = tmp_path / "NVDA.md"
            earnings_path = tmp_path / "earnings.md"
            note_path.write_text(note, encoding="utf-8")
            earnings_path.write_text(earnings, encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["lock", "--notes", str(note_path), "--force"]), 0)
                self.assertEqual(
                    cli.main(
                        [
                            "extract",
                            "--earnings",
                            str(earnings_path),
                            "--notes",
                            str(note_path),
                            "--write",
                        ]
                    ),
                    0,
                )

            from thesis_breaker.parsers.obsidian_thesis import split_frontmatter

            yaml_after, _ = split_frontmatter(note_path.read_text(encoding="utf-8"))
            meta_after = _parse_yaml_builtin(yaml_after or "")
            self.assertIn("Blackwell 放量", meta_after["description"])
            self.assertIn("# 注意不能被当成注释丢掉", meta_after["description"])
            self.assertEqual(meta_after["custom_tag"], "keep_after_description")
            self.assertEqual(meta_after["entry_price"], 120.0)
            self.assertEqual(len(meta_after["kill_switches"]), 3)
            self.assertEqual(meta_after["latest_actuals"]["dc_yoy_pct"], 42.0)
            self.assertTrue(meta_after["thesis_lock_sha256"])

    def test_invalid_yaml_fails_closed_without_data_loss(self) -> None:
        bad_samples = [
            "symbol: MU\n  unexpected_indent: 1\n",
            "symbol: MU\nnot_a_mapping_line\n",
            "operator: >=\n",
            "unit: %\n",
            "symbol: MU\n\tbad_tab: 1\n",
        ]
        for sample in bad_samples:
            with self.assertRaises(ValueError):
                _parse_yaml_builtin(sample)

        malformed_note = "---\nsymbol: MU\n  bad_indent: 1\n---\n\n## Core Thesis\nKeep me.\n"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "broken.md"
            p.write_text(malformed_note, encoding="utf-8")
            with self.assertRaises(ValueError):
                update_thesis_card_frontmatter(p, lambda m: {**m, "entry_price": 1.0})
            self.assertEqual(p.read_text(encoding="utf-8"), malformed_note)

    def test_builtin_dumper_quotes_yaml_indicators(self) -> None:
        payload = {
            "symbol": "0700.HK",
            "entry_date": "2025-11-04",
            "flag_word": "yes",
            "description": "Line 1\nLine 2\n",
            "kill_switches": [
                {"id": "KS-1", "operator": ">=", "unit": "%", "threshold": 8.0},
                {"id": "KS-2", "operator": "<=", "unit": "%", "threshold": -1.0},
            ],
        }
        dumped = _dump_yaml_builtin(payload)
        self.assertIn('">="', dumped)
        self.assertIn('"<="', dumped)
        self.assertIn('"%"', dumped)
        self.assertIn('"2025-11-04"', dumped)
        reparsed = _parse_yaml_builtin(dumped)
        self.assertEqual(reparsed, payload)
        try:
            import yaml  # type: ignore

            self.assertEqual(yaml.safe_load(dumped), payload)
        except ImportError:
            pass


if __name__ == "__main__":
    unittest.main()
