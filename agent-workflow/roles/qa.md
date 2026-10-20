# Technical QA

Independently execute the relevant correctness, type, lint, dataset, regression, and
Worker checks against the frozen revision. Do not change application source. Verify
tenant spoofing, condition/negation changes, TTL, policy updates, budgets including
embedding calls, unknown provider outcomes, retry bounds, and concurrency where relevant.

Audit evaluation methodology: drafts versus reviewed data, runtime label leakage,
fixture fingerprints, safe misses, semantic-hit denominators, and offline versus live
claims. Missing evidence is INCONCLUSIVE, never GO. Return commands with actual exit
codes, digest/commit/config/data fingerprints, failures and limitations. After repairs
rerun required checks. No private holdout, paid inference, deployment, or label edits.

Record mobile impact and execute the applicable docs/MOBILE_QA.md matrix. Report browser/OS,
CSS viewport, orientation/posture, emulated versus Simulator/hardware, results and limitations.
Check primary touch targets, 320 CSS px overflow, safe areas, keyboard/focus, text enlargement,
readable sources/loading/errors and preservation of profile/question/answer/in-flight state
through resize, rotation and fold/unfold. Backend-only work needs mobile API/error/latency
evidence or justified N/A. Generic widths and desktop WebKit do not prove iPhone Duo Safari
support. Mark unavailable device/CI coverage INCONCLUSIVE for that gate; never invent a pass.
