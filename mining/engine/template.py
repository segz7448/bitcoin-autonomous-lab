"""Mining-work acquisition for the TASK 005 engine (brief Phase 2).

Fetches ``getblocktemplate`` replies from Bitcoin Core, validates them into
a strictly checked :class:`MiningTemplate`, and detects staleness (tip
change or template expiry). Everything fails closed: a template the engine
does not fully understand is rejected, never guessed at. The manager
refuses every chain other than regtest.

Covered template fields (per the brief): previous-block hash, version,
height, compact target (bits), curtime, mintime, transactions with fees
and dependencies, coinbase value, consensus rules, SegWit data and the
default witness commitment.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from mining.pow.target import POW_LIMIT_REGTEST, bits_to_target

_HEX = frozenset("0123456789abcdef")
MAX_MONEY = 21_000_000 * 100_000_000


class TemplateError(RuntimeError):
    """A getblocktemplate reply failed validation; the work is unusable."""


def subsidy_at(height: int) -> int:
    """Block subsidy in satoshis at ``height`` (Bitcoin halving schedule)."""
    halvings = height // 210_000
    if halvings >= 64:
        return 0
    return (50 * 100_000_000) >> halvings


def _strict_hex(value, name: str, length: int | None = None) -> str:
    if not isinstance(value, str):
        raise TemplateError(f"{name} must be a hex string, got {type(value).__name__}")
    lowered = value.lower()
    if length is not None and len(lowered) != length:
        raise TemplateError(f"{name} must be {length} hex chars, got {len(lowered)}")
    if len(lowered) % 2:
        raise TemplateError(f"{name} must have an even number of hex chars")
    if any(c not in _HEX for c in lowered):
        raise TemplateError(f"{name} contains non-hex characters")
    return lowered


def _require(reply: dict, name: str):
    if name not in reply:
        raise TemplateError(f"template missing required field {name!r}")
    return reply[name]


def _require_int(reply: dict, name: str, minimum: int | None = None,
                 maximum: int | None = None) -> int:
    value = _require(reply, name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TemplateError(f"{name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise TemplateError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise TemplateError(f"{name} must be <= {maximum}, got {value}")
    return value


@dataclass(frozen=True)
class TemplateTx:
    """One transaction offered by the template.

    ``depends`` holds 1-based positions of earlier template transactions
    that must appear first, exactly as getblocktemplate reports them.
    ``fee`` is required: the engine never guesses fee accounting.
    """

    txid: str            # display byte order
    wtxid: str           # display byte order; equals txid for non-witness
    data: bytes          # full serialization as supplied by Core
    fee: int             # satoshis
    depends: tuple[int, ...]
    sigops: int | None
    weight: int | None

    @property
    def has_witness(self) -> bool:
        return self.wtxid != self.txid


@dataclass(frozen=True)
class MiningTemplate:
    """A validated getblocktemplate reply."""

    previous_block_hash: str       # display byte order
    version: int                   # signed int32 range
    height: int
    bits: int
    target: int                    # decoded from bits
    curtime: int
    mintime: int
    transactions: tuple[TemplateTx, ...]
    coinbase_value: int            # satoshis Core allows the coinbase to pay
    coinbase_flags: str            # coinbaseaux.flags hex ("" when absent)
    rules: tuple[str, ...]
    capabilities: frozenset[str]
    default_witness_commitment: str | None
    longpollid: str | None
    expires: int                   # seconds the work stays valid (BIP22)
    sigoplimit: int | None
    sizelimit: int | None
    weightlimit: int | None
    mutable: tuple[str, ...]
    acquired_at: float = field(default=0.0)

    @property
    def total_fees(self) -> int:
        return sum(tx.fee for tx in self.transactions)

    @property
    def tx_count(self) -> int:
        return len(self.transactions)

    @property
    def has_witness_transactions(self) -> bool:
        return any(tx.has_witness for tx in self.transactions)

    @property
    def expires_at(self) -> float:
        return self.curtime + self.expires

    @property
    def total_tx_weight(self) -> int | None:
        """Sum of template transaction weights, None when unreported."""
        weights = [tx.weight for tx in self.transactions]
        if any(w is None for w in weights):
            return None
        return sum(weights)


def parse_template(reply: dict, pow_limit: int = POW_LIMIT_REGTEST) -> MiningTemplate:
    """Validate a getblocktemplate reply; raise TemplateError on any doubt."""
    if not isinstance(reply, dict):
        raise TemplateError("getblocktemplate reply is not an object")

    previous = _strict_hex(_require(reply, "previousblockhash"),
                           "previousblockhash", 64)
    version = _require_int(reply, "version", minimum=-(2 ** 31),
                           maximum=2 ** 31 - 1)
    height = _require_int(reply, "height", minimum=1)

    bits_hex = _strict_hex(_require(reply, "bits"), "bits", 8)
    bits = int(bits_hex, 16)
    try:
        target = bits_to_target(bits)
    except ValueError as exc:
        raise TemplateError(f"invalid compact target: {exc}") from exc
    if target > pow_limit:
        raise TemplateError(
            "template target is above the regtest proof-of-work limit; "
            "refusing out-of-scope work"
        )

    curtime = _require_int(reply, "curtime", minimum=0)
    mintime = _require_int(reply, "mintime", minimum=0)
    if mintime > curtime:
        raise TemplateError(f"mintime {mintime} is after curtime {curtime}")

    coinbase_value = _require_int(reply, "coinbasevalue", minimum=1,
                                  maximum=MAX_MONEY)

    raw_txs = _require(reply, "transactions")
    if not isinstance(raw_txs, list):
        raise TemplateError("transactions must be a list")
    txs: list[TemplateTx] = []
    for position, raw in enumerate(raw_txs, start=1):
        if not isinstance(raw, dict):
            raise TemplateError(f"transaction #{position} is not an object")
        txid = _strict_hex(_require(raw, "txid"), f"tx #{position} txid", 64)
        wtxid = raw.get("hash") or txid
        wtxid = _strict_hex(wtxid, f"tx #{position} wtxid", 64)
        data_hex = _strict_hex(_require(raw, "data"), f"tx #{position} data")
        if not data_hex:
            raise TemplateError(f"tx #{position} has empty data")
        fee = _require_int(raw, "fee", minimum=0)
        depends_raw = raw.get("depends", [])
        if not isinstance(depends_raw, list):
            raise TemplateError(f"tx #{position} depends must be a list")
        depends = []
        for dep in depends_raw:
            if not isinstance(dep, int) or isinstance(dep, bool):
                raise TemplateError(f"tx #{position} depends entry {dep!r} is not an integer")
            # Core lists transactions so dependencies come first; the index
            # is 1-based into the template list.
            if not 1 <= dep < position:
                raise TemplateError(
                    f"tx #{position} depends on position {dep}; "
                    "dependency must refer to an earlier template transaction"
                )
            depends.append(dep)
        sigops = raw.get("sigops")
        weight = raw.get("weight")
        for name, value in (("sigops", sigops), ("weight", weight)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise TemplateError(f"tx #{position} {name} must be a non-negative integer")
        txs.append(TemplateTx(
            txid=txid, wtxid=wtxid, data=bytes.fromhex(data_hex), fee=fee,
            depends=tuple(depends), sigops=sigops, weight=weight,
        ))

    # The coinbase may never pay more than subsidy + included fees. Core
    # computes coinbasevalue the same way; a mismatch means the template is
    # misunderstood, so fail closed.
    permitted = subsidy_at(height) + sum(tx.fee for tx in txs)
    if coinbase_value > permitted:
        raise TemplateError(
            f"coinbasevalue {coinbase_value} exceeds subsidy+fees {permitted}"
        )

    commitment = reply.get("default_witness_commitment")
    if commitment is not None:
        commitment = _strict_hex(commitment, "default_witness_commitment")
        if not commitment:
            raise TemplateError("default_witness_commitment is empty")

    flags_hex = ""
    coinbaseaux = reply.get("coinbaseaux")
    if coinbaseaux is not None:
        if not isinstance(coinbaseaux, dict):
            raise TemplateError("coinbaseaux must be an object")
        flags_hex = _strict_hex(coinbaseaux.get("flags", ""), "coinbaseaux.flags")

    expires = reply.get("expires", 120)
    if not isinstance(expires, int) or isinstance(expires, bool) or expires <= 0:
        raise TemplateError("expires must be a positive integer")

    rules = reply.get("rules", [])
    mutable = reply.get("mutable", [])
    capabilities = reply.get("capabilities", [])
    for name, value in (("rules", rules), ("mutable", mutable),
                        ("capabilities", capabilities)):
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise TemplateError(f"{name} must be a list of strings")

    sigoplimit = reply.get("sigoplimit")
    sizelimit = reply.get("sizelimit")
    weightlimit = reply.get("weightlimit")
    for name, value in (("sigoplimit", sigoplimit), ("sizelimit", sizelimit),
                        ("weightlimit", weightlimit)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
            raise TemplateError(f"{name} must be a positive integer")

    longpollid = reply.get("longpollid")
    if longpollid is not None and not isinstance(longpollid, str):
        raise TemplateError("longpollid must be a string")

    return MiningTemplate(
        previous_block_hash=previous,
        version=version,
        height=height,
        bits=bits,
        target=target,
        curtime=curtime,
        mintime=mintime,
        transactions=tuple(txs),
        coinbase_value=coinbase_value,
        coinbase_flags=flags_hex,
        rules=tuple(rules),
        capabilities=frozenset(capabilities),
        default_witness_commitment=commitment,
        longpollid=longpollid,
        expires=expires,
        sigoplimit=sigoplimit,
        sizelimit=sizelimit,
        weightlimit=weightlimit,
        mutable=tuple(mutable),
        acquired_at=time.time(),
    )


class TemplateManager:
    """Acquires validated mining work and detects when it goes stale.

    Regtest only: acquisition fails closed on any other chain.
    """

    def __init__(self, rpc, expected_chain: str = "regtest",
                 pow_limit: int = POW_LIMIT_REGTEST):
        self._rpc = rpc
        self._expected_chain = expected_chain
        self._pow_limit = pow_limit

    def acquire(self) -> MiningTemplate:
        """Fetch fresh work from the node and validate it."""
        chain = self._rpc.get_blockchain_info().get("chain")
        if chain != self._expected_chain:
            raise TemplateError(
                f"refusing mining work on chain {chain!r}; regtest only"
            )
        return parse_template(self._rpc.get_block_template(),
                              pow_limit=self._pow_limit)

    def staleness_reasons(self, template: MiningTemplate,
                          now: float | None = None) -> list[str]:
        """Why this template can no longer be mined (empty = still valid)."""
        reasons = []
        if self._rpc.get_best_block_hash() != template.previous_block_hash:
            reasons.append("blockchain tip changed")
        current = time.time() if now is None else now
        if current >= template.expires_at:
            reasons.append("template expired")
        return reasons

    def is_stale(self, template: MiningTemplate, now: float | None = None) -> bool:
        return bool(self.staleness_reasons(template, now=now))

    def refresh(self, template: MiningTemplate) -> MiningTemplate:
        """Return fresh work when the template is stale, else the template."""
        if self.is_stale(template):
            return self.acquire()
        return template
