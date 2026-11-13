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
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass

from mining.pow.nonce_search import NONCE_SPACE, NonceSearcher, SearchStatus
from mining.pow.target import POW_LIMIT_REGTEST, bits_to_target
from mining.pow.validator import validate_header

from .builder import CandidateBlock


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
        }


class EngineSearcher:
    """Searches a candidate block's nonce space with escalation handling."""

    def __init__(self, stop_event: threading.Event | None = None,
                 pow_limit: int = POW_LIMIT_REGTEST):
        self._searcher = NonceSearcher(stop_event=stop_event)
        self._stop_event = self._searcher.stop_event
        self._pow_limit = pow_limit

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
    ) -> SearchOutcome:
        """Search until a verified nonce, staleness, cancel, or budget end.

        ``is_stale`` is an optional zero-argument callable evaluated before
        every round; when it returns True the search stops and the work is
        abandoned (never submitted).
        """
        try:
            target = bits_to_target(candidate.bits)
        except ValueError as exc:
            raise SearchError(f"candidate has invalid target: {exc}") from exc
        if target > self._pow_limit:
            raise SearchError(
                "candidate target above the regtest proof-of-work limit")

        started = time.monotonic()
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
                now = int(time.time())
                if now > candidate.header.timestamp:
                    candidate = candidate.with_timestamp(
                        max(now, candidate.mintime))

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

    @staticmethod
    def _finish(status, candidate, hashes, started, batches, counter,
                nonce=None, hash_display=None, batch_rates=()) -> SearchOutcome:
        return SearchOutcome(
            status=status, candidate=candidate, hashes=hashes,
            seconds=time.monotonic() - started, batches=batches,
            extranonce_counter=counter, nonce=nonce,
            hash_display=hash_display, batch_rates=tuple(batch_rates),
        )
