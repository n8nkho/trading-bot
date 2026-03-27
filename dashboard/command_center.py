#!/usr/bin/env python3
"""
Fortress Command Center - World-class agentic dashboard.
System health, agent activity, trading performance, strategy-impacting news, recommendations.
"""
import os
import re
import sys
import getpass
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

# Load `.env` into os.environ for all routes (/proof billing links, etc.). systemd
# `EnvironmentFile=` also works; dotenv fills gaps and helps non-systemd runs.
try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env", override=False)
except Exception:
    pass

from flask import Flask, render_template, jsonify, make_response, request, redirect, url_for, Response
from flask_cors import CORS

from utils.market_assets import require_market_assets
from utils.policy_profile import get_profile_bundle
from utils.trust_ledger import append_trust_event, enrich_trust_ledger_items, read_recent_trust_events
from utils.operator_halt import get_halt_state, set_trading_halt
from utils.alerts import send_operator_alert
from utils.simple_daily_backtest import read_backtest_snapshot, run_daily_momentum_backtest
from utils.run_registry import summarize_screening_runs
from agents.drift_detector import analyze_drift
from utils.alpaca_env import is_alpaca_paper


def _get_version() -> str:
    """Read VERSION file at project root; default 1.0.0."""
    try:
        vf = _ROOT / "VERSION"
        if vf.exists():
            return vf.read_text().strip() or "1.0.0"
    except Exception:
        pass
    return "1.0.0"

app = Flask(__name__, template_folder=Path(__file__).resolve().parent / "templates")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

# Optional HTTP Basic auth for Command Center + APIs (manifest/health/setup stay public).
_DASH_PUBLIC_PATHS = frozenset({
    "/api/health",
    "/api/system_health",
    "/proof",
    "/setup",
    "/api/setup/status",
    "/api/setup/save_keys",
    "/api/setup/test_connection",
    "/manifest.json",
    "/api/hooks/tradingview",
    "/api/billing/stripe-webhook",
    # No secrets: paths + key names + counts (for debugging /proof billing when Basic auth is on).
    "/api/billing/proof_links_status",
})
_DASH_PUBLIC_PREFIXES = ("/static/",)


@app.before_request
def _fortress_dashboard_basic_auth():
    user = (os.environ.get("FORTRESS_DASHBOARD_USER") or "").strip()
    pw = (os.environ.get("FORTRESS_DASHBOARD_PASS") or "").strip()
    if not user or not pw:
        return None
    path = request.path or ""
    if path in _DASH_PUBLIC_PATHS or any(path.startswith(p) for p in _DASH_PUBLIC_PREFIXES):
        return None
    auth = request.authorization
    if auth and auth.username == user and auth.password == pw:
        return None
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Fortress Command Center"'},
    )


DATA_DIR = _ROOT / "data"
LOGS_DIR = _ROOT / "logs"
CONFIG_DIR = _ROOT / "config"
FORTRESS_REPORT_MAX_AGE_HOURS = float(os.getenv("FORTRESS_REPORT_MAX_AGE_HOURS", "30"))

# Fortress hedging output is routed to either `logs/fortress.log` or (on some builds)
# `logs/fortress_dashboard.log`. Use whichever exists so agent activity has a real last_run.
FORTRESS_HEDGE_LOG = LOGS_DIR / "fortress.log"
if (not FORTRESS_HEDGE_LOG.exists()) and (LOGS_DIR / "fortress_dashboard.log").exists():
    FORTRESS_HEDGE_LOG = LOGS_DIR / "fortress_dashboard.log"

# Agent activity: one row per agent/log file.
# "Last run" = file mtime; status is "fresh" if age <= max_age_hours.
AGENT_LOGS = {
    "cron_heartbeat": {"log": LOGS_DIR / "cron_heartbeat.log", "name": "Cron Heartbeat", "max_age_hours": 0.2},
    "screener": {"log": LOGS_DIR / "screener.log", "name": "Screener", "max_age_hours": 26},
    "monitor": {"log": LOGS_DIR / "monitor.log", "name": "Exit Monitor", "max_age_hours": 2},
    "sniper": {"log": LOGS_DIR / "sniper.log", "name": "Intraday Sniper", "max_age_hours": 2},
    "momentum": {"log": LOGS_DIR / "momentum.log", "name": "Momentum", "max_age_hours": 2},
    "inefficiency": {"log": LOGS_DIR / "inefficiency.log", "name": "Inefficiency", "max_age_hours": 26},
    "merger_arb": {"log": LOGS_DIR / "merger_arb.log", "name": "Merger Arb", "max_age_hours": 26},
    "trump_trader": {"log": LOGS_DIR / "trump_trader.log", "name": "Trump Trader", "max_age_hours": 26},
    "smart_money": {"log": LOGS_DIR / "smart_money.log", "name": "Smart Money", "max_age_hours": 26},
    "fortress": {"log": FORTRESS_HEDGE_LOG, "name": "Fortress Hedging", "max_age_hours": 26},
    # Additional agents already writing to dedicated logs on Oracle.
    # These were previously omitted from the UI agent activity list.
    "entry": {"log": LOGS_DIR / "entry.log", "name": "Entry Agent", "max_age_hours": 2},
    "risk_guardian": {"log": LOGS_DIR / "risk.log", "name": "Risk Guardian", "max_age_hours": 2},
    "meta_architect": {"log": LOGS_DIR / "meta_architect.log", "name": "Meta Architect", "max_age_hours": 26},
    "grok": {"log": LOGS_DIR / "grok.log", "name": "Grok / Vision", "max_age_hours": 26},
    "fortress_dashboard": {"log": LOGS_DIR / "fortress_dashboard.log", "name": "Fortress Dashboard", "max_age_hours": 26},
    "weekly": {"log": LOGS_DIR / "weekly.log", "name": "Weekly Review", "max_age_hours": 26},
    "sync": {"log": LOGS_DIR / "sync.log", "name": "Sync Alpaca", "max_age_hours": 2},
    "orchestrator": {"log": LOGS_DIR / "orchestrator.log", "name": "Orchestrator", "max_age_hours": 9999},
    "agent_manager": {"log": LOGS_DIR / "agent_manager.log", "name": "Agent Manager", "max_age_hours": 1},
    "llama_watchdog": {"log": LOGS_DIR / "llama_watchdog.log", "name": "Llama Watchdog", "max_age_hours": 2},
    "error_detective": {"log": LOGS_DIR / "error_detective.log", "name": "Error Detective", "max_age_hours": 25},
    "main_loop": {"log": LOGS_DIR / "main_loop.log", "name": "Main Loop", "max_age_hours": 1},
}

# Extend agent activity to include *all* agent modules in `agents/`.
# Where we have a dedicated log file, we map directly; otherwise we associate
# hedging modules to the main fortress log so they still show meaningful runs.
def _extend_agent_logs_from_modules() -> None:
    agents_dir = _ROOT / "agents"
    if not agents_dir.exists():
        return

    # Maps module stem -> dedicated log filename.
    dedicated = {
        "screener_agent": ("screener.log", "Screener"),
        "exit_monitor": ("monitor.log", "Exit Monitor"),
        "intraday_sniper": ("sniper.log", "Intraday Sniper"),
        "entry_agent": ("entry.log", "Entry Agent"),
        "risk_guardian": ("risk.log", "Risk Guardian"),
        "llama_watchdog": ("llama_watchdog.log", "Llama Watchdog"),
        "meta_architect": ("meta_architect.log", "Meta Architect"),
        "vision_analyst": ("grok.log", "Vision Analyst"),
        "document_analyst": ("grok.log", "Document Analyst"),
    }

    # Hedging/fortress-related modules tend to emit into fortress orchestration stdout/stderr.
    hedging_modules = {
        "fortress_orchestrator",
        "bond_manager",
        "commodity_trader",
        "forex_hedger",
        "forex_sniper",
        "theta_spreads",
        "dividend_capture",
        "pairs_trader",
        "vix_insurance",
    }

    for py in agents_dir.glob("*.py"):
        stem = py.stem
        # Use stable ids so we don't duplicate existing cron/key agents.
        id_map = {
            "screener_agent": "screener",
            "exit_monitor": "monitor",
            "intraday_sniper": "sniper",
            "entry_agent": "entry",
            "risk_guardian": "risk_guardian",
            "llama_watchdog": "llama_watchdog",
            "meta_architect": "meta_architect",
            # vision/document share grok.log but still show as dedicated modules.
            "vision_analyst": "vision_analyst",
            "document_analyst": "document_analyst",
        }
        agent_id = id_map.get(stem, stem)

        # If already present (cron/key agents), keep existing.
        if agent_id in AGENT_LOGS:
            continue

        if stem in dedicated:
            log_name, display = dedicated[stem]
            AGENT_LOGS[agent_id] = {
                "log": LOGS_DIR / log_name,
                "name": display,
                "max_age_hours": 26 if stem in ["screener_agent", "meta_architect"] else 2,
            }
        elif stem in hedging_modules:
            AGENT_LOGS[agent_id] = {
                "log": FORTRESS_HEDGE_LOG,
                "name": stem.replace("_", " ").title(),
                "max_age_hours": 26,
            }
        else:
            # Unknown/optional agent; still show in UI if it ever writes a log.
            AGENT_LOGS[agent_id] = {
                "log": LOGS_DIR / f"{stem}.log",
                "name": stem.replace("_", " ").title(),
                "max_age_hours": 26,
            }


_extend_agent_logs_from_modules()


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
        elif a.get("status") == "err":
            errors.append(f"{a.get('name')} err")
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


def _read_latest_json_glob(pattern: str | Path, default=None):
    """
    Best-effort: read newest JSON file matching a glob (sorted reverse).
    Returns `default` (dict) when no match or JSON errors.
    """
    if default is None:
        default = {}
    try:
        pattern_s = str(pattern)
        paths = sorted(glob.glob(pattern_s), reverse=True)
        if not paths:
            return default
        p = Path(paths[0])
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else default
    except Exception:
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


def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _read_pnl_ledger_summary(path):
    """
    Read realized P&L from `pnl_ledger.jsonl` (authoritative sell ledger).
    """
    summary = {"count": 0, "wins": 0, "realized_pnl": 0.0}
    try:
        if not path.exists():
            return summary
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pnl = _safe_float(rec.get("pnl"))
                if pnl is None:
                    continue
                summary["count"] += 1
                summary["realized_pnl"] += pnl
                if pnl > 0:
                    summary["wins"] += 1
    except Exception:
        pass
    summary["realized_pnl"] = round(summary["realized_pnl"], 2)
    return summary


