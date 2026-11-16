"""Command-line interface for ThesisBreaker."""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from thesis_breaker import __version__
from thesis_breaker.engine.auditor import audit_portfolio
from thesis_breaker.engine.thesis_lock import compute_thesis_lock_hash
from thesis_breaker.formatters.caveman import (
    format_caveman_report,
    format_json_report,
    format_markdown_report,
)
from thesis_breaker.models import PositionAuditReport
from thesis_breaker.parsers.broker_csv import normalize_symbol, parse_broker_csv
from thesis_breaker.parsers.earnings_extractor import extract_earnings_metrics
from thesis_breaker.parsers.obsidian_thesis import (
    load_thesis_cards,
    update_thesis_card_frontmatter,
)


def _is_valid_examples_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "ibkr_flex_positions.csv").is_file()
        and (path / "earnings_q4_flash.md").is_file()
        and (path / "obsidian_vault").is_dir()
    )


def _resolve_examples_dir() -> Path:
    """Locate bundled demo_data or repository examples directory."""
    candidates = [
        Path(__file__).resolve().parent / "demo_data",
        Path(__file__).resolve().parents[2] / "examples",
        Path.cwd() / "examples",
    ]
    for cand in candidates:
        if _is_valid_examples_dir(cand):
            return cand
    raise FileNotFoundError("Could not locate bundled demo_data/ or examples/ directory.")


def _render_output(reports: List[PositionAuditReport], fmt: str) -> str:
    if fmt == "json":
        return format_json_report(reports)
    if fmt == "markdown":
        return format_markdown_report(reports)
    return format_caveman_report(reports)


def _cmd_audit(args: argparse.Namespace) -> int:
    positions = parse_broker_csv(args.ibkr)
    cards = load_thesis_cards(args.notes)
    extracted: Optional[Dict[str, Dict[str, float]]] = None
    if args.earnings:
        extracted = extract_earnings_metrics(args.earnings, cards.values())

    reports = audit_portfolio(positions, cards, extracted_actuals=extracted)
    output = _render_output(reports, args.format)
    print(output)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    ex_dir = _resolve_examples_dir()
    ibkr_csv = ex_dir / "ibkr_flex_positions.csv"
    vault_dir = ex_dir / "obsidian_vault"
    earnings_md = ex_dir / "earnings_q4_flash.md"

    positions = parse_broker_csv(ibkr_csv)
    cards = load_thesis_cards(vault_dir)
    extracted = extract_earnings_metrics(earnings_md, cards.values())
    reports = audit_portfolio(positions, cards, extracted_actuals=extracted)
    print(_render_output(reports, args.format))
    return 0


def _cmd_lock(args: argparse.Namespace) -> int:
    cards = load_thesis_cards(args.notes)
    if not cards:
        print(f"No valid ThesisCards found under {args.notes}", file=sys.stderr)
        return 1

    for symbol, card in cards.items():
        if card.thesis_lock_sha256 and not args.force:
            print(
                f"[SKIPPED] {symbol}: already locked ({card.thesis_lock_sha256[:16]}...). "
                "Pass --force to re-baseline."
            )
            continue

        lock_hash = compute_thesis_lock_hash(card, use_locked_thresholds=False)
        if args.dry_run:
            print(f"[DRY-RUN] {symbol}: thesis_lock_sha256={lock_hash}")
            continue

        def _apply_lock(meta: Dict[str, Any], h: str = lock_hash) -> Dict[str, Any]:
            meta["thesis_lock_sha256"] = h
            for ks in meta.get("kill_switches", []) or []:
                if isinstance(ks, dict):
                    ks["locked_threshold"] = ks.get("threshold")
            return meta

        update_thesis_card_frontmatter(card.source_path, _apply_lock)
        print(f"[LOCKED] {symbol} ({card.source_path}) -> {lock_hash[:16]}...")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    cards = load_thesis_cards(args.notes)
    extracted = extract_earnings_metrics(args.earnings, cards.values())
    if args.write:
        for sym, metrics in extracted.items():
            card = cards.get(sym)
            if card is None:
                continue

            def _apply_actuals(
                meta: Dict[str, Any], new_vals: Dict[str, float] = metrics
            ) -> Dict[str, Any]:
                actuals = dict(meta.get("latest_actuals") or {})
                actuals.update(new_vals)
                meta["latest_actuals"] = actuals
                return meta

            update_thesis_card_frontmatter(card.source_path, _apply_actuals)
    print(json.dumps(extracted, indent=2, ensure_ascii=False))
    return 0


