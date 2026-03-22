# Changelog

All notable changes to this project are documented here. Version in `VERSION` should match the latest release tag when you cut one.

## [1.0.4] — 2026-03-21

### Added

- **Docs:** `docs/LANE1_HARDENING_AND_ROUTINE.md` (B: reboot + deploy `--service`), `docs/STRIPE_CHECKOUT_AND_PORTAL.md` (C: Payment Links / portal).
- **`/proof`:** optional **Billing (Stripe)** links from `STRIPE_PAYMENT_LINK_*` and `STRIPE_CUSTOMER_PORTAL_URL` in `.env`.

## [1.0.3] — 2026-03-21

### Security

- Removed **`COMMANDS.txt`** from all Git history (it contained pasted API keys). File is now **`COMMANDS.txt` in `.gitignore`**. **Rotate** any OpenAI / xAI keys that were ever in that file or in old commits.

### Added

- **Stripe webhook → license file** — `POST /api/billing/stripe-webhook` (public; signature-verified), `utils/stripe_license_sync.py`, `stripe==11.4.1`, `docs/BILLING_STRIPE.md`. Maps Price IDs to Starter/Pro/Enterprise via env; writes `STRIPE_LICENSE_OUT_PATH` for `FORTRESS_LICENSE_PATH`.

## [1.0.2] — 2026-03-21

### Added

- **Universe cap by license** — `utils/license_gates.py`: `effective_max_universe_size()`, `apply_license_universe_cap()`; `agents/screener_agent.py` trims priority tiers; `agents/intraday_sniper.py` caps watchlist. Telemetry: `data/last_screening_meta.json` → `universe_license_cap`.
- **Lane 1 checklist** — `docs/LANE1_OPERATOR_CHECKLIST.md` (commit → deploy → Oracle verification).

## [1.0.1] — 2026-03-21

### Added

- **Tier enforcement** — `utils/license_gates.py` centralizes checks; Pro+ features are blocked for invalid/expired licenses and for **Starter** where defined in `config/pricing_gates.json`.
- **Dashboard:** `GET /api/backtest`, `GET /api/walk_forward` return **403** with JSON when gated; `get_trust_report()` returns gated stubs for walk-forward / backtest / research verdict; runbooks mark Fortress / walk-forward / audit export with `tier_gated` when applicable.
- **CLI:** `orchestrator.py fortress` exits **2** when gated; `scripts/export_audit_bundle.py` and `agents/walk_forward_validator.py` exit **2** when gated.

## [1.0.0] — 2026-03-18

### Added

- **Distribution model** — `docs/DISTRIBUTION.md` (three lanes: personal OCI+Mac, customer laptop, customer OCI).
- **Licensing foundation** — `config/license.py` (`get_plan()`), `config/tiers.py` (tier limits and gate helpers aligned with `config/pricing_gates.json`).
- **Version file** — `VERSION` for support and release discipline.

### Notes

- Personal / dev installs: set `FORTRESS_LICENSE_TIER=master` in `.env` for unrestricted gates (see `.env.example`).
- Customer installs: set tier from purchase (`starter` / `pro` / `enterprise`) or use `FORTRESS_LICENSE_PATH` pointing at `license.json`.
