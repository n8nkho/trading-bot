import os
import json
import re
import time
import logging
import traceback
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import yfinance as yf

try:
    from utils.llm_router import ensure_llm_env_loaded

    ensure_llm_env_loaded()
except Exception:
    pass

from utils.local_llm import analyze_stock_drop
from agents.vision_analyst import analyze_chart_patterns, pattern_to_signal
from utils.policy_profile import get_profile_bundle
from utils.runtime_config import get_llm_config
from agents.convergence_engine import score_candidate
from utils.uplift_runtime import get_flag_mode
from utils.throughput_controller import recommend_thresholds

# Load current parameters
DATA_DIR = Path("data")
CURRENT_PARAMS_FILE = DATA_DIR / "current_params.json"

_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
_screener_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")


def _configure_screener_logging() -> None:
    """Only agents.screener_agent logs go to screener.log (not Flask/werkzeug on root)."""
    lg = logging.getLogger(__name__)
    if lg.handlers:
        return
    lg.setLevel(logging.INFO)
    fh = logging.FileHandler(_log_dir / "screener.log")
    fh.setFormatter(_screener_fmt)
    lg.addHandler(fh)
    lg.propagate = False


_configure_screener_logging()
logger = logging.getLogger(__name__)


def _read_latest_json(data_dir: Path, pattern: str) -> dict:
    try:
        files = sorted(data_dir.glob(pattern), reverse=True)
        if not files:
            return {}
        with open(files[0], "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def load_agentic_opportunities(
    data_dir: Path = DATA_DIR,
    *,
    min_consensus: float = 0.60,
) -> dict:
    """
    Build a prioritized symbol set from scout + analyst artifacts.

    Rules:
    - Symbol must appear in analyst_consensus with recommendation BUY.
    - consensus_score must be strictly > min_consensus.
    - If CIO sleeve tilts are present, expose an agentic budget fraction so caller
      can respect CIO allocation percentages when merging with deterministic flow.
    """
    scout = _read_latest_json(data_dir, "scout_opportunity_queue_*.json")
    analyst = _read_latest_json(data_dir, "analyst_consensus_*.json")
    cio = _read_latest_json(data_dir, "cio_directive_*.json")

    scout_rows = scout.get("opportunities") if isinstance(scout.get("opportunities"), list) else []
    analyst_rows = analyst.get("recommendations") if isinstance(analyst.get("recommendations"), list) else []

    analyst_index: dict[str, dict] = {}
    for row in analyst_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        analyst_index[sym] = row

    selected: list[dict] = []
    for row in scout_rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ar = analyst_index.get(sym) or {}
        rec = str(ar.get("recommendation") or "").strip().upper()
        score = ar.get("consensus_score")
        try:
            score_f = float(score)
        except Exception:
            continue
        if rec != "BUY" or score_f <= float(min_consensus):
            continue
        selected.append(
            {
                "ticker": sym,
                "source": "agentic",
                "scout_theme": row.get("theme"),
                "scout_score": row.get("score"),
                "consensus_score": score_f,
                "consensus_recommendation": rec,
            }
        )

    selected.sort(key=lambda x: float(x.get("consensus_score") or 0.0), reverse=True)

    tilts = cio.get("sleeve_tilts_pct") if isinstance(cio.get("sleeve_tilts_pct"), dict) else {}
    # For the screener stage, treat day+swing sleeves as immediate opportunity budget.
    try:
        day_pct = float(tilts.get("day_trading", 0) or 0)
        swing_pct = float(tilts.get("swing_trading", 0) or 0)
        agentic_budget_fraction = max(0.0, min(1.0, (day_pct + swing_pct) / 100.0))
    except Exception:
        agentic_budget_fraction = 1.0

    return {
        "symbols": selected,
        "agentic_count": len(selected),
        "scout_timestamp": scout.get("timestamp"),
        "analyst_timestamp": analyst.get("timestamp"),
        "cio_timestamp": cio.get("timestamp"),
        "cio_directive": cio.get("portfolio_directive"),
        "agentic_budget_fraction": agentic_budget_fraction if tilts else 1.0,
    }

def load_screening_params():
    """Load current screening parameters (may have been auto-tuned)"""
    try:
        if CURRENT_PARAMS_FILE.exists():
            with open(CURRENT_PARAMS_FILE, 'r') as f:
                params = json.load(f)
                logger.info(f"Loaded tuned parameters: RSI<{params['rsi_threshold']}, Drop: {params['drop_min']}% to {params['drop_max']}%")
                return params
        else:
            # Default parameters
            return {
                'rsi_threshold': 40,
                'drop_min': -15,
                'drop_max': -5,
                'volume_ratio_min': 1.5
            }
    except Exception as e:
        logger.error(f"Error loading parameters, using defaults: {e}")
        return {
            'rsi_threshold': 40,
            'drop_min': -15,
            'drop_max': -5,
            'volume_ratio_min': 1.5
        }

