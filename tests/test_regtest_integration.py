"""Live regtest integration: the TASK 001 milestone against real Bitcoin Core.

Skipped unless bitcoind is available (BAL_BITCOIND env var or on PATH).
Runs the complete milestone flow: start node, JSON-RPC connect,
getblockchaininfo, getblockcount, generatetoaddress, getblock, and
independent verification that the node recognizes the generated blocks.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.monitor import ChainMonitor  # noqa: E402
from node.node_manager import NodeConfig, NodeManager  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestRegtestIntegration(unittest.TestCase):
    RPC_PORT = 18445  # distinct from the default to avoid collisions

    def setUp(self):
        self.datadir = tempfile.mkdtemp(prefix="bal-itest-")
        self.manager = NodeManager(NodeConfig(
            bitcoind=BITCOIND, datadir=self.datadir, rpc_port=self.RPC_PORT,
        ))
        self.rpc = self.manager.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            self.manager.stop()
        except Exception:
            pass
        shutil.rmtree(self.datadir, ignore_errors=True)

    def test_milestone_flow(self):
        # 1-2. Node started; JSON-RPC connection works.
        net = self.rpc.get_network_info()
        self.assertEqual(net["networks"][0]["name"], "ipv4")

        # 3. getblockchaininfo on a fresh regtest chain.
        info = self.rpc.get_blockchain_info()
        self.assertEqual(info["chain"], "regtest")
        self.assertEqual(info["blocks"], 0)

        # 4. getblockcount.
        self.assertEqual(self.rpc.get_block_count(), 0)

        # Wallet for generatetoaddress (regtest block rewards stay local).
        self.rpc.create_wallet("bal")
        address = self.rpc.get_new_address()
        self.assertTrue(address.startswith("bcrt1"))

        # 5. Generate test blocks.
        monitor = ChainMonitor(self.rpc)
        reports = monitor.generate_and_verify(3, address)
        self.assertEqual(self.rpc.get_block_count(), 3)

        # 6. getblock on the new tip.
        tip_hash = self.rpc.get_best_block_hash()
        block = self.rpc.get_block(tip_hash)
        self.assertEqual(block["height"], 3)
        self.assertEqual(block["confirmations"], 1)
        self.assertGreaterEqual(block["nTx"], 1)

        # 7. The node recognizes every generated block, and our independent
        # header reconstruction + PoW check passes on each.
        self.assertTrue(all(r.ok for r in reports))
        for i, report in enumerate(reports, start=1):
            self.assertEqual(report.height, i)
            self.assertEqual(self.rpc.get_block_hash(i), report.block_hash)

        # Chain snapshot is coherent after generation.
        status = monitor.snapshot()
        self.assertEqual(status.blocks, 3)
        self.assertEqual(status.best_block_hash, tip_hash)


if __name__ == "__main__":
    unittest.main()
