"""Deterministic valuation, thesis-lock, and drift auditing engine."""

from __future__ import annotations

from thesis_breaker.engine.auditor import audit_portfolio, audit_position, evaluate_kill_switch
from thesis_breaker.engine.thesis_lock import (
    compute_thesis_lock_hash,
    is_threshold_relaxed,
    verify_thesis_lock,
)
from thesis_breaker.engine.valuation import compute_fcfe, compute_sotp, reprice_valuation

__all__ = [
    "audit_portfolio",
    "audit_position",
    "compute_fcfe",
    "compute_sotp",
    "compute_thesis_lock_hash",
    "evaluate_kill_switch",
    "is_threshold_relaxed",
    "reprice_valuation",
    "verify_thesis_lock",
]
