#!/usr/bin/env python3
"""
Fortress Command Center - World-class agentic dashboard.
System health, agent activity, trading performance, strategy-impacting news, recommendations.
"""
import os
import re
import sys
import json
import subprocess
import shutil
import glob
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

# Project root
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from flask import Flask, render_template, jsonify
from flask_cors import CORS

app = Flask(__name__, template_folder=Path(__file__).resolve().parent / "templates")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

DATA_DIR = _ROOT / "data"
LOGS_DIR = _ROOT / "logs"
CONFIG_DIR = _ROOT / "config"

# Agent activity: one row per log file. "Last run" = file mtime; "fresh" if age <= max_age_hours.
# This list is cron/key agents with dedicated logs. Other agents (e.g. opportunity_analyzer,
# regime_alignment, pattern_miner) run via Command Center refresh and write to data/ + their own logs;
# add an entry here if you want them shown (use the log path that gets written when they run).
AGENT_LOGS = {
    "screener": {"log": LOGS_DIR / "screener.log", "name": "Screener", "max_age_hours": 26},
    "monitor": {"log": LOGS_DIR / "monitor.log", "name": "Exit Monitor", "max_age_hours": 2},
    "sniper": {"log": LOGS_DIR / "sniper.log", "name": "Intraday Sniper", "max_age_hours": 2},
    "momentum": {"log": LOGS_DIR / "momentum.log", "name": "Momentum", "max_age_hours": 2},
    "inefficiency": {"log": LOGS_DIR / "inefficiency.log", "name": "Inefficiency", "max_age_hours": 26},
    "merger_arb": {"log": LOGS_DIR / "merger_arb.log", "name": "Merger Arb", "max_age_hours": 26},
    "trump_trader": {"log": LOGS_DIR / "trump_trader.log", "name": "Trump Trader", "max_age_hours": 26},
    "smart_money": {"log": LOGS_DIR / "smart_money.log", "name": "Smart Money", "max_age_hours": 26},
    "fortress": {"log": LOGS_DIR / "fortress.log", "name": "Fortress Hedging", "max_age_hours": 26},
    "sync": {"log": LOGS_DIR / "sync.log", "name": "Sync Alpaca", "max_age_hours": 2},
    "orchestrator": {"log": LOGS_DIR / "orchestrator.log", "name": "Orchestrator", "max_age_hours": 9999},
    "agent_manager": {"log": LOGS_DIR / "agent_manager.log", "name": "Agent Manager", "max_age_hours": 1},
    "llama_watchdog": {"log": LOGS_DIR / "llama_watchdog.log", "name": "Llama Watchdog", "max_age_hours": 2},
    "error_detective": {"log": LOGS_DIR / "error_detective.log", "name": "Error Detective", "max_age_hours": 25},
    "main_loop": {"log": LOGS_DIR / "main_loop.log", "name": "Main Loop", "max_age_hours": 1},
}


def _validate_system():
    """Quick validation: import key modules + check for stale agents. Returns (unresolved_errors, unresolved_warnings, errors, warnings)."""
    errors = []
    warnings = []
    try:
        from agents.screener_agent import run_screener
    except Exception as e:
        errors.append(f"screener: {type(e).__name__}: {e}")
    try:
        from agents.exit_monitor import monitor_positions
    except Exception as e:
        errors.append(f"exit_monitor: {type(e).__name__}: {e}")
    try:
        from agents.intraday_sniper import scan_intraday_opportunities
    except Exception as e:
        errors.append(f"sniper: {type(e).__name__}: {e}")
    try:
        from agents.entry_agent import evaluate_entry
    except Exception as e:
        errors.append(f"entry_agent: {type(e).__name__}: {e}")
    try:
        from agents.risk_guardian import get_risk_status
    except Exception as e:
        errors.append(f"risk_guardian: {type(e).__name__}: {e}")
    # Stale agents = warnings (attempt to resolve; de-prioritize during trading hours)
    activity = get_agent_activity()
    for a in activity.get("agents", []):
        if a.get("status") == "stale":
            warnings.append(f"{a.get('name')} stale")
    return (len(errors) > 0, len(warnings) > 0, errors, warnings)


def _is_market_hours():
    """True if 9:30-16:00 ET Mon-Fri."""
    try:
        import pytz
        from datetime import time as dtime
        et = pytz.timezone("America/New_York")
        now = datetime.now(et)
        if now.weekday() >= 5:
            return False
        t = now.time()
        return dtime(9, 30) <= t <= dtime(16, 0)
    except Exception:
        return False


