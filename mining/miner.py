"""Nonce-scanning CPU miner (thin layer over the PoW engine).

The search itself lives in mining.pow.nonce_search (midstate, exact hash
counts, bounded range, interruption). This module only adapts it to the
older (prefix, bits) call shape, so there is a single consensus-correct
nonce loop in the code base: the hash must be <= target, the target must be
valid (not negative/zero/overflowing), and the nonce range never wraps.
"""

from __future__ import annotations

from dataclasses import dataclass

from blockchain.primitives import BlockHeader
from mining.pow.nonce_search import NONCE_SPACE, NonceSearcher
from mining.pow.target import POW_LIMIT_REGTEST, bits_to_target


@dataclass
class MiningResult:
    found: bool
    nonce: int | None
    hashes: int
    seconds: float

    @property
    def hashrate(self) -> float:
        return self.hashes / self.seconds if self.seconds > 0 else 0.0


def scan_nonces(
    header_prefix: bytes,
    bits: int,
    start_nonce: int = 0,
    max_nonces: int = NONCE_SPACE,
    max_seconds: float | None = None,
) -> MiningResult:
    """Scan nonces for a header whose double-SHA-256 is <= the nBits target.

    header_prefix is the serialized header up to (excluding) the 4-byte nonce.
    Stops when a nonce is found, the range (clamped at 2^32) is exhausted, or
    max_seconds elapses (0 means "stop immediately", not "no limit").
    """
    if len(header_prefix) != 76:
        raise ValueError("header prefix must be the first 76 header bytes")
    if not isinstance(start_nonce, int) or not 0 <= start_nonce <= NONCE_SPACE:
        raise ValueError("start_nonce must be in [0, 2^32]")
    if not isinstance(max_nonces, int) or max_nonces < 0:
        raise ValueError("max_nonces must be a non-negative integer")
    target = bits_to_target(bits)  # ValueError on negative/zero/overflow nBits
    end = min(start_nonce + max_nonces, NONCE_SPACE)
    r = NonceSearcher().search(header_prefix + b"\x00\x00\x00\x00", target,
                               start_nonce, end, max_seconds=max_seconds)
    return MiningResult(r.found, r.nonce, r.hashes_attempted, r.elapsed)


def mine_header(
    header: BlockHeader,
    max_seconds: float | None = None,
    max_nonces: int = NONCE_SPACE,
) -> MiningResult:
    """Mine an existing header (all fields fixed except nonce)."""
    return scan_nonces(header.serialize()[:76], header.bits, start_nonce=header.nonce,
                       max_nonces=max_nonces, max_seconds=max_seconds)


def verify_pow(header: BlockHeader) -> bool:
    """Independent proof-of-work check for a (mined) header."""
    return header.meets_target()


__all__ = ["MiningResult", "scan_nonces", "mine_header", "verify_pow", "POW_LIMIT_REGTEST"]
