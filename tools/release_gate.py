"""Validate owner-supplied release evidence. Never creates approval or private cases."""

import argparse
import json
from pathlib import Path

from agent_workflow import source_digest

REQUIRED = (
    "human_labels_reviewed",
    "approved_answers_reviewed",
    "access_verified",
    "adapter_live_checks",
    "budget_recovery_checks",
    "rollback_exercised",
    "reviewer_go",
    "qa_go",
    "fresh_live_quality",
    "private_release_assessment",
)


def validate(evidence: dict, digest: str) -> None:
    if evidence.get("source_digest") != digest:
        raise ValueError("Release evidence does not match this source")
    if any(evidence.get(gate) is not True for gate in REQUIRED):
        raise ValueError("Missing required owner-controlled release evidence")
    if not evidence.get("external_evidence_sha256") or not evidence.get("assessment_date"):
        raise ValueError("External evidence digest and assessment date are required")
    if evidence.get("semantic_serving") is True:
        if (
            evidence.get("incorrect_semantic_hits") != 0
            or evidence.get("accepted_semantic_hits", 0) < 1
        ):
            raise ValueError("Semantic serving requires a reported error-free assessment")
        if evidence.get("semantic_evidence_sufficient") is not True:
            raise ValueError("Owner must assess uncertainty; otherwise keep semantic shadow mode")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(json.loads(args.evidence.read_text()), source_digest())
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print("Required evidence supplied; repository/environment protections still apply")
