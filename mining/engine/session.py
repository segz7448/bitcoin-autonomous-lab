"""Mining session orchestration for the TASK 005 engine (Phases 5-6).

One :class:`MiningEngine` ties the stages together for a single node:

    acquire template -> build candidate -> search PoW -> submit -> verify
    acceptance on the active chain -> record persistent statistics.

A block is reported as mined only when Bitcoin Core accepted it AND it is
verified on the active chain. Rejections, stale work, cancellations and
errors are all recorded, never silently discarded.
"""

from __future__ import annotations

import enum
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .builder import BuildError, build_candidate
from .search import EngineSearcher, OutcomeStatus, SearchError
from .stats import MiningStatsStore
from .template import TemplateError, TemplateManager


class CycleStatus(enum.Enum):
    ACCEPTED = "accepted"        # Core accepted; verified on the active chain
    DUPLICATE = "duplicate"      # Core already knew the block
    REJECTED = "rejected"        # Core refused it (reason recorded)
    STALE = "stale"
    CANCELLED = "cancelled"
    LIMIT = "limit"
    EXHAUSTED = "exhausted"
    TEMPLATE_ERROR = "template-error"
    BUILD_ERROR = "build-error"
    SEARCH_ERROR = "search-error"
    RPC_ERROR = "rpc-error"


@dataclass
class CycleResult:
    session_id: str
    status: CycleStatus
    started_at: str
    finished_at: str
    seconds: float
    height: int | None = None
    prev_hash: str | None = None
    block_hash: str | None = None
    hashes: int = 0
    hashrate_avg: float = 0.0
    hashrate_peak: float = 0.0
    backend: str = "cpu"
    batches: int = 0
    nonce: int | None = None
    extranonce_counter: int = 0
    submit_result: str | None = None
    accepted: bool = False
    coinbase_value: int | None = None
    fees: int | None = None
    chain_height_after: int | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {k: (v.value if isinstance(v, enum.Enum) else v)
                for k, v in self.__dict__.items()}


def payout_script_from_rpc(rpc) -> bytes:
    """Derive a payout scriptPubKey from a fresh wallet address (regtest)."""
    address = rpc.get_new_address()
    return bytes.fromhex(rpc.get_address_info(address)["scriptPubKey"])


class MiningEngine:
    """Runs full mining cycles against one regtest node."""

    def __init__(self, rpc, stats: MiningStatsStore | None = None,
                 stop_event: threading.Event | None = None,
                 backend: str = "cpu"):
        self._rpc = rpc
        self.templates = TemplateManager(rpc)
        self._stats = stats
        self._stop_event = stop_event or threading.Event()
        self._backend = backend

    def stop(self) -> None:
        self._stop_event.set()

    def mine_cycle(self, payout_script: bytes,
                   max_seconds: float | None = 60.0,
                   max_extranonce_rounds: int = 8,
                   max_hashes: int | None = None) -> CycleResult:
        """Run one complete acquire/build/search/submit/verify cycle."""
        session_id = uuid.uuid4().hex
        started_wall = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        result = CycleResult(
            session_id=session_id, status=CycleStatus.RPC_ERROR,
            started_at=started_wall, finished_at=started_wall, seconds=0.0,
            backend=self._backend,
        )
        try:
            template = self.templates.acquire()
        except TemplateError as exc:
            return self._record(result, CycleStatus.TEMPLATE_ERROR,
                                started, error=str(exc))
        except Exception as exc:  # RPC/transport failure
            return self._record(result, CycleStatus.RPC_ERROR,
                                started, error=str(exc))
        result.height = template.height
        result.prev_hash = template.previous_block_hash

        try:
            candidate = build_candidate(template, payout_script)
        except BuildError as exc:
            return self._record(result, CycleStatus.BUILD_ERROR,
                                started, error=str(exc))
        result.coinbase_value = candidate.coinbase_value
        result.fees = candidate.fees

        searcher = EngineSearcher(stop_event=self._stop_event)
        try:
            outcome = searcher.search_candidate(
                candidate,
                is_stale=lambda: self.templates.is_stale(template),
                max_seconds=max_seconds,
                max_extranonce_rounds=max_extranonce_rounds,
                max_hashes=max_hashes,
            )
        except SearchError as exc:
            return self._record(result, CycleStatus.SEARCH_ERROR,
                                started, error=str(exc))

        result.hashes = outcome.hashes
        result.hashrate_avg = outcome.hashrate
        result.hashrate_peak = outcome.hashrate_peak
        result.batches = outcome.batches
        result.extranonce_counter = outcome.extranonce_counter
        result.nonce = outcome.nonce

        if outcome.status is not OutcomeStatus.FOUND:
            return self._record(
                result, CycleStatus(outcome.status.value), started,
                error=None if outcome.status is OutcomeStatus.FOUND
                else f"search ended: {outcome.status.value}")

        result.block_hash = outcome.hash_display
        try:
            reject_reason = self._rpc.submit_block(
                outcome.candidate.block_hex())
        except Exception as exc:
            return self._record(result, CycleStatus.RPC_ERROR,
                                started, error=f"submitblock failed: {exc}")
        result.submit_result = "accepted" if reject_reason is None else reject_reason

        if reject_reason is not None:
            status = (CycleStatus.DUPLICATE if reject_reason == "duplicate"
                      else CycleStatus.REJECTED)
            return self._record(result, status, started,
                                error=f"submitblock: {reject_reason}")

        # Acceptance is not enough: verify the block is on the active chain.
        try:
            committed = self._rpc.get_block(result.block_hash)
            chain = self._rpc.get_blockchain_info()
        except Exception as exc:
            return self._record(result, CycleStatus.RPC_ERROR,
                                started, error=f"post-submit check failed: {exc}")
        result.chain_height_after = chain.get("blocks")
        if (committed.get("confirmations", 0) < 1
                or chain.get("bestblockhash") != result.block_hash):
            return self._record(
                result, CycleStatus.REJECTED, started,
                error="block not on the active chain after submission")

        result.accepted = True
        return self._record(result, CycleStatus.ACCEPTED, started)

    def mine_blocks(self, count: int, payout_script: bytes,
                    max_seconds_per_block: float | None = 60.0) -> list[CycleResult]:
        """Run consecutive cycles; stop early on cancel or repeated failure."""
        results = []
        consecutive_failures = 0
        for _ in range(count):
            if self._stop_event.is_set():
                break
            cycle = self.mine_cycle(
                payout_script, max_seconds=max_seconds_per_block)
            results.append(cycle)
            consecutive_failures = 0 if cycle.accepted else consecutive_failures + 1
            if consecutive_failures >= 3:
                break
        return results

    def _record(self, result: CycleResult, status: CycleStatus,
                started: float, error: str | None = None) -> CycleResult:
        result.status = status
        result.error = error
        result.seconds = time.monotonic() - started
        result.finished_at = datetime.now(timezone.utc).isoformat()
        if self._stats is not None:
            self._stats.record_session({
                "session_id": result.session_id,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "height": result.height,
                "prev_hash": result.prev_hash,
                "block_hash": result.block_hash,
                "seconds": result.seconds,
                "hashes": result.hashes,
                "hashrate_avg": result.hashrate_avg,
                "hashrate_peak": result.hashrate_peak,
                "backend": result.backend,
                "batches": result.batches,
                "nonce": result.nonce,
                "extranonce_counter": result.extranonce_counter,
                "submit_result": result.submit_result or status.value,
                "accepted": 1 if result.accepted else 0,
                "coinbase_value": result.coinbase_value,
                "fees": result.fees,
                "error": result.error,
            })
        return result
