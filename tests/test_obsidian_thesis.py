"""Tests for pure-Python YAML parser and Obsidian ThesisCard loader."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis_breaker import cli
from thesis_breaker.parsers.obsidian_thesis import (
    load_thesis_cards,
    parse_thesis_card,
    split_frontmatter,
    update_thesis_card_frontmatter,
)
from thesis_breaker.parsers.simple_yaml import (
    _dump_yaml_builtin,
    _parse_yaml_builtin,
    dump_yaml,
    parse_yaml,
)


class TestObsidianThesisParser(unittest.TestCase):
    def test_multiline_markers_and_tabs_survive_cli_writes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "examples/obsidian_vault/MU_Micron_SOTP.md").read_text(encoding="utf-8")
        _, original_body = split_frontmatter(source)
        for description in ("line1\n---\nline3\n", "line1\n\tline2\n"):
            with self.subTest(description=description), tempfile.TemporaryDirectory() as tmp:
                note_path = Path(tmp) / "MU.md"
                fields = (
                    f"custom_description: {json.dumps(description)}\n"
                    "custom_property: preserve-me\n"
                )
                note_path.write_text(source.replace("kill_switches:\n", fields + "kill_switches:\n", 1), encoding="utf-8")
                for args in (
                    ["lock", "--notes", str(note_path), "--force"],
                    ["extract", "--notes", str(note_path), "--earnings", str(root / "examples/earnings_q4_flash.md"), "--write"],
                ):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(cli.main(args), 0)
                    yaml_after, body_after = split_frontmatter(note_path.read_text(encoding="utf-8"))
                    meta = parse_yaml(yaml_after)
                    self.assertEqual(meta["custom_description"], description)
                    self.assertEqual(meta["custom_property"], "preserve-me")
                    self.assertEqual(len(meta["kill_switches"]), 3)
                    self.assertIsNotNone(parse_thesis_card(note_path))
                    self.assertEqual(body_after.lstrip("\r\n"), original_body.lstrip("\r\n"))

    def test_builtin_block_scalar_tabs_are_content_after_indentation(self) -> None:
        for value in ("line1\n\tline2\n", "\tline1\nline2\n"):
            payload = {"description": value}
            self.assertEqual(_parse_yaml_builtin(_dump_yaml_builtin(payload)), payload)
        parsed = _parse_yaml_builtin("description: |\n  \tline1\n  line2\n")
        self.assertEqual(parsed["description"], "\tline1\nline2\n")

    def test_lossy_serialization_is_rejected_before_writing(self) -> None:
        source = "---\nsymbol: MU\ncustom_property: preserve-me\n---\n\nKeep body.\n"
        with tempfile.TemporaryDirectory() as tmp:
            note_path = Path(tmp) / "MU.md"
            note_path.write_text(source, encoding="utf-8")
            with patch("thesis_breaker.parsers.obsidian_thesis.dump_yaml", return_value="symbol: MU"):
                with self.assertRaisesRegex(ValueError, "refusing to write"):
                    update_thesis_card_frontmatter(note_path, lambda meta: meta)
            self.assertEqual(note_path.read_text(encoding="utf-8"), source)

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

    def test_real_vault_skips_hidden_dirs_and_invalid_notes_with_warnings(self) -> None:
        root = Path(__file__).resolve().parents[1]
        mu_source = (root / "examples/obsidian_vault/MU_Micron_SOTP.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            # Put the vault itself under a dot-prefixed parent to verify only relative hidden paths are skipped.
            vault = Path(tmp) / ".hidden_parent" / "vault"
            vault.mkdir(parents=True)
            (vault / "MU.md").write_text(mu_source, encoding="utf-8")

            # Stale trashed copy with altered entry_price must NOT override the active card.
            trash_dir = vault / ".trash"
            trash_dir.mkdir()
            (trash_dir / "z_MU_deleted.md").write_text(
                mu_source.replace("entry_price: 118.0", "entry_price: 999.0"),
                encoding="utf-8",
            )

            # .obsidian config markdown and hidden dotfile must be ignored without warnings.
            obsidian_dir = vault / ".obsidian"
            obsidian_dir.mkdir()
            (obsidian_dir / "broken_plugin_doc.md").write_text(
                "---\nbad_tab:\n\tvalue: %\n---\n", encoding="utf-8"
            )
            (vault / ".secret_draft.md").write_text(
                "---\nbad_tab:\n\tvalue: %\n---\n", encoding="utf-8"
            )

            # Regular non-thesis daily note should be silently ignored.
            (vault / "2026-11-20_daily.md").write_text(
                "---\ntags: [daily, journal]\n---\n\nMarket felt noisy today.\n",
                encoding="utf-8",
            )

            # Broken non-thesis template (e.g. Obsidian Templater / unquoted %) warns and is skipped.
            broken_template = vault / "Templates_bad.md"
            broken_template.write_text(
                "---\ntitle: {{date}}\nrate: %\n---\n\nTemplate body.\n",
                encoding="utf-8",
            )

            # Non-UTF-8 file warns and is skipped rather than crashing the scan.
            (vault / "binary_clip.md").write_bytes(b"\xff\xfe---\nsymbol: BAD\n---\n")

            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                cards = load_thesis_cards(vault)

            self.assertEqual(set(cards.keys()), {"MU"})
            self.assertEqual(cards["MU"].entry_price, 118.0)
            warnings = err_buf.getvalue()
            self.assertIn("Templates_bad.md", warnings)
            self.assertIn("binary_clip.md", warnings)
            self.assertNotIn("broken_plugin_doc.md", warnings)
            self.assertNotIn(".secret_draft.md", warnings)

            # Explicit single-file load must remain fail-closed.
            with self.assertRaises(ValueError):
                load_thesis_cards(broken_template)

    def test_duplicate_symbol_emits_warning_and_null_optional_numbers_parse(self) -> None:
        note_template = """---
symbol: NVDA
name: NVIDIA
entry_price: null
initial_strategy_type: cyclical_swing
kill_switches:
  - id: KS-1
    name: "DC YoY"
    metric_key: dc_yoy
    operator: ">="
    threshold: 30.0
    locked_threshold: null
    haircut_pct: null
  - id: KS-2
    name: "GM"
    metric_key: gm
    operator: ">="
    threshold: 70.0
  - id: KS-3
    name: "Capex"
    metric_key: capex
    operator: "<="
    threshold: 5.0
valuation:
  model_type: SOTP
  currency: USD
  diluted_shares: 24.5
  net_cash: null
  segments:
    - name: DC
      metric_value: 100.0
      multiple: 25.0
      ownership_pct: null
---
"""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "a_NVDA.md").write_text(note_template, encoding="utf-8")
            (vault / "b_NVDA_copy.md").write_text(note_template, encoding="utf-8")

            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                cards = load_thesis_cards(vault)

            self.assertIn("NVDA", cards)
            self.assertEqual(cards["NVDA"].entry_price, 0.0)
            self.assertEqual(cards["NVDA"].valuation.net_cash, 0.0)
            self.assertEqual(cards["NVDA"].valuation.segments[0].ownership_pct, 100.0)
            self.assertIn("duplicate ThesisCard for NVDA", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
