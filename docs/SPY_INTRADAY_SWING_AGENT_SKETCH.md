# SPY intraday swing agent — design sketch

**Goal:** Focus on **SPY** (and optionally **/ES** as **context only**) to surface **intraday swing** setups: lean long on bullish risk-on dips or fade extremes — with **fast exits** when the tape turns. This is **not** a guarantee of profit; it is a **structured hypothesis + risk envelope**.

**Not investment advice.**

---

## 1. What you already have

- **`agents/intraday_sniper.py`** — scans a **broad universe** with **1m yfinance** data, sudden-drop / volume logic, tight **stops/targets**, caps (`MAX_INTRADAY_POSITIONS`, `POSITION_SIZE`). Cron runs **`orchestrator.py snipe`**.
- **Alpaca** — stocks/ETFs (SPY). **Not CME futures execution** unless you add a futures broker later.

So the new piece is mainly **SPY + session regime + optional futures “weather vane”**, not a second copy of the sniper.

---

## 2. “Futures” in practice

| Idea | Reality |
|------|--------|
| **Use ES/NQ as lead** for SPY | **Correlation is high** but **lead/lag is noisy** intraday. ES can hint **risk-on / risk-off** and **gap / opening drive**, not a magic entry timer. |
| **Data** | Yahoo **`ES=F`**, **`NQ=F`** via yfinance — often **delayed** and **imperfect** for HFT-style edges. Good enough for **coarse context** (e.g. “ES above VWAP vs below”). |
| **Trade futures** | **Out of scope** for v1 unless you integrate **CME-capable** data + broker + compliance. v1 = **context only** on SPY orders. |

**v1 rule:** futures feed **gates or scores** SPY signals; **only SPY** (or cash ETF) is **executed** on Alpaca.

---

## 3. Proposed agent shape (v1)

**Name:** `spy_intraday_swing` (or `spy_swing_context`).

**Inputs (each run, e.g. every 5 min with your monitor/sniper cadence):**

1. **SPY** — 1m (or 5m) bars for the **RTH session**; VWAP or opening range; recent high/low; realized vol vs prior days (optional).
2. **ES=F** (optional) — same session slice: **direction since open**, **distance from a simple session VWAP proxy**, **last N-bar return** (no overfitting).
3. **Risk state** — `risk_guardian` (circuit, consecutive losses, `strict_mode`), **pre_trade_gate**, **open positions** (avoid stacking SPY unless policy allows).

**Outputs:**

- **`shadow`** (default): append `data/spy_swing_shadow_YYYYMMDD.jsonl` with `{ ts, signal, score, reason_codes[], suggested_action: watch|consider_long|consider_exit|no_trade }`.
- **`live` (later):** enqueue or call the **same execution path as sniper** with **SPY-only** and **hard caps** (max adds per day, max notional, forced flat by **15:55 ET** aligned with sniper).

**Exit discipline (“sell as soon as market moves”):**

- Translate to **rules**, not vibes: e.g. **time stop** (flat if no follow-through in M minutes), **structure stop** (break of entry bar low), **target** (R-multiple or VWAP touch), **opposing ES flip** (optional tighten).

---

## 4. How it differs from `intraday_sniper`

| | Sniper (today) | SPY swing agent |
|--|----------------|-----------------|
| Universe | Many tickers | **SPY first** (optional QQQ later) |
| Context | Per-name technicals | **Session structure + optional ES** |
| Objective | Generic quick hits | **Defined swing playbook** (documented) |
| Logging | `sniper.log` | **`spy_swing.log` + shadow JSONL** |

You can either **extend** sniper with a `SPY_SWING_MODE=1` branch or **add a small module** called from **`orchestrator.py spy-swing`** to keep concerns separate.

---

## 5. Risks (operational, not moralizing)

- **Whipsaws** — 1m noise triggers bad entries; **wider bar interval** (2–5m) or **confirmation bar** often helps.
- **yfinance intraday gaps/delays** — signals can be **stale** vs Alpaca prints; **confirm with Alpaca last trade / quote** before size in live.
- **Fees / spread** — tiny targets must clear **round-trip cost** on your account.
- **PDT / concentration** — repeated SPY in-and-out may hit **pattern day trader** rules on small cash accounts; **policy check** outside the bot.

---

## 6. Suggested phases

| Phase | Deliverable |
|-------|-------------|
| **P0** | Shadow-only: compute **session metrics** + **signal enum** + reasons; log + JSONL; **no orders**. |
| **P1** | Wire **Alpaca quote** check before logging “consider_long”; still no auto-buy. |
| **P2** | **Paper:** one **small** SPY entry path behind **pre_trade_gate** + **max daily trades** + **flatten by 15:55 ET**. |
| **P3** | Tune playbook from **paper logs**; optional **QQQ** or **IWM** as secondary. |

