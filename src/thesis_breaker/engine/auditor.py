"""Kill-switch evaluator, Thesis Creep detector, and Exposure Posture auditor."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Dict, Iterable, List, Optional, Tuple

from thesis_breaker.engine.thesis_lock import is_threshold_relaxed, verify_thesis_lock
from thesis_breaker.engine.valuation import reprice_valuation
from thesis_breaker.numeric import finite_float
from thesis_breaker.formatters.caveman import format_caveman_lines
from thesis_breaker.models import (
    DriftAuditResult,
    ExposurePosture,
    KillSwitch,
    KillSwitchResult,
    PositionAuditReport,
    PositionRecord,
    ThesisCard,
    ValuationResult,
    select_worst_breach,
)

# Self-deception / rationalization phrases commonly written after drawdowns or earnings misses.
_RATIONALIZATION_PATTERNS: Tuple[str, ...] = (
    "长期价值",
    "长期主义",
    "价值投资",
    "长期持有",
    "超级周期",
    "战略性投入",
    "忽略短期",
    "短期噪音",
    "短期波动",
    "逢低摊平",
    "加仓摊低",
    "信仰",
    "死扛",
    "长坡厚雪",
    "时间的朋友",
    "耐心等待下个周期",
    "下个季度会好",
    "long-term value",
    "long-term compounder",
    "ignore short-term",
    "short-term noise",
    "buying the dip",
    "averaging down",
    "hold through",
    "permanent capital",
)

_STRATEGY_LABELS: Dict[str, str] = {
    "cyclical_swing": "基本面波段/周期交易",
    "sotp_rerating": "SOTP 分部重估",
    "compounder_fcfe": "长期现金流复利",
    "long_term_value": "长期价值死扛",
    "event_driven": "事件驱动",
}


def _check_operator(actual: float, operator: str, threshold: float) -> bool:
    """Return True if actual satisfies (passes) the kill-switch condition."""
    op = operator.strip()
    if op == ">=":
        return actual >= threshold
    if op == ">":
        return actual > threshold
    if op == "<=":
        return actual <= threshold
    if op == "<":
        return actual < threshold
    if op == "==":
        return abs(actual - threshold) < 1e-9
    raise ValueError(f"Unsupported kill-switch operator: {operator!r}")


def evaluate_kill_switch(
    ks: KillSwitch, actuals: Dict[str, float]
) -> KillSwitchResult:
    """Evaluate a single falsifiable kill-switch against latest actual data."""
    finite_float(ks.threshold, f"kill_switch.{ks.id}.threshold")
    finite_float(ks.haircut_pct, f"kill_switch.{ks.id}.haircut_pct")
    if ks.locked_threshold is not None:
        finite_float(ks.locked_threshold, f"kill_switch.{ks.id}.locked_threshold")
    relaxed = is_threshold_relaxed(ks)
    # Audit against the stricter original locked_threshold if tolerance creep occurred!
    effective_threshold = (
        ks.locked_threshold
        if (relaxed and ks.locked_threshold is not None)
        else ks.threshold
    )

    if ks.metric_key not in actuals:
        return KillSwitchResult(
            kill_switch=ks,
            actual_value=None,
            breached=False,
            deviation_pct=None,
            tolerance_creep_detected=relaxed,
            original_threshold=ks.locked_threshold if relaxed else None,
            missing_data=True,
        )

    actual = finite_float(actuals[ks.metric_key], f"actuals.{ks.metric_key}")
    passed = _check_operator(actual, ks.operator, effective_threshold)
    breached = not passed

    if abs(effective_threshold) > 1e-9:
        deviation_pct = ((actual - effective_threshold) / abs(effective_threshold)) * 100.0
    else:
        deviation_pct = actual - effective_threshold
    finite_float(deviation_pct, f"kill_switch.{ks.id}.deviation_pct")

    return KillSwitchResult(
        kill_switch=ks,
        actual_value=round(actual, 4),
        breached=breached,
        deviation_pct=round(deviation_pct, 2),
        tolerance_creep_detected=relaxed,
        original_threshold=ks.locked_threshold if relaxed else None,
        missing_data=False,
    )


def _extract_rationalization_sentences(notes: str) -> Tuple[List[str], Optional[str]]:
    """Find rationalization phrases and the most specific excuse sentence in review notes."""
    if not notes.strip():
        return [], None
    clauses = [
        c.strip()
        for c in re.split(r"(?:[。！？\n!?;；]+|(?<!\d)\.(?!\d))", notes)
        if c.strip()
    ]
    matched_phrases: List[str] = []
    best_clause: Optional[str] = None
    best_hits = 0

    for clause in clauses:
        lowered = clause.lower()
        hits_in_clause: List[str] = []
        for pat in _RATIONALIZATION_PATTERNS:
            if pat.lower() in lowered:
                hits_in_clause.append(pat)
                if pat not in matched_phrases:
                    matched_phrases.append(pat)
        if len(hits_in_clause) > best_hits:
            best_hits = len(hits_in_clause)
            best_clause = clause

    if best_clause and len(best_clause) > 78:
        best_clause = best_clause[:75].rstrip() + "..."
    return matched_phrases, best_clause


def _format_failed_assumption(ksr: KillSwitchResult) -> str:
    ks = ksr.kill_switch
    unit = ks.unit
    if ksr.actual_value is not None:
        return (
            f"{ks.name}（实测 {ksr.actual_value:g}{unit} vs 死线 "
            f"{ks.operator}{ksr.original_threshold if ksr.tolerance_creep_detected else ks.threshold:g}{unit}）"
        )
    return f"{ks.name}（死线 {ks.operator}{ks.threshold:g}{unit}）"


def detect_thesis_drift(
    card: ThesisCard,
    position: PositionRecord,
    ks_results: List[KillSwitchResult],
    lock_valid: bool,
) -> DriftAuditResult:
    """Detect Thesis Creep (style drift, silent threshold relaxation, and self-deception)."""
    style_drift: Optional[str] = None
    if (
        card.initial_strategy_type
        and card.current_claimed_style
        and card.initial_strategy_type != card.current_claimed_style
    ):
        init_label = _STRATEGY_LABELS.get(card.initial_strategy_type, card.initial_strategy_type)
        curr_label = _STRATEGY_LABELS.get(card.current_claimed_style, card.current_claimed_style)
        style_drift = f"{init_label} -> {curr_label}"

    tolerance_creep_details: List[str] = []
    for ksr in ks_results:
        if ksr.tolerance_creep_detected and ksr.original_threshold is not None:
            ks = ksr.kill_switch
            tolerance_creep_details.append(
                f"{ks.name} 阈值被暗中放宽: {ksr.original_threshold:g}{ks.unit} -> {ks.threshold:g}{ks.unit}"
            )

    phrases, best_clause = _extract_rationalization_sentences(card.latest_review_notes)
    breached_results = [ksr for ksr in ks_results if ksr.breached]
    creep_results = [ksr for ksr in ks_results if ksr.tolerance_creep_detected]

    has_conflict = bool(breached_results or creep_results or position.unrealized_pnl_pct <= -10.0)
    rationalization_triggered = bool(phrases) and has_conflict

    drift_detected = bool(
        style_drift or tolerance_creep_details or rationalization_triggered or (not lock_valid)
    )

    excuse_summary: Optional[str] = None
    if rationalization_triggered and best_clause:
        excuse_summary = best_clause
    elif style_drift:
        excuse_summary = f"将「{style_drift}」当作继续持仓理由"
    elif tolerance_creep_details:
        excuse_summary = tolerance_creep_details[0]
    elif not lock_valid:
        excuse_summary = "事后篡改已锁定的死线条件或估值基准"

    failed_assumption_summary: Optional[str] = None
    if breached_results:
        worst = select_worst_breach(breached_results)
        failed_assumption_summary = _format_failed_assumption(worst)
    elif creep_results:
        failed_assumption_summary = _format_failed_assumption(creep_results[0])
    elif not lock_valid:
        failed_assumption_summary = "SHA-256 锁定的初始死线契约"

    return DriftAuditResult(
        drift_detected=drift_detected,
        style_drift=style_drift,
        tolerance_creep_details=tolerance_creep_details,
        rationalization_phrases=phrases if rationalization_triggered else [],
        excuse_summary=excuse_summary,
        failed_assumption_summary=failed_assumption_summary,
        lock_tampered=not lock_valid,
    )


def _determine_posture_and_action(
    position: PositionRecord,
    card: Optional[ThesisCard],
    ks_results: List[KillSwitchResult],
    val_result: Optional[ValuationResult],
    drift: DriftAuditResult,
) -> Tuple[ExposurePosture, str]:
    """Map deterministic facts to an ExposurePosture for human review (never auto-orders)."""
    if card is None or len(card.kill_switches) < 3:
        reason = (
            "缺少 Obsidian 买入逻辑存证卡（裸奔仓位）"
            if card is None
            else "逻辑卡不足 3 条可证伪死线"
        )
        return (
            ExposurePosture.UNTRACKED_NAKED_POSITION,
            f"48小时内补齐3条可证伪死线与估值底稿，否则清仓归零（{reason}）",
        )

    breached = [r for r in ks_results if r.breached]
    critical_breach = any(r.kill_switch.critical for r in breached)
    mos_negative = (
        val_result is not None
        and val_result.current_mos_pct is not None
        and val_result.current_mos_pct <= 0.0
    )
    mos_below_floor = (
        val_result is not None
        and val_result.current_mos_pct is not None
        and val_result.current_mos_pct < val_result.required_mos_pct
    )
    price_missing = position.current_price <= 0.0 or (
        val_result is not None and val_result.current_mos_pct is None
    )

    if critical_breach or len(breached) >= 2 or (
        len(breached) >= 1 and (mos_negative or drift.drift_detected)
    ):
        return (
            ExposurePosture.KILL_SWITCH_TRIGGERED,
            "无条件执行死线砍仓/清仓（至少立即削减 50%-100% 敞口），禁止摊平",
        )

    # An unavailable valuation cannot erase an independently established breach.
    if card.validation_errors and not breached:
        return (
            ExposurePosture.UNTRACKED_NAKED_POSITION,
            "48小时内补齐3条可证伪死线与估值底稿，否则清仓归零"
            f"（逻辑卡校验未通过: {'; '.join(card.validation_errors)}）",
        )

    if (
        len(breached) == 1
        or drift.lock_tampered
        or drift.tolerance_creep_details
        or drift.style_drift
        or mos_below_floor
    ):
        return (
            ExposurePosture.TRIM_EXPOSURE,
            "执行纪律裁剪（削减 30%-50% 风险敞口），恢复锁定的原始死线",
        )

    missing_any = any(r.missing_data for r in ks_results)
    if (
        position.unrealized_pnl_pct <= -10.0
        or missing_any
        or price_missing
        or drift.rationalization_phrases
    ):
        return (
            ExposurePosture.WATCH_WARNING,
            "暂停加仓并补全最新指标核对，紧盯剩余死线边界",
        )

    return (
        ExposurePosture.HOLD_CONVICTION,
        "维持当前仓位，继续按季度跟踪 3 条核心死线",
    )


def _merge_actuals(
    card: ThesisCard, external_actuals: Optional[Dict[str, float]]
) -> Dict[str, float]:
    merged = dict(card.latest_actuals)
    if external_actuals:
        merged.update(external_actuals)
    return merged


def audit_position(
    position: PositionRecord,
    card: Optional[ThesisCard],
    external_actuals: Optional[Dict[str, float]] = None,
) -> PositionAuditReport:
    """Run deterministic kill-switch, valuation repricing, and drift audit for one position."""
    if card is None:
        empty_drift = DriftAuditResult(drift_detected=False)
        posture, action = _determine_posture_and_action(
            position, None, [], None, empty_drift
        )
        preliminary = PositionAuditReport(
            position=position,
            thesis_card=None,
            kill_switch_results=[],
            valuation_result=None,
            drift_result=empty_drift,
            posture=posture,
            recommended_action=action,
            caveman_lines=[],
            warnings=["持仓存在于券商交割单，但未匹配到 Obsidian 投研存证卡"],
        )
        preliminary.caveman_lines = format_caveman_lines(preliminary)
        return preliminary

    runtime_errors: List[str] = []
    actuals: Dict[str, float] = {}
    for key, value in _merge_actuals(card, external_actuals).items():
        try:
            actuals[key] = finite_float(value, f"actuals.{key}")
        except ValueError as exc:
            runtime_errors.append(str(exc))
    for field in (
        "quantity", "avg_cost", "current_price", "market_value",
        "unrealized_pnl", "unrealized_pnl_pct", "account_weight_pct",
    ):
        try:
            finite_float(getattr(position, field), f"position.{field}")
        except ValueError as exc:
            runtime_errors.append(str(exc))
    ks_results: List[KillSwitchResult] = []
    for ks in card.kill_switches:
        try:
            ks_results.append(evaluate_kill_switch(ks, actuals))
        except (ValueError, OverflowError) as exc:
            runtime_errors.append(str(exc))

    lock_valid, lock_reason = verify_thesis_lock(card)
    val_result: Optional[ValuationResult] = None
    if card.valuation is not None and not card.validation_errors and not runtime_errors:
        try:
            val_result = reprice_valuation(
                config=card.valuation,
                kill_switch_results=ks_results,
                actuals=actuals,
                entry_price=card.entry_price,
                current_price=position.current_price,
            )
        except (ValueError, OverflowError) as exc:
            runtime_errors.append(str(exc))

    effective_card = (
        replace(card, validation_errors=[*card.validation_errors, *runtime_errors])
        if runtime_errors
        else card
    )
    drift = detect_thesis_drift(effective_card, position, ks_results, lock_valid=lock_valid)
    posture, action = _determine_posture_and_action(
        position, effective_card, ks_results, val_result, drift
    )

    warnings: List[str] = list(effective_card.validation_errors)
    if not lock_valid:
        warnings.append(lock_reason)
    if position.current_price <= 0.0:
        warnings.append("券商 CSV 缺少有效现价（MarkPrice / PositionValue），无法校验当前安全边际")
    missing_keys = [r.kill_switch.metric_key for r in ks_results if r.missing_data]
    if missing_keys:
        warnings.append(f"缺少最新实际数据指标: {', '.join(missing_keys)}")

    report = PositionAuditReport(
        position=position,
        thesis_card=effective_card,
        kill_switch_results=ks_results,
        valuation_result=val_result,
        drift_result=drift,
        posture=posture,
        recommended_action=action,
        caveman_lines=[],
        warnings=warnings,
    )
    report.caveman_lines = format_caveman_lines(report)
    return report


def _lookup_card_for_position(
    position: PositionRecord, cards: Dict[str, ThesisCard]
) -> Optional[ThesisCard]:
    if position.symbol in cards:
        return cards[position.symbol]
    for card in cards.values():
        if position.symbol in card.symbol_aliases:
            return card
    return None


def audit_portfolio(
    positions: Iterable[PositionRecord],
    cards: Dict[str, ThesisCard],
    extracted_actuals: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[PositionAuditReport]:
    """Audit all open positions against Obsidian ThesisCards and extracted actuals."""
    reports: List[PositionAuditReport] = []
    actuals_map = extracted_actuals or {}
    for pos in positions:
        card = _lookup_card_for_position(pos, cards)
        ext_actuals: Optional[Dict[str, float]] = None
        if card is not None:
            ext_actuals = actuals_map.get(card.symbol) or actuals_map.get(pos.symbol)
        reports.append(audit_position(pos, card, external_actuals=ext_actuals))
    return reports
