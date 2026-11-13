"""Transaction intelligence: inspection, fees, confirmations, mempool.

Every result comes from real RPC replies (getrawtransaction,
decoderawtransaction, getmempoolinfo, getrawmempool, getmempoolentry).
Fees are reported only where the required data is actually available -
a mempool entry or a block the node can undo; a bare getrawtransaction
against a node without txindex returns "available": False instead of a
fabricated answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from node.rpc_client import RPCError

TX_NOT_FOUND_CODES = {-5}  # "No such mempool/blockchain transaction"


@dataclass
class TxInput:
    txid: str | None  # None for coinbase inputs
    vout: int | None
    is_coinbase: bool
    sequence: int


@dataclass
class TxOutput:
    n: int
    value_btc: float
    script_type: str
    address: str | None


@dataclass
class TxSummary:
    txid: str
    available: bool
    unavailable_reason: str | None = None
    size: int = 0
    vsize: int = 0
    weight: int = 0
    n_inputs: int = 0
    n_outputs: int = 0
    is_coinbase: bool = False
    value_out_btc: float = 0.0
    fee_btc: float | None = None  # only when the node can resolve inputs
    confirmations: int = 0
    block_hash: str | None = None
    in_mempool: bool = False
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MempoolStatus:
    size: int
    bytes: int
    usage: int
    total_fee_btc: float
    min_fee_rate: float  # BTC/kvB relay threshold
    txids: list

    def to_dict(self) -> dict:
        return asdict(self)


def _summarize_tx(txid: str, raw: dict, in_mempool: bool) -> TxSummary:
    vin = raw["vin"]
    vout = raw["vout"]
    is_coinbase = bool(vin) and "coinbase" in vin[0]
    return TxSummary(
        txid=txid,
        available=True,
        size=raw["size"],
        vsize=raw["vsize"],
        weight=raw["weight"],
        n_inputs=len(vin),
        n_outputs=len(vout),
        is_coinbase=is_coinbase,
        value_out_btc=round(sum(o["value"] for o in vout), 8),
        confirmations=raw.get("confirmations", 0),
        block_hash=raw.get("blockhash"),
        in_mempool=in_mempool,
        inputs=[
            asdict(TxInput(
                txid=i.get("txid"),
                vout=i.get("vout"),
                is_coinbase="coinbase" in i,
                sequence=i["sequence"],
            )) for i in vin
        ],
        outputs=[
            asdict(TxOutput(
                n=o["n"],
                value_btc=o["value"],
                script_type=o["scriptPubKey"]["type"],
                address=o["scriptPubKey"].get("address"),
            )) for o in vout
        ],
    )


class TransactionIntelligence:
    """Transaction and mempool queries over a BitcoinRPC client."""

    def __init__(self, rpc):
        self.rpc = rpc

    # --- single transactions -------------------------------------------------
    def get_transaction(self, txid: str) -> TxSummary:
        """Decoded transaction by txid, or an explicit unavailable result.

        A node without txindex only serves mempool transactions and ones in
        blocks it still has undo data for; anything else is reported
        unavailable with the node's own reason, never fabricated.
        """
        try:
            raw = self.rpc.get_raw_transaction(txid, True)
        except RPCError as exc:
            if exc.code in TX_NOT_FOUND_CODES:
                return TxSummary(
                    txid=txid, available=False,
                    unavailable_reason=exc.message,
                )
            raise
        return _summarize_tx(txid, raw, in_mempool="blockhash" not in raw)

    def decode_raw_transaction(self, tx_hex: str) -> TxSummary:
        """Decode a serialized transaction without any node lookup."""
        raw = self.rpc.decode_raw_transaction(tx_hex)
        return _summarize_tx(raw["txid"], raw, in_mempool=False)

    # --- mempool -----------------------------------------------------------
    def mempool_status(self, verbose: bool = True) -> MempoolStatus:
        """Current mempool picture: counts, bytes, fees, txids."""
        info = self.rpc.get_mempool_info()
        txids = self.rpc.get_raw_mempool(False) if verbose else []
        return MempoolStatus(
            size=info["size"],
            bytes=info["bytes"],
            usage=info["usage"],
            total_fee_btc=info["total_fee"],
            min_fee_rate=info["mempoolminfee"],
            txids=txids,
        )

    def mempool_entry(self, txid: str) -> dict:
        """One mempool entry: fee, size, ancestor data, arrival time."""
        entry = self.rpc.get_mempool_entry(txid)
        return {
            "txid": txid,
            "vsize": entry["vsize"],
            "weight": entry["weight"],
            "fee_btc": entry["fees"]["base"],
            "modified_fee_btc": entry["fees"]["modified"],
            "time": entry["time"],
            "height": entry["height"],
            "ancestor_count": entry["ancestorcount"],
            "depends": entry["depends"],
        }

    def detect_new_mempool_txs(self, known_txids: set) -> list:
        """Transactions in the mempool that are not in known_txids.

        Returns getmempoolentry-shaped summaries for the new arrivals.
        """
        current = set(self.rpc.get_raw_mempool(False))
        new = current - set(known_txids)
        return [self.mempool_entry(t) for t in sorted(new)]

    # --- fees --------------------------------------------------------------
    def transaction_fee(self, txid: str) -> dict:
        """Fee for a transaction, from the source that actually has it.

        Mempool transactions carry their fee in getmempoolentry. Confirmed
        transactions have no fee field in getrawtransaction; their inputs
        are only resolvable with txindex, so the result is explicit about
        what is and is not available.
        """
        try:
            entry = self.mempool_entry(txid)
            return {
                "txid": txid, "fee_btc": entry["fee_btc"],
                "fee_rate_btc_per_kvb": round(
                    entry["fee_btc"] / entry["vsize"] * 1000, 8),
                "source": "mempool",
            }
        except RPCError as exc:
            if exc.code not in TX_NOT_FOUND_CODES:
                raise
        raw = self.get_transaction(txid)
        if not raw.available:
            return {"txid": txid, "fee_btc": None,
                    "source": "unavailable", "reason": raw.unavailable_reason}
        return {
            "txid": txid, "fee_btc": None, "source": "confirmed",
            "reason": "confirmed transaction; fee requires txindex or "
                      "block verbosity-2 undo data",
        }
