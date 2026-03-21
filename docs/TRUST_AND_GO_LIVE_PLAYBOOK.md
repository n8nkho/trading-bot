# Trust & Go-Live Playbook

1. **Proof Center** — Open `/proof` and verify JSON endpoints respond (`/api/trust_report`, `/api/safety_status`).
2. **Policy** — Set `active_profile` in `config/policy_profiles.json` or override with `TRADING_POLICY_PROFILE`.
3. **Shadow mode** — Enable `guardrails.shadow_mode_enabled` and set `shadow_candidate_profile` to log “what-if” limits in the trust ledger without switching live risk.
4. **Drift** — Run `python3 agents/drift_detector.py` daily; if `drift_alert` and `auto_rollback_on_drift_alert` is true, the system may force `rollback_target_profile` for `rollback_duration_hours`.
5. **Clear rollback** — After human review: `POST /api/policy/clear_rollback` or runbook Python one-liner in Command Center.
6. **Walk-forward** — Run `python3 agents/walk_forward_validator.py` weekly; check `data/walk_forward_report.json`.
7. **Release marker** — After deploy: `python3 utils/release_snapshot.py`.
8. **Paper first** — Keep Alpaca paper until KPIs meet your bar; no feature removes market risk.
