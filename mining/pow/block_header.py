"""Strict Bitcoin block header: 80-byte serialize / deserialize / hash.

Layout (all integers little-endian):
  0..4    version (int32, signed)
  4..36   previous block hash  (internal byte order = reversed display hex)
  36..68  merkle root          (internal byte order)
  68..72  time   (uint32)
  72..76  nBits  (uint32)
  76..80  nonce  (uint32)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from .double_sha256 import double_sha256, double_sha256_fast
from .target import digest_to_display, display_to_digest

HEADER_SIZE = 80
_FMT = "<i32s32sIII"


def _u32(name: str, v: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be an integer in [0, 2^32-1], got {v!r}")
    return v


@dataclass(frozen=True)
class BlockHeader:
    """Header with hashes held in INTERNAL byte order (raw digest order)."""

    version: int
    prev_hash: bytes
    merkle_root: bytes
    time: int
    bits: int
    nonce: int

    def __post_init__(self):
        if not isinstance(self.version, int) or isinstance(self.version, bool) \
                or not -(2 ** 31) <= self.version <= 2 ** 31 - 1:
            raise ValueError(f"version must be a signed 32-bit integer, got {self.version!r}")
        for name in ("prev_hash", "merkle_root"):
            v = getattr(self, name)
            if not isinstance(v, (bytes, bytearray)) or len(v) != 32:
                raise ValueError(f"{name} must be exactly 32 bytes")
            object.__setattr__(self, name, bytes(v))
        _u32("time", self.time)
        _u32("bits", self.bits)
        _u32("nonce", self.nonce)

    # -- construction --------------------------------------------------
    @classmethod
    def from_display(cls, version: int, prev_hash_hex: str, merkle_root_hex: str,
                     time: int, bits: int, nonce: int) -> "BlockHeader":
        """Build from RPC-style display hashes (byte-reversed hex)."""
        return cls(version, display_to_digest(prev_hash_hex),
                   display_to_digest(merkle_root_hex), time, bits, nonce)

    @classmethod
    def from_rpc(cls, h: dict) -> "BlockHeader":
        """Build from a getblockheader / getblock (verbosity>=1) reply.

        Genesis has no previousblockhash: it is 32 zero bytes.
        """
        return cls.from_display(
            h["version"], h.get("previousblockhash", "00" * 32), h["merkleroot"],
            h["time"], int(h["bits"], 16), h["nonce"],
        )

    @classmethod
    def deserialize(cls, raw: bytes) -> "BlockHeader":
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError("header must be bytes-like")
        if len(raw) != HEADER_SIZE:
            raise ValueError(f"block header must be exactly {HEADER_SIZE} bytes, got {len(raw)}")
        version, prev, merkle, t, bits, nonce = struct.unpack(_FMT, bytes(raw))
        return cls(version, prev, merkle, t, bits, nonce)

    @classmethod
    def from_hex(cls, hex_str: str) -> "BlockHeader":
        if len(hex_str) != HEADER_SIZE * 2:
            raise ValueError(f"header hex must be {HEADER_SIZE * 2} characters, got {len(hex_str)}")
        return cls.deserialize(bytes.fromhex(hex_str))

    # -- serialization -------------------------------------------------
    def serialize(self) -> bytes:
        raw = struct.pack(_FMT, self.version, self.prev_hash, self.merkle_root,
                          self.time, self.bits, self.nonce)
        assert len(raw) == HEADER_SIZE
        return raw

    def hex(self) -> str:
        return self.serialize().hex()

    def with_nonce(self, nonce: int) -> "BlockHeader":
        return replace(self, nonce=nonce)

    # -- hashing -------------------------------------------------------
    def hash(self) -> bytes:
        """Raw 32-byte double-SHA-256 (internal order), own SHA-256 implementation."""
        return double_sha256(self.serialize())

    def hash_fast(self) -> bytes:
        return double_sha256_fast(self.serialize())

    def hash_display(self) -> str:
        """The displayed block hash (reversed digest, as Core reports it)."""
        return digest_to_display(self.hash())

    @property
    def prev_hash_display(self) -> str:
        return digest_to_display(self.prev_hash)

    @property
    def merkle_root_display(self) -> str:
        return digest_to_display(self.merkle_root)


def hash_header_bytes(raw: bytes, fast: bool = False) -> bytes:
    """Double-SHA-256 of an exactly-80-byte header (validates length)."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != HEADER_SIZE:
        raise ValueError(f"block header must be exactly {HEADER_SIZE} bytes")
    return double_sha256_fast(raw) if fast else double_sha256(raw)
