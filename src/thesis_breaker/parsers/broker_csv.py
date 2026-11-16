"""Broker CSV parser supporting IBKR Flex Query, IBKR Activity Statement, and Longbridge exports."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from thesis_breaker.models import PositionRecord

# Conservative fallback USD FX rates when broker CSV omits FXRateToBase.
_DEFAULT_FX_TO_USD: Dict[str, float] = {
    "USD": 1.0,
    "HKD": 1.0 / 7.78,
    "CNY": 1.0 / 7.20,
    "CNH": 1.0 / 7.20,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 1.0 / 150.0,
    "SGD": 1.0 / 1.34,
}

_FIELD_CANDIDATES: Dict[str, List[str]] = {
    "symbol": [
        "symbol",
        "ticker",
        "underlying symbol",
        "code",
        "股票代码",
        "代码",
    ],
    "name": [
        "description",
        "name",
        "security name",
        "股票名称",
        "名称",
    ],
    "currency": [
        "currencyprimary",
        "currency",
        "curr",
        "币种",
        "货币",
    ],
    "exchange": [
        "listingexchange",
        "exchange",
        "market",
        "交易所",
        "市场",
    ],
    "quantity": [
        "quantity",
        "position",
        "qty",
        "shares",
        "持仓数量",
        "股数",
        "持有数量",
    ],
    "avg_cost": [
        "costbasisprice",
        "openprice",
        "avgcost",
        "averagecost",
        "costprice",
        "cost price",
        "成本价",
        "持仓成本价",
    ],
    "current_price": [
        "markprice",
        "closeprice",
        "lastprice",
        "last price",
        "currentprice",
        "现价",
        "最新价",
        "市价",
    ],
    "market_value": [
        "positionvalue",
        "marketvalue",
        "market value",
        "value",
        "市值",
    ],
    "unrealized_pnl": [
        "fifopnlunrealized",
        "unrealizedpnl",
        "unrealized p&l",
        "unrealizedpnlbase",
        "未实现盈亏",
        "浮动盈亏",
    ],
    "first_buy_date": [
        "firstbuydate",
        "opendatetime",
        "reportdate",
        "entrydate",
        "买入日期",
    ],
    "asset_class": [
        "assetclass",
        "asset category",
        "资产类别",
    ],
    "fx_rate": [
        "fxratetobase",
        "fxrate",
        "exchangerate",
        "汇率",
    ],
}


def _clean_header(name: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", name.strip().lower())


def _parse_float(raw: Optional[str], default: float = 0.0) -> float:
    if raw is None:
        return default
    cleaned = raw.strip().replace(",", "").replace("$", "").replace("HK$", "").replace("%", "")
    if cleaned in ("", "-", "--", "N/A", "null"):
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def normalize_symbol(symbol: str, exchange: str = "", currency: str = "") -> str:
    """Normalize US and HK equity tickers into canonical format.

    Examples:
      - '9988', exchange='SEHK' -> '9988.HK'
      - 'SEHK:700' -> '0700.HK'
      - '09988.HK' -> '9988.HK'
      - '00700.HK' -> '0700.HK'
      - 'NASDAQ:MU' -> 'MU'
    """
    raw = symbol.strip().upper()
    exch = exchange.strip().upper()
    curr = currency.strip().upper()

    if ":" in raw:
        prefix, code = raw.split(":", 1)
        if prefix in ("SEHK", "HKEX", "HK", "HKG"):
            exch = "SEHK"
        raw = code.strip()

    if raw.endswith(".HK"):
        code_part = raw[:-3]
        if code_part.isdigit():
            trimmed = str(int(code_part))
            return f"{trimmed.zfill(4)}.HK"
        return raw

    if raw.isdigit() and (exch in ("SEHK", "HKEX", "HK", "HKG") or curr == "HKD"):
        trimmed = str(int(raw))
        return f"{trimmed.zfill(4)}.HK"

    return raw


def _find_col_index(headers: List[str], field: str) -> Optional[int]:
    cleaned_headers = [_clean_header(h) for h in headers]
    candidates = [_clean_header(c) for c in _FIELD_CANDIDATES[field]]
    for cand in candidates:
        for idx, h in enumerate(cleaned_headers):
            if h == cand:
                return idx
    return None


def _extract_row_dict(headers: List[str], row: List[str]) -> Dict[str, str]:
    extracted: Dict[str, str] = {}
    for field in _FIELD_CANDIDATES:
        idx = _find_col_index(headers, field)
        if idx is not None and idx < len(row):
            extracted[field] = row[idx].strip()
    return extracted


def _row_to_position(fields: Dict[str, str], broker_source: str) -> Optional[PositionRecord]:
    raw_symbol = fields.get("symbol", "").strip()
    if not raw_symbol:
        return None

    asset_class = fields.get("asset_class", "").upper()
    if asset_class and asset_class not in ("STK", "EQUITY", "STOCK", "STOCKS", "股票", ""):
        return None

    qty = _parse_float(fields.get("quantity"))
    if qty == 0.0:
        return None

    currency = (fields.get("currency") or "USD").upper()
    exchange = fields.get("exchange", "")
    symbol = normalize_symbol(raw_symbol, exchange=exchange, currency=currency)
    if symbol.endswith(".HK") and not fields.get("currency"):
        currency = "HKD"

    avg_cost = _parse_float(fields.get("avg_cost"))
    current_price = _parse_float(fields.get("current_price"))
    market_value = _parse_float(fields.get("market_value"))
    raw_pnl = fields.get("unrealized_pnl")
    has_explicit_pnl = raw_pnl is not None and raw_pnl.strip() not in (
        "",
        "-",
        "--",
        "N/A",
        "null",
    )
    explicit_pnl = _parse_float(raw_pnl) if has_explicit_pnl else 0.0

    if current_price <= 0.0:
        if market_value != 0.0 and abs(qty) > 1e-9:
            current_price = abs(market_value) / abs(qty)
        elif avg_cost > 0.0 and has_explicit_pnl and abs(qty) > 1e-9:
            implied_mv = qty * avg_cost + explicit_pnl
            if implied_mv / qty > 0.0:
                current_price = implied_mv / qty
                market_value = implied_mv

    if market_value == 0.0 and current_price > 0.0:
        market_value = qty * current_price

    cost_basis_total = qty * avg_cost
    if has_explicit_pnl:
        unrealized_pnl = explicit_pnl
    elif avg_cost > 0 and current_price > 0:
        unrealized_pnl = (current_price - avg_cost) * qty
    else:
        unrealized_pnl = 0.0

    if cost_basis_total != 0.0:
        unrealized_pnl_pct = (unrealized_pnl / abs(cost_basis_total)) * 100.0
    elif avg_cost > 0 and current_price > 0:
        unrealized_pnl_pct = ((current_price - avg_cost) / avg_cost) * 100.0
    else:
        unrealized_pnl_pct = 0.0

    return PositionRecord(
        symbol=symbol,
        name=fields.get("name", "") or symbol,
        currency=currency,
        quantity=qty,
        avg_cost=avg_cost,
        current_price=current_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        first_buy_date=fields.get("first_buy_date", ""),
        broker_source=broker_source,
    )


def _assign_account_weights(
    positions: List[PositionRecord], fx_rates: Optional[List[float]] = None
) -> None:
    """Compute account_weight_pct using USD-equivalent market value across currencies."""
    usd_values: List[float] = []
    for idx, pos in enumerate(positions):
        explicit_fx = fx_rates[idx] if fx_rates and idx < len(fx_rates) else 0.0
        rate = explicit_fx if explicit_fx > 0 else _DEFAULT_FX_TO_USD.get(pos.currency, 1.0)
        usd_values.append(abs(pos.market_value) * rate)

    total_abs_usd = sum(usd_values)
    if total_abs_usd <= 0:
        return
    for pos, usd_mv in zip(positions, usd_values):
        pos.account_weight_pct = round((usd_mv / total_abs_usd) * 100.0, 2)


def _extract_fx_rate(fields: Dict[str, str]) -> float:
    return _parse_float(fields.get("fx_rate"), default=0.0)


def _parse_ibkr_activity_rows(
    rows: List[List[str]],
) -> Tuple[List[PositionRecord], List[float]]:
    positions: List[PositionRecord] = []
    fx_rates: List[float] = []
    open_pos_headers: Optional[List[str]] = None

    for row in rows:
        if len(row) < 3:
            continue
        section = row[0].strip().lower()
        row_type = row[1].strip().lower()
        if section not in ("openpositions", "open positions"):
            continue
        if row_type == "header":
            open_pos_headers = row[2:]
        elif row_type == "data" and open_pos_headers is not None:
            payload = row[2:]
            # IBKR Activity Statement sometimes includes DataDiscriminator column ("Summary", "Lot")
            fields = _extract_row_dict(open_pos_headers, payload)
            discriminator_idx = None
            for i, h in enumerate(open_pos_headers):
                if _clean_header(h) == "datadiscriminator":
                    discriminator_idx = i
                    break
            if discriminator_idx is not None and discriminator_idx < len(payload):
                disc_val = payload[discriminator_idx].strip().lower()
                if disc_val not in ("summary", ""):
                    continue
            pos = _row_to_position(fields, broker_source="IBKR_ACTIVITY")
            if pos is not None:
                positions.append(pos)
                fx_rates.append(_extract_fx_rate(fields))

    return positions, fx_rates


def _detect_broker_source(headers: List[str]) -> str:
    joined = " ".join(headers).lower()
    if any(tok in joined for tok in ("持仓数量", "股票代码", "longbridge")):
        return "Longbridge"
    return "IBKR_FLEX"


def _merge_duplicate_positions(
    positions: List[PositionRecord], fx_rates: List[float]
) -> Tuple[List[PositionRecord], List[float]]:
    """Consolidate multi-lot or multi-subaccount rows sharing (symbol, currency)."""
    merged_map: Dict[Tuple[str, str], PositionRecord] = {}
    cost_totals: Dict[Tuple[str, str], float] = {}
    fx_map: Dict[Tuple[str, str], float] = {}

    for idx, pos in enumerate(positions):
        key = (pos.symbol, pos.currency)
        fx = fx_rates[idx] if idx < len(fx_rates) else 0.0
        if key not in merged_map:
            merged_map[key] = PositionRecord(
                symbol=pos.symbol,
                name=pos.name,
                currency=pos.currency,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                current_price=pos.current_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=pos.unrealized_pnl_pct,
                first_buy_date=pos.first_buy_date,
                broker_source=pos.broker_source,
            )
            cost_totals[key] = pos.quantity * pos.avg_cost
            fx_map[key] = fx
            continue

        existing = merged_map[key]
        existing.quantity += pos.quantity
        cost_totals[key] += pos.quantity * pos.avg_cost
        existing.market_value += pos.market_value
        existing.unrealized_pnl += pos.unrealized_pnl
        if abs(existing.quantity) > 1e-9:
            existing.avg_cost = cost_totals[key] / existing.quantity
            if existing.market_value != 0.0:
                existing.current_price = existing.market_value / existing.quantity
        if abs(cost_totals[key]) > 1e-9:
            existing.unrealized_pnl_pct = (
                existing.unrealized_pnl / abs(cost_totals[key])
            ) * 100.0
        if pos.first_buy_date and (
            not existing.first_buy_date or pos.first_buy_date < existing.first_buy_date
        ):
            existing.first_buy_date = pos.first_buy_date
        if fx > 0 and fx_map[key] <= 0:
            fx_map[key] = fx

    final_positions: List[PositionRecord] = []
    final_fx: List[float] = []
    for key, pos in merged_map.items():
        if abs(pos.quantity) <= 1e-9:
            continue
        final_positions.append(pos)
        final_fx.append(fx_map[key])
    return final_positions, final_fx


def parse_broker_csv(csv_path: Union[str, Path]) -> List[PositionRecord]:
    """Parse IBKR Flex Query, IBKR Activity Statement, or Longbridge CSV into PositionRecords."""
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]

    if not rows:
        return []

    # Check if multi-section IBKR Activity Statement format
    is_activity_statement = any(
        len(r) >= 2 and r[0].strip().lower() in ("statement", "openpositions", "open positions")
        and r[1].strip().lower() in ("header", "data")
        for r in rows[:25]
    )

    if is_activity_statement:
        positions, fx_rates = _parse_ibkr_activity_rows(rows)
        positions, fx_rates = _merge_duplicate_positions(positions, fx_rates)
        _assign_account_weights(positions, fx_rates)
        return positions

    headers = rows[0]
    broker_source = _detect_broker_source(headers)
    positions = []
    fx_rates = []
    for row in rows[1:]:
        fields = _extract_row_dict(headers, row)
        pos = _row_to_position(fields, broker_source=broker_source)
        if pos is not None:
            positions.append(pos)
            fx_rates.append(_extract_fx_rate(fields))

    positions, fx_rates = _merge_duplicate_positions(positions, fx_rates)
    _assign_account_weights(positions, fx_rates)
    return positions
