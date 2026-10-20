"""Record the native-agent review protocol. This tool does not launch LLMs."""

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprints() -> dict[str, str]:
    from warmstart.config import Config, fingerprint
    from warmstart.evals import fixture_payload

    return {
        "dataset_fingerprint": fingerprint(fixture_payload()),
        "config_fingerprint": fingerprint(asdict(Config())),
    }


def source_digest(root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    digest = hashlib.sha256()
    for name in sorted(set(result.stdout.decode().split("\0")) - {""}):
        path = root / name
        if path.is_file():
            digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "uncommitted"


def freeze(state: dict) -> None:
    if state["phase"] not in ("development", "repair"):
        raise ValueError("Only a developer/repair candidate may be frozen")
    state.update(
        phase="reviewer",
        source_digest=source_digest(),
        head_sha=revision(),
        evidence={},
        **fingerprints(),
    )


def record(state: dict, report: dict, current_digest: str | None = None) -> None:
    if state["phase"] not in ("reviewer", "qa", "ci"):
        raise ValueError("No evidence is accepted in this phase")
    if report.get("role") != state["phase"]:
        raise ValueError("Evidence role does not match the required phase")
    if report.get("task_id") != state["task_id"]:
        raise ValueError("Evidence is for another task")
    if report.get("source_digest") != state["source_digest"]:
        raise ValueError("Stale report: candidate source digest differs")
    if (current_digest or source_digest()) != state["source_digest"]:
        raise ValueError("Source changed since freeze; start a repair and freeze again")
    if report.get("head_sha") != state["head_sha"]:
        raise ValueError("Stale report: revision differs")
    if revision() != state["head_sha"]:
        raise ValueError("HEAD changed since candidate freeze")
    if report.get("repair_cycle") != state["repair_cycles"]:
        raise ValueError("Evidence is for another repair cycle")
    required = ("dataset_fingerprint", "config_fingerprint", "commands", "findings")
    if any(key not in report for key in required):
        raise ValueError("Incomplete report: fingerprints, commands and findings are required")
    for key, value in fingerprints().items():
        if report[key] != value or state.get(key) != value:
            raise ValueError("Configuration or dataset fingerprint differs")
    findings = report["findings"]
    if not isinstance(findings, list) or any(
        not isinstance(item, dict)
        or item.get("severity") not in ("critical", "high", "medium", "low", "info")
        or not isinstance(item.get("description"), str)
        or not item["description"].strip()
        or type(item.get("resolved", False)) is not bool
        for item in findings
    ):
        raise ValueError("Findings must be structured, with recognized severity and description")
    verdict = report.get("verdict")
    if verdict not in ("GO", "NO_GO", "INCONCLUSIVE", "FAIL", "PASS"):
        raise ValueError("Unknown verdict")
    commands = report["commands"]
    if not isinstance(commands, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("command"), str)
        or not item.get("command", "").strip()
        or not isinstance(item.get("gate"), str)
        or type(item.get("exit_code")) is not int
        for item in commands
    ):
        raise ValueError("Commands must contain actual command/exit_code records")
    if state["phase"] in ("qa", "ci") and verdict in ("GO", "PASS"):
        if not commands or any(item["exit_code"] != 0 for item in commands):
            raise ValueError("A successful QA/CI verdict requires successful commands")
        expected = {"qa": {"tests", "regression"}, "ci": {"checks", "worker-build"}}
        if not expected[state["phase"]].issubset({item["gate"] for item in commands}):
            raise ValueError("Required verification gates are missing")
    if verdict in ("GO", "PASS") and any(
        item.get("severity") in ("critical", "high") and not item.get("resolved", False)
        for item in report["findings"]
        if isinstance(item, dict)
    ):
        raise ValueError("Unresolved critical/high findings cannot receive GO")
    state["history"].append(report)
    if verdict not in ("GO", "PASS"):
        repair(state)
        return
    state["evidence"][state["phase"]] = report
    state["phase"] = {"reviewer": "qa", "qa": "ci", "ci": "ready_for_owner"}[state["phase"]]


def repair(state: dict) -> None:
    state["evidence"] = {}
    if state["repair_cycles"] >= 2:
        state["phase"] = "needs_owner"
    else:
        state["repair_cycles"] += 1
        state["phase"] = "repair"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("start", "freeze", "record", "repair", "status", "digest")
    )
    parser.add_argument("--state", type=Path, default=ROOT / "artifacts/agent-workflow.json")
    parser.add_argument("--task-id")
    parser.add_argument("--criteria")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "digest":
            print(json.dumps({"source_digest": source_digest(), "head_sha": revision()}))
            return
        if args.action == "start":
            if args.state.exists():
                raise ValueError("State already exists; use a new task state path")
            if not args.task_id or not args.criteria:
                raise ValueError("Task ID and acceptance criteria are required")
            state = {
                "task_id": args.task_id,
                "criteria": args.criteria,
                "phase": "development",
                "repair_cycles": 0,
                "evidence": {},
                "history": [],
            }
        else:
            state = json.loads(args.state.read_text())
            if args.action == "freeze":
                freeze(state)
            elif args.action == "record":
                if not args.report:
                    raise ValueError("A structured report is required")
                record(state, json.loads(args.report.read_text()))
            elif args.action == "repair":
                if state["phase"] in ("needs_owner", "ready_for_owner"):
                    raise ValueError("This task requires the owner; start a new task")
                repair(state)
        if args.action != "status":
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps(state, indent=2))
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
