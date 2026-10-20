"""Owner-invoked, bounded hosted smoke. This is not a quality or private release assessment."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from agent_workflow import source_digest


async def run(url: str, *, paid: bool, output: Path) -> None:
    if urlparse(url).scheme != "https" or urlparse(url).path not in ("", "/"):
        raise ValueError("Use the provisioned HTTPS application origin")
    headers = {
        "CF-Access-Client-Id": os.environ["ACCESS_CLIENT_ID"],
        "CF-Access-Client-Secret": os.environ["ACCESS_CLIENT_SECRET"],
    }
    results = []
    async with httpx.AsyncClient(headers=headers, timeout=25, follow_redirects=False) as client:
        health = await client.get(url + "/healthz")
        health.raise_for_status()
        async with httpx.AsyncClient(timeout=10) as anonymous:
            unauthorized = await anonymous.get(url + "/v1/metrics")
        if unauthorized.status_code == 200:
            raise ValueError("Unauthorized metrics access succeeded")
        questions = ["my order status"]
        if paid:
            questions += ["What is the standard shipping cost?"] * 2
        for question in questions:
            started = time.perf_counter()
            response = await client.post(url + "/v1/answer", json={"question": question})
            response.raise_for_status()
            body = response.json()
            results.append(
                {
                    "status": body["cache_status"],
                    "version": body["policy_version"],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        if paid and results[-1]["status"] != "exact":
            raise ValueError("Second identical request did not hit the private exact cache")
    output.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(
        output.write_text,
        json.dumps(
            {
                "source_digest": source_digest(),
                "paid_requested": paid,
                "requests": results,
                "quality_assessed": False,
            },
            indent=2,
        )
        + "\n",
    )
    print("Hosted smoke completed; response text and credentials were not recorded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("artifacts/live-smoke.json"))
    args = parser.parse_args()
    asyncio.run(run(args.url.rstrip("/"), paid=args.allow_paid, output=args.output))
