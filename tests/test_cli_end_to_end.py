"""End-to-end CLI tests covering demo, audit, lock, extract, and init-note."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from thesis_breaker.cli import main


class TestCliEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def _run_cli(self, args: list[str]) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(args)
        self.assertEqual(code, 0)
        return buf.getvalue()

    def test_demo_caveman_and_json(self) -> None:
        out = self._run_cli(["demo", "--format", "caveman"])
        self.assertIn("[持仓：MU", out)
        self.assertIn("[持仓：9988.HK", out)
        self.assertIn("[持仓：0700.HK", out)
        self.assertIn("[持仓：SMCI", out)

        json_out = self._run_cli(["demo", "--format", "json"])
        payload = json.loads(json_out)
        self.assertEqual(payload["summary"]["total_positions"], 4)
        self.assertIn("watch_warning", payload["summary"])
        self.assertEqual(payload["summary"]["untracked_naked"], 1)
        self.assertEqual(payload["summary"]["hold_conviction"], 1)

    def test_audit_markdown_format(self) -> None:
        out = self._run_cli(
            [
                "audit",
                "--ibkr",
                str(self.root / "examples" / "ibkr_flex_positions.csv"),
                "--notes",
                str(self.root / "examples" / "obsidian_vault"),
                "--earnings",
                str(self.root / "examples" / "earnings_q4_flash.md"),
                "--format",
                "markdown",
            ]
        )
        self.assertIn("# ThesisBreaker 持仓逻辑证伪与估值复盘报告", out)
        self.assertIn("KILL_SWITCH_TRIGGERED", out)

    def test_init_note_lock_and_extract_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            note_path = tmp_path / "NVDA.md"
            self._run_cli(
                [
                    "init-note",
                    "--symbol",
                    "NVDA",
                    "--name",
                    "NVIDIA",
                    "--model",
                    "FCFE",
                    "--output",
                    str(note_path),
                ]
            )
            self.assertTrue(note_path.exists())
            # User lowers template threshold from 10.0 to 5.0 BEFORE initial lock -> must NOT trigger Tolerance Creep
            edited = note_path.read_text(encoding="utf-8").replace("threshold: 10.0", "threshold: 5.0")
            note_path.write_text(edited, encoding="utf-8")
            lock_out = self._run_cli(["lock", "--notes", str(tmp_path)])
            self.assertIn("[LOCKED] NVDA", lock_out)

            # Second lock without --force is safely skipped
            skip_out = self._run_cli(["lock", "--notes", str(tmp_path)])
            self.assertIn("[SKIPPED] NVDA", skip_out)
            # Re-lock with --force succeeds
            force_out = self._run_cli(["lock", "--notes", str(tmp_path), "--force"])
            self.assertIn("[LOCKED] NVDA", force_out)

            # Test extract --write using copied vault
            vault_copy = tmp_path / "vault"
            shutil.copytree(self.root / "examples" / "obsidian_vault", vault_copy)
            extract_out = self._run_cli(
                [
                    "extract",
                    "--earnings",
                    str(self.root / "examples" / "earnings_q4_flash.md"),
                    "--notes",
                    str(vault_copy),
                    "--write",
                ]
            )
            data = json.loads(extract_out)
            self.assertIn("MU", data)


    def test_module_entrypoint_demo(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.root / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "thesis_breaker", "demo"],
            cwd=str(self.root),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("死线锁哈希不匹配", proc.stdout)
        self.assertIn("[HOLD_CONVICTION]", proc.stdout)

    def test_init_note_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            note_path = Path(tmp) / "NVDA.md"
            self._run_cli(
                [
                    "init-note",
                    "--symbol",
                    "NVDA",
                    "--name",
                    "NVIDIA",
                    "--output",
                    str(note_path),
                ]
            )
            custom_marker = "CUSTOM_REVIEW_DO_NOT_DELETE"
            note_path.write_text(
                note_path.read_text(encoding="utf-8") + f"\n{custom_marker}\n",
                encoding="utf-8",
            )
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                code = main(
                    [
                        "init-note",
                        "--symbol",
                        "NVDA",
                        "--output",
                        str(note_path),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("Refusing to overwrite", err_buf.getvalue())
            self.assertIn(custom_marker, note_path.read_text(encoding="utf-8"))

            self._run_cli(
                [
                    "init-note",
                    "--symbol",
                    "NVDA",
                    "--output",
                    str(note_path),
                    "--force",
                ]
            )
            self.assertNotIn(custom_marker, note_path.read_text(encoding="utf-8"))

    def test_bundled_demo_data_matches_examples_and_wheel_demo_runs_outside_repo(self) -> None:
        examples_dir = self.root / "examples"
        demo_data_dir = self.root / "src" / "thesis_breaker" / "demo_data"
        example_files = sorted(
            p.relative_to(examples_dir) for p in examples_dir.rglob("*") if p.is_file()
        )
        demo_files = sorted(
            p.relative_to(demo_data_dir) for p in demo_data_dir.rglob("*") if p.is_file()
        )
        self.assertEqual(example_files, demo_files)
        for rel in example_files:
            self.assertEqual(
                (examples_dir / rel).read_bytes(),
                (demo_data_dir / rel).read_bytes(),
                f"Mismatch between examples/{rel} and demo_data/{rel}",
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dist_dir = tmp_path / "dist"
            site_dir = tmp_path / "site"
            outside_dir = tmp_path / "outside"
            (outside_dir / "examples").mkdir(parents=True, exist_ok=True)

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(self.root),
                    "--no-deps",
                    "-w",
                    str(dist_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            wheels = list(dist_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0], "r") as zf:
                zf.extractall(site_dir)

            env = dict(os.environ)
            env["PYTHONPATH"] = str(site_dir)
            proc = subprocess.run(
                [sys.executable, "-m", "thesis_breaker", "demo"],
                cwd=str(outside_dir),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("[持仓：MU", proc.stdout)
            self.assertIn("[HOLD_CONVICTION]", proc.stdout)

    def test_init_note_normalizes_longbridge_and_futu_symbols(self) -> None:
        hk_note = self._run_cli(["init-note", "--symbol", "HK.00700", "--name", "Tencent"])
        self.assertIn("symbol: 0700.HK", hk_note)
        self.assertIn("currency: HKD", hk_note)

        us_note = self._run_cli(["init-note", "--symbol", "MU.US", "--name", "Micron"])
        self.assertIn("symbol: MU", us_note)
        self.assertIn("currency: USD", us_note)

    def test_audit_survives_messy_obsidian_vault_and_longbridge_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            vault = tmp_path / "my_obsidian"
            shutil.copytree(self.root / "examples" / "obsidian_vault", vault)
            (vault / ".trash").mkdir()
            (vault / ".trash" / "old_MU.md").write_text("---\nsymbol: MU\n\tbad: %\n---\n", encoding="utf-8")
            (vault / "broken_daily.md").write_text("---\nrate: %\n---\nDaily note.\n", encoding="utf-8")

            lb_csv = tmp_path / "longbridge.csv"
            lb_csv.write_text(
                "股票代码,股票名称,币种,持仓数量,成本价,现价\n"
                "MU.US,Micron,USD,300,118.0,98.6\n"
                "HK.00700,Tencent,港币,600,345.0,408.8\n"
                "合计,,,900,,\n",
                encoding="utf-8",
            )

            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                code = main(
                    [
                        "audit",
                        "--ibkr",
                        str(lb_csv),
                        "--notes",
                        str(vault),
                        "--earnings",
                        str(self.root / "examples" / "earnings_q4_flash.md"),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(out_buf.getvalue())
            self.assertEqual(payload["summary"]["total_positions"], 2)
            self.assertIn("broken_daily.md", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
