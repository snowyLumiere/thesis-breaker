"""Tests for kill-switch evaluation, Tolerance Creep, Thesis Drift, and Caveman output."""

from __future__ import annotations

import unittest
from pathlib import Path

from thesis_breaker.engine.auditor import audit_portfolio, audit_position
from thesis_breaker.engine.thesis_lock import compute_thesis_lock_hash, verify_thesis_lock
from thesis_breaker.models import (
    ExposurePosture,
    KillSwitch,
    KillSwitchResult,
    PositionRecord,
    select_worst_breach,
)
from thesis_breaker.parsers.broker_csv import parse_broker_csv
from thesis_breaker.parsers.obsidian_thesis import load_thesis_cards


class TestAuditorAndDrift(unittest.TestCase):
    def setUp(self) -> None:
        base = Path(__file__).resolve().parents[1] / "examples"
        self.positions = parse_broker_csv(base / "ibkr_flex_positions.csv")
        self.cards = load_thesis_cards(base / "obsidian_vault")
        self.reports = {
            r.position.symbol: r for r in audit_portfolio(self.positions, self.cards)
        }

    def test_micron_catches_breach_and_style_drift(self) -> None:
        mu = self.reports["MU"]
        self.assertEqual(mu.posture, ExposurePosture.KILL_SWITCH_TRIGGERED)
        self.assertTrue(mu.drift_result.drift_detected)
        self.assertIsNotNone(mu.drift_result.style_drift)
        self.assertIn("基本面波段", mu.drift_result.style_drift)
        self.assertLess(mu.valuation_result.current_mos_pct, 0.0)
        self.assertEqual(len(mu.caveman_lines), 3)
        self.assertIn("KILL_SWITCH_TRIGGERED", mu.caveman_lines[2])

    def test_alibaba_catches_tolerance_creep(self) -> None:
        baba = self.reports["9988.HK"]
        self.assertTrue(baba.drift_result.tolerance_creep_details)
        self.assertIn("10% -> 4%", baba.drift_result.tolerance_creep_details[0])
        self.assertIn("4.2%", baba.drift_result.excuse_summary or "")
        self.assertTrue(baba.kill_switch_results[0].breached)
        self.assertEqual(baba.posture, ExposurePosture.KILL_SWITCH_TRIGGERED)
        self.assertEqual(len(baba.caveman_lines), 3)

    def test_tencent_holds_conviction(self) -> None:
        tcehy = self.reports["0700.HK"]
        self.assertEqual(tcehy.posture, ExposurePosture.HOLD_CONVICTION)
        self.assertFalse(tcehy.drift_result.drift_detected)
        self.assertGreater(tcehy.valuation_result.current_mos_pct, 20.0)
        self.assertEqual(len(tcehy.caveman_lines), 3)

    def test_smci_naked_position_caught(self) -> None:
        smci = self.reports["SMCI"]
        self.assertEqual(smci.posture, ExposurePosture.UNTRACKED_NAKED_POSITION)
        self.assertIsNone(smci.thesis_card)
        self.assertIn("裸奔", smci.caveman_lines[0])

    def test_thesis_lock_detects_tampering(self) -> None:
        card = self.cards["0700.HK"]
        card.thesis_lock_sha256 = compute_thesis_lock_hash(card)
        ok, _ = verify_thesis_lock(card)
        self.assertTrue(ok)
        # Tamper with threshold silently
        card.kill_switches[0].threshold = 2.0
        ok2, reason = verify_thesis_lock(card)
        self.assertFalse(ok2)
        self.assertIn("篡改", reason)

        pos = PositionRecord(
            symbol="0700.HK",
            name="Tencent",
            currency="HKD",
            quantity=100,
            avg_cost=400,
            current_price=350,
            market_value=35000,
            unrealized_pnl=-5000,
            unrealized_pnl_pct=-12.5,
        )
        rep = audit_position(pos, card)
        self.assertTrue(rep.drift_result.lock_tampered)

        # Restore threshold, then tamper with haircut_pct -> lock must still detect tampering!
        card.kill_switches[0].threshold = 8.0
        ok_restored, _ = verify_thesis_lock(card)
        self.assertTrue(ok_restored)
        card.kill_switches[0].haircut_pct = 0.0
        ok_haircut, _ = verify_thesis_lock(card)
        self.assertFalse(ok_haircut)

    def test_select_worst_breach_handles_upper_bounds_and_critical(self) -> None:
        ks_floor = KillSwitch(
            id="KS-1",
            name="Margin Floor",
            metric_key="m",
            operator=">=",
            threshold=40.0,
            critical=False,
        )
        ks_ceiling = KillSwitch(
            id="KS-2",
            name="Leverage Ceiling",
            metric_key="lev",
            operator="<=",
            threshold=2.0,
            critical=False,
        )
        ks_crit = KillSwitch(
            id="KS-3",
            name="Critical Yield",
            metric_key="y",
            operator=">=",
            threshold=75.0,
            critical=True,
        )
        r1 = KillSwitchResult(ks_floor, actual_value=36.0, breached=True, deviation_pct=-10.0)
        r2 = KillSwitchResult(ks_ceiling, actual_value=3.0, breached=True, deviation_pct=50.0)
        # Upper-bound breach with larger |deviation_pct| (50% > 10%) wins when neither is critical
        self.assertEqual(select_worst_breach([r1, r2]).kill_switch.id, "KS-2")

        r3 = KillSwitchResult(ks_crit, actual_value=70.0, breached=True, deviation_pct=-6.67)
        # Critical kill-switch always takes priority
        self.assertEqual(select_worst_breach([r1, r2, r3]).kill_switch.id, "KS-3")


if __name__ == "__main__":
    unittest.main()
