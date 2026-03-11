# Intelligent Agents Review: Opportunities, Hedging, and Forward-Looking Strategies

## Overarching Goals (Reference)
- **Near-zero loss**: Tight stop losses (-3% to -4%), scalp ladder (2%/4%/6%), no reckless sizing.
- **High probability of wins**: Quality filters (RSI, drop band, volume), regime-aware criteria, diversification.

---

## Current Intelligent Analyzers

### 1. Opportunity Analyzer (`agents/opportunity_analyzer.py`)
- **Role**: Analyzes **equity screening** results to find safe opportunities lost and suggest **strategy/criteria** changes.
- **Inputs**: Last 7 days of `daily_signals_*.json` (candidates found, approved, executed).
- **Output**: `data/opportunity_recommendations.json` → Command Center **Recommendations** panel.
- **Logic**: Zero-candidate runs → suggest slight RSI/drop widening in RISK_ON; candidates-but-none-approved → suggest reviewing confidence/risk; backtest sample of non-executed candidates for “safe win” paths → suggest criteria tweaks while keeping stops unchanged.

### 2. Hedging Opportunity Analyzer (`agents/hedging_opportunity_analyzer.py`)
- **Role**: Assesses **missed safe opportunities across hedging strategies** (bonds, commodities, VIX, pairs).
- **Inputs**: Latest `fortress_report_*.json`, `market_regime.json`, optional `positions.json`.
- **Output**: `data/hedging_recommendations.json` → Command Center **Recommendations** panel.
- **Logic**: Compares fortress recommendations vs regime and inferred positions (e.g. bond target vs TLT/IEF value); VIX elevated while VIX insurance is SKIP → recommend review; RISK_OFF → reinforce bond/commodity targets; pairs opportunity in report → surface for review.

---

## Need for Other Intelligent Agents

### Analyzing “Futures” of Tickers (Screening Universe and Beyond)

**Interpretation**: “Futures” can mean (1) **forward-looking performance** of tickers (would they have been safe wins?), or (2) **alternative/supplementary strategies** (defensive names, low-beta adds, sector tilts) that stay within our goals.

| Agent idea | Purpose | Safe-strategy alignment | Priority |
|------------|---------|---------------------------|----------|
| **Defensive universe scanner** | From screening universe (or a broader set), flag names with low beta, high dividend, or that held up in past drawdowns; suggest as “defensive adds” without loosening core criteria. | Adds optional low-correlation, capital-preservation names. | Medium |
| **Regime–strategy alignment** | Ensure equity sizing, hedge targets, and which strategies are active align with current regime; recommend on/off or size adjustments. | Keeps risk and sizing consistent with regime. | Medium (partially covered by hedging analyzer + fortress). |
| **Forward-looking ticker grader** | For tickers in (or outside) universe, use momentum/RSI/volume and simple rules to classify “likely safe” vs “avoid” for next N days; output a small watchlist or blocklist. | Could gate entries or suggest only highest-conviction names. | Lower (needs backtest; risk of overfitting). |
| **Correlation / drawdown analyzer** | Periodically compute pairwise correlation and max drawdown of current positions and candidates; recommend reducing concentration or adding uncorrelated names. | Directly supports diversification and near-zero loss. | Medium |
| **Sector/factor exposure** | Summarize sector and factor exposure of positions + pipeline candidates; recommend caps or rebalancing. | Avoids over-concentration in one sector (already in risk_guardian; could be extended). | Low (existing sector limits). |

### Recommended Next Steps (Without Overbuilding)

1. **Keep and run** the two existing analyzers (opportunity + hedging); they already feed Command Center and align with goals.
2. **Add one lightweight “defensive/quality” agent** (optional): e.g. **Defensive Universe Scanner** that:
   - Takes current screener universe (or S&P 100) and filters for: beta &lt; 1, dividend yield &gt; 0, and optionally “held up in last drawdown” (e.g. drawdown &gt; -10% vs SPY -15%).
   - Outputs a small list of “defensive candidates” and writes to `data/defensive_watchlist.json`; Command Center or screener could optionally prefer these when regime is RISK_OFF.
3. **Defer** full “forward-looking grader” and heavy correlation/drawdown analytics until we have more history and clear backtest; document as future work in this file.

---

## Summary

- **Opportunity Analyzer** and **Hedging Opportunity Analyzer** are implemented and wired to the Command Center; they address missed safe opportunities in equity screening and hedging.
- **Other intelligent agents** that analyze “futures” of tickers (forward-looking or defensive) are **useful but not required** for the current goals; the highest-value next step is an optional **Defensive Universe Scanner** for regime-aware, low-risk names. More advanced forward-looking or correlation agents can be added later with proper backtesting.
