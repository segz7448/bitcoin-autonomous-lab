"""Bitcoin block primitives: hashing, targets, headers, merkle roots.

Byte-order conventions: hashes are handled in two forms --
  * internal byte order: the raw 32-byte digest, used inside headers/merkles
  * display byte order: the reversed hex string seen in explorers and RPC
    replies (block hash, txid, previousblockhash).
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass


def sha256d_fast(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


_HEX = frozenset("0123456789abcdefABCDEF")


def _strict_hash_hex(hex_hash: str) -> str:
    """Exactly 64 hex digits: no prefix, sign, whitespace or underscores."""
    if not isinstance(hex_hash, str) or len(hex_hash) != 64 or not set(hex_hash) <= _HEX:
        raise ValueError("expected a 64-character hexadecimal hash")
    return hex_hash


def display_to_internal(hex_hash: str) -> bytes:
    return bytes.fromhex(_strict_hash_hex(hex_hash))[::-1]


def internal_to_display(raw: bytes) -> str:
    if len(raw) != 32:
        raise ValueError("expected 32-byte hash")
    return raw[::-1].hex()


# Target arithmetic has exactly one implementation: mining.pow.target, which
# mirrors Bitcoin Core's SetCompact/GetCompact/CheckProofOfWork. The legacy
# helpers below delegate to it (an earlier duplicate used `hash < target`
# and skipped the overflow/zero/negative checks).
def bits_to_target(bits: int) -> int:
    """Decode compact nBits; ValueError if negative, zero or overflowing."""
    from mining.pow.target import bits_to_target as _decode
    return _decode(bits)


def target_to_bits(target: int) -> int:
    """Encode a positive 256-bit target as compact nBits (Core GetCompact)."""
    from mining.pow.target import MAX_UINT256, encode_compact
    if not isinstance(target, int) or not 0 < target <= MAX_UINT256:
        raise ValueError("target must be an integer in [1, 2^256-1]")
    return encode_compact(target)


def hash_meets_target(digest_internal: bytes, target: int) -> bool:
    """Core's rule: the hash (little-endian integer) must be <= target."""
    if len(digest_internal) != 32:
        raise ValueError("digest must be exactly 32 bytes")
    return int.from_bytes(digest_internal, "little") <= target


@dataclass
class BlockHeader:
    version: int
    prev_hash_display: str
    merkle_root_display: str
    timestamp: int
    bits: int
    nonce: int

    def serialize(self) -> bytes:
        return (
            struct.pack("<i", self.version)
            + display_to_internal(self.prev_hash_display)
            + display_to_internal(self.merkle_root_display)
            + struct.pack("<III", self.timestamp, self.bits, self.nonce)
        )

    def hash_display(self) -> str:
        return internal_to_display(self.hash_internal())

    def hash_internal(self) -> bytes:
        return sha256d_fast(self.serialize())

    def target(self) -> int:
        return bits_to_target(self.bits)

    def meets_target(self) -> bool:
        return hash_meets_target(self.hash_internal(), self.target())

    @classmethod
    def from_rpc_block(cls, block: dict) -> "BlockHeader":
        """Rebuild a header from a getblock (verbosity 1) reply.

        The reply carries every header field in display form; genesis has no
        previousblockhash. Recomputing hash_display() from this reconstruction
        must reproduce the node's own "hash" field - that check is the basis
        of independent block verification.
        """
        return cls(
            version=block["version"],
            prev_hash_display=block.get("previousblockhash", "00" * 32),
            merkle_root_display=block["merkleroot"],
            timestamp=block["time"],
            bits=int(block["bits"], 16),
            nonce=block["nonce"],
        )


def merkle_root_checked(txids_internal: list[bytes]) -> tuple[bytes, bool]:
    """Merkle root plus Core's `mutated` flag (CVE-2012-2459).

    Duplicating the last transaction of an odd level yields the same root as
    the honest block, so a block whose tree contains two identical sibling
    hashes at any level is a malleated copy. Core's ComputeMerkleRoot flags
    this and block validation rejects it.
    """
    if not txids_internal:
        raise ValueError("merkle root needs at least one txid")
    layer = list(txids_internal)
    mutated = False
    while len(layer) > 1:
        for i in range(0, len(layer) - 1, 2):
            if layer[i] == layer[i + 1]:
                mutated = True
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [sha256d_fast(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0], mutated


def merkle_root(txids_internal: list[bytes]) -> bytes:
    """Compute the merkle root (internal byte order) of internal-order txids."""
    return merkle_root_checked(txids_internal)[0]


def encode_varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def push_data(data: bytes) -> bytes:
    """Minimal script push for data up to 75 bytes (enough for coinbase)."""
    if len(data) > 75:
        raise ValueError("coinbase scriptSig pushes must be <= 75 bytes")
    return bytes([len(data)]) + data


def script_num_push(n: int) -> bytes:
    """Encode a block height exactly as CScript::operator<<(int64_t) does:
    OP_0 for 0, OP_1..OP_16 for 1-16, otherwise a minimally-encoded
    CScriptNum push. Consensus checks this byte-exactly (BIP34).
    """
    if n == 0:
        return b"\x00"  # OP_0
    if 1 <= n <= 16:
        return bytes([0x50 + n])  # OP_1..OP_16
    abs_n = abs(n)
    out = bytearray()
    while abs_n:
        out.append(abs_n & 0xFF)
        abs_n >>= 8
    if out[-1] & 0x80:
        out.append(0x80 if n < 0 else 0)
    elif n < 0:
        out[-1] |= 0x80
    return push_data(bytes(out))


WITNESS_COMMITMENT_HEADER = bytes.fromhex("aa21a9ed")
