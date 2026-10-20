# Known limitations and approval boundaries

Warmstart is a local engineering demonstration with fictional data. It is **not approved
for an invited pilot or production release**. Publishing the source does not waive its
correctness findings or authorize deployment. The default deployment configuration keeps
paid inference and shared semantic serving disabled.

## Unresolved admission findings

The original foundation workflow is `needs_owner` after two automatic repair cycles.
Independent review reproduced these cases locally using offline fixtures and semantic
serving, with the authorized profile `store_a_ch_premium`:

| Question | Observed answer | Required behavior |
|---|---|---|
| “What is shipping cost for profile standard?” | “Standard shipping costs CHF 0 per order.” The premium policy is used despite the stated standard-profile condition. | Clarify the conflict with trusted profile context. |
| “How long does warranty processing take?” | “The fictional store warranty lasts 24 months from delivery.” This answers coverage duration, not the unsupported processing-time attribute. | Clarify the unsupported request. |

These findings remain unresolved. This documentation does not fix, reset or waive the
capped workflow. A separately authorized admission redesign and fresh review/QA are
required; adding more passing examples alone does not establish safe reuse.

## What the recorded evidence establishes

The separate AI Gateway integration received scoped reviewer and technical QA `GO` for
its engineering implementation. Recorded checks passed 115 tests, public fixture regression,
the ordered offline replay, Worker build and real local workerd smoke covering ASGI, D1
and coordinator RPC. The local smoke made no paid inference calls.

That scoped result does not approve the foundation admission logic or the overall pilot.
Passing tests cover the exercised cases; they do not negate the reproductions above.
Offline vectors are feature hashes and answers are deterministic policy fixtures, so these
runs do not measure live model accuracy, inference savings or hosted latency. The optional
1,000-event replay repeats 50 unique regression cases; it is not 1,000 independently reviewed
questions.

## Evidence still required

- **Data:** 100 public cases and 80 seed answers are agent-authored drafts, with zero human
  approvals. The planned reviewed benchmark and owner-held private release set are future work.
- **Hosted operation:** live Access authorization and memberships, Gateway routing, raw-payload
  suppression, response-cache bypass, single-attempt enforcement, billing, latency and recovery
  need owner-authorized staging verification. Request options and local mocks are not hosted proof.
- **Mobile:** a shared acceptance policy exists, but responsive WebKit CI and iPhone Duo
  Simulator/hardware coverage remain unverified. No device-support claim is made.
- **Release:** current source-bound review, human data/answer approval, live quality evidence,
  release assessment and exercised rollback remain gates. No coding-agent `GO` authorizes promotion.

See [Evaluation](EVALUATION.md), [Deployment and Gateway verification](DEPLOYMENT.md),
[Mobile QA](MOBILE_QA.md) and the [readiness checklist](ROADMAP.md) for the required evidence.

Mobile impact of this publication documentation: `N/A`; no runtime API, response payload,
latency behavior or interface is changed, and no fresh browser/device result is asserted.
