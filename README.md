# KHF Zero-Cost Trading Bot

Fundamental value strategy (DeepSeek LLM + Alpaca).

**Operator default (Oracle + Mac mirror):** the **personal bot and all cron jobs run on Oracle** (`~/trading-bot` on the VM). **Default sync is Oracle → Mac** (`./scripts/sync_pull_from_oracle.sh`) so your Mac stays a Cursor/editor mirror — see **`docs/SYNC_ORACLE_SOURCE_OF_TRUTH.md`**.

**Risk roadmap + ship workflow (test → paper trade/cancel → commit → deploy → sync Mac):** **`docs/STRATEGY_ROADMAP_TICKETS.md`**.

## Fortress install (VM / laptop)

```bash
chmod +x scripts/*.sh
./scripts/install.sh
./scripts/verify_install.sh
./scripts/restart_dashboard.sh
```

**systemd (Linux server):** `sudo ./scripts/install_systemd.sh --now` — see `deploy/systemd/README.md` and `docs/INSTALL.md`.

## Quick Start

Configure DeepSeek via `DEEPSEEK_API_KEY` and `config/fortress_runtime.yaml` (`llm.provider: deepseek`).

