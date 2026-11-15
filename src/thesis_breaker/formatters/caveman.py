"""Caveman-style ultra-terse telegraphic formatter plus Markdown & JSON renderers."""

from __future__ import annotations

import json
from typing import List

from thesis_breaker.models import (
    ExposurePosture,
    KillSwitchResult,
    PositionAuditReport,
    select_worst_breach,
)


def _format_breach_detail(report: PositionAuditReport) -> str:
    breached = [r for r in report.kill_switch_results if r.breached]
    creeped = [r for r in report.kill_switch_results if r.tolerance_creep_detected]
    total = len(report.kill_switch_results)

    if breached:
        worst = select_worst_breach(breached)
        ks = worst.kill_switch
        thr = worst.original_threshold if worst.tolerance_creep_detected else ks.threshold
        dev_str = (
            f"，偏离 {worst.deviation_pct:+.1f}%"
            if worst.deviation_pct is not None and abs(thr) > 1e-9
            else (
                f"，差值 {worst.deviation_pct:+.1f}{ks.unit}"
                if worst.deviation_pct is not None
                else ""
            )
        )
        extra = f"（共 {len(breached)}/{total} 条死线击穿）" if len(breached) > 1 else ""
        return (
            f"当初假设「{ks.name}」已破产（实测 {worst.actual_value:g}{ks.unit} "
            f"vs 死线 {ks.operator}{thr:g}{ks.unit}{dev_str}）{extra}"
        )

    if creeped:
        first = creeped[0]
        ks = first.kill_switch
        return (
            f"检测到死线容忍度被暗中放宽（{ks.name}: {first.original_threshold:g}{ks.unit} "
            f"-> {ks.threshold:g}{ks.unit}）"
        )

    missing = [r for r in report.kill_switch_results if r.missing_data]
    if missing:
        return f"{total - len(missing)}/{total} 条死线达标，{len(missing)} 条缺少最新数据"

    return f"{total}/{total} 条核心死线全部守住"


def _format_valuation_snippet(report: PositionAuditReport) -> str:
    val = report.valuation_result
    if val is None:
        return "无确定性估值底稿"
    if val.current_mos_pct <= 0.0:
        mos_status = "安全边际已彻底消失/高估"
    elif val.current_mos_pct < val.required_mos_pct:
        mos_status = "安全边际不足"
    else:
        mos_status = "安全边际充足"
    return (
        f"重算 {val.model_type} 内在价值 {val.currency} {val.repriced_intrinsic_value:.2f}"
        f"（初值 {val.initial_intrinsic_value:.2f}），"
        f"当前安全边际 {val.current_mos_pct:+.1f}%"
        f"（死线要求 >={val.required_mos_pct:.1f}%，{mos_status}）"
    )


def _format_drift_line(report: PositionAuditReport) -> str:
    drift = report.drift_result
    if report.thesis_card is None:
        return (
            "检测到裸奔仓位：券商持仓无对应 Obsidian 估值卡与 3 条可证伪死线，无法执行逻辑校验。"
        )
    if report.thesis_card.validation_errors:
        return (
            f"逻辑卡结构不合格：{'；'.join(report.thesis_card.validation_errors)}。"
        )

    if not drift.drift_detected:
        return "逻辑一致性核查通过：未检测到信仰漂移或私自放宽死线阈值。"

    tags: List[str] = []
    if drift.style_drift:
        tags.append(f"风格漂移: {drift.style_drift}")
    if drift.tolerance_creep_details:
        tags.append("容忍度松动")
    if drift.rationalization_phrases:
        tags.append(f"自我合理化: {', '.join(drift.rationalization_phrases[:3])}")
    if drift.lock_tampered:
        tags.append("死线锁哈希不匹配")
    drift_tag = " | ".join(tags) if tags else "逻辑漂移"

    excuse_b = drift.excuse_summary or "事后口头新理由"
    failed_a = drift.failed_assumption_summary or "初始核心假设"
    return f"检测到你正试图用「{excuse_b}」掩盖「{failed_a}」的失败（{drift_tag}）。"


def format_caveman_lines(report: PositionAuditReport) -> List[str]:
    """Generate the strict 3-line Caveman telegraphic audit block for one position."""
    pos = report.position
    if report.thesis_card is None:
        line1 = (
            f"[持仓：{pos.symbol} ({pos.name} | 浮盈亏 {pos.unrealized_pnl_pct:+.1f}%)] "
            f"未找到买入存证卡与可证伪死线，仓位占比 {pos.account_weight_pct:.1f}%，处于无纪律裸奔状态。"
        )
    else:
        breach_detail = _format_breach_detail(report)
        val_snippet = _format_valuation_snippet(report)
        line1 = (
            f"[持仓：{pos.symbol} ({pos.name} | 浮盈亏 {pos.unrealized_pnl_pct:+.1f}%)] "
            f"{breach_detail}；{val_snippet}。"
        )

    line2 = _format_drift_line(report)
    line3 = (
        f"建议动作：{report.recommended_action} | "
        f"风险敞口姿态：[{report.posture.value}]（仅供人类决策审查，严禁自动下单）。"
    )
    return [line1, line2, line3]


