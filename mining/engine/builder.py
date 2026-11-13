"""Candidate block construction for the TASK 005 engine (brief Phase 3).

Builds a complete candidate block from a validated
:class:`~mining.engine.template.MiningTemplate`:

* strict transaction verification - every template transaction's txid (and
  wtxid for witness transactions) is recomputed from the supplied raw data
  and must match, so a misunderstood or corrupt template fails closed;
* dependency- and limit-aware transaction selection;
* BIP34 coinbase with correct subsidy + fee accounting (never above what
  the template permits);
* BIP141 witness commitment, cross-checked against Core's
  ``default_witness_commitment`` when supplied;
* merkle root from the project's own primitives;
* extra-nonce and timestamp variation for Phase 4 nonce-range handling.

The existing single-shot ``mining.template_miner`` flow is untouched; this
module is the engine's reusable, strictly validated counterpart.
"""

from __future__ import annotations

from dataclasses import dataclass

from blockchain.primitives import (
    BlockHeader, display_to_internal, internal_to_display, merkle_root,
    sha256d_fast,
)

from ..block import CoinbaseTx, assemble_block, build_coinbase_tx
from .template import MiningTemplate, TemplateTx, subsidy_at

RESERVED_VALUE = b"\x00" * 32
# Consensus maximum future drift for a block timestamp (2 hours).
MAX_FUTURE_DRIFT = 2 * 60 * 60
# Conservative weight/size reservation for the coinbase transaction when
# enforcing template limits during selection.
_COINBASE_WEIGHT_RESERVE = 1_000
_COINBASE_SIGOP_RESERVE = 100
_COINBASE_SIZE_RESERVE = 200


class BuildError(RuntimeError):
    """A candidate block could not be constructed; fails closed."""


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    if pos >= len(data):
        raise BuildError("truncated transaction (varint)")
    first = data[pos]
    if first < 0xFD:
        return first, pos + 1
    size = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
    if pos + 1 + size > len(data):
        raise BuildError("truncated transaction (varint payload)")
    return int.from_bytes(data[pos + 1:pos + 1 + size], "little"), pos + 1 + size


def split_witness(data: bytes) -> tuple[bytes, bool]:
    """Return (stripped serialization, is_witness) for a raw transaction.

    Re-parses the transaction exactly enough to strip the witness; any
    structural inconsistency fails closed with BuildError.
    """
    if len(data) < 10:
        raise BuildError("transaction too short")
    pos = 4  # version
    is_witness = data[pos:pos + 2] == b"\x00\x01"
    if is_witness:
        pos += 2
    vin_count, pos = _read_varint(data, pos)
    if vin_count == 0:
        raise BuildError("transaction with zero inputs")
    vin_start = pos
    for _ in range(vin_count):
        pos += 36  # prevout hash + index
        script_len, pos = _read_varint(data, pos)
        pos += script_len + 4  # script + sequence
        if pos > len(data):
            raise BuildError("truncated transaction (input)")
    stripped_vins = data[vin_start:pos]
    vout_count, pos = _read_varint(data, pos)
    vout_start = pos
    for _ in range(vout_count):
        pos += 8
        script_len, pos = _read_varint(data, pos)
        pos += script_len
        if pos > len(data):
            raise BuildError("truncated transaction (output)")
    stripped_vouts = data[vout_start:pos]
    if is_witness:
        for _ in range(vin_count):
            item_count, pos = _read_varint(data, pos)
            for _ in range(item_count):
                item_len, pos = _read_varint(data, pos)
                pos += item_len
                if pos > len(data):
                    raise BuildError("truncated transaction (witness)")
    if pos + 4 != len(data):
        raise BuildError("transaction has trailing or missing bytes")
    locktime = data[pos:pos + 4]

    def varint(n: int) -> bytes:
        if n < 0xFD:
            return bytes([n])
        if n <= 0xFFFF:
            return b"\xfd" + n.to_bytes(2, "little")
        if n <= 0xFFFFFFFF:
            return b"\xfe" + n.to_bytes(4, "little")
        return b"\xff" + n.to_bytes(8, "little")

    stripped = (
        data[:4]
        + varint(vin_count) + stripped_vins
        + varint(vout_count) + stripped_vouts
        + locktime
    )
    return stripped, is_witness


