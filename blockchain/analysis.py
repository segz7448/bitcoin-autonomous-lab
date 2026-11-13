"""Block structure analysis: headers, merkle roots, targets, subsidy, fees.

BlockAnalyzer interprets real block data from the node. Every check is
independent: the merkle root is recomputed from the block's own txids and
the proof-of-work target is re-derived from the compact bits field, so the
analysis does not trust the node's bookkeeping - it re-derives it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .primitives import (
    BlockHeader,
    bits_to_target,
    display_to_internal,
    internal_to_display,
    merkle_root,
)
from .reader import BlockchainReader, BlockSummary

COIN = 100_000_000  # satoshis per bitcoin
BASE_SUBSIDY_SATS = 50 * COIN
HALVING_INTERVAL = 210_000


@dataclass
class BlockAnalysis:
    """The full analytical picture of one block."""

    height: int
    hash: str
    # header
    version: int
    prev_hash: str
    merkle_root: str
    time: int
    bits: str
    nonce: int
    # derived consensus quantities
    target: int
    difficulty: float
    # shape
    size: int
    stripped_size: int
    weight: int
    n_tx: int
    confirmations: int
    # economics
    txids: list
    merkle_root_verified: bool
    pow_meets_target: bool
    total_fees_btc: float | None  # None when Core cannot resolve all inputs
    coinbase_value_btc: float
    expected_subsidy_btc: float
    coinbase_within_limit: bool  # coinbase <= subsidy + fees

    def to_dict(self) -> dict:
        return asdict(self)


def expected_subsidy_sats(height: int) -> int:
    """Consensus subsidy schedule: 50 BTC, halving every 210,000 blocks."""
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return BASE_SUBSIDY_SATS >> halvings


def verify_merkle_root(block: dict) -> bool:
    """Recompute the merkle root from a getblock reply's txid list and
    compare it against the block's own merkleroot field."""
    txids = block["tx"]
    if txids and isinstance(txids[0], dict):  # verbosity 2
        txids = [tx["txid"] for tx in txids]
    computed = internal_to_display(
        merkle_root([display_to_internal(t) for t in txids])
    )
    return computed == block["merkleroot"]


class BlockAnalyzer:
    """Interprets blocks retrieved through a BlockchainReader."""

    def __init__(self, reader: BlockchainReader):
        self.reader = reader

    def analyze(self, block_hash: str) -> BlockAnalysis:
        """Full analysis of one block, from real node data."""
        block = self.reader.block_with_txs(block_hash)
        summary = BlockSummary.from_rpc(block)
        header = BlockHeader.from_rpc_block(block)

        txs = block["tx"]
        coinbase = txs[0]
        coinbase_value = sum(out["value"] for out in coinbase["vout"])
        # Core's verbosity-2 reply carries "fee" only for transactions whose
        # inputs it can resolve; report a total only when every non-coinbase
        # transaction has one (mempool/undo data available).
        fees = [tx.get("fee") for tx in txs[1:]]
        total_fees = (
            round(sum(fees), 8) if all(f is not None for f in fees) else None
        )
        expected = expected_subsidy_sats(summary.height) / COIN
        limit = expected + (total_fees or 0.0)
        return BlockAnalysis(
            height=summary.height,
            hash=summary.hash,
            version=summary.version,
            prev_hash=summary.prev_hash,
            merkle_root=summary.merkle_root,
            time=summary.time,
            bits=summary.bits,
            nonce=summary.nonce,
            target=header.target(),
            difficulty=summary.difficulty,
            size=summary.size,
            stripped_size=summary.stripped_size,
            weight=summary.weight,
            n_tx=summary.n_tx,
            confirmations=summary.confirmations,
            txids=[tx["txid"] for tx in txs],
            merkle_root_verified=verify_merkle_root(block),
            pow_meets_target=header.meets_target(),
            total_fees_btc=total_fees,
            coinbase_value_btc=round(coinbase_value, 8),
            expected_subsidy_btc=expected,
            coinbase_within_limit=(coinbase_value <= limit + 1e-8),
        )

    def merkle_proof_check(self, block_hash: str) -> dict:
        """Merkle verification alone, for callers that only need the root."""
        block = self.reader.rpc.get_block(block_hash, 1)
        ok = verify_merkle_root(block)
        return {
            "block_hash": block_hash,
            "height": block["height"],
            "tx_count": len(block["tx"]),
            "merkle_root": block["merkleroot"],
            "verified": ok,
        }
