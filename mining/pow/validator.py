"""Independent Proof-of-Work validation of block headers."""

from __future__ import annotations

from dataclasses import dataclass

from .block_header import BlockHeader
from .target import (POW_LIMIT_MAINNET, check_proof_of_work, decode_compact,
                     digest_to_display, hash_to_int)


@dataclass(frozen=True)
class PowValidation:
    valid: bool
    reason: str           # "ok" or the first failed rule
    hash_display: str
    hash_int: int
    target: int
    bits: int

    def as_dict(self) -> dict:
        return {"valid": self.valid, "reason": self.reason, "hash": self.hash_display,
                "bits": f"{self.bits:08x}", "hash_int_hex": f"{self.hash_int:064x}",
                "target_hex": f"{self.target:064x}"}


def validate_header(header, pow_limit: int = POW_LIMIT_MAINNET) -> PowValidation:
    """Validate PoW for a BlockHeader or exactly-80 raw bytes.

    Reasons: negative-target, overflow-target, zero-target, target-above-limit,
    high-hash (hash integer > target), ok.
    """
    if isinstance(header, (bytes, bytearray)):
        header = BlockHeader.deserialize(header)  # enforces 80 bytes
    digest = header.hash()
    t = decode_compact(header.bits)
    h_int = hash_to_int(digest)
    if t.negative:
        reason = "negative-target"
    elif t.overflow:
        reason = "overflow-target"
    elif t.value == 0:
        reason = "zero-target"
    elif t.value > pow_limit:
        reason = "target-above-limit"
    elif h_int > t.value:
        reason = "high-hash"
    else:
        reason = "ok"
    ok = reason == "ok"
    # The boolean must agree with the single consensus predicate.
    if ok != check_proof_of_work(digest, header.bits, pow_limit):
        raise RuntimeError("validator disagrees with the consensus predicate")
    return PowValidation(ok, reason, digest_to_display(digest), h_int, t.value, header.bits)
