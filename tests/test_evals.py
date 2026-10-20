import json

import pytest

from warmstart.evals import evaluate, load_cases, verify_manifest


def test_starter_data_truthful_and_grouped():
    cases = load_cases()
    assert len(cases) == 100
    assert sum(case.split == "development" for case in cases) == 50
    assert sum(case.split == "regression" for case in cases) == 50
    assert all(case.review_status == "agent_authored_draft" for case in cases)
    development = {case.family_id for case in cases if case.split == "development"}
    regression = {case.family_id for case in cases if case.split == "regression"}
    assert development.isdisjoint(regression)
    verify_manifest()


@pytest.mark.parametrize("suite", ["development", "regression"])
async def test_replay_gates_and_honest_evidence(suite):
    report = await evaluate(suite)
    assert report["pass"], json.dumps(report, indent=2)
    assert report["human_reviewed_cases"] == 0
    assert report["production_promotion_eligible"] is False


async def test_human_review_gate_fails_for_drafts():
    with pytest.raises(ValueError, match="Human review gate failed"):
        await evaluate("regression", require_human_reviewed=True)
