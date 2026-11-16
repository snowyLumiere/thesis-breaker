"""Core data models for ThesisBreaker."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExposurePosture(str, Enum):
    """Risk exposure posture emitted for human review (never direct trade execution)."""

    HOLD_CONVICTION = "HOLD_CONVICTION"
    WATCH_WARNING = "WATCH_WARNING"
    TRIM_EXPOSURE = "TRIM_EXPOSURE"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    UNTRACKED_NAKED_POSITION = "UNTRACKED_NAKED_POSITION"


@dataclass
class PositionRecord:
    """Normalized open position parsed from IBKR Flex Query or Longbridge CSV."""

    symbol: str
    name: str
    currency: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    first_buy_date: str = ""
    account_weight_pct: float = 0.0
    broker_source: str = "IBKR"


@dataclass
class KillSwitch:
    """A single falsifiable numerical kill-switch registered at entry time."""

    id: str
    name: str
    metric_key: str
    operator: str
    threshold: float
    unit: str = ""
    haircut_pct: float = 0.0
    locked_threshold: Optional[float] = None
    critical: bool = False
    aliases: List[str] = field(default_factory=list)


@dataclass
class SOTPSegment:
    """Single business segment for Sum-Of-The-Parts (SOTP) valuation."""

    name: str
    metric_value: float
    multiple: float
    ownership_pct: float = 100.0
    metric_key: Optional[str] = None
    multiple_key: Optional[str] = None


@dataclass
class ValuationConfig:
    """Deterministic valuation parameters for SOTP or FCFE models."""

    model_type: str  # "SOTP" or "FCFE"
    currency: str
    diluted_shares: float
    net_cash: float = 0.0
    required_mos_pct: float = 20.0
    segments: List[SOTPSegment] = field(default_factory=list)
    base_fcfe_per_share: float = 0.0
    growth_rate_pct: float = 0.0
    terminal_growth_pct: float = 2.5
    cost_of_equity_pct: float = 10.0
    projection_years: int = 5


@dataclass
class ThesisCard:
    """Obsidian Markdown investment thesis card with locked falsifiable assumptions."""

    symbol: str
    name: str
    entry_date: str
    entry_price: float
    initial_strategy_type: str
    current_claimed_style: str
    core_thesis_summary: str
    kill_switches: List[KillSwitch]
    valuation: Optional[ValuationConfig]
    latest_actuals: Dict[str, float] = field(default_factory=dict)
    latest_review_notes: str = ""
    thesis_lock_sha256: Optional[str] = None
    source_path: str = ""
    symbol_aliases: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)


@dataclass
class KillSwitchResult:
    """Evaluation result of one falsifiable kill-switch against latest actual data."""

    kill_switch: KillSwitch
    actual_value: Optional[float]
    breached: bool
    deviation_pct: Optional[float]
    tolerance_creep_detected: bool = False
    original_threshold: Optional[float] = None
    missing_data: bool = False


@dataclass
class ValuationResult:
    """Deterministic valuation comparison between initial thesis and repriced reality."""

    model_type: str
    currency: str
    initial_intrinsic_value: float
    repriced_intrinsic_value: float
    valuation_change_pct: float
    current_price: float
    initial_mos_pct: Optional[float]
    current_mos_pct: Optional[float]
    required_mos_pct: float
    mos_vanished: bool
    total_haircut_applied_pct: float
    notes: List[str] = field(default_factory=list)


@dataclass
class DriftAuditResult:
    """Audit result for thesis drift, style shift, and silent threshold relaxation."""

    drift_detected: bool
    style_drift: Optional[str] = None
    tolerance_creep_details: List[str] = field(default_factory=list)
    rationalization_phrases: List[str] = field(default_factory=list)
    excuse_summary: Optional[str] = None
    failed_assumption_summary: Optional[str] = None
    lock_tampered: bool = False


@dataclass
class PositionAuditReport:
    """Complete deterministic audit report for a single equity position."""

    position: PositionRecord
    thesis_card: Optional[ThesisCard]
    kill_switch_results: List[KillSwitchResult]
    valuation_result: Optional[ValuationResult]
    drift_result: DriftAuditResult
    posture: ExposurePosture
    recommended_action: str
    caveman_lines: List[str]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit report into a JSON-serializable dictionary."""
        data = asdict(self)
        data["posture"] = self.posture.value
        return data


def select_worst_breach(breached: List[KillSwitchResult]) -> KillSwitchResult:
    """Select the primary breached kill-switch prioritizing critical switches and largest |deviation|."""
    return min(
        breached,
        key=lambda r: (
            not r.kill_switch.critical,
            -abs(r.deviation_pct if r.deviation_pct is not None else 0.0),
        ),
    )
