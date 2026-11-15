"""Cryptographic thesis lock and Tolerance Creep detection."""

from __future__ import annotations

import hashlib
import json
from typing import Tuple

from thesis_breaker.models import KillSwitch, ThesisCard


def compute_thesis_lock_hash(card: ThesisCard, use_locked_thresholds: bool = False) -> str:
    """Compute a deterministic SHA-256 fingerprint over strategy, MOS floor, and kill-switches."""
    required_mos = round(card.valuation.required_mos_pct, 6) if card.valuation else 0.0
    payload = {
        "symbol": card.symbol,
        "initial_strategy_type": card.initial_strategy_type,
        "required_mos_pct": required_mos,
        "kill_switches": [
            {
                "id": ks.id,
                "metric_key": ks.metric_key,
                "operator": ks.operator,
                "threshold": round(
                    ks.locked_threshold
                    if (use_locked_thresholds and ks.locked_threshold is not None)
                    else ks.threshold,
                    6,
                ),
                "haircut_pct": round(ks.haircut_pct, 6),
                "critical": bool(ks.critical),
            }
            for ks in card.kill_switches
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_threshold_relaxed(ks: KillSwitch) -> bool:
    """Detect whether current kill-switch threshold was silently relaxed vs locked_threshold.

    - For minimum floors ('>=' or '>'): lowering the threshold relaxes the standard.
    - For maximum ceilings ('<=' or '<'): raising the threshold relaxes the standard.
    - For exact equality ('=='): any change flags modification.
    """
    if ks.locked_threshold is None:
        return False
    op = ks.operator.strip()
    if op in (">=", ">"):
        return ks.threshold < ks.locked_threshold - 1e-9
    if op in ("<=", "<"):
        return ks.threshold > ks.locked_threshold + 1e-9
    return abs(ks.threshold - ks.locked_threshold) > 1e-9


def verify_thesis_lock(card: ThesisCard) -> Tuple[bool, str]:
    """Verify whether the ThesisCard matches its stored thesis_lock_sha256.

    Returns (is_valid, reason). If no lock hash is present, returns (True, "unlocked").
    """
    if not card.thesis_lock_sha256:
        return True, "unlocked"
    current_hash = compute_thesis_lock_hash(card, use_locked_thresholds=False)
    if current_hash == card.thesis_lock_sha256:
        return True, "verified"
    return False, (
        f"死线锁哈希校验失败（当前 {current_hash[:10]} != 锁定 {card.thesis_lock_sha256[:10]}），"
        "初始策略或死线阈值被事后篡改"
    )
