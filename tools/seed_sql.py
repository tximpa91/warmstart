"""Write idempotent D1 seed SQL. Drafts remain ineligible for deployed reuse."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from warmstart.data import policies, seeds


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def seed_sql() -> str:
    statements = ["-- Original synthetic fixtures. Human review pending."]
    for policy in policies():
        values = [policy.profile, policy.version, json.dumps(asdict(policy), sort_keys=True)]
        # A conflicting payload attempts UPDATE and is rejected by the immutable trigger.
        statements.append(
            "INSERT INTO policies(profile,version,payload) VALUES("
            + ",".join(map(quote, values))
            + ") ON CONFLICT(profile,version) DO UPDATE "
            "SET payload=excluded.payload WHERE policies.payload!=excluded.payload;"
        )
    for seed in seeds():
        values = [seed.id, seed.profile, seed.version, json.dumps(asdict(seed), sort_keys=True)]
        statements.append(
            "INSERT OR IGNORE INTO seeds VALUES(" + ",".join(map(quote, values)) + ");"
        )
    return "\n".join(statements) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/seed.sql"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(seed_sql())
    print(f"Wrote {args.output}; deployed semantic eligibility remains false")
