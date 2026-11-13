"""TASK 005 Phase 4: Proof-of-Work search behaviour tests."""

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.engine.builder import build_candidate  # noqa: E402
from mining.engine.search import (  # noqa: E402
    EngineSearcher, OutcomeStatus, SearchError,
)
from mining.engine.template import parse_template  # noqa: E402
from mining.pow.validator import validate_header  # noqa: E402
from mining.pow.target import POW_LIMIT_REGTEST  # noqa: E402

from tests.test_engine_template import make_template  # noqa: E402

PAYOUT = bytes.fromhex("51")

# Valid compact encoding of target = 1: only the all-zero hash wins, so a
# bounded scan always exhausts.
IMPOSSIBLE_BITS = "01010000"


def candidate_from(**overrides):
    return build_candidate(parse_template(make_template(**overrides)), PAYOUT)


class TestSearchFound(unittest.TestCase):
    def test_found_at_regtest_difficulty(self):
        candidate = candidate_from()
        outcome = EngineSearcher().search_candidate(candidate, max_seconds=30)
        self.assertEqual(outcome.status, OutcomeStatus.FOUND)
        self.assertTrue(outcome.found)
        self.assertIsNotNone(outcome.nonce)
        self.assertGreaterEqual(outcome.hashes, 1)
        self.assertGreater(outcome.hashrate, 0)
        self.assertEqual(outcome.batches, 1)
        self.assertEqual(outcome.extranonce_counter, 0)
        self.assertEqual(outcome.candidate.header.nonce, outcome.nonce)

    def test_solution_independently_verified(self):
        candidate = candidate_from()
        outcome = EngineSearcher().search_candidate(candidate, max_seconds=30)
        check = validate_header(outcome.candidate.header.serialize(),
                                pow_limit=POW_LIMIT_REGTEST)
        self.assertTrue(check.valid, check.reason)
        self.assertEqual(check.hash_display, outcome.hash_display)
        self.assertEqual(outcome.candidate.block_hash_display(),
                         outcome.hash_display)


class TestSearchHandling(unittest.TestCase):
    def test_exhaustion_escalates_extranonce_then_reports(self):
        candidate = candidate_from(bits=IMPOSSIBLE_BITS)
        outcome = EngineSearcher().search_candidate(
            candidate, nonce_end=200, max_extranonce_rounds=2,
            update_time=False)
        self.assertEqual(outcome.status, OutcomeStatus.EXHAUSTED)
        self.assertEqual(outcome.hashes, 200 * 3)  # base round + 2 escalations
        self.assertEqual(outcome.batches, 3)
        self.assertEqual(outcome.extranonce_counter, 2)

    def test_extranonce_escalation_changes_work(self):
        candidate = candidate_from(bits=IMPOSSIBLE_BITS)
        roots = [candidate.header.serialize()]
        probe = candidate
        for counter in (1, 2):
            probe = probe.with_extranonce(counter)
            roots.append(probe.header.serialize())
        self.assertEqual(len(set(roots)), 3)

    def test_stale_template_abandons_work(self):
        candidate = candidate_from()
        outcome = EngineSearcher().search_candidate(
            candidate, is_stale=lambda: True)
        self.assertEqual(outcome.status, OutcomeStatus.STALE)
        self.assertEqual(outcome.hashes, 0)

    def test_stale_detected_between_rounds(self):
        candidate = candidate_from(bits=IMPOSSIBLE_BITS)
        calls = {"n": 0}

        def stale_after_first_round():
            calls["n"] += 1
            return calls["n"] > 1

        outcome = EngineSearcher().search_candidate(
            candidate, is_stale=stale_after_first_round,
            nonce_end=100, update_time=False)
        self.assertEqual(outcome.status, OutcomeStatus.STALE)
        self.assertEqual(outcome.hashes, 100)

    def test_cancellation(self):
        stop = threading.Event()
        stop.set()
        candidate = candidate_from()
        outcome = EngineSearcher(stop_event=stop).search_candidate(candidate)
        self.assertEqual(outcome.status, OutcomeStatus.CANCELLED)
        self.assertEqual(outcome.hashes, 0)

    def test_time_budget_limit(self):
        candidate = candidate_from(bits=IMPOSSIBLE_BITS)
        outcome = EngineSearcher().search_candidate(
            candidate, max_seconds=0.05, update_time=False)
        self.assertEqual(outcome.status, OutcomeStatus.LIMIT)
        self.assertGreater(outcome.hashes, 0)

    def test_invalid_target_fails_closed(self):
        candidate = candidate_from()
        candidate.bits = 0x21800000  # decodes to a zero target
        with self.assertRaises(SearchError):
            EngineSearcher().search_candidate(candidate)

    def test_block_time_updates_between_rounds(self):
        # Template time is fixed in 2023; the search must bump it to now.
        outcome = EngineSearcher().search_candidate(
            candidate_from(bits=IMPOSSIBLE_BITS),
            nonce_end=10, max_extranonce_rounds=0)
        self.assertEqual(outcome.status, OutcomeStatus.EXHAUSTED)
        self.assertGreater(outcome.candidate.header.timestamp, 1_700_000_000)


if __name__ == "__main__":
    unittest.main()