def run_screener():
    # Load current parameters (may have been auto-tuned)
    params = load_screening_params()
    
    with open('config/watchlist.json', 'r') as f:
        watchlist_payload = json.load(f)

    # Agentic opportunity integration (Task 1):
    # Scout + analyst consensus creates a high-priority seed tier.
    # Deterministic watchlist tiers remain as fallback.
    agentic_pack = load_agentic_opportunities(DATA_DIR, min_consensus=0.60)
    agentic_symbols = agentic_pack.get("symbols") or []
    if agentic_symbols:
        logger.info(
            "Agentic queue loaded: %d BUY symbol(s) from scout+analyst (cio=%s, budget_fraction=%.2f)",
            len(agentic_symbols),
            agentic_pack.get("cio_directive"),
            float(agentic_pack.get("agentic_budget_fraction") or 1.0),
        )
    else:
        logger.info("Agentic queue unavailable or empty; using deterministic-only screener tiers.")

    # LLM is optional/advisory. By default runtime config sets llm.provider=none,
    # so we should not block screening on a local Ollama call.
    llm_cfg = {}
    try:
        llm_cfg = get_llm_config() or {}
    except Exception:
        llm_cfg = {}
    llm_provider = str(llm_cfg.get("provider") or "").strip().lower()
    disable_llm = str(os.getenv("SCREENER_DISABLE_LLM", "0") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    } or llm_provider == "none"

    def _norm_stock(x):
        # Accept either {"ticker": "..."} objects or plain ticker strings.
        if isinstance(x, str):
            return {"ticker": x}
        if isinstance(x, dict) and x.get("ticker"):
            return x
        return None

    priority_tiers = watchlist_payload.get("priority_tiers")
    if priority_tiers:
        tiers = []
        for tier in priority_tiers:
            stocks = None
            if isinstance(tier, dict):
                stocks = tier.get("stocks") or tier.get("quality_stocks") or tier.get("tickers")
            elif isinstance(tier, list):
                stocks = tier
            if not stocks:
                continue
            normed = [_norm_stock(s) for s in stocks]
            normed = [s for s in normed if s is not None]
            if normed:
                tiers.append(normed)
    else:
        # Backward compatible fallback: flat list
        watchlist_flat = watchlist_payload.get("quality_stocks") or []
        normed = [_norm_stock(s) for s in watchlist_flat]
        normed = [s for s in normed if s is not None]
        tiers = [normed] if normed else []

    # If priority tiers are configured, but `quality_stocks` contains extra tickers,
    # append the remaining tickers into the last tier.
    # This lets us expand the universe (e.g., 100 -> 200) without rewriting tier lists.
    try:
        quality_flat = watchlist_payload.get("quality_stocks") or []
        quality_normed = [_norm_stock(s) for s in quality_flat]
        quality_normed = [s for s in quality_normed if s is not None]

        if tiers and quality_normed:
            existing = {s.get("ticker") for tier in tiers for s in tier if s.get("ticker")}
            existing.discard(None)
            remaining = [s for s in quality_normed if s.get("ticker") and s.get("ticker") not in existing]
            # Extend only the last tier to keep scan-order priority intact.
            if remaining:
                tiers[-1].extend(remaining)
    except Exception:
        # Telemetry should never break screening.
        pass

    # Inject agentic symbols as highest-priority tier before license capping.
    # Existing deterministic tiers remain and will still run.
    if agentic_symbols:
        seen_agentic = set()
        agentic_tier = []
        for row in agentic_symbols:
            t = str(row.get("ticker") or "").strip().upper()
            if not t or t in seen_agentic:
                continue
            seen_agentic.add(t)
            agentic_tier.append({"ticker": t, "__source": "agentic", "__agentic_meta": row})
        if agentic_tier:
            tiers = [agentic_tier] + tiers

    # License tier: cap distinct tickers (Starter/Pro/Enterprise); master is effectively unlimited.
    universe_cap_meta: dict = {}
    try:
        from utils.license_gates import apply_license_universe_cap

        tiers, universe_cap_meta = apply_license_universe_cap(tiers)
        if universe_cap_meta.get("universe_truncated"):
            logger.warning(
                "Universe trimmed by license: max=%s configured=%s using=%s",
                universe_cap_meta.get("license_max_universe"),
                universe_cap_meta.get("universe_configured_before_cap"),
                universe_cap_meta.get("universe_after_cap"),
            )
    except Exception as exc:
        logger.warning("License universe cap skipped: %s", exc)

    policy = get_profile_bundle()
    screening_cfg = policy.get("screening") or {}
    max_tiers_to_scan = int(
        screening_cfg.get("max_priority_tiers_to_scan")
        or watchlist_payload.get("max_priority_tiers_to_scan")
        or os.getenv("SCREENER_MAX_PRIORITY_TIERS")
        or 5
    )
    target_candidates = int(
        screening_cfg.get("target_candidates_per_run")
        or watchlist_payload.get("screening_target_candidates_per_run")
        or os.getenv("SCREENING_TARGET_CANDIDATES")
        or 2
    )
    prefilter_workers = int(watchlist_payload.get("prefilter_workers") or os.getenv("SCREENER_PREFILTER_WORKERS") or 6)
    max_runtime_seconds = float(watchlist_payload.get("max_screening_runtime_seconds") or os.getenv("SCREENER_MAX_RUNTIME_SECONDS") or 180)

    risk_doc = _read_daily_risk_params(DATA_DIR)
    market_regime = str(risk_doc.get("regime") or "").strip().upper() or "RANGING"
    ranging_extremes = str(os.getenv("FORTRESS_SCREENER_REGIME_RSI_EXTREMES", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    reject_samples: list[dict[str, Any]] = []

    def _tier_params(tier_idx: int) -> dict:
        """
        Step-wise relaxation of numeric prefilter thresholds by tier.
        Keeps Tier 1 strict, and broadens only if earlier tiers produce too few/zero candidates.
        """
        if market_regime in ("TRENDING_BULL", "BULL"):
            tier_profiles = {
                1: {"drop_min": -6, "drop_max": 2, "rsi_threshold": 50, "volume_ratio_min": 0.85},
                2: {"drop_min": -10, "drop_max": 3, "rsi_threshold": 52, "volume_ratio_min": 0.75},
                3: {"drop_min": -15, "drop_max": 4, "rsi_threshold": 55, "volume_ratio_min": 0.65},
                4: {"drop_min": -20, "drop_max": 5, "rsi_threshold": 58, "volume_ratio_min": 0.55},
                5: {"drop_min": -25, "drop_max": 6, "rsi_threshold": 60, "volume_ratio_min": 0.50},
            }
        else:
            tier_profiles = {
                1: {"drop_min": -15, "drop_max": -5, "rsi_threshold": 40, "volume_ratio_min": 1.5},
                2: {"drop_min": -25, "drop_max": -1, "rsi_threshold": 45, "volume_ratio_min": 1.3},
                3: {"drop_min": -35, "drop_max": 0, "rsi_threshold": 50, "volume_ratio_min": 1.2},
                4: {"drop_min": -45, "drop_max": 0, "rsi_threshold": 52, "volume_ratio_min": 1.1},
                5: {"drop_min": -50, "drop_max": 5, "rsi_threshold": 55, "volume_ratio_min": 1.0},
            }
        prof = tier_profiles.get(tier_idx) or tier_profiles[5]
        merged = dict(params)
        merged.update(prof)
        return merged

    # Compact pre-filter telemetry used by the dashboard.
    # This is meant to be robust/resilient; failures to write telemetry should not break screening.
    universe_size = 0
    filter_counts = {
        "insufficient_data": 0,
        "zero_open": 0,
        "insufficient_days_for_rsi": 0,
        "zero_mean_volume": 0,
        "drop_criteria": 0,
        "rsi_criteria": 0,
        "volume_criteria": 0,
        "scan_error": 0,
    }
    passed_all_filters = 0  # number of tickers that passed numeric prefilter (not heavy LLM)

    candidates = []
    start_ts = time.time()
    screening_started_at = datetime.now().isoformat()
    tier_telemetry: list[dict] = []
    tiers_configured = len(tiers)
    tiers_scanned = 0
    tier_stop_reason = "none"
    agentic_candidate_count = 0
    deterministic_candidate_count = 0

    def _prefilter_one(stock, params_for_tier: dict):
        ticker = stock["ticker"]
        # Fetch Yahoo Finance data
        stock_data = yf.Ticker(ticker).history(period="1mo")

        if len(stock_data) < 2:
            return {"status": "reject", "reason": "insufficient_data"}

        # Calculate metrics with validation
        latest_open = stock_data["Open"].iloc[-1]
        latest_close = stock_data["Close"].iloc[-1]

        if latest_open == 0:
            return {"status": "reject", "reason": "zero_open"}

        # Sign convention:
        # - drop_pct is NEGATIVE when the stock dropped from open -> close
        # - filter thresholds are tuned for negative "drop" values (e.g. -15%..-5%)
        drop_pct = (latest_close - latest_open) / latest_open * 100

        # Calculate RSI with validation
        if len(stock_data) < 15:
            return {"status": "reject", "reason": "insufficient_days_for_rsi"}

        rsi = calculate_rsi(stock_data["Close"], 14)
            
        # Calculate volume ratio
        mean_volume = stock_data["Volume"].mean()
        if mean_volume == 0:
            return {"status": "reject", "reason": "zero_mean_volume"}

        volume_ratio = stock_data["Volume"].iloc[-1] / mean_volume

        # Check if stock meets ALL criteria before calling heavier analysis
        meets_drop_criteria = params_for_tier["drop_min"] <= drop_pct <= params_for_tier["drop_max"]
        if ranging_extremes and market_regime == "RANGING":
            meets_rsi_criteria = (rsi < 35) or (rsi > 65)
        else:
            meets_rsi_criteria = rsi < params_for_tier["rsi_threshold"]
        meets_volume_criteria = volume_ratio > params_for_tier["volume_ratio_min"]

        def _sample(reason: str) -> None:
            if len(reject_samples) >= 64:
                return
            reject_samples.append(
                {
                    "ticker": ticker,
                    "reason": reason,
                    "rsi": round(float(rsi), 4),
                    "drop_pct": round(float(drop_pct), 4),
                    "volume_ratio": round(float(volume_ratio), 4),
                    "rsi_rule": "ranging_extremes_lt35_or_gt65"
                    if (ranging_extremes and market_regime == "RANGING")
                    else f"lt_{params_for_tier['rsi_threshold']}",
                    "drop_band": [params_for_tier["drop_min"], params_for_tier["drop_max"]],
                    "regime": market_regime,
                }
            )

        if not meets_drop_criteria:
            _sample("drop_criteria")
            return {"status": "reject", "reason": "drop_criteria"}
        if not meets_rsi_criteria:
            _sample("rsi_criteria")
            return {"status": "reject", "reason": "rsi_criteria"}
        if not meets_volume_criteria:
            _sample("volume_criteria")
            return {"status": "reject", "reason": "volume_criteria"}

        return {
            "status": "pass",
            "ticker": ticker,
            "stock_data": stock_data,
            # Used downstream by entry evaluation (options ROI sizing, etc.)
            "current_price": float(latest_close),
            "drop_pct": float(drop_pct),
            "rsi": float(rsi),
            "volume_ratio": float(volume_ratio),
        }

    convergence_mode = get_flag_mode("FORTRESS_UPLIFT_CONVERGENCE_MODE")
    throughput_mode = get_flag_mode("FORTRESS_UPLIFT_THROUGHPUT_MODE")
    for tier_idx, tier_stocks in enumerate(tiers[:max_tiers_to_scan], start=1):
        tier_start_ts = time.time()
        if time.time() - start_ts > max_runtime_seconds:
            logger.warning(f"Screening runtime cap hit; stopping after tier {tier_idx-1}.")
            tier_stop_reason = "runtime_cap_hit"
            break

        tiers_scanned += 1
        tier_prefilter_passed = 0
        # Data hygiene guard: reject malformed symbols before network calls.
        # tier entries may be dicts or plain ticker strings; (s or {}).get breaks on str s.
        valid_tier = []
        invalid_symbol_count = 0
        for s in tier_stocks:
            ns = _norm_stock(s)
            if not ns:
                invalid_symbol_count += 1
                continue
            sym = str(ns.get("ticker") or "").strip().upper()
            if sym and sym.replace("-", "").isalnum():
                valid_tier.append({"ticker": sym})
            else:
                invalid_symbol_count += 1
        if invalid_symbol_count:
            filter_counts["scan_error"] += invalid_symbol_count
        tier_prefilter_screened = len(valid_tier)

        # Prefilter stage (numeric only) in bounded parallel threads.
        passed_items = []
        tier_universe = valid_tier
        universe_size += len(tier_universe)
        tier_params = _tier_params(tier_idx)

        prefilter_start_ts = time.time()
        with ThreadPoolExecutor(max_workers=prefilter_workers) as ex:
            futures = [ex.submit(_prefilter_one, s, tier_params) for s in tier_universe]
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception:
                    filter_counts["scan_error"] += 1
                    continue

                if res.get("status") == "pass":
                    passed_all_filters += 1
                    tier_prefilter_passed += 1
                    passed_items.append(res)
                else:
                    reason = res.get("reason") or "scan_error"
                    if reason in filter_counts:
                        filter_counts[reason] += 1
                    else:
                        filter_counts["scan_error"] += 1

        prefilter_duration_seconds = round(time.time() - prefilter_start_ts, 3)

        # Heavy stage (news + analysis + chart patterns) sequentially until we hit the target.
        heavy_start_ts = time.time()
        tier_candidates_added = 0
        for item in passed_items:
            if len(candidates) >= target_candidates:
                break
            ticker = item["ticker"]
            stock_data = item["stock_data"]
            drop_pct = item["drop_pct"]
            rsi = item["rsi"]
            volume_ratio = item["volume_ratio"]
            latest_close = item["current_price"]

            try:
                news_headlines = get_news_headlines(ticker, 3)
                # Only call local LLM when enabled. Otherwise keep analysis bounded so
                # downstream entry sizing still has a confidence value.
                if disable_llm:
                    analysis = {
                        "classification": "UNCERTAIN",
                        "confidence": 0.5,
                        "reasoning": "LLM disabled (provider=none or SCREENER_DISABLE_LLM=1).",
                    }
                else:
                    analysis = analyze_stock_drop(ticker, news_headlines, {"drop_pct": drop_pct, "rsi": rsi})
                pattern_result = analyze_chart_patterns(ticker, price_data=stock_data, period="3mo", interval="1d")

                vision_signal = None
                if pattern_result.get("success"):
                    vision_signal = pattern_to_signal(pattern_result.get("patterns") or [])
                    signal_type = vision_signal.get("signal")
                    signal_conf = vision_signal.get("confidence")
                    signal_reasons = ", ".join((vision_signal.get("reasoning") or [])[:2])

                    # Bonus points if vision agrees (BUY or STRONG_BUY)
                    if signal_type in ["BUY", "STRONG_BUY"]:
                        original_confidence = analysis.get("confidence", 0)
                        analysis["confidence"] = min(original_confidence + 0.10, 1.0)
                    elif signal_type == "AVOID":
                        original_confidence = analysis.get("confidence", 0)
                        analysis["confidence"] = max(original_confidence - 0.15, 0.0)

                # Determine signal source for auditability.
                source_label = "deterministic"
                agentic_meta = {}
                for s in tier_stocks:
                    ns = _norm_stock(s)
                    if not ns:
                        continue
                    if str(ns.get("ticker") or "").strip().upper() == ticker:
                        source_label = str(ns.get("__source") or "deterministic")
                        agentic_meta = ns.get("__agentic_meta") or {}
                        break

                cand = {
                    "ticker": ticker,
                    "current_price": latest_close,
                    "drop_pct": drop_pct,
                    "rsi": rsi,
                    "volume_ratio": volume_ratio,
                    "news": news_headlines,
                    "analysis": analysis,
                    "vision_signal": vision_signal,
                    "signal_source": source_label,
                }
                if convergence_mode >= 1:
                    conv = score_candidate(cand, regime_label="UNKNOWN")
                    cand["convergence"] = conv
                if source_label == "agentic":
                    cand["agentic_meta"] = agentic_meta
                candidates.append(cand)
                if source_label == "agentic":
                    agentic_candidate_count += 1
                    logger.info("%s: candidate accepted via AGENTIC priority path", ticker)
                else:
                    deterministic_candidate_count += 1
                    logger.info("%s: candidate accepted via deterministic path", ticker)
                tier_candidates_added += 1
            except Exception as e:
                logger.error(f"Error heavy-analyzing {ticker}: {type(e).__name__}: {str(e)}")
                logger.error(f"Full traceback for {ticker}:\n{traceback.format_exc()}")
                continue

        heavy_duration_seconds = round(time.time() - heavy_start_ts, 3)
        tier_duration_seconds = round(time.time() - tier_start_ts, 3)
        tier_telemetry.append({
            "tier_index": tier_idx,
            "tier_screened_tickers": tier_prefilter_screened,
            "tier_prefilter_passed": tier_prefilter_passed,
            "tier_candidates_added": tier_candidates_added,
            "prefilter_duration_seconds": prefilter_duration_seconds,
            "heavy_duration_seconds": heavy_duration_seconds,
            "tier_duration_seconds": tier_duration_seconds,
        })

        if len(candidates) >= target_candidates:
            tier_stop_reason = "target_reached"
            break

    # Persist compact screening telemetry for the dashboard.
    # Never fail the screener if telemetry write fails.
    try:
        screening_duration_seconds = round(time.time() - start_ts, 3)
        Path("data").mkdir(parents=True, exist_ok=True)
        meta_path = Path("data") / "last_screening_meta.json"
        convergence_scores = []
        if convergence_mode >= 1:
            for c in candidates:
                try:
                    convergence_scores.append(float(((c.get("convergence") or {}).get("convergence_score"))))
                except Exception:
                    pass
        throughput = recommend_thresholds(
            current_params=params,
            candidates_found=len(candidates),
            target_min=2,
            target_max=5,
        )
        if throughput.get("changed") and (
            throughput_mode >= 2 or (throughput_mode >= 1 and len(candidates) == 0)
        ):
            try:
                applied = throughput.get("recommended_params") or params
                with open(CURRENT_PARAMS_FILE, "w", encoding="utf-8") as f:
                    json.dump(applied, f, indent=2)
                params.update(applied)
            except Exception:
                pass
        try:
            from utils.pipeline_health import record_screening_outcome

            record_screening_outcome(candidates_found=len(candidates))
        except Exception:
            pass

        meta = {
            "timestamp": datetime.now().isoformat(),
            "policy_profile": policy.get("active_profile"),
            "screening_started_at": screening_started_at,
            "screening_finished_at": datetime.now().isoformat(),
            "screening_duration_seconds": screening_duration_seconds,
            "universe_license_cap": universe_cap_meta,
            "universe_size": universe_size,
            "screened_tickers": universe_size,
            "candidates_found": len(candidates),
            "passed_all_filters": passed_all_filters,
            "filter_counts": filter_counts,
            "market_regime_at_screen": market_regime,
            "prefilter_reject_samples": reject_samples[:40],
            "tiers_configured": tiers_configured,
            "tiers_scanned": tiers_scanned,
            "tier_stop_reason": tier_stop_reason,
            "screening_target_candidates_per_run": target_candidates,
            "prefilter_workers": prefilter_workers,
            "max_screening_runtime_seconds": max_runtime_seconds,
            "tier_telemetry": tier_telemetry,
            "uplift": {
                "convergence_mode": convergence_mode,
                "convergence_scored_count": len(convergence_scores),
                "convergence_score_avg": round(sum(convergence_scores) / len(convergence_scores), 3)
                if convergence_scores
                else None,
                "throughput_mode": throughput_mode,
                "throughput_controller": throughput,
            },
            "agentic": {
                "scout_timestamp": agentic_pack.get("scout_timestamp"),
                "analyst_timestamp": agentic_pack.get("analyst_timestamp"),
                "cio_timestamp": agentic_pack.get("cio_timestamp"),
                "cio_directive": agentic_pack.get("cio_directive"),
                "agentic_budget_fraction": agentic_pack.get("agentic_budget_fraction"),
                "agentic_symbols_loaded": len(agentic_symbols),
                "agentic_candidates_output": agentic_candidate_count,
                "deterministic_candidates_output": deterministic_candidate_count,
            },
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
    except Exception:
        pass

    if convergence_mode >= 2:
        return sorted(
            candidates,
            key=lambda x: float(((x.get("convergence") or {}).get("convergence_score")) or 0.0),
            reverse=True,
        )
    return sorted(candidates, key=lambda x: x["analysis"]["confidence"], reverse=True)

def calculate_rsi(prices, n=14):
    """Calculate the Relative Strength Index (RSI)"""
    try:
        deltas = prices.diff()
        seed = deltas[:n+1]
        up = seed[seed >= 0].sum() / n
        down = -seed[seed < 0].sum() / n
        
        if down == 0:
            return 100.0  # If no down movement, RSI is 100
            
        rs = up / down
        rsi = 100 - (100 / (1 + rs))
        
        # Handle if rsi is a Series, get the last value
        if hasattr(rsi, 'iloc'):
            return rsi.iloc[-1]
        return rsi
    except Exception as e:
        logger.error(f"Error calculating RSI: {type(e).__name__}: {str(e)}")
        raise

def get_news_headlines(ticker, limit):
    """Fetch top news headlines for a stock from Yahoo Finance"""
    try:
        news = yf.Ticker(ticker).get_news()
        headlines = []
        for h in news[:limit]:
            if 'title' in h:
                headlines.append(h['title'])
            else:
                logger.warning(f"News item for {ticker} missing 'title' field: {h.keys()}")
        return headlines
    except Exception as e:
        logger.warning(f"Could not fetch news for {ticker}: {type(e).__name__}: {str(e)}")
        return []


# --- Recursive multi-layer screener (upstream of critique loop) ---

_RECURSIVE_LOG_PATH = Path("logs") / "screener.log"


def _recursive_screener_enabled() -> bool:
    return os.environ.get("FORTRESS_RECURSIVE_SCREENER_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _recursive_llm_dry_run() -> bool:
    return os.environ.get("FORTRESS_RECURSIVE_SCREENER_LLM_DRY_RUN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _et_timestamp_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")


def _recursive_screener_log(line: str) -> None:
    """Append human-readable recursive-screener lines to logs/screener.log."""
    try:
        _RECURSIVE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamped = f"[{_et_timestamp_str()}] {line}"
        with open(_RECURSIVE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(stamped + "\n")
    except Exception:
        pass


def _parse_json_llm(text: str) -> dict[str, Any] | None:
    if not text or not str(text).strip():
        return None
    t = str(text).strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
        if m:
            t = m.group(1).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", t):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _load_positions_list(data_dir: Path) -> list[dict]:
    p = data_dir / "positions.json"
    try:
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("positions", [])
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _read_daily_risk_params(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "daily_risk_params.json"
    try:
        if not path.exists():
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _today_realized_pnl_usd(data_dir: Path) -> float:
    path = data_dir / "pnl_ledger.jsonl"
    if not path.exists():
        return 0.0
    today = datetime.now().date()
    total = 0.0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ts = str(row.get("timestamp") or "")
            if len(ts) >= 10:
                try:
                    d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                except ValueError:
                    continue
                if d != today:
                    continue
            try:
                total += float(row.get("pnl") or 0.0)
            except (TypeError, ValueError):
                pass
    except Exception:
        return 0.0
    return total


def _rth_bad_window_et() -> bool:
    """First 15m after 9:30 or last 15m before 16:00 US/Eastern."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    t = now.time()
    open_m = datetime.strptime("09:30", "%H:%M").time()
    bad_early = datetime.strptime("09:45", "%H:%M").time()
    bad_late_start = datetime.strptime("15:45", "%H:%M").time()
    close_m = datetime.strptime("16:00", "%H:%M").time()
    return (open_m <= t < bad_early) or (bad_late_start <= t < close_m)


def _earnings_within_days(ticker: str, days: int = 2) -> tuple[bool, str]:
    try:
        tk = yf.Ticker(ticker)
        cal = getattr(tk, "calendar", None)
        if cal is not None and hasattr(cal, "empty") and not cal.empty:
            # yfinance calendar index sometimes holds next earnings date
            pass
        ed = getattr(tk, "earnings_dates", None)
        if ed is not None and hasattr(ed, "empty") and not ed.empty:
            next_idx = ed.index.min()
            if hasattr(next_idx, "to_pydatetime"):
                nd = next_idx.to_pydatetime().date()
            else:
                nd = next_idx.date() if hasattr(next_idx, "date") else None
            if nd:
                delta = (nd - datetime.now().date()).days
                if 0 <= delta <= days:
                    return True, f"earnings in {delta}d"
    except Exception:
        pass
    return False, ""


class RecursiveScreener:
    """
    Layered filter: hard rules → technical score → recursive LLM → portfolio context.
    Disabled unless FORTRESS_RECURSIVE_SCREENER_ENABLED=1 (passthrough).
    """

    def __init__(
        self,
        *,
        min_layer2_score: float = 65.0,
        data_dir: Path | None = None,
    ) -> None:
        self.min_layer2_score = float(min_layer2_score)
        self.data_dir = data_dir or DATA_DIR
        self._router = None

    def _router_lazy(self):
        if self._router is None:
            from utils.llm_router import LLMRouter

            self._router = LLMRouter()
        return self._router

    def screen_candidates(
        self,
        candidates: list[dict],
        *,
        portfolio_nav: float | None = None,
    ) -> list[dict]:
        # ── Regime hook (read-only) ──────────────────────────────────────────
        _regime_min_score = None
        _regime_halt = False
        try:
            if os.path.exists("data/daily_risk_params.json"):
                from utils.atomic_json import read_json

                _rp = read_json("data/daily_risk_params.json", default={})
                _regime_params = _rp.get("regime_params", {})
                if _regime_params.get("halt_new_entries"):
                    _regime_halt = True
                if _regime_params.get("screener_min_score") is not None:
                    _regime_min_score = float(_regime_params["screener_min_score"])
        except Exception as _e:
            pass  # Silent — never interrupt screening

        if _regime_halt:
            try:
                from utils.fortress_logger import append_log

                append_log("screener.log", f"[REGIME] halt_new_entries=True — returning 0 candidates")
            except Exception:
                pass
            return []

        # Use regime-adjusted min score if available, else existing default
        _l2_min_score = _regime_min_score if _regime_min_score is not None \
            else getattr(self, 'min_score', 65)
        # ── End regime hook ──────────────────────────────────────────────────

        if not _recursive_screener_enabled():
            return list(candidates)

        if not candidates:
            _recursive_screener_log("RecursiveScreener | no input candidates")
            return []

        rp = _read_daily_risk_params(self.data_dir)
        max_concurrent = int(rp.get("max_concurrent_positions") or rp.get("max_new_positions") or 5)
        max_concurrent = max(1, min(5, max_concurrent))
        max_per_sector = int(rp.get("max_positions_per_sector") or 2)
        max_corr = float(rp.get("max_basket_correlation") or 0.85)
        daily_pnl_halt_pct = float(rp.get("halt_new_entries_daily_pnl_pct") or -0.02)
        vix_max = rp.get("vix_max_for_new_entries")
        try:
            vix_max_f = float(vix_max) if vix_max is not None else None
        except (TypeError, ValueError):
            vix_max_f = None

        nav = float(portfolio_nav) if portfolio_nav and portfolio_nav > 0 else 100_000.0
        today_pnl = _today_realized_pnl_usd(self.data_dir)
        daily_pnl_frac = today_pnl / nav
        if daily_pnl_frac < daily_pnl_halt_pct:
            _recursive_screener_log(
                f"GLOBAL | L4: HALT new entries — daily realized P&L {daily_pnl_frac*100:.2f}% "
                f"vs floor {daily_pnl_halt_pct*100:.2f}% (nav≈${nav:,.0f})"
            )
            return []

        if vix_max_f is not None:
            try:
                vix = float(yf.Ticker("^VIX").history(period="5d")["Close"].iloc[-1])
                if vix > vix_max_f:
                    _recursive_screener_log(
                        f"GLOBAL | L4: HALT — VIX {vix:.1f} > limit {vix_max_f:.1f} (daily_risk_params)"
                    )
                    return []
            except Exception:
                pass

        open_positions = _load_positions_list(self.data_dir)
        approved: list[dict] = []

        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            sym = str(cand.get("ticker") or "").strip().upper()
            if not sym:
                continue

            l1_ok, l1_reason = self._layer1_hard_filters(sym, cand)
            if not l1_ok:
                _recursive_screener_log(
                    f"{sym} | L1: FAIL | REJECTED at L1 — {l1_reason}"
                )
                continue

            tech, card = self.score_technical(cand)
            if tech < _l2_min_score:
                hints = []
                if float(card.get("volume_score") or 0) < 45:
                    hints.append("weak volume")
                if float(card.get("trend_score") or 0) < 45:
                    hints.append("poor trend alignment")
                if float(card.get("rsi_macd_score") or 0) < 45:
                    hints.append("weak momentum")
                if float(card.get("tod_score") or 100) < 50:
                    hints.append("poor time-of-day score")
                hint_str = ", ".join(hints) if hints else str(card.get("l2_detail") or "below threshold")
                _recursive_screener_log(
                    f"{sym} | L1: PASS | L2: {tech:.0f}/100 | REJECTED at L2 — {hint_str}"
                )
                continue

            l3 = self.run_llm_filter(cand)
            if not l3.get("pass"):
                l3_reason = l3.get("fail_log") or str(l3.get("reason") or "LLM FAIL")
                _recursive_screener_log(
                    f"{sym} | L1: PASS | L2: {tech:.0f}/100 | L3: FAIL — {l3_reason}"
                )
                continue

            conv = l3.get("final_conviction", "?")
            l4_ok, l4_reason = self.check_portfolio_context(
                cand,
                open_positions,
                max_concurrent=max_concurrent,
                max_per_sector=max_per_sector,
                max_correlation=max_corr,
            )
            if not l4_ok:
                _recursive_screener_log(
                    f"{sym} | L1: PASS | L2: {tech:.0f}/100 | L3: PASS (conviction {conv}/10) "
                    f"| L4: FAIL — {l4_reason}"
                )
                continue

            out = dict(cand)
            out["recursive_screener"] = {
                "layer1": "PASS",
                "layer2_score": round(tech, 2),
                "layer2_card": card,
                "layer3": l3,
                "layer4": "PASS",
            }
            approved.append(out)
            _recursive_screener_log(
                f"{sym} | L1: PASS | L2: {tech:.0f}/100 | L3: PASS (conviction {conv}/10) "
                f"| L4: PASS | → forwarded to critique loop"
            )

        approved.sort(
            key=lambda x: float((x.get("recursive_screener") or {}).get("layer2_score") or 0),
            reverse=True,
        )
        return approved

    def _layer1_hard_filters(self, ticker: str, cand: dict) -> tuple[bool, str]:
        px = float(cand.get("current_price") or 0)
        if px < 3.0:
            return False, f"price ${px:.2f} below $3 min"
        if px > 2500.0:
            return False, f"price ${px:.2f} above sanity max"

        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist is None or hist.empty:
                return False, "no recent OHLCV"
            last_vol = float(hist["Volume"].iloc[-1])
            if last_vol < 50_000:
                return False, f"volume {last_vol:.0f} below 50k"
            spread_proxy = float(
                (hist["High"].iloc[-1] - hist["Low"].iloc[-1]) / max(hist["Close"].iloc[-1], 1e-9)
            )
            if spread_proxy > 0.12:
                return False, f"wide range {spread_proxy*100:.1f}% of close (halt/spread risk)"
        except Exception as e:
            return False, f"market data error: {e}"

        near_earn, er = _earnings_within_days(ticker, days=2)
        if near_earn:
            return False, er or "earnings proximity"

        return True, ""

    def score_technical(self, candidate: dict) -> tuple[float, dict[str, Any]]:
        """
        Weighted 0–100: trend/EMA 25%, volume 20%, RSI+MACD 20%, sector vs SPY 15%,
        ATR profile 10%, time-of-day 10% (already hard-gated in L1 when bad window).
        """
        ticker = str(candidate.get("ticker") or "").strip().upper()
        card: dict[str, Any] = {"ticker": ticker}
        try:
            hist = yf.Ticker(ticker).history(period="3mo", interval="1d")
            spy = yf.Ticker("SPY").history(period="3mo", interval="1d")
            if hist is None or hist.empty or len(hist) < 55:
                return 0.0, {**card, "l2_detail": "insufficient history for EMA/MACD"}

            close = hist["Close"]
            vol = hist["Volume"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            last = float(close.iloc[-1])
            e20 = float(ema20.iloc[-1])
            e50 = float(ema50.iloc[-1])
            if last >= e20 >= e50:
                trend_score = 100.0
            elif last >= e20:
                trend_score = 70.0
            elif last >= e50:
                trend_score = 45.0
            else:
                trend_score = 25.0

            ma10 = vol.rolling(10).mean()
            vr = float(vol.iloc[-1] / max(ma10.iloc[-1], 1.0))
            vol_score = max(0.0, min(100.0, (vr - 0.6) / 1.4 * 100.0))

            rsi_series = calculate_rsi(close, 14)
            rsi_last = float(rsi_series.iloc[-1]) if hasattr(rsi_series, "iloc") else float(rsi_series)
            rsi_score = max(0.0, min(100.0, (55.0 - rsi_last) / 30.0 * 100.0))

            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            sig = macd_line.ewm(span=9, adjust=False).mean()
            macd_bull = float(macd_line.iloc[-1]) > float(sig.iloc[-1])
            macd_score = 80.0 if macd_bull else 35.0
            combo_rsi_macd = 0.5 * rsi_score + 0.5 * macd_score

            ret_stock = float(close.iloc[-1] / max(close.iloc[-6], 1e-9) - 1.0)
            ret_spy = 0.0
            if spy is not None and not spy.empty and len(spy["Close"]) > 6:
                sc = spy["Close"]
                ret_spy = float(sc.iloc[-1] / max(sc.iloc[-6], 1e-9) - 1.0)
            rel = (ret_stock - ret_spy) * 100.0
            sector_score = max(0.0, min(100.0, 50.0 + rel * 8.0))

            tr = hist["High"] - hist["Low"]
            atr_pct = float(tr.rolling(14).mean().iloc[-1] / max(last, 1e-9))
            if 0.01 <= atr_pct <= 0.04:
                atr_score = 100.0
            elif atr_pct < 0.01:
                atr_score = 40.0
            else:
                atr_score = max(20.0, 100.0 - (atr_pct - 0.04) * 800.0)

            tod_score = 0.0 if _rth_bad_window_et() else 100.0

            total = (
                0.25 * trend_score
                + 0.20 * vol_score
                + 0.20 * combo_rsi_macd
                + 0.15 * sector_score
                + 0.10 * atr_score
                + 0.10 * tod_score
            )
            card.update(
                {
                    "trend_score": round(trend_score, 1),
                    "volume_score": round(vol_score, 1),
                    "rsi_macd_score": round(combo_rsi_macd, 1),
                    "rel_spy_score": round(sector_score, 1),
                    "atr_score": round(atr_score, 1),
                    "tod_score": round(tod_score, 1),
                    "rsi": round(rsi_last, 2),
                    "volume_ratio_proxy": round(vr, 2),
                    "l2_detail": "composite technical",
                }
            )
            return total, card
        except Exception as e:
            return 0.0, {**card, "l2_detail": str(e)}

    def run_llm_filter(self, candidate: dict) -> dict[str, Any]:
        """Three-iteration loop: DeepSeek → xAI → DeepSeek; PASS/FAIL."""
        ticker = str(candidate.get("ticker") or "").strip().upper()
        if _recursive_llm_dry_run():
            return {
                "pass": True,
                "reason": "dry_run",
                "final_conviction": 7,
                "iter1": {},
                "iter2": {},
                "iter3": {},
            }

        headlines = candidate.get("news") or []
        if not isinstance(headlines, list):
            headlines = []
        news_blob = json.dumps(headlines[:8], default=str)
        base = json.dumps(
            {
                "ticker": ticker,
                "current_price": candidate.get("current_price"),
                "rsi": candidate.get("rsi"),
                "volume_ratio": candidate.get("volume_ratio"),
                "drop_pct": candidate.get("drop_pct"),
            },
            default=str,
        )
        r = self._router_lazy()

        def _api_fail(msg: str) -> dict[str, Any]:
            return {
                "pass": False,
                "reason": msg,
                "fail_log": msg,
                "final_conviction": 0,
                "iter1": {},
                "iter2": {},
                "iter3": {},
            }

        p1 = (
            "You are a disciplined equity analyst. Given the candidate snapshot and news titles, "
            "output ONLY valid JSON (no markdown):\n"
            '{"narrative": "string", "conviction": <1-10 integer>}\n\n'
            f"DATA: {base}\nNEWS: {news_blob}"
        )
        raw1 = r.call_deepseek(p1)
        if str(raw1 or "").strip().startswith("Error:"):
            return _api_fail(raw1.strip()[:200])
        o1 = _parse_json_llm(raw1 or "") or {"narrative": "parse_fail", "conviction": 5}
        c1 = int(o1.get("conviction") or 5)
        c1 = max(1, min(10, c1))

        p2 = (
            "You are a skeptical fact-checker. Cross-check the narrative vs news. "
            "Output ONLY valid JSON:\n"
            '{"stance": "support" or "contradict", "notes": "string"}\n\n'
            f"NARRATIVE: {json.dumps(o1, default=str)}\nNEWS: {news_blob}"
        )
        raw2 = r.call_xai(p2)
        if str(raw2 or "").strip().startswith("Error:"):
            return _api_fail(raw2.strip()[:200])
        o2 = _parse_json_llm(raw2 or "") or {"stance": "support", "notes": ""}
        stance = str(o2.get("stance", "support")).lower()

        p3 = (
            "Final gate: adjust conviction given the contradiction check. "
            "Output ONLY valid JSON:\n"
            '{"final_conviction": <1-10>, "verdict": "PASS" or "FAIL"}\n\n'
            f"ITER1: {json.dumps(o1, default=str)}\nITER2: {json.dumps(o2, default=str)}"
        )
        raw3 = r.call_deepseek(p3)
        if str(raw3 or "").strip().startswith("Error:"):
            return _api_fail(raw3.strip()[:200])
        o3 = _parse_json_llm(raw3 or "") or {"final_conviction": c1, "verdict": "FAIL"}
        fc = int(o3.get("final_conviction") or c1)
        fc = max(1, min(10, fc))
        verdict = str(o3.get("verdict", "FAIL")).upper()
        if stance == "contradict" and verdict == "PASS" and fc < 8:
            verdict = "FAIL"
        ok = verdict == "PASS" and fc >= 6
        notes2 = str(o2.get("notes") or "")[:160]
        fail_log = ""
        if not ok:
            if stance == "contradict":
                fail_log = f"news contradicts technical setup — {notes2 or 'contradict stance'}"
            else:
                fail_log = f"verdict={verdict}, conviction={fc}/10"
        return {
            "pass": ok,
            "reason": o3 if not ok else "ok",
            "fail_log": fail_log,
            "final_conviction": fc,
            "iter1": o1,
            "iter2": o2,
            "iter3": o3,
        }

    def check_portfolio_context(
        self,
        candidate: dict,
        open_positions: list[dict],
        *,
        max_concurrent: int = 5,
        max_per_sector: int = 2,
        max_correlation: float = 0.85,
    ) -> tuple[bool, str]:
        if len(open_positions) >= max_concurrent:
            return False, f"max concurrent positions ({max_concurrent})"

        sym = str(candidate.get("ticker") or "").strip().upper()

        def _pos_underlying_key(p: dict) -> str:
            if str(p.get("type", "")).upper() == "OPTION":
                return str(p.get("underlying_ticker") or "").strip().upper()
            return str(p.get("ticker") or "").strip().upper()

        if any(_pos_underlying_key(p) == sym for p in open_positions if isinstance(p, dict)):
            return False, "already hold same ticker / underlying"

        sector = None
        try:
            info = yf.Ticker(sym).info or {}
            sector = str(info.get("sector") or info.get("industry") or "Unknown")
        except Exception:
            sector = "Unknown"

        def _pos_sector(p: dict) -> str:
            t = str(p.get("ticker") or "")
            if p.get("type") == "OPTION":
                u = str(p.get("underlying_ticker") or "")
                if u:
                    t = u
            try:
                inf = yf.Ticker(t).info or {}
                return str(inf.get("sector") or inf.get("industry") or "Unknown")
            except Exception:
                return "Unknown"

        same_sector = 0
        for p in open_positions:
            if not isinstance(p, dict):
                continue
            ps = _pos_sector(p)
            if ps != "Unknown" and sector != "Unknown" and ps == sector:
                same_sector += 1
        if same_sector >= max_per_sector:
            return False, f"sector concentration {sector} ({same_sector}≥{max_per_sector})"

        if not open_positions:
            return True, ""

        try:
            h = yf.Ticker(sym).history(period="30d", interval="1d")["Close"].pct_change().dropna()
            if h.empty or len(h) < 5:
                return True, ""
            for p in open_positions:
                if not isinstance(p, dict):
                    continue
                other = str(p.get("ticker") or "")
                if not other:
                    continue
                ho = yf.Ticker(other).history(period="30d", interval="1d")["Close"].pct_change().dropna()
                joined = h.align(ho, join="inner")
                a, b = joined[0].dropna(), joined[1].dropna()
                m = min(len(a), len(b))
                if m < 5:
                    continue
                a, b = a.iloc[-m:], b.iloc[-m:]
                corr = float(a.corr(b))
                if not math.isnan(corr) and corr > max_correlation:
                    return False, f"high correlation {corr:.2f} vs open {other}"
        except Exception as e:
            logger.warning("RecursiveScreener correlation skip %s: %s", sym, e)

        return True, ""


if __name__ == "__main__":
    start_time = time.time()
    results = run_screener()
    end_time = time.time()

    print("Screening Results:")
    for result in results:
        print(f"{result['ticker']} - Drop: {result['drop_pct']:.1f}%, RSI: {result['rsi']:.1f}, Volume: {result['volume_ratio']:.1f}")
        print(f"  News: {', '.join(result['news'])}")
        print(f"  Analysis: {result['analysis']}")
        print()

    print(f"Found {len(results)} candidates in {end_time - start_time:.2f} seconds")

    # Save results to file
    filename = f"data/screening_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
