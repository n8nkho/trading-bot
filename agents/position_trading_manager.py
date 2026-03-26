from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class PositionTradingManager:
    sleeve_key = "position_trading"

    def evaluate(
        self,
        candidates: list[dict[str, Any]],
        *,
        sleeve_cfg: dict[str, Any],
        regime: str,
        vix: float | None,
        portfolio_value: float,
    ) -> dict[str, Any]:
        selected: list[dict[str, Any]] = []
        for c in candidates:
            conf = float((c.get("analysis") or {}).get("confidence") or 0.0)
            vol = float(c.get("volume_ratio") or 0.0)
            # Longer-horizon sleeve prefers cleaner quality setups.
            if conf >= 0.75 and vol >= 1.0:
                selected.append(c)
        cap = float(sleeve_cfg.get("capital_allocation_pct", 0.0)) / 100.0 * float(portfolio_value)
        return {
            "sleeve": self.sleeve_key,
            "active": bool(sleeve_cfg.get("enabled", True)),
            "regime": regime,
            "vix": vix,
            "target_capital_usd": round(cap, 2),
            "selected_candidates": selected[:6],
            "selected_count": len(selected[:6]),
            "holding_period": sleeve_cfg.get("holding_period", "2-8w"),
        }

    def record_outcome(self, result: dict[str, Any], *, data_dir: Path) -> None:
        out = data_dir / "sleeve_metrics_position_trading.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        row = {"timestamp": datetime.now().isoformat(), **result}
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")

