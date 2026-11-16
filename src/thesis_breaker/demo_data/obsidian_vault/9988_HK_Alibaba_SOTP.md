---
symbol: 9988.HK
name: "Alibaba Group"
entry_date: "2026-05-18"
entry_price: 102.0
initial_strategy_type: sotp_rerating
current_claimed_style: sotp_rerating
thesis_lock_sha256: baebe91a612f8fafaf15e1c7928ad4d1621500a38d77fe5df9059c5e460fe77d
kill_switches:
  - id: KS-1
    name: "阿里云外部收入 YoY"
    metric_key: cloud_rev_yoy_pct
    operator: ">="
    threshold: 4.0
    locked_threshold: 10.0
    unit: "%"
    haircut_pct: 15.0
    critical: false
    aliases: ["Cloud YoY"]
  - id: KS-2
    name: "淘天核心 EBITA 利润率"
    metric_key: taotian_ebita_margin_pct
    operator: ">="
    threshold: 42.0
    locked_threshold: 42.0
    unit: "%"
    haircut_pct: 10.0
    critical: false
  - id: KS-3
    name: 季度回购年化收益率
    metric_key: buyback_yield_pct
    operator: ">="
    threshold: 5.0
    locked_threshold: 5.0
    unit: "%"
    haircut_pct: 8.0
    critical: false
valuation:
  model_type: SOTP
  currency: HKD
  diluted_shares: 19.0
  net_cash: 420.0
  required_mos_pct: 25.0
  segments:
    - name: "Taotian Core Commerce (EBITA)"
      metric_value: 195.0
      multiple: 8.0
      ownership_pct: 100.0
    - name: "Cloud Intelligence (Revenue)"
      metric_value: 115.0
      multiple: 3.5
      ownership_pct: 100.0
    - name: "AIDC & Strategic Investments"
      metric_value: 220.0
      multiple: 1.0
      ownership_pct: 100.0
latest_actuals:
  cloud_rev_yoy_pct: 4.2
  taotian_ebita_margin_pct: 43.5
  buyback_yield_pct: 5.6
---

## Core Thesis
基于 SOTP 估值折价与高回购率建仓：前提是阿里云外部收入恢复至 >=10% 增长，推动云业务按 3.5x P/S 重估。

## Review Notes
短期云业务为 AI 算力做战略性投入导致增速放缓至 4.2%，忽略短期增速压力并下调观察门槛，坚持长期价值持有。
