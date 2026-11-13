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
from typing import Any

from blockchain.monitor import ChainMonitor
from node.node_manager import NodeManager

logger = logging.getLogger(__name__)


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
