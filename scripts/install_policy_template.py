#!/usr/bin/env python3
"""
Merge a policy profile template into config/policy_profiles.json.

Usage:
  python3 scripts/install_policy_template.py operator_conservative
  python3 scripts/install_policy_template.py tv_signal_sleeve --activate
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "policy_profiles.json"
TEMPLATES = ROOT / "config" / "policy_templates"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "name",
        help="Template stem (e.g. operator_conservative) or path to JSON file",
    )
    p.add_argument(
        "--activate",
        action="store_true",
        help="Set active_profile to the template's profile_name after merge",
    )
    args = p.parse_args()

    raw = args.name.strip()
    if raw.endswith(".json"):
        path = Path(raw)
    else:
        path = TEMPLATES / f"{raw}.json"
    if not path.exists():
        print(f"[error] template not found: {path}", file=sys.stderr)
        return 1

    tpl = json.loads(path.read_text(encoding="utf-8"))
    pname = str(tpl.get("profile_name") or "").strip().lower()
    if not pname:
        print("[error] template missing profile_name", file=sys.stderr)
        return 1

    if POLICY.exists():
        payload = json.loads(POLICY.read_text(encoding="utf-8"))
    else:
        payload = {"active_profile": "balanced", "guardrails": {}, "profiles": {}}

    if not isinstance(payload.get("profiles"), dict):
        payload["profiles"] = {}

    profile_body = {
        "description": tpl.get("description", ""),
        "risk": tpl.get("risk") or {},
        "screening": tpl.get("screening") or {},
        "execution": tpl.get("execution") or {},
    }
    payload["profiles"][pname] = profile_body

    if args.activate or tpl.get("set_active") is True:
        payload["active_profile"] = pname

    bak = POLICY.with_suffix(".json.bak-" + datetime.now().strftime("%Y%m%d%H%M%S"))
    if POLICY.exists():
        shutil.copy2(POLICY, bak)
        print(f"[ok] backup {bak}")

    POLICY.parent.mkdir(parents=True, exist_ok=True)
    POLICY.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] merged profile {pname!r} into {POLICY}")
    print(f"[ok] active_profile = {payload.get('active_profile')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
