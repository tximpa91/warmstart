"""Durable-Object ledger using atomic multi-key writes and an instance lock.

The storage interface is injected so the actual state transitions can be tested
under CPython without pretending a fake binding is a deployed integration test.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from warmstart.cloud import plain
from warmstart.models import BudgetExceeded, QuotaExceeded


class BindingLedger:
    def __init__(
        self,
        storage: Any,
        convert: Callable[[object], Any],
        *,
        budget_microusd: int = 12_000_000,
        identity_limit: int = 50,
        global_limit: int = 200,
        max_concurrency: int = 5,
    ) -> None:
        if min(budget_microusd, identity_limit, global_limit, max_concurrency) < 0:
            raise ValueError("Limits must be nonnegative")
        self.storage = storage
        self.convert = convert
        self.budget = budget_microusd
        self.identity_limit = identity_limit
        self.global_limit = global_limit
        self.max_concurrency = max_concurrency
        self.lock = asyncio.Lock()

    async def _get(self, key: str, default: Any = None) -> Any:
        raw = plain(await self.storage.get(key))
        return json.loads(raw) if raw else default

    async def _put(self, values: dict[str, Any]) -> None:
        # One multi-key put is atomic. Values are strings to avoid proxy lifetime issues.
        await self.storage.put(
            self.convert({key: json.dumps(value) for key, value in values.items()})
        )

    async def operation(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.lock:
            now = float(payload.get("now", datetime.now(UTC).timestamp()))
            moment = datetime.fromtimestamp(now, UTC)
            month, day = moment.strftime("%Y-%m"), moment.strftime("%Y-%m-%d")
            if name == "admit":
                quotas = await self._get("quota:" + day, {"total": 0, "subjects": {}})
                subject = str(payload["identity_id"])
                count = quotas["subjects"].get(subject, 0)
                if count >= self.identity_limit or quotas["total"] >= self.global_limit:
                    raise QuotaExceeded()
                version = await self._get("active-policy", "v1")
                quotas["subjects"][subject] = count + 1
                quotas["total"] += 1
                await self._put({"quota:" + day: quotas})
                return {"version": version, "request_id": uuid.uuid4().hex}
            if name == "activate":
                if payload["version"] not in ("v1", "v2"):
                    raise ValueError("Unknown policy version")
                await self._put({"active-policy": payload["version"]})
                return {"ok": True}
            if name == "reserve":
                amount, kind = payload["amount"], payload["kind"]
                if type(amount) is not int or amount < 0 or kind not in ("embedding", "generation"):
                    raise ValueError("Invalid reservation")
                ledger = await self._get("budget:" + month, {"committed": 0, "by_kind": {}})
                if ledger["committed"] + amount > self.budget:
                    raise BudgetExceeded()
                identifier = uuid.uuid4().hex
                ledger["committed"] += amount
                ledger["by_kind"][kind] = ledger["by_kind"].get(kind, 0) + amount
                await self._put(
                    {
                        "budget:" + month: ledger,
                        "reservation:" + identifier: {
                            "month": month,
                            "kind": kind,
                            "reserved": amount,
                            "actual": None,
                        },
                    }
                )
                return {"reservation_id": identifier}
            if name == "settle":
                identifier, actual = str(payload["reservation_id"]), payload["actual"]
                if type(actual) is not int or actual < 0:
                    raise ValueError("Invalid settlement")
                reservation = await self._get("reservation:" + identifier)
                if reservation is None:
                    raise ValueError("Unknown reservation")
                if reservation["actual"] is not None:
                    if reservation["actual"] != actual:
                        raise ValueError("Conflicting settlement")
                    return {"ok": True}
                budget_key = "budget:" + reservation["month"]
                ledger = await self._get(budget_key)
                delta = actual - reservation["reserved"]
                ledger["committed"] += delta
                ledger["by_kind"][reservation["kind"]] += delta
                reservation["actual"] = actual
                await self._put({budget_key: ledger, "reservation:" + identifier: reservation})
                if actual > reservation["reserved"]:
                    raise BudgetExceeded("Usage exceeded the conservative reservation")
                return {"ok": True}
            if name in ("acquire", "release"):
                leases = await self._get("leases", {})
                leases = {key: item for key, item in leases.items() if item["expires_at"] > now}
                key = str(payload["key"])
                if name == "release":
                    if key in leases and leases[key]["token"] == payload["token"]:
                        del leases[key]
                    await self._put({"leases": leases})
                    return {"ok": True}
                if key in leases or len(leases) >= self.max_concurrency:
                    return {"token": None}
                token = uuid.uuid4().hex
                leases[key] = {"token": token, "expires_at": now + float(payload["ttl"])}
                await self._put({"leases": leases})
                return {"token": token}
            if name == "state":
                ledger = await self._get("budget:" + month, {"committed": 0, "by_kind": {}})
                return {
                    "active_policy_version": await self._get("active-policy", "v1"),
                    "month": month,
                    "committed_microusd": ledger["committed"],
                    "budget_microusd": self.budget,
                    "by_kind": ledger["by_kind"],
                }
            raise ValueError("Unknown operation")
