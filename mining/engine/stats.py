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

import os
import sqlite3
import stat
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


def _owner_only(path: str) -> None:
    """Restrict ``path`` to owner-only access (0600).

    Applied both when the database is first created and when an existing
    file is opened, so a database left permissive by other means is
    tightened on next use. This only ever restricts access; it never
    weakens it. On platforms where POSIX permission semantics do not
    apply (os.name != 'posix') the call is skipped, matching the rest of
    the project's cross-platform behaviour. A genuine chmod failure on a
    supported system is raised, not hidden: silently storing mining
    history with loose permissions would weaken the guarantee.
    """
    if os.name == "posix":
        os.chmod(path, 0o600)


class MiningStatsStore:
    """SQLite-backed mining-session history.

    The database file and its parent directory are created safely, and
    the file is kept owner-only (0600) on supported systems - the same
    protection the blockchain chain store applies to its database.
    """

    def __init__(self, path: str):
        self._path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        # Refuse unsafe database paths instead of clobbering their
        # targets: a symlink (dangling or not) or a non-regular file is
        # rejected outright. New files are created with O_NOFOLLOW where
        # the platform offers it, so creation cannot be raced through a
        # swapped-in link either. Residual, documented: the sqlite3
        # stdlib API itself follows symlinks at connect time, so a link
        # swapped in between this validation and connect cannot be
        # excluded; the state directory is expected to be private.
        if os.path.lexists(path):
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(
                    f"refusing symbolic-link database path: {path}")
            if not stat.S_ISREG(mode):
                raise ValueError(
                    f"database path is not a regular file: {path}")
        else:
            # Create the file private (0600) before SQLite opens it.
            flags = os.O_CREAT | os.O_WRONLY
            flags |= getattr(os, "O_NOFOLLOW", 0)
            os.close(os.open(path, flags, 0o600))
        _owner_only(path)
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
            # The interpolated text is the module-level COLUMNS constant
            # (a fixed allowlist; record_session rejects unknown keys) -
            # only values are passed, as bound parameters.
            self._conn.execute(
                f"INSERT INTO mining_sessions ({', '.join(COLUMNS)}) "  # nosec B608 - fixed COLUMNS constant, bound values only
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
