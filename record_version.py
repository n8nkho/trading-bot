import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    repo_root = Path(__file__).resolve().parent
    data_dir = repo_root / "data"
    data_dir.mkdir(exist_ok=True)

    # When deploying, `.git/` may not be present on the server.
    # Prefer explicit env vars if provided by deploy scripts.
    import os
    env_commit = os.getenv("DEPLOY_COMMIT")
    env_dirty = os.getenv("DEPLOY_DIRTY")

    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root).decode().strip()
    except Exception:
        commit = None

    if env_commit:
        commit = env_commit.strip()

    try:
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root).decode().strip()
    except Exception:
        status = ""

    dirty = bool(status)
    if env_dirty is not None:
        dirty = env_dirty.strip().lower() in {"1", "true", "yes", "y"}

    version = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "dirty": dirty,
        "git_status_porcelain": status,
    }

    (data_dir / "version.json").write_text(json.dumps(version, indent=2), encoding="utf-8")
    print("[version] wrote data/version.json")


if __name__ == "__main__":
    main()