def verify_template_tx(tx: TemplateTx) -> None:
    """Recompute txid/wtxid from the supplied data; fail closed on mismatch."""
    stripped, is_witness = split_witness(tx.data)
    txid = internal_to_display(sha256d_fast(stripped))
    if txid != tx.txid:
        raise BuildError(
            f"template transaction txid mismatch: data hashes to {txid}, "
            f"template claims {tx.txid}"
        )
    if is_witness:
        wtxid = internal_to_display(sha256d_fast(tx.data))
        if wtxid != tx.wtxid:
            raise BuildError(
                f"template transaction wtxid mismatch: data hashes to {wtxid}, "
                f"template claims {tx.wtxid}"
            )
    elif tx.has_witness:
        raise BuildError(
            f"template transaction {tx.txid} claims witness data its "
            "serialization does not carry"
        )


def select_transactions(template: MiningTemplate) -> tuple[list[TemplateTx], int]:
    """Pick template transactions in dependency order within block limits.

    Returns (selected, total_fees). A transaction is skipped when one of
    its dependencies was skipped or a reported template limit would be
    exceeded - never silently reordered.
    """
    selected: list[TemplateTx] = []
    included_positions: set[int] = set()
    total_weight = _COINBASE_WEIGHT_RESERVE
    total_sigops = _COINBASE_SIGOP_RESERVE
    total_size = _COINBASE_SIZE_RESERVE
    for position, tx in enumerate(template.transactions, start=1):
        if not set(tx.depends).issubset(included_positions):
            continue
        if (template.weightlimit is not None and tx.weight is not None
                and total_weight + tx.weight > template.weightlimit):
            continue
        if (template.sigoplimit is not None and tx.sigops is not None
                and total_sigops + tx.sigops > template.sigoplimit):
            continue
        if (template.sizelimit is not None
                and total_size + len(tx.data) > template.sizelimit):
            continue
        selected.append(tx)
        included_positions.add(position)
        total_weight += tx.weight or 0
        total_sigops += tx.sigops or 0
        total_size += len(tx.data)
    return selected, sum(tx.fee for tx in selected)