def _build_note_template(
    symbol: str, name: str, model: str, strategy: str, currency: str
) -> str:
    if model == "FCFE":
        valuation_block = (
            f"valuation:\n"
            f"  model_type: FCFE\n"
            f"  currency: {currency}\n"
            f"  diluted_shares: 1.0\n"
            f"  net_cash: 0.0\n"
            f"  required_mos_pct: 20.0\n"
            f"  base_fcfe_per_share: 10.0\n"
            f"  growth_rate_pct: 12.0\n"
            f"  terminal_growth_pct: 2.5\n"
            f"  cost_of_equity_pct: 10.0\n"
            f"  projection_years: 5"
        )
    else:
        valuation_block = (
            f"valuation:\n"
            f"  model_type: SOTP\n"
            f"  currency: {currency}\n"
            f"  diluted_shares: 1.0\n"
            f"  net_cash: 0.0\n"
            f"  required_mos_pct: 25.0\n"
            f"  segments:\n"
            f"    - name: Core Segment\n"
            f"      metric_value: 10.0\n"
            f"      multiple: 12.0\n"
            f"      ownership_pct: 100.0"
        )

    today_str = date.today().isoformat()
    return f"""---
symbol: {symbol}
name: "{name}"
entry_date: "{today_str}"
entry_price: 100.0
initial_strategy_type: {strategy}
current_claimed_style: {strategy}
thesis_lock_sha256: null
kill_switches:
  - id: KS-1
    name: "核心假设 1（例如：产品良率或核心增速）"
    metric_key: core_metric_1
    operator: ">="
    threshold: 10.0
    locked_threshold: null
    unit: "%"
    haircut_pct: 20.0
    critical: true
  - id: KS-2
    name: "核心假设 2（例如：毛利率或价格周期）"
    metric_key: core_metric_2
    operator: ">="
    threshold: 30.0
    locked_threshold: null
    unit: "%"
    haircut_pct: 15.0
    critical: false
  - id: KS-3
    name: "核心假设 3（例如：资本开支或净现金底线）"
    metric_key: core_metric_3
    operator: "<="
    threshold: 5.0
    locked_threshold: null
    unit: "B"
    haircut_pct: 10.0
    critical: false
{valuation_block}
latest_actuals: {{}}
---

## Core Thesis
写下当初买入 {symbol} 的可证伪逻辑，严禁空泛宏大叙事。

## Review Notes
记录最新财报与行业数据对比，严禁事后将波段/周期逻辑偷偷改口为长期价值投资。
"""


def _cmd_init_note(args: argparse.Namespace) -> int:
    currency = "HKD" if args.symbol.upper().endswith(".HK") else "USD"
    sym = normalize_symbol(args.symbol, currency=currency)
    template = _build_note_template(
        symbol=sym,
        name=args.name or sym,
        model=args.model.upper(),
        strategy=args.strategy,
        currency=currency,
    )
    if args.output:
        out_path = Path(args.output)
        force = bool(getattr(args, "force", False))
        if out_path.exists() and not force:
            raise FileExistsError(
                f"Refusing to overwrite existing ThesisCard: {out_path} (pass --force to overwrite)."
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if force else "x"
        with out_path.open(mode, encoding="utf-8") as handle:
            handle.write(template)
        print(f"Created ThesisCard template: {out_path}")
    else:
        print(template)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thesis-breaker",
        description="Zero-API-cost local position postmortem & valuation discipline officer.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Audit broker positions against Obsidian thesis cards.")
    p_audit.add_argument("--ibkr", required=True, help="Path to IBKR/Longbridge CSV file.")
    p_audit.add_argument("--notes", required=True, help="Path to Obsidian thesis vault folder or file.")
    p_audit.add_argument("--earnings", default=None, help="Optional local Markdown/CSV earnings dump.")
    p_audit.add_argument(
        "--format",
        choices=["caveman", "markdown", "json"],
        default="caveman",
        help="Output format (default: caveman).",
    )
    p_audit.set_defaults(func=_cmd_audit)

    p_demo = sub.add_parser("demo", help="Run built-in US/HK portfolio postmortem demonstration.")
    p_demo.add_argument(
        "--format",
        choices=["caveman", "markdown", "json"],
        default="caveman",
        help="Output format (default: caveman).",
    )
    p_demo.set_defaults(func=_cmd_demo)

    p_lock = sub.add_parser("lock", help="Compute and stamp SHA-256 thesis locks onto Obsidian cards.")
    p_lock.add_argument("--notes", required=True, help="Path to Obsidian thesis vault folder or file.")
    p_lock.add_argument("--dry-run", action="store_true", help="Print lock hashes without editing files.")
    p_lock.add_argument("--force", action="store_true", help="Re-baseline an already locked card.")
    p_lock.set_defaults(func=_cmd_lock)

    p_extract = sub.add_parser("extract", help="Extract kill-switch metrics from a local earnings report.")
    p_extract.add_argument("--earnings", required=True, help="Path to local earnings Markdown or CSV.")
    p_extract.add_argument("--notes", required=True, help="Path to Obsidian thesis vault folder or file.")
    p_extract.add_argument("--write", action="store_true", help="Write extracted actuals into YAML frontmatter.")
    p_extract.set_defaults(func=_cmd_extract)

    p_init = sub.add_parser("init-note", help="Generate a new Obsidian ThesisCard template with 3 kill-switches.")
    p_init.add_argument("--symbol", required=True, help="Ticker symbol (e.g. MU, 9988.HK, 0700.HK).")
    p_init.add_argument("--name", default="", help="Company name.")
    p_init.add_argument("--model", choices=["SOTP", "FCFE"], default="SOTP", help="Valuation model.")
    p_init.add_argument("--strategy", default="cyclical_swing", help="Initial strategy type.")
    p_init.add_argument("--output", default=None, help="Output Markdown path (prints to stdout if omitted).")
    p_init.add_argument("--force", action="store_true", help="Overwrite output file if it already exists.")
    p_init.set_defaults(func=_cmd_init_note)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