def _tail(path, lines=50):
    try:
        if path.exists():
            with open(path, "r") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
    except Exception:
        pass
    return ""


# Substrings that indicate trading-bot jobs in crontab (user and/or /etc/cron.d).
_CRON_JOB_MARKERS = (
    "orchestrator.py",
    "run_strategies.py",
    "agent_manager",
    "error_detective.py",
    "cron_heartbeat",
)


def _cron_bin() -> str:
    return shutil.which("crontab") or "/usr/bin/crontab"


def _read_crontab_spool(uname: str) -> str:
    try:
        spool = Path("/var/spool/cron/crontabs") / uname
        if spool.is_file():
            return spool.read_text(errors="ignore") or ""
    except Exception:
        pass
    return ""


def _aggregate_cron_text() -> str:
    """Effective-user crontab + repo-owner spool + system cron (OCI / systemd user mismatch safe)."""
    parts: list[str] = []
    seen: set[int] = set()

    def _add(text: str) -> None:
        raw = text or ""
        if not raw.strip():
            return
        key = hash(raw)
        if key in seen:
            return
        seen.add(key)
        parts.append(raw)

    # Process user (often ubuntu under systemd; may be root on misconfigured units).
    user_cron = ""
    try:
        r = subprocess.run(
            [_cron_bin(), "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        user_cron = (r.stdout or "").strip()
        if user_cron:
            _add(r.stdout or "")
    except Exception:
        pass
    if not user_cron:
        try:
            import pwd

            uname = pwd.getpwuid(os.getuid()).pw_name
            _add(_read_crontab_spool(uname))
        except Exception:
            pass

    # Always merge crontab for the UNIX owner of the repo dir (jobs live there even if
    # this process runs as root or another user that has an empty crontab).
    try:
        import pwd

        repo_owner = pwd.getpwuid(_ROOT.resolve().stat().st_uid).pw_name
        _add(_read_crontab_spool(repo_owner))
    except Exception:
        pass
    try:
        etc = Path("/etc/crontab")
        if etc.is_file():
            parts.append(etc.read_text(errors="ignore"))
    except Exception:
        pass
    try:
        cron_d = Path("/etc/cron.d")
        if cron_d.is_dir():
            for p in sorted(cron_d.iterdir()):
                if not p.is_file():
                    continue
                if p.name.startswith("."):
                    continue
                low = p.name.lower()
                if "dpkg" in low or low.endswith(".dpkg-dist") or low.endswith(".dpkg-old"):
                    continue
                try:
                    parts.append(p.read_text(errors="ignore"))
                except Exception:
                    continue
    except Exception:
        pass
    return "\n".join(parts)


def _cron_marker_list() -> list[str]:
    """Job substrings + repo path + common install paths + FORTRESS_CRON_MARKERS."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _CRON_JOB_MARKERS:
        if m not in seen:
            seen.add(m)
            out.append(m)
    root = str(_ROOT.resolve())
    if len(root) >= 6 and root not in seen:
        seen.add(root)
        out.append(root)
    for p in ("~/trading-bot", "/trading-bot/"):
        if p not in seen:
            seen.add(p)
            out.append(p)
    extra = os.environ.get("FORTRESS_CRON_MARKERS", "")
    for piece in extra.split(","):
        s = piece.strip()
        if len(s) >= 2 and s not in seen:
            seen.add(s)
            out.append(s)
    return out


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
        "safety_status": {},
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

    # Cron: user crontab + spool + /etc/crontab + /etc/cron.d (must match green/red with real installs).
    try:
        out = _aggregate_cron_text()
        markers = _cron_marker_list()
        health["cron_aggregate_chars"] = len(out)
        health["cron_count"] = sum(out.count(m) for m in markers)
        health["cron_configured"] = health["cron_count"] > 0
        if os.environ.get("FORTRESS_CRON_DEBUG", "").strip() in ("1", "true", "yes"):
            health["cron_debug"] = {
                "aggregate_chars": len(out),
                "markers_used": len(markers),
            }
    except Exception as exc:
        health["cron_aggregate_chars"] = 0
        health["cron_error"] = str(exc)[:200]

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

    # License tier (for customer builds)
    try:
        from config.license import get_plan
        from config.tiers import backtest_allowed, fortress_allowed, get_tier_spec
        plan = get_plan()
        spec = get_tier_spec(plan.tier)
        health["license"] = {
            "tier": plan.tier,
            "name": plan.name,
            "valid": plan.valid,
            "backtest_allowed": backtest_allowed(plan.tier),
            "fortress_allowed": fortress_allowed(plan.tier),
            "max_universe_size": spec.max_universe_size,
            "upgrade_message": None,
        }
        if plan.tier == "starter":
            health["license"]["upgrade_message"] = "Upgrade to Pro for backtest, Fortress hedging, and more strategies."
        elif plan.tier == "pro" and not plan.valid:
            health["license"]["upgrade_message"] = "License expired or invalid. Contact support."
    except Exception:
        health["license"] = {"tier": "master", "name": "Master", "valid": True, "upgrade_message": None}

    try:
        health["safety_status"] = get_safety_status()
    except Exception:
        health["safety_status"] = {}
    return health


def get_agent_activity():
    """Per-agent last run, status (fresh/stale), last log line."""
    agents = []
    now = datetime.now()
    for key, cfg in AGENT_LOGS.items():
        log_path = cfg["log"]
        max_h = cfg["max_age_hours"]
        status = "stale"
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
            low = last_line.lower()
            err_markers = [
                "traceback",
                "modulenotfounderror",
                "module not found",
                "can't open file",
                "no such file",
                "importerror",
                "syntaxerror",
            ]
            if any(m in low for m in err_markers):
                status = "err"
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
        "realized_pnl": 0.0,
        "total_pnl": 0,
        "recent_trades": [],
        "strategies": [],
        "hedging": {},
        "latest_screening": {},
        "auto_execution_today": {},
        "timestamp": datetime.now().isoformat(),
        "policy_profile": get_profile_bundle().get("active_profile"),
    }
    # Positions: prefer Alpaca broker truth; fall back to positions.json; surface file/broker drift
    file_positions = _read_json(DATA_DIR / "positions.json", default=[])
    if isinstance(file_positions, dict):
        file_positions = file_positions.get("positions", [])
    if not isinstance(file_positions, list):
        file_positions = []

    broker_list: list | None = None
    broker_err: str | None = None
    try:
        from utils.alpaca_broker import fetch_broker_positions

        broker_list, broker_err = fetch_broker_positions()
    except Exception as e:
        broker_list, broker_err = None, f"{type(e).__name__}:{e}"

    if broker_list is not None:
        perf["positions_source"] = "alpaca_broker"
        perf["positions_alpaca_error"] = None
        perf["positions"] = broker_list
        perf["positions_count"] = len(broker_list)
        perf["positions_file_count"] = len(file_positions)
        file_syms = {
            str(p.get("ticker") or p.get("symbol") or "").strip().upper()
            for p in file_positions
            if isinstance(p, dict) and (p.get("ticker") or p.get("symbol"))
        }
        brok_syms = {
            str(p.get("ticker") or "").strip().upper()
            for p in broker_list
            if p.get("ticker")
        }
        perf["positions_broker_file_mismatch"] = file_syms != brok_syms
        if perf["positions_broker_file_mismatch"]:
            perf["positions_mismatch_hint"] = (
                f"Broker open symbols {sorted(brok_syms)} != data/positions.json {sorted(file_syms)}. "
                "Reconcile: python3 sync_alpaca.py (from repo root on the VM)."
            )
        else:
            perf["positions_mismatch_hint"] = None
        positions = broker_list
    else:
        perf["positions_source"] = "positions_json"
        perf["positions_alpaca_error"] = broker_err
        perf["positions"] = file_positions
        perf["positions_count"] = len(file_positions)
        perf["positions_file_count"] = len(file_positions)
        perf["positions_broker_file_mismatch"] = None
        perf["positions_mismatch_hint"] = None
        if broker_err:
            perf["positions_mismatch_hint"] = (
                f"Alpaca positions unavailable ({broker_err}); showing positions.json only."
            )
        positions = file_positions

    # Decisions log
    decisions = _read_jsonl(DATA_DIR / "decisions_log.jsonl", limit=100)
    valid_decisions = [d for d in decisions if isinstance(d, dict) and d.get("ticker")]
    perf["decisions"] = valid_decisions[-20:]
    sells = []

    # Use pnl_ledger as primary source of realized performance to avoid malformed decision rows
    # skewing dashboard P&L.
    pnl_ledger_summary = _read_pnl_ledger_summary(DATA_DIR / "pnl_ledger.jsonl")
    ledger_count = pnl_ledger_summary.get("count", 0)
    if ledger_count > 0:
        wins = pnl_ledger_summary.get("wins", 0)
        perf["win_rate_30d"] = round(100 * wins / ledger_count, 1)
        perf["realized_pnl"] = pnl_ledger_summary.get("realized_pnl", 0.0)
        perf["total_pnl"] = perf["realized_pnl"]
    else:
        sells = [
            d for d in valid_decisions
            if d.get("action") == "SELL" and _safe_float(d.get("pnl")) is not None
        ]
        if sells:
            wins = sum(1 for s in sells if (_safe_float(s.get("pnl")) or 0) > 0)
            perf["win_rate_30d"] = round(100 * wins / len(sells), 1)
            perf["realized_pnl"] = round(sum((_safe_float(s.get("pnl")) or 0.0) for s in sells), 2)
            perf["total_pnl"] = perf["realized_pnl"]
    if sells:
        # Aggregate per-strategy stats
        strategy_stats = {}
        for s in sells:
            key = s.get("strategy_id") or s.get("strategy") or "Unknown"
            info = strategy_stats.setdefault(key, {"name": key, "trades": 0, "wins": 0, "pnl": 0.0})
            info["trades"] += 1
            pnl = _safe_float(s.get("pnl"))
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
    unrealized_pnl = round(sum(float(p.get("pnl") or 0) for p in positions), 2)
    perf["unrealized_pnl"] = unrealized_pnl
    total = float(perf.get("realized_pnl") or perf.get("total_pnl") or 0) + unrealized_pnl
    perf["net_pnl"] = round(total, 2)
    perf["total_pnl"] = perf["net_pnl"]  # backward compat: total_pnl == net_pnl
    perf["recent_trades"] = list(reversed(valid_decisions[-15:]))

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
        screening_meta = latest.get("screening_meta") or {}
        entry_gate = latest.get("entry_gate_summary") or {}
        risk_gate = latest.get("risk_gate_summary") or {}

        # If daily_signals hasn't been regenerated yet, fall back to the newest
        # screener telemetry so the dashboard doesn't lag behind.
        try:
            meta_path = DATA_DIR / "last_screening_meta.json"
            if meta_path.exists():
                latest_meta = _read_json(meta_path, default={}) or {}

                meta_universe_size = latest_meta.get("universe_size")
                daily_screening_universe = screening_meta.get("universe_size")

                # `daily_signals_*` does not reliably expose a top-level `universe_size`,
                # but it *does* embed it inside `screening_meta`.
                # If the meta universe differs from the daily_signals universe (or tier telemetry is missing),
                # overlay numeric + tier telemetry from the newest screener meta.
                should_overlay_from_meta = (
                    meta_universe_size is not None
                    and (
                        daily_screening_universe is None
                        or str(daily_screening_universe) != str(meta_universe_size)
                        or screening_meta.get("tiers_configured") is None
                    )
                )

                if should_overlay_from_meta:
                    universe_size = latest_meta.get("universe_size", universe_size)
                    screening_meta["passed_all_filters"] = latest_meta.get("passed_all_filters")
                    screening_meta["filter_counts"] = latest_meta.get("filter_counts") or {}
                    # Ensure the UI's "Candidates" reflects the newest screener telemetry.
                    screening_meta["candidates_found"] = latest_meta.get("candidates_found")

                    # Tier telemetry (keep orchestration-derived strict/hedge gate fields intact).
                    for k in [
                        "tiers_configured",
                        "tiers_scanned",
                        "tier_stop_reason",
                        "screening_target_candidates_per_run",
                        "prefilter_workers",
                        "max_screening_runtime_seconds",
                        "screening_started_at",
                        "screening_finished_at",
                        "screening_duration_seconds",
                    ]:
                        if latest_meta.get(k) is not None:
                            screening_meta[k] = latest_meta.get(k)
        except Exception:
            pass

        if universe_size is None:
            # Fallback: prefer daily_signals' screening_meta over older meta files.
            universe_size = screening_meta.get("universe_size")
        # Fallback: try meta file if daily_signals lacks universe_size
        if universe_size is None:
            try:
                meta_path = DATA_DIR / "last_screening_meta.json"
                if meta_path.exists():
                    meta = _read_json(meta_path, default={})
                    universe_size = meta.get("universe_size", universe_size)
            except Exception:
                pass

        # Derived pre-filter metrics (screener gates).
        prefilter_passed = screening_meta.get("passed_all_filters")
        prefilter_filtered = None
        if universe_size is not None and prefilter_passed is not None:
            try:
                prefilter_filtered = int(universe_size) - int(prefilter_passed)
            except Exception:
                prefilter_filtered = None

        filter_counts = screening_meta.get("filter_counts") or {}
        top_prefilter_reasons = []
        if isinstance(filter_counts, dict) and filter_counts:
            try:
                top_prefilter_reasons = [
                    {"reason": reason, "count": count}
                    for reason, count in sorted(filter_counts.items(), key=lambda kv: kv[1], reverse=True)[:4]
                ]
            except Exception:
                top_prefilter_reasons = []

        perf["latest_screening"] = {
            "date": latest.get("timestamp", "")[:10],
            "time": time_str,
            "candidates_found": screening_meta.get("candidates_found", latest.get("candidates_found", 0)),
            "universe_size": universe_size,
            "tiers_configured": screening_meta.get("tiers_configured"),
            "tiers_scanned": screening_meta.get("tiers_scanned"),
            "tier_stop_reason": screening_meta.get("tier_stop_reason"),
            "screening_target_candidates_per_run": screening_meta.get("screening_target_candidates_per_run"),
            "prefilter_workers": screening_meta.get("prefilter_workers"),
            "max_screening_runtime_seconds": screening_meta.get("max_screening_runtime_seconds"),
            "screening_started_at": screening_meta.get("screening_started_at"),
            "screening_finished_at": screening_meta.get("screening_finished_at"),
            "screening_duration_seconds": screening_meta.get("screening_duration_seconds"),
            "prefilter_passed": prefilter_passed if prefilter_passed is not None else latest.get("candidates_found", 0),
            "prefilter_filtered": prefilter_filtered,
            "approved": len(latest.get("approved_trades", [])),
            "rejected": len(latest.get("rejected_trades", [])),
            "entry_buy": entry_gate.get("buy_count"),
            "entry_skip": entry_gate.get("skip_count"),
            "top_entry_skip_reasons": entry_gate.get("top_skip_reasons") or [],
            "risk_approved": risk_gate.get("approved_count"),
            "risk_rejected": risk_gate.get("rejected_count"),
            "top_risk_rejected_reasons": risk_gate.get("top_rejected_reasons") or [],
            "strict_mode": screening_meta.get("strict_mode"),
            "strict_mode_reason": screening_meta.get("strict_mode_reason"),
            "hedge_gate_passed": (screening_meta.get("hedge_gate") or {}).get("passed"),
            "hedge_gate_applied_count": (screening_meta.get("hedge_gate") or {}).get("applied_count"),
            "hedge_gate_total_known": (screening_meta.get("hedge_gate") or {}).get("total_known"),
            "auto_executed": len((latest.get("auto_execution") or {}).get("executed", [])),
            "execution_gate_summary": latest.get("execution_gate_summary") or {},
            "top_prefilter_reasons": top_prefilter_reasons,
            "top_candidates": top_candidates,
        }
        try:
            from agents.risk_guardian import get_risk_status

            rlive = get_risk_status() or {}
            sm, smr = _strict_mode_live(rlive)
            perf["latest_screening"]["strict_mode"] = sm
            perf["latest_screening"]["strict_mode_reason"] = smr
        except Exception:
            pass

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
            latest_fort_path = Path(fort_files[0])
            report_age_hours = (time.time() - latest_fort_path.stat().st_mtime) / 3600.0
            is_fresh = report_age_hours <= FORTRESS_REPORT_MAX_AGE_HOURS
            latest_fort = _read_json(latest_fort_path, default={})
            mc = latest_fort.get("market_conditions") or {}
            targets = latest_fort.get("target_allocations") or {}
            strat = latest_fort.get("strategies") or {}
            bonds = strat.get("bonds") or {}
            commodities = strat.get("commodities") or {}
            forex = strat.get("forex") or {}
            vix_ins = strat.get("vix_insurance") or {}
            theta = strat.get("theta_spreads") or {}
            dividend = strat.get("dividend_capture") or {}
            pairs = strat.get("pairs_trading") or {}
            perf["hedging"] = {
                "regime": mc.get("regime"),
                "vix": mc.get("vix"),
                "usd_strength": mc.get("usd_strength"),
                "note": latest_fort.get("note"),
                "report_age_hours": round(report_age_hours, 2),
                "report_fresh": is_fresh,
                "target_allocations": targets,
                "bonds_target": bonds.get("target"),
                "commodities": commodities,
                "forex": forex,
                "vix_insurance": vix_ins,
                "theta_spreads": theta,
                "dividend_capture": dividend,
                "pairs_trading": pairs,
            }
            if not is_fresh:
                perf["hedging"]["note"] = (
                    f"STALE fortress report ({round(report_age_hours, 2)}h old); "
                    "run fortress cycle to refresh hedge context"
                )
            # Strategy applied vs skipped transparency (what hedges passed their gates today).
            try:
                if not is_fresh:
                    perf["hedging"]["strategy_gate_metrics"] = {
                        "applied_count": 0,
                        "skipped_count": 0,
                        "not_evaluated_count": 0,
                        "total_known": 0,
                    }
                    perf["hedging"]["strategy_gate_details"] = {}
                else:
                    known_strategies = [
                        "bonds",
                        "commodities",
                        "forex",
                        "vix_insurance",
                        "theta_spreads",
                        "dividend_capture",
                        "pairs_trading",
                    ]
                    strategy_details = {}
                    applied = skipped = not_evaluated = 0
                    for name in known_strategies:
                        s = strat.get(name)
                        if not isinstance(s, dict):
                            not_evaluated += 1
                            strategy_details[name] = {"status": "not_evaluated"}
                            continue

                        if name == "bonds":
                            status = "applied" if s.get("target") is not None else "skipped"
                            if status == "applied":
                                applied += 1
                            else:
                                skipped += 1
                            strategy_details[name] = {
                                "status": status,
                                "target": s.get("target"),
                            }
                            continue

                        action = s.get("action")
                        reason = s.get("reason") or s.get("opportunity") or ""
                        if action is None:
                            not_evaluated += 1
                            status = "not_evaluated"
                        elif str(action).upper() in ["SKIP", "NONE", "HOLD"]:
                            skipped += 1
                            status = "skipped"
                        else:
                            applied += 1
                            status = "applied"

                        strategy_details[name] = {
                            "status": status,
                            "action": action,
                            "reason": reason,
                        }

                    perf["hedging"]["strategy_gate_metrics"] = {
                        "applied_count": applied,
                        "skipped_count": skipped,
                        "not_evaluated_count": not_evaluated,
                        "total_known": len(known_strategies),
                    }
                    perf["hedging"]["strategy_gate_details"] = strategy_details
            except Exception:
                pass
    except Exception:
        perf["hedging"] = {}

    try:
        perf["trust_ledger_recent"] = read_recent_trust_events(limit=10)
    except Exception:
        perf["trust_ledger_recent"] = []

    # Agentic artifacts (Task 5-8)
    # These are planning-only JSON artifacts produced by autonomous layers; they
    # are safe to read in the UI any time.
    try:
        scout = _read_latest_json_glob(DATA_DIR / "scout_opportunity_queue_*.json", default={})
        cio = _read_latest_json_glob(DATA_DIR / "cio_directive_*.json", default={})
        analyst = _read_latest_json_glob(DATA_DIR / "analyst_consensus_*.json", default={})
        mtf = _read_latest_json_glob(DATA_DIR / "multi_timeframe_plan_*.json", default={})
        sector = _read_latest_json_glob(DATA_DIR / "sector_rotation_signal_*.json", default={})
        geo = _read_latest_json_glob(DATA_DIR / "geographic_allocation_plan_*.json", default={})

        def _top_list(d: dict, key: str, n: int = 5):
            v = d.get(key)
            if not isinstance(v, list):
                return []
            return v[:n]

        # Multi-timeframe: produce a compact, UI-friendly summary.
        mtf_sleeves = mtf.get("sleeves") or {}
        mtf_summary = []
        if isinstance(mtf_sleeves, dict):
            for sleeve_key, row in mtf_sleeves.items():
                if not isinstance(row, dict):
                    continue
                mtf_summary.append(
                    {
                        "sleeve": sleeve_key,
                        "active": bool(row.get("active")),
                        "selected": row.get("selected_count") if row.get("selected_count") is not None else None,
                    }
                )
        mtf_summary.sort(key=lambda x: x.get("sleeve") or "")

        available = any(
            bool(x)
            for x in [
                scout,
                cio,
                analyst,
                mtf,
                sector,
                geo,
            ]
        )
        perf["agentic_artifacts"] = {
            "available": available,
            "scout_queue": {
                "timestamp": scout.get("timestamp"),
                "opportunity_count": scout.get("opportunity_count"),
                "top_opportunities": _top_list(scout, "opportunities", 5),
            },
            "cio_directive": {
                "timestamp": cio.get("timestamp"),
                "portfolio_directive": cio.get("portfolio_directive"),
                "confidence": cio.get("confidence"),
                "regime": cio.get("regime"),
                "vix": cio.get("vix"),
            },
            "analyst_consensus": {
                "timestamp": analyst.get("timestamp"),
                "evaluated": analyst.get("evaluated"),
                "recommendations_top": _top_list(analyst, "recommendations", 5),
            },
            "multi_timeframe_plan": {
                "timestamp": mtf.get("timestamp"),
                "regime": mtf.get("regime"),
                "vix": mtf.get("vix"),
                "candidates_found": mtf.get("candidates_found"),
                "sleeves_summary": mtf_summary,
            },
            "sector_rotation": {
                "timestamp": sector.get("timestamp"),
                "macro_quadrant": sector.get("macro_quadrant"),
                "vix": sector.get("vix"),
                "signals": sector.get("signals") if isinstance(sector.get("signals"), list) else [],
            },
            "geographic_allocation": {
                "timestamp": geo.get("timestamp"),
                "international_sleeve_pct": geo.get("international_sleeve_pct"),
                "international_capital_usd": geo.get("international_capital_usd"),
                "allocations": geo.get("allocations") if isinstance(geo.get("allocations"), list) else [],
            },
        }
    except Exception:
        perf["agentic_artifacts"] = {"available": False}

    try:
        from utils.execution_mode import get_execution_mode
        from utils.pending_execution_queue import pending_summary

        perf["execution_mode"] = get_execution_mode()
        ps = pending_summary(DATA_DIR)
        perf["pending_execution_batches"] = ps["batch_count"]
        perf["pending_execution_trades"] = ps["trade_count"]
        perf["pending_execution_path"] = ps["path"]
    except Exception:
        perf["execution_mode"] = "autonomous"
        perf["pending_execution_batches"] = 0
        perf["pending_execution_trades"] = 0
        perf["pending_execution_path"] = str(DATA_DIR / "pending_execution_queue.json")

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

    # 4) Market headlines for context (tickers from config).
    assets = require_market_assets()
    market_headline_tickers = assets.get("market_headline_tickers") or []
    for market_ticker in market_headline_tickers[:3]:
        for title, url in _fetch_news_for_ticker(market_ticker, limit=3):
            key = _normalize_headline(title)
            if key and key not in seen:
                seen.add(key)
                candidates.append((source_priority["market"], market_ticker, title, "market", url or ""))

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


def _parse_iso_dt(value):
    try:
        if not value:
            return None
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _latest_fortress_report_is_fresh(max_age_hours: float = 36.0) -> bool:
    try:
        fort_pattern = DATA_DIR / "fortress_report_*.json"
        fort_files = sorted(glob.glob(str(fort_pattern)), reverse=True)
        if not fort_files:
            return False
        latest = Path(fort_files[0])
        age_hours = (time.time() - latest.stat().st_mtime) / 3600.0
        return age_hours <= max_age_hours
    except Exception:
        return False


def _latest_release_snapshot_dict() -> dict:
    try:
        pat = str(DATA_DIR / "release_snapshots" / "release_snapshot_*.json")
        files = sorted(glob.glob(pat), reverse=True)
        if not files:
            return {}
        return _read_json(Path(files[0]), default={}) or {}
    except Exception:
        return {}


def _strict_mode_live(risk: dict) -> tuple[bool, str]:
    """Align with orchestrator daily screening: strict if circuit tripped or consecutive_losses >= 2."""
    circuit = bool(risk.get("circuit_breaker_active"))
    consec = int(risk.get("consecutive_losses") or 0)
    if circuit:
        return True, f"circuit_breaker_active (consecutive_losses={consec})"
    if consec >= 2:
        return True, f"consecutive_losses={consec} >= 2"
    return False, "normal"


def get_safety_status():
    risk = {}
    try:
        from agents.risk_guardian import get_risk_status
        risk = get_risk_status() or {}
    except Exception:
        risk = {}

    perf = get_trading_performance()
    screening = perf.get("latest_screening") or {}
    policy = get_profile_bundle()

    rollback = {}
    guard = {}
    try:
        from utils.policy_guardrails import get_public_rollback_status, get_guardrails

        rollback = get_public_rollback_status()
        guard = get_guardrails()
    except Exception:
        pass

    heartbeat_last_run = None
    hb = AGENT_LOGS.get("cron_heartbeat", {})
    hb_log = hb.get("log")
    if hb_log and hb_log.exists():
        heartbeat_last_run = datetime.fromtimestamp(hb_log.stat().st_mtime).isoformat()

    hs = get_halt_state()
    strict_now, strict_reason_now = _strict_mode_live(risk)

    # Risk guardian auto-reset (for operator clarity).
    auto_reset_enabled = str(os.getenv("FORTRESS_AUTO_RESET_RISK_GUARDIAN_STATE", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    risk_state_max_age_hours = float(os.getenv("FORTRESS_RISK_STATE_MAX_AGE_HOURS", "24"))

    # Entry gating defaults: useful to explain why screening yields 0 BUYs.
    entry_window_end_et = None
    entry_stabilization_factor = None
    try:
        from agents import entry_agent as _entry_agent

        eh, em = _entry_agent._entry_window_end_with_extension()
        entry_window_end_et = f"{eh:02d}:{em:02d}"
        entry_stabilization_factor = float(getattr(_entry_agent, "STABILIZATION_FACTOR", None))
    except Exception:
        pass

    return {
        "timestamp": datetime.now().isoformat(),
        "policy_profile": policy.get("active_profile"),
        "shadow_mode_enabled": bool(guard.get("shadow_mode_enabled")),
        "shadow_candidate_profile": guard.get("shadow_candidate_profile"),
        "forced_rollback_profile": rollback.get("forced_profile"),
        "forced_rollback_until": rollback.get("forced_until"),
        "circuit_breaker_active": bool(risk.get("circuit_breaker_active")),
        "consecutive_losses": risk.get("consecutive_losses"),
        "position_size_reduction": risk.get("position_size_reduction"),
        "risk_auto_reset_enabled": auto_reset_enabled,
        "risk_state_max_age_hours": risk_state_max_age_hours,
        "strict_mode": strict_now,
        "strict_mode_reason": strict_reason_now,
        "latest_screening_time": screening.get("time"),
        "latest_screening_date": screening.get("date"),
        "last_screening_finished_at": screening.get("screening_finished_at"),
        "hedge_gate_passed": screening.get("hedge_gate_passed"),
        "cron_heartbeat_last_run": heartbeat_last_run,
        "open_positions": perf.get("positions_count", 0),
        "net_pnl": perf.get("net_pnl"),
        "latest_release_signature": (_latest_release_snapshot_dict() or {}).get("signature_sha256"),
        "trading_halt": hs,
        "trading_halt_active": bool(hs.get("effective_halted")),
        "entry_window_end_et": entry_window_end_et,
        "entry_stabilization_factor": entry_stabilization_factor,
    }


def get_headline_event_status() -> dict:
    """
    Summarize headline_event_agent outputs for Command Center (shadow ledger + latest shadow file).
    """
    data_dir = DATA_DIR
    out: dict = {
        "timestamp": datetime.now().isoformat(),
        "enabled": os.getenv("HEADLINE_EVENT_AGENT_ENABLED", "1").strip().lower()
        not in ("0", "false", "no"),
        "mode": "shadow_only",
        "events_path": str(data_dir / "headline_events.jsonl"),
        "events_line_count": 0,
        "last_event": None,
        "shadow_latest_name": None,
        "shadow_latest_mtime": None,
        "shadow_preview": [],
        "doc": "docs/HEADLINE_EVENT_AGENT_SKETCH.md",
        "note": "Shadow-only signals; no auto-execution from this agent.",
    }
    for name in ("headline_event_agent.yaml", "headline_event_agent.example.yaml"):
        p = _ROOT / "config" / name
        if not p.is_file():
            continue
        try:
            import yaml

            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            out["mode"] = str(cfg.get("mode") or out["mode"])
            break
        except ImportError:
            break
        except Exception:
            continue

    ev_path = data_dir / "headline_events.jsonl"
    if ev_path.is_file():
        try:
            lines = [x for x in ev_path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
            out["events_line_count"] = len(lines)
            for line in reversed(lines):
                try:
                    out["last_event"] = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    shadow_files = sorted(glob.glob(str(data_dir / "headline_event_shadow_*.jsonl")), reverse=True)
    if shadow_files:
        sp = Path(shadow_files[0])
        out["shadow_latest_name"] = sp.name
        try:
            out["shadow_latest_mtime"] = datetime.fromtimestamp(sp.stat().st_mtime).isoformat()
            raw_lines = [x for x in sp.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
            for line in raw_lines[-12:]:
                try:
                    out["shadow_preview"].append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    return out


def _to_action_queue_item(item: dict) -> dict:
    severity = str(item.get("severity") or "low").lower()
    priority_map = {"high": 1, "medium": 2, "low": 3}
    impact_map = {"high": "high", "medium": "medium", "low": "low"}
    effort = "medium"
    action = str(item.get("action") or "")
    if "run " in action.lower() or "check " in action.lower():
        effort = "low"
    if "fix " in action.lower() or "review " in action.lower():
        effort = "medium"

    return {
        "priority": priority_map.get(severity, 3),
        "impact": impact_map.get(severity, "low"),
        "effort": effort,
        "title": item.get("title"),
        "body": item.get("body"),
        "action": action,
        "severity": severity,
        "type": item.get("type"),
    }


def get_recommendation_action_queue():
    recs = get_recommendations()
    items = [_to_action_queue_item(i) for i in recs.get("items", []) if isinstance(i, dict)]
    items.sort(key=lambda x: (x.get("priority", 9), x.get("effort", "z"), x.get("title") or ""))
    return {"timestamp": datetime.now().isoformat(), "items": items[:20]}


def get_why_this_trade():
    out = {"timestamp": datetime.now().isoformat(), "items": []}
    pattern = DATA_DIR / "daily_signals_*.json"
    files = sorted(glob.glob(str(pattern)), reverse=True)
    if not files:
        return out
    latest = _read_json(Path(files[0]), default={}) or {}
    approved = latest.get("approved_trades") or []
    for t in approved[:10]:
        if not isinstance(t, dict):
            continue
        out["items"].append({
            "ticker": t.get("ticker"),
            "confidence": t.get("confidence"),
            "entry_price": t.get("entry_price"),
            "position_size": t.get("position_size"),
            "reasoning": t.get("reasoning") or t.get("reason"),
            "risk_summary": (t.get("risk_check") or {}).get("reason"),
            "grok_sentiment": t.get("grok_sentiment"),
            "vision_signal": (t.get("vision_analysis") or {}).get("signal") if isinstance(t.get("vision_analysis"), dict) else None,
            "timestamp": t.get("timestamp") or latest.get("timestamp"),
        })
    return out


def get_runbooks():
    return {
        "timestamp": datetime.now().isoformat(),
        "items": [
            {
                "id": "run_screen_now",
                "title": "Run Daily Screening Now",
                "impact": "Find and evaluate new opportunities immediately.",
                "command": "python3 orchestrator.py screen",
            },
            {
                "id": "run_monitor_now",
                "title": "Run Exit Monitor Now",
                "impact": "Refresh exits and stop/take-profit checks.",
                "command": "python3 orchestrator.py monitor",
            },
            {
                "id": "run_fortress_now",
                "title": "Run Fortress Hedge Refresh",
                "impact": "Recompute hedge recommendations and regime guards.",
                "command": "python3 orchestrator.py fortress",
            },
            {
                "id": "run_health_now",
                "title": "Run System Health Check",
                "impact": "Validate runtime dependencies and service health.",
                "command": "python3 check_health.py",
            },
            {
                "id": "run_drift_detector",
                "title": "Run Drift Detector",
                "impact": "Detect meaningful degradation versus prior trade window.",
                "command": "python3 agents/drift_detector.py",
            },
            {
                "id": "write_release_snapshot",
                "title": "Write Signed Release Snapshot",
                "impact": "Create immutable fallback marker with signature.",
                "command": "python3 utils/release_snapshot.py",
            },
            {
                "id": "walk_forward_refresh",
                "title": "Refresh Walk-Forward Report",
                "impact": "Recompute early vs late window P&L stability from ledger.",
                "command": "python3 agents/walk_forward_validator.py",
            },
            {
                "id": "clear_policy_rollback",
                "title": "Clear Forced Policy Rollback",
                "impact": "Remove drift-triggered profile override (after review).",
                "command": 'python3 -c "from utils.policy_guardrails import clear_forced_rollback; import json; print(json.dumps(clear_forced_rollback()))"',
            },
            {
                "id": "export_audit_bundle",
                "title": "Export audit bundle (ZIP)",
                "impact": "Zip trust ledger, operational runs, halt file + SHA-256 manifest for custody / review.",
                "command": "python3 scripts/export_audit_bundle.py",
            },
            {
                "id": "operator_morning_brief",
                "title": "Operator Morning Brief (dashboard)",
                "impact": "Session, macro pulse, compliance-style ops tip, stack checklist, book-aware rows — GET /api/operator_brief.",
                "command": "curl -s http://127.0.0.1:8083/api/operator_brief | head -c 400",
            },
            {
                "id": "install_tv_signal_policy",
                "title": "Install tv_signal_sleeve policy template",
                "impact": "Merge TradingView-oriented risk sleeve into policy_profiles.json (optional --activate).",
                "command": "python3 scripts/install_policy_template.py tv_signal_sleeve",
            },
            {
                "id": "test_tradingview_webhook",
                "title": "Test TradingView webhook (POST sample)",
                "impact": "Append one row to data/tradingview_signal_queue.jsonl; use your secret in URL if set.",
                "command": 'curl -s -X POST "http://127.0.0.1:8083/api/hooks/tradingview?secret=YOUR_SECRET" -H "Content-Type: text/plain" -d "AAPL long"',
            },
            {
                "id": "execution_mode_autonomous",
                "title": "Autonomous execution (.env)",
                "impact": "Set FORTRESS_EXECUTION_MODE=autonomous so screening/sniper submit approved orders automatically (still gated by halt + pre-trade gate).",
                "command": "grep FORTRESS_EXECUTION_MODE .env || echo 'FORTRESS_EXECUTION_MODE=autonomous' >> .env",
            },
            {
                "id": "execution_mode_hitl",
                "title": "Human-in-the-loop execution (.env)",
                "impact": "Set FORTRESS_EXECUTION_MODE=human_in_loop — approved buys go to data/pending_execution_queue.json; exits via monitor still autonomous unless you halt.",
                "command": "echo 'FORTRESS_EXECUTION_MODE=human_in_loop' >> .env  # then restart dashboard / cron",
            },
            {
                "id": "execute_pending_trades",
                "title": "Submit queued HITL trades",
                "impact": "After reviewing pending_execution_queue.json, run once to submit all queued batches (pre-trade gate still applies).",
                "command": "python3 orchestrator.py execute_pending",
            },
            {
                "id": "ops_recovery_pipeline",
                "title": "Ops recovery (fortress → screen → execute_pending)",
                "impact": "Refreshes regime files, reruns daily screen, flushes HITL queue. Use after stale logs or missed cadence. Flags: --no-fortress --no-screen --no-pending",
                "command": "python3 orchestrator.py ops_recovery",
            },
            {
                "id": "regime_check_cli",
                "title": "Print regime / hedge file snapshot",
                "impact": "Read-only: latest fortress_report + hedging_recommendations.json presence.",
                "command": "python3 orchestrator.py regime_check",
            },
            {
                "id": "print_entry_skips_cli",
                "title": "Print latest entry_gate skip reasons",
                "impact": "Shows newest daily_signals entry_gate_summary for tuning ENTRY_WINDOW_* / RSI via current_params.json.",
                "command": "python3 orchestrator.py print_entry_skips",
            },
            {
                "id": "agentic_scout_swarm",
                "title": "Build scout opportunity queue",
                "impact": "Runs Task 6 scout swarm and writes scout_opportunity_queue_*.json for later analysis/execution gating.",
                "command": "python3 orchestrator.py scout_swarm",
            },
            {
                "id": "agentic_analyst_ensemble",
                "title": "Run analyst ensemble consensus",
                "impact": "Runs Task 7 analyst quorum from the latest scout queue and writes analyst_consensus_*.json.",
                "command": "python3 orchestrator.py analyst_ensemble",
            },
            {
                "id": "agentic_cio_cycle",
                "title": "Produce top-level CIO directive",
                "impact": "Runs Task 5 deterministic CIO cycle using latest planning artifacts and writes cio_directive_*.json.",
                "command": "python3 orchestrator.py cio_cycle",
            },
            {
                "id": "agentic_task1_multi_timeframe",
                "title": "Run Task 1 multi-timeframe planner",
                "impact": "Runs Task 1 sleeve allocation framework and writes multi_timeframe_plan_*.json.",
                "command": "python3 orchestrator.py multi_timeframe",
            },
            {
                "id": "agentic_sector_rotation",
                "title": "Run sector rotation signal",
                "impact": "Runs Task 3 sector rotation and writes sector_rotation_signal_*.json.",
                "command": "python3 orchestrator.py sector_rotation",
            },
            {
                "id": "agentic_geographic_allocation",
                "title": "Run geographic allocation plan",
                "impact": "Runs Task 4 international allocation planner and writes geographic_allocation_plan_*.json.",
                "command": "python3 orchestrator.py geographic_allocation",
            },
        ],
    }


def get_trust_report():
    """Aggregate trust artifacts for operators and monetization demos."""
    policy_payload = _read_json(CONFIG_DIR / "policy_profiles.json", default={}) or {}
    drift = _read_json(DATA_DIR / "drift_report.json", default={}) or {}
    wf = _read_json(DATA_DIR / "walk_forward_report.json", default={}) or {}
    if not wf:
        try:
            from agents.walk_forward_validator import compute_walk_forward_report

            wf = compute_walk_forward_report()
        except Exception:
            wf = {}
    guard = {}
    rollback = {}
    try:
        from utils.policy_guardrails import get_guardrails, get_public_rollback_status

        guard = get_guardrails()
        rollback = get_public_rollback_status()
    except Exception:
        pass
    policy_bundle = get_profile_bundle()
    rv = {}
    try:
        from agents.walk_forward_validator import get_research_verdict

        rv = get_research_verdict()
    except Exception:
        rv = {"verdict": "unknown", "headline": "Walk-forward unavailable."}
    bt = read_backtest_snapshot()
    return {
        "timestamp": datetime.now().isoformat(),
        "effective_policy_profile": policy_bundle.get("active_profile"),
        "configured_active_profile": policy_payload.get("active_profile"),
        "guardrails": guard,
        "rollback": rollback,
        "drift": drift,
        "walk_forward": wf,
        "research_verdict": rv,
        "backtest_snapshot": bt,
        "trust_ledger_recent": read_recent_trust_events(20),
        "latest_release_snapshot": _latest_release_snapshot_dict(),
    }


def get_intelligence_brief_status() -> dict:
    """
    Load latest fortress intelligence brief JSON + short markdown preview.
    """
    out = {
        "timestamp": datetime.now().isoformat(),
        "available": False,
        "json_path": None,
        "markdown_path": None,
        "brief": {},
        "markdown_preview": "",
    }
    files = sorted(glob.glob(str(DATA_DIR / "fortress_intelligence_brief_*.json")), reverse=True)
    if not files:
        return out
    jp = Path(files[0])
    out["json_path"] = str(jp)
    out["available"] = True
    out["brief"] = _read_json(jp, default={}) or {}
    md = jp.with_suffix(".md")
    if md.exists():
        out["markdown_path"] = str(md)
        try:
            txt = md.read_text(encoding="utf-8", errors="replace")
            out["markdown_preview"] = "\n".join(txt.splitlines()[:40])
        except OSError:
            out["markdown_preview"] = ""
    return out


def get_pricing_gates():
    return _read_json(CONFIG_DIR / "pricing_gates.json", default={"tiers": [], "disclaimer": ""})


def get_product_funnel():
    return _read_json(CONFIG_DIR / "product_funnel.json", default={})


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
        latest_perf = get_trading_performance()
        latest_screening = latest_perf.get("latest_screening") or {}
        candidates_found = int(latest_screening.get("candidates_found") or 0)
        fortress_fresh = _latest_fortress_report_is_fresh()
        now = datetime.now()
        cron_out = _aggregate_cron_text()

        # Agent IDs that are stale-noisy in this build (legacy/no-op supervisors).
        always_suppress_ids = {"agent_manager", "main_loop"}
        conditional_ids = {"entry", "grok", "document_analyst", "vision_analyst", "performance_analyzer", "sync", "momentum", "smart_money", "merger_arb"}
        fortress_family_ids = {
            "fortress",
            "fortress_dashboard",
            "fortress_orchestrator",
            "bond_manager",
            "commodity_trader",
            "forex_hedger",
            "forex_sniper",
            "theta_spreads",
            "dividend_capture",
            "pairs_trader",
            "vix_insurance",
        }
        # Keep recommendations focused on jobs that are operationally expected to run.
        critical_ids = {
            "screener",
            "monitor",
            "sniper",
            "fortress",
            "llama_watchdog",
            "error_detective",
            "cron_heartbeat",
            "weekly",
            "meta_architect",
        }
        schedule_hints = {
            "screener": "Scheduled weekdays at 15:00 ET (orchestrator.py screen).",
            "monitor": "Scheduled every 5 minutes during market hours (orchestrator.py monitor).",
            "sniper": "Scheduled every 5 minutes during market hours (orchestrator.py snipe).",
            "fortress": "Scheduled daily at 00:00 ET (orchestrator.py fortress).",
            "llama_watchdog": "Scheduled weekdays at 07:00 ET (orchestrator.py watchdog).",
            "error_detective": "Scheduled daily at 06:00 ET (agents/error_detective.py).",
            "cron_heartbeat": "Scheduled every 5 minutes (cron heartbeat).",
            "weekly": "Scheduled weekly Saturday 07:15 ET (orchestrator.py review).",
            "meta_architect": "Scheduled weekly Saturday 07:30 ET (orchestrator.py tune).",
        }
        stale_added = 0

        for a in activity.get("agents", []):
            if a.get("status") != "stale":
                continue

            agent_id = a.get("id")
            last_run = a.get("last_run")
            last_dt = _parse_iso_dt(last_run)
            age_days = (now - last_dt).total_seconds() / 86400.0 if last_dt else None

            if agent_id in always_suppress_ids:
                continue

            # Suppress stale alerts for non-critical/non-scheduled agents to reduce noise.
            if agent_id not in critical_ids:
                continue

            # If screening produced zero candidates, these agents are expected to be idle.
            if agent_id in conditional_ids and candidates_found == 0:
                continue

            # If fortress report is fresh, suppress stale warnings for fortress sub-agents.
            if agent_id in fortress_family_ids and fortress_fresh:
                continue

            # Weekly jobs should only alert if they are more than ~one week stale.
            if agent_id in {"weekly", "meta_architect"}:
                if age_days is None or age_days <= 8:
                    continue

            # Sniper only alerts when stale during active market hours.
            if agent_id == "sniper" and not _is_market_hours():
                continue

            # If agent has an explicit cron signature and it's absent, avoid stale spam.
            if agent_id == "screener" and "orchestrator.py screen" not in cron_out:
                continue
            if agent_id == "monitor" and "orchestrator.py monitor" not in cron_out:
                continue
            if agent_id == "sniper" and "orchestrator.py snipe" not in cron_out:
                continue
            if agent_id == "fortress" and "orchestrator.py fortress" not in cron_out:
                continue
            if agent_id == "llama_watchdog" and "orchestrator.py watchdog" not in cron_out:
                continue
            if agent_id == "error_detective" and "agents/error_detective.py" not in cron_out:
                continue
            if agent_id == "cron_heartbeat" and "cron_heartbeat.log" not in cron_out:
                continue

            if stale_added >= 5:
                continue

            recs["items"].append({
                "type": "agent", "severity": "medium",
                "title": f"{a.get('name')} has not run recently",
                "body": f"Last run: {last_run or 'N/A'}",
                "action": schedule_hints.get(agent_id) or f"Check cron or run {agent_id} manually.",
            })
            stale_added += 1

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

    # Fallback so UI always shows something actionable (hedging snapshot)
    if not recs["items"]:
        try:
            fort_pattern = DATA_DIR / "fortress_report_*.json"
            fort_files = sorted(glob.glob(str(fort_pattern)), reverse=True)
            if fort_files:
                latest_fort = _read_json(Path(fort_files[0]), default={})
                mc = latest_fort.get("market_conditions") or {}
                strat = latest_fort.get("strategies") or {}
                commodities = strat.get("commodities") or {}
                forex = strat.get("forex") or {}
                vix_ins = strat.get("vix_insurance") or {}
                body = (
                    f"Regime={mc.get('regime')}. "
                    f"Commodities={commodities.get('action')}. "
                    f"Forex={forex.get('action')}. "
                    f"VIX Insurance={vix_ins.get('action')}. "
                    f"Note={latest_fort.get('note') or ''}"
                ).strip()
                recs["items"].append({
                    "type": "hedging",
                    "severity": "low",
                    "title": "Hedging snapshot",
                    "body": body[:320],
                    "action": "Review fortress_report_*.json and adjust hedges if needed.",
                })
            else:
                recs["items"].append({
                    "type": "info",
                    "severity": "low",
                    "title": "No recommendations right now",
                    "body": "Risk and agent checks look nominal; no hedging report found for today.",
                    "action": "None",
                })
        except Exception:
            recs["items"].append({
                "type": "info",
                "severity": "low",
                "title": "No recommendations right now",
                "body": "System is running but no actionable recommendations were generated.",
                "action": "None",
            })

    return recs


def _operator_halt_post_allowed() -> bool:
    """If FORTRESS_OPERATOR_TOKEN is set, require token header or valid dashboard Basic auth."""
    token = (os.environ.get("FORTRESS_OPERATOR_TOKEN") or "").strip()
    if not token:
        return True
    hdr = (request.headers.get("X-Operator-Token") or "").strip()
    if hdr == token:
        return True
    user = (os.environ.get("FORTRESS_DASHBOARD_USER") or "").strip()
    pw = (os.environ.get("FORTRESS_DASHBOARD_PASS") or "").strip()
    auth = request.authorization
    if user and pw and auth and auth.username == user and auth.password == pw:
        return True
    return False


def get_chart_bars_json(ticker: str, days: int) -> dict:
    import yfinance as yf

    sym = (ticker or "SPY").strip().upper() or "SPY"
    d = max(5, min(int(days), 800))

    def _hist_to_bars(hist):
        out = []
        if hist is None or hist.empty:
            return out
        for idx, row in hist.iterrows():
            try:
                try:
                    vol_raw = float(row["Volume"])
                    vol = int(vol_raw) if vol_raw == vol_raw else 0
                except Exception:
                    vol = 0
                tstr = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                out.append({
                    "time": tstr,
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": vol,
                })
            except Exception:
                continue
        return out

    t = yf.Ticker(sym)
    hist = t.history(period=f"{d}d", interval="1d", auto_adjust=True)
    bars = _hist_to_bars(hist)
    if not bars:
        try:
            alt = yf.download(sym, period=f"{d}d", interval="1d", progress=False, auto_adjust=True, threads=False)
            bars = _hist_to_bars(alt)
        except Exception:
            pass
    return {"timestamp": datetime.now().isoformat(), "ticker": sym, "bars": bars}


# ---- First-run setup (easy install for non-technical customers) ----
SETUP_COMPLETE_FILE = DATA_DIR / "setup_complete"
ENV_FILE = _ROOT / ".env"


def _setup_status():
    """Returns dict: setup_complete (bool), has_alpaca_keys (bool). Keys never logged."""
    has_keys = False
    if ENV_FILE.exists():
        try:
            text = ENV_FILE.read_text()
            key_val = secret_val = None
            for line in text.splitlines():
                if line.strip().startswith("ALPACA_API_KEY="):
                    key_val = line.split("=", 1)[1].strip().strip('"\'')
                elif line.strip().startswith("ALPACA_SECRET_KEY="):
                    secret_val = line.split("=", 1)[1].strip().strip('"\'')
            if key_val and secret_val and "your_" not in key_val.lower() and "your_" not in secret_val.lower():
                if len(key_val) > 10 and len(secret_val) > 10:
                    has_keys = True
        except Exception:
            pass
    done = SETUP_COMPLETE_FILE.exists()
    return {"setup_complete": done or has_keys, "has_alpaca_keys": has_keys}


def _env_upsert_alpaca(api_key: str, secret_key: str) -> None:
    """Update or add ALPACA_API_KEY and ALPACA_SECRET_KEY in .env. Preserve other vars. Never log keys."""
    lines = []
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            s = line.strip()
            if s.startswith("ALPACA_API_KEY=") or s.startswith("ALPACA_SECRET_KEY="):
                continue
            lines.append(line)
    lines.append(f"ALPACA_API_KEY={api_key}")
    lines.append(f"ALPACA_SECRET_KEY={secret_key}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    # Reload env into process so next request sees them
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE, override=True)
    except Exception:
        pass


@app.route("/setup")
def setup_page():
    """First-run wizard: enter Alpaca keys and test connection."""
    if _setup_status()["setup_complete"]:
        return redirect(url_for("index"))
    return make_response(render_template("setup_wizard.html", version=_get_version()))


@app.route("/api/setup/status")
def api_setup_status():
    return jsonify(_setup_status())


@app.route("/api/setup/save_keys", methods=["POST"])
def api_setup_save_keys():
    """Save Alpaca API key and secret to .env. Never logged or echoed."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        api_key = (data.get("api_key") or "").strip()
        secret_key = (data.get("secret_key") or "").strip()
        if not api_key or not secret_key:
            return jsonify({"ok": False, "error": "API key and secret are required."}), 400
        if "your_" in api_key.lower() or "your_" in secret_key.lower():
            return jsonify({"ok": False, "error": "Please use your real Alpaca keys, not placeholders."}), 400
        if len(api_key) < 10 or len(secret_key) < 10:
            return jsonify({"ok": False, "error": "Keys look too short. Check you copied them fully."}), 400
        _env_upsert_alpaca(api_key, secret_key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/setup/test_connection", methods=["POST"])
def api_setup_test_connection():
    """Test Alpaca connection. On success, mark setup complete."""
    try:
        from alpaca.trading.client import TradingClient
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE, override=True)
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            return jsonify({"ok": False, "error": "No keys found. Save keys first."}), 400
        try:
            client = TradingClient(key, secret, paper=is_alpaca_paper())
        except ValueError as e:
            return jsonify({"ok": False, "error": f"Invalid Alpaca keys: {e}"}), 400
        acc = client.get_account()
        if acc:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETUP_COMPLETE_FILE.write_text("ok")
            return jsonify({"ok": True, "message": "Connection successful. You're all set."})
        return jsonify({"ok": False, "error": "Could not get account."}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


_STRIPE_LINK_KEYS = (
    "STRIPE_PAYMENT_LINK_STARTER",
    "STRIPE_PAYMENT_LINK_PRO",
    "STRIPE_PAYMENT_LINK_ENTERPRISE",
    "STRIPE_CUSTOMER_PORTAL_URL",
)


def _stripe_billing_values_from_dotenv_file() -> dict:
    """
    Read Stripe link URLs from project `.env` on disk.

    systemd `EnvironmentFile=` sometimes drops or mangles long URL lines; the shell
    `python3 -c "load_dotenv(...)"` test can still work while the service process does not.
    """
    path = _ROOT / ".env"
    out: dict = {}
    if not path.is_file():
        return out
    try:
        # utf-8-sig: some editors write a BOM that would otherwise break the first key.
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Shell-style `export FOO=bar` (common in hand-edited .env files).
        if s.lower().startswith("export "):
            s = s[7:].lstrip()
        if "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        if key not in _STRIPE_LINK_KEYS:
            continue
        val = val.strip().strip('"').strip("'")
        if val:
            out[key] = val
    return out


def _billing_links_from_env() -> dict:
    """Optional Stripe Payment Link / portal URLs for /proof (see docs/STRIPE_CHECKOUT_AND_PORTAL.md)."""
    file_vals = _stripe_billing_values_from_dotenv_file()
    labels = {
        "STRIPE_PAYMENT_LINK_STARTER": "Starter",
        "STRIPE_PAYMENT_LINK_PRO": "Pro",
        "STRIPE_PAYMENT_LINK_ENTERPRISE": "Enterprise",
        "STRIPE_CUSTOMER_PORTAL_URL": "Customer portal",
    }
    out = {}
    for env_key, label in labels.items():
        url = (os.environ.get(env_key) or file_vals.get(env_key) or "").strip()
        if url:
            out[label] = url
    return out


@app.route("/proof")
def proof_page():
    """Public-facing trust / proof center (no Alpaca setup required)."""
    resp = make_response(
        render_template(
            "proof_center.html",
            version=_get_version(),
            billing_links=_billing_links_from_env(),
        )
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/billing/proof_links_status")
def proof_billing_proof_links_status():
    """
    Operator/debug: why /proof may show “No links loaded”. Does not expose URLs or secrets.
    """
    path = _ROOT / ".env"
    read_ok = False
    read_err = None
    if path.is_file():
        try:
            path.read_text(encoding="utf-8-sig")
            read_ok = True
        except OSError as e:
            read_err = str(e)
    file_vals = _stripe_billing_values_from_dotenv_file()
    billing = _billing_links_from_env()
    try:
        run_as = getpass.getuser()
    except Exception:
        run_as = ""
    r = jsonify(
        {
            "effective_project_root": str(_ROOT),
            "dotenv_path": str(path.resolve()),
            "dotenv_exists": path.is_file(),
            "dotenv_read_ok": read_ok,
            "dotenv_read_error": read_err,
            "stripe_keys_parsed_from_file": sorted(file_vals.keys()),
            "billing_link_labels_count": len(billing),
            "process_user": run_as,
        }
    )
    r.headers["Cache-Control"] = "no-store"
    return r


@app.route("/performance")
def performance_redirect():
    """Legacy path: analytics live on Command Center (TRADING SNAPSHOT / performance)."""
    if not _setup_status()["setup_complete"]:
        return redirect(url_for("setup_page"))
    return redirect(url_for("index") + "#performance-panel", code=302)


@app.route("/")
def index():
    if not _setup_status()["setup_complete"]:
        return redirect(url_for("setup_page"))
    from flask import make_response
    resp = make_response(render_template("command_center.html", version=_get_version()))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


def _run_pristine_checks():
    """Run pristine verification checks; return dict with passed, checks[], timestamp."""
    checks = []
    all_ok = True
    py = sys.executable

    # 1. Critical imports
    for desc, mod_attr in [
        ("exit_monitor.monitor_positions", ("agents.exit_monitor", "monitor_positions")),
        ("risk_guardian.get_risk_status", ("agents.risk_guardian", "get_risk_status")),
        ("performance_analyzer.analyze_performance", ("agents.performance_analyzer", "analyze_performance")),
    ]:
        try:
            mod = __import__(mod_attr[0], fromlist=[mod_attr[1]])
            getattr(mod, mod_attr[1])
            checks.append({"name": desc, "ok": True, "detail": "OK"})
        except Exception as e:
            checks.append({"name": desc, "ok": False, "detail": str(e)[:120]})
            all_ok = False


    # 2. Strategies
    run_strategies = _ROOT / "run_strategies.py"
    if run_strategies.exists():
        for label, cmd in [
            ("run_strategies.py inefficiency", [py, str(run_strategies), "inefficiency"]),
            ("run_strategies.py sector", [py, str(run_strategies), "sector"]),
        ]:
            try:
                r = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, timeout=120)
                ok = r.returncode == 0
                checks.append({"name": label, "ok": ok, "detail": "exit 0" if ok else (r.stderr or r.stdout or "non-zero exit")[:80]})
                if not ok:
                    all_ok = False
            except Exception as e:
                checks.append({"name": label, "ok": False, "detail": str(e)[:120]})
                all_ok = False
    else:
        checks.append({"name": "run_strategies.py", "ok": True, "detail": "SKIP (not installed)"})
    # 3. Health check
    try:
        r = subprocess.run([py, str(_ROOT / "check_health.py")], cwd=_ROOT, capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0
        checks.append({"name": "check_health.py", "ok": ok, "detail": "exit 0" if ok else "failed"})
        if not ok:
            all_ok = False
    except Exception as e:
        checks.append({"name": "check_health.py", "ok": False, "detail": str(e)[:120]})
        all_ok = False

    return {
        "passed": all_ok,
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


@app.route("/api/pristine")
def api_pristine():
    """Run pristine verification and return pass/fail and per-check results."""
    try:
        result = _run_pristine_checks()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "passed": False,
            "checks": [],
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
        }), 500


@app.route("/api/health")
def api_health():
    return jsonify(get_system_health())


@app.route("/api/system_health")
def api_system_health():
    """Alias of /api/health (same JSON; some docs/scripts used this path)."""
    return jsonify(get_system_health())


@app.route("/api/operator_brief")
def api_operator_brief():
    """Morning brief: session, macro pulse, policy tip, stack checks, book-aware (positions.json)."""
    try:
        from utils.operator_morning_brief import build_operator_morning_brief

        h = get_system_health()
        health_excerpt = {
            "cron_configured": h.get("cron_configured"),
            "cron_count": h.get("cron_count"),
            "validation_errors": h.get("validation_errors", []),
        }
        ss = get_safety_status()
        safety_excerpt = {"circuit_breaker_active": ss.get("circuit_breaker_active")}
        return jsonify(
            build_operator_morning_brief(
                data_dir=DATA_DIR,
                health_excerpt=health_excerpt,
                safety_excerpt=safety_excerpt,
            )
        )
    except Exception as e:
        return jsonify(
            {
                "timestamp": datetime.now().isoformat(),
                "error": "brief_build_failed",
                "detail": str(e)[:500],
                "disclaimer": "Morning Brief failed to build; other dashboard data may still load.",
            }
        )


@app.route("/api/hooks/tradingview", methods=["GET", "POST"])
def api_hooks_tradingview():
    """TradingView alert URL target. Public path; use FORTRESS_TV_WEBHOOK_SECRET + ?secret= or header."""
    from utils.tradingview_webhook import append_tradingview_event, verify_webhook_secret

    if not verify_webhook_secret(
        request.args.get("secret"),
        request.headers.get("X-Fortress-Webhook-Secret"),
    ):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "message": "POST alert payloads here (JSON or plain text). See docs/TRADINGVIEW_WEBHOOK_SETUP.md",
        })
    raw = request.get_data(cache=False, as_text=False) or b""
    ct = request.content_type or ""
    try:
        row = append_tradingview_event(
            raw_body=raw,
            content_type=ct,
            remote_addr=request.remote_addr,
            query_params={k: str(v) for k, v in request.args.items()},
        )
        append_trust_event(
            "tradingview_webhook_received",
            {
                "ticker_guess": row.get("ticker_guess"),
                "parse_kind": row.get("parse_kind"),
            },
        )
        return jsonify({"ok": True, "received_at": row.get("timestamp")}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/billing/stripe-webhook", methods=["POST"])
def api_billing_stripe_webhook():
    """
    Stripe → license file (Lanes 2–3). Public URL; verified with Stripe-Signature + STRIPE_WEBHOOK_SECRET.
    Dashboard URL: https://YOUR_HOST:8083/api/billing/stripe-webhook
    """
    secret = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return jsonify({"error": "stripe_webhook_not_configured"}), 501
    payload = request.get_data(cache=False, as_text=False) or b""
    sig = request.headers.get("Stripe-Signature") or ""
    try:
        import stripe

        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception:
        return jsonify({"error": "webhook_verify_failed"}), 400

    from utils.stripe_license_sync import process_stripe_webhook_event

    path = process_stripe_webhook_event(event)
    if path is None:
        return jsonify({"received": True, "ignored": True}), 200
    try:
        append_trust_event(
            "stripe_license_updated",
            {"path": str(path), "event_type": event.get("type")},
        )
    except Exception:
        pass
    return jsonify({"received": True, "license_path": str(path)}), 200


@app.route("/api/tradingview_signals")
def api_tradingview_signals():
    from utils.tradingview_webhook import read_recent_signals

    lim = request.args.get("limit", default=30, type=int) or 30
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "items": read_recent_signals(limit=lim),
    })


