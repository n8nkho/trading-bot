import os
import json
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
from utils.local_llm import analyze_stock_drop
from agents.vision_analyst import analyze_chart_patterns, pattern_to_signal
from utils.policy_profile import get_profile_bundle

# Load current parameters
DATA_DIR = Path("data")
CURRENT_PARAMS_FILE = DATA_DIR / "current_params.json"

def load_screening_params():
    """Load current screening parameters (may have been auto-tuned)"""
    try:
        if CURRENT_PARAMS_FILE.exists():
            with open(CURRENT_PARAMS_FILE, 'r') as f:
                params = json.load(f)
                logging.info(f"Loaded tuned parameters: RSI<{params['rsi_threshold']}, Drop: {params['drop_min']}% to {params['drop_max']}%")
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
        logging.error(f"Error loading parameters, using defaults: {e}")
        return {
            'rsi_threshold': 40,
            'drop_min': -15,
            'drop_max': -5,
            'volume_ratio_min': 1.5
        }

logging.basicConfig(
    filename='logs/screener.log', 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_screener():
    # Load current parameters (may have been auto-tuned)
    params = load_screening_params()
    
    with open('config/watchlist.json', 'r') as f:
        watchlist_payload = json.load(f)

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

    # License tier: cap distinct tickers (Starter/Pro/Enterprise); master is effectively unlimited.
    universe_cap_meta: dict = {}
    try:
        from utils.license_gates import apply_license_universe_cap

        tiers, universe_cap_meta = apply_license_universe_cap(tiers)
        if universe_cap_meta.get("universe_truncated"):
            logging.warning(
                "Universe trimmed by license: max=%s configured=%s using=%s",
                universe_cap_meta.get("license_max_universe"),
                universe_cap_meta.get("universe_configured_before_cap"),
                universe_cap_meta.get("universe_after_cap"),
            )
    except Exception as exc:
        logging.warning("License universe cap skipped: %s", exc)

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

    def _tier_params(tier_idx: int) -> dict:
        """
        Step-wise relaxation of numeric prefilter thresholds by tier.
        Keeps Tier 1 strict, and broadens only if earlier tiers produce too few/zero candidates.
        """
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
        meets_rsi_criteria = rsi < params_for_tier["rsi_threshold"]
        meets_volume_criteria = volume_ratio > params_for_tier["volume_ratio_min"]

        if not meets_drop_criteria:
            return {"status": "reject", "reason": "drop_criteria"}
        if not meets_rsi_criteria:
            return {"status": "reject", "reason": "rsi_criteria"}
        if not meets_volume_criteria:
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

    for tier_idx, tier_stocks in enumerate(tiers[:max_tiers_to_scan], start=1):
        tier_start_ts = time.time()
        if time.time() - start_ts > max_runtime_seconds:
            logging.warning(f"Screening runtime cap hit; stopping after tier {tier_idx-1}.")
            tier_stop_reason = "runtime_cap_hit"
            break

        tiers_scanned += 1
        tier_prefilter_passed = 0
        # Data hygiene guard: reject malformed symbols before network calls.
        valid_tier = []
        invalid_symbol_count = 0
        for s in tier_stocks:
            ticker = str((s or {}).get("ticker") or "").strip().upper()
            if ticker and ticker.replace("-", "").isalnum():
                valid_tier.append({"ticker": ticker})
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

                candidates.append({
                    "ticker": ticker,
                    "current_price": latest_close,
                    "drop_pct": drop_pct,
                    "rsi": rsi,
                    "volume_ratio": volume_ratio,
                    "news": news_headlines,
                    "analysis": analysis,
                    "vision_signal": vision_signal,
                })
                tier_candidates_added += 1
            except Exception as e:
                logging.error(f"Error heavy-analyzing {ticker}: {type(e).__name__}: {str(e)}")
                logging.error(f"Full traceback for {ticker}:\n{traceback.format_exc()}")
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
            "tiers_configured": tiers_configured,
            "tiers_scanned": tiers_scanned,
            "tier_stop_reason": tier_stop_reason,
            "screening_target_candidates_per_run": target_candidates,
            "prefilter_workers": prefilter_workers,
            "max_screening_runtime_seconds": max_runtime_seconds,
            "tier_telemetry": tier_telemetry,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
    except Exception:
        pass

    return sorted(candidates, key=lambda x: x['analysis']['confidence'], reverse=True)

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
        logging.error(f"Error calculating RSI: {type(e).__name__}: {str(e)}")
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
                logging.warning(f"News item for {ticker} missing 'title' field: {h.keys()}")
        return headlines
    except Exception as e:
        logging.warning(f"Could not fetch news for {ticker}: {type(e).__name__}: {str(e)}")
        return []

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
