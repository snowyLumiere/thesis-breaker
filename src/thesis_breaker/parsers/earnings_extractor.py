"""Zero-API local earnings report & metric table extractor.

Extracts numerical actuals from Markdown earnings summaries, CSV tables, or
key-value flash notes and maps them directly to ThesisCard kill-switch metrics.
"""

from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

from thesis_breaker.models import ThesisCard
from thesis_breaker.parsers.broker_csv import normalize_symbol

_CURRENCY_PREFIX_RE = re.compile(
    r"(?:US\$|HK\$|CN¥|USD|HKD|RMB|CNY|\$|¥)\s*",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(
    r"(?<![a-zA-Z0-9_.,+-])([+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+))"
    r"(?![\d.,])"
)

_UNIT_TOKEN_RE = re.compile(
    r"(?<![a-zA-Z])(万亿|百万|[亿万千]|%|bps|trillion|billion|million|thousand|tn|bn|mm|mn|[tbmkx])"
    r"(?![a-zA-Z0-9])",
    re.IGNORECASE,
)

_MAGNITUDE_SCALES: Dict[str, float] = {
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
    "万亿": 1e12,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "亿": 1e8,
    "m": 1e6,
    "mm": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "百万": 1e6,
    "万": 1e4,
    "k": 1e3,
    "thousand": 1e3,
    "千": 1e3,
}


def _normalize_expected_unit(expected_unit: str) -> str:
    stripped = _CURRENCY_PREFIX_RE.sub("", expected_unit.strip()).strip()
    if not stripped:
        return ""
    match = _UNIT_TOKEN_RE.search(stripped)
    if match:
        return match.group(1).lower()
    return stripped.lower()


def _infer_unit_from_key(metric_key: str) -> str:
    lowered = metric_key.strip().lower()
    if lowered.endswith("_pct"):
        return "%"
    if lowered.endswith("_bps"):
        return "bps"
    if lowered.endswith("_t"):
        return "T"
    if lowered.endswith("_b"):
        return "B"
    if lowered.endswith("_m"):
        return "M"
    if lowered.endswith("_k"):
        return "K"
    if lowered.endswith("_x"):
        return "x"
    return ""


def parse_metric_number(raw_value: str, expected_unit: str = "") -> Optional[float]:
    """Parse a formatted metric token and normalize units (e.g. $500M -> 0.5B, -180 bps -> -1.8%)."""
    text = _CURRENCY_PREFIX_RE.sub("", raw_value.strip())
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    num = float(match.group(1).replace(",", ""))
    if not math.isfinite(num):
        return None
    remainder = text[match.end():].lstrip()
    unit_match = _UNIT_TOKEN_RE.match(remainder)
    if unit_match:
        suffix = unit_match.group(1).lower()
    else:
        # Reject unsupported units rather than backtracking to a numeric prefix.
        if re.match(r"[a-zA-Z0-9_.,+\-\u4e00-\u9fff]", remainder):
            return None
        suffix = ""
    exp = _normalize_expected_unit(expected_unit)

    if not exp:
        return num

    if exp == "%":
        if suffix in ("", "%"):
            return num
        if suffix == "bps":
            return num / 100.0
        return None

    if exp == "bps":
        if suffix in ("", "bps"):
            return num
        if suffix == "%":
            return num * 100.0
        return None

    if exp in _MAGNITUDE_SCALES:
        if suffix == "":
            return num
        if suffix in _MAGNITUDE_SCALES:
            scaled = num * (_MAGNITUDE_SCALES[suffix] / _MAGNITUDE_SCALES[exp])
            return round(scaled, 10) if math.isfinite(scaled) else None
        return None

    if exp == "x":
        if suffix in ("", "x"):
            return num
        return None

    if suffix in ("", exp):
        return num
    return None


def _clean_label(label: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", label.strip().lower())


def _extract_table_rows(lines: List[str]) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in lines:
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _extract_section_blocks(text: str) -> Dict[str, str]:
    """Split Markdown by ## headings; returns {'__GLOBAL__': full_or_unscoped, symbol: block}."""
    sections: Dict[str, List[str]] = {"__GLOBAL__": []}
    current_key = "__GLOBAL__"
    for line in text.splitlines():
        heading_match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if heading_match:
            heading_text = heading_match.group(1).strip()
            ticker_match = re.search(
                r"\b("
                r"(?:HK|SEHK|HKEX|HKG)[.:]\d{1,5}"
                r"|\d{1,5}\.HK"
                r"|(?:US|USA|NASDAQ|NYSE|AMEX|ARCA)[.:][A-Z]{1,6}(?:\.[A-Z])?"
                r"|[A-Z]{1,6}(?:\.[A-Z])?\.US"
                r"|[A-Z]{1,6}(?:\.[A-Z])?"
                r")\b",
                heading_text.upper(),
            )
            if ticker_match:
                current_key = normalize_symbol(ticker_match.group(1))
            else:
                current_key = heading_text
            sections.setdefault(current_key, [])
        sections[current_key].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


@dataclass
class _ParsedBlock:
    explicit_rows: Dict[str, List[Tuple[str, str]]]
    section_table: List[Tuple[str, str]]
    section_prose: List[Tuple[str, str]]


def _parse_kv_and_table_block(block_text: str) -> _ParsedBlock:
    """Extract candidate (label, raw_value_str) tuples separated by structure priority."""
    explicit_rows: Dict[str, List[Tuple[str, str]]] = {}
    section_table: List[Tuple[str, str]] = []
    section_prose: List[Tuple[str, str]] = []

    lines = block_text.splitlines()
    table_rows = _extract_table_rows(lines)

    if len(table_rows) >= 2:
        headers = [_clean_label(h) for h in table_rows[0]]
        sym_col = next(
            (i for i, h in enumerate(headers) if h in ("symbol", "ticker", "代码", "股票代码")),
            None,
        )
        key_col = next(
            (i for i, h in enumerate(headers) if h in ("metrickey", "key", "metric", "指标", "指标键")),
            None,
        )
        alias_col = next(
            (i for i, h in enumerate(headers) if h in ("name", "label", "指标名称", "项目")),
            None,
        )
        val_col = next(
            (i for i, h in enumerate(headers) if h in ("actual", "actualvalue", "value", "最新值", "实际值")),
            None,
        )

        for row in table_rows[1:]:
            if val_col is None:
                if len(row) >= 2:
                    section_table.append((row[0], row[1]))
                continue
            if val_col >= len(row):
                continue
            val_raw = row[val_col]
            has_sym = sym_col is not None and sym_col < len(row) and bool(row[sym_col])
            target_list = (
                explicit_rows.setdefault(normalize_symbol(row[sym_col]), [])
                if has_sym
                else section_table
            )
            if key_col is not None and key_col < len(row) and row[key_col]:
                target_list.append((row[key_col], val_raw))
            if alias_col is not None and alias_col < len(row) and row[alias_col]:
                target_list.append((row[alias_col], val_raw))

    # Parse bullet / key: value lines AND whitespace/tab-aligned PDF table lines
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        kv_match = re.match(r"^([^:=：]+?)\s*[:=：]\s*(.+)$", stripped)
        if kv_match:
            label = kv_match.group(1).strip().strip("`*")
            val_raw = kv_match.group(2).strip()
            section_prose.append((label, val_raw))
            continue

        # Whitespace/tab-aligned table rows copied from PDFs (e.g. "Q4 HBM3E 良率    62.0%    75.0%")
        cols = [c.strip() for c in re.split(r"\t+|\s{2,}", stripped) if c.strip()]
        if len(cols) >= 2:
            for col in cols[1:]:
                if parse_metric_number(col) is not None:
                    section_prose.append((cols[0].strip("`*"), col))
                    break

    return _ParsedBlock(
        explicit_rows=explicit_rows,
        section_table=section_table,
        section_prose=section_prose,
    )


def _extract_pdf_text(path: Path) -> str:
    """Extract plain text from a local earnings PDF via pypdf or pdftotext if installed."""
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            reader = mod.PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError:
            continue

    pdftotext_bin = shutil.which("pdftotext")
    if pdftotext_bin:
        proc = subprocess.run(
            [pdftotext_bin, "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    raise RuntimeError(
        f"PDF extraction requires 'pypdf' or 'pdftotext' installed locally ({path})."
    )


def _extract_from_csv(path: Path) -> Dict[str, List[Tuple[str, str]]]:
    by_symbol: Dict[str, List[Tuple[str, str]]] = {"__GLOBAL__": []}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        norm_row = {_clean_label(k): (v or "").strip() for k, v in row.items() if k}
        sym = (
            norm_row.get("symbol")
            or norm_row.get("ticker")
            or norm_row.get("代码")
            or norm_row.get("股票代码")
            or ""
        )
        sym_key = normalize_symbol(sym) if sym else "__GLOBAL__"
        metric = (
            norm_row.get("metrickey")
            or norm_row.get("metric")
            or norm_row.get("key")
            or norm_row.get("指标")
            or norm_row.get("指标键")
            or ""
        )
        alias = norm_row.get("name") or norm_row.get("label") or norm_row.get("指标名称") or ""
        val = (
            norm_row.get("actual")
            or norm_row.get("value")
            or norm_row.get("actualvalue")
            or norm_row.get("最新值")
            or norm_row.get("实际值")
            or ""
        )
        if val:
            if metric:
                by_symbol.setdefault(sym_key, []).append((metric, val))
            if alias:
                by_symbol.setdefault(sym_key, []).append((alias, val))
    return by_symbol


def _is_safe_fuzzy_match(cleaned_label: str, alias_clean: str) -> bool:
    """Prevent short generic tokens ('q4', 'yoy', 'ai') from colliding with longer metric names."""
    if not cleaned_label or not alias_clean:
        return False
    if len(alias_clean) >= 4 and alias_clean in cleaned_label:
        return True
    cjk_count = sum(1 for ch in cleaned_label if "\u4e00" <= ch <= "\u9fff")
    if (len(cleaned_label) >= 6 or cjk_count >= 4) and cleaned_label in alias_clean:
        return True
    return False


@dataclass
class _CardTargetMaps:
    canonical_keys: Dict[str, Tuple[str, str]]
    exact_aliases: Dict[str, Tuple[str, str]]


def _match_tiers_for_card(
    tiers: List[List[Tuple[str, str]]],
    targets: _CardTargetMaps,
) -> Dict[str, float]:
    """Match candidate tiers from highest to lowest priority; never overwrite matched keys."""
    matched: Dict[str, float] = {}
    cleaned_keys = {
        _clean_label(k): val for k, val in targets.canonical_keys.items() if _clean_label(k)
    }
    cleaned_aliases = {
        _clean_label(alias): val
        for alias, val in targets.exact_aliases.items()
        if _clean_label(alias)
    }
    combined_fuzzy: Dict[str, Tuple[str, str]] = {**cleaned_keys, **cleaned_aliases}

    for candidates in tiers:
        if not candidates:
            continue

        # Pass 1: exact canonical metric_key matches
        for label, raw_val in candidates:
            cleaned = _clean_label(label)
            if cleaned in cleaned_keys:
                metric_key, unit = cleaned_keys[cleaned]
                if metric_key not in matched:
                    parsed = parse_metric_number(raw_val, expected_unit=unit)
                    if parsed is not None:
                        matched[metric_key] = parsed

        # Pass 2: exact human name / alias matches
        for label, raw_val in candidates:
            cleaned = _clean_label(label)
            if cleaned in cleaned_aliases:
                metric_key, unit = cleaned_aliases[cleaned]
                if metric_key not in matched:
                    parsed = parse_metric_number(raw_val, expected_unit=unit)
                    if parsed is not None:
                        matched[metric_key] = parsed

        # Pass 3: safe fuzzy matches
        for label, raw_val in candidates:
            cleaned = _clean_label(label)
            for alias_clean, (metric_key, unit) in combined_fuzzy.items():
                if metric_key not in matched and _is_safe_fuzzy_match(cleaned, alias_clean):
                    parsed = parse_metric_number(raw_val, expected_unit=unit)
                    if parsed is not None:
                        matched[metric_key] = parsed

    return matched


def extract_earnings_metrics(
    earnings_path: Union[str, Path],
    cards: Iterable[ThesisCard],
) -> Dict[str, Dict[str, float]]:
    """Extract kill-switch & valuation metrics per symbol from a local Markdown, CSV, or PDF report."""
    path = Path(earnings_path)
    cards_list = list(cards)
    results: Dict[str, Dict[str, float]] = {}

    if path.suffix.lower() == ".csv":
        csv_entries = _extract_from_csv(path)
        for card in cards_list:
            targets = _build_card_target_map(card)
            tier1: List[Tuple[str, str]] = []
            for sym_cand in [card.symbol, *card.symbol_aliases]:
                tier1.extend(csv_entries.get(sym_cand, []))
            tier2 = csv_entries.get("__GLOBAL__", [])
            extracted = _match_tiers_for_card([tier1, tier2], targets)
            if extracted:
                results[card.symbol] = extracted
        return results

    raw_text = (
        _extract_pdf_text(path)
        if path.suffix.lower() == ".pdf"
        else path.read_text(encoding="utf-8")
    )
    section_blocks = _extract_section_blocks(raw_text)
    parsed_blocks = {sec: _parse_kv_and_table_block(txt) for sec, txt in section_blocks.items()}

    # Build a flat lookup across explicit symbol rows in any block
    explicit_symbol_rows: Dict[str, List[Tuple[str, str]]] = {}
    for block in parsed_blocks.values():
        for sym_key, pairs in block.explicit_rows.items():
            explicit_symbol_rows.setdefault(sym_key, []).extend(pairs)

    for card in cards_list:
        targets = _build_card_target_map(card)
        sym_candidates = [card.symbol, *card.symbol_aliases]

        # Tier 1: Explicit symbol rows in tables (highest priority)
        tier1: List[Tuple[str, str]] = []
        for sym_cand in sym_candidates:
            tier1.extend(explicit_symbol_rows.get(sym_cand, []))

        # Tier 2: Markdown tables under section headed by this ticker symbol
        tier2: List[Tuple[str, str]] = []
        # Tier 3: Bullet / prose / whitespace-aligned lines under section headed by this symbol
        tier3: List[Tuple[str, str]] = []
        for sym_cand in sym_candidates:
            if sym_cand in parsed_blocks:
                tier2.extend(parsed_blocks[sym_cand].section_table)
                tier3.extend(parsed_blocks[sym_cand].section_prose)

        tiers = [tier1, tier2, tier3]
        # Tier 4: Single-stock / unscoped fallback only when no symbol-specific entries exist
        if not any(tiers) and "__GLOBAL__" in parsed_blocks:
            tiers.append(parsed_blocks["__GLOBAL__"].section_table)
            tiers.append(parsed_blocks["__GLOBAL__"].section_prose)

        extracted = _match_tiers_for_card(tiers, targets)
        if extracted:
            results[card.symbol] = extracted

    return results


def _build_card_target_map(card: ThesisCard) -> _CardTargetMaps:
    """Map every metric_key, name, and alias on a ThesisCard to (canonical_key, unit)."""
    canonical_keys: Dict[str, Tuple[str, str]] = {}
    exact_aliases: Dict[str, Tuple[str, str]] = {}

    for ks in card.kill_switches:
        if ks.metric_key:
            unit = ks.unit or _infer_unit_from_key(ks.metric_key)
            canonical_keys[ks.metric_key] = (ks.metric_key, unit)
            exact_aliases[ks.name] = (ks.metric_key, unit)
            for alias in ks.aliases:
                exact_aliases[alias] = (ks.metric_key, unit)
    if card.valuation:
        for seg in card.valuation.segments:
            if seg.metric_key:
                canonical_keys.setdefault(
                    seg.metric_key, (seg.metric_key, _infer_unit_from_key(seg.metric_key))
                )
            if seg.multiple_key:
                canonical_keys.setdefault(seg.multiple_key, (seg.multiple_key, "x"))
        if card.valuation.model_type == "FCFE":
            canonical_keys.setdefault("base_fcfe_per_share", ("base_fcfe_per_share", ""))
            canonical_keys.setdefault("growth_rate_pct", ("growth_rate_pct", "%"))
    for k in card.latest_actuals:
        canonical_keys.setdefault(k, (k, _infer_unit_from_key(k)))

    return _CardTargetMaps(canonical_keys=canonical_keys, exact_aliases=exact_aliases)