@dataclass
class CandidateBlock:
    """A constructed candidate block, ready for nonce search."""

    header: BlockHeader
    txs: list[bytes]               # full serializations, coinbase first
    coinbase: CoinbaseTx
    height: int
    version: int
    prev_hash_display: str
    bits: int
    coinbase_value: int            # what the coinbase actually pays
    fees: int                      # fees of the selected transactions
    selected_txids: list[str]
    witness_tx_count: int
    payout_script: bytes
    coinbase_flags: str
    witness_commitment: bytes | None
    mintime: int
    extranonce: bytes

    def serialize(self) -> bytes:
        return assemble_block(self.header, self.txs)

    def block_hex(self) -> str:
        return self.serialize().hex()

    def block_hash_display(self) -> str:
        return self.header.hash_display()

    def _rebuild(self, extranonce: bytes, timestamp: int) -> "CandidateBlock":
        return build_candidate_from_parts(
            height=self.height,
            version=self.version,
            prev_hash_display=self.prev_hash_display,
            bits=self.bits,
            timestamp=timestamp,
            mintime=self.mintime,
            coinbase_value=self.coinbase_value,
            payout_script=self.payout_script,
            extranonce=extranonce,
            coinbase_flags=self.coinbase_flags,
            witness_commitment=self.witness_commitment,
            tx_datas=self.txs[1:],
            fees=self.fees,
            selected_txids=self.selected_txids,
            witness_tx_count=self.witness_tx_count,
        )

    def with_extranonce(self, counter: int) -> "CandidateBlock":
        """New candidate whose coinbase carries a bumped extra nonce.

        Changes the coinbase txid and therefore the merkle root, giving the
        nonce search a fresh 32-bit nonce space (brief Phase 4). The witness
        commitment is unaffected: the coinbase slot in the witness merkle
        tree is zero by definition.
        """
        if counter < 0:
            raise BuildError("extranonce counter must be non-negative")
        bumped = self.extranonce + counter.to_bytes(
            max(1, (counter.bit_length() + 7) // 8), "little")
        return self._rebuild(bumped, self.header.timestamp)

    def with_timestamp(self, timestamp: int) -> "CandidateBlock":
        """New candidate with an updated block time (respecting mintime)."""
        if timestamp < self.mintime:
            raise BuildError(
                f"timestamp {timestamp} below template mintime {self.mintime}")
        return self._rebuild(self.extranonce, timestamp)


def build_candidate_from_parts(*, height, version, prev_hash_display, bits,
                               timestamp, mintime, coinbase_value,
                               payout_script, extranonce, coinbase_flags,
                               witness_commitment, tx_datas, fees,
                               selected_txids, witness_tx_count) -> CandidateBlock:
    coinbase = build_coinbase_tx(
        height=height,
        value_sats=coinbase_value,
        script_pubkey=payout_script,
        extranonce=extranonce,
        coinbase_flags=coinbase_flags,
        witness_commitment=witness_commitment,
    )
    txids_internal = [coinbase.txid_internal]
    for data in tx_datas:
        stripped, _ = split_witness(data)
        txids_internal.append(sha256d_fast(stripped))
    header = BlockHeader(
        version=version,
        prev_hash_display=prev_hash_display,
        merkle_root_display=internal_to_display(merkle_root(txids_internal)),
        timestamp=timestamp,
        bits=bits,
        nonce=0,
    )
    return CandidateBlock(
        header=header,
        txs=[coinbase.full] + list(tx_datas),
        coinbase=coinbase,
        height=height,
        version=version,
        prev_hash_display=prev_hash_display,
        bits=bits,
        coinbase_value=coinbase_value,
        fees=fees,
        selected_txids=list(selected_txids),
        witness_tx_count=witness_tx_count,
        payout_script=payout_script,
        coinbase_flags=coinbase_flags,
        witness_commitment=witness_commitment,
        mintime=mintime,
        extranonce=extranonce,
    )


def build_candidate(template: MiningTemplate, payout_script: bytes,
                    extranonce: bytes = b"bal") -> CandidateBlock:
    """Construct a fully verified candidate block from a template."""
    selected, fees = select_transactions(template)
    for tx in selected:
        verify_template_tx(tx)

    value = subsidy_at(template.height) + fees
    if value > template.coinbase_value:
        # Core's own accounting said less is permitted; fail closed.
        raise BuildError(
            f"computed coinbase {value} exceeds template coinbasevalue "
            f"{template.coinbase_value}"
        )

    witness_count = sum(1 for tx in selected if tx.has_witness)
    commitment = None
    if witness_count:
        witness_ids = [b"\x00" * 32]  # coinbase slot is zero by definition
        witness_ids += [display_to_internal(tx.wtxid) for tx in selected]
        commitment = sha256d_fast(merkle_root(witness_ids) + RESERVED_VALUE)
        expected = template.default_witness_commitment
        if expected and commitment.hex() not in expected:
            raise BuildError(
                "computed witness commitment disagrees with Core's "
                "default_witness_commitment; refusing to build"
            )

    timestamp = max(template.curtime, template.mintime)
    return build_candidate_from_parts(
        height=template.height,
        version=template.version,
        prev_hash_display=template.previous_block_hash,
        bits=template.bits,
        timestamp=timestamp,
        mintime=template.mintime,
        coinbase_value=value,
        payout_script=payout_script,
        extranonce=extranonce,
        coinbase_flags=template.coinbase_flags,
        witness_commitment=commitment,
        tx_datas=[tx.data for tx in selected],
        fees=fees,
        selected_txids=[tx.txid for tx in selected],
        witness_tx_count=witness_count,
    )