@app.route("/api/agents")
def api_agents():
    return jsonify(get_agent_activity())


@app.route("/api/performance")
def api_performance():
    return jsonify(get_trading_performance())

@app.route("/api/bot_audit")
def api_bot_audit():
    """
    Operator-facing objective audit:
    - near-zero loss health (realized P&L + loss rate + risk_guardian streak)
    - profit opportunity throughput (fills + win rate heuristics)
    - per-strategy breakdown from pnl_ledger + process checks
    - session window from 03:00 America/New_York; contrast vs fortress/hedge files
    - optional delayed benchmark/VIX via yfinance (?market=0 to disable)

    No broker orders; safe to run anytime from Command Center.
    """
    days = request.args.get("days", default=1, type=int) or 1
    lookback_days = request.args.get("lookback_days", default=30, type=int) or 30
    market_raw = (request.args.get("market") or "1").strip().lower()
    include_market = market_raw not in ("0", "false", "no", "off")
    try:
        from agents.bot_audit_agent import audit_bot_performance

        report = audit_bot_performance(
            data_dir=DATA_DIR,
            logs_dir=LOGS_DIR,
            lookback_days=lookback_days,
            audit_days=days,
            include_market=include_market,
        )
        return jsonify(report)
    except Exception as e:
        return jsonify({"timestamp": datetime.now().isoformat(), "ok": False, "error": f"{type(e).__name__}:{e}"}), 500