---

## 7. Next step in code (when you say go)

1. **`agents/spy_intraday_swing.py`** — `run_spy_swing_cycle(shadow_only=True)` reading config from `config/spy_intraday_swing.example.yaml`.
2. **`orchestrator.py spy-swing`** — cron-friendly entry.
3. **`smoke_spy_intraday_swing.py`** — fixture bars or mocked DataFrame → assert JSONL rows.
4. **Command Center** (optional) — small panel like headline agent: last signal + link to `/api/spy_swing_status`.

---

## 8. Honest expectation

This can **organize** intraday attention around SPY and futures **context**, but **“buy then sell as soon as the market moves”** must be specified as **measurable rules** (stop, target, time cap). Without that, the agent becomes **discretionary trading with extra steps**.

If you want, the next message can pin your **playbook** (e.g. “buy 0.25% pullback to VWAP in first 2h when ES above session mid”) and we map it to **exact fields** in shadow JSONL before any paper execution.

---

## 9. Recommended formulas, rules, guardrails, and decision parameters

**Scope:** Defaults tuned for **SPY**, **RTH**, **yfinance-style bars** (no sub-minute edge), and execution through your existing **Alpaca + pre_trade_gate + risk_guardian** stack. These are **starting points** for paper/shadow — backtest and tighten to your account and data quality.

**Account cap:** **US $5,000** maximum equity (your stated budget). Scale **dollar** caps linearly if equity differs; **% of equity** rules stay the same.

**Not investment advice.**

### 9.1 Session and clock (hard guardrails)

| Parameter | Recommended | Rationale |
|-----------|-------------|-----------|
| Trading window | **09:45–15:50 ET** | Skip first ~15 min (auction/noise); exit before **15:55** hard flat like sniper. |
| No new entries after | **15:30 ET** | Avoid holding into close illiquidity / MOC noise on a “swing” that should resolve same day. |
| Bar interval (primary) | **5m** | Less whipsaw than 1m on delayed/free data; 1m only as optional **confirm**. |
| Evaluation cadence | **Every 5 min** (aligned to bar close) | Matches bar; avoids double-counting the same move. |
| Timezone | **America/New_York** | All session logic in ET. |

### 9.2 Core price formulas (SPY)

**Session VWAP** (typical cash-session definition):

- For each RTH bar \(i\): typical price \(P_i = (H_i + L_i + C_i) / 3\), volume \(V_i\).
- Cumulative: \(\text{VWAP}_n = \sum_{i=1}^{n} P_i V_i \big/ \sum_{i=1}^{n} V_i\).

**Opening range (first 30 min):**

- \(\text{ORH} = \max(\text{High})\), \(\text{ORL} = \min(\text{Low})\) over bars **09:30–09:59 ET** (or first six 5m bars).

**Distance to VWAP (%):**

- \(d_\text{VWAP} = (C_\text{last} - \text{VWAP}) / \text{VWAP} \times 100\).

**Short-term momentum (5m, last closed bar vs 3 bars ago):**

- \(r_3 = (C_{-1} - C_{-4}) / C_{-4} \times 100\) (requires enough history).

**ATR for ladders (5m SPY, Wilder-style period 10–14):** use \(\text{ATR\%} = \text{ATR}_{5m} / C_\text{last} \times 100\). If ATR is unavailable (thin history), fall back to **session range %** \((\text{day high} - \text{day low}) / C_\text{last} \times 100\) capped to a sane max.

### 9.2b Account budget ($5k cap)

| Parameter | Recommended |
|-----------|-------------|
| Max **notional** in SPY swing book at once | **≤ 10% of equity** (~**$500** on $5k) — one missile, one warhead budget. |
| Max **cash risk** (entry → initial stop) per swing | **≤ 0.75–1.0% of equity** (~**$37–$50** on $5k); if stop distance is wide (high ATR rung), **shrink shares** to keep risk ≤ cap. |
| Max round-trip **entries** (long + short combined) | **2/day** until paper proves stability. |
| Long vs short | **One open swing total** (either long **or** short); no hedge pair in v1. |

### 9.3 ES context (data-only gate, long + short)

Use **`ES=F`** on the **same bar interval** as SPY. Same session VWAP and \(d_\text{VWAP}\) for ES.

| Flag | Definition |
|------|------------|
| `es_risk_on` | ES close **≥** ES VWAP **and** ES \(r_3 > 0\). |
| `es_risk_off` | ES close **<** ES VWAP **or** ES \(r_3 < 0\). |

