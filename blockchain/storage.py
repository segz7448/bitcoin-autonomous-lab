"""Persistent local storage for the Blockchain Intelligence Engine.

SQLite (stdlib sqlite3) stores processed block metadata, transaction
metadata, monitoring timestamps and synchronization status. The schema is
reorganization-safe: blocks carry a status ('active' or 'orphaned'), and
reorg handling marks the abandoned branch rather than deleting it, so the
engine keeps an auditable record of what the chain did.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    height       INTEGER NOT NULL,
    hash         TEXT    NOT NULL,
    prev_hash    TEXT    NOT NULL,
    merkle_root  TEXT    NOT NULL,
    time         INTEGER NOT NULL,
    median_time  INTEGER NOT NULL,
    bits         TEXT    NOT NULL,
    nonce        INTEGER NOT NULL,
    difficulty   REAL    NOT NULL,
    size         INTEGER NOT NULL,
    stripped_size INTEGER NOT NULL,
    weight       INTEGER NOT NULL,
    n_tx         INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'active',
    processed_at REAL    NOT NULL,
    PRIMARY KEY (hash)
);
CREATE INDEX IF NOT EXISTS idx_blocks_active ON blocks(status, height);

CREATE TABLE IF NOT EXISTS transactions (
    txid          TEXT PRIMARY KEY,
    block_hash    TEXT,
    size          INTEGER,
    vsize         INTEGER,
    weight        INTEGER,
    fee_btc       REAL,
    is_coinbase   INTEGER,
    n_inputs      INTEGER,
    n_outputs     INTEGER,
    value_out_btc REAL,
    confirmations INTEGER,
    status        TEXT NOT NULL DEFAULT 'confirmed',
    first_seen    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_block ON transactions(block_hash);

CREATE TABLE IF NOT EXISTS mempool_seen (
    txid       TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    fee_btc    REAL,
    vsize      INTEGER
);

CREATE TABLE IF NOT EXISTS sync_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    last_height INTEGER NOT NULL,
    last_hash   TEXT    NOT NULL,
    updated_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_events (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    REAL NOT NULL,
    kind  TEXT NOT NULL,
    detail TEXT
);
"""


