# Evaluation and golden-set protocol

## Four assets, four responsibilities

1. Policy truth: original fictional facts for each shop/country/tier/edition.
2. Reusable answers: separately reviewed text, sources, scope, condition, vector provenance,
   review time and expiry. A correct golden question does not automatically approve a seed.
3. Golden questions: expected outcome, reuse permission, approved seeds, required facts,
   forbidden claims, scenario/version setup, review status and family split.
4. Traffic order: declared request sequence and warmup procedure, used for efficiency/recovery.

Current `data/golden.public.jsonl` has 100 agent-authored drafts: 50 development and 50
regression cases. No cases or seeds are human-approved. The intended final split is 300
public development, 300 public regression and 400 private release cases. Category targets:
500 paraphrases, 200 near negatives, 100 context boundaries, 100 time/version changes and
100 unsupported/personalized/ambiguous/adversarial cases. These are targets, not completed counts.

Keep template families within a split. Validator checks IDs, family/question leakage,
known profiles, answer labels and scoped seed references. Similarity alone cannot establish
that two templates belong to independent families; a human checks the split.

## Human review

Review each policy first, then reusable answers and question labels against that policy.
Check amounts, product condition, tier, country, edition, negation and answerability.
Quarantine disagreements; do not assign a confident expected answer to an ambiguous question.
Record reviewer, date and rationale outside public identities as appropriate. Only the human
reviewer changes a draft's review status. Agents must not perform this attestation.

Do not manufacture 1,000 reviewed examples by multiplying templates or changing a label
until tests pass. Expand families deliberately, including unsupported shipping destinations,
express service, refurbished products, contradictory conditions and authorization boundaries.
Runtime code never receives expected labels. Allowed source IDs are checked for accepted hits.

## Offline commands

```bash
uv run python -m warmstart.evals --validate-only
uv run python -m warmstart.evals --suite development --output artifacts/development.json
uv run python -m warmstart.evals --suite regression --output artifacts/regression.json
uv run python -m warmstart.evals --suite regression --requests 1000 --output artifacts/traffic.json
# Deliberately fails until the selected labels are human-reviewed:
uv run python -m warmstart.evals --suite regression --require-human-reviewed
```

Compare no response cache, exact, exact plus semantic, and a policy-template baseline with
the same request order and per-condition reset. The optional traffic mode cyclically repeats
the selected public split; report unique cases separately from requests. Before a case marked
as a policy transition, warm the prior edition identically across applicable conditions and
report those calls separately. Report exact/semantic/generated latency separately, and do
not label local fixture timings as hosted latency. The template baseline is intentionally
strong for this tiny fact corpus; a model is not automatically the better solution.

The fixture fingerprint includes configuration, full policy/seed records, public dataset,
guard and fixture-inference source. A deliberate change requires a reviewed manifest update;
CI never rewrites expected answers. `data/fixtures.manifest.json` records the current payload.
The CLI never updates this manifest automatically.

## Live and private assessment

The owner runs a bounded hosted smoke with a narrowly scoped Access service token:

```bash
uv run python tools/live_smoke.py --url https://YOUR-APP-ORIGIN
# Only after explicitly enabling paid inference and verifying the durable budget:
uv run python tools/live_smoke.py --url https://YOUR-APP-ORIGIN --allow-paid
```

The paid smoke makes at most three authenticated answer requests; the repeated shipping
question should produce an exact hit. It does not judge prose or replace the release set.
Record fresh live outputs for rubric assessment separately under owner control. Evaluate
supported answers against the reviewed facts and forbidden claims; calibrate any LLM judge
with human judgments. Validate references and factual content separately.

Keep private cases entirely outside the repository, coding environments, logs and PR artifacts.
The release operator uses a separate owner-controlled environment, freezes code/config and
publishes only dataset checksum, counts, aggregate metrics and evidence digest. No private
holdout has been generated or accessed by this implementation. Cases used to guide a fix
are no longer unseen; retire or reclassify them and obtain fresh release evidence.

## Promotion gates

| Gate | Requirement |
|---|---|
| Isolation | Zero observed cross-context disclosure; adversarial authorization tests pass |
| Freshness | Admissions after activation use the new immutable edition |
| Public cache correctness | Zero incorrect accepted hits in public regression |
| Human quality | At least 95% supported-answer quality against the reviewed rubric |
| Semantic release | Zero observed incorrect semantic hits; accepted-hit count and uncertainty reported |
| Recovery | Timeout, cancellation, restart, concurrency, quota and budget checks pass |
| Efficiency | Target 25% lower model cost on declared traffic, with cold/warm costs separated |

A safe miss lowers coverage/savings but is not automatically an answer-correctness failure.
Semantic error denominator is accepted semantic hits. Zero errors in a small synthetic set
does not establish a production error rate below 1%. An illustrative one-sided 95% zero-error
bound is `1 - 0.05**(1/n)` under IID sampling; repeated templates violate that assumption.
Insufficient evidence keeps semantic serving in shadow mode.

Track provider input/output/cached-input tokens, confirmed/estimated cost, outstanding ledger
reservations, hit coverage and p50/p95 by path. Provider prefix savings and avoided generation
are different effects. Reconcile actual billing weekly. Recorded replay provides engineering
regression, never fresh model quality or actual provider savings.