| Side | ES gate |
|------|---------|
| **Long** | Require **`es_risk_on`**. |
| **Short** | Require **`es_risk_off`**. |

Mid-flight: if ES flips against the position, treat as **abort** (§9.5 ladder / §9.5b terminal).

### 9.4 Adaptive VWAP band **ladder** (entry zones)

Pick a **rung** from **session volatility** so bands widen in chop and tighten in compression.

**Regime index** \(R_\sigma = \max(\text{ATR\%},\, 0.5 \times \text{session range \%})\). Map to rung:

| Rung | Condition (start here, tune on paper) | Long entry: \(d_\text{VWAP}\) window (below / at VWAP) | Short entry: \(d_\text{VWAP}\) window (above / at VWAP) |
|------|----------------------------------------|--------------------------------------------------------|-----------------------------------------------------------|
| **L0** (quiet) | \(R_\sigma < 0.10\%\) | \([-0.22\%,\, +0.06\%]\) (discount zone) | \([+0.06\%,\, +0.22\%]\) (extension zone) |
| **L1** (normal) | \(0.10\% \le R_\sigma < 0.18\%\) | \([-0.38\%,\, +0.12\%]\) | \([+0.12\%,\, +0.38\%]\) |
| **L2** (hot) | \(R_\sigma \ge 0.18\%\) | \([-0.60\%,\, +0.18\%]\) | \([+0.18\%,\, +0.60\%]\) |

**Long:** require \(d_\text{VWAP}\) in the **lower** part of the band (pullback): e.g. for L1, **\(d_\text{VWAP} \le +0.05\%\)** and **\(\ge\) band low** — you are buying **discount to VWAP**, not chasing above.

**Short:** symmetric — price **extended above** VWAP within the **upper** band (e.g. \(d_\text{VWAP} \ge -0.05\%\) and \(\le\) band high).

**Shared hard gates (both sides):** §9.1 window; ES gate §9.3; **knife filter** — long requires SPY \(r_3 > -0.25\%\); short requires SPY \(r_3 < +0.25\%\). Optional RSI(14) on 5m: long prefer **[32, 58]**, short prefer **[42, 68]** (wider than before to allow trend legs). Optional OR filter: long prefers price **≥ OR mid** or **ORH broken**; short prefers **≤ OR mid** or **ORL broken**.

**Score:** +1 per optional (RSI band, OR alignment); recommend **`consider_long` / `consider_short`** only if **score ≥ 2** plus all hard gates. Log `vol_rung`, `R_sigma`, `d_VWAP`, `side`.

### 9.5 Adaptive stop / target **ladder** (R-based, volatility-scaled)

Define **one initial stop distance** \(D\) in **price %** (adaptive), then express targets as **multiples of R** where **R = |entry − stop|** as % of entry.

**Initial stop distance ladder** (use **larger** of structure and ATR floor so the missile doesn’t detonate on noise):

| Component | Rule |
|-----------|------|
| **Structure** | Long: **min** of entry bar low and prior 3-bar low; stop = **0.02%** below that level (buffer). Short: **max** of entry bar high and prior 3-bar high; stop **0.02%** above. |
| **ATR floor** | \(D_\text{floor} = k \cdot \text{ATR\%}\) with **k = 0.9** (tune 0.8–1.1). |
| **Percent floor** | \(D \ge \max(D_\text{structure},\, D_\text{floor},\, 0.18\%)\) for L0; **0.22%** for L1; **0.28%** for L2 (match vol rung). |

**Target ladder (partials)** — sell/buy back in **thirds** by default:

| Tier | Trigger (long) | Trigger (short) | Action |
|------|----------------|-----------------|--------|
| **T1** | Price **≥ VWAP − 0.04%** (reclaim) **or** **+0.35 R** favorable | Price **≤ VWAP + 0.04%** **or** **+0.35 R** favorable | Close **1/3** |
| **T2** | **+0.75 R** **or** opposing 5m close vs VWAP (long: close **<** VWAP after T1) | **+0.75 R** **or** close **>** VWAP after T1 | Close **1/3** |
| **T3 (runner)** | **+1.25 R** **or** **15:50** flatten | **+1.25 R** **or** **15:50** | Flat remainder |

**Stop ratchet (midcourse guidance):**

- After **T1** fill: move stop to **breakeven − 0.02%** (long) / **+0.02%** (short).
- After **T2** fill: tighten to **+0.35 R** profit lock (long) / **−0.35 R** (short).

**Time fuse:** if after **8** closed 5m bars (**40 min**) unrealized **R < 0.15** (favorable move &lt; 15% of R), **flatten** at market on next bar open (no hero hold).

