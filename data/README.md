# Public synthetic evaluation data

These 100 starter cases and the policy corpus are original, agent-authored fictional fixtures. None have been human-reviewed. They are engineering regression drafts, not a completed human-approved golden set. There are 50 development and 50 regression cases, with distinct authored question templates. The 1,000-case target and 400 private release cases do not exist yet.

Each case labels acceptable factual output and cache reuse permission. A safe miss is acceptable. Expected labels are passed only to the evaluator, never to the service. The policies and seed answers live in `warmstart.data`. Offline vectors use deterministic feature hashing, not BGE. Live semantic quality and cost claims require separate evidence.

Review and correct each case against the policy before changing its status to `human_reviewed`, and record reviewer identity plus review date. Keep the private release set outside this repository and all coding environments.
