"""Compact difficulty-target (nBits) handling, mirroring Bitcoin Core.

Reference behaviour: arith_uint256::SetCompact / GetCompact and
pow.cpp CheckProofOfWork. Byte order rules used throughout:

  * A hash is the raw 32-byte double-SHA-256 digest ("internal order").
  * Proof-of-Work interprets that digest as a LITTLE-ENDIAN 256-bit
    integer. The displayed block hash is the digest reversed (big-endian
    hex), which is why a valid displayed hash has leading zeros.
  * Never compare the displayed hex string lexicographically as the
    integer unless it has been parsed as big-endian from the REVERSED
    digest; hash_to_int() below is the single place that does this.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_UINT256 = (1 << 256) - 1

# Consensus proof-of-work limits (chainparams.cpp).
POW_LIMIT_MAINNET = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
POW_LIMIT_REGTEST = 0x7FFFFF0000000000000000000000000000000000000000000000000000000000
POW_LIMITS = {"main": POW_LIMIT_MAINNET, "regtest": POW_LIMIT_REGTEST}
BITS_MAINNET_LIMIT = 0x1D00FFFF
BITS_REGTEST_LIMIT = 0x207FFFFF


@dataclass(frozen=True)
class CompactTarget:
    """Result of decoding nBits, with Core's three failure flags."""

    value: int
    negative: bool
    overflow: bool

    @property
    def zero(self) -> bool:
        return self.value == 0

    @property
    def valid(self) -> bool:
        """True when the decoded target is usable (not negative/zero/overflow)."""
        return not (self.negative or self.overflow or self.value == 0)


def _check_uint32(name: str, v: int) -> None:
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be an integer in [0, 2^32-1], got {v!r}")


def decode_compact(bits: int) -> CompactTarget:
    """Decode nBits exactly as arith_uint256::SetCompact does."""
    _check_uint32("nBits", bits)
    size = bits >> 24
    word = bits & 0x007FFFFF
    if size <= 3:
        word >>= 8 * (3 - size)
        value = word
    else:
        value = word << (8 * (size - 3))
    negative = word != 0 and (bits & 0x00800000) != 0
    overflow = word != 0 and (
        size > 34 or (word > 0xFF and size > 33) or (word > 0xFFFF and size > 32)
    )
    if overflow:
        # Core leaves the (truncated) value meaningless; report the flag and
        # clamp so callers cannot accidentally use an out-of-range integer.
        value &= MAX_UINT256
    return CompactTarget(value=value, negative=negative, overflow=overflow)


def bits_to_target(bits: int) -> int:
    """Return the target for nBits, raising ValueError if it is invalid."""
    t = decode_compact(bits)
    if t.negative:
        raise ValueError(f"nBits {bits:#010x} encodes a negative target")
    if t.overflow:
        raise ValueError(f"nBits {bits:#010x} overflows 256 bits")
    if t.value == 0:
        raise ValueError(f"nBits {bits:#010x} encodes a zero target")
    return t.value


def encode_compact(target: int, negative: bool = False) -> int:
    """Encode a 256-bit integer as nBits exactly as GetCompact does."""
    if not isinstance(target, int) or isinstance(target, bool):
        raise ValueError("target must be an integer")
    if not 0 <= target <= MAX_UINT256:
        raise ValueError("target must be in [0, 2^256-1]")
    size = (target.bit_length() + 7) // 8
    if size <= 3:
        compact = (target << (8 * (3 - size))) & 0xFFFFFFFF
    else:
        compact = (target >> (8 * (size - 3))) & 0xFFFFFFFF
    if compact & 0x00800000:
        compact >>= 8
        size += 1
    compact |= size << 24
    if negative and (compact & 0x007FFFFF):
        compact |= 0x00800000
    return compact


def hash_to_int(digest: bytes) -> int:
    """Interpret a raw 32-byte digest as Bitcoin's PoW integer (little-endian)."""
    if not isinstance(digest, (bytes, bytearray)) or len(digest) != 32:
        raise ValueError("digest must be exactly 32 bytes")
    return int.from_bytes(digest, "little")


def display_hash_to_int(display_hex: str) -> int:
    """Integer value of a displayed (byte-reversed, big-endian) block hash."""
    if len(display_hex) != 64:
        raise ValueError("displayed hash must be 64 hex characters")
    return int(display_hex, 16)


def digest_to_display(digest: bytes) -> str:
    if len(digest) != 32:
        raise ValueError("digest must be exactly 32 bytes")
    return bytes(digest)[::-1].hex()


def display_to_digest(display_hex: str) -> bytes:
    raw = bytes.fromhex(display_hex)
    if len(raw) != 32:
        raise ValueError("displayed hash must be 32 bytes")
    return raw[::-1]


def check_proof_of_work(digest: bytes, bits: int, pow_limit: int = POW_LIMIT_MAINNET) -> bool:
    """Mirror of CheckProofOfWork(hash, nBits, params).

    False if nBits is negative, zero, overflowing or easier than pow_limit,
    or if hash_integer > target. Equality passes (hash <= target).
    """
    t = decode_compact(bits)
    if not t.valid or t.value > pow_limit:
        return False
    return hash_to_int(digest) <= t.value
