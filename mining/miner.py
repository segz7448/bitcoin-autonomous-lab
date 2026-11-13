"""Nonce-scanning CPU miner.

The hot loop hashes 80-byte block headers with double SHA-256 and compares
each digest against the target. hashlib's sha256 is OpenSSL-backed C code, so
this is the fast path; the pure-Python implementation in blockchain.sha256
exists for verification, not throughput.
"""

from __future__ import annotations

import hashlib
import struct
import time
from dataclasses import dataclass

from blockchain.primitives import BlockHeader, bits_to_target


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
    max_nonces: int = 0x100000000,
    max_seconds: float | None = None,
    progress_every: int = 1_000_000,
) -> MiningResult:
    """Scan nonces for a header whose double-SHA-256 meets the target.

    header_prefix is the serialized header up to (excluding) the 4-byte nonce.
    Returns when a nonce is found, the range is exhausted, or max_seconds
    elapses.
    """
    if len(header_prefix) != 76:
        raise ValueError("header prefix must be the first 76 header bytes")
    target = bits_to_target(bits)
    sha256 = hashlib.sha256
    start = time.monotonic()
    deadline = start + max_seconds if max_seconds else None
    hashes = 0
    nonce = start_nonce
    end = min(start_nonce + max_nonces, 0x100000000)
    while nonce < end:
        digest = sha256(sha256(header_prefix + struct.pack("<I", nonce)).digest()).digest()
        hashes += 1
        if int.from_bytes(digest, "little") < target:
            return MiningResult(True, nonce, hashes, time.monotonic() - start)
        nonce += 1
        if hashes % progress_every == 0 and deadline and time.monotonic() > deadline:
            break
    # Final deadline check for small loops that never hit progress_every.
    if deadline and time.monotonic() > deadline:
        return MiningResult(False, None, hashes, time.monotonic() - start)
    return MiningResult(False, None, hashes, time.monotonic() - start)


def mine_header(
    header: BlockHeader,
    max_seconds: float | None = None,
    max_nonces: int = 0x100000000,
) -> MiningResult:
    """Mine an existing header (all fields fixed except nonce)."""
    prefix = header.serialize()[:76]
    return scan_nonces(
        prefix, header.bits, start_nonce=header.nonce,
        max_nonces=max_nonces, max_seconds=max_seconds,
    )


def verify_pow(header: BlockHeader) -> bool:
    """Independent proof-of-work check for a (mined) header."""
    return header.meets_target()
