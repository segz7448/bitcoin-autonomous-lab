"""Background blockchain monitoring service.

The service polls the node cheaply (a single getblockcount per cycle),
walks and stores any new blocks, detects chain reorganizations by comparing
stored hashes against the node's, and keeps going through RPC failures with
exponential backoff. State persists in a ChainStore, so a restart resumes
exactly where the chain left off.
"""

from __future__ import annotations

import logging
import threading
import urllib.error
from dataclasses import asdict, dataclass, field

from node.rpc_client import RPCError

from .analysis import BlockAnalyzer
from .reader import BlockchainReader
from .storage import ChainStore
from .transactions import TransactionIntelligence, _summarize_tx

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """What one synchronization cycle observed and did."""

    ok: bool
    error: str | None = None
    node_height: int = 0
    synced_height_before: int = -1
    synced_height_after: int = -1
    new_blocks: list = field(default_factory=list)  # hashes, ascending
    reorg_detected: bool = False
    orphaned_blocks: list = field(default_factory=list)  # hashes, descending
    in_sync: bool = True
    consecutive_failures: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class ChainMovedError(Exception):
    """The node's chain changed while a sync walk was in progress."""


class MonitoringService:
    """Polls a regtest node and maintains a persistent record of the chain.

    Cost discipline: an idle cycle issues exactly one getblockcount RPC plus
    one getblockhash tip check. Full getblock calls happen only for blocks
    that are actually new (or re-added by a reorg).
    """

    def __init__(self, rpc, store: ChainStore, poll_interval: float = 1.0,
                 max_backoff: float = 30.0, rpc_factory=None):
        """rpc: a BitcoinRPC client. rpc_factory: optional zero-arg callable
        returning a fresh client; used to re-establish the connection
        (new cookie) after an RPC failure, e.g. a node restart."""
        self.rpc = rpc
        self._rpc_factory = rpc_factory
        self.reader = BlockchainReader(rpc)
        self.analyzer = BlockAnalyzer(self.reader)
        self.txs = TransactionIntelligence(rpc)
        self.store = store
        self.poll_interval = poll_interval
        self.max_backoff = max_backoff
        self._new_block_listeners: list = []
        self._failures = 0
        self._stop = threading.Event()

    def __enter__(self) -> "MonitoringService":
        return self

    def __exit__(self, *exc) -> None:
        self.store.close()

    # --- listeners ------------------------------------------------------------
    def add_block_listener(self, callback) -> None:
        """Register callback(summary) invoked for each newly stored block."""
        self._new_block_listeners.append(callback)

    def _emit_new_block(self, summary) -> None:
        for cb in self._new_block_listeners:
            try:
                cb(summary)
            except Exception:
                logger.exception("block listener failed")

    # --- one synchronization cycle ------------------------------------------------
    def _refresh_client(self) -> None:
        """Rebuild reader/analyzer/txs around the current client."""
        self.reader = BlockchainReader(self.rpc)
        self.analyzer = BlockAnalyzer(self.reader)
        self.txs = TransactionIntelligence(self.rpc)

    def sync_once(self) -> SyncReport:
        """Compare the node to the store; fetch and persist what changed."""
        report = SyncReport(ok=True)
        if self._failures > 0 and self._rpc_factory is not None:
            # Previous cycle failed: try to re-establish the connection
            # before giving up on this one.
            try:
                self.rpc = self._rpc_factory()
                self._refresh_client()
            except Exception as exc:
                logger.debug("reconnect attempt failed: %s", exc)
        try:
            node_height = self.rpc.get_block_count()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            self._failures += 1
            logger.warning("node unreachable (%d consecutive): %s",
                           self._failures, exc)
            self.store.record_event("rpc_unreachable", str(exc))
            return SyncReport(ok=False, error=str(exc),
                              consecutive_failures=self._failures)
        except RPCError as exc:
            self._failures += 1
            logger.warning("rpc error (%d consecutive): %s",
                           self._failures, exc)
            self.store.record_event("rpc_error", str(exc))
            return SyncReport(ok=False, error=str(exc),
                              consecutive_failures=self._failures)

        self._failures = 0
        report.node_height = node_height
        sync = self.store.get_sync()
        synced_height = sync["last_height"] if sync else -1
        report.synced_height_before = synced_height

        # Reorg check: does the node still agree with our recorded tip?
        if synced_height >= 0:
            stored_hash = self.store.block_hash_at(synced_height)
            if stored_hash:
                node_hash = (self.reader.block_hash_at(synced_height)
                             if synced_height <= node_height else None)
                if node_hash != stored_hash:
                    fork_height = self._find_fork_height(
                        min(synced_height, node_height))
                    orphaned = self.store.mark_orphaned_from(fork_height)
                    report.reorg_detected = True
                    report.orphaned_blocks = [b["hash"] for b in orphaned]
                    self.store.record_event(
                        "reorg",
                        f"fork at {fork_height}; orphaned "
                        f"{len(orphaned)} block(s)",
                    )
                    logger.warning("reorg detected: fork at height %d, "
                                   "%d block(s) orphaned",
                                   fork_height, len(orphaned))
                    synced_height = fork_height - 1

        # Walk forward and store every new block. Each block must link to the
        # block stored just before it: if the chain moves while we walk, stop
        # and let the next cycle's reorg check reconcile instead of storing
        # blocks from two different branches as one chain.
        try:
            expected_parent = (self.store.block_hash_at(synced_height)
                               if synced_height >= 0 else None)
            for height in range(synced_height + 1, node_height + 1):
                summary = self.reader.block_at_height(height)
                if height > 0 and expected_parent is not None \
                        and summary.prev_hash != expected_parent:
                    raise ChainMovedError(
                        f"block {height} {summary.hash} does not extend stored "
                        f"{expected_parent}; chain changed during sync")
                self.store.record_block(summary)
                expected_parent = summary.hash
                report.new_blocks.append(summary.hash)
                self._emit_new_block(summary)
        except (urllib.error.URLError, OSError, TimeoutError, RPCError, ChainMovedError) as exc:
            self._failures += 1
            logger.warning("sync interrupted at %d new block(s): %s",
                           len(report.new_blocks), exc)
            self.store.record_event("sync_interrupted", str(exc))
            if report.new_blocks:
                # Persist progress so the next cycle resumes after the last good block.
                self.store.set_sync(synced_height + len(report.new_blocks),
                                    report.new_blocks[-1])
            report.ok = False
            report.error = str(exc)
            report.consecutive_failures = self._failures
            return report

        if report.new_blocks or report.reorg_detected or sync is None:
            tip_hash = self.reader.block_hash_at(node_height) \
                if node_height >= 0 else "00" * 32
            self.store.set_sync(node_height, tip_hash)
        report.synced_height_after = node_height
        report.in_sync = True
        return report

    def _find_fork_height(self, from_height: int) -> int:
        """Walk back until stored and node hashes agree again."""
        height = from_height
        while height >= 0:
            stored = self.store.block_hash_at(height)
            node = self.reader.block_hash_at(height)
            if stored == node:
                return height + 1
            height -= 1
        return 0

    # --- monitoring loop ------------------------------------------------------------
    def run(self, iterations: int | None = None) -> None:
        """Poll forever (or iterations times) with backoff on failures.

        RPC outages do not stop the service: it backs off up to
        max_backoff seconds between attempts and resumes on its own.
        """
        backoff = self.poll_interval
        cycles = 0
        while not self._stop.is_set():
            try:
                report = self.sync_once()
            except Exception as exc:  # never let one bad reply kill the monitor
                logger.exception("unexpected error in sync cycle")
                self._failures += 1
                try:
                    self.store.record_event("sync_exception", repr(exc))
                except Exception:
                    logger.exception("could not record sync_exception event")
                report = SyncReport(ok=False, error=repr(exc),
                                    consecutive_failures=self._failures)
            cycles += 1
            if report.ok:
                backoff = self.poll_interval
            else:
                backoff = min(self.max_backoff, backoff * 2)
            if iterations is not None and cycles >= iterations:
                return
            self._stop.wait(backoff)

    def run_event_driven(self, wait_ms: int = 5000, iterations: int | None = None) -> None:
        """Event-driven monitoring: sleep inside the node until the tip changes.

        Uses Core's waitfornewblock long-poll, so an idle chain costs one
        blocked request per wait_ms instead of a poll every poll_interval, and
        a new block is seen as soon as the node connects it. Every wake-up
        still runs the same sync_once() (reorg check, parent-link check,
        persistence), so correctness does not depend on the notification.
        On any RPC failure it falls back to the same exponential backoff as
        run().
        """
        backoff = self.poll_interval
        cycles = 0
        while not self._stop.is_set():
            try:
                report = self.sync_once()
            except Exception as exc:
                logger.exception("unexpected error in sync cycle")
                self._failures += 1
                report = SyncReport(ok=False, error=repr(exc),
                                    consecutive_failures=self._failures)
            cycles += 1
            if iterations is not None and cycles >= iterations:
                return
            if not report.ok:
                backoff = min(self.max_backoff, backoff * 2)
                self._stop.wait(backoff)
                continue
            backoff = self.poll_interval
            try:
                self.rpc.wait_for_new_block(wait_ms)
            except (urllib.error.URLError, OSError, TimeoutError, RPCError) as exc:
                self._failures += 1
                logger.warning("wait-for-block failed: %s", exc)
                self._stop.wait(min(self.max_backoff, self.poll_interval * 2))

    def stop(self) -> None:
        self._stop.set()

    # --- composite views ------------------------------------------------------------
    def status(self) -> dict:
        """Synchronization picture for dashboards and the agent interface."""
        sync = self.store.get_sync()
        info = self.rpc.get_blockchain_info()
        return {
            "node_height": info["blocks"],
            "node_headers": info["headers"],
            "synced_height": sync["last_height"] if sync else -1,
            "synced_hash": sync["last_hash"] if sync else None,
            "in_sync": bool(sync) and sync["last_height"] == info["blocks"],
            "stored_blocks": self.store.count_blocks(),
            "orphaned_blocks": self.store.count_blocks("orphaned"),
            "stored_transactions": self.store.count_transactions(),
            "consecutive_failures": self._failures,
        }

    def record_block_transactions(self, block_hash: str) -> int:
        """Store summaries of every transaction in a block. Returns count."""
        block = self.reader.block_with_txs(block_hash)
        for tx in block["tx"]:
            raw = {
                "vin": tx["vin"], "vout": tx["vout"],
                "size": tx["size"], "vsize": tx["vsize"],
                "weight": tx["weight"], "txid": tx["txid"],
                "confirmations": block["confirmations"],
                "blockhash": block_hash,
            }
            summary = _summarize_tx(tx["txid"], raw, in_mempool=False)
            if "fee" in tx:
                summary.fee_btc = tx["fee"]
            self.store.record_transaction(summary)
        return len(block["tx"])
