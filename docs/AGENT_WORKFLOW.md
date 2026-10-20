# Agent workflow across Codex, Cursor and Claude Code

`AGENTS.md` is canonical project guidance; `agent-workflow/roles/*.md` contains shared role
instructions. `CLAUDE.md` imports `@AGENTS.md`. Generate native role adapters:

```bash
uv run python tools/sync_agents.py
uv run python tools/sync_agents.py --check
```

Codex reads `.codex/agents/*.toml`, Cursor reads `.cursor/agents/*.md`, and Claude reads
`.claude/agents/*.md`. Names include their tool prefix to avoid discovery collisions.
The developer implements; reviewer inspects independently; QA runs verification independently;
principal integrates findings. One tool is principal for a task. Switching tools requires a
handoff with current revision, digest, task, acceptance criteria, cycle and unresolved findings.

Ask the selected tool explicitly to delegate using its native agents. This application does
not run an LLM orchestrator or require cross-vendor API subscriptions. Native availability
and permissions vary; check discovery in a fresh task. If native delegation is unavailable,
perform explicit separate role stages and record that limitation. Codex subagents inherit
parent permissions. Claude QA's Bash tool is not a read-only security boundary.

## State and evidence

```bash
uv run python tools/agent_workflow.py start --task-id cache-isolation \
  --criteria 'No cross-profile reuse; expiry and new policy admissions tested'
uv run python tools/agent_workflow.py freeze
uv run python tools/agent_workflow.py digest
# After the native reviewer actually completes:
uv run python tools/agent_workflow.py record --report artifacts/reviewer.json
# Then independent QA, then CI evidence:
uv run python tools/agent_workflow.py record --report artifacts/qa.json
uv run python tools/agent_workflow.py record --report artifacts/ci.json
```

Reports include `role`, `task_id`, `head_sha`, `source_digest`, `repair_cycle`,
`dataset_fingerprint`, `config_fingerprint`, `verdict`, `commands` and `findings`.
`freeze` records the expected fingerprints; use `status` to read them. Each command has
`gate`, `command` and integer `exit_code`. QA GO requires successful `tests` and `regression`
gates; CI PASS requires `checks` and `worker-build`. Findings are structured objects with
recognized `severity`, nonempty `description` and optional boolean `resolved`.

The workflow accepts only the expected role at the frozen source/commit/config/dataset.
Missing or inconclusive evidence is not GO. NO_GO, FAIL or INCONCLUSIVE clears approvals
and starts a repair. The developer fixes, freezes again, and repeats reviewer and QA. Two
automatic repairs are allowed; the next failure enters `needs_owner`. Do not reset the task
merely to evade that limit. Changed source invalidates previous approvals.

The recorder cannot prove that an agent was independent or a command actually executed.
Report artifacts are advisory evidence; trusted CI and repository protections enforce merges.
Agents cannot grant human label approval, approve their own exceptions, or promote a pilot.
Luis owns the final merge and release decision. Report unresolved findings after the repair cap.

## Mobile acceptance in every task

Principal criteria and developer/reviewer/QA reports include a mobile impact statement using
[Mobile QA](MOBILE_QA.md). UI tasks cover mobile-first layouts, touch/focus/keyboard behavior,
text enlargement, readable evidence/errors and preserved request state through resize,
rotation and fold/unfold. Backend-only tasks cover mobile API/error/latency implications or
justify N/A. Record evidence in existing criteria/findings/artifacts; this adds no recorder fields.

QA records browser/OS, CSS viewport, orientation/posture, emulation versus named Simulator
or hardware, results and limitations. The generic 320/390/430/768/1024/1280 CSS px layout
matrix is not an official iPhone Duo viewport matrix. Actual Duo Safari folded/unfolded
checks and transitions need device-specific evidence; hardware coverage gates pilot support.
Planned WebKit responsive PR regression is not implemented or passed by these instructions.

NO_GO or missing mobile evidence uses the existing repair protocol. This policy does not
reset a task in `needs_owner`, authorize additional repairs beyond the cap, or weaken any
correctness, golden-set, admission or deployment gate.

References: [Codex agents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Cursor subagents](https://cursor.com/docs/subagents),
[Claude subagents](https://code.claude.com/docs/en/sub-agents),
[Claude memory imports](https://code.claude.com/docs/en/memory).
