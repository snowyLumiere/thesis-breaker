# Obsidian ThesisCard YAML Frontmatter Schema

Every position note in your Obsidian vault must contain YAML frontmatter matching this schema:

```yaml
symbol: "MU"                         # Normalized US or HK ticker (e.g. MU, 9988.HK, 0700.HK)
name: "Micron Technology"
entry_date: "2026-06-12"
entry_price: 118.0
initial_strategy_type: cyclical_swing # cyclical_swing | sotp_rerating | compounder_fcfe | event_driven
current_claimed_style: cyclical_swing # Changing this without closing the trade triggers Style Drift
thesis_lock_sha256: null              # Stamped by `thesis-breaker lock --notes <dir>`

kill_switches:                        # Minimum 3 falsifiable numerical kill-switches required
  - id: KS-1
    name: "Q4 HBM3E 良率"
    metric_key: hbm_yield_pct
    operator: ">="                    # >= | <= | > | < | ==
    threshold: 75.0
    locked_threshold: 75.0            # Frozen baseline to catch Tolerance Creep
    unit: "%"
    haircut_pct: 20.0                 # Valuation haircut applied when breached
    critical: true                    # Forces KILL_SWITCH_TRIGGERED when breached

valuation:
  model_type: SOTP                    # SOTP or FCFE
  currency: USD
  diluted_shares: 1.12
  net_cash: -4.2
  required_mos_pct: 25.0
  # For SOTP:
  segments:
    - name: "HBM3E & AI Memory"
      metric_value: 14.0
      multiple: 7.5
      ownership_pct: 100.0
      metric_key: hbm_rev_b
  # For FCFE:
  # base_fcfe_per_share: 22.5
  # growth_rate_pct: 11.0
  # terminal_growth_pct: 3.0
  # cost_of_equity_pct: 9.5
  # projection_years: 5

latest_actuals: {}
```

And Markdown body sections:
- `## Core Thesis` — Original falsifiable investment hypothesis.
- `## Review Notes` — Latest quarterly/weekly review notes (scanned for Thesis Drift).
