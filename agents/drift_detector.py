"""
Drift detector for strategy stability monitoring.
Compares recent realized P&L average against prior window.
"""

import json
from datetime import datetime
from pathlib import Path


LEDGER = Path("data") / "pnl_ledger.jsonl"
OUT = Path("data") / "drift_report.json"


def _load_pnls() -> list[float]:
    vals = []
    if not LEDGER.exists():
        return vals
    with open(LEDGER, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                vals.append(float(row.get("pnl") or 0.0))
            except Exception:
                continue
    return vals


def analyze_drift() -> dict:
    pnls = _load_pnls()
    recent = pnls[-20:]
    prior = pnls[-40:-20]
    recent_avg = sum(recent) / len(recent) if recent else 0.0
    prior_avg = sum(prior) / len(prior) if prior else 0.0

    drift_ratio = None
    if prior_avg != 0:
        drift_ratio = (recent_avg - prior_avg) / abs(prior_avg)

    drift_alert = False
    reason = "insufficient_history"
    if len(recent) >= 10 and len(prior) >= 10:
        reason = "stable"
        if drift_ratio is not None and drift_ratio < -0.35:
            drift_alert = True
            reason = "recent_performance_deterioration"

    report = {
        "timestamp": datetime.now().isoformat(),
        "recent_trades": len(recent),
        "prior_trades": len(prior),
        "recent_avg_pnl": round(recent_avg, 4),
        "prior_avg_pnl": round(prior_avg, 4),
        "drift_ratio": round(drift_ratio, 4) if drift_ratio is not None else None,
        "drift_alert": drift_alert,
        "reason": reason,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(report, f, indent=2)

    try:
        from utils.policy_guardrails import maybe_trigger_rollback_on_drift

        maybe_trigger_rollback_on_drift(report)
    except Exception:
        pass

    return report


if __name__ == "__main__":
    print(json.dumps(analyze_drift(), indent=2))