@app.route("/api/news")
def api_news():
    return jsonify(get_news_and_impact())


@app.route("/api/recommendations")
def api_recommendations():
    return jsonify(get_recommendations())

@app.route("/api/safety_status")
def api_safety_status():
    return jsonify(get_safety_status())


@app.route("/api/headline_event_status")
def api_headline_event_status():
    return jsonify(get_headline_event_status())


@app.route("/api/action_queue")
def api_action_queue():
    return jsonify(get_recommendation_action_queue())


@app.route("/api/trust_ledger")
def api_trust_ledger():
    limit = request.args.get("limit", default=50, type=int)
    items = enrich_trust_ledger_items(read_recent_trust_events(limit=limit))
    return jsonify({"timestamp": datetime.now().isoformat(), "items": items})


@app.route("/api/operator_runs")
def api_operator_runs():
    """Canonical screening run rows (operational_runs.jsonl) for operator UX."""
    return jsonify(
        {
            "timestamp": datetime.now().isoformat(),
            "runs": summarize_screening_runs(),
        }
    )


@app.route("/api/why_trade")
def api_why_trade():
    return jsonify(get_why_this_trade())


@app.route("/api/runbooks")
def api_runbooks():
    return jsonify(get_runbooks())

@app.route("/api/drift")
def api_drift():
    try:
        return jsonify(analyze_drift())
    except Exception as e:
        return jsonify({"timestamp": datetime.now().isoformat(), "drift_alert": None, "reason": str(e)}), 500


