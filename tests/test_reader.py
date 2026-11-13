"""BlockchainReader: typed RPC queries against the fake node."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.reader import BlockchainReader  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402


class TestBlockchainReader(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeRPC()
        self.hashes = self.rpc.mine(4)
        self.reader = BlockchainReader(self.rpc)

    def test_chain_height_and_best_hash(self):
        self.assertEqual(self.reader.chain_height(), 3)
        self.assertEqual(self.reader.best_block_hash(), self.hashes[-1])

    def test_block_hash_at_and_summary(self):
        block = self.reader.block_at_height(2)
        self.assertEqual(block.height, 2)
        self.assertEqual(block.hash, self.hashes[2])
        self.assertEqual(block.prev_hash, self.hashes[1])
        self.assertEqual(block.n_tx, 1)
        self.assertGreater(block.time, 0)
        self.assertGreater(block.size, 0)

    def test_header_matches_block(self):
        header = self.reader.header(self.hashes[2])
        self.assertEqual(header.merkle_root,
                         self.reader.block_summary(self.hashes[2]).merkle_root)
        self.assertGreater(header.target(), 0)

    def test_block_txids(self):
        txids = self.reader.block_txids(self.hashes[1])
        self.assertEqual(len(txids), 1)

    def test_chain_tips_active(self):
        tips = self.reader.chain_tips()
        self.assertEqual(tips[0].status, "active")
        self.assertEqual(tips[0].height, 3)

    def test_recent_blocks_newest_first(self):
        recent = self.reader.recent_blocks(2)
        self.assertEqual([b.height for b in recent], [3, 2])

    def test_block_with_txs_decodes(self):
        block = self.reader.block_with_txs(self.hashes[0])
        self.assertEqual(block["tx"][0]["txid"], self.rpc.blocks[0]["tx"][0])
        self.assertIn("vout", block["tx"][0])


if __name__ == "__main__":
    unittest.main()
