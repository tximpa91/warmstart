"""Exercise the real local workerd Python runtime, ASGI, D1 and Durable Object RPC.

Uses an isolated temporary emulator state, no Workers AI binding, no remote calls or keys.
"""

import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from agent_workflow import source_digest
from seed_sql import seed_sql

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(ROOT)
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    seed = artifacts / "seed.sql"
    seed.write_text(seed_sql())
    environment = dict(
        os.environ, WRANGLER_SEND_METRICS="false", CLOUDFLARE_CF_FETCH_ENABLED="false"
    )
    environment.setdefault("WRANGLER_LOG_PATH", str(artifacts / "wrangler-smoke.log"))
    with tempfile.TemporaryDirectory(prefix="warmstart-emulator-") as temporary:
        common = ["--local", "--config", "wrangler.smoke.toml", "--persist-to", temporary]
        for command in (
            ["d1", "migrations", "apply", "DB", *common],
            ["d1", "execute", "DB", *common, "--file", str(seed)],
        ):
            subprocess.run(
                ["npx", "--no-install", "wrangler", *command], env=environment, check=True
            )
        with (artifacts / "workerd.log").open("w") as log:
            process = subprocess.Popen(
                [
                    "npx",
                    "--no-install",
                    "wrangler",
                    "dev",
                    *common,
                    "--port",
                    "8788",
                    "--ip",
                    "127.0.0.1",
                    "--log-level",
                    "debug",
                ],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                with httpx.Client(base_url="http://127.0.0.1:8788", timeout=5) as client:
                    deadline = time.monotonic() + 90
                    while True:
                        try:
                            health = client.get("/healthz")
                            if health.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(
                                "Local Worker startup failed; inspect artifacts/workerd.log"
                            )
                        time.sleep(0.5)
                    assert health.json()["service"] == "warmstart"
                    bindings = client.get("/__bindings")
                    bindings.raise_for_status()
                    assert bindings.json() == {
                        "d1_policy": "v1",
                        "admission": "v1",
                        "reserved_and_settled": True,
                    }
                    forbidden = client.post(
                        "/v1/answer", json={"question": "What is the shipping cost?"}
                    )
                    assert forbidden.status_code == 403
                    report = {
                        "source_digest": source_digest(),
                        "runtime": "local workerd",
                        "asgi": True,
                        "d1": True,
                        "durable_object_rpc": True,
                        "missing_jwt_denied": True,
                        "paid_inference_calls": 0,
                        "hosted_integration": False,
                    }
                    (artifacts / "worker-smoke.json").write_text(
                        json.dumps(report, indent=2) + "\n"
                    )
                    print(json.dumps(report))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)


if __name__ == "__main__":
    main()