@app.route("/api/trust_report")
def api_trust_report():
    return jsonify(get_trust_report())


@app.route("/api/intelligence_brief")
def api_intelligence_brief():
    return jsonify(get_intelligence_brief_status())


@app.route("/manifest.json")
def manifest_json():
    body = {
        "name": "Fortress Command Center",
        "short_name": "Fortress",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#06090f",
        "theme_color": "#00f5d4",
        "icons": [],
    }
    r = make_response(json.dumps(body, indent=2))
    r.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
    r.headers["Cache-Control"] = "public, max-age=3600"
    return r


@app.route("/api/operator/halt", methods=["GET"])
def api_operator_halt_get():
    return jsonify(get_halt_state())


@app.route("/api/operator/halt", methods=["POST"])
def api_operator_halt_post():
    if not _operator_halt_post_allowed():
        return jsonify({"ok": False, "error": "operator_token_or_auth_required"}), 403
    data = request.get_json(force=True, silent=True) or {}
    active = bool(data.get("active"))
    reason = str(data.get("reason") or "")
    actor = str(data.get("actor") or "dashboard")
    prev = get_halt_state().get("file") or {}
    st = set_trading_halt(active, reason=reason, actor=actor)
    send_operator_alert(
        "operator_trading_halt" if active else "operator_trading_resume",
        {"active": active, "reason": reason, "actor": actor},
    )
    append_trust_event(
        "operator_trading_halt_set",
        {"active": active, "reason": reason, "actor": actor, "previous": prev},
    )
    return jsonify({"ok": True, "state": get_halt_state(), "file": st})


