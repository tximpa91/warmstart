# Cloudflare deployment and operations

## Provision once, then deploy reviewed code

No Cloudflare resources or credentials are created by the local setup. The checked-in
Wrangler database ID is an intentionally invalid placeholder. Use a paid Workers account
for the selected generation model; verify current pricing and available models before use.

1. Authenticate Wrangler as the owner, or create a narrowly scoped deployment token.
2. Create separate D1 databases `warmstart-staging` and `warmstart-pilot`; record their IDs.
3. Provision a named AI Gateway in the same account for each environment, for example
   `warmstart-staging` and `warmstart-pilot`; record `AI_GATEWAY_ID`. Do not use `default`,
   which can auto-create a gateway, or enable a dynamic route/provider fallback.
4. Create Access applications and invite five testers. Protect all pilot routes and disable
   unprotected previews. Application JWT verification also protects the backend on direct URLs.
5. Record exact Access issuer and application audience; derive membership keys from the
   verified principal: SHA-256 of `user:<Access sub>` or `service:<common_name>`.
6. Configure memberships as a runtime secret. Each entry grants explicit demo profiles and
   an optional owner flag. Do not commit tester identities or membership maps.
7. Render the deployment config, migrate, seed original drafts and deploy. Initial paid
   inference and semantic serving stay disabled until owner-authorized live checks.

```bash
uv sync --frozen --group cloud
npm ci --ignore-scripts
uv run python tools/deploy_config.py --environment staging
uv run python tools/seed_sql.py
uv run --group cloud python tools/build_worker.py
npx --no-install wrangler d1 migrations apply DB --remote --config artifacts/wrangler.staging.json
npx --no-install wrangler d1 execute DB --remote --config artifacts/wrangler.staging.json --file artifacts/seed.sql
npx --no-install wrangler secret put MEMBERSHIPS_JSON --config artifacts/wrangler.staging.json
npx --no-install wrangler deploy --config artifacts/wrangler.staging.json
```

The renderer requires `CF_ACCOUNT_ID`, `D1_DATABASE_ID`, `ACCESS_ISSUER`, `ACCESS_AUDIENCE`
and `AI_GATEWAY_ID` from the operator environment and writes an ignored config.
`AI_GATEWAY_LOG_MODE` defaults to `metadata`; `off` is the only alternative. These Gateway
settings are non-secret protected environment variables. The membership secret must
exist before invited access works. A service token for CI is a distinct, non-owner principal;
grant it only the profile needed for smoke tests. Its client credentials stay in protected
environment secrets. Missing/invalid JWT or membership fails closed.

## CI/CD

Public PRs run lint, strict domain typing, tests, dataset/split/fixture checks, full public
regression, ordered traffic replay, generated-agent drift checks, credential/path scans and
Worker build. There are no deployment or inference credentials in this workflow. Actions
are pinned by commit and token permissions default to read-only. The required aggregate job
fails on failures and unexpected skips.

The manual deployment workflow accepts only the exact current reviewed `main` revision,
repeats offline checks and rebuilds from source. It never downloads untrusted PR artifacts.
Deployment credentials exist only in the deployment step. Runtime memberships are provisioned
separately. Staging smoke exercises authenticated D1/coordinator admission without inference.

Before enabling workflows, configure GitHub outside the repository:

- Protect `main` and require `required` plus owner review; restrict workflow and instruction changes.
- Create protected `staging` and `pilot` environments with Luis as required reviewer; prevent
  self-review where available. Configure environment variables and scoped secrets.
- Set variables `CF_ACCOUNT_ID`, `D1_DATABASE_ID`, `ACCESS_ISSUER`, `ACCESS_AUDIENCE`, `PILOT_URL`,
  `AI_GATEWAY_ID`, and optionally `AI_GATEWAY_LOG_MODE` (`metadata` by default).
- Set secrets `CLOUDFLARE_API_TOKEN`, `ACCESS_CLIENT_ID`, `ACCESS_CLIENT_SECRET`.
- For pilot promotion, supply `RELEASE_EVIDENCE_JSON` from the external release operator.
  `tools/release_gate.py` checks source-bound owner attestations, not their factual truth.

The checked-in workflow deliberately deploys with paid inference off. For a bounded live
assessment, the owner changes the rendered staging configuration to paid inference on,
deploys that reviewed config, verifies the budget state, then explicitly runs `live_smoke.py
--allow-paid`. Preserve the exact deployed configuration digest with the assessment. This
manual step does not grant permission to turn on semantic serving. Pilot release remains
subject to the human/live/private gates and is not automated from an agent GO.

## Gateway settings and live evidence

