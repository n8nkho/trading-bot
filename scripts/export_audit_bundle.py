#!/usr/bin/env python3
"""
Build a ZIP audit bundle: trust ledger, operational runs, operator halt file + manifest (SHA-256).

Optional upload: if FORTRESS_AUDIT_S3_BUCKET and AWS credentials are configured and boto3 is
installed, set FORTRESS_AUDIT_S3_PREFIX (e.g. audit-bundles/) to upload the zip.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    candidates = [
        DATA / "trust_ledger.jsonl",
        DATA / "operational_runs.jsonl",
        DATA / "operator_trading_halt.json",
        DATA / "backtest_snapshot.json",
    ]
    manifest = {
        "created_at": datetime.now().isoformat(),
        "root": str(ROOT),
        "files": [],
    }
    for p in candidates:
        if p.exists():
            manifest["files"].append({
                "path": str(p.relative_to(ROOT)),
                "sha256": _sha256_file(p),
                "size": p.stat().st_size,
            })

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_zip = DATA / f"audit_export_{stamp}.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for p in candidates:
            if p.exists():
                z.write(p, arcname=str(p.relative_to(ROOT)))

    print(str(out_zip))

    bucket = (os.environ.get("FORTRESS_AUDIT_S3_BUCKET") or "").strip()
    prefix = (os.environ.get("FORTRESS_AUDIT_S3_PREFIX") or "audit-bundles/").strip()
    if bucket:
        try:
            import boto3  # type: ignore

            key = prefix.rstrip("/") + "/" + out_zip.name
            boto3.client("s3").upload_file(str(out_zip), bucket, key)
            print(f"[uploaded] s3://{bucket}/{key}")
        except Exception as e:
            print(f"[warn] S3 upload skipped/failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
