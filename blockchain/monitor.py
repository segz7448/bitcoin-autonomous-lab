"""Chain monitoring and independent block verification.

ChainMonitor wraps the RPC client with the read-side operations the lab
needs: node/chain snapshots, tip verification, and generate-and-verify
cycles on regtest. Verification is independent: block headers are
reconstructed from the node's own getblock reply fields, the double-SHA-256
block hash is recomputed locally, and the proof-of-work target check is
re-run - the monitor does not take the node's word for its own data.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field

from .primitives import BlockHeader

logger = logging.getLogger(__name__)


@dataclass
class NodeStatus:
    chain: str
    blocks: int
    headers: int
    best_block_hash: str
    difficulty: float
    median_time: int
    verification_progress: float
    mempool_size: int
    connections: int
    node_uptime_s: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BlockVerification:
    height: int
    block_hash: str
    hash_recomputed: bool
    pow_meets_target: bool
    recognized_by_node: bool
    prev_link_ok: bool
    n_tx: int
    confirmations: int

    @property
    def ok(self) -> bool:
        return (self.hash_recomputed and self.pow_meets_target
                and self.recognized_by_node and self.prev_link_ok)

    def to_dict(self) -> dict:
        return asdict(self)


class ChainMonitor:
    def __init__(self, rpc):
        self.rpc = rpc

    # --- status ----------------------------------------------------------
    def snapshot(self) -> NodeStatus:
        """One consistent picture of the node and its chain."""
        info = self.rpc.get_blockchain_info()
        net = self.rpc.get_network_info()
        mempool = self.rpc.get_mempool_info()
        return NodeStatus(
            chain=info["chain"],
            blocks=info["blocks"],
            headers=info["headers"],
            best_block_hash=info["bestblockhash"],
            difficulty=info["difficulty"],
            median_time=info["mediantime"],
            verification_progress=info["verificationprogress"],
            mempool_size=mempool["size"],
            connections=net["connections"],
            node_uptime_s=self.rpc.uptime(),
        )

    # --- verification ------------------------------------------------------
    def verify_block(self, block_hash: str) -> BlockVerification:
        """Independently verify one block the node reports.

        Rebuilds the 80-byte header from the getblock fields, recomputes the
        block hash, checks the hash against the compact target, and confirms
        the previous-block linkage the node reports.
        """
        block = self.rpc.get_block(block_hash)
        header = BlockHeader.from_rpc_block(block)
        recomputed = header.hash_display()
        prev_link_ok = True
        if "previousblockhash" in block:
            prev_link_ok = header.prev_hash_display == block["previousblockhash"]
        return BlockVerification(
            height=block["height"],
            block_hash=block["hash"],
            hash_recomputed=(recomputed == block["hash"]),
            pow_meets_target=header.meets_target(),
            recognized_by_node=True,  # getblock answered for this hash
            prev_link_ok=prev_link_ok,
            n_tx=block["nTx"],
            confirmations=block["confirmations"],
        )

    def verify_tip(self) -> BlockVerification:
        return self.verify_block(self.rpc.get_best_block_hash())

    def wait_for_height(self, height: int, timeout: float = 60.0,
                        poll_s: float = 0.25) -> int:
        """Block until the node's block count reaches height."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            count = self.rpc.get_block_count()
            if count >= height:
                return count
            time.sleep(poll_s)
        raise TimeoutError(f"height {height} not reached within {timeout:.0f}s")

    # --- regtest block generation -------------------------------------------
    def generate_and_verify(self, nblocks: int, address: str) -> list[BlockVerification]:
        """Generate regtest blocks and verify the node recognizes them.

        generatetoaddress is Core's regtest-only mining RPC. For every block
        hash it returns, we cross-check height/hash via getblockhash and run
        the independent header verification above.
        """
        before = self.rpc.get_block_count()
        hashes = self.rpc.generate_to_address(nblocks, address)
        if len(hashes) != nblocks:
            raise RuntimeError(
                f"generatetoaddress returned {len(hashes)} of {nblocks} blocks"
            )
        reports = []
        for i, block_hash in enumerate(hashes):
            expected_height = before + 1 + i
            # The node must map this height back to the same block hash.
            node_hash_at_height = self.rpc.get_block_hash(expected_height)
            if node_hash_at_height != block_hash:
                raise RuntimeError(
                    f"node mismatch at height {expected_height}: "
                    f"{node_hash_at_height} != {block_hash}"
                )
            report = self.verify_block(block_hash)
            reports.append(report)
            logger.info("block %s height=%d verified=%s",
                        block_hash[:16], report.height, report.ok)
        after = self.rpc.get_block_count()
        if after != before + nblocks:
            raise RuntimeError(f"block count moved {before} -> {after}")
        return reports
