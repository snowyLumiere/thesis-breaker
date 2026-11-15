"""Tests for IBKR Flex, IBKR Activity Statement, and Longbridge CSV parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from thesis_breaker.parsers.broker_csv import normalize_symbol, parse_broker_csv


class TestBrokerCsvParser(unittest.TestCase):
    def test_normalize_symbol_us_and_hk(self) -> None:
        self.assertEqual(normalize_symbol("NASDAQ:MU"), "MU")
        self.assertEqual(normalize_symbol("9988", exchange="SEHK", currency="HKD"), "9988.HK")
        self.assertEqual(normalize_symbol("700", exchange="SEHK", currency="HKD"), "0700.HK")
        self.assertEqual(normalize_symbol("00700.HK"), "0700.HK")
        self.assertEqual(normalize_symbol("SEHK:9988"), "9988.HK")

    def test_parse_ibkr_flex_example(self) -> None:
        csv_path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "ibkr_flex_positions.csv"
        )
        positions = parse_broker_csv(csv_path)
        by_sym = {p.symbol: p for p in positions}
        self.assertEqual(set(by_sym.keys()), {"MU", "9988.HK", "0700.HK", "SMCI"})
        self.assertAlmostEqual(by_sym["MU"].unrealized_pnl_pct, -16.44, places=2)
        self.assertEqual(by_sym["9988.HK"].currency, "HKD")
        # Multi-currency FX-normalized weights: MU ($29,580) is ~35%, SMCI ($6,480) is ~7.7%
        self.assertAlmostEqual(by_sym["MU"].account_weight_pct, 35.02, places=1)
        self.assertAlmostEqual(by_sym["SMCI"].account_weight_pct, 7.67, places=1)
        self.assertAlmostEqual(sum(p.account_weight_pct for p in positions), 100.0, places=1)

    def test_parse_ibkr_activity_statement_and_longbridge(self) -> None:
        activity_csv = (
            "Statement,Header,Field Name,Field Value\n"
            "OpenPositions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Cost Price,Close Price,Value,Unrealized P/L\n"
            "OpenPositions,Data,Summary,Stocks,HKD,700,500,350,420,210000,35000\n"
            "OpenPositions,Data,Lot,Stocks,HKD,700,500,350,420,210000,35000\n"
            "OpenPositions,Data,Summary,Stocks,USD,MU,0,100,110,0,0\n"
        )
        longbridge_csv = (
            "股票代码,股票名称,币种,持仓数量,成本价,现价\n"
            "9988.HK,阿里巴巴,HKD,1000,100,85\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "activity.csv"
            p1.write_text(activity_csv, encoding="utf-8")
            pos1 = parse_broker_csv(p1)
            self.assertEqual(len(pos1), 1)
            self.assertEqual(pos1[0].symbol, "0700.HK")
            self.assertAlmostEqual(pos1[0].unrealized_pnl_pct, 20.0, places=2)

            p2 = Path(tmp) / "lb.csv"
            p2.write_text(longbridge_csv, encoding="utf-8")
            pos2 = parse_broker_csv(p2)
            self.assertEqual(len(pos2), 1)
            self.assertEqual(pos2[0].symbol, "9988.HK")
            self.assertEqual(pos2[0].broker_source, "Longbridge")
            self.assertAlmostEqual(pos2[0].unrealized_pnl_pct, -15.0, places=2)

    def test_merge_duplicate_subaccount_lots(self) -> None:
        multi_lot_csv = (
            "Symbol,Currency,Quantity,CostBasisPrice,MarkPrice,PositionValue,FifoPnlUnrealized,OpenDateTime\n"
            "MU,USD,100,100.0,90.0,9000.0,-1000.0,2026-07-01\n"
            "MU,USD,200,127.0,90.0,18000.0,-7400.0,2026-06-01\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "lots.csv"
            p.write_text(multi_lot_csv, encoding="utf-8")
            positions = parse_broker_csv(p)
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0].quantity, 300.0)
            self.assertAlmostEqual(positions[0].avg_cost, 118.0, places=2)
            self.assertAlmostEqual(positions[0].unrealized_pnl, -8400.0, places=2)
            self.assertEqual(positions[0].first_buy_date, "2026-06-01")


if __name__ == "__main__":
    unittest.main()
