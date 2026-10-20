#!/usr/bin/env bash
set -euo pipefail
# Network is needed only for public locked package installation. No application secrets.
uv sync --frozen --group cloud
npm ci --ignore-scripts
uv run python tools/sync_agents.py --check
uv run python -m warmstart.evals --validate-only
