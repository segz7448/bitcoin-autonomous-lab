"""Proof-of-Work search for the TASK 005 engine (brief Phase 4).

Drives the existing :class:`mining.pow.nonce_search.NonceSearcher` over a
constructed :class:`~mining.engine.builder.CandidateBlock` and adds the
engine-level behaviour the brief requires:

* target decoded and validated before any hashing (regtest pow limit);
* nonce-range exhaustion handling: the candidate's extra nonce is bumped
  (new coinbase, new merkle root) and the full 32-bit nonce space is
  searched again, up to a bounded number of rounds;
* block-time updates between rounds, respecting the template's mintime;
* staleness checks between rounds - work on a stale template is abandoned,
  never submitted;
* graceful cancellation through a stop event;
* every candidate solution independently re-verified on the CPU through
  ``mining.pow.validator`` before it is reported as found;
* exact accounting: total hashes, elapsed seconds, hashrate, batches and
  extra-nonce rounds.

When a :class:`gpu.engine.ComputeEngine` is supplied, nonce space is
dispatched through it in bounded batches: this is the CPU/CUDA backend
integration the brief requires (Phase 4/9). ComputeEngine selects the
backend, falls back to the CPU on CUDA faults (the fallback reason is
recorded on the outcome), and every batch is staleness/cancel/budget
checked - so stale work is abandoned mid-search, not only between full
nonce-space rounds. Block-time updates respect the template's mintime
and the network-adjusted consensus limit (now + MAX_FUTURE_BLOCK_TIME).
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass

from gpu.engine import ComputeEngine
from mining.pow.nonce_search import NONCE_SPACE, NonceSearcher, SearchStatus
from mining.pow.target import POW_LIMIT_REGTEST, bits_to_target
from mining.pow.validator import validate_header

from .builder import CandidateBlock

# Consensus rule: a block timestamp may not be more than two hours ahead
# of the network-adjusted time (MAX_FUTURE_BLOCK_TIME).
MAX_FUTURE_BLOCK_TIME = 2 * 60 * 60

DEFAULT_BATCH_SIZE = 65536


class SearchError(RuntimeError):
    """Search setup or verification failed; fails closed."""


class OutcomeStatus(enum.Enum):
    FOUND = "found"                    # valid nonce, independently verified
    STALE = "stale"                    # template went stale; work abandoned
    CANCELLED = "cancelled"            # stop event / interrupt
    LIMIT = "limit"                    # time/hash budget exhausted
    EXHAUSTED = "exhausted"            # all extra-nonce rounds exhausted


@dataclass
class SearchOutcome:
    status: OutcomeStatus
    candidate: CandidateBlock
    hashes: int
    seconds: float
    batches: int
    extranonce_counter: int
    nonce: int | None = None
    hash_display: str | None = None
    batch_rates: tuple[float, ...] = ()   # hashrate sample per batch
    backend: str = "cpu"                  # backend that actually hashed
    backend_fallback: str | None = None   # recorded when a fallback fired

    @property
    def found(self) -> bool:
        return self.status is OutcomeStatus.FOUND

    @property
    def hashrate(self) -> float:
        return self.hashes / self.seconds if self.seconds > 0 else 0.0

    @property
    def hashrate_peak(self) -> float:
        return max(self.batch_rates) if self.batch_rates else self.hashrate

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "nonce": self.nonce,
            "hash": self.hash_display,
            "hashes": self.hashes,
            "seconds": round(self.seconds, 6),
            "hashrate_hs": round(self.hashrate, 1),
            "batches": self.batches,
            "batch_rates": [round(r, 1) for r in self.batch_rates],
            "extranonce_counter": self.extranonce_counter,
            "height": self.candidate.height,
            "backend": self.backend,
            "backend_fallback": self.backend_fallback,
        }


class EngineSearcher:
    """Searches a candidate block's nonce space with escalation handling."""

    def __init__(self, stop_event: threading.Event | None = None,
                 pow_limit: int = POW_LIMIT_REGTEST,
                 compute: ComputeEngine | None = None,
                 batch_size: int = DEFAULT_BATCH_SIZE):
        self._searcher = NonceSearcher(stop_event=stop_event)
        self._stop_event = self._searcher.stop_event
        self._pow_limit = pow_limit
        self._compute = compute
        if batch_size < 1 or batch_size > NONCE_SPACE:
            raise ValueError("batch_size must be within [1, 2^32]")
        self._batch_size = batch_size

    def stop(self) -> None:
        self._searcher.stop()

    def search_candidate(
        self,
        candidate: CandidateBlock,
        *,
        is_stale=None,
        max_seconds: float | None = 60.0,
        max_hashes: int | None = None,
        max_extranonce_rounds: int = 8,
        nonce_end: int = NONCE_SPACE,
        update_time: bool = True,
        network_time_offset: int = 0,
    ) -> SearchOutcome:
        """Search until a verified nonce, staleness, cancel, or budget end.

        ``is_stale`` is an optional zero-argument callable evaluated before
        every batch (or round); when it returns True the search stops and
        the work is abandoned (never submitted).
        ``network_time_offset`` is the node's timeoffset (getnetworkinfo):
        block-time updates are clamped to network-adjusted time plus the
        MAX_FUTURE_BLOCK_TIME consensus allowance and never go below the
        template's mintime.
        """
        try:
            target = bits_to_target(candidate.bits)
        except ValueError as exc:
            raise SearchError(f"candidate has invalid target: {exc}") from exc
        if target > self._pow_limit:
            raise SearchError(
                "candidate target above the regtest proof-of-work limit")

        started = time.monotonic()
        if self._compute is not None:
            return self._search_with_compute(
                candidate, target, started, is_stale=is_stale,
                max_seconds=max_seconds, max_hashes=max_hashes,
                max_extranonce_rounds=max_extranonce_rounds,
                nonce_end=nonce_end, update_time=update_time,
                network_time_offset=network_time_offset)
        deadline = started + max_seconds if max_seconds is not None else None
        total_hashes = 0
        batches = 0
        counter = 0
        batch_rates: list[float] = []

        while True:
            if self._stop_event.is_set():
                return self._finish(OutcomeStatus.CANCELLED, candidate,
                                    total_hashes, started, batches, counter,
                                    batch_rates=batch_rates)
            if is_stale is not None and is_stale():
                return self._finish(OutcomeStatus.STALE, candidate,
                                    total_hashes, started, batches, counter,
                                    batch_rates=batch_rates)

            if update_time:
                candidate = self._refresh_time(candidate,
                                               network_time_offset)

            remaining_seconds = None
            if deadline is not None:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    return self._finish(OutcomeStatus.LIMIT, candidate,
                                        total_hashes, started, batches, counter,
                                        batch_rates=batch_rates)
            remaining_hashes = None
            if max_hashes is not None:
                remaining_hashes = max_hashes - total_hashes
                if remaining_hashes <= 0:
                    return self._finish(OutcomeStatus.LIMIT, candidate,
                                        total_hashes, started, batches, counter,
                                        batch_rates=batch_rates)

            result = self._searcher.search(
                candidate.header.serialize(), target,
                start_nonce=0, end_nonce=nonce_end,
                max_seconds=remaining_seconds, max_hashes=remaining_hashes,
                label=f"extranonce:{counter}",
            )
            batches += 1
            total_hashes += result.hashes_attempted
            batch_rates.append(result.hashrate)

            if result.status is SearchStatus.FOUND:
                candidate.header.nonce = result.nonce
                # Independent CPU verification of the candidate solution
                # before it is reported or submitted (brief Phase 5).
                check = validate_header(candidate.header.serialize(),
                                        pow_limit=self._pow_limit)
                if not check.valid:
                    raise SearchError(
                        f"searcher reported a nonce that independent "
                        f"validation rejects: {check.reason}"
                    )
                return self._finish(OutcomeStatus.FOUND, candidate,
                                    total_hashes, started, batches, counter,
                                    nonce=result.nonce,
                                    hash_display=result.hash_display,
                                    batch_rates=batch_rates)

            if result.status is SearchStatus.EXHAUSTED:
                if counter >= max_extranonce_rounds:
                    return self._finish(OutcomeStatus.EXHAUSTED, candidate,
                                        total_hashes, started, batches, counter,
                                        batch_rates=batch_rates)
                counter += 1
                candidate = candidate.with_extranonce(counter)
                continue

            if result.status is SearchStatus.INTERRUPTED:
                return self._finish(OutcomeStatus.CANCELLED, candidate,
                                    total_hashes, started, batches, counter,
                                    batch_rates=batch_rates)

            return self._finish(OutcomeStatus.LIMIT, candidate,
                                total_hashes, started, batches, counter,
                                batch_rates=batch_rates)

    def _refresh_time(self, candidate: CandidateBlock,
                      network_time_offset: int) -> CandidateBlock:
        """Advance the block time within consensus limits.

        The new time is at least the template's mintime and never more
        than network-adjusted time + MAX_FUTURE_BLOCK_TIME. A template
        whose mintime already exceeds that limit is impossible to mine
        honestly, so the search fails closed.
        """
        max_valid = (int(time.time()) + network_time_offset
                     + MAX_FUTURE_BLOCK_TIME)
        if candidate.mintime > max_valid:
            raise SearchError(
                f"template mintime {candidate.mintime} exceeds the "
                f"network-adjusted maximum valid block time {max_valid}")
        now = min(int(time.time()), max_valid)
        if now > candidate.header.timestamp:
            return candidate.with_timestamp(max(now, candidate.mintime))
        return candidate

    def _search_with_compute(
        self, candidate: CandidateBlock, target: int, started: float,
        *, is_stale, max_seconds, max_hashes, max_extranonce_rounds,
        nonce_end: int, update_time: bool, network_time_offset: int,
    ) -> SearchOutcome:
        """Dispatch the nonce space through the ComputeEngine in batches.

        Every batch goes through the selected backend (CPU/CUDA); a CUDA
        fault falls back to the CPU inside ComputeEngine and the reason is
        recorded here. Staleness, cancellation and budgets are checked
        between batches, so work on a stale template is abandoned
        mid-search. Every reported nonce is independently re-verified.
        """
        compute = self._compute
        deadline = (started + max_seconds
                    if max_seconds is not None else None)
        total_hashes = 0
        batches = 0
        counter = 0
        batch_rates: list[float] = []
        fallback_reason = None
        backend = compute.backend.name

        while True:
            if update_time:
                candidate = self._refresh_time(candidate,
                                               network_time_offset)
            header = candidate.header.serialize()
            start_nonce = 0
            while start_nonce < nonce_end:
                if self._stop_event.is_set():
                    return self._finish(
                        OutcomeStatus.CANCELLED, candidate, total_hashes,
                        started, batches, counter, batch_rates=batch_rates,
                        backend=backend, backend_fallback=fallback_reason)
                if is_stale is not None and is_stale():
                    return self._finish(
                        OutcomeStatus.STALE, candidate, total_hashes,
                        started, batches, counter, batch_rates=batch_rates,
                        backend=backend, backend_fallback=fallback_reason)
                if deadline is not None and time.monotonic() >= deadline:
                    return self._finish(
                        OutcomeStatus.LIMIT, candidate, total_hashes,
                        started, batches, counter, batch_rates=batch_rates,
                        backend=backend, backend_fallback=fallback_reason)
                count = min(self._batch_size, nonce_end - start_nonce)
                if max_hashes is not None:
                    count = min(count, max_hashes - total_hashes)
                    if count <= 0:
                        return self._finish(
                            OutcomeStatus.LIMIT, candidate, total_hashes,
                            started, batches, counter, batch_rates=batch_rates,
                            backend=backend, backend_fallback=fallback_reason)
                try:
                    reply = compute.batch(header, target,
                                          start_nonce=start_nonce,
                                          count=count)
                except Exception as exc:
                    raise SearchError(
                        f"computation batch failed on backend "
                        f"{backend}: {exc}") from exc
                batches += 1
                total_hashes += reply["hashes_computed"]
                elapsed = reply.get("elapsed_seconds") or 0.0
                if elapsed > 0:
                    batch_rates.append(reply["hashes_computed"] / elapsed)
                # A fault mid-batch (CUDA error recomputed on CPU) is a
                # real mining fallback and is recorded; the backend named
                # by each reply is the one that actually hashed it.
                backend = reply.get("backend", backend)
                if reply.get("fallback_in_batch"):
                    fallback_reason = reply["fallback_reason"]

                candidates = reply.get("candidates") or []
                if candidates:
                    nonce = int(candidates[0]["nonce"])
                    candidate.header.nonce = nonce
                    check = validate_header(candidate.header.serialize(),
                                            pow_limit=self._pow_limit)
                    if not check.valid:
                        raise SearchError(
                            "backend reported a nonce that independent "
                            f"validation rejects: {check.reason}")
                    return self._finish(
                        OutcomeStatus.FOUND, candidate, total_hashes,
                        started, batches, counter, nonce=nonce,
                        hash_display=candidate.header.hash_display(),
                        batch_rates=batch_rates, backend=backend,
                        backend_fallback=fallback_reason)
                start_nonce += count

            if counter >= max_extranonce_rounds:
                return self._finish(
                    OutcomeStatus.EXHAUSTED, candidate, total_hashes,
                    started, batches, counter, batch_rates=batch_rates,
                    backend=backend, backend_fallback=fallback_reason)
            counter += 1
            candidate = candidate.with_extranonce(counter)

    @staticmethod
    def _finish(status, candidate, hashes, started, batches, counter,
                nonce=None, hash_display=None, batch_rates=(),
                backend="cpu", backend_fallback=None) -> SearchOutcome:
        return SearchOutcome(
            status=status, candidate=candidate, hashes=hashes,
            seconds=time.monotonic() - started, batches=batches,
            extranonce_counter=counter, nonce=nonce,
            hash_display=hash_display, batch_rates=tuple(batch_rates),
            backend=backend, backend_fallback=backend_fallback,
        )
