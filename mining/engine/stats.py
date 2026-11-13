"""Persistent mining statistics for the TASK 005 engine (brief Phase 6).

Follows the project's existing database architecture: a small
context-managed SQLite store (same pattern as ``blockchain.storage``),
in its own database file so mining history never collides with chain data.
Records survive application restarts; every mining cycle - successful or
not - is written exactly once with its own session ID.

Only real mining-session measurements are recorded here; benchmark numbers
never enter this store.
"""

from __future__ import annotations

import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS mining_sessions (
    session_id        TEXT PRIMARY KEY,
    started_at        TEXT NOT NULL,
    finished_at       TEXT NOT NULL,
    height            INTEGER,
    prev_hash         TEXT,
    block_hash        TEXT,
    seconds           REAL NOT NULL,
    hashes            INTEGER NOT NULL,
    hashrate_avg      REAL NOT NULL,
    hashrate_peak     REAL NOT NULL,
    backend           TEXT NOT NULL,
    batches           INTEGER NOT NULL,
    nonce             INTEGER,
    extranonce_counter INTEGER NOT NULL,
    submit_result     TEXT NOT NULL,
    accepted          INTEGER NOT NULL,
    coinbase_value    INTEGER,
    fees              INTEGER,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    kind              TEXT NOT NULL,
    detail            TEXT
);
CREATE TABLE IF NOT EXISTS agent_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    kind              TEXT NOT NULL,
    detail            TEXT
);
"""

COLUMNS = (
    "session_id", "started_at", "finished_at", "height", "prev_hash",
    "block_hash", "seconds", "hashes", "hashrate_avg", "hashrate_peak",
    "backend", "batches", "nonce", "extranonce_counter", "submit_result",
    "accepted", "coinbase_value", "fees", "error",
)


class MiningStatsStore:
    """SQLite-backed mining-session history."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def __enter__(self) -> "MiningStatsStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def path(self) -> str:
        return self._path

    def record_session(self, record: dict) -> None:
        """Insert one finished mining cycle. Unknown keys are rejected."""
        unknown = set(record) - set(COLUMNS)
        if unknown:
            raise ValueError(f"unknown session record fields: {sorted(unknown)}")
        missing = {"session_id", "started_at", "finished_at", "seconds",
                   "hashes", "hashrate_avg", "hashrate_peak", "backend",
                   "batches", "extranonce_counter", "submit_result",
                   "accepted"} - set(record)
        if missing:
            raise ValueError(f"session record missing fields: {sorted(missing)}")
        with self._lock:
            self._conn.execute(
                f"INSERT INTO mining_sessions ({', '.join(COLUMNS)}) "
                f"VALUES ({', '.join(':' + c for c in COLUMNS)})",
                {c: record.get(c) for c in COLUMNS},
            )
            self._conn.commit()

    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mining_sessions ORDER BY started_at DESC, "
                "session_id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def record_decision(self, ts: str, kind: str, detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_decisions (ts, kind, detail) VALUES (?, ?, ?)",
                (ts, kind, detail))
            self._conn.commit()

    def record_event(self, ts: str, kind: str, detail: str = "") -> None:
        """Errors and recovery events - never silently discarded."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_events (ts, kind, detail) VALUES (?, ?, ?)",
                (ts, kind, detail))
            self._conn.commit()

    def decisions(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_decisions ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in rows]

    def events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_events ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in rows]

    def totals(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cycles, "
                "COALESCE(SUM(accepted), 0) AS accepted, "
                "COALESCE(SUM(hashes), 0) AS hashes, "
                "COALESCE(SUM(seconds), 0.0) AS seconds, "
                "COALESCE(SUM(coinbase_value), 0) AS coinbase_value, "
                "COALESCE(SUM(fees), 0) AS fees "
                "FROM mining_sessions").fetchone()
        result = dict(row)
        result["hashrate_avg"] = (
            result["hashes"] / result["seconds"] if result["seconds"] else 0.0)
        return result
