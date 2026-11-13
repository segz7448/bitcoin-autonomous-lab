"""Coinbase transaction construction and block assembly.

Shared primitives (headers, targets, merkle roots, script pushes) live in
blockchain.primitives and are re-exported here so mining code has a single
import surface. Consensus-relevant details:

  * BIP34: the coinbase scriptSig starts with the block height encoded
    exactly as CScript encodes it (see script_num_push).
  * BIP141: when any transaction in the block carries witness data, the
    coinbase commits to the witness merkle root in an OP_RETURN output and
    its input gains a witness stack holding the 32-byte reserved value.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from blockchain.primitives import (  # noqa: F401  (re-exported)
    WITNESS_COMMITMENT_HEADER, BlockHeader, bits_to_target,
    display_to_internal, encode_varint, hash_meets_target,
    internal_to_display, merkle_root, push_data, script_num_push,
    sha256d_fast, target_to_bits,
)


@dataclass
class CoinbaseTx:
    """A coinbase transaction in its two serializations.

    stripped: no-witness serialization. txid = sha256d(stripped), which is
        what the merkle tree commits to.
    full: serialization included in the block (identical to stripped unless
        a witness commitment is present).
    """
    stripped: bytes
    full: bytes

    @property
    def txid_internal(self) -> bytes:
        return sha256d_fast(self.stripped)


def build_coinbase_tx(
    height: int,
    value_sats: int,
    script_pubkey: bytes,
    extranonce: bytes = b"bal",
    coinbase_flags: str = "",
    witness_commitment: bytes | None = None,
    reserved_value: bytes = b"\x00" * 32,
) -> CoinbaseTx:
    """Serialize a coinbase transaction (see module docstring for BIP34/141)."""
    if witness_commitment is not None and len(witness_commitment) != 32:
        raise ValueError("witness commitment must be 32 bytes")
    if len(reserved_value) != 32:
        raise ValueError("witness reserved value must be 32 bytes")

    script_sig = script_num_push(height) + extranonce
    if coinbase_flags:
        script_sig += bytes.fromhex(coinbase_flags)
    # Consensus rule (CheckTransaction): coinbase scriptSig must be 2-100 bytes.
    if not 2 <= len(script_sig) <= 100:
        raise ValueError(
            f"coinbase scriptSig must be 2-100 bytes, got {len(script_sig)}"
        )

    vin = b"\x00" * 32 + struct.pack("<I", 0xFFFFFFFF)  # null prevout
    vin += encode_varint(len(script_sig)) + script_sig
    vin += struct.pack("<I", 0xFFFFFFFF)  # sequence

    outputs = [(value_sats, script_pubkey)]
    if witness_commitment is not None:
        commit_script = (
            b"\x6a"  # OP_RETURN
            + push_data(WITNESS_COMMITMENT_HEADER + witness_commitment)
        )
        outputs.append((0, commit_script))
    vout = encode_varint(len(outputs))
    for value, script in outputs:
        vout += struct.pack("<Q", value) + encode_varint(len(script)) + script

    version = struct.pack("<i", 2)
    locktime = struct.pack("<I", 0)
    stripped = version + encode_varint(1) + vin + vout + locktime
    if witness_commitment is None:
        return CoinbaseTx(stripped=stripped, full=stripped)
    witness = encode_varint(1) + push_data(reserved_value)  # one input, one item
    full = version + b"\x00\x01" + encode_varint(1) + vin + vout + witness + locktime
    return CoinbaseTx(stripped=stripped, full=full)


def assemble_block(header: BlockHeader, txs: list[bytes]) -> bytes:
    return header.serialize() + encode_varint(len(txs)) + b"".join(txs)
