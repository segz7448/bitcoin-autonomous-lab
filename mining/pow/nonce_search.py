"""Interruptible nonce-search engine over the 32-bit nonce space.

Design notes
  * Input is an exact 80-byte candidate header; only bytes 76..80 (nonce)
    change. The first 64 bytes are hashed once (a SHA-256 "midstate",
    via hashlib's copy()), so each attempt costs one compression of the
    second block plus the outer hash. The result is identical to hashing
    the full header; tests assert this against the plain double-SHA-256.
  * The search range is [start_nonce, end_nonce) with end_nonce <= 2^32.
    It never wraps: when the range is spent the result status is
    EXHAUSTED and hashes_attempted equals exactly the range size.
  * Stops cleanly on: found, exhausted, stop_event/signal (INTERRUPTED),
    max_seconds or max_hashes (LIMIT). next_nonce says where to resume.
  * Extra nonce: `search_variants` takes any iterable of
    (label, 80-byte header) so a caller can vary the coinbase extra nonce
    / merkle root and keep searching; statistics accumulate across them.
"""

from __future__ import annotations

import enum
import hashlib
import signal
import struct
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .block_header import HEADER_SIZE
from .target import MAX_UINT256, POW_LIMIT_MAINNET, check_proof_of_work, decode_compact, digest_to_display

NONCE_SPACE = 1 << 32


class SearchStatus(enum.Enum):
    FOUND = "found"
    EXHAUSTED = "exhausted"
    INTERRUPTED = "interrupted"
    LIMIT = "limit"  # max_seconds / max_hashes reached


@dataclass
class SearchResult:
    status: SearchStatus
    hashes_attempted: int
    elapsed: float
    start_nonce: int
    next_nonce: int                  # first nonce NOT yet tried (resume point)
    nonce: Optional[int] = None
    digest: Optional[bytes] = None   # raw internal-order digest of the winner
    label: object = None             # variant label (extra nonce), if any

    @property
    def found(self) -> bool:
        return self.status is SearchStatus.FOUND

    @property
    def hash_display(self) -> Optional[str]:
        return digest_to_display(self.digest) if self.digest else None

    @property
    def hashrate(self) -> float:
        return self.hashes_attempted / self.elapsed if self.elapsed > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "status": self.status.value, "nonce": self.nonce,
            "hash": self.hash_display, "hashes_attempted": self.hashes_attempted,
            "elapsed_s": round(self.elapsed, 6), "hashrate_hs": round(self.hashrate, 1),
            "start_nonce": self.start_nonce, "next_nonce": self.next_nonce,
            "label": self.label,
        }


@contextmanager
def graceful_shutdown(stop_event: threading.Event):
    """Set stop_event on SIGINT/SIGTERM for the duration of the block.

    Only installs handlers from the main thread; elsewhere it is a no-op
    (callers can still set the event themselves).
    """
    if threading.current_thread() is not threading.main_thread():
        yield stop_event
        return
    previous = {}

    def handler(signum, frame):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, handler)
    try:
        yield stop_event
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


