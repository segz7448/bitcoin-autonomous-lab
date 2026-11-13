"""TASK 005 Phase 4/9: engine <-> backend integration tests.

The mining engine dispatches nonce batches through gpu.engine.ComputeEngine,
so backend selection, CUDA->CPU fault fallback, per-batch staleness checks
and network-adjusted block-time limits genuinely apply to mining - not only
to a benchmark probe. All tests run on the CPU backend; no GPU availability
or success is claimed anywhere.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gpu.engine import ComputeEngine, CudaError  # noqa: E402
from mining.engine.builder import build_candidate  # noqa: E402
from mining.engine.search import (  # noqa: E402
    EngineSearcher, MAX_FUTURE_BLOCK_TIME, OutcomeStatus, SearchError,
)
from mining.engine.template import parse_template  # noqa: E402
from mining.pow.validator import validate_header  # noqa: E402
from mining.pow.target import POW_LIMIT_REGTEST  # noqa: E402

from tests.test_engine_template import make_template  # noqa: E402

PAYOUT = bytes.fromhex("51")


def candidate_from(**overrides):
    return build_candidate(parse_template(make_template(**overrides)), PAYOUT)


class RaisingBackend:
    """A backend that faults on every batch, like a CUDA execution error."""

    name = "cuda"

    def batch(self, header, target, start, count, threads=128):
        raise CudaError("simulated device fault")


class SlowFakeBackend:
    """Returns tiny honest batches so staleness can fire mid-search."""

    name = "cpu"

    def __init__(self, chunk=50):
        self.chunk = chunk
        self.calls = 0

    def batch(self, header, target, start, count, threads=128):
        import hashlib
        self.calls += 1
        count = min(count, self.chunk)
        digests = []
        matches = []
        for nonce in range(start, start + count):
            digest = hashlib.sha256(hashlib.sha256(
                header[:76] + nonce.to_bytes(4, "little")).digest()).digest()
            digests.append(digest)
            matches.append(int.from_bytes(digest, "little") <= target)
        return digests, matches


class TestBackendDispatch(unittest.TestCase):
    def test_search_dispatches_through_compute_engine(self):
        candidate = candidate_from()
        compute = ComputeEngine(backend="cpu")
        outcome = EngineSearcher(
            compute=compute, batch_size=4096).search_candidate(
            candidate, max_seconds=30)
        self.assertEqual(outcome.status, OutcomeStatus.FOUND)
        self.assertEqual(outcome.backend, "cpu")
        self.assertIsNone(outcome.backend_fallback)
        check = validate_header(outcome.candidate.header.serialize(),
                                pow_limit=POW_LIMIT_REGTEST)
        self.assertTrue(check.valid, check.reason)
        self.assertEqual(check.hash_display, outcome.hash_display)

    def test_backend_fault_falls_back_to_cpu_and_records_it(self):
        candidate = candidate_from()
        compute = ComputeEngine(backend="cpu")
        compute.backend = RaisingBackend()  # fault injected at dispatch
        outcome = EngineSearcher(
            compute=compute, batch_size=4096).search_candidate(
            candidate, max_seconds=30)
        self.assertEqual(outcome.status, OutcomeStatus.FOUND)
        self.assertEqual(outcome.backend, "cpu")
        self.assertEqual(outcome.backend_fallback,
                         "CUDA execution failed; recomputed full batch on CPU")
        check = validate_header(outcome.candidate.header.serialize(),
                                pow_limit=POW_LIMIT_REGTEST)
        self.assertTrue(check.valid, check.reason)

    def test_stale_template_abandons_work_mid_search(self):
        # Impossible target (only the all-zero hash wins) so the search
        # would otherwise run to exhaustion; staleness must stop it early.
        candidate = candidate_from(bits="01010000")
        compute = ComputeEngine(backend="cpu")
        compute.backend = SlowFakeBackend(chunk=50)
        calls = {"stale_after": 3}

        def is_stale():
            return compute.backend.calls >= calls["stale_after"]

        outcome = EngineSearcher(
            compute=compute, batch_size=1000).search_candidate(
            candidate, is_stale=is_stale, max_seconds=60,
            update_time=False)
        self.assertEqual(outcome.status, OutcomeStatus.STALE)
        self.assertGreaterEqual(outcome.batches, 3)
        self.assertLess(outcome.hashes, 1 << 32)
        self.assertIsNone(outcome.nonce)


class TestBlockTimeConsensusLimits(unittest.TestCase):
    def test_mintime_beyond_future_limit_fails_closed(self):
        future = int(time.time()) + MAX_FUTURE_BLOCK_TIME + 100
        candidate = candidate_from(curtime=future, mintime=future)
        with self.assertRaises(SearchError):
            EngineSearcher(compute=ComputeEngine(backend="cpu"),
                           batch_size=64).search_candidate(
                candidate, max_seconds=5)

    def test_time_update_clamped_to_network_adjusted_limit(self):
        now = int(time.time())
        candidate = candidate_from(curtime=now, mintime=now - 10)
        compute = ComputeEngine(backend="cpu")
        outcome = EngineSearcher(
            compute=compute, batch_size=4096).search_candidate(
            candidate, max_seconds=30, network_time_offset=0)
        self.assertEqual(outcome.status, OutcomeStatus.FOUND)
        self.assertLessEqual(
            outcome.candidate.header.timestamp,
            int(time.time()) + MAX_FUTURE_BLOCK_TIME)
        self.assertGreaterEqual(outcome.candidate.header.timestamp,
                                outcome.candidate.mintime)

    def test_time_offset_shifts_future_limit(self):
        # A node whose timeoffset is -3h has a lower future limit; a
        # mintime beyond it must still fail closed.
        future = int(time.time()) - 3 * 3600 + MAX_FUTURE_BLOCK_TIME + 60
        candidate = candidate_from(curtime=future, mintime=future)
        with self.assertRaises(SearchError):
            EngineSearcher(compute=ComputeEngine(backend="cpu"),
                           batch_size=64).search_candidate(
                candidate, max_seconds=5, network_time_offset=-3 * 3600)


class TestBatchSizeManagement(unittest.TestCase):
    def test_adjust_batch_size_adapts_to_measured_time(self):
        from agent.autonomous.compute import ComputationManager
        manager = ComputationManager(requested="cpu", batch_size=65536)
        self.assertEqual(manager.batch_size, 65536)
        # Very slow batch -> halve
        self.assertEqual(manager.adjust_batch_size(9.0), 32768)
        # Very fast batch -> double
        self.assertEqual(manager.adjust_batch_size(0.01), 65536)
        # In-window batch -> unchanged
        self.assertEqual(manager.adjust_batch_size(1.0), 65536)

    def test_adjust_batch_size_bounded(self):
        from agent.autonomous.compute import (BATCH_MAX, BATCH_MIN,
                                              ComputationManager)
        manager = ComputationManager(requested="cpu", batch_size=BATCH_MIN)
        self.assertEqual(manager.adjust_batch_size(100.0), BATCH_MIN)
        manager = ComputationManager(requested="cpu", batch_size=BATCH_MAX)
        self.assertEqual(manager.adjust_batch_size(0.0001), BATCH_MAX)


if __name__ == "__main__":
    unittest.main()
