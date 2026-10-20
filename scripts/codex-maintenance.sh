#!/usr/bin/env bash
set -euo pipefail
uv sync --frozen --group cloud
uv run python tools/sync_agents.py --check
