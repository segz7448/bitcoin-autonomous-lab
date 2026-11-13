"""Typed read access to the blockchain through Bitcoin Core RPC.

BlockchainReader is the low-level query layer of the Intelligence Engine.
It maps the monitoring RPC surface (getblockchaininfo, getblockcount,
getbestblockhash, getblockhash, getblock, getblockheader, getchaintips)
onto typed results. It keeps no state of its own: persistence lives in
blockchain/storage.py and monitoring logic in blockchain/service.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .primitives import bits_to_target


@dataclass
class BlockSummary:
    """The block metadata the Intelligence Engine tracks."""

    height: int
    hash: str
    prev_hash: str
    merkle_root: str
    time: int
    median_time: int
    version: int
    bits: str
    nonce: int
    difficulty: float
    size: int
    stripped_size: int
    weight: int
    n_tx: int
    confirmations: int

    @classmethod
    def from_rpc(cls, block: dict) -> "BlockSummary":
        return cls(
            height=block["height"],
            hash=block["hash"],
            prev_hash=block.get("previousblockhash", "00" * 32),
            merkle_root=block["merkleroot"],
            time=block["time"],
            median_time=block["mediantime"],
            version=block["version"],
            bits=block["bits"],
            nonce=block["nonce"],
            difficulty=block["difficulty"],
            size=block["size"],
            stripped_size=block["strippedsize"],
            weight=block["weight"],
            n_tx=block["nTx"],
            confirmations=block["confirmations"],
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HeaderInfo:
    """A block header exactly as getblockheader reports it."""

    hash: str
    height: int
    version: int
    prev_hash: str
    merkle_root: str
    time: int
    median_time: int
    bits: str
    nonce: int
    difficulty: float
    confirmations: int
    next_hash: str | None

    @classmethod
    def from_rpc(cls, header: dict) -> "HeaderInfo":
        return cls(
            hash=header["hash"],
            height=header["height"],
            version=header["version"],
            prev_hash=header.get("previousblockhash", "00" * 32),
            merkle_root=header["merkleroot"],
            time=header["time"],
            median_time=header["mediantime"],
            bits=header["bits"],
            nonce=header["nonce"],
            difficulty=header["difficulty"],
            confirmations=header["confirmations"],
            next_hash=header.get("nextblockhash"),
        )

    def target(self) -> int:
        return bits_to_target(int(self.bits, 16))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChainTip:
    """One tip from getchaintips: a branch the node knows about."""

    height: int
    hash: str
    branchlen: int
    status: str  # active, valid-fork, valid-headers, headers-only, invalid

    @classmethod
    def from_rpc(cls, tip: dict) -> "ChainTip":
        return cls(
            height=tip["height"],
            hash=tip["hash"],
            branchlen=tip["branchlen"],
            status=tip["status"],
        )

    def to_dict(self) -> dict:
        return asdict(self)


class BlockchainReader:
    """Structured blockchain queries over a BitcoinRPC client."""

    def __init__(self, rpc):
        self.rpc = rpc

    # --- height / tip ------------------------------------------------------
    def chain_height(self) -> int:
        """Current height of the most-work chain (getblockcount)."""
        return self.rpc.get_block_count()

    def best_block_hash(self) -> str:
        return self.rpc.get_best_block_hash()

    def block_hash_at(self, height: int) -> str:
        return self.rpc.get_block_hash(height)

    # --- blocks -------------------------------------------------------------
    def block_summary(self, block_hash: str) -> BlockSummary:
        """Full metadata for one block (getblock verbosity 1)."""
        return BlockSummary.from_rpc(self.rpc.get_block(block_hash, 1))

    def block_at_height(self, height: int) -> BlockSummary:
        return self.block_summary(self.block_hash_at(height))

    def block_txids(self, block_hash: str) -> list[str]:
        """Transaction IDs in block order (getblock verbosity 1)."""
        return list(self.rpc.get_block(block_hash, 1)["tx"])

    def block_with_txs(self, block_hash: str) -> dict:
        """Block with fully decoded transactions (getblock verbosity 2).

        Core computes a per-transaction fee for every non-coinbase input it
        can resolve, which the block-analysis module uses for fee totals.
        """
        return self.rpc.get_block(block_hash, 2)

    def header(self, block_hash: str) -> HeaderInfo:
        """A block header without its transactions (getblockheader)."""
        return HeaderInfo.from_rpc(self.rpc.get_block_header(block_hash))

    # --- chain shape ---------------------------------------------------------
    def chain_tips(self) -> list[ChainTip]:
        """All chain tips the node knows, including stale forks."""
        return [ChainTip.from_rpc(t) for t in self.rpc.get_chain_tips()]

    def recent_blocks(self, n: int) -> list[BlockSummary]:
        """Summaries of the n most recent blocks, newest first."""
        height = self.chain_height()
        start = max(0, height - n + 1)
        return [self.block_at_height(h) for h in range(height, start - 1, -1)]