**ES abort:** ES flips against position → **flatten remainder** next 5m close (same as before).

**Flatten by end of day:** **15:55 ET** — align with `intraday_sniper` `MARKET_CLOSE_TIME`.

### 9.5b “Intelligent missile” — phased decision model

Treat the agent as **guidance in three phases** (log `phase` in JSONL every tick):

| Phase | Name | What happens |
|-------|------|----------------|
| **1 — Acquire** | Lock | Regime rung (§9.4), ES gate, session clock, data quality. **No fire** unless lock is valid. |
| **2 — Midcourse** | Track | On each **closed 5m bar**: recompute VWAP, \(d_\text{VWAP}\), ATR%, rung (can **widen** stop floor if \(R_\sigma\) jumps — **never** loosen stop **below** initial risk once in trade except ratchet rules). Update **abort** if ES flips or time fuse arms. |
| **3 — Terminal** | Engage / detonate | Hit **T1/T2/T3**, ratchet stops, **15:55** self-destruct flat, or **stop** hit. |

**“Smart” behavior (not magic):** the **adaptive ladders** are the intelligence — same rules, **different coefficients** for quiet vs hot days. Optional future hook: **confidence score** = f(regime stability, ES/SPY agreement over last 3 bars) to **scale notional** within the $5k cap (e.g. 60% size if confidence &lt; 0.6).

### 9.6 Position sizing and concentration (align with repo + $5k)

| Parameter | Recommended | Notes |
|-----------|-------------|--------|
| Max SPY swing **entries** per day | **2** | Long+short combined. |
| Max concurrent | **1** swing | One missile in the air. |
| Notional | **≤ 10% equity** (~**$500** on $5k) | Fits `POSITION_SIZE`-scale; still capped by `pre_trade_gate`. |
| Risk per trade | **≤ ~1% equity** to stop | Size shares so \(|entry-stop| \times \text{shares} \le \$50\) on $5k. |
| `risk_guardian` | **Must approve** | Call `check_risk_limits` / orchestrator path before live order. |
| `pre_trade_gate` | **Must pass** | `FORTRESS_MAX_ORDER_NOTIONAL_USD`, qty, halt, live ack. |

### 9.7 Global blocks (do not trade)

- **`is_trading_halted()`** — operator halt.
- **Circuit breaker active** or **strict_mode** from `risk_guardian` — **no new entries** (exits only if your policy allows reducing risk).
- **Daily P&L ≤ `DAILY_LOSS_LIMIT_PCT`** (normal) or **≤ `STRICT_MODE_DAILY_LOSS_LIMIT_PCT`** (strict) — **no new entries**.
- **FOMC / known macro** (optional config): widen thresholds or **shadow-only** — reduces model-breaking vol.

### 9.8 Data quality checks (before trusting a signal)

| Check | Action if fail |
|-------|----------------|
| SPY bar count &lt; N (e.g. **6** five-minute bars since open) | `no_trade` — insufficient session |
| Last bar stale vs wall clock (&gt; **2× bar length + 120s**) | `no_trade` — yfinance lag |
| Optional: Alpaca last vs bar close **disagree &gt; 0.15%** | Downgrade to `watch` or `no_trade` for live |

### 9.9 Why these numbers

- **Ladder bands** — **ATR% / range** picks **L0/L1/L2** so quiet days don’t use hot-day widths (fewer false entries) and volatile days don’t get stopped out by a one-size band.
- **R-multiple targets + ratchet** — partials bank **edge** while the runner catches continuation; stops **tighten** after proof (missile doesn’t give back full R after T1).
- **ES as directional gate** — longs need **risk-on** ES; shorts need **risk-off** ES; **abort** on flip is the “self-destruct if target changed” rule.
- **$5k book** — **~10% notional** and **~1% max cash risk** per swing keeps **PDT / ruin** math sane for a single-name intraday system.

### 9.10 Summary checklist for implementation

1. Compute **SPY + ES** VWAP, **\(d_\text{VWAP}\)**, **ATR%**, **\(R_\sigma\)**, **vol rung L0/L1/L2** on **5m** RTH bars.  
2. **Entry (long or short):** clock + ES gate + **band ladder** + knife filter + optional score ≥ 2; log `side`, `vol_rung`, `phase=acquire`.  
3. **In trade:** each bar **midcourse** — ratchet rules, **T1/T2/T3** ladder, **time fuse**, **ES abort**; `phase=track` / `terminal`.  
4. **Risk ($5k):** one swing, **≤10%** notional, **≤~1%** equity to stop, max **2** entries/day, **risk_guardian** + **pre_trade_gate** + stale-data checks, **15:55** flat.
