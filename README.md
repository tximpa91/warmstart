# Warmstart

**An evaluation-first AI support-answer cache, using original fictional retailer data.**

**Work in progress: local engineering demo; not approved for pilot or release.**
Two admission correctness findings remain unresolved after the automatic repair limit.
Read [Known limitations](docs/KNOWN_LIMITATIONS.md) before using or deploying it.
Publishing this code does not approve deployment; paid inference and shared semantic
serving remain disabled in the default deployment configuration.

Warmstart asks when an answer can be reused safely. Exact answers stay private to an
authenticated tester. Shared semantic answers require compatible context, approved
provenance, a matching condition, similarity and a valid review expiry. A policy activation
changes the version for new admissions; requests already admitted retain their version.

## Run locally

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/) and Git. No credentials are needed.

```bash
uv sync --frozen
uv run uvicorn warmstart.api:app --host 127.0.0.1 --port 8000 --reload
```

Open <http://127.0.0.1:8000/console/> or <http://127.0.0.1:8000/docs>.
The local API accepts a fixed demo owner identity on loopback only; request headers cannot
choose another identity. Do not expose this local server as a public deployment.

```bash
curl http://127.0.0.1:8000/v1/answer \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the standard shipping cost?","profile":"store_a_ch_standard"}'
```

Repeat the request for an exact hit. The response contains the answer, source IDs, admitted
policy edition, cache status and request ID. Owner-only activation:

```bash
curl http://127.0.0.1:8000/v1/admin/invalidate \
  -H 'Content-Type: application/json' -d '{"policy_version":"v2"}'
```

Local state persists in the ignored `artifacts/warmstart.sqlite3`. Use a new
`WARMSTART_LOCAL_DB` path for a clean experiment; never reset a pilot spending ledger.

## What exists, and what remains gated

| Evidence | Current implementation |
|---|---|
| Local runtime | FastAPI, SQLite, exact cache, condition guards, semantic shadow/fixture serving |
| Offline data | 16 policy contexts, 80 fixture seed answers, 100 draft golden cases |
| Human review | **0 human-reviewed labels or approved answers** |
| Regression | Development/regression splits, fixture fingerprints, four comparison conditions |
| Traffic | Optional 1,000-request ordered replay; repeated cases are explicitly identified |
| Cloud | Python Worker, D1, Durable Object ledger, named AI Gateway and Workers AI; gated deployment workflow |
| Agent workflow | Canonical roles, native adapters, evidence state machine, two repair cycles |
| Mobile acceptance | Shared task/review policy; responsive WebKit CI and Duo device verification remain follow-up gates |
| Public demo | Static recordings only; no API or inference binding |
| Hosted pilot / Codex cloud | Account provisioning, authentication and fresh hosted verification still required |
| Release benchmark | Planned 600 public reviewed cases + 400 owner-held private cases; not completed |

The offline model is a deterministic policy fixture and its vectors are feature hashes.
They demonstrate application behavior, **not live model accuracy, cost savings or hosted
latency**. The deployed path rejects fixture seeds and starts with paid inference and
semantic serving disabled. Reference validation cannot establish free-text factuality.
Deployed embeddings and generation require a named AI Gateway, bypass its response cache,
request metadata-only logs without bodies, and disable Gateway retries. Hosted verification
of these controls remains a pilot gate; local development stays offline.

## Verify

```bash
uv run python tools/check.py
uv run python -m warmstart.evals --suite development --mode replay
uv run python -m warmstart.evals --suite regression --requests 1000 --output artifacts/traffic.json
# Requires Node 22+ and the additional locked Cloudflare tooling:
uv sync --frozen --group cloud
npm ci --ignore-scripts
uv run --group cloud python tools/build_worker.py
uv run --group cloud python tools/worker_smoke.py
```

The Cloudflare build installs public runtime packages; it requires network access but no
account credentials. `uv.lock` pins CPython dependencies; `pylock.toml` pins the Worker
target. The build unpacks hash-locked cross-target wheels and invokes pinned Wrangler;
the smoke executes real local workerd, ASGI, D1 and coordinator RPC. `pywrangler dev` remains
an optional SDK workflow, requiring its standalone Pyodide interpreter download.
CI never runs paid inference for public PRs. Require the aggregate
`required` job in GitHub branch protection; repository files alone cannot enable protections.

## Read the design

- [Architecture and both Mermaid diagrams](docs/ARCHITECTURE.md)
- [Known limitations and current approval boundaries](docs/KNOWN_LIMITATIONS.md)
- [Evaluation protocol and golden-label review](docs/EVALUATION.md)
- [Cloudflare deployment, budget and rollback](docs/DEPLOYMENT.md)
- [Codex / Cursor / Claude agents and repair workflow](docs/AGENT_WORKFLOW.md)
- [Mobile acceptance and iPhone Duo verification boundaries](docs/MOBILE_QA.md)
- [Codex cloud setup](docs/CODEX_CLOUD.md)
- [Delivery and human readiness checklist](docs/ROADMAP.md)
- [Public repository boundaries](SECURITY.md)

This repository contains original code and synthetic examples. No real retailer policy,
customer record or claim is represented. Infrastructure is designed around a CHF 50/month
allocation; provider billing, taxes, currencies and coding-assistant subscriptions remain
separate. A configured spending ledger limits application inference, not every account cost.
