"""Difficulty and work arithmetic (Core's GetDifficulty / GetBlockProof)."""

from __future__ import annotations

from .target import MAX_UINT256, bits_to_target


def difficulty_from_bits(bits: int) -> float:
    """Core's GetDifficulty(): difficulty relative to mainnet minimum (0x1d00ffff)."""
    shift = (bits >> 24) & 0xFF
    mantissa = bits & 0x00FFFFFF
    if mantissa == 0:
        raise ValueError("nBits mantissa is zero")
    d = 0x0000FFFF / mantissa
    while shift < 29:
        d *= 256.0
        shift += 1
    while shift > 29:
        d /= 256.0
        shift -= 1
    return d


def difficulty_from_target(target: int) -> float:
    """Exact-ratio difficulty: (mainnet max target) / target."""
    if not 0 < target <= MAX_UINT256:
        raise ValueError("target out of range")
    return 0x00000000FFFF0000000000000000000000000000000000000000000000000000 / target


def expected_hashes(target: int) -> float:
    """Expected number of double-SHA-256 attempts to meet target (2^256 / (target+1))."""
    if not 0 < target <= MAX_UINT256:
        raise ValueError("target out of range")
    return (1 << 256) / (target + 1)


def block_work(bits: int) -> int:
    """Work of one block: floor(2^256 / (target+1)), computed as Core does."""
    target = bits_to_target(bits)
    return ((~target) & MAX_UINT256) // (target + 1) + 1
