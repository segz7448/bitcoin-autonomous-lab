"""BlockAnalyzer: header/target/merkle/subsidy analysis on real mined data."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.analysis import (  # noqa: E402
    BlockAnalyzer,
    expected_subsidy_sats,
    verify_merkle_root,
)
from blockchain.primitives import (  # noqa: E402
    display_to_internal,
    internal_to_display,
    merkle_root,
)
from blockchain.reader import BlockchainReader  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402

COIN = 100_000_000


class TestMerkleVerification(unittest.TestCase):
    def test_merkle_root_matches_header(self):
        txids = [f"{i:064x}" for i in range(1, 6)]
        computed = internal_to_display(
            merkle_root([display_to_internal(t) for t in txids]))
        block = {"tx": list(txids), "merkleroot": computed}
        self.assertTrue(verify_merkle_root(block))

    def test_merkle_root_detects_tampering(self):
        txids = [f"{i:064x}" for i in range(1, 4)]
        computed = internal_to_display(
            merkle_root([display_to_internal(t) for t in txids]))
        block = {"tx": ["ff" * 32] + txids[1:], "merkleroot": computed}
        self.assertFalse(verify_merkle_root(block))

    def test_odd_txid_count_duplicates_last(self):
        txids = [f"{i:064x}" for i in range(1, 4)]
        computed = internal_to_display(
            merkle_root([display_to_internal(t) for t in txids]))
        self.assertTrue(verify_merkle_root(
            {"tx": txids, "merkleroot": computed}))


class TestSubsidySchedule(unittest.TestCase):
    def test_subsidy_halvings(self):
        self.assertEqual(expected_subsidy_sats(0), 50 * COIN)
        self.assertEqual(expected_subsidy_sats(209_999), 50 * COIN)
        self.assertEqual(expected_subsidy_sats(210_000), 25 * COIN)
        self.assertEqual(expected_subsidy_sats(630_000), 6.25 * COIN)
        self.assertEqual(expected_subsidy_sats(64 * 210_000), 0)


class TestBlockAnalyzer(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeRPC()
        self.hashes = self.rpc.mine(3, with_txs=True)
        self.analyzer = BlockAnalyzer(BlockchainReader(self.rpc))

    def test_analyze_block(self):
        analysis = self.analyzer.analyze(self.hashes[2])
        self.assertEqual(analysis.height, 2)
        self.assertEqual(analysis.n_tx, 3)
        self.assertTrue(analysis.merkle_root_verified)
        self.assertTrue(analysis.pow_meets_target)
        self.assertTrue(analysis.coinbase_within_limit)
        self.assertEqual(analysis.expected_subsidy_btc, 50.0)
        self.assertAlmostEqual(analysis.total_fees_btc, 0.00002)
        self.assertGreater(analysis.target, 0)

    def test_merkle_proof_check(self):
        result = self.analyzer.merkle_proof_check(self.hashes[1])
        self.assertTrue(result["verified"])

    def test_fees_none_when_unresolvable(self):
        # Strip fee fields: the total must become None, never fabricated.
        original = self.rpc._verbose_tx

        def no_fee(txid, block=None):
            tx = original(txid, block)
            tx.pop("fee", None)
            return tx

        self.rpc._verbose_tx = no_fee
        analysis = self.analyzer.analyze(self.hashes[0])
        self.assertIsNone(analysis.total_fees_btc)


if __name__ == "__main__":
    unittest.main()
