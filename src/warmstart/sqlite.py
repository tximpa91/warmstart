"""Local durable adapters. This module is deliberately outside the portable core."""

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from warmstart.data import policies, seeds
from warmstart.models import (
    Admission,
    BudgetExceeded,
    CachedAnswer,
    Policy,
    QuotaExceeded,
    RequestEvent,
    SeedAnswer,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
 profile TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(profile, version));
CREATE TABLE IF NOT EXISTS seeds (
 id TEXT PRIMARY KEY, profile TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS seed_scope ON seeds(profile, version);
CREATE TABLE IF NOT EXISTS exact_cache (
 key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 request_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coordinator_state (
 key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily_quotas (
 day TEXT NOT NULL, subject TEXT NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(day,subject));
CREATE TABLE IF NOT EXISTS reservations (
 id TEXT PRIMARY KEY, month TEXT NOT NULL, kind TEXT NOT NULL,
 reserved INTEGER NOT NULL, actual INTEGER, settled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS leases (
 key TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at REAL NOT NULL);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=3000")
    connection.executescript(SCHEMA)
    return connection


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:", *, seed: bool = True) -> None:
        self.connection = connect(path)
        if seed:
            for policy in policies():
                previous = self.connection.execute(
                    "SELECT payload FROM policies WHERE profile=? AND version=?",
                    (policy.profile, policy.version),
                ).fetchone()
                if previous and json.loads(previous[0]) != asdict(policy):
                    raise ValueError("Immutable policy changed; use a new edition/database")
                self.connection.execute(
                    "INSERT OR IGNORE INTO policies VALUES(?,?,?)",
                    (policy.profile, policy.version, json.dumps(asdict(policy))),
                )
            for entry in seeds():
                self.connection.execute(
                    "INSERT OR IGNORE INTO seeds VALUES(?,?,?,?)",
                    (entry.id, entry.profile, entry.version, json.dumps(asdict(entry))),
                )

    def close(self) -> None:
        self.connection.close()

    async def policy(self, profile: str, version: str) -> Policy | None:
        row = self.connection.execute(
            "SELECT payload FROM policies WHERE profile=? AND version=?", (profile, version)
        ).fetchone()
        return Policy(**json.loads(row[0])) if row else None

    async def candidates(self, profile: str, version: str) -> list[SeedAnswer]:
        rows = self.connection.execute(
            "SELECT payload FROM seeds WHERE profile=? AND version=? ORDER BY id LIMIT 128",
            (profile, version),
        ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row[0])
            payload["fact_ids"] = tuple(payload["fact_ids"])
            payload["vector"] = tuple(payload["vector"])
            result.append(SeedAnswer(**payload))
        return result

    async def exact_get(self, key: str, now: float) -> CachedAnswer | None:
        row = self.connection.execute(
            "SELECT payload FROM exact_cache WHERE key=? AND expires_at>?", (key, now)
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        payload["fact_ids"] = tuple(payload["fact_ids"])
        return CachedAnswer(**payload)

    async def exact_put(self, entry: CachedAnswer) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO exact_cache VALUES(?,?,?)",
            (entry.key, json.dumps(asdict(entry)), entry.expires_at),
        )

    async def event(self, event: RequestEvent) -> None:
        self.connection.execute(
            "INSERT INTO events VALUES(?,?)", (event.request_id, json.dumps(asdict(event)))
        )

    async def metrics(self) -> dict[str, object]:
        rows = self.connection.execute("SELECT payload FROM events").fetchall()
        events = [json.loads(row[0]) for row in rows]
        by_status: dict[str, int] = {}
        for event in events:
            by_status[event["status"]] = by_status.get(event["status"], 0) + 1
        return {
            "requests": len(events),
            "by_status": by_status,
            "cost_microusd": sum(event["cost_microusd"] for event in events),
            "cached_input_tokens": sum(event["cached_input_tokens"] for event in events),
            "raw_questions_recorded": False,
        }


class SQLiteCoordinator:
    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        budget_microusd: int = 1_000_000,
        identity_daily_limit: int = 50,
        global_daily_limit: int = 200,
        max_concurrency: int = 5,
    ) -> None:
        if min(budget_microusd, identity_daily_limit, global_daily_limit, max_concurrency) < 0:
            raise ValueError("Coordinator limits cannot be negative")
        self.connection = connect(path)
        self.budget_microusd = budget_microusd
        self.identity_daily_limit = identity_daily_limit
        self.global_daily_limit = global_daily_limit
        self.max_concurrency = max_concurrency
        self.connection.execute("INSERT OR IGNORE INTO coordinator_state VALUES('version','v1')")

    def close(self) -> None:
        self.connection.close()

    async def admit(self, identity_id: str, now: float) -> Admission:
        day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            for subject, limit in (
                (f"identity:{identity_id}", self.identity_daily_limit),
                ("global", self.global_daily_limit),
            ):
                row = connection.execute(
                    "SELECT count FROM daily_quotas WHERE day=? AND subject=?", (day, subject)
                ).fetchone()
                if (row[0] if row else 0) >= limit:
                    raise QuotaExceeded()
                connection.execute(
                    "INSERT INTO daily_quotas VALUES(?,?,1) ON CONFLICT(day,subject) "
                    "DO UPDATE SET count=count+1",
                    (day, subject),
                )
            row = connection.execute(
                "SELECT value FROM coordinator_state WHERE key='version'"
            ).fetchone()
            version = str(row[0])
            connection.execute("COMMIT")
            return Admission(version, uuid.uuid4().hex)
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    async def reserve(self, kind: str, amount_microusd: int, now: float) -> str:
        if amount_microusd < 0 or kind not in ("embedding", "generation"):
            raise ValueError("Invalid reservation")
        month = datetime.fromtimestamp(now, UTC).strftime("%Y-%m")
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            used = connection.execute(
                "SELECT COALESCE(SUM(CASE WHEN settled=1 THEN actual ELSE reserved END),0) "
                "FROM reservations WHERE month=?",
                (month,),
            ).fetchone()[0]
            if int(used) + amount_microusd > self.budget_microusd:
                raise BudgetExceeded()
            identifier = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO reservations(id,month,kind,reserved) VALUES(?,?,?,?)",
                (identifier, month, kind, amount_microusd),
            )
            connection.execute("COMMIT")
            return identifier
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    async def settle(self, reservation_id: str, actual_microusd: int) -> None:
        if actual_microusd < 0:
            raise ValueError("Actual cost cannot be negative")
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT reserved,actual,settled FROM reservations WHERE id=?", (reservation_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown reservation")
            if row[2]:
                if row[1] != actual_microusd:
                    raise ValueError("Reservation already settled with different cost")
            else:
                connection.execute(
                    "UPDATE reservations SET actual=?,settled=1 WHERE id=?",
                    (actual_microusd, reservation_id),
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        if actual_microusd > row[0]:
            # Full cost has been retained; subsequent requests see the overspend.
            raise BudgetExceeded("Provider usage exceeded the conservative reservation")

    async def acquire(self, key: str, now: float, ttl: float) -> str | None:
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DELETE FROM leases WHERE expires_at<=?", (now,))
            count = connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
            exists = connection.execute("SELECT 1 FROM leases WHERE key=?", (key,)).fetchone()
            if exists or count >= self.max_concurrency:
                connection.execute("COMMIT")
                return None
            token = uuid.uuid4().hex
            connection.execute("INSERT INTO leases VALUES(?,?,?)", (key, token, now + ttl))
            connection.execute("COMMIT")
            return token
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    async def release(self, key: str, token: str) -> None:
        self.connection.execute("DELETE FROM leases WHERE key=? AND token=?", (key, token))

    async def activate(self, version: str) -> None:
        if version not in ("v1", "v2"):
            raise ValueError("Unknown policy version")
        self.connection.execute(
            "UPDATE coordinator_state SET value=? WHERE key='version'", (version,)
        )

    async def state(self) -> dict[str, object]:
        rows = self.connection.execute(
            "SELECT month,kind,SUM(CASE WHEN settled=1 THEN actual ELSE reserved END) "
            "FROM reservations GROUP BY month,kind ORDER BY month,kind"
        ).fetchall()
        values: list[dict[str, Any]] = [
            {"month": row[0], "kind": row[1], "committed_microusd": row[2]} for row in rows
        ]
        version = self.connection.execute(
            "SELECT value FROM coordinator_state WHERE key='version'"
        ).fetchone()[0]
        return {"active_policy_version": version, "spending": values}