def _is_trading_day_window():
    """True if Mon-Fri 6:00-19:00 ET (so stale-agent recs are relevant)."""
    try:
        import pytz
        from datetime import time as dtime
        et = pytz.timezone("America/New_York")
        now = datetime.now(et)
        if now.weekday() >= 5:
            return False
        t = now.time()
        return dtime(6, 0) <= t <= dtime(19, 0)
    except Exception:
        return False


def _read_json(path, default=None):
    if default is None:
        default = {}
    try:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _read_jsonl(path, limit=500):
    out = []
    try:
        if path.exists():
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if len(out) >= limit:
                        break
    except Exception:
        pass
    return out


def _tail(path, lines=50):
    try:
        if path.exists():
            with open(path, "r") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
    except Exception:
        pass
    return ""


def get_system_health():
    """Services, cron, disk, CPU/RAM, risk, data files."""
    health = {
        "timestamp": datetime.now().isoformat(),
        "services": {},
        "cron_configured": False,
        "cron_count": 0,
        "disk": {},
        "cpu": {},
        "memory": {},
        "risk": {},
        "data_files": {},
    }
    # Services
    for name, cmd in [
        ("ollama", ["systemctl", "is-active", "ollama"]),
        ("dashboard", ["pgrep", "-f", "dashboard"]),
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if name == "ollama":
                health["services"][name] = "active" in (r.stdout or "").lower()
            else:
                health["services"][name] = r.returncode == 0 and bool((r.stdout or "").strip())
        except Exception:
            health["services"][name] = False

    # Cron
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        out = r.stdout or ""
        health["cron_configured"] = "orchestrator.py" in out
        health["cron_count"] = out.count("orchestrator.py") + out.count("run_strategies.py") + out.count("agent_manager")
    except Exception:
        pass

    # Disk
    try:
        usage = shutil.disk_usage("/")
        health["disk"] = {
            "used_gb": round(usage.used / (1024 ** 3), 1),
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "pct": round(100 * usage.used / usage.total, 1),
        }
    except Exception:
        health["disk"] = {"used_gb": 0, "total_gb": 0, "pct": 0}

    # CPU load (1-minute) vs cores
    try:
        load1, _load5, _load15 = os.getloadavg()
        cores = os.cpu_count() or 1
        cpu_pct = min(100.0, round(100.0 * load1 / cores, 1))
        health["cpu"] = {"load1": load1, "cores": cores, "pct": cpu_pct}
    except Exception:
        health["cpu"] = {}

    # Memory usage from /proc/meminfo (Linux)
    try:
        mem_total = None
        mem_available = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = float(line.split()[1])  # kB
                elif line.startswith("MemAvailable:"):
                    mem_available = float(line.split()[1])  # kB
                if mem_total is not None and mem_available is not None:
                    break
        if mem_total and mem_available:
            used_pct = round(100.0 * (1.0 - mem_available / mem_total), 1)
            health["memory"] = {"used_pct": used_pct}
    except Exception:
        health["memory"] = {}

    # Risk (from risk_guardian if available)
    try:
        risk_file = DATA_DIR / "risk_status.json"
        if risk_file.exists():
            with open(risk_file) as f:
                health["risk"] = json.load(f)
        else:
            from agents.risk_guardian import get_risk_status
            health["risk"] = get_risk_status()
    except Exception:
        health["risk"] = {}

    # Data files
    health["data_files"]["positions"] = (DATA_DIR / "positions.json").exists()
    health["data_files"]["decisions"] = (DATA_DIR / "decisions_log.jsonl").exists()
    health["data_files"]["watchlist"] = (CONFIG_DIR / "watchlist.json").exists()

    # Unresolved errors/warnings (from quick validation - current code only)
    has_err, has_warn, err_list, warn_list = _validate_system()
    health["unresolved_errors"] = has_err
    health["unresolved_warnings"] = has_warn
    health["validation_errors"] = err_list
    health["market_hours"] = _is_market_hours()

    return health


def get_agent_activity():
    """Per-agent last run, status (fresh/stale), last log line."""
    agents = []
    now = datetime.now()
    for key, cfg in AGENT_LOGS.items():
        log_path = cfg["log"]
        max_h = cfg["max_age_hours"]
        status = "unknown"
        last_run = None
        last_line = ""
        if log_path.exists():
            mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
            age_h = (now - mtime).total_seconds() / 3600
            last_run = mtime.isoformat()
            status = "fresh" if age_h <= max_h else "stale"
            raw = _tail(log_path, 1)
            if raw:
                last_line = raw.strip().split("\n")[-1][-200:]
        agents.append({
            "id": key,
            "name": cfg["name"],
            "status": status,
            "last_run": last_run,
            "last_activity": last_line,
        })
    return {"agents": agents, "timestamp": now.isoformat()}


def get_trading_performance():
    """Positions, decisions summary, win rate, per-strategy stats, hedging snapshot, recent trades, latest daily_signals summary."""
    perf = {
        "positions": [],
        "positions_count": 0,
        "decisions": [],
        "win_rate_30d": None,
        "total_pnl": 0,
        "recent_trades": [],
        "strategies": [],
        "hedging": {},
        "latest_screening": {},
        "auto_execution_today": {},
        "timestamp": datetime.now().isoformat(),
    }
    # Positions
    positions = _read_json(DATA_DIR / "positions.json", default=[])
    if isinstance(positions, dict):
        positions = positions.get("positions", [])
    perf["positions"] = positions
    perf["positions_count"] = len(positions)

    # Decisions log
    decisions = _read_jsonl(DATA_DIR / "decisions_log.jsonl", limit=100)
    perf["decisions"] = decisions[-20:]
    sells = [d for d in decisions if d.get("action") == "SELL" or "pnl_pct" in d]
    if sells:
        wins = sum(1 for s in sells if float(s.get("pnl_pct") or 0) > 0)
        perf["win_rate_30d"] = round(100 * wins / len(sells), 1)
        perf["total_pnl"] = round(sum(float(s.get("pnl") or 0) for s in sells), 2)
        # Aggregate per-strategy stats
        strategy_stats = {}
        for s in sells:
            key = s.get("strategy_id") or s.get("strategy") or "Unknown"
            info = strategy_stats.setdefault(key, {"name": key, "trades": 0, "wins": 0, "pnl": 0.0})
            info["trades"] += 1
            pnl = s.get("pnl")
            if pnl is not None:
                info["pnl"] += pnl
                if pnl > 0:
                    info["wins"] += 1
        strategies = []
        for st in strategy_stats.values():
            if st["trades"] > 0:
                st["win_rate"] = round(100 * st["wins"] / st["trades"], 1)
            else:
                st["win_rate"] = None
            st["pnl"] = round(st["pnl"], 2)
            strategies.append(st)
        # Sort by absolute P&L then trades
        strategies.sort(key=lambda x: (abs(x["pnl"]), x["trades"]), reverse=True)
        perf["strategies"] = strategies
    # Unrealized P&L from open positions
    unrealized_pnl = round(sum(p.get("pnl", 0) or 0 for p in positions), 2)
    perf["unrealized_pnl"] = unrealized_pnl
    perf["total_pnl"] = round(perf["total_pnl"] + unrealized_pnl, 2)
    perf["recent_trades"] = list(reversed(decisions[-15:]))

    # Latest daily signals
    pattern = DATA_DIR / "daily_signals_*.json"
    files = sorted(glob.glob(str(pattern)), reverse=True)
    if files:
        latest = _read_json(Path(files[0]))
        ts = latest.get("timestamp", "") or ""
        time_str = ts[11:16] if len(ts) >= 16 else ""
        cand_list = latest.get("candidates") or []
        top_candidates = [c.get("ticker") for c in cand_list[:6] if isinstance(c, dict) and c.get("ticker")]
        universe_size = latest.get("universe_size")
        # Fallback: try meta file if daily_signals lacks universe_size
        if universe_size is None:
            try:
                meta_path = DATA_DIR / "last_screening_meta.json"
                if meta_path.exists():
                    meta = _read_json(meta_path, default={})
                    universe_size = meta.get("universe_size", universe_size)
            except Exception:
                pass
        perf["latest_screening"] = {
            "date": latest.get("timestamp", "")[:10],
            "time": time_str,
            "candidates_found": latest.get("candidates_found", 0),
            "universe_size": universe_size,
            "approved": len(latest.get("approved_trades", [])),
            "rejected": len(latest.get("rejected_trades", [])),
            "auto_executed": len((latest.get("auto_execution") or {}).get("executed", [])),
            "top_candidates": top_candidates,
        }

    # Auto trades today
    today = datetime.now().strftime("%Y%m%d")
    auto_path = DATA_DIR / f"auto_trades_{today}.json"
    if auto_path.exists():
        perf["auto_execution_today"] = _read_json(auto_path, default={})

    # Hedging snapshot from latest fortress report
    try:
        fort_pattern = DATA_DIR / "fortress_report_*.json"
        fort_files = sorted(glob.glob(str(fort_pattern)), reverse=True)
        if fort_files:
            latest_fort = _read_json(Path(fort_files[0]), default={})
            mc = latest_fort.get("market_conditions") or {}
            strat = latest_fort.get("strategies") or {}
            bonds = strat.get("bonds") or {}
            commodities = strat.get("commodities") or {}
            vix_ins = strat.get("vix_insurance") or {}
            theta = strat.get("theta_spreads") or {}
            dividend = strat.get("dividend_capture") or {}
            pairs = strat.get("pairs_trading") or {}
            perf["hedging"] = {
                "regime": mc.get("regime"),
                "vix": mc.get("vix"),
                "usd_strength": mc.get("usd_strength"),
                "bonds_target": bonds.get("target"),
                "commodities": commodities,
                "vix_insurance": vix_ins,
                "theta_spreads": theta,
                "dividend_capture": dividend,
                "pairs_trading": pairs,
            }
    except Exception:
        perf["hedging"] = {}

    return perf


def _fetch_news_for_ticker(ticker, limit=2):
    """Fetch up to `limit` headlines for a ticker via yfinance. Returns list of (title, url)."""
    try:
        import yfinance as yf
        news = yf.Ticker(ticker).get_news()
        out = []
        for h in (news or [])[:limit]:
            title = None
            url = None
            if isinstance(h, dict):
                c = h.get("content") or h
                title = h.get("title") or (c.get("title") if isinstance(c, dict) else None)
                if isinstance(c, dict):
                    for key in ("clickThroughUrl", "canonicalUrl"):
                        u = c.get(key)
                        if isinstance(u, dict) and u.get("url"):
                            url = u["url"]
                            break
            elif isinstance(h, str):
                title = h
            if title and isinstance(title, str) and title.strip():
                out.append((title.strip(), url or ""))
        return out
    except Exception:
        return []


def _normalize_headline(s):
    """Normalize for dedupe."""
    if not s:
        return ""
    return " ".join(str(s).lower().strip().split())[:200]


def get_news_and_impact():
    """
    Top 10 strategy-impacting news: positions, opportunities, defensive, market.
    Deduped, prioritized, with source links. Returns top_10 (each: ticker, source, headline, url).
    """
    impact = {
        "top_10": [],
        "top_5": [],  # backward compat
        "headlines": [],
        "candidate_news": [],
        "timestamp": datetime.now().isoformat(),
    }

    source_priority = {"position": 1, "opportunity": 2, "defensive": 3, "market": 4}
    seen = set()
    candidates = []  # (priority, ticker, headline, source, url)

    # 1) Positions
    positions = _read_json(DATA_DIR / "positions.json", default=[])
    if not isinstance(positions, list):
        positions = positions.get("positions", positions.get("positions_list", []))
    position_tickers = [(p.get("ticker") or p.get("symbol") or "").strip().upper() for p in positions[:10] if (p.get("ticker") or p.get("symbol"))]
    for ticker in position_tickers[:5]:
        for title, url in _fetch_news_for_ticker(ticker, limit=2):
            key = _normalize_headline(title)
            if key and key not in seen:
                seen.add(key)
                candidates.append((source_priority["position"], ticker, title, "position", url or ""))

    # 2) Opportunities
    pattern = DATA_DIR / "daily_signals_*.json"
    files = sorted(glob.glob(str(pattern)), reverse=True)
    opportunity_tickers = []
    for fpath in files[:1]:
        data = _read_json(Path(fpath))
        for c in data.get("candidates", [])[:5]:
            t = (c.get("ticker") or "").strip().upper()
            if t and t not in position_tickers:
                opportunity_tickers.append(t)
        for c in data.get("candidates", [])[:10]:
            ticker = (c.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            news = c.get("news", [])
            for h in news[:2]:
                text = h if isinstance(h, str) else (h.get("title") or str(h))
                if not text:
                    continue
                key = _normalize_headline(text)
                if key and key not in seen:
                    seen.add(key)
                    candidates.append((source_priority["opportunity"], ticker, text, "opportunity", ""))
            impact["candidate_news"].append({
                "ticker": ticker,
                "headlines": news[:5],
                "snippet": ((c.get("analysis") or {}).get("reasoning", ""))[:200],
                "drop_pct": c.get("drop_pct"),
                "confidence": (c.get("analysis") or {}).get("confidence"),
            })
        break

    # 3) Defensive watchlist
    def_tickers = []
    def_path = DATA_DIR / "defensive_watchlist.json"
    if def_path.exists():
        try:
            raw = _read_json(def_path, default=[])
            raw_list = raw if isinstance(raw, list) else raw.get("tickers", [])
            def_tickers = [str(x).strip().upper() for x in raw_list[:8] if x]
        except Exception:
            pass
    for ticker in def_tickers:
        if ticker in position_tickers or ticker in opportunity_tickers:
            continue
        for title, url in _fetch_news_for_ticker(ticker, limit=2):
            key = _normalize_headline(title)
            if key and key not in seen:
                seen.add(key)
                candidates.append((source_priority["defensive"], ticker, title, "defensive", url or ""))

    # 4) Market (SPY) – up to 3 for variety
    for title, url in _fetch_news_for_ticker("SPY", limit=3):
        key = _normalize_headline(title)
        if key and key not in seen:
            seen.add(key)
            candidates.append((source_priority["market"], "SPY", title, "market", url or ""))

    candidates.sort(key=lambda x: (x[0], -len(x[2])))
    for _, ticker, headline, source, url in candidates[:10]:
        item = {"ticker": ticker, "source": source, "headline": headline[:200] if headline else "", "url": url or ""}
        impact["top_10"].append(item)
        if len(impact["top_5"]) < 5:
            impact["top_5"].append(item)

    for item in impact["candidate_news"]:
        for h in item.get("headlines", []):
            text = h if isinstance(h, str) else (h.get("title") if isinstance(h, dict) else str(h))
            impact["headlines"].append({"ticker": item["ticker"], "text": text})
    if not impact["headlines"] and impact["top_10"]:
        for n in impact["top_10"]:
            impact["headlines"].append({"ticker": n["ticker"], "text": n["headline"]})
    return impact


def _normalize_title(s):
    """Normalize for dedupe: lower, strip, collapse spaces."""
    if not s:
        return ""
    return " ".join(str(s).lower().strip().split())


def _append_rec(recs, seen_titles, item_type, severity, title, body, action):
    """Append one recommendation if title not already seen (dedupe)."""
    key = _normalize_title(title)
    if key and key in seen_titles:
        return
    seen_titles.add(key)
    recs["items"].append({
        "type": item_type,
        "severity": severity,
        "title": title,
        "body": body,
        "action": action,
    })


def get_recommendations():
    """Error report summary, risk alerts, stale agents, analyzer outputs, strategic roadmap. Capped per source; deduped by title."""
    recs = {"items": [], "timestamp": datetime.now().isoformat()}
    seen_titles = set()

    # --- Must-show: errors, risk, stale agents (no dedupe) ---
    has_err, has_warn, err_list, warn_list = _validate_system()
    if has_err and err_list:
        recs["items"].append({
            "type": "errors", "severity": "high",
            "title": "Unresolved errors (fix required)",
            "body": "; ".join(err_list[:5]) + (" ..." if len(err_list) > 5 else ""),
            "action": "Fix import/runtime errors in affected agents",
        })

    try:
        from agents.risk_guardian import get_risk_status
        risk = get_risk_status()
        if risk.get("circuit_breaker_active"):
            recs["items"].append({
                "type": "risk", "severity": "high",
                "title": "Circuit breaker active",
                "body": "Trading reduced until circuit breaker is reset.",
                "action": "Check risk_status and reset if intended.",
            })
        if (risk.get("position_size_reduction") or 1) < 1:
            recs["items"].append({
                "type": "risk", "severity": "medium",
                "title": "Position size reduced",
                "body": f"Position size at {100 * (risk.get('position_size_reduction') or 1):.0f}% due to consecutive losses.",
                "action": "None",
            })
    except Exception:
        pass

    if _is_trading_day_window():
        activity = get_agent_activity()
        for a in activity.get("agents", []):
            if a.get("status") == "stale":
                recs["items"].append({
                    "type": "agent", "severity": "medium",
                    "title": f"{a.get('name')} has not run recently",
                    "body": f"Last run: {a.get('last_run', 'N/A')}",
                    "action": f"Check cron or run {a.get('id')} manually.",
                })

    # --- Single combined "Reports" block (improvement + weekly review) ---
    imp_path = next(iter(sorted(glob.glob(str(DATA_DIR / "improvement_report_*.json")), reverse=True)), None)
    week_path = next(iter(sorted(glob.glob(str(DATA_DIR / "weekly_review_*.json")), reverse=True)), None)
    imp_ok = imp_path and (datetime.now() - datetime.fromtimestamp(Path(imp_path).stat().st_mtime)).days <= 14
    week_ok = week_path and (datetime.now() - datetime.fromtimestamp(Path(week_path).stat().st_mtime)).days <= 14
    if imp_ok and week_ok:
        _append_rec(recs, seen_titles, "reports", "low",
            "Meta-architect & weekly review",
            "Latest improvement report and weekly performance review are available.",
            "See data/improvement_report_*.json and data/weekly_review_*.json")
    elif imp_ok:
        try:
            with open(imp_path) as f:
                imp = json.load(f)
            _append_rec(recs, seen_titles, "reports", "low",
                "Meta-architect improvement report",
                (json.dumps(imp)[:180] + "…") if len(json.dumps(imp)) > 180 else json.dumps(imp),
                "Review data/improvement_report_*.json")
        except Exception:
            pass
    elif week_ok:
        try:
            with open(week_path) as f:
                rev = json.load(f)
            _append_rec(recs, seen_titles, "reports", "low",
                "Weekly performance review",
                (json.dumps(rev)[:180] + "…") if len(json.dumps(rev)) > 180 else json.dumps(rev),
                "See data/weekly_review_*.json")
        except Exception:
            pass

    # --- Analyzer outputs (capped; deduped by title) ---
    def _add_from_file(path, key, item_type, default_action, limit=3):
        if not path.exists():
            return
        try:
            if (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days > 7:
                return
            with open(path) as f:
                data = json.load(f)
            items = (data.get(key) or data.get("recommendations") or [])[:limit]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if (item.get("action") or "").strip() == "No action required.":
                    continue  # skip filler reminders
                _append_rec(recs, seen_titles, item_type,
                    item.get("severity", "low"),
                    item.get("title", ""),
                    item.get("body", ""),
                    item.get("action", default_action))
        except Exception:
            pass

    _add_from_file(DATA_DIR / "opportunity_recommendations.json", "recommendations", "opportunity", "Review and adjust criteria if desired.", 3)
    _add_from_file(DATA_DIR / "hedging_recommendations.json", "recommendations", "hedging", "Review hedge allocation and regime.", 3)
    _add_from_file(DATA_DIR / "defensive_recommendations.json", "recommendations", "defensive", "See data/defensive_watchlist.json", 3)
    _add_from_file(DATA_DIR / "regime_recommendations.json", "recommendations", "regime", "Review regime and risk settings.", 3)

    no_trade_path = DATA_DIR / "no_trade_findings.json"
    if no_trade_path.exists():
        try:
            if (datetime.now() - datetime.fromtimestamp(no_trade_path.stat().st_mtime)).days <= 7:
                with open(no_trade_path) as f:
                    no_trade = json.load(f)
                for item in no_trade.get("findings", [])[:5]:
                    _append_rec(recs, seen_titles, "no_trade_diagnostic",
                        item.get("severity", "low"),
                        item.get("title", "No-trade diagnostic"),
                        item.get("body", ""),
                        item.get("action", "Review data/no_trade_findings.json."))
        except Exception:
            pass

    # --- Pattern discovery (self-improving: mined patterns, 0-2 advisory) ---
    pattern_rec_path = DATA_DIR / "pattern_discovery_recommendations.json"
    if pattern_rec_path.exists():
        try:
            if (datetime.now() - datetime.fromtimestamp(pattern_rec_path.stat().st_mtime)).days <= 14:
                with open(pattern_rec_path) as f:
                    pattern_rec = json.load(f)
                for item in pattern_rec.get("recommendations", [])[:2]:
                    _append_rec(recs, seen_titles, "pattern_discovery",
                        item.get("severity", "low"),
                        item.get("title", "Discovered pattern"),
                        item.get("body", ""),
                        item.get("action", "Review docs/SELF_IMPROVING_PATTERN_DISCOVERY.md"))
        except Exception:
            pass

    # --- Strategic (self-improving capability, roadmap) ---
    strat_path = DATA_DIR / "strategic_recommendations.json"
    if strat_path.exists():
        try:
            if (datetime.now() - datetime.fromtimestamp(strat_path.stat().st_mtime)).days <= 30:
                with open(strat_path) as f:
                    strat = json.load(f)
                for item in strat.get("recommendations", [])[:5]:
                    _append_rec(recs, seen_titles, "strategic",
                        item.get("severity", "medium"),
                        item.get("title", "Strategic"),
                        item.get("body", ""),
                        item.get("action", ""))
        except Exception:
            pass

    return recs


@app.route("/")
def index():
    from flask import make_response
    resp = make_response(render_template("command_center.html"))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route("/api/health")
def api_health():
    return jsonify(get_system_health())


@app.route("/api/agents")
def api_agents():
    return jsonify(get_agent_activity())


@app.route("/api/performance")
def api_performance():
    return jsonify(get_trading_performance())


@app.route("/api/news")
def api_news():
    return jsonify(get_news_and_impact())


@app.route("/api/recommendations")
def api_recommendations():
    return jsonify(get_recommendations())


def _parse_log_timestamp(line):
    """Try to extract timestamp from log line (e.g. 2026-03-01 22:20:00 or similar)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    if m:
        try:
            s = m.group(1).replace("T", " ")
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            pass
    return None


@app.route("/api/feed")
def api_feed():
    """Unified activity feed: recent log lines, sorted by recency (most recent first)."""
    feed = []
    # Include all agents + high-activity logs
    all_logs = dict(AGENT_LOGS)
    all_logs["fortress_dashboard"] = {"log": LOGS_DIR / "fortress_dashboard.log", "name": "Fortress"}
    all_logs["cron"] = {"log": LOGS_DIR / "cron.log", "name": "Cron"}

    # Sort logs by modification time (most recently updated first)
    log_items = []
    for key, cfg in all_logs.items():
        lp = cfg["log"]
        if lp.exists():
            mtime = lp.stat().st_mtime
            log_items.append((mtime, key, cfg))
    log_items.sort(key=lambda x: -x[0])

    has_err, has_warn, _, _ = _validate_system()
    for _mtime, key, cfg in log_items:
        log_path = cfg["log"]
        mtime = log_path.stat().st_mtime
        raw = _tail(log_path, 40)
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # RED/Amber only when there are unresolved errors/warnings (otherwise neutral)
            level = "info"
            if has_err and "ERROR" in line:
                level = "error"
            elif has_warn and "WARNING" in line:
                level = "warning"
            ts = _parse_log_timestamp(line) or mtime
            feed.append({"agent": cfg["name"], "level": level, "text": line[-350:], "_ts": ts})
    feed.sort(key=lambda x: -x["_ts"])
    for item in feed:
        del item["_ts"]
    return jsonify({"items": feed[:100], "timestamp": datetime.now().isoformat()})


def _run_recommendation_refresh():
    """Run the 6 recommendation agents (no pkill/restart). For use by auto-refresh thread."""
    py = _ROOT / "venv" / "bin" / "python"
    if not py.exists():
        py = shutil.which("python3") or "python3"
    agents = [
        "agents/opportunity_analyzer.py",
        "agents/hedging_opportunity_analyzer.py",
        "agents/defensive_universe_scanner.py",
        "agents/regime_alignment.py",
        "agents/no_trade_analyzer.py",
        "agents/pattern_miner.py",
    ]
    for rel in agents:
        path = _ROOT / rel
        if path.exists():
            try:
                subprocess.run(
                    [str(py), str(path)],
                    cwd=str(_ROOT),
                    timeout=300,
                    capture_output=True,
                )
            except Exception:
                pass


def _refresh_loop():
    """Background: run recommendation refresh shortly after start, then every 15 min."""
    time.sleep(20)
    while True:
        try:
            _run_recommendation_refresh()
        except Exception:
            pass
        time.sleep(15 * 60)



def get_live_positions():
    """Live positions from positions.json enriched with current price from yfinance."""
    out = []
    try:
        import yfinance as yf
        from datetime import datetime
        positions = _read_json(DATA_DIR / "positions.json", default=[])
        if isinstance(positions, dict):
            positions = positions.get("positions", [])
        tickers = list({p.get("ticker") for p in positions if p.get("ticker")})
        # Batch fetch current prices
        prices = {}
        if tickers:
            try:
                data = yf.download(tickers if len(tickers) > 1 else tickers[0],
                                   period="1d", interval="1m", progress=False, auto_adjust=True)
                if data is not None and not data.empty:
                    close = data["Close"] if "Close" in data.columns else data
                    if hasattr(close, "columns"):
                        # Multiple tickers: MultiIndex or wide
                        for t in tickers:
                            try:
                                prices[t] = float(close[t].dropna().iloc[-1])
                            except Exception:
                                pass
                    else:
                        prices[tickers[0]] = float(close.dropna().iloc[-1])
            except Exception:
                # Fallback: single ticker at a time
                for t in tickers:
                    try:
                        hist = yf.Ticker(t).history(period="1d", interval="1m")
                        if hist is not None and not hist.empty:
                            prices[t] = float(hist["Close"].dropna().iloc[-1])
                    except Exception:
                        pass
        now = datetime.now()
        for p in positions:
            ticker = p.get("ticker", "")
            entry = p.get("entry_price") or p.get("entry") or 0
            shares = p.get("shares") or p.get("qty") or 0
            current = prices.get(ticker)
            pnl_pct = round((current - entry) / entry * 100, 2) if current and entry else None
            pnl_usd = round((current - entry) * shares, 2) if current and entry else None
            entry_date = p.get("entry_date") or p.get("entry_time") or ""
            try:
                held_hours = round((now - datetime.fromisoformat(str(entry_date).replace("Z", ""))).total_seconds() / 3600, 1) if entry_date else None
            except Exception:
                held_hours = None
            out.append({
                "ticker": ticker,
                "shares": shares,
                "entry_price": round(float(entry), 2) if entry else None,
                "current_price": round(current, 2) if current else None,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "strategy": p.get("strategy") or p.get("strategy_id") or "—",
                "entry_date": str(entry_date)[:16],
                "held_hours": held_hours,
                "stop_loss_pct": p.get("stop_loss_pct"),
                "take_profit_pct": p.get("take_profit_pct"),
            })
        out.sort(key=lambda x: (x.get("pnl_pct") or 0))
    except Exception as e:
        out = [{"error": str(e)}]
    return {"positions": out, "count": len(out), "timestamp": __import__("datetime").datetime.now().isoformat()}


def get_recent_orders():
    """Recent orders from Alpaca paper trading API."""
    import os
    out = []
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            # try loading .env
            env_path = _ROOT / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("ALPACA_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                    elif line.startswith("ALPACA_SECRET_KEY="):
                        secret = line.split("=", 1)[1].strip()
        client = TradingClient(key, secret, paper=True)
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=25)
        orders = client.get_orders(req)
        for o in orders:
            out.append({
                "id": str(o.id)[:8],
                "ticker": str(o.symbol),
                "side": str(o.side.value if hasattr(o.side, "value") else o.side),
                "qty": str(o.qty),
                "filled_qty": str(o.filled_qty or 0),
                "status": str(o.status.value if hasattr(o.status, "value") else o.status),
                "order_type": str(o.order_type.value if hasattr(o.order_type, "value") else o.order_type),
                "filled_avg_price": round(float(o.filled_avg_price), 2) if o.filled_avg_price else None,
                "submitted_at": str(o.submitted_at)[:16] if o.submitted_at else "—",
                "filled_at": str(o.filled_at)[:16] if o.filled_at else "—",
            })
    except Exception as e:
        out = [{"error": str(e)}]
    return {"orders": out, "count": len(out), "timestamp": __import__("datetime").datetime.now().isoformat()}


@app.route("/api/positions")
def api_positions():
    return jsonify(get_live_positions())


@app.route("/api/orders")
def api_orders():
    return jsonify(get_recent_orders())


if __name__ == "__main__":
    LOGS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    port = int(os.environ.get("COMMAND_CENTER_PORT", "8083"))
    print(f"Command Center: http://0.0.0.0:{port}")
    t = threading.Thread(target=_refresh_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=port, debug=False)
