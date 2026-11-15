"""Obsidian Markdown + YAML frontmatter parser and updater for ThesisCard notes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from thesis_breaker.models import KillSwitch, SOTPSegment, ThesisCard, ValuationConfig
from thesis_breaker.parsers.broker_csv import normalize_symbol
from thesis_breaker.parsers.simple_yaml import dump_yaml, parse_yaml

MIN_KILL_SWITCHES = 3

_CORE_THESIS_HEADINGS = ("core thesis", "核心买入逻辑", "买入逻辑", "investment thesis")
_REVIEW_NOTES_HEADINGS = (
    "review notes",
    "latest review notes",
    "最新复盘笔记",
    "复盘笔记",
    "weekly review",
)


def split_frontmatter(text: str) -> Tuple[Optional[str], str]:
    """Split a Markdown note into (raw_yaml_frontmatter, markdown_body)."""
    normalized = text.lstrip("\ufeff")
    if not normalized.startswith("---"):
        return None, text
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            yaml_block = "".join(lines[1:idx])
            body = "".join(lines[idx + 1 :])
            return yaml_block, body
    return None, text


def _extract_markdown_sections(body: str) -> Dict[str, str]:
    """Extract level-2 (##) and level-3 (###) Markdown sections by lowercase title."""
    sections: Dict[str, str] = {}
    current_heading: Optional[str] = None
    buf: List[str] = []

    for line in body.splitlines():
        match = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if match:
            if current_heading is not None:
                sections[current_heading] = "\n".join(buf).strip()
            current_heading = match.group(1).strip().lower()
            buf = []
        else:
            if current_heading is not None:
                buf.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(buf).strip()
    return sections


def _pick_section(sections: Dict[str, str], candidates: Tuple[str, ...]) -> str:
    for heading, content in sections.items():
        for cand in candidates:
            if cand in heading:
                return content
    return ""


def _build_kill_switches(raw_list: Any) -> List[KillSwitch]:
    if not isinstance(raw_list, list):
        return []
    result: List[KillSwitch] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        locked = item.get("locked_threshold")
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = [str(aliases)]
        result.append(
            KillSwitch(
                id=str(item.get("id") or f"KS-{idx}"),
                name=str(item.get("name") or item.get("metric_key") or f"Kill-Switch {idx}"),
                metric_key=str(item.get("metric_key") or ""),
                operator=str(item.get("operator") or ">="),
                threshold=float(item.get("threshold", 0.0)),
                unit=str(item.get("unit") or ""),
                haircut_pct=float(item.get("haircut_pct", 0.0)),
                locked_threshold=float(locked) if locked is not None else None,
                critical=bool(item.get("critical", False)),
                aliases=[str(a) for a in aliases],
            )
        )
    return result


def _build_valuation(raw_val: Any, default_currency: str) -> Optional[ValuationConfig]:
    if not isinstance(raw_val, dict) or not raw_val:
        return None
    model_type = str(raw_val.get("model_type") or "SOTP").upper()
    segments: List[SOTPSegment] = []
    raw_segments = raw_val.get("segments") or []
    if isinstance(raw_segments, list):
        for seg in raw_segments:
            if not isinstance(seg, dict):
                continue
            segments.append(
                SOTPSegment(
                    name=str(seg.get("name") or "Segment"),
                    metric_value=float(seg.get("metric_value", 0.0)),
                    multiple=float(seg.get("multiple", 1.0)),
                    ownership_pct=float(seg.get("ownership_pct", 100.0)),
                    metric_key=(
                        str(seg["metric_key"]) if seg.get("metric_key") is not None else None
                    ),
                    multiple_key=(
                        str(seg["multiple_key"]) if seg.get("multiple_key") is not None else None
                    ),
                )
            )
    return ValuationConfig(
        model_type=model_type,
        currency=str(raw_val.get("currency") or default_currency).upper(),
        diluted_shares=float(raw_val.get("diluted_shares", 1.0)),
        net_cash=float(raw_val.get("net_cash", 0.0)),
        required_mos_pct=float(raw_val.get("required_mos_pct", 20.0)),
        segments=segments,
        base_fcfe_per_share=float(raw_val.get("base_fcfe_per_share", 0.0)),
        growth_rate_pct=float(raw_val.get("growth_rate_pct", 0.0)),
        terminal_growth_pct=float(raw_val.get("terminal_growth_pct", 2.5)),
        cost_of_equity_pct=float(raw_val.get("cost_of_equity_pct", 10.0)),
        projection_years=int(raw_val.get("projection_years", 5)),
    )


def parse_thesis_card(md_path: Union[str, Path]) -> Optional[ThesisCard]:
    """Parse an Obsidian Markdown note into a ThesisCard. Returns None if not a thesis note."""
    path = Path(md_path)
    raw_text = path.read_text(encoding="utf-8")
    yaml_str, body = split_frontmatter(raw_text)
    if yaml_str is None:
        return None

    meta = parse_yaml(yaml_str)
    if not isinstance(meta, dict) or not meta.get("symbol"):
        return None
    if "kill_switches" not in meta and "valuation" not in meta:
        return None

    raw_symbol = str(meta["symbol"])
    val_cfg = _build_valuation(meta.get("valuation"), default_currency=str(meta.get("currency", "USD")))
    inferred_currency = val_cfg.currency if val_cfg else str(meta.get("currency", "USD"))
    symbol = normalize_symbol(raw_symbol, currency=inferred_currency)

    aliases_raw = meta.get("symbol_aliases") or []
    aliases = [normalize_symbol(str(a), currency=inferred_currency) for a in aliases_raw]
    if raw_symbol.upper() != symbol:
        aliases.append(raw_symbol.upper())

    kill_switches = _build_kill_switches(meta.get("kill_switches"))
    validation_errors: List[str] = []
    if len(kill_switches) < MIN_KILL_SWITCHES:
        validation_errors.append(
            f"仅记录了 {len(kill_switches)} 条可证伪死线（强制要求至少 {MIN_KILL_SWITCHES} 条）"
        )
    if val_cfg is None:
        validation_errors.append("缺少确定性估值模型配置 (valuation: SOTP/FCFE)")

    raw_actuals = meta.get("latest_actuals") or {}
    latest_actuals: Dict[str, float] = {}
    if isinstance(raw_actuals, dict):
        for k, v in raw_actuals.items():
            if v is not None:
                try:
                    latest_actuals[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass

    sections = _extract_markdown_sections(body)
    core_summary = str(meta.get("core_thesis_summary") or _pick_section(sections, _CORE_THESIS_HEADINGS))
    review_notes = str(
        meta.get("latest_review_notes") or _pick_section(sections, _REVIEW_NOTES_HEADINGS)
    )

    initial_strategy = str(meta.get("initial_strategy_type") or "unspecified")
    current_style = str(meta.get("current_claimed_style") or initial_strategy)

    return ThesisCard(
        symbol=symbol,
        name=str(meta.get("name") or symbol),
        entry_date=str(meta.get("entry_date") or ""),
        entry_price=float(meta.get("entry_price", 0.0)),
        initial_strategy_type=initial_strategy,
        current_claimed_style=current_style,
        core_thesis_summary=core_summary.strip(),
        kill_switches=kill_switches,
        valuation=val_cfg,
        latest_actuals=latest_actuals,
        latest_review_notes=review_notes.strip(),
        thesis_lock_sha256=(
            str(meta["thesis_lock_sha256"]) if meta.get("thesis_lock_sha256") else None
        ),
        source_path=str(path),
        symbol_aliases=list(dict.fromkeys(aliases)),
        validation_errors=validation_errors,
    )


def load_thesis_cards(notes_path: Union[str, Path]) -> Dict[str, ThesisCard]:
    """Load all ThesisCards from a file or directory, keyed by canonical ticker symbol."""
    root = Path(notes_path)
    cards: Dict[str, ThesisCard] = {}
    paths = [root] if root.is_file() else sorted(root.rglob("*.md"))
    for md_file in paths:
        card = parse_thesis_card(md_file)
        if card is not None:
            cards[card.symbol] = card
    return cards


def update_thesis_card_frontmatter(
    md_path: Union[str, Path], updater: Callable[[Dict[str, Any]], Dict[str, Any]]
) -> Dict[str, Any]:
    """Safely update YAML frontmatter in an Obsidian Markdown note while preserving body text."""
    path = Path(md_path)
    raw_text = path.read_text(encoding="utf-8")
    yaml_str, body = split_frontmatter(raw_text)
    if yaml_str is None:
        raise ValueError(f"No YAML frontmatter found in {path}")
    meta = parse_yaml(yaml_str)
    if not isinstance(meta, dict):
        raise ValueError(f"Invalid YAML frontmatter mapping in {path}")
    updated_meta = updater(meta)
    new_yaml = dump_yaml(updated_meta).strip()
    body_clean = body.lstrip("\r\n")
    new_text = f"---\n{new_yaml}\n---\n\n{body_clean}" if body_clean else f"---\n{new_yaml}\n---\n"
    path.write_text(new_text, encoding="utf-8")
    return updated_meta
