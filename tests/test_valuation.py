"""Tests for deterministic SOTP and FCFE valuation & repricing math."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from thesis_breaker.engine.auditor import audit_position
from thesis_breaker.engine.valuation import compute_fcfe, compute_sotp
from thesis_breaker.models import (
    ExposurePosture,
    KillSwitch,
    KillSwitchResult,
    PositionRecord,
    SOTPSegment,
    ValuationConfig,
)
from thesis_breaker.parsers.obsidian_thesis import parse_thesis_card


class TestValuationEngine(unittest.TestCase):
    def test_nonfinite_inputs_and_overflowed_results_are_rejected(self) -> None:
        cfg = ValuationConfig(
            model_type="FCFE", currency="USD", diluted_shares=1,
            base_fcfe_per_share=20, growth_rate_pct=10,
        )
        for invalid in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "finite"):
                    compute_fcfe(cfg, [], {"base_fcfe_per_share": invalid}, 100, 100)
                with self.assertRaisesRegex(ValueError, "finite"):
                    compute_fcfe(replace(cfg, required_mos_pct=invalid), [], {}, 100, 100)
        with self.assertRaisesRegex(ValueError, "finite"):
            compute_fcfe(replace(cfg, base_fcfe_per_share=1e308), [], {}, 100, 100)
        sotp = ValuationConfig(
            model_type="SOTP", currency="USD", diluted_shares=1,
            segments=[SOTPSegment(name="Core", metric_value=1e308, multiple=10)],
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            compute_sotp(sotp, [], {}, 100, 100)

    def test_sotp_repricing_with_segment_update_and_haircut(self) -> None:
        cfg = ValuationConfig(
            model_type="SOTP",
            currency="USD",
            diluted_shares=1.0,
            net_cash=10.0,
            required_mos_pct=25.0,
            segments=[
                SOTPSegment(
                    name="Core",
                    metric_value=10.0,
                    multiple=10.0,
                    ownership_pct=100.0,
                    metric_key="core_ebitda",
                )
            ],
        )
        # Initial IV = (10 * 10 + 10) / 1 = 110.0
        ks = KillSwitch(
            id="KS-1",
            name="Margin",
            metric_key="margin_pct",
            operator=">=",
            threshold=30.0,
            haircut_pct=20.0,
        )
        ksr = [
            KillSwitchResult(
                kill_switch=ks,
                actual_value=24.0,
                breached=True,
                deviation_pct=-20.0,
            )
        ]
        # Repriced segment metric drops to 8.0 -> pre_haircut IV = (8 * 10 + 10) = 90.0
        # Minus 20% haircut -> 72.0
        res = compute_sotp(
            config=cfg,
            kill_switch_results=ksr,
            actuals={"core_ebitda": 8.0},
            entry_price=80.0,
            current_price=90.0,
        )
        self.assertEqual(res.initial_intrinsic_value, 110.0)
        self.assertEqual(res.repriced_intrinsic_value, 72.0)
        self.assertLess(res.current_mos_pct, 0.0)
        self.assertTrue(res.mos_vanished)
        self.assertEqual(res.total_haircut_applied_pct, 20.0)

    def test_fcfe_two_stage_valuation(self) -> None:
        cfg = ValuationConfig(
            model_type="FCFE",
            currency="HKD",
            diluted_shares=10.0,
            net_cash=50.0,  # +5.0 per share
            required_mos_pct=20.0,
            base_fcfe_per_share=20.0,
            growth_rate_pct=10.0,
            terminal_growth_pct=3.0,
            cost_of_equity_pct=10.0,
            projection_years=5,
        )
        res = compute_fcfe(
            config=cfg,
            kill_switch_results=[],
            actuals={},
            entry_price=300.0,
            current_price=300.0,
        )
        # Explicit PV when g == ke == 10%: 5 * 20 = 100
        # Year 5 FCFE = 20 * 1.1^5 = 32.2102
        # TV = 32.2102 * 1.03 / 0.07 = 473.9501 -> PV(TV) = 473.9501 / 1.1^5 = 294.2857
        # Total = 100 + 294.2857 + 5 = 399.29
        self.assertAlmostEqual(res.initial_intrinsic_value, 399.29, places=1)
        self.assertAlmostEqual(res.repriced_intrinsic_value, 399.29, places=1)
        self.assertFalse(res.mos_vanished)

    def test_fcfe_narrow_terminal_spread_not_clamped(self) -> None:
        cfg = ValuationConfig(
            model_type="FCFE",
            currency="USD",
            diluted_shares=1.0,
            net_cash=0.0,
            required_mos_pct=20.0,
            base_fcfe_per_share=1.0,
            growth_rate_pct=0.0,
            terminal_growth_pct=9.0,
            cost_of_equity_pct=9.5,
            projection_years=1,
        )
        res = compute_fcfe(
            config=cfg,
            kill_switch_results=[],
            actuals={},
            entry_price=100.0,
            current_price=100.0,
        )
        # (1.0 + 1.09 / 0.005) / 1.095 = 219.0 / 1.095 = 200.00
        self.assertEqual(res.initial_intrinsic_value, 200.00)
        self.assertEqual(res.repriced_intrinsic_value, 200.00)

    def test_fcfe_rejects_gt_gte_ke(self) -> None:
        for bad_gt in (9.5, 10.0):
            cfg = ValuationConfig(
                model_type="FCFE",
                currency="USD",
                diluted_shares=1.0,
                base_fcfe_per_share=1.0,
                growth_rate_pct=5.0,
                terminal_growth_pct=bad_gt,
                cost_of_equity_pct=9.5,
                projection_years=5,
            )
            with self.assertRaises(ValueError):
                compute_fcfe(
                    config=cfg,
                    kill_switch_results=[],
                    actuals={},
                    entry_price=50.0,
                    current_price=50.0,
                )

        bad_note = """---
symbol: "BAD"
name: "Bad FCFE"
entry_date: "2026-01-01"
entry_price: 50.0
initial_strategy_type: "compounder_fcfe"
kill_switches:
  - id: KS-1
    name: "K1"
    metric_key: k1
    operator: ">="
    threshold: 10.0
    unit: "%"
  - id: KS-2
    name: "K2"
    metric_key: k2
    operator: ">="
    threshold: 10.0
    unit: "%"
  - id: KS-3
    name: "K3"
    metric_key: k3
    operator: ">="
    threshold: 10.0
    unit: "%"
valuation:
  model_type: "FCFE"
  currency: "USD"
  diluted_shares: 1.0
  base_fcfe_per_share: 1.0
  growth_rate_pct: 5.0
  terminal_growth_pct: 10.0
  cost_of_equity_pct: 9.5
  projection_years: 5
latest_actuals:
  k1: 12.0
  k2: 12.0
  k3: 12.0
---
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "BAD.md"
            p.write_text(bad_note, encoding="utf-8")
            card = parse_thesis_card(p)
            self.assertIsNotNone(card)
            self.assertTrue(card.validation_errors)
            pos = PositionRecord(
                symbol="BAD",
                name="Bad FCFE",
                currency="USD",
                quantity=10,
                avg_cost=50.0,
                current_price=50.0,
                market_value=500.0,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
            )
            rep = audit_position(pos, card)
            self.assertEqual(rep.posture, ExposurePosture.UNTRACKED_NAKED_POSITION)


if __name__ == "__main__":
    unittest.main()
