"""Install reviewed cross-target wheels and run Cloudflare's actual Worker bundler.

Avoids downloading a separate standalone WASM interpreter just to unpack prebuilt wheels.
Runtime compatibility is verified separately by the real workerd smoke.
"""

import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    config = tomllib.loads((ROOT / "wrangler.toml").read_text())
    if config["compatibility_date"] != "2026-09-01":
        raise SystemExit("Review Python ABI and wheel locks before changing compatibility date")
    lock = tomllib.loads((ROOT / "pylock.toml").read_text())
    sdk = next(item for item in lock["packages"] if item["name"] == "workers-runtime-sdk")
    if sdk["version"] != "1.9.4":
        raise SystemExit("Worker SDK differs from the reviewed build configuration")
    os.environ.setdefault("WRANGLER_SEND_METRICS", "false")
    run(
        [
            "uv",
            "pip",
            "sync",
            "pylock.toml",
            "--target",
            "python_modules",
            "--python-version",
            "3.13",
            "--python-platform",
            "wasm32-pyodide2025",
            "--no-build",
        ]
    )
    run(
        [
            "npx",
            "--no-install",
            "wrangler",
            "deploy",
            "--dry-run",
            "--outdir",
            "artifacts/worker-build",
        ]
    )
