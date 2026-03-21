# Policy profile templates

JSON files merged into `config/policy_profiles.json` by:

```bash
python3 scripts/install_policy_template.py <stem>
python3 scripts/install_policy_template.py tv_signal_sleeve --activate
```

| File | `profile_name` | Purpose |
|------|------------------|---------|
| `operator_conservative.json` | `operator_conservative` | Few names, small % per position |
| `operator_balanced_kit.json` | `balanced` | Restore default balanced numbers |
| `tv_signal_sleeve.json` | `tv_signal_sleeve` | Modest sleeve for external signals + webhook queue |

Each file may include `"set_active": true` to switch `active_profile` on install (use `--activate` to force).

A timestamped `.json.bak-*` copy is written before overwrite.
