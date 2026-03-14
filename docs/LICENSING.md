# Fortress Licensing and Tiers

## Overview

- **Master** – Internal/full version; no restrictions. Used by you for development and full feature set.
- **Starter** – Limited strategies, smaller universe, no backtest, no Fortress hedging. Suitable for low-cost entry.
- **Pro** – Core + extended strategies, backtest, Fortress hedging, Command Center.
- **Enterprise** – Full feature set (all strategies, large universe).

Deployments use the **same codebase**. The tier is determined by `data/license.json`. Customers receive a license file (and optionally a signed license) for their tier.

## License file (`data/license.json`)

- **tier** – `"master"` | `"starter"` | `"pro"` | `"enterprise"`.
- **name** – Display name (e.g. "Pro Plan").
- **expiry** – Optional ISO date (e.g. `"2026-12-31"`). If past, the system behaves as Starter.
- **license_key** – Optional; if present with **signature**, the signature is verified.
- **signature** – Optional; HMAC-SHA256 of `tier|expiry|customer_id` with a server secret. Prevents customers from editing `tier` to get higher features.

If the file is missing or invalid, the system defaults to **master** (full) so your own install is unchanged.

## Generating a signed license

From project root:

```bash
python scripts/generate_license.py pro "Customer Name" 2026-12-31
```

Paste the output into `data/license.json` for that customer’s deployment. **Keep the signing secret secure** (in production use an env var or secret store; update `config/license.py` and `scripts/generate_license.py` to read it).

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
