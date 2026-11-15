---
symbol: 0700.HK
name: "Tencent Holdings"
entry_date: 2025-11-04
entry_price: 345.0
initial_strategy_type: compounder_fcfe
current_claimed_style: compounder_fcfe
thesis_lock_sha256: 80556f5ffec67854924051bdbfa4eeaa4f8a524d4c5d811bd23b9aa23b5d5c3f
kill_switches:
  - id: KS-1
    name: "本土及海外游戏收入 YoY"
    metric_key: game_rev_yoy_pct
    operator: >=
    threshold: 8.0
    locked_threshold: 8.0
    unit: %
    haircut_pct: 15.0
    critical: false
  - id: KS-2
    name: 综合毛利率
    metric_key: gross_margin_pct
    operator: >=
    threshold: 50.0
    locked_threshold: 50.0
    unit: %
    haircut_pct: 12.0
    critical: false
  - id: KS-3
    name: 稀释总股本同比变动（持续净注销）
    metric_key: share_count_change_pct
    operator: <=
    threshold: -1.0
    locked_threshold: -1.0
    unit: %
    haircut_pct: 10.0
    critical: false
valuation:
  model_type: FCFE
  currency: HKD
  diluted_shares: 9.25
  net_cash: 110.0
  required_mos_pct: 20.0
  base_fcfe_per_share: 22.5
  growth_rate_pct: 11.0
  terminal_growth_pct: 3.0
  cost_of_equity_pct: 9.5
  projection_years: 5
latest_actuals:
  game_rev_yoy_pct: 12.6
  gross_margin_pct: 53.4
  share_count_change_pct: -2.4
  base_fcfe_per_share: 24.2
---

## Core Thesis
现金流复利核心底仓：以视频号高毛利广告 + 长青游戏现金流 + 净注销回购构建 11% FCFE 复利，要求至少 20% 安全边际。

## Review Notes
最新季度游戏收入同比增长 12.6%，毛利率提升至 53.4%，股本同比净注销 2.4%，所有核心死线均稳固达标。
