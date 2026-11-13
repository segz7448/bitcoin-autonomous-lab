"""Intelligent computation management for the autonomous agent (Phase 9).

Backend decisions are made from actual execution results, never assumed
availability: a real batch is dispatched through the existing
``gpu.engine.ComputeEngine`` and measured. CUDA is selected only when its
self-test and a real batch succeed; any failure falls back to CPU and the
fallback reason is recorded. The TASK 004 privacy restrictions are
respected: only operational outcomes (backend name, fallback reason,
measured hashrate) are reported - no GPU model, architecture, compute
capability, memory topology or hardware identifiers are requested or
exposed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from gpu.engine import ComputeEngine

_BENCH_HEADER = bytes(range(80))
_BENCH_TARGET = (1 << 256) - 1   # every digest matches; pure throughput probe
_BENCH_HASHES = 4096


@dataclass
class BackendReport:
    requested: str
    backend: str
    fallback_reason: str | None
    benchmark_hashes: int
    benchmark_seconds: float
    benchmark_hashrate: float
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "requested": self.requested,
            "backend": self.backend,
            "fallback_reason": self.fallback_reason,
            "benchmark_hashes": self.benchmark_hashes,
            "benchmark_seconds": round(self.benchmark_seconds, 6),
            "benchmark_hashrate": round(self.benchmark_hashrate, 1),
            "errors": list(self.errors),
        }


class ComputationManager:
    """Selects a usable backend from measured results and monitors it."""

    def __init__(self, requested: str = "auto"):
        if requested not in ("auto", "cpu", "cuda"):
            raise ValueError("requested backend must be auto, cpu or cuda")
        self._requested = requested
        self._engine: ComputeEngine | None = None
        self._report: BackendReport | None = None
        self._batch_count = 0

    def probe(self) -> BackendReport:
        """Create the engine and measure a real batch on the live backend."""
        errors: list[str] = []
        engine = ComputeEngine(backend=self._requested)
        started = time.perf_counter()
        try:
            result = engine.batch(_BENCH_HEADER, _BENCH_TARGET, 0,
                                  _BENCH_HASHES)
            seconds = time.perf_counter() - started
            hashes = result["hashes_computed"]
            if result["fallback_reason"] and engine.fallback_reason:
                errors.append(engine.fallback_reason)
        except Exception as exc:  # defensive: ComputeEngine already falls back
            seconds = time.perf_counter() - started
            hashes = 0
            errors.append(str(exc))
            engine = ComputeEngine(backend="cpu")
        self._engine = engine
        self._report = BackendReport(
            requested=self._requested,
            backend=engine.backend.name,
            fallback_reason=engine.fallback_reason,
            benchmark_hashes=hashes,
            benchmark_seconds=seconds,
            benchmark_hashrate=hashes / seconds if seconds > 0 else 0.0,
            errors=errors,
        )
        return self._report

    @property
    def engine(self) -> ComputeEngine:
        if self._engine is None:
            self.probe()
        return self._engine

    @property
    def backend_name(self) -> str:
        return self.engine.backend.name

    @property
    def report(self) -> BackendReport | None:
        return self._report

    def record_batch(self) -> None:
        self._batch_count += 1

    @property
    def batch_count(self) -> int:
        return self._batch_count
