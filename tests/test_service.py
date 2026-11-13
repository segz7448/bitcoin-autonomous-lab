"""MonitoringService: sync, new blocks, reorgs, failure resilience."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.service import MonitoringService  # noqa: E402
from blockchain.storage import ChainStore  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402


class TestMonitoringService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bal-svc-test-")
        self.path = os.path.join(self.tmp, "chain.db")
        self.rpc = FakeRPC()
        self.hashes = self.rpc.mine(3)
        self.store = ChainStore(self.path)
        self.addCleanup(self.store.close)
        self.service = MonitoringService(self.rpc, self.store,
                                         poll_interval=0.01,
                                         rpc_factory=lambda: self.rpc)

    def test_initial_sync_stores_chain(self):
        report = self.service.sync_once()
        self.assertTrue(report.ok)
        self.assertEqual(report.synced_height_after, 2)
        self.assertEqual(len(report.new_blocks), 3)
        self.assertEqual(self.store.count_blocks("active"), 3)
        self.assertEqual(self.store.get_sync()["last_height"], 2)

    def test_new_blocks_detected_incrementally(self):
        self.service.sync_once()
        new = self.rpc.mine(2)
        report = self.service.sync_once()
        self.assertEqual(report.new_blocks, new)
        self.assertEqual(self.store.count_blocks("active"), 5)

    def test_idle_cycle_is_cheap(self):
        self.service.sync_once()
        calls_before = self.rpc.calls
        report = self.service.sync_once()
        self.assertTrue(report.ok)
        self.assertEqual(report.new_blocks, [])
        self.assertFalse(report.reorg_detected)
        # Idle cycle: one getblockcount + one getblockhash tip check only.
        self.assertEqual(self.rpc.calls - calls_before, 2)

    def test_reorg_detected_and_orphaned(self):
        self.service.sync_once()
        forked = self.rpc.invalidate_tip()
        competing = self.rpc.mine(2)
        report = self.service.sync_once()
        self.assertTrue(report.reorg_detected)
        self.assertIn(forked, report.orphaned_blocks)
        self.assertTrue(report.in_sync)
        self.assertEqual(self.store.count_blocks("orphaned"), 1)
        self.assertEqual(self.store.block_hash_at(3), competing[1])

    def test_reorg_walks_back_to_fork_point(self):
        self.service.sync_once()
        self.rpc.invalidate_tip()
        self.rpc.invalidate_tip()
        self.rpc.mine(1)  # one new block from height 1
        report = self.service.sync_once()
        self.assertTrue(report.reorg_detected)
        self.assertEqual(len(report.orphaned_blocks), 2)
        self.assertEqual(self.store.count_blocks("active"), 2)
        self.assertTrue(report.in_sync)

    def test_rpc_failure_does_not_crash_and_recovers(self):
        self.service.sync_once()
        self.rpc.failures = 2
        fail1 = self.service.sync_once()
        self.assertFalse(fail1.ok)
        self.assertEqual(fail1.consecutive_failures, 1)
        fail2 = self.service.sync_once()
        self.assertEqual(fail2.consecutive_failures, 2)
        recovered = self.service.sync_once()
        self.assertTrue(recovered.ok)
        self.assertEqual(recovered.consecutive_failures, 0)
        events = [e["kind"] for e in self.store.events()]
        self.assertIn("rpc_unreachable", events)

    def test_reconnect_factory_used_after_failure(self):
        self.service.sync_once()
        calls = []

        def factory():
            calls.append(1)
            return self.rpc

        self.service._rpc_factory = factory
        self.rpc.failures = 2
        self.assertFalse(self.service.sync_once().ok)
        self.assertFalse(self.service.sync_once().ok)
        self.assertTrue(self.service.sync_once().ok)
        self.assertTrue(calls, "factory should be consulted after a failure")

    def test_run_loop_with_iterations(self):
        self.rpc.failures = 2
        self.service.run(iterations=3)  # must not hang on failures
        report = self.service.sync_once()
        self.assertTrue(report.ok)

    def test_block_listeners_fire(self):
        seen = []
        self.service.add_block_listener(seen.append)
        self.service.sync_once()
        self.rpc.mine(1)
        self.service.sync_once()
        self.assertEqual(len(seen), 4)

    def test_status_view(self):
        self.service.sync_once()
        status = self.service.status()
        self.assertTrue(status["in_sync"])
        self.assertEqual(status["synced_height"], status["node_height"])
        self.assertEqual(status["stored_blocks"], 3)

    def test_record_block_transactions(self):
        self.rpc.mine(1, with_txs=True)
        tip = self.rpc.blocks[-1]
        count = self.service.record_block_transactions(tip["hash"])
        self.assertEqual(count, 3)
        self.assertEqual(self.store.count_transactions(), 3)
        stored = self.store.get_transaction(tip["tx"][1])
        self.assertAlmostEqual(stored["fee_btc"], 0.00001)


if __name__ == "__main__":
    unittest.main()
