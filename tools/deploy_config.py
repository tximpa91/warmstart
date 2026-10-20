"""Render ignored, environment-specific Wrangler config from explicit provisioning values."""

import argparse
import json
import os
import re
import tomllib
from pathlib import Path

from warmstart.gateway import validate_gateway_id

ROOT = Path(__file__).resolve().parents[1]


def render(environment: str, values: dict[str, str]) -> dict:
    if environment not in ("staging", "pilot"):
        raise ValueError("Use staging or pilot")
    required = (
        "CF_ACCOUNT_ID",
        "D1_DATABASE_ID",
        "ACCESS_ISSUER",
        "ACCESS_AUDIENCE",
        "AI_GATEWAY_ID",
    )
    if any(not values.get(name) for name in required):
        raise ValueError("Missing provisioning configuration: " + ", ".join(required))
    if not re.fullmatch(r"[0-9a-f]{32}", values["CF_ACCOUNT_ID"]):
        raise ValueError("Invalid account ID")
    database = values["D1_DATABASE_ID"]
    if (
        not re.fullmatch(r"[0-9a-f-]{36}", database)
        or database == "00000000-0000-0000-0000-000000000000"
    ):
        raise ValueError("Replace the database placeholder with the provisioned database ID")
    if not re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", values["ACCESS_ISSUER"]):
        raise ValueError("Use your exact Cloudflare Access team issuer")
    validate_gateway_id(values["AI_GATEWAY_ID"])
    log_mode = values.get("AI_GATEWAY_LOG_MODE") or "metadata"
    if log_mode not in ("metadata", "off"):
        raise ValueError("Use metadata or off for AI_GATEWAY_LOG_MODE")
    config = tomllib.loads((ROOT / "wrangler.toml").read_text())
    config.update(name=f"warmstart-{environment}", account_id=values["CF_ACCOUNT_ID"])
    config["main"] = str(ROOT / "src/worker.py")
    config["d1_databases"][0].update(
        database_name=f"warmstart-{environment}",
        database_id=database,
        migrations_dir=str(ROOT / "migrations"),
    )
    config["vars"].update(
        APP_ENV=environment,
        ACCESS_ISSUER=values["ACCESS_ISSUER"],
        ACCESS_AUDIENCE=values["ACCESS_AUDIENCE"],
        AI_GATEWAY_ID=values["AI_GATEWAY_ID"],
    )
    # These defaults are deliberate release gates. Runtime memberships are a secret.
    config["vars"].update(
        PAID_INFERENCE="false",
        SEMANTIC_MODE="off",
        AI_GATEWAY_LOG_MODE=log_mode,
    )
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "pilot"), required=True)
    args = parser.parse_args()
    target = ROOT / "artifacts" / f"wrangler.{args.environment}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(render(args.environment, dict(os.environ)), indent=2) + "\n")
    print(target)
