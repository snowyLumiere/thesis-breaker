"""Zero-API local earnings report & metric table extractor.

Extracts numerical actuals from Markdown earnings summaries, CSV tables, or
key-value flash notes and maps them directly to ThesisCard kill-switch metrics.
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

from thesis_breaker.models import ThesisCard
from thesis_breaker.parsers.broker_csv import normalize_symbol

_NUMBER_RE = re.compile(
    r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|bps|B|M|x|X)?", re.IGNORECASE
)


def parse_metric_number(raw_value: str, expected_unit: str = "") -> Optional[float]:
    """Parse a formatted metric token like '62.0%', '-4.5%', '$22.1B', '-180 bps'."""
    text = raw_value.strip().replace("US$", "").replace("HK$", "").replace("$", "")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    num = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()
    if suffix == "bps" and expected_unit.strip() == "%":
        num = num / 100.0
    return num


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
            # Try to extract ticker token such as "MU", "9988.HK", "0700.HK" from heading
            ticker_match = re.search(r"\b(\d{4,5}\.HK|[A-Z]{1,6})\b", heading_text.upper())
            if ticker_match:
                current_key = normalize_symbol(ticker_match.group(1))
            else:
                current_key = heading_text
            sections.setdefault(current_key, [])
        sections[current_key].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _parse_kv_and_table_block(block_text: str) -> Dict[str, List[Tuple[str, str]]]:
    """Extract (label, raw_value_str) entries grouped by optional explicit symbol."""
    by_symbol: Dict[str, List[Tuple[str, str]]] = {"__SECTION__": []}
    lines = block_text.splitlines()
    table_rows = _extract_table_rows(lines)

    if len(table_rows) >= 2:
        headers = [_clean_label(h) for h in table_rows[0]]
        sym_col = next((i for i, h in enumerate(headers) if h in ("symbol", "ticker", "代码", "股票代码")), None)
        key_col = next((i for i, h in enumerate(headers) if h in ("metrickey", "key", "metric", "指标", "指标键")), None)
        alias_col = next((i for i, h in enumerate(headers) if h in ("name", "label", "指标名称", "项目")), None)
        val_col = next((i for i, h in enumerate(headers) if h in ("actual", "actualvalue", "value", "最新值", "实际值")), None)

        for row in table_rows[1:]:
            if val_col is None:
                if len(row) >= 2:
                    by_symbol["__SECTION__"].append((row[0], row[1]))
                continue
            if val_col >= len(row):
                continue
            val_raw = row[val_col]
            sym_key = (
                normalize_symbol(row[sym_col])
                if sym_col is not None and sym_col < len(row) and row[sym_col]
                else "__SECTION__"
            )
            by_symbol.setdefault(sym_key, [])
            if key_col is not None and key_col < len(row) and row[key_col]:
                by_symbol[sym_key].append((row[key_col], val_raw))
            if alias_col is not None and alias_col < len(row) and row[alias_col]:
                by_symbol[sym_key].append((row[alias_col], val_raw))

    # Also parse bullet / key: value lines AND whitespace/tab-aligned PDF table lines
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        kv_match = re.match(r"^([^:=：]+?)\s*[:=：]\s*(.+)$", stripped)
        if kv_match:
            label = kv_match.group(1).strip().strip("`*")
            val_raw = kv_match.group(2).strip()
            by_symbol["__SECTION__"].append((label, val_raw))
            continue

        # Whitespace/tab-aligned table rows copied from PDFs (e.g. "Q4 HBM3E 良率    62.0%    75.0%")
        cols = [c.strip() for c in re.split(r"\t+|\s{2,}", stripped) if c.strip()]
        if len(cols) >= 2:
            for col in cols[1:]:
                if parse_metric_number(col) is not None:
                    by_symbol["__SECTION__"].append((cols[0].strip("`*"), col))
                    break

    return by_symbol


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
        sym = norm_row.get("symbol") or norm_row.get("ticker") or ""
        sym_key = normalize_symbol(sym) if sym else "__GLOBAL__"
        metric = norm_row.get("metrickey") or norm_row.get("metric") or norm_row.get("key") or ""
        val = norm_row.get("actual") or norm_row.get("value") or norm_row.get("actualvalue") or ""
        if metric and val:
            by_symbol.setdefault(sym_key, []).append((metric, val))
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


def _match_metric_for_card(
    candidates: List[Tuple[str, str]],
    target_keys: Dict[str, Tuple[str, str]],
) -> Dict[str, float]:
    """Match extracted (label, raw_value) tuples against target metric keys & aliases."""
    matched: Dict[str, float] = {}
    cleaned_targets = {
        _clean_label(alias): (metric_key, unit)
        for alias, (metric_key, unit) in target_keys.items()
    }

    for label, raw_val in candidates:
        cleaned = _clean_label(label)
        if cleaned in cleaned_targets:
            metric_key, unit = cleaned_targets[cleaned]
            parsed = parse_metric_number(raw_val, expected_unit=unit)
            if parsed is not None:
                matched[metric_key] = parsed
                continue
        for alias_clean, (metric_key, unit) in cleaned_targets.items():
            if _is_safe_fuzzy_match(cleaned, alias_clean) and metric_key not in matched:
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
            pool = csv_entries.get(card.symbol, []) + csv_entries.get("__GLOBAL__", [])
            extracted = _match_metric_for_card(pool, targets)
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
    for block_map in parsed_blocks.values():
        for sym_key, pairs in block_map.items():
            if sym_key != "__SECTION__":
                explicit_symbol_rows.setdefault(sym_key, []).extend(pairs)

    for card in cards_list:
        targets = _build_card_target_map(card)
        pool: List[Tuple[str, str]] = []

        # 1. Explicit symbol rows in tables (highest priority)
        for sym_cand in [card.symbol, *card.symbol_aliases]:
            if sym_cand in explicit_symbol_rows:
                pool.extend(explicit_symbol_rows[sym_cand])

        # 2. Section headed by this ticker symbol
        for sym_cand in [card.symbol, *card.symbol_aliases]:
            if sym_cand in parsed_blocks:
                pool.extend(parsed_blocks[sym_cand].get("__SECTION__", []))

        # 3. Single-stock / unscoped fallback only if __GLOBAL__ exists
        if not pool and "__GLOBAL__" in parsed_blocks:
            pool.extend(parsed_blocks["__GLOBAL__"].get("__SECTION__", []))

        extracted = _match_metric_for_card(pool, targets)
        if extracted:
            results[card.symbol] = extracted

    return results


def _build_card_target_map(card: ThesisCard) -> Dict[str, Tuple[str, str]]:
    """Map every metric_key, name, and alias on a ThesisCard to (canonical_key, unit)."""
    targets: Dict[str, Tuple[str, str]] = {}
    for ks in card.kill_switches:
        if ks.metric_key:
            targets[ks.metric_key] = (ks.metric_key, ks.unit)
            targets[ks.name] = (ks.metric_key, ks.unit)
            for alias in ks.aliases:
                targets[alias] = (ks.metric_key, ks.unit)
    if card.valuation:
        for seg in card.valuation.segments:
            if seg.metric_key:
                targets.setdefault(seg.metric_key, (seg.metric_key, ""))
            if seg.multiple_key:
                targets.setdefault(seg.multiple_key, (seg.multiple_key, "x"))
        if card.valuation.model_type == "FCFE":
            targets.setdefault("base_fcfe_per_share", ("base_fcfe_per_share", ""))
            targets.setdefault("growth_rate_pct", ("growth_rate_pct", "%"))
    for k in card.latest_actuals:
        targets.setdefault(k, (k, ""))
    return targets
