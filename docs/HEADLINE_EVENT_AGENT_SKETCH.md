# Headline event agent — design sketch (v1 pragmatic path)

**Working name:** `headline_event_agent` (avoid “greed” in code, dashboards, and customer-facing copy.)

**Not investment advice.** This document describes **engineering intent** only.

---

## 1. Problem statement

**Goal:** Surface **short-horizon** (intraday / few sessions) **hypotheses** tied to **high-impact political or policy headlines**, limited to **names that already pass fundamental quality filters** — without bypassing risk controls.

**Non-goals (v1):**
- Proving “extremely strong” predictive correlation (requires a separate research track).
- Auto-sizing large positions from headline alone.
- Scraping or relying on any single proprietary feed without license/terms clarity.
- Claiming cross-exchange arb, market making, or guaranteed returns.

---

## 2. Pragmatic v1 scope (phased)

| Phase | Deliverable | Success criterion |
|--------|-------------|-------------------|
| **P0** | **Event ledger** + **config** | Every stored event has UTC time, source id, text hash, topic tags, optional tickers; reproducible runs. |
| **P1** | **Labeling** (rules + optional LLM assist) | Consistent taxonomy (e.g. `tariffs`, `fed_appointments`, `war_risk`, `crypto_reg`, `other`); human-auditable. |
| **P2** | **Historical stats** (offline / batch) | For each (topic × horizon), report **distribution** of forward returns vs **matched** control (sector/beta bucket); no live trading from this alone. |
| **P3** | **Shadow signals** | Writes `data/headline_event_shadow_YYYYMMDD.jsonl` (or trust ledger events): “would suggest watch / reduce / no_trade”; **no orders**. |
| **P4** | **Optional live nudge** | Only if P3 stable: merge **small-weight** suggestions into screening or action queue, still behind **pre-trade gate** + **risk_guardian** + **max notional cap** for “event” bucket. |

**Stop line:** If shadow Sharpe vs control is not documented over a **pre-registered** window, do not enable P4.

---

## 3. High-level architecture

```
[Sources] → ingest (scheduled) → normalize → label → persist event ledger
                                              ↓
                    intersect watchlist / fundamentally approved universe
                                              ↓
                    stats module (batch) ← historical prices (existing utils)
                                              ↓
                    shadow writer (cron) → JSONL + optional trust_ledger
                                              ↓
                    [optional] orchestrator hook → action_queue / screening bump
                                              ↓
                    pre_trade_gate + risk_guardian + Alpaca (unchanged)
```

- **New code:** `agents/headline_event_agent.py` (or split `ingest`, `label`, `shadow` modules if it grows).
- **Config:** `config/headline_event_agent.yaml` (or JSON under `config/`) — sources, topics, horizons (e.g. 1h, 1d, 5d), shadow-only flag, caps.
- **Cron:** lightweight **ingest + shadow** every N minutes during market hours; **heavy stats** weekly off-market (aligns with existing `meta_architect` pattern).

---

## 4. Data model (minimum viable)

**Event record (append-only, e.g. JSONL):** `data/headline_events.jsonl`

| Field | Type | Notes |
|--------|------|--------|
| `event_id` | string | UUID |
| `ingested_at_utc` | ISO8601 | Server time |
| `published_at_utc` | ISO8601 \| null | From source when available |
| `source` | string | e.g. `rss`, `api_name` |
| `source_item_id` | string | URL or stable id |
| `text_hash` | string | sha256 of normalized text |
| `title` | string | short |
| `summary` | string | optional |
| `raw_ref` | string | URL or opaque ref (no secrets) |
| `topics` | list[str] | from rules/LLM |
| `entities` | list[str] | tickers or names if extracted |
| `confidence` | float | 0–1 for labeling |
| `version` | string | schema version |

**Shadow signal record:** `data/headline_event_shadow_YYYYMMDD.jsonl`

| Field | Notes |
|--------|--------|
| `event_id` | FK to event |
| `ticker` | Must be in approved universe |
| `horizon` | e.g. `intraday`, `5d` |
| `suggested_action` | `watch`, `reduce_risk`, `no_trade` (enum) |
| `rationale_short` | non-binding text |
| `notional_cap_hint` | optional; actual cap enforced in risk layer |

---

## 5. Inputs (sources) — v1 practical options

- **Curated RSS / official feeds** where ToS allows automated read.
- **Existing news pipeline** in the repo (if any) — **reuse** before adding vendors.
- **LLM:** optional **labeling only**, with **frozen prompt version** in config; no LLM-driven order size in v1.

**Explicitly out of v1:** paid Twitter/X firehose without contract; scraping behind login.

---

## 6. Intersection with “foundationally good” stocks

- **Universe = output of your existing screen** (or a static `watchlist` + last screening pass).
- Agent **never** introduces a ticker that failed fundamental gates; it only **ranks or flags** within the allowed set.

---

## 7. Orchestrator integration (sketch)

- **`orchestrator.py headline-event`** (or `shadow`): ingest + label + write shadow file + optional trust event.
- **Optional:** after `screen` / `snipe`, read **latest shadow file** and pass **hints** into `action_queue` as **low priority** items (same shape as other recommendations).
- **Kill switch:**
  - `HEADLINE_EVENT_AGENT_ENABLED=0` in `.env`, and/or
  - `config` flag `mode: shadow_only` (default **true** for first N weeks).

---

## 8. Risk and safety

- **Hard rules:** respect **circuit breaker**, **daily loss**, **max positions**, **pre_trade_gate**.
- **Cap:** `max_event_bucket_notional_pct` of equity (config, small default e.g. 0.25–0.5% until validated).
- **Audit:** shadow and live (if ever) lines visible in Command Center or daily ops report appendix (optional follow-up).

---

## 9. Testing

- **Unit:** parsing, hashing, dedupe (same `text_hash` same day).
- **Smoke:** `smoke_headline_event_agent.py` — ingest fixture file → labeled events → shadow rows (no network or mock HTTP).
- **Research:** notebook or script under `research/` (gitignored outputs) for correlation study — **not** shipped as production truth.

---

## 10. Open questions (resolve before P4)

1. **Legal/ToS** for each feed.
2. **Latency budget** vs your Alpaca paper fills.
3. **Whether “Trump-only”** is too narrow vs **policy headline** taxonomy (broader = more samples, less narrative fit).
4. **T3 consecutive-loss semantics** — event trades should count as normal trades for streak logic.

---

## 11. Suggested next engineering ticket (single PR)

- **`agents/headline_event_agent.py`** — P0–P3 fixture path + shadow JSONL under `data/`.
- **`smoke_headline_event_alpaca.py`** — unique fixture run + **`smoke_alpaca_paper_trade_cancel`** (paper limit + cancel).
- **`python orchestrator.py headline_event --fixture`** — manual run on Oracle.
- Optional cron (off by default): e.g. `15 * * * 1-5` … `headline_event --fixture` only if you replace fixture with real ingest later.

When you want that stub implemented in code, say so and point to preferred **news source** (RSS URL or existing internal module).
