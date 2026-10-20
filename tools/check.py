"""Run the credential-free acceptance gates used by local development and PR CI."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = (
    ("ruff", "check", "."),
    ("mypy", "src/warmstart"),
    (sys.executable, "tools/sync_agents.py", "--check"),
    ("pytest", "-q"),
    (
        sys.executable,
        "-m",
        "warmstart.evals",
        "--suite",
        "regression",
        "--mode",
        "replay",
        "--output",
        "artifacts/regression.json",
    ),
    (sys.executable, "tools/public_safety.py"),
)


if __name__ == "__main__":
    os.chdir(ROOT)
    for command in COMMANDS:
        print("RUN", " ".join(command), flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    print("Offline acceptance gates passed. Live/pilot readiness is a separate gate.")
