# Public repository boundaries

This project uses original fictional policies, products, questions and support answers.
It contains no real retailer's proprietary materials or real customer records. Publish a
dedicated application repository, not the entire personal roadmap workspace.

Ignored paths include credentials, runtime variables, databases, logs, artifacts and private
holdout folders. Ignore rules do not protect a file already committed. Before publication,
run `uv run python tools/public_safety.py`, inspect `git status`, staged files and history.
The scanner detects selected credential formats and prohibited paths; it is not a proof that
all secrets or personal information are absent. Enable GitHub secret scanning/push protection
where available. Rotate any exposed secret; deleting a later file does not revoke it.

Keep actual tester memberships, Access service credentials, Cloudflare tokens, raw traces,
database exports and private cases out of Git and coding environments. Public CI has no
deployment or inference secrets. Do not use `pull_request_target` to execute contributor code.
Protect instructions, workflows, labels, seed admission and release gates through owner review.

The public demo plays fixtures and has no inference binding. The invited pilot verifies
Access JWTs and server-side membership, private exact keys and scoped semantic admission.
HTML rendering uses text content, not model-generated HTML. Avoid logging raw questions.
Before real data, define retention, access controls, deletion and recovery responsibilities.

Publishing is intentionally visible and copyable. Public GitHub cannot offer zero risk.
Report a vulnerability privately to the repository owner; do not include live credentials,
customer information or exploit details in a public issue.
