# Codex cloud environment

The repository is designed for a fresh cloud checkout with no application secrets. It does
not automatically create or publish a Codex cloud environment from a local code change.

1. Publish this reviewed application tree to a dedicated GitHub repository. Connect that
   repository in Codex and create its cloud environment.
2. Use Python 3.13+, Node 22+ and uv 0.12.3. Setup command:
   `bash scripts/codex-setup.sh`; maintenance: `bash scripts/codex-maintenance.sh`.
3. Permit setup downloads from the package/runtime registries required by uv and Cloudflare.
   Application tasks and golden regression run offline. Never add production credentials,
   tester memberships or private holdout cases to this environment.
4. In a fresh task, run `uv run python tools/check.py`. Verify the four native Codex agents
   are discoverable and explicitly dispatch a bounded developer/reviewer/QA task. If the
   environment lacks native delegation, use separate explicit role stages and report it.
5. Start the local API for API checks when useful. Perform browser visual QA locally when
   cloud browser tooling is unavailable. Do not claim a hosted browser check from a CLI test.
6. Keep deployment and paid inference in protected CI/owner environments, outside coding tasks.

Cursor and Claude Code use the same locked checkout and offline commands. Their project
adapters are generated from the shared roles; purchasing all three tools is unnecessary.

Setup scripts and local offline commands can be tested here. Actual Codex cloud account
connection, environment publication and a fresh remote task require account-level setup.
Reference: [Codex cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).
