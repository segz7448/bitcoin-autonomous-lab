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
    display_to_internal,
    internal_to_display,
    merkle_root_checked,
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
    root, mutated = merkle_root_checked([display_to_internal(t) for t in txids])
    # A mutated tree (duplicate sibling hashes, CVE-2012-2459) reproduces
    # the honest root with a different tx list; Core rejects such blocks.
    return (not mutated) and internal_to_display(root) == block["merkleroot"]


def btc_to_sats(value) -> int:
    """Exact satoshi count for a JSON-RPC BTC amount (8-decimal float/str)."""
    from decimal import Decimal
    return int((Decimal(str(value)) * COIN).to_integral_value())


def coinbase_within_limit(coinbase_btc, subsidy_sats: int, fees_btc) -> bool:
    """Consensus: coinbase output total <= subsidy + fees, to the satoshi.

    fees_btc is None when fees are unknown; then only the subsidy is
    provable and the comparison uses it alone.
    """
    limit = subsidy_sats + (btc_to_sats(fees_btc) if fees_btc is not None else 0)
    return btc_to_sats(coinbase_btc) <= limit


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
        coinbase_sats = sum(btc_to_sats(out["value"]) for out in coinbase["vout"])
        coinbase_value = coinbase_sats / COIN
        # Core's verbosity-2 reply carries "fee" only for transactions whose
        # inputs it can resolve; report a total only when every non-coinbase
        # transaction has one (mempool/undo data available).
        fees = [tx.get("fee") for tx in txs[1:]]
        total_fees = (
            sum(btc_to_sats(f) for f in fees) / COIN if all(f is not None for f in fees) else None
        )
        subsidy_sats = expected_subsidy_sats(summary.height)
        expected = subsidy_sats / COIN
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
            coinbase_within_limit=coinbase_within_limit(coinbase_value, subsidy_sats, total_fees),
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
