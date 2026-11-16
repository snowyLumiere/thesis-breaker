---
symbol: MU
name: "Micron Technology"
entry_date: "2026-06-12"
entry_price: 118.0
initial_strategy_type: cyclical_swing
current_claimed_style: long_term_value
thesis_lock_sha256: bfb7f545e22667da23ef38d8c0445d1fc8d3b72e54b605ada7f96578c0f2fe5b
kill_switches:
  - id: KS-1
    name: "Q4 HBM3E 良率"
    metric_key: hbm_yield_pct
    operator: ">="
    threshold: 75.0
    locked_threshold: 75.0
    unit: "%"
    haircut_pct: 20.0
    critical: true
    aliases: ["HBM yield", "HBM3E yield"]
  - id: KS-2
    name: "DRAM 合约价环比增速"
    metric_key: dram_contract_qoq_pct
    operator: ">="
    threshold: 0.0
    locked_threshold: 0.0
    unit: "%"
    haircut_pct: 15.0
    critical: false
    aliases: ["DRAM contract QoQ"]
  - id: KS-3
    name: 综合毛利率底线
    metric_key: gross_margin_pct
    operator: ">="
    threshold: 38.0
    locked_threshold: 38.0
    unit: "%"
    haircut_pct: 10.0
    critical: false
valuation:
  model_type: SOTP
  currency: USD
  diluted_shares: 1.12
  net_cash: -4.2
  required_mos_pct: 25.0
  segments:
    - name: "HBM3E & AI Memory"
      metric_value: 14.0
      multiple: 7.5
      ownership_pct: 100.0
      metric_key: hbm_rev_b
    - name: "Commodity DRAM & NAND"
      metric_value: 26.0
      multiple: 3.0
      ownership_pct: 100.0
latest_actuals:
  hbm_yield_pct: 62.0
  dram_contract_qoq_pct: -4.5
  gross_margin_pct: 36.2
  hbm_rev_b: 11.5
---

## Core Thesis
作为存储芯片周期波段交易建仓：赌 HBM3E 良率爬坡至 75% 以上叠加 DRAM 合约价上行周期，驱动 SOTP 分部重估至 $159.6 附近。

## Review Notes
虽然 Q4 HBM 良率不及预期且 DRAM 价格转跌，但 AI 存储超级周期才刚开始，打算把原本的波段仓位转为长期价值投资死扛，忽略短期波动并等待下个周期。
