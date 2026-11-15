"""Tests for pure-Python YAML parser and Obsidian ThesisCard loader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from thesis_breaker.parsers.obsidian_thesis import (
    load_thesis_cards,
    parse_thesis_card,
    update_thesis_card_frontmatter,
)
from thesis_breaker.parsers.simple_yaml import dump_yaml, parse_yaml


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


if __name__ == "__main__":
    unittest.main()
