"""ChainStore: SQLite persistence, reorg-safe updates, restart survival."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.reader import BlockchainReader  # noqa: E402
from blockchain.storage import ChainStore  # noqa: E402
from blockchain.transactions import TransactionIntelligence  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402


class TestChainStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bal-store-test-")
        self.path = os.path.join(self.tmp, "chain.db")
        self.rpc = FakeRPC()
        self.hashes = self.rpc.mine(4)
        self.reader = BlockchainReader(self.rpc)

    def _store_blocks(self, store, heights):
        for h in heights:
            store.record_block(self.reader.block_at_height(h))

    def test_record_and_query_blocks(self):
        with ChainStore(self.path) as store:
            self._store_blocks(store, range(4))
            self.assertEqual(store.count_blocks(), 4)
            self.assertEqual(store.count_blocks("active"), 4)
            self.assertEqual(store.block_hash_at(2), self.hashes[2])
            recent = store.recent_blocks(2)
            self.assertEqual([b["height"] for b in recent], [3, 2])
            stored = store.get_block(self.hashes[1])
            self.assertEqual(stored["n_tx"], 1)
            self.assertGreater(stored["processed_at"], 0)

    def test_reorg_marks_orphaned_and_keeps_history(self):
        with ChainStore(self.path) as store:
            self._store_blocks(store, range(4))
            orphaned = store.mark_orphaned_from(3)
            self.assertEqual([b["height"] for b in orphaned], [3])
            self.assertEqual(store.count_blocks("orphaned"), 1)
            self.assertIsNone(store.block_hash_at(3))
            # The winning branch coexists with the orphaned record.
            self.rpc.invalidate_tip()
            competing = self.rpc.mine(1)[0]
            store.record_block(self.reader.block_summary(competing))
            self.assertEqual(store.count_blocks("active"), 4)
            self.assertEqual(store.count_blocks(), 5)
            self.assertEqual(store.block_hash_at(3), competing)
            self.assertEqual(store.get_block(self.hashes[3])["status"],
                             "orphaned")

    def test_sync_state_roundtrip(self):
        with ChainStore(self.path) as store:
            store.set_sync(3, self.hashes[3])
            sync = store.get_sync()
            self.assertEqual(sync["last_height"], 3)
            self.assertEqual(sync["last_hash"], self.hashes[3])
            store.set_sync(4, "ee" * 32)
            self.assertEqual(store.get_sync()["last_height"], 4)

    def test_transactions_upsert(self):
        with ChainStore(self.path) as store:
            self.rpc.add_mempool_tx("ab" * 32, fee=0.00002)
            summary = TransactionIntelligence(self.rpc).get_transaction(
                "ab" * 32)
            store.record_transaction(summary, status="mempool")
            summary.confirmations = 1
            summary.block_hash = self.hashes[0]
            store.record_transaction(summary)
            self.assertEqual(store.count_transactions(), 1)
            stored = store.get_transaction("ab" * 32)
            self.assertEqual(stored["status"], "confirmed")
            self.assertEqual(stored["block_hash"], self.hashes[0])

    def test_persistence_across_restart(self):
        with ChainStore(self.path) as store:
            self._store_blocks(store, range(4))
            store.set_sync(3, self.hashes[3])
            store.record_event("test", "first run")
        with ChainStore(self.path) as reopened:
            self.assertEqual(reopened.count_blocks(), 4)
            self.assertEqual(reopened.get_sync()["last_height"], 3)
            self.assertEqual(reopened.events()[0]["kind"], "test")

    def test_mempool_sightings(self):
        with ChainStore(self.path) as store:
            store.record_mempool_sighting("ab" * 32, 0.00002, 200)
            store.record_mempool_sighting("ab" * 32, None, None)
            sightings = store.mempool_sightings()
            self.assertEqual(len(sightings), 1)
            self.assertEqual(sightings[0]["fee_btc"], 0.00002)


if __name__ == "__main__":
    unittest.main()