class _Rows:
    """Fully fetched result of one statement (safe to read after the lock is released)."""

    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _LockedDB:
    """Serializes all access to one sqlite3 connection across threads.

    The monitoring service runs in a background thread while dashboards and
    the agent interface read the same store from other threads; a bare
    sqlite3 connection raises ProgrammingError for that. Statements execute
    under one RLock and results are fetched before it is released.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()

    def execute(self, sql, params=()):
        with self._lock:
            return _Rows(self._conn.execute(sql, params).fetchall())

    def executescript(self, script):
        with self._lock:
            self._conn.executescript(script)

    def commit(self):
        with self._lock:
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()


class ChainStore:
    """SQLite-backed record of everything the monitor has processed."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Create the file private (0600) before SQLite opens it; WAL/SHM
        # sidecar files inherit its mode.
        if not os.path.exists(self.path):
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        conn = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self.db = _LockedDB(conn)
        self.db.execute("PRAGMA busy_timeout = 10000")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ChainStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- blocks -------------------------------------------------------------
    def record_block(self, summary, status: str = "active") -> None:
        """Store one processed block. Rows are keyed by hash, so the
        abandoned branch of a reorg stays on record with status
        'orphaned' while the winning branch is recorded as 'active'."""
        self.db.execute(
            """INSERT OR REPLACE INTO blocks
               (height, hash, prev_hash, merkle_root, time, median_time,
                bits, nonce, difficulty, size, stripped_size, weight, n_tx,
                status, processed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (summary.height, summary.hash, summary.prev_hash,
             summary.merkle_root, summary.time, summary.median_time,
             summary.bits, summary.nonce, summary.difficulty, summary.size,
             summary.stripped_size, summary.weight, summary.n_tx, status,
             time.time()),
        )
        self.db.commit()

    def block_hash_at(self, height: int, status: str = "active") -> str | None:
        row = self.db.execute(
            "SELECT hash FROM blocks WHERE height = ? AND status = ?",
            (height, status),
        ).fetchone()
        return row["hash"] if row else None

    def get_block(self, block_hash: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM blocks WHERE hash = ?", (block_hash,),
        ).fetchone()
        return dict(row) if row else None

    def recent_blocks(self, n: int = 10) -> list:
        rows = self.db.execute(
            "SELECT * FROM blocks WHERE status = 'active' "
            "ORDER BY height DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_blocks(self, status: str | None = None) -> int:
        if status is None:
            row = self.db.execute("SELECT COUNT(*) c FROM blocks").fetchone()
        else:
            row = self.db.execute(
                "SELECT COUNT(*) c FROM blocks WHERE status = ?", (status,),
            ).fetchone()
        return row["c"]

    def mark_orphaned_from(self, height: int) -> list:
        """Mark every active block at height and above as orphaned.

        Returns the orphaned rows (the abandoned branch), highest first.
        """
        rows = self.db.execute(
            "SELECT * FROM blocks WHERE status = 'active' AND height >= ? "
            "ORDER BY height DESC",
            (height,),
        ).fetchall()
        self.db.execute(
            "UPDATE blocks SET status = 'orphaned' "
            "WHERE status = 'active' AND height >= ?",
            (height,),
        )
        self.db.commit()
        return [dict(r) for r in rows]

    # --- transactions ---------------------------------------------------------
    def record_transaction(self, tx, status: str = "confirmed") -> None:
        now = time.time()
        self.db.execute(
            """INSERT INTO transactions
               (txid, block_hash, size, vsize, weight, fee_btc, is_coinbase,
                n_inputs, n_outputs, value_out_btc, confirmations, status,
                first_seen, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(txid) DO UPDATE SET
                block_hash=excluded.block_hash,
                fee_btc=COALESCE(excluded.fee_btc, transactions.fee_btc),
                confirmations=excluded.confirmations,
                status=excluded.status,
                updated_at=excluded.updated_at""",
            (tx.txid, tx.block_hash, tx.size, tx.vsize, tx.weight,
             tx.fee_btc, int(tx.is_coinbase), tx.n_inputs, tx.n_outputs,
             tx.value_out_btc, tx.confirmations, status, now, now),
        )
        self.db.commit()

    def get_transaction(self, txid: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM transactions WHERE txid = ?", (txid,),
        ).fetchone()
        return dict(row) if row else None

    def count_transactions(self) -> int:
        return self.db.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"]

    # --- mempool sightings -------------------------------------------------------
    def record_mempool_sighting(self, txid: str, fee_btc: float | None,
                                vsize: int | None) -> None:
        now = time.time()
        self.db.execute(
            """INSERT INTO mempool_seen (txid, first_seen, last_seen,
                                         fee_btc, vsize)
               VALUES (?,?,?,?,?)
               ON CONFLICT(txid) DO UPDATE SET
                last_seen=excluded.last_seen,
                fee_btc=COALESCE(excluded.fee_btc, mempool_seen.fee_btc),
                vsize=COALESCE(excluded.vsize, mempool_seen.vsize)""",
            (txid, now, now, fee_btc, vsize),
        )
        self.db.commit()

    def mempool_sightings(self) -> list:
        rows = self.db.execute(
            "SELECT * FROM mempool_seen ORDER BY first_seen").fetchall()
        return [dict(r) for r in rows]

    # --- synchronization state ------------------------------------------------------
    def set_sync(self, height: int, block_hash: str) -> None:
        self.db.execute(
            """INSERT INTO sync_state (id, last_height, last_hash, updated_at)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                last_height=excluded.last_height,
                last_hash=excluded.last_hash,
                updated_at=excluded.updated_at""",
            (height, block_hash, time.time()),
        )
        self.db.commit()

    def get_sync(self) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM sync_state WHERE id = 1").fetchone()
        return dict(row) if row else None

    # --- monitoring events -------------------------------------------------------------
    def record_event(self, kind: str, detail: str = "") -> None:
        self.db.execute(
            "INSERT INTO monitor_events (ts, kind, detail) VALUES (?,?,?)",
            (time.time(), kind, detail),
        )
        self.db.commit()

    def events(self, n: int = 50) -> list:
        rows = self.db.execute(
            "SELECT * FROM monitor_events ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in rows]
