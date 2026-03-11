# Self-Improving Pattern Discovery (Design)

**Goal:** Automatically identify new patterns of trade opportunities not considered by current strategies, within the constraints of near-zero loss and high win rate.

---

## 1. Approach (recommended)

### Phase 1: Outcome logging (existing + light extension)
- **Already have:** `daily_signals_*.json` (candidates, approved, rejected), `decisions_log.jsonl`, exit outcomes in exit_monitor.
- **Add:** For each candidate (executed or not), persist a minimal **outcome record**: ticker, date, features at signal time (drop_pct, rsi, volume_ratio, regime), and outcome after N days: `safe_win` / `stop_hit` / `open` / `not_traded`. Use same logic as opportunity_analyzer’s `_check_safe_opportunity` (e.g. 5-day forward, -4% stop, +5% target).

### Phase 2: Pattern mining (batch, weekly)
- **Input:** Last 8–12 weeks of outcome records.
- **Process:**  
  - Discretize features (e.g. drop_pct buckets: -15–-12, -12–-9, -9–-6, -6–-3; RSI buckets: &lt;30, 30–35, 35–40; volume_ratio: 1.5–2, 2–3, &gt;3).  
  - Compute P(safe_win | feature combo) and count; filter combos with count &lt; 5 (noise).  
  - Rank by hit rate and by “currently underused” (e.g. pattern has high safe_win rate but our screener rarely passes it because our band is different).  
- **Output:** `data/discovered_patterns.json`: list of { "pattern": { "drop_bucket", "rsi_bucket", "vol_bucket", "regime" }, "safe_win_rate", "count", "suggestion" }.

### Phase 3: Propose new opportunities (no auto-change)
- **Gate:** Only suggest a pattern if: safe_win_rate ≥ 0.55, count ≥ 8, and pattern is not already covered by current screener params (e.g. current drop -5 to -15, pattern -6 to -9 → already in band; pattern -3 to -5 → “consider widening upper bound in RISK_ON”).  
- **Output:** One or two “discovered pattern” recommendations into Command Center (e.g. “Pattern: drop -6% to -9%, RSI 32–38, vol 2–2.5x had 62% safe_win (12 cases). Consider adding as optional filter or RISK_ON widen.”).  
- **No automatic change to screener or risk:** All suggestions are advisory; human or separate approval step before any param change.

### Phase 4 (later): Optional automation
- **Backtest gate:** Before any suggested param change (e.g. “allow RSI up to 42 in RISK_ON”), run a small backtest on last 60 days: apply change, count simulated entries and outcomes, require improvement or neutral vs current.  
- **Candidate generator:** Use discovered patterns to propose a **new strategy hook** (e.g. “momentum + oversold” combo) as a new agent or a new screener branch, again suggestion-only until approved.

---

## 2. Implementation options (best way to adopt)

| Option | Effort | Risk | Recommendation |
|--------|--------|------|-----------------|
| **A. Outcome logger only** | Low | None | Add a small writer in orchestrator/opportunity_analyzer that appends outcome records to `data/outcome_records.jsonl` when we have 5-day forward data. No UI change. |
| **B. Weekly pattern miner** | Medium | Low | New agent `agents/pattern_miner.py` runs weekly (e.g. Sunday 2 AM), reads outcome records, writes `data/discovered_patterns.json` and 0–2 recommendations to `data/strategic_recommendations.json` or a dedicated `data/pattern_discovery_recommendations.json`. Command Center already reads strategic. |
| **C. Full pipeline (B + backtest gate)** | Higher | Medium | As B, plus before writing a “widen RSI” style recommendation, run a 60-day backtest; only recommend if backtest passes. |

**Best way to build:** Start with **A** (outcome logging) so we have data; then add **B** (weekly pattern miner) so the bot surfaces 0–2 “new pattern” recommendations without changing any strategy. Add **C** when we want to avoid bad suggestions.

---

## 3. Constraints (unchanged)

- No automatic change to MIN_CONFIDENCE, stop loss, profit target, or position size.
- Any suggested criterion change (RSI, drop band) must be optional and documented (e.g. “RISK_ON only”).
- Preserve near-zero loss and high win rate as core objectives.

---

## 4. Files and ownership

| File | Purpose |
|------|---------|
| `data/outcome_records.jsonl` | One line per candidate outcome (future). |
| `data/discovered_patterns.json` | Output of pattern miner (future). |
| `data/strategic_recommendations.json` | Strategic/roadmap items shown in Command Center (e.g. self-improving capability, pattern discovery). |
| `docs/SELF_IMPROVING_PATTERN_DISCOVERY.md` | This design. |

---

**Status:** Implemented. Phase 1 (outcome logging) in `opportunity_analyzer.py` appends to `data/outcome_records.jsonl` when signals are 5+ days old; Phase 2 (pattern miner) in `agents/pattern_miner.py` runs weekly (cron Sunday 2 AM), writes `data/discovered_patterns.json` and `data/pattern_discovery_recommendations.json`; Command Center shows pattern_discovery recommendations (up to 2).
