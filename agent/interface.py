"""Autonomous agent orchestration interface.

AgentInterface is the stable seam between an orchestrator (today: scripts
and tests; later: the autonomous agent) and the lab's moving parts. Every
operation returns a JSON-serializable dict with an "ok" flag and structured
data or an "error" string - no exceptions cross the boundary, so an agent
can consume results directly.

All operations are regtest-scoped by construction: the underlying
NodeManager refuses to run on any other chain.
"""

from __future__ import annotations

import logging
import os

from blockchain.monitor import ChainMonitor
from node.node_manager import NodeManager

logger = logging.getLogger(__name__)


MAX_BLOCKS_PER_CALL = 1000
_HEX64 = frozenset("0123456789abcdefABCDEF")


def _check_count(name: str, n, hi: int = MAX_BLOCKS_PER_CALL) -> int:
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= hi:
        raise ValueError(f"{name} must be an integer in [1, {hi}], got {n!r}")
    return n


def _check_hash(name: str, v) -> str:
    if not isinstance(v, str) or len(v) != 64 or not set(v) <= _HEX64:
        raise ValueError(f"{name} must be 64 hexadecimal characters")
    return v


class AgentInterface:
    """High-level node/chain operations for an orchestrating agent."""

    def __init__(self, manager: NodeManager | None = None):
        self.manager = manager or NodeManager()

    @staticmethod
    def _ok(**data) -> dict:
        return {"ok": True, **data}

    @staticmethod
    def _err(exc: Exception, **data) -> dict:
        logger.warning("operation failed: %s", exc)
        return {"ok": False, "error": str(exc), **data}

    # --- lifecycle -------------------------------------------------------
    def start_node(self) -> dict:
        try:
            rpc = self.manager.start()
            info = rpc.get_blockchain_info()
            return self._ok(chain=info["chain"], blocks=info["blocks"],
                            rpc_url=self.manager.config.rpc_url)
        except Exception as exc:
            return self._err(exc)

    def stop_node(self) -> dict:
        try:
            self.manager.stop()
            return self._ok()
        except Exception as exc:
            return self._err(exc)

    # --- monitoring ------------------------------------------------------
    def node_status(self) -> dict:
        try:
            monitor = ChainMonitor(self.manager.client())
            return self._ok(status=monitor.snapshot().to_dict())
        except Exception as exc:
            return self._err(exc)

    def verify_tip(self) -> dict:
        try:
            monitor = ChainMonitor(self.manager.client())
            report = monitor.verify_tip()
            return self._ok(verification=report.to_dict(), verified=report.ok)
        except Exception as exc:
            return self._err(exc)

    # --- regtest block production -----------------------------------------
    def ensure_wallet(self, name: str = "bal") -> dict:
        try:
            rpc = self.manager.client()
            if name not in rpc.list_wallets():
                rpc.create_wallet(name)
            address = rpc.get_new_address()
            return self._ok(wallet=name, address=address)
        except Exception as exc:
            return self._err(exc)

    def generate_blocks(self, nblocks: int, address: str | None = None) -> dict:
        """Generate regtest blocks and return per-block verification reports."""
        try:
            _check_count("nblocks", nblocks)
            rpc = self.manager.client()
            if address is None:
                if "bal" not in rpc.list_wallets():
                    rpc.create_wallet("bal")
                address = rpc.get_new_address()
            monitor = ChainMonitor(rpc)
            reports = monitor.generate_and_verify(nblocks, address)
            return self._ok(
                generated=len(reports),
                all_verified=all(r.ok for r in reports),
                blocks=[r.to_dict() for r in reports],
            )
        except Exception as exc:
            return self._err(exc)

    # --- Blockchain Intelligence Engine (TASK 002) -----------------------------
    def _engine(self, db_path: str | None = None):
        from blockchain.service import MonitoringService
        from blockchain.storage import ChainStore
        # Connect to the node first: if it is down, no database handle is
        # opened (and leaked) for a service that can never be returned.
        rpc = self.manager.client()
        store = ChainStore(db_path or self._default_db_path())
        return MonitoringService(rpc, store)

    @staticmethod
    def _default_db_path() -> str:
        return os.path.join(
            os.environ.get("BAL_DATA", ".bal"), "chain-intelligence.db")

    def sync_blockchain(self, db_path: str | None = None) -> dict:
        """Run one monitoring cycle against the persistent store."""
        try:
            with self._engine(db_path) as svc_ctx:
                svc = svc_ctx
                report = svc.sync_once()
                return self._ok(report=report.to_dict())
        except Exception as exc:
            return self._err(exc)

    def blockchain_status(self, db_path: str | None = None) -> dict:
        """Synchronization status: node height vs stored height."""
        try:
            with self._engine(db_path) as svc:
                return self._ok(status=svc.status())
        except Exception as exc:
            return self._err(exc)

    def current_block_height(self) -> dict:
        try:
            rpc = self.manager.client()
            return self._ok(height=rpc.get_block_count())
        except Exception as exc:
            return self._err(exc)

    def latest_block_hash(self) -> dict:
        try:
            rpc = self.manager.client()
            return self._ok(block_hash=rpc.get_best_block_hash())
        except Exception as exc:
            return self._err(exc)

    def latest_blocks(self, n: int = 10) -> dict:
        try:
            from blockchain.reader import BlockchainReader
            _check_count("n", n)
            reader = BlockchainReader(self.manager.client())
            blocks = reader.recent_blocks(n)
            return self._ok(count=len(blocks),
                            blocks=[b.to_dict() for b in blocks])
        except Exception as exc:
            return self._err(exc)

    def analyze_block(self, block_hash: str) -> dict:
        """Full block analysis: header, target, sizes, merkle verification,
        subsidy and fee economics - all derived from real node data."""
        try:
            from blockchain.analysis import BlockAnalyzer
            from blockchain.reader import BlockchainReader
            _check_hash("block_hash", block_hash)
            analyzer = BlockAnalyzer(BlockchainReader(self.manager.client()))
            analysis = analyzer.analyze(block_hash)
            return self._ok(analysis=analysis.to_dict())
        except Exception as exc:
            return self._err(exc)

    def latest_block_tx_count(self) -> dict:
        try:
            rpc = self.manager.client()
            block = rpc.get_block(rpc.get_best_block_hash(), 1)
            return self._ok(block_hash=block["hash"], height=block["height"],
                            n_tx=block["nTx"])
        except Exception as exc:
            return self._err(exc)

    def network_difficulty(self) -> dict:
        try:
            rpc = self.manager.client()
            info = rpc.get_blockchain_info()
            return self._ok(difficulty=info["difficulty"],
                            chain=info["chain"],
                            best_block_hash=info["bestblockhash"])
        except Exception as exc:
            return self._err(exc)

    def mempool_status(self) -> dict:
        """What is happening in the mempool right now."""
        try:
            from blockchain.transactions import TransactionIntelligence
            txs = TransactionIntelligence(self.manager.client())
            return self._ok(mempool=txs.mempool_status().to_dict())
        except Exception as exc:
            return self._err(exc)

    def get_transaction(self, txid: str) -> dict:
        """Decoded transaction inspection, or an explicit unavailable result."""
        try:
            from blockchain.transactions import TransactionIntelligence
            _check_hash("txid", txid)
            txs = TransactionIntelligence(self.manager.client())
            return self._ok(transaction=txs.get_transaction(txid).to_dict())
        except Exception as exc:
            return self._err(exc)

    def has_new_block(self, db_path: str | None = None) -> dict:
        """Has a new block been discovered since the last stored sync?"""
        try:
            with self._engine(db_path) as svc:
                report = svc.sync_once()
                return self._ok(
                    new_block=bool(report.new_blocks) or report.reorg_detected,
                    report=report.to_dict(),
                )
        except Exception as exc:
            return self._err(exc)