def format_caveman_report(reports: List[PositionAuditReport]) -> str:
    """Render all position audit reports in ultra-terse Caveman telegraphic mode."""
    blocks = ["\n".join(r.caveman_lines) for r in reports]
    return "\n\n".join(blocks)


def format_markdown_report(reports: List[PositionAuditReport]) -> str:
    """Render a structured Markdown portfolio postmortem report for Obsidian or GitHub."""
    lines: List[str] = [
        "# ThesisBreaker 持仓逻辑证伪与估值复盘报告",
        "",
        "> **Zero-Paid-API Local Audit** | 仅输出供人类审查的风险敞口姿态（Exposure Posture），绝不直接下达交易指令。",
        "",
        "## 1. 组合风险敞口姿态总览",
        "",
        "| 标的 | 浮盈亏 | 仓位占比 | 估值模型 | 初值 -> 重算内在价值 | 当前安全边际 | 逻辑漂移 | 风险敞口姿态 |",
        "| --- | ---: | ---: | :---: | ---: | ---: | :---: | --- |",
    ]

    for r in reports:
        pos = r.position
        val = r.valuation_result
        if val:
            iv_str = f"{val.currency} {val.initial_intrinsic_value:.2f} -> {val.repriced_intrinsic_value:.2f}"
            mos_str = f"{val.current_mos_pct:+.1f}% (底线 {val.required_mos_pct:.0f}%)"
            model_str = val.model_type
        else:
            iv_str = "N/A"
            mos_str = "N/A"
            model_str = "-"
        drift_flag = "YES" if r.drift_result.drift_detected else "NO"
        lines.append(
            f"| **{pos.symbol}** | {pos.unrealized_pnl_pct:+.1f}% | {pos.account_weight_pct:.1f}% "
            f"| {model_str} | {iv_str} | {mos_str} | {drift_flag} | `{r.posture.value}` |"
        )

    lines.extend(["", "## 2. Caveman 极简冷酷三行裁决", ""])
    for r in reports:
        lines.append(f"### {r.position.symbol} ({r.position.name})")
        lines.append("```text")
        lines.extend(r.caveman_lines)
        lines.append("```")
        if r.kill_switch_results:
            lines.append("")
            lines.append("| 死线 ID | 核心假设指标 | 锁定死线 | 最新实测 | 偏离 | 状态 |")
            lines.append("| --- | --- | --- | --- | ---: | :---: |")
            for ksr in r.kill_switch_results:
                ks = ksr.kill_switch
                thr = ksr.original_threshold if ksr.tolerance_creep_detected else ks.threshold
                actual_str = f"{ksr.actual_value:g}{ks.unit}" if ksr.actual_value is not None else "MISSING"
                dev_str = f"{ksr.deviation_pct:+.1f}%" if ksr.deviation_pct is not None else "-"
                if ksr.breached:
                    status = "BREACHED"
                elif ksr.tolerance_creep_detected:
                    status = "CREEP"
                elif ksr.missing_data:
                    status = "MISSING"
                else:
                    status = "PASS"
                lines.append(
                    f"| {ks.id} | {ks.name} | {ks.operator}{thr:g}{ks.unit} | {actual_str} | {dev_str} | **{status}** |"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json_report(reports: List[PositionAuditReport]) -> str:
    """Render full deterministic audit payload as formatted JSON."""
    payload = {
        "schema_version": "0.1.0",
        "disclaimer": "Exposure posture for human review only. Never emits trade execution orders.",
        "summary": {
            "total_positions": len(reports),
            "kill_switch_triggered": sum(
                1 for r in reports if r.posture == ExposurePosture.KILL_SWITCH_TRIGGERED
            ),
            "trim_exposure": sum(
                1 for r in reports if r.posture == ExposurePosture.TRIM_EXPOSURE
            ),
            "watch_warning": sum(
                1 for r in reports if r.posture == ExposurePosture.WATCH_WARNING
            ),
            "untracked_naked": sum(
                1 for r in reports if r.posture == ExposurePosture.UNTRACKED_NAKED_POSITION
            ),
            "hold_conviction": sum(
                1 for r in reports if r.posture == ExposurePosture.HOLD_CONVICTION
            ),
        },
        "positions": [r.to_dict() for r in reports],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
