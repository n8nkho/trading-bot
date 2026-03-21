import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def write_release_snapshot(tag: str = "manual") -> dict:
    out_dir = Path("data") / "release_snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = _git_commit()
    payload = {
        "timestamp": datetime.now().isoformat(),
        "tag": tag,
        "commit": commit,
    }
    sig = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    payload["signature_sha256"] = sig
    path = out_dir / f"release_snapshot_{ts}.json"
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    payload["path"] = str(path)
    return payload


if __name__ == "__main__":
    print(json.dumps(write_release_snapshot("manual"), indent=2))
