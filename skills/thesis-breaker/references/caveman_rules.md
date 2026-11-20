# Caveman Mode Discipline Rules (Inspired by JuliusBrussee/caveman)

1. **Zero Filler, Zero Pleasantries**: Strip greetings, apologies, empathy, and boilerplate disclaimers.
2. **Zero Hedging ("和稀泥"禁令)**: Ban phrases like "on the other hand", "long-term might recover", "既有可能上涨也有宏观风险".
3. **Exact 3-Line Output Budget Per Holding**:
   - **Line 1 (Facts + Re-priced Valuation)**: Ticker, PnL %, breached kill-switch vs threshold & % deviation, re-priced SOTP/FCFE intrinsic value vs initial IV, current Margin of Safety vs required floor.
   - **Line 2 (Cognitive Bias Trap)**: Contrast **Excuse B** (rationalization quote from review notes / style drift / threshold relaxation) against **Failed Assumption A**; or explicitly confirm zero drift. If the Python engine's fixed keyword matcher missed an implicit rationalization under a breach or `<= -10%` drawdown, the Agent may quote a verbatim phrase from `latest_review_notes` tagged `语义合理化补抓` without altering Line 1 numbers or Line 3 posture.
   - **Line 3 (Posture Directive)**: Concrete exposure sizing directive + `[ExposurePosture]` tag + human-review-only lock.
4. **Numbers Are Law**: Always cite exact computed percentages and currency figures from `thesis_breaker.engine`; never round away an inconvenient loss.