@app.route("/api/chart_bars")
def api_chart_bars():
    ticker = request.args.get("ticker", "SPY") or "SPY"
    days = request.args.get("days", default=120, type=int) or 120
    try:
        return jsonify(get_chart_bars_json(ticker, days))
    except Exception as e:
        return jsonify({"timestamp": datetime.now().isoformat(), "error": str(e), "bars": []}), 500


@app.route("/api/backtest")
def api_backtest():
    refresh = request.args.get("refresh", "0") == "1"
    ticker = (request.args.get("ticker") or "SPY").strip() or "SPY"
    if refresh:
        try:
            snap = run_daily_momentum_backtest(ticker)
            append_trust_event("backtest_refreshed", {"ticker": ticker})
            return jsonify(snap)
        except Exception as e:
            return jsonify({"timestamp": datetime.now().isoformat(), "error": str(e)}), 500
    snap = read_backtest_snapshot()
    return jsonify(snap if snap else {"message": "no_snapshot", "timestamp": datetime.now().isoformat()})


@app.route("/api/release_snapshot")
def api_release_snapshot():
    snap = _latest_release_snapshot_dict()
    if not snap:
        return jsonify({"timestamp": datetime.now().isoformat(), "message": "No release snapshots yet"})
    return jsonify(snap)


