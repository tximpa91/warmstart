from copy import deepcopy

import agent_workflow as workflow
import pytest
from deploy_config import render
from release_gate import validate
from sync_agents import rendered


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setattr(workflow, "source_digest", lambda: "a" * 64)
    monkeypatch.setattr(workflow, "revision", lambda: "uncommitted")
    monkeypatch.setattr(
        workflow,
        "fingerprints",
        lambda: {
            "dataset_fingerprint": "b" * 64,
            "config_fingerprint": "c" * 64,
        },
    )
    state = {
        "task_id": "test",
        "phase": "development",
        "repair_cycles": 0,
        "history": [],
        "evidence": {},
    }
    workflow.freeze(state)
    return state


def report(state, verdict="GO"):
    return {
        key: state[key]
        for key in (
            "task_id",
            "source_digest",
            "head_sha",
            "dataset_fingerprint",
            "config_fingerprint",
        )
    } | {
        "role": state["phase"],
        "verdict": verdict,
        "repair_cycle": state["repair_cycles"],
        "commands": [
            {"gate": gate, "command": command, "exit_code": 0}
            for gate, command in (
                ("tests", "uv run pytest"),
                ("regression", "uv run python -m warmstart.evals"),
                ("checks", "uv run python tools/check.py"),
                ("worker-build", "uv run --group cloud pywrangler deploy --dry-run"),
            )
        ],
        "findings": [],
    }


def test_successful_role_order(candidate):
    for phase in ("reviewer", "qa", "ci"):
        assert candidate["phase"] == phase
        workflow.record(candidate, report(candidate))
    assert candidate["phase"] == "ready_for_owner"


def test_repair_invalidates_all_reviews_and_stops_after_two(candidate):
    for expected_cycle in (1, 2):
        workflow.record(candidate, report(candidate, "NO_GO"))
        assert candidate["repair_cycles"] == expected_cycle and candidate["phase"] == "repair"
        assert candidate["evidence"] == {}
        workflow.freeze(candidate)
    workflow.record(candidate, report(candidate, "NO_GO"))
    assert candidate["phase"] == "needs_owner"
    with pytest.raises(ValueError):
        workflow.freeze(candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        {"findings": "UNRESOLVED CRITICAL ISSUE"},
        {"dataset_fingerprint": ""},
        {"findings": [{"severity": "banana", "description": "invalid"}]},
        {"findings": [{"severity": "high", "description": "blocked"}]},
        {"commands": [{"command": "true", "exit_code": 0}]},
        {"source_digest": "stale"},
        {"head_sha": "stale"},
    ],
)
def test_malformed_or_blocking_reports_do_not_approve(candidate, mutation):
    value = report(candidate) | mutation
    with pytest.raises(ValueError):
        workflow.record(candidate, value)
    assert candidate["phase"] == "reviewer"


def test_stale_current_revision_and_missing_qa_gates(candidate, monkeypatch):
    monkeypatch.setattr(workflow, "revision", lambda: "different-head")
    with pytest.raises(ValueError, match="HEAD changed"):
        workflow.record(candidate, report(candidate))
    monkeypatch.setattr(workflow, "revision", lambda: "uncommitted")
    workflow.record(candidate, report(candidate))
    value = report(candidate) | {"commands": [{"gate": "tests", "command": "true", "exit_code": 0}]}
    with pytest.raises(ValueError, match="gates are missing"):
        workflow.record(candidate, value)


def test_generated_agents_have_no_drift():
    assert all(path.read_text() == text for path, text in rendered().items())


def test_deployment_config_fail_closed():
    with pytest.raises(ValueError):
        render("pilot", {})
    values = {
        "CF_ACCOUNT_ID": "a" * 32,
        "D1_DATABASE_ID": "a" * 8 + "-" + "b" * 27,
        "ACCESS_ISSUER": "https://example.cloudflareaccess.com",
        "ACCESS_AUDIENCE": "aud",
        "AI_GATEWAY_ID": "warmstart-staging",
    }
    config = render("staging", values)
    assert config["vars"]["PAID_INFERENCE"] == "false"
    assert config["vars"]["SEMANTIC_MODE"] == "off"
    malicious = deepcopy(values) | {"ACCESS_ISSUER": "https://evil.example"}
    with pytest.raises(ValueError):
        render("staging", malicious)


def test_missing_release_evidence_cannot_promote():
    with pytest.raises(ValueError, match="required"):
        validate({"source_digest": "a" * 64}, "a" * 64)
