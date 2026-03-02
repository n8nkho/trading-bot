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
from datetime import datetime, timedelta
from pathlib import Path

# Project root
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from flask import Flask, render_template, jsonify
from flask_cors import CORS

app = Flask(__name__, template_folder=Path(__file__).resolve().parent / "templates")
CORS(app)

DATA_DIR = _ROOT / "data"
LOGS_DIR = _ROOT / "logs"
CONFIG_DIR = _ROOT / "config"

# Agent log files and max age (hours) for "fresh"
AGENT_LOGS = {
    "screener": {"log": LOGS_DIR / "screener.log", "name": "Screener", "max_age_hours": 26},
    "monitor": {"log": LOGS_DIR / "monitor.log", "name": "Exit Monitor", "max_age_hours": 2},
    "sniper": {"log": LOGS_DIR / "sniper.log", "name": "Intraday Sniper", "max_age_hours": 2},
    "orchestrator": {"log": LOGS_DIR / "orchestrator.log", "name": "Orchestrator", "max_age_hours": 26},
    "agent_manager": {"log": LOGS_DIR / "agent_manager.log", "name": "Agent Manager", "max_age_hours": 1},
    "llama_watchdog": {"log": LOGS_DIR / "llama_watchdog.log", "name": "Llama Watchdog", "max_age_hours": 2},
    "error_detective": {"log": LOGS_DIR / "error_detective.log", "name": "Error Detective", "max_age_hours": 25},
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
    """Services, cron, disk, risk, data files."""
    health = {
        "timestamp": datetime.now().isoformat(),
        "services": {},
        "cron_configured": False,
        "cron_count": 0,
        "disk": {},
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
    """Positions, decisions summary, win rate, recent trades, latest daily_signals summary."""
    perf = {
        "positions": [],
        "positions_count": 0,
        "decisions": [],
        "win_rate_30d": None,
        "total_pnl": 0,
        "recent_trades": [],
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
        wins = sum(1 for s in sells if (s.get("pnl_pct") or 0) > 0)
        perf["win_rate_30d"] = round(100 * wins / len(sells), 1)
        perf["total_pnl"] = round(sum(s.get("pnl", 0) for s in sells), 2)
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
        perf["latest_screening"] = {
            "date": latest.get("timestamp", "")[:10],
            "time": time_str,
            "candidates_found": latest.get("candidates_found", 0),
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

    return perf


def get_news_and_impact():
    """News from latest screening candidates + watchlist tickers."""
    impact = {
        "headlines": [],
        "candidate_news": [],
        "timestamp": datetime.now().isoformat(),
    }
    # From latest daily_signals
    pattern = DATA_DIR / "daily_signals_*.json"
    files = sorted(glob.glob(str(pattern)), reverse=True)
    for fpath in files[:1]:
        data = _read_json(Path(fpath))
        for c in data.get("candidates", [])[:10]:
            ticker = c.get("ticker")
            news = c.get("news", [])
            analysis = (c.get("analysis") or {}).get("reasoning", "")[:200]
            impact["candidate_news"].append({
                "ticker": ticker,
                "headlines": news[:5],
                "snippet": analysis,
                "drop_pct": c.get("drop_pct"),
                "confidence": (c.get("analysis") or {}).get("confidence"),
            })
        break
    # Flatten for headlines
    for item in impact["candidate_news"]:
        for h in item.get("headlines", []):
            impact["headlines"].append({"ticker": item["ticker"], "text": h if isinstance(h, str) else h.get("title", str(h))})
    return impact


def get_recommendations():
    """Error report summary, risk alerts, stale agents, improvement reports."""
    recs = {
        "items": [],
        "timestamp": datetime.now().isoformat(),
    }
    # Unresolved errors from validation (current code - fix these first)
    has_err, has_warn, err_list, warn_list = _validate_system()
    if has_err and err_list:
        recs["items"].append({
            "type": "errors",
            "severity": "high",
            "title": "Unresolved errors (fix required)",
            "body": "; ".join(err_list[:5]) + (" ..." if len(err_list) > 5 else ""),
            "action": "Fix import/runtime errors in affected agents",
        })

    # Risk
    try:
        from agents.risk_guardian import get_risk_status
        risk = get_risk_status()
        if risk.get("circuit_breaker_active"):
            recs["items"].append({
                "type": "risk",
                "severity": "high",
                "title": "Circuit breaker active",
                "body": "Trading reduced until circuit breaker is reset.",
                "action": "Check risk_status and reset if intended.",
            })
        if (risk.get("position_size_reduction") or 1) < 1:
            recs["items"].append({
                "type": "risk",
                "severity": "medium",
                "title": "Position size reduced",
                "body": f"Position size at {100 * (risk.get('position_size_reduction') or 1):.0f}% due to consecutive losses.",
                "action": "None",
            })
    except Exception:
        pass

    # Stale agents
    activity = get_agent_activity()
    for a in activity.get("agents", []):
        if a.get("status") == "stale":
            recs["items"].append({
                "type": "agent",
                "severity": "medium",
                "title": f"{a.get('name')} has not run recently",
                "body": f"Last run: {a.get('last_run', 'N/A')}",
                "action": f"Check cron or run {a.get('id')} manually.",
            })

    # Improvement report (latest)
    imp_pattern = DATA_DIR / "improvement_report_*.json"
    imp_files = sorted(glob.glob(str(imp_pattern)), reverse=True)
    if imp_files:
        try:
            with open(imp_files[0]) as f:
                imp = json.load(f)
                recs["items"].append({
                    "type": "improvement",
                    "severity": "low",
                    "title": "Meta-architect improvement report",
                    "body": json.dumps(imp)[:400],
                    "action": "Review data/improvement_report_*.json",
                })
        except Exception:
            pass

    # Weekly review
    week_pattern = DATA_DIR / "weekly_review_*.json"
    week_files = sorted(glob.glob(str(week_pattern)), reverse=True)
    if week_files:
        try:
            with open(week_files[0]) as f:
                rev = json.load(f)
                recs["items"].append({
                    "type": "review",
                    "severity": "low",
                    "title": "Weekly performance review",
                    "body": json.dumps(rev)[:400],
                    "action": "See data/weekly_review_*.json",
                })
        except Exception:
            pass

    return recs


@app.route("/")
def index():
    return render_template("command_center.html")


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


if __name__ == "__main__":
    LOGS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    port = int(os.environ.get("COMMAND_CENTER_PORT", "8083"))
    print(f"Command Center: http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