@app.route("/api/walk_forward")
def api_walk_forward():
    refresh = request.args.get("refresh", "0") == "1"
    if refresh:
        try:
            from agents.walk_forward_validator import write_report

            return jsonify(write_report())
        except Exception as e:
            return jsonify({"timestamp": datetime.now().isoformat(), "error": str(e)}), 500
    r = _read_json(DATA_DIR / "walk_forward_report.json", default={}) or {}
    if not r:
        try:
            from agents.walk_forward_validator import compute_walk_forward_report

            r = compute_walk_forward_report()
        except Exception:
            r = {}
    return jsonify(r or {"timestamp": datetime.now().isoformat(), "reason": "no_data"})


@app.route("/api/pricing_gates")
def api_pricing_gates():
    return jsonify(get_pricing_gates())


@app.route("/api/product_funnel")
def api_product_funnel():
    return jsonify(get_product_funnel())


@app.route("/api/referral")
def api_referral():
    return jsonify(_read_json(CONFIG_DIR / "referral_program.json", default={}))


@app.route("/api/policy/clear_rollback", methods=["POST"])
def api_policy_clear_rollback():
    try:
        from utils.policy_guardrails import clear_forced_rollback

        return jsonify({"ok": True, "state": clear_forced_rollback()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
    """Open positions from Alpaca (preferred) or positions.json; prices enriched with yfinance when possible."""
    out = []
    ts = __import__("datetime").datetime.now().isoformat()
    try:
        import yfinance as yf
        from datetime import datetime

        bl: list | None = None
        broker_err: str | None = None
        positions: list = []
        positions_source: str | None = None
        try:
            from utils.alpaca_broker import fetch_broker_positions

            bl, broker_err = fetch_broker_positions()
            if bl is not None:
                positions = bl
                positions_source = "alpaca_broker"
        except Exception as e:
            broker_err = f"{type(e).__name__}:{e}"
        if bl is None:
            positions = _read_json(DATA_DIR / "positions.json", default=[])
            if isinstance(positions, dict):
                positions = positions.get("positions", [])
            positions_source = "positions_json"
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
            entry = float(p.get("entry_price") or p.get("entry") or 0)
            shares = float(p.get("qty") or p.get("shares") or 0)
            is_broker = p.get("source") == "alpaca_broker"
            if is_broker:
                # Match Alpaca dashboard: use broker unrealized_pl / unrealized_plpc / mark.
                cur_raw = p.get("current_price")
                if cur_raw is not None:
                    current = float(cur_raw)
                else:
                    current = prices.get(ticker)
                broker_pnl = p.get("pnl")
                if broker_pnl is not None:
                    pnl_usd = round(float(broker_pnl), 2)
                elif current is not None and entry:
                    pnl_usd = round((current - entry) * shares, 2)
                else:
                    pnl_usd = None
                bpct = p.get("pnl_pct")
                if bpct is not None:
                    pnl_pct = round(float(bpct), 2)
                elif current is not None and entry:
                    pnl_pct = round((current - entry) / entry * 100, 2)
                else:
                    pnl_pct = None
            else:
                current = p.get("current_price")
                if current is None:
                    current = prices.get(ticker)
                else:
                    current = float(current)
                pnl_pct = round((current - entry) / entry * 100, 2) if current is not None and entry else None
                pnl_usd = round((current - entry) * shares, 2) if current is not None and entry else None
            entry_date = p.get("entry_date") or p.get("entry_time") or ""
            try:
                held_hours = round((now - datetime.fromisoformat(str(entry_date).replace("Z", ""))).total_seconds() / 3600, 1) if entry_date else None
            except Exception:
                held_hours = None
            out.append({
                "ticker": ticker,
                "shares": shares,
                "entry_price": round(float(entry), 2) if entry else None,
                "current_price": round(current, 2) if current is not None else None,
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
        return {
            "positions": [{"error": str(e)}],
            "count": 1,
            "timestamp": ts,
            "positions_source": None,
            "positions_alpaca_error": None,
        }
    return {
        "positions": out,
        "count": len(out),
        "timestamp": ts,
        "positions_source": positions_source,
        "positions_alpaca_error": broker_err if positions_source == "positions_json" else None,
    }


def get_recent_orders():
    """Recent orders from Alpaca (paper vs live from ALPACA_BASE_URL)."""
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
        if not key or not secret:
            return {"orders": [{"error": "Alpaca keys not set"}], "count": 0, "timestamp": __import__("datetime").datetime.now().isoformat()}
        try:
            client = TradingClient(key, secret, paper=is_alpaca_paper())
        except ValueError:
            return {"orders": [{"error": "Invalid Alpaca keys"}], "count": 0, "timestamp": __import__("datetime").datetime.now().isoformat()}
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
