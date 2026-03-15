# Fortress Licensing and Tiers

## Overview

- **Master** – Vendor only (you). Never sold. Full capabilities; no customer tier is equivalent.
- **Starter** – Base customer tier: limited strategies, smaller universe, no backtest, no Fortress hedging.
- **Growth** – More strategies and universe than Starter.
- **Pro** – Core + extended strategies, backtest, Fortress hedging, Command Center.
- **Enterprise** – Highest customer tier; largest limits. Still a subset of Master (e.g. no experimental-only features unless you add them).

Deployments use the **same codebase**. The tier is determined by `data/license.json`. Customers receive a license file (and optionally a signed license) for their tier. All updates are compatible with every tier; tier upgrade = new license only (see [TIER_COMPATIBILITY.md](TIER_COMPATIBILITY.md)).

## License file (`data/license.json`)

- **tier** – `"master"` (vendor only) | `"starter"` | `"growth"` | `"pro"` | `"enterprise"`.
- **name** – Display name (e.g. "Pro Plan").
- **expiry** – Optional ISO date (e.g. `"2026-12-31"`). If past, the system behaves as Starter.
- **license_key** – Optional; if present with **signature**, the signature is verified.
- **signature** – Optional; Ed25519 (base64) or legacy HMAC-SHA256 hex. Prevents customers from editing `tier` to get higher features.

If the file is missing or invalid, the system defaults to **master** (full) so your own install is unchanged.

## Generating a signed license

The signing key is **randomly generated** (not hardcoded). One-time setup from project root:

```bash
python3 scripts/generate_license_keypair.py
```

This creates `data/.license_private.pem` (gitignored; back it up) and `config/license_public.pem` (committed; shipped so customers can verify). Then generate licenses:

```bash
python3 scripts/generate_license.py growth "Customer Name" 2026-12-31
python3 scripts/generate_license.py pro "Customer Name" 2026-12-31
```

Paste the output into `data/license.json` for that customer’s deployment. No secret in code; only the public key is shipped. Legacy: **LICENSE_SIGNING_SECRET** still works for HMAC-signed licenses.

## Customer settings (bounded risk)

Customers can tune risk within safe bounds via `data/customer_settings.json` (copy from `data/customer_settings.json.example`). Allowed keys and ranges:

| Key | Bounds | Description |
|-----|--------|-------------|
| position_size_min | 200–500 | Min $ per position |
| position_size_max | 500–2000 | Max $ per position |
| stop_loss_pct | -5 to -1 | Stop loss % |
| take_profit_pct | 3–15 | Take profit % |
| max_auto_trades_per_day | 2–12 | Daily trade cap |
| min_confidence_for_auto | 0.65–0.85 | Min confidence for auto-entry |
| daily_profit_target_dollars | 100–500 | Pause new trades above this daily profit |
| daily_profit_target_pct | 0.5–2.0 | Or above this % of equity |
| max_positions | 3–10 | Max open positions |

Values outside bounds are clamped. These settings only apply when the license tier allows customer settings (all current tiers do).

## Integrity (optional)

For customer builds you can generate an integrity manifest so the bot detects if core files were modified:

```bash
python scripts/build_manifest.py
```

This writes `data/integrity_manifest.json`. Ship this file with the customer build; do not put it in the public repo. If the license enables integrity checks, the bot can refuse to run or downgrade when a core file hash does not match.

## Command Center (customer builds)

The dashboard shows the current **License** tier in System Health (e.g. STARTER, PRO, MASTER). If the tier is Starter or the license is invalid, an **upgrade banner** appears: *"Upgrade to Pro for backtest, Fortress hedging, and more strategies."* so customers see what they’re missing without editing any code.

## Keeping master separate

- **Your repo** – Keep `data/license.json` out of version control (e.g. in `.gitignore`) or use `tier: "master"` and no signature so your copy always runs full features.
- **Customer builds** – Ship a copy of the codebase plus a generated `data/license.json` (and optionally `data/integrity_manifest.json`) for their tier. They do not get the signing secret or your master license.
