"""Live regtest integration: the TASK 002 engine against real Bitcoin Core.

Skipped unless bitcoind is available (BAL_BITCOIND env var or on PATH).
Exercises the Intelligence Engine end to end: real RPC monitoring,
transaction intelligence, merkle-verified block analysis, the monitoring
service with reorg detection, and SQLite persistence across a restart.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.analysis import BlockAnalyzer  # noqa: E402
from blockchain.reader import BlockchainReader  # noqa: E402
from blockchain.service import MonitoringService  # noqa: E402
from blockchain.storage import ChainStore  # noqa: E402
from blockchain.transactions import TransactionIntelligence  # noqa: E402
from node.node_manager import NodeConfig, NodeManager  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestRegtestIntelligence(unittest.TestCase):
    RPC_PORT = 18447  # distinct from other suites to avoid collisions

    def setUp(self):
        self.datadir = tempfile.mkdtemp(prefix="bal-itest2-")
        self.manager = NodeManager(NodeConfig(
            bitcoind=BITCOIND, datadir=self.datadir, rpc_port=self.RPC_PORT,
            extra_args=("-txindex",),
        ))
        self.rpc = self.manager.start()
        if "bal" not in self.rpc.list_wallets():
            self.rpc.create_wallet("bal")
        self.address = self.rpc.get_new_address()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            self.manager.stop()
        except Exception:
            pass
        shutil.rmtree(self.datadir, ignore_errors=True)

    def test_intelligence_engine_live(self):
        reader = BlockchainReader(self.rpc)
        self.rpc.generate_to_address(101, self.address)  # mature coinbase
        hashes = self.rpc.generate_to_address(3, self.address)

        # Monitoring: height, blocks, headers, tips.
        self.assertEqual(reader.chain_height(), 104)
        block = reader.block_summary(hashes[-1])
        self.assertEqual(block.hash, hashes[-1])
        self.assertEqual(reader.header(hashes[-1]).merkle_root,
                         block.merkle_root)
        self.assertEqual(reader.chain_tips()[0].status, "active")
        self.assertGreater(block.time, 0)

        # Transaction intelligence on a real spend.
        txs = TransactionIntelligence(self.rpc)
        send_txid = self.rpc.send_to_address(self.rpc.get_new_address(), 1.0)
        self.assertIn(send_txid, txs.mempool_status().txids)
        entry = txs.mempool_entry(send_txid)
        self.assertGreater(entry["fee_btc"], 0)
        decoded = txs.get_transaction(send_txid)
        self.assertTrue(decoded.available)
        self.assertGreaterEqual(decoded.n_outputs, 1)
        self.assertFalse(
            txs.get_transaction("00" * 32).available)
        mined = self.rpc.generate_to_address(1, self.address)[0]
        self.assertGreaterEqual(
            txs.get_transaction(send_txid).confirmations, 1)

        # Block analysis: merkle root and economics from real data.
        analysis = BlockAnalyzer(reader).analyze(mined)
        self.assertTrue(analysis.merkle_root_verified)
        self.assertTrue(analysis.pow_meets_target)
        self.assertTrue(analysis.coinbase_within_limit)
        self.assertGreater(analysis.total_fees_btc, 0)
        self.assertEqual(analysis.expected_subsidy_btc, 50.0)

        # Monitoring service: sync, reorg detection, persistence.
        db_path = os.path.join(self.datadir, "chain.db")
        with ChainStore(db_path) as store:
            service = MonitoringService(self.rpc, store)
            report = service.sync_once()
            self.assertTrue(report.ok)
            self.assertEqual(report.synced_height_after, 105)
            service.record_block_transactions(mined)
            self.assertGreaterEqual(store.count_transactions(), 1)
            forked = mined
            self.rpc.invalidate_block(forked)
            # A fresh address guarantees the competing branch has
            # different block hashes than the invalidated one.
            self.rpc.generate_to_address(2, self.rpc.get_new_address())
            report = service.sync_once()
            self.assertTrue(report.reorg_detected)
            self.assertIn(forked, report.orphaned_blocks)
            self.assertTrue(service.status()["in_sync"])

        # State survives a restart of the store.
        with ChainStore(db_path) as reopened:
            self.assertEqual(reopened.get_sync()["last_height"], 106)
            self.assertGreaterEqual(reopened.count_blocks("orphaned"), 1)


if __name__ == "__main__":
    unittest.main()
