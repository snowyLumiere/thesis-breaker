"""Tests for deterministic SOTP and FCFE valuation & repricing math."""

from __future__ import annotations

import unittest

from thesis_breaker.engine.valuation import compute_fcfe, compute_sotp
from thesis_breaker.models import (
    KillSwitch,
    KillSwitchResult,
    SOTPSegment,
    ValuationConfig,
)


class TestValuationEngine(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