class NonceSearcher:
    """Searches nonces for a header whose double-SHA-256 satisfies a target."""

    def __init__(self, stop_event: Optional[threading.Event] = None,
                 check_interval: int = 4096,
                 clock: Callable[[], float] = time.perf_counter):
        if check_interval < 1:
            raise ValueError("check_interval must be >= 1")
        self.stop_event = stop_event or threading.Event()
        self.check_interval = check_interval
        self._clock = clock

    def stop(self) -> None:
        self.stop_event.set()

    # -- single header ---------------------------------------------------
    def search(self, header: bytes, target: int, start_nonce: int = 0,
               end_nonce: int = NONCE_SPACE, max_seconds: Optional[float] = None,
               max_hashes: Optional[int] = None,
               progress: Optional[Callable[[int, int], None]] = None,
               label=None) -> SearchResult:
        """Search nonces in [start_nonce, end_nonce) for hash_int <= target.

        `target` is the decoded integer target; it is range-checked here.
        Use search_bits() to start from nBits with consensus validation.
        """
        if not isinstance(header, (bytes, bytearray)) or len(header) != HEADER_SIZE:
            raise ValueError(f"candidate header must be exactly {HEADER_SIZE} bytes")
        if not isinstance(target, int) or not 0 < target <= MAX_UINT256:
            raise ValueError("target must be an integer in [1, 2^256-1]")
        if not (isinstance(start_nonce, int) and isinstance(end_nonce, int)
                and 0 <= start_nonce <= end_nonce <= NONCE_SPACE):
            raise ValueError("require 0 <= start_nonce <= end_nonce <= 2^32")
        header = bytes(header)
        tail_fixed = header[64:76]
        mid = hashlib.sha256(header[:64])  # midstate over the first 64 bytes
        sha256 = hashlib.sha256
        pack = struct.Struct("<I").pack
        from_bytes = int.from_bytes

        started = self._clock()
        deadline = started + max_seconds if max_seconds is not None else None
        hash_cap = (start_nonce + max_hashes) if max_hashes is not None else None
        stop_at = end_nonce if hash_cap is None else min(end_nonce, hash_cap)
        nonce = start_nonce
        interval = self.check_interval

        def finish(status, nonce_now, **kw):
            return SearchResult(status, nonce_now - start_nonce, self._clock() - started,
                                start_nonce, nonce_now, **kw)

        while nonce < stop_at:
            if self.stop_event.is_set():
                return finish(SearchStatus.INTERRUPTED, nonce)
            if deadline is not None and self._clock() >= deadline:
                return finish(SearchStatus.LIMIT, nonce)
            chunk_end = min(nonce + interval, stop_at)
            for n in range(nonce, chunk_end):
                h = mid.copy()
                h.update(tail_fixed + pack(n))
                digest = sha256(h.digest()).digest()
                if from_bytes(digest, "little") <= target:
                    return finish(SearchStatus.FOUND, n + 1, nonce=n, digest=digest, label=label)
            nonce = chunk_end
            if progress:
                progress(nonce - start_nonce, nonce)

        if nonce >= end_nonce:
            return finish(SearchStatus.EXHAUSTED, nonce)
        return finish(SearchStatus.LIMIT, nonce)

    def search_bits(self, header: bytes, pow_limit: int = POW_LIMIT_MAINNET, **kw) -> SearchResult:
        """Search using the header's own nBits, with Core's consensus checks.

        Raises ValueError for negative / zero / overflowing nBits or a
        target easier than pow_limit, instead of searching a bogus target.
        """
        if not isinstance(header, (bytes, bytearray)) or len(header) != HEADER_SIZE:
            raise ValueError(f"candidate header must be exactly {HEADER_SIZE} bytes")
        bits = struct.unpack("<I", bytes(header[72:76]))[0]
        t = decode_compact(bits)
        if not t.valid:
            raise ValueError(f"nBits {bits:#010x} is not a valid target "
                             f"(negative={t.negative} overflow={t.overflow} zero={t.zero})")
        if t.value > pow_limit:
            raise ValueError(f"nBits {bits:#010x} target exceeds the network pow limit")
        result = self.search(header, t.value, **kw)
        # Defence in depth: re-verify any winner with the consensus check
        # using the independent code path before reporting success.
        if result.found and not check_proof_of_work(result.digest, bits, pow_limit):
            raise AssertionError("internal error: winner failed consensus PoW check")
        return result

    # -- extra-nonce / varying header ----------------------------------------
    def search_variants(self, variants: Iterable, target: int,
                        max_seconds: Optional[float] = None,
                        max_hashes: Optional[int] = None,
                        start_nonce: int = 0,
                        end_nonce: int = NONCE_SPACE) -> SearchResult:
        """Search a nonce range (default: the full space) for each (label, header80) in turn.

        Totals (hashes, time) accumulate across variants. Returns FOUND
        with the winning variant label, EXHAUSTED when every variant's
        nonce space is spent, or INTERRUPTED/LIMIT.
        """
        started = self._clock()
        total = 0
        last = None
        for label, header in variants:
            remaining_s = None if max_seconds is None else max_seconds - (self._clock() - started)
            remaining_h = None if max_hashes is None else max_hashes - total
            if (remaining_s is not None and remaining_s <= 0) or \
                    (remaining_h is not None and remaining_h <= 0):
                return SearchResult(SearchStatus.LIMIT, total, self._clock() - started,
                                    0, 0, label=last)
            r = self.search(header, target, start_nonce, end_nonce, max_seconds=remaining_s,
                            max_hashes=remaining_h, label=label)
            total += r.hashes_attempted
            last = label
            if r.status in (SearchStatus.FOUND, SearchStatus.INTERRUPTED, SearchStatus.LIMIT):
                r.hashes_attempted = total
                r.elapsed = self._clock() - started
                return r
        return SearchResult(SearchStatus.EXHAUSTED, total, self._clock() - started,
                            0, NONCE_SPACE, label=last)
