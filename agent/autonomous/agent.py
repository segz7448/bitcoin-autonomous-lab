"""Autonomous AI mining agent (TASK 006, brief Phases 7-11).

The agent coordinates - it does not replace - the deterministic mining
engine. It decides *when* to mine, *which* backend is usable (from measured
results), *when* work is stale, and *how* to recover; the engine remains
responsible for constructing and validating blocks under consensus rules.

Lifecycle (Phase 8): initialize -> observe -> prepare -> compute -> verify
-> submit -> repeat, driven by MiningEngine.mine_cycle, with staleness
detection, interruption recovery and persistent state. Every decision,
error and recovery event is recorded in the mining statistics database.

Control interface (Phase 11): start / stop / pause / resume / status /
blockchain_status / backend_status / current_stats / historical_stats /
decisions / errors / diagnostics. All operations return dicts with an "ok"
flag, matching the project's AgentInterface style. Regtest only.
"""

from __future__ import annotations

import enum
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from mining.engine.session import CycleStatus, MiningEngine
from mining.engine.stats import MiningStatsStore
from mining.engine.template import TemplateManager

from .compute import ComputationManager


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentState(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"  # cancellation signalled; worker not yet terminated
    STOPPED = "stopped"
    ERROR = "error"


def _require_positive_int(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(
            f"{name} must be a positive integer, got {value!r}")


def _require_positive_number(name: str, value) -> None:
    if (isinstance(value, bool)
            or not isinstance(value, (int, float)) or not value > 0):
        raise ValueError(
            f"{name} must be a positive number, got {value!r}")


def _require_non_negative_number(name: str, value) -> None:
    if (isinstance(value, bool)
            or not isinstance(value, (int, float)) or value < 0):
        raise ValueError(
            f"{name} must be a non-negative number, got {value!r}")


@dataclass
class ResourceLimits:
    """Configurable limits so the agent never consumes unbounded resources.

    Every field is validated on construction: nonsensical settings (zero
    or negative cycle limits, negative time budgets, hash limits or
    backoffs, a failure limit below one) are rejected with ValueError so
    the controller can never run with an accidentally unbounded or
    meaningless configuration. ``max_hashes_per_cycle=None`` is the one
    explicit opt-out: no per-cycle hash cap, chosen deliberately rather
    than by accident.
    """
    max_cycles: int = 100
    max_seconds_per_cycle: float = 60.0
    max_hashes_per_cycle: int | None = None
    cycle_pause_seconds: float = 0.0
    max_consecutive_failures: int = 3
    failure_backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        _require_positive_int("max_cycles", self.max_cycles)
        _require_positive_number("max_seconds_per_cycle",
                                 self.max_seconds_per_cycle)
        if self.max_hashes_per_cycle is not None:
            _require_positive_int("max_hashes_per_cycle",
                                  self.max_hashes_per_cycle)
        _require_non_negative_number("cycle_pause_seconds",
                                     self.cycle_pause_seconds)
        _require_positive_int("max_consecutive_failures",
                              self.max_consecutive_failures)
        _require_non_negative_number("failure_backoff_seconds",
                                     self.failure_backoff_seconds)


class MiningAgent:
    """Central autonomous mining controller (regtest only)."""

    def __init__(self, rpc, stats: MiningStatsStore, state_path: str,
                 limits: ResourceLimits | None = None,
                 requested_backend: str = "auto",
                 shutdown_timeout: float = 30.0):
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        self._rpc = rpc
        self._stats = stats
        self._state_path = state_path
        self._limits = limits or ResourceLimits()
        self._shutdown_timeout = float(shutdown_timeout)
        self._compute = ComputationManager(requested=requested_backend)
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = AgentState.IDLE
        self._cycles_completed = 0
        self._last_cycle: dict | None = None
        self._engine: MiningEngine | None = None

    # -- persistence -------------------------------------------------------
    def _write_state(self, state: str) -> None:
        payload = {
            "state": state,
            "updated_at": _utcnow(),
            "cycles_completed": self._cycles_completed,
            "backend": self._compute.report.backend
            if self._compute.report else None,
        }
        tmp = self._state_path + ".tmp"
        # Both the temporary and the final state file are owner-only
        # (0600) on supported systems, matching the mining database.
        # The temp file is created private before any content is written;
        # os.replace then carries that mode onto the final path, and the
        # final chmod also repairs a previously permissive file.
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, self._state_path)
        if os.name == "posix":
            os.chmod(self._state_path, 0o600)

    def _check_interrupted_session(self) -> None:
        """Detect a previous session that never shut down cleanly."""
        try:
            with open(self._state_path) as fh:
                prior = json.load(fh)
        except (OSError, ValueError):
            return
        if prior.get("state") in (AgentState.RUNNING.value,
                                  AgentState.PAUSED.value):
            self._stats.record_event(
                _utcnow(), "recovery",
                "prior session ended without shutdown "
                f"(was {prior.get('state')}, "
                f"cycles_completed={prior.get('cycles_completed')}); "
                "state reset to a consistent idle state")
            self._write_state(AgentState.IDLE.value)

    def _decide(self, kind: str, detail: str = "") -> None:
        self._stats.record_decision(_utcnow(), kind, detail)

    def _event(self, kind: str, detail: str = "") -> None:
        self._stats.record_event(_utcnow(), kind, detail)

    # -- diagnostics (Phase 8 step 1) ---------------------------------------
    def diagnostics(self) -> dict:
        """Health checks: connectivity, chain, mining work, backend."""
        checks = {}
        try:
            info = self._rpc.get_blockchain_info()
            checks["core_connectivity"] = True
            checks["chain"] = info.get("chain")
            checks["regtest_only"] = info.get("chain") == "regtest"
            checks["blocks"] = info.get("blocks")
            checks["headers"] = info.get("headers")
            checks["synchronized"] = info.get("blocks") == info.get("headers")
        except Exception as exc:
            return {"ok": False, "error": f"Bitcoin Core unreachable: {exc}",
                    "checks": {"core_connectivity": False}}
        try:
            template = TemplateManager(self._rpc).acquire()
            checks["mining_work_available"] = True
            checks["next_height"] = template.height
        except Exception as exc:
            checks["mining_work_available"] = False
            checks["mining_work_error"] = str(exc)
        report = self._compute.report or self._compute.probe()
        checks["backend"] = report.backend
        checks["backend_fallback_reason"] = report.fallback_reason
        checks["backend_benchmark_hs"] = round(report.benchmark_hashrate, 1)
        checks["engine_ready"] = bool(checks.get("mining_work_available"))
        healthy = (checks["regtest_only"] and checks["synchronized"]
                   and checks["engine_ready"])
        return {"ok": healthy, "checks": checks}

    # -- control interface (Phase 11) ----------------------------------------
    def start(self, payout_script: bytes) -> dict:
        with self._lock:
            # STOPPING is refused too: a worker from the previous session
            # is still alive, and starting a second one would double-mine.
            if self._state in (AgentState.RUNNING, AgentState.PAUSED,
                               AgentState.STOPPING):
                return {"ok": False, "error": f"agent already {self._state.value}"}
            self._check_interrupted_session()
            health = self.diagnostics()
            if not health["ok"]:
                self._event("error", f"pre-start diagnostics failed: {health}")
                return {"ok": False, "error": "diagnostics failed",
                        "diagnostics": health}
            backend = health["checks"]["backend"]
            self._decide(
                "backend-selected",
                f"backend={backend} (requested "
                f"{self._compute.report.requested}); "
                f"fallback_reason={self._compute.report.fallback_reason}; "
                f"measured {self._compute.report.benchmark_hashrate:.0f} H/s")
            self._engine = MiningEngine(
                self._rpc, stats=self._stats, stop_event=self._stop_event,
                backend=backend, compute=self._compute.engine,
                batch_size=self._compute.batch_size)
            self._stop_event.clear()
            self._pause_event.clear()
            self._cycles_completed = 0
            self._state = AgentState.RUNNING
            self._payout_script = payout_script
            self._write_state(AgentState.RUNNING.value)
            self._thread = threading.Thread(
                target=self._run, name="mining-agent", daemon=True)
            self._thread.start()
            self._decide("mining-started",
                         f"limits: max_cycles={self._limits.max_cycles}, "
                         f"max_seconds_per_cycle="
                         f"{self._limits.max_seconds_per_cycle}")
            return {"ok": True, "state": self._state.value, "backend": backend}

    def stop(self) -> dict:
        """Signal cancellation and wait for the worker to actually exit.

        STOPPED is reported and persisted only after the mining thread
        has verifiably terminated. If the join times out with the worker
        still alive, the agent reports an explicit shutdown-timeout
        error and stays in STOPPING - status() and the state file keep
        telling the truth, and a later stop() can complete the shutdown
        once the worker exits.
        """
        with self._lock:
            if self._state not in (AgentState.RUNNING, AgentState.PAUSED,
                                   AgentState.STOPPING):
                return {"ok": False, "error": f"agent is {self._state.value}"}
            self._state = AgentState.STOPPING
            self._pause_event.clear()
            self._stop_event.set()
        if self._engine is not None:
            self._engine.stop()
        worker = self._thread
        if worker is not None:
            worker.join(timeout=self._shutdown_timeout)
            if worker.is_alive():
                # Cancellation was signalled but the worker has NOT
                # terminated: never report or persist a false STOPPED.
                with self._lock:
                    self._state = AgentState.STOPPING
                self._write_state(AgentState.STOPPING.value)
                self._event(
                    "error",
                    f"shutdown timeout: mining worker still running "
                    f"{self._shutdown_timeout}s after cancellation")
                return {"ok": False,
                        "error": "shutdown timeout: worker did not "
                                 f"terminate within "
                                 f"{self._shutdown_timeout}s",
                        "state": AgentState.STOPPING.value,
                        "cycles_completed": self._cycles_completed}
        with self._lock:
            self._state = AgentState.STOPPED
        self._write_state(AgentState.STOPPED.value)
        self._decide("mining-stopped",
                     f"cycles_completed={self._cycles_completed}")
        return {"ok": True, "state": AgentState.STOPPED.value,
                "cycles_completed": self._cycles_completed}

    def pause(self) -> dict:
        with self._lock:
            if self._state is not AgentState.RUNNING:
                return {"ok": False, "error": f"agent is {self._state.value}"}
            self._state = AgentState.PAUSED
            self._pause_event.set()
        self._write_state(AgentState.PAUSED.value)
        self._decide("mining-paused", "takes effect between cycles")
        return {"ok": True, "state": self._state.value}

    def resume(self) -> dict:
        with self._lock:
            if self._state is not AgentState.PAUSED:
                return {"ok": False, "error": f"agent is {self._state.value}"}
            self._state = AgentState.RUNNING
            self._pause_event.clear()
        self._write_state(AgentState.RUNNING.value)
        self._decide("mining-resumed", "")
        return {"ok": True, "state": self._state.value}

    def status(self) -> dict:
        with self._lock:
            return {
                "ok": True,
                "state": self._state.value,
                "cycles_completed": self._cycles_completed,
                "backend": (self._compute.report.backend
                            if self._compute.report else None),
                "limits": self._limits.__dict__,
                "last_cycle": self._last_cycle,
            }

    def blockchain_status(self) -> dict:
        try:
            info = self._rpc.get_blockchain_info()
            return {"ok": True, "chain": info.get("chain"),
                    "blocks": info.get("blocks"),
                    "best_block_hash": info.get("bestblockhash")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def backend_status(self) -> dict:
        report = self._compute.report
        if report is None:
            return {"ok": True, "backend": None, "probed": False}
        return {"ok": True, "probed": True, **report.as_dict()}

    def current_stats(self) -> dict:
        return {"ok": True, "totals": self._stats.totals(),
                "latest": (self._stats.history(1) or [None])[0]}

    def historical_stats(self, limit: int = 50) -> dict:
        return {"ok": True, "history": self._stats.history(limit)}

    def decisions(self, limit: int = 100) -> dict:
        return {"ok": True, "decisions": self._stats.decisions(limit)}

    def errors(self, limit: int = 100) -> dict:
        return {"ok": True, "events": self._stats.events(limit)}

    # -- autonomous lifecycle (Phase 8) ---------------------------------------
    def _run(self) -> None:
        failures = 0
        try:
            while (not self._stop_event.is_set()
                   and self._cycles_completed < self._limits.max_cycles):
                if self._pause_event.is_set():
                    time.sleep(0.1)
                    continue
                cycle = self._engine.mine_cycle(
                    self._payout_script,
                    max_seconds=self._limits.max_seconds_per_cycle,
                    max_hashes=self._limits.max_hashes_per_cycle)
                self._cycles_completed += 1
                self._last_cycle = cycle.as_dict()
                self._write_state(AgentState.RUNNING.value)

                if cycle.backend_fallback:
                    self._decide(
                        "backend-fallback",
                        f"actual backend now {cycle.backend}: "
                        f"{cycle.backend_fallback}")
                if cycle.batches:
                    new_size = self._compute.adjust_batch_size(
                        cycle.seconds / cycle.batches)
                    if new_size != self._engine.batch_size:
                        self._decide(
                            "batch-size-adjusted",
                            f"batch_size {self._engine.batch_size} -> "
                            f"{new_size} from measured batch time "
                            f"{cycle.seconds / cycle.batches:.3f}s")
                        self._engine.batch_size = new_size

                if cycle.accepted:
                    failures = 0
                    self._decide(
                        "cycle-accepted",
                        f"height={cycle.height} hash={cycle.block_hash} "
                        f"nonce={cycle.nonce} hashes={cycle.hashes} "
                        f"in {cycle.seconds:.3f}s")
                else:
                    failures += 1
                    self._event(
                        "cycle-failed",
                        f"status={cycle.status.value} error={cycle.error}")
                    if cycle.status is CycleStatus.STALE:
                        self._decide("template-stale",
                                     "work abandoned; fresh template will be "
                                     "acquired on the next cycle")
                    if failures >= self._limits.max_consecutive_failures:
                        self._event(
                            "error",
                            f"{failures} consecutive failures; stopping")
                        self._decide("mining-halted",
                                     "consecutive failure limit reached")
                        break
                    self._decide("failure-backoff",
                                 f"waiting {self._limits.failure_backoff_seconds}s "
                                 f"after failure {failures}")
                    if self._stop_event.wait(self._limits.failure_backoff_seconds):
                        break
                if self._limits.cycle_pause_seconds:
                    if self._stop_event.wait(self._limits.cycle_pause_seconds):
                        break
        except Exception as exc:  # never let the thread die silently
            self._event("error", f"lifecycle crashed: {exc}")
            with self._lock:
                self._state = AgentState.ERROR
        finally:
            with self._lock:
                if self._state is not AgentState.ERROR:
                    self._state = (AgentState.STOPPED
                                   if self._stop_event.is_set()
                                   else AgentState.IDLE)
            self._write_state(self._state.value)
