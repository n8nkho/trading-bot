# Low-Risk Improvements & AI/Agentic Recommendations

**Purpose:** Increase win opportunities while preserving core objectives (near-zero loss, high win rate, strict filters). Incorporates proven/unproven low-risk models and latest AI/agentic capabilities.

**Reference:** PROJECT_CONTEXT.md, INTELLIGENT_AGENTS_REVIEW.md, NEW_AGENT_PROMPT.md.

---

## 1. Proven Low-Risk Model Improvements

### 1.1 Regime-filtered momentum (already partially in place)
- **Current:** Regime center (RISK_ON/NEUTRAL/RISK_OFF/CRASH), regime-aware RSI/drop band, bond allocation.
- **Improvement:** Add explicit **regime filter before entry** — e.g. in RISK_OFF, require higher confidence (e.g. 0.75) or only allow defensive watchlist names; in CRASH, consider pausing new equity entries and only rebalancing bonds.
- **Evidence:** Regime-filtered momentum strategies show improved risk-adjusted returns (12–655% in backtests with inverse-vol weighting).

### 1.2 ATR-adaptive position sizing (unproven here, high value)
- **Idea:** Scale position size by volatility: `position_dollars = base_dollars * (reference_ATR / stock_ATR)` with caps (e.g. 0.5x–1.5x).
- **Benefit:** Smaller size in high-vol names (fewer blow-ups), same or larger in low-vol (more shares for same risk).
- **Implementation:** Add 14-day ATR in screener or entry_agent; pass to orchestrator; apply multiplier within existing AUTO_POSITION_SIZE and risk limits.
- **Risk:** Slightly more complexity; backtest before enabling.

### 1.3 Inverse volatility weighting for multi-candidate days
- **Current:** We take top N by confidence up to daily cap.
- **Idea:** When multiple candidates qualify, weight by inverse of recent volatility (or inverse of ATR/price) so lower-vol names get slightly preferred — aligns with “quality over quantity.”
- **Implementation:** In orchestrator `qualify_candidates_for_auto_execution`, sort by `confidence / (1 + vol_pct)` or use ATR when available.

### 1.4 Stricter reward-to-risk floor
- **Current:** Stop -3%, target +10% (~3.3:1).
- **Improvement:** Document and enforce minimum 1.5:1 or 2:1 reward-to-risk per trade (already satisfied by current numbers). Optional: add a “minimum expected value” gate: e.g. `confidence * (target_pct) > abs(stop_pct)` so we only take trades where expected payoff is positive.

### 1.5 Daily profit target / pause (proven in quant systems)
- **Idea:** Once daily realized P&L exceeds a threshold (e.g. +$200 or +1% of equity), pause new auto-trades for the day to lock in gains and avoid overtrading.
- **Implementation:** In orchestrator, before qualifying candidates, load today’s realized P&L (from decisions_log or Alpaca); if above threshold, skip auto-execution and log “Daily profit target reached.”

---

## 2. Unproven but Low-Risk Additions

### 2.1 Dual EMA / trend filter (no new trades against strong downtrend)
- **Idea:** Require price above 50-day EMA (or 20-day) for BUY candidates to avoid catching falling knives.
- **Risk:** May reduce number of contrarian wins; best tested as optional filter in RISK_OFF only, or as a “bonus” confidence bump when price is above EMA rather than a hard gate.

### 2.2 Correlation / concentration cap (from INTELLIGENT_AGENTS_REVIEW)
- **Idea:** Periodic correlation and sector exposure check; recommend or auto-reduce concentration in highly correlated names.
- **Implementation:** Lightweight agent that reads positions + pipeline candidates, computes pairwise correlation or sector weights, writes to `data/correlation_recommendations.json` and/or feeds risk_guardian.

### 2.3 Forward-looking ticker grader (deferred per INTELLIGENT_AGENTS_REVIEW)
- **Idea:** Simple rule-based “likely safe vs avoid” for next N days (momentum/RSI/volume). Output watchlist or blocklist.
- **Status:** Defer until more history; avoid overfitting. Document as future work.

---

## 3. AI and Agentic Capabilities (2024–2025)

### 3.1 Multi-agent roles (already partially present)
- **Current:** ~29 agents (screener, momentum, forex, exit monitor, opportunity/hedging analyzers, defensive scanner, etc.).
- **Improvement:** Align with “TradingAgents”-style roles:
  - **Analysts:** Technical (screener + vision), sentiment (Grok), fundamental (optional).
  - **Debate / research:** Optional “bull vs bear” summary for high-stake names (e.g. when confidence > 0.8 and position size is large).
  - **Risk team:** risk_guardian, exit_monitor, agent_manager — already in place.
  - **Execution:** Single execution path (orchestrator) with strict gates — keep as is.

### 3.2 Orchestrator as single “trader” agent
- **Current:** Orchestrator qualifies candidates and executes; analyzers only recommend.
- **Improvement:** Keep one execution path. Add an optional “pre-trade checklist” step: before placing an order, run a small LLM or rule-based “final go/no-go” that considers regime + daily P&L + concentration. If no-go, skip and log (no override of stop-loss or risk limits).

### 3.3 Regime–strategy alignment agent
- **Idea:** Dedicated agent that compares current regime (regime_center) with active strategies, bond target, and hedging recommendations; outputs recommendations like “Increase bond allocation” or “Pause momentum in CRASH.”
- **Implementation:** Extend hedging_opportunity_analyzer or add a small `regime_alignment_agent.py` that reads `market_regime.json`, fortress report, and positions; writes to `data/regime_recommendations.json`; Command Center shows in RECOMMENDATIONS.

### 3.4 Local LLM usage (already in place)
- **Current:** Ollama (khf-fast) for stock drop analysis and pattern detection.
- **Improvement:** Consider adding a short “reasoning” summary for each auto-trade (e.g. “RSI 35, drop -8%, volume 2x, vision BUY”) and append to decisions_log and trade record for later analysis.

### 3.5 Reinforcement learning / execution (future)
- **Reference:** Hi-DARTS, constrained RL execution — improve execution quality (slippage, timing) rather than entry signals.
- **Status:** Not recommended until paper track record is large; document as long-term option.

---

## 4. Implementation Priority

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| High | Daily profit target / pause | Low | Reduces overtrading, locks gains |
| High | Regime–strategy alignment (recommendations) | Low | Better alignment with objectives |
| Medium | ATR-adaptive position sizing | Medium | Better risk per trade |
| Medium | Inverse vol weighting for multi-candidate sort | Low | Slightly better name selection |
| Medium | Pre-trade checklist (optional go/no-go) | Low | Extra safety without changing core logic |
| Low | Dual EMA as optional filter (RISK_OFF) | Low | Test in backtest first |
| Low | Correlation/concentration agent | Medium | Diversification and near-zero loss |
| Deferred | Forward-looking grader, RL execution | — | After more data and backtests |

---

## 5. Summary

- **Fixes applied (this session):** Smart Money Trader pandas ambiguity, fortress_orchestrator duplicate import, current_price KeyError (defensive access + screener safe latest close), exit_monitor defensive current_price.
- **Quick wins:** Daily profit target pause, regime alignment recommendations, inverse-vol sort for candidates.
- **Next steps:** Implement daily profit cap in orchestrator; add regime alignment to Command Center; consider ATR in screener for adaptive sizing and sorting.
