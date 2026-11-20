"""Deterministic SOTP and FCFE valuation and repricing calculators."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from thesis_breaker.models import KillSwitchResult, ValuationConfig, ValuationResult
from thesis_breaker.numeric import finite_float


def _validate_inputs(
    config: ValuationConfig, actuals: Dict[str, float], entry_price: float, current_price: float
) -> None:
    for field in (
        "diluted_shares", "net_cash", "required_mos_pct", "base_fcfe_per_share",
        "growth_rate_pct", "terminal_growth_pct", "cost_of_equity_pct", "projection_years",
    ):
        finite_float(getattr(config, field), f"valuation.{field}")
    for index, segment in enumerate(config.segments):
        for field in ("metric_value", "multiple", "ownership_pct"):
            finite_float(getattr(segment, field), f"valuation.segments[{index}].{field}")
    for key, value in actuals.items():
        finite_float(value, f"actuals.{key}")
    finite_float(entry_price, "entry_price")
    finite_float(current_price, "current_price")


def _checked_result(result: ValuationResult) -> ValuationResult:
    for field, value in vars(result).items():
        if isinstance(value, (int, float)):
            finite_float(value, f"valuation_result.{field}")
    return result


def _safe_mos(intrinsic_value: float, price: float) -> float:
    """Compute Margin of Safety percentage: (IV - Price) / IV * 100."""
    if intrinsic_value <= 0:
        return -100.0
    return ((intrinsic_value - price) / intrinsic_value) * 100.0


def _finalize_mos(
    initial_iv: float,
    repriced_iv: float,
    entry_price: float,
    current_price: float,
    required_mos_pct: float,
    notes: List[str],
) -> Tuple[Optional[float], Optional[float], bool]:
    """Compute entry/current Margin of Safety; return None instead of 100% when price is missing."""
    ref_entry = entry_price if entry_price > 0 else current_price
    initial_mos = (
        round(_safe_mos(initial_iv, ref_entry), 2) if ref_entry > 0 else None
    )
    if current_price > 0:
        raw_current_mos = _safe_mos(repriced_iv, current_price)
        return (
            initial_mos,
            round(raw_current_mos, 2),
            raw_current_mos <= 0.0 or raw_current_mos < required_mos_pct,
        )

    notes.append("缺少有效现价（current_price <= 0），无法计算当前安全边际")
    return initial_mos, None, False


def _sum_breached_haircuts(kill_switch_results: List[KillSwitchResult]) -> float:
    """Aggregate valuation haircut percentage across breached kill-switches (capped at 90%)."""
    total = sum(
        max(0.0, finite_float(ksr.kill_switch.haircut_pct, "haircut_pct"))
        for ksr in kill_switch_results
        if ksr.breached
    )
    return min(90.0, total)


def compute_sotp(
    config: ValuationConfig,
    kill_switch_results: List[KillSwitchResult],
    actuals: Dict[str, float],
    entry_price: float,
    current_price: float,
) -> ValuationResult:
    """Compute initial and repriced Sum-Of-The-Parts (SOTP) intrinsic value per share."""
    _validate_inputs(config, actuals, entry_price, current_price)
    shares = config.diluted_shares if config.diluted_shares > 0 else 1.0
    notes: List[str] = []

    initial_ev = 0.0
    repriced_ev = 0.0
    for seg in config.segments:
        ownership = seg.ownership_pct / 100.0
        initial_ev += seg.metric_value * seg.multiple * ownership

        seg_metric = (
            actuals[seg.metric_key]
            if seg.metric_key and seg.metric_key in actuals
            else seg.metric_value
        )
        seg_mult = (
            actuals[seg.multiple_key]
            if seg.multiple_key and seg.multiple_key in actuals
            else seg.multiple
        )
        if seg.metric_key and seg.metric_key in actuals and seg_metric != seg.metric_value:
            notes.append(
                f"{seg.name} 基准指标从 {seg.metric_value:.2f} 修正为 {seg_metric:.2f}"
            )
        if seg.multiple_key and seg.multiple_key in actuals and seg_mult != seg.multiple:
            notes.append(
                f"{seg.name} 估值倍数从 {seg.multiple:.2f}x 修正为 {seg_mult:.2f}x"
            )
        repriced_ev += seg_metric * seg_mult * ownership

    initial_iv = (initial_ev + config.net_cash) / shares
    pre_haircut_iv = (repriced_ev + config.net_cash) / shares

    total_haircut = _sum_breached_haircuts(kill_switch_results)
    repriced_iv = max(0.0, pre_haircut_iv * (1.0 - total_haircut / 100.0))

    val_change_pct = (
        ((repriced_iv - initial_iv) / initial_iv) * 100.0 if initial_iv > 0 else 0.0
    )
    initial_mos, current_mos, mos_vanished = _finalize_mos(
        initial_iv=initial_iv,
        repriced_iv=repriced_iv,
        entry_price=entry_price,
        current_price=current_price,
        required_mos_pct=config.required_mos_pct,
        notes=notes,
    )

    result = ValuationResult(
        model_type="SOTP",
        currency=config.currency,
        initial_intrinsic_value=round(initial_iv, 2),
        repriced_intrinsic_value=round(repriced_iv, 2),
        valuation_change_pct=round(val_change_pct, 2),
        current_price=round(current_price, 2),
        initial_mos_pct=initial_mos,
        current_mos_pct=current_mos,
        required_mos_pct=round(config.required_mos_pct, 2),
        mos_vanished=mos_vanished,
        total_haircut_applied_pct=round(total_haircut, 2),
        notes=notes,
    )
    return _checked_result(result)


def _fcfe_dcf_per_share(
    base_fcfe: float,
    growth_rate_pct: float,
    terminal_growth_pct: float,
    cost_of_equity_pct: float,
    projection_years: int,
    net_cash_per_share: float,
) -> float:
    """Two-stage Free Cash Flow to Equity (FCFE) Gordon Growth model per share."""
    if projection_years < 1:
        raise ValueError(
            f"Invalid FCFE projection_years ({projection_years}): must be >= 1."
        )
    if cost_of_equity_pct <= -100.0:
        raise ValueError(
            f"Invalid FCFE cost_of_equity_pct ({cost_of_equity_pct}%): must be > -100%."
        )
    if terminal_growth_pct >= cost_of_equity_pct:
        raise ValueError(
            f"Invalid FCFE parameters: cost_of_equity_pct ({cost_of_equity_pct}%) "
            f"must be strictly greater than terminal_growth_pct ({terminal_growth_pct}%)."
        )

    g = growth_rate_pct / 100.0
    gt = terminal_growth_pct / 100.0
    ke = cost_of_equity_pct / 100.0
    spread = ke - gt

    pv_explicit = 0.0
    projected_fcfe = base_fcfe
    for yr in range(1, projection_years + 1):
        projected_fcfe = projected_fcfe * (1.0 + g)
        pv_explicit += projected_fcfe / ((1.0 + ke) ** yr)

    terminal_value = (projected_fcfe * (1.0 + gt)) / spread
    pv_terminal = terminal_value / ((1.0 + ke) ** projection_years)
    intrinsic_value = finite_float(
        pv_explicit + pv_terminal + net_cash_per_share, "fcfe_intrinsic_value"
    )
    return max(0.0, intrinsic_value)


def compute_fcfe(
    config: ValuationConfig,
    kill_switch_results: List[KillSwitchResult],
    actuals: Dict[str, float],
    entry_price: float,
    current_price: float,
) -> ValuationResult:
    """Compute initial and repriced FCFE intrinsic value per share."""
    _validate_inputs(config, actuals, entry_price, current_price)
    shares = config.diluted_shares if config.diluted_shares > 0 else 1.0
    net_cash_per_share = config.net_cash / shares
    notes: List[str] = []

    initial_iv = _fcfe_dcf_per_share(
        base_fcfe=config.base_fcfe_per_share,
        growth_rate_pct=config.growth_rate_pct,
        terminal_growth_pct=config.terminal_growth_pct,
        cost_of_equity_pct=config.cost_of_equity_pct,
        projection_years=config.projection_years,
        net_cash_per_share=net_cash_per_share,
    )

    rep_fcfe = actuals.get("base_fcfe_per_share", config.base_fcfe_per_share)
    rep_growth = actuals.get("growth_rate_pct", config.growth_rate_pct)
    rep_ke = actuals.get("cost_of_equity_pct", config.cost_of_equity_pct)

    if rep_fcfe != config.base_fcfe_per_share:
        notes.append(
            f"每股基准 FCFE 从 {config.base_fcfe_per_share:.2f} 更新为 {rep_fcfe:.2f}"
        )
    if rep_growth != config.growth_rate_pct:
        notes.append(
            f"显性期 FCFE 增速从 {config.growth_rate_pct:.1f}% 更新为 {rep_growth:.1f}%"
        )

    pre_haircut_iv = _fcfe_dcf_per_share(
        base_fcfe=rep_fcfe,
        growth_rate_pct=rep_growth,
        terminal_growth_pct=config.terminal_growth_pct,
        cost_of_equity_pct=rep_ke,
        projection_years=config.projection_years,
        net_cash_per_share=net_cash_per_share,
    )

    total_haircut = _sum_breached_haircuts(kill_switch_results)
    repriced_iv = max(0.0, pre_haircut_iv * (1.0 - total_haircut / 100.0))

    val_change_pct = (
        ((repriced_iv - initial_iv) / initial_iv) * 100.0 if initial_iv > 0 else 0.0
    )
    initial_mos, current_mos, mos_vanished = _finalize_mos(
        initial_iv=initial_iv,
        repriced_iv=repriced_iv,
        entry_price=entry_price,
        current_price=current_price,
        required_mos_pct=config.required_mos_pct,
        notes=notes,
    )

    result = ValuationResult(
        model_type="FCFE",
        currency=config.currency,
        initial_intrinsic_value=round(initial_iv, 2),
        repriced_intrinsic_value=round(repriced_iv, 2),
        valuation_change_pct=round(val_change_pct, 2),
        current_price=round(current_price, 2),
        initial_mos_pct=initial_mos,
        current_mos_pct=current_mos,
        required_mos_pct=round(config.required_mos_pct, 2),
        mos_vanished=mos_vanished,
        total_haircut_applied_pct=round(total_haircut, 2),
        notes=notes,
    )
    return _checked_result(result)


def reprice_valuation(
    config: ValuationConfig,
    kill_switch_results: List[KillSwitchResult],
    actuals: Dict[str, float],
    entry_price: float,
    current_price: float,
) -> ValuationResult:
    """Dispatch valuation calculation according to model_type ('SOTP' or 'FCFE')."""
    model = config.model_type.strip().upper()
    if model == "FCFE":
        return compute_fcfe(config, kill_switch_results, actuals, entry_price, current_price)
    return compute_sotp(config, kill_switch_results, actuals, entry_price, current_price)