Keep the existing Workers AI billing path. This integration does not purchase credits,
enroll Unified Billing, create a gateway or choose another provider. Check the dashboard's
Workers AI billing setting before live calls; do not enable credit purchases to follow a
code example. Gateway/log charges are account-dependent; verify current
[Gateway pricing](https://developers.cloudflare.com/ai-gateway/reference/pricing/) and
[logging eligibility/retention](https://developers.cloudflare.com/ai-gateway/observability/logging/)
within the existing CHF envelope rather than assume all observation is free.

Operator configuration:

- Disable Gateway response caching and automatic retries at the gateway level as defense
  in depth; do not configure model fallbacks or additional evaluation/guardrail calls.
- Requests independently send `skipCache: true`, `retries.maxAttempts: 1` and
  `cf-aig-max-attempts: 1`. Model settings, application retry limits and reservations remain
  unchanged. Request headers take precedence over ordinary gateway defaults.
- Default metadata-only requests use `collectLog: true` and
  `cf-aig-collect-log-payload: false`. Do not enable raw payload collection or add user,
  profile, identity, question or answer metadata. `off` sets `collectLog: false`, suppressing
  all Gateway logs. Application aggregate events and the durable ledger remain available.
- Record the rendered Wrangler file's SHA-256 and `GatewaySettings.signature()` with the
  source/configuration digest. Transport is intentionally excluded from answer-cache keys;
  a missing/disabled gateway still permits valid exact hits while new paid calls fail closed.

Before inviting testers, use original synthetic inputs in an owner-authorized staging run:

1. Verify embedding and generation route through the intended account and gateway, retaining
   the fixed model IDs. No request may silently use direct inference or another provider.
2. Inspect stored Gateway entries: token/model/status/cost/duration metadata is present,
   request and response bodies are absent, and no custom identity metadata is stored.
3. Verify response-cache bypass on repeated model calls. Compare Warmstart exact hits
   separately; those should produce no inference/Gateway call.
4. Exercise a controlled transient failure and verify one provider attempt per binding call,
   at most two generation calls overall, and a reservation for every attempted paid call.
   Keep the full reservation for uncertain outcomes. Avoid an unbounded paid failure test.
5. Verify `x-session-affinity` is preserved and cached input tokens remain measurable without
   confusing prefix savings with response reuse. Reconcile usage against billed inference.
6. Disable paid inference/remove the Gateway ID and verify existing private exact hits still
   work; new paid calls must fail. Record hosted timeout/error behavior separately.

Current offline tests validate options and retry/reservation behavior. Pinned workerd type
definitions support `gateway.retries` and `extraHeaders`; current upstream implementation
forwards headers, but matching-tag implementation source was not retrieved. No local build
or mock proves the hosted service honors those controls. Routing, payload suppression,
single-attempt behavior, cost and latency remain unverified until this live checklist passes.
[Binding contract](https://developers.cloudflare.com/ai-gateway/usage/worker-binding-methods/),
[header hierarchy](https://developers.cloudflare.com/ai-gateway/glossary/),
[request handling](https://developers.cloudflare.com/ai-gateway/configuration/request-handling/).

Mobile impact: this is a backend transport change. The response API/payload and bounded
application timeout/retry behavior are unchanged; real network latency remains a hosted
measurement. No UI, responsive, browser or iPhone Duo verification is asserted.
Missing/invalid Gateway configuration returns a controlled `503 service_unavailable` before
reservation or provider work; `429 budget_exhausted` remains reserved for paid-work controls.

## Budget and limits

| Monthly allocation | CHF |
|---|---:|
| Workers, D1, coordination, minimal logging | 8 |
| Development/live evaluation | 15 |
| Invited pilot inference | 15 |
| Currency, tax and unexpected use | 12 |
| Total | 50 |

These are allocations, not billing guarantees. The initial coordinator caps modeled inference
at USD 12 per calendar month per deployed environment. Staging and pilot ledgers are separate;
include both in the CHF envelope. Default quotas are 50 questions/tester/day, 200 globally/day,
five concurrent generations. Calls reserve USD 0.0001 for embedding or USD 0.01 for generation
before each attempt. Bounded prompts/outputs keep these above modeled usage at reviewed prices.
Timeouts and unknown outcomes retain the full reservation. Model/pricing changes require review.

When paid inference is disabled or its budget is exhausted, valid exact hits can still return.
Semantic lookup requires its own embedding reservation. A provider failure can bypass semantic
search but cannot bypass generation authorization. Infrastructure/account spend is not governed
by this application ledger; set account alerts and reconcile provider billing weekly.

## Pilot release and rollback

Required evidence: fresh checkout, adapter contracts and hosted smoke, Access/membership
isolation, policy activation, durable budgets/restart recovery, current reviewer/QA/CI, human
quality assessment, public regression and exercised rollback. Private assessment remains
outside coding environments. Semantic serving requires a separate sufficient-evidence decision.

Keep separate configuration switches for exact caching, semantic mode and paid inference.
For incident response, first disable paid inference and semantic serving. Roll back to the
previous compatible Worker and reactivate the previous immutable policy edition using the
owner endpoint. Preserve the Durable Object name/storage and reservation history. Use additive
migrations; an incompatible schema change needs a forward fix rather than blind binary rollback.

Before real customers, establish representative workloads, retention/privacy decisions,
operations ownership, backup/recovery drills and stronger availability/load evidence. The
invited synthetic pilot is deliberately smaller than that readiness claim.

The public demo deploys separately with `wrangler.demo.toml`: static assets only, no AI bindings.
Reference: [Workers Access configuration](https://developers.cloudflare.com/workers/configuration/cloudflare-access/).
