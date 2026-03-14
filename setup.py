#!/usr/bin/env python3
"""
Fortress one-time setup (Windows-friendly).
Run: python setup.py
Then run the dashboard and open the browser: python dashboard/command_center.py
Open http://localhost:8083 and complete the setup wizard.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

def main():
    print("=== Fortress Setup ===\n")
    # 1. Venv
    if not (ROOT / "venv").exists():
        print("Creating venv...")
        subprocess.check_call([sys.executable, "-m", "venv", "venv"])
    # Use venv python if present
    py = ROOT / "venv" / "Scripts" / "python.exe" if os.name == "nt" else ROOT / "venv" / "bin" / "python"
    if not py.exists():
        py = sys.executable
    # 2. .env
    if not (ROOT / ".env").exists() and (ROOT / ".env.example").exists():
        (ROOT / ".env").write_text((ROOT / ".env.example").read_text())
        print("Created .env from .env.example")
    # 3. data/config
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "config").mkdir(exist_ok=True)
    watchlist = ROOT / "config" / "watchlist.json"
    if not watchlist.exists():
        watchlist.write_text('{"quality_stocks":[{"ticker":"AAPL","sector":"Technology","name":"Apple"}]}')
        print("Created config/watchlist.json")
    # 4. Dependencies
    if (ROOT / "requirements.txt").exists():
        print("Installing dependencies...")
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"])
    print("\nSetup complete.")
    print("\nNEXT: Start the dashboard and finish in your browser:")
    print("  python dashboard/command_center.py")
    print("  Then open: http://localhost:8083")
    print("  See docs/CUSTOMER_INSTALL.md for details.\n")

if __name__ == "__main__":
    main()
