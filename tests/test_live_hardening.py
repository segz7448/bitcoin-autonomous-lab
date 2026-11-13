"""Live regtest checks for the TASK 004 hardening (real bitcoind, no mocked RPC).

Skipped unless bitcoind is available (BAL_BITCOIND or PATH).
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.analysis import BlockAnalyzer, verify_merkle_root  # noqa: E402
from blockchain.primitives import display_to_internal, merkle_root_checked  # noqa: E402
from blockchain.reader import BlockchainReader  # noqa: E402
from blockchain.service import MonitoringService  # noqa: E402
from blockchain.storage import ChainStore  # noqa: E402
from mining.block import assemble_block  # noqa: E402
from mining.pow.nonce_search import NonceSearcher  # noqa: E402
from mining.pow.target import POW_LIMIT_REGTEST  # noqa: E402
from mining.template_miner import build_block_from_template  # noqa: E402
from node.node_manager import NodeConfig, NodeManager  # noqa: E402
from node.rpc_client import RPCError  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestLiveHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.datadir = tempfile.mkdtemp(prefix="bal-hard-itest-")
        cls.manager = NodeManager(NodeConfig(bitcoind=BITCOIND, datadir=cls.datadir, rpc_port=18447))
        cls.rpc = cls.manager.start()
        cls.rpc.create_wallet("bal")
        cls.address = cls.rpc.get_new_address()
        cls.script = bytes.fromhex(cls.rpc.get_address_info(cls.address)["scriptPubKey"])
        cls.rpc.generate_to_address(101, cls.address)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.manager.stop()
        finally:
            shutil.rmtree(cls.datadir, ignore_errors=True)

    def test_merkle_mutation_flagged_here_and_rejected_by_core(self):
        """CVE-2012-2459 against a real node.

        [cb, t1, t2] and [cb, t1, t2, t2] share one merkle root and one
        header. Core must reject the duplicated form; our verifier must flag
        it; the honest block must then still be accepted (a mutated copy
        must not poison the valid block).
        """
        rpc = self.rpc
        rpc.send_to_address(rpc.get_new_address(), 1.0)
        rpc.send_to_address(rpc.get_new_address(), 2.0)
        template = rpc.get_block_template()
        self.assertEqual(len(template["transactions"]), 2)
        header, txs, _ = build_block_from_template(template, self.script)
        self.assertEqual(len(txs), 3)  # odd: the last tx is duplicated in the tree
        found = NonceSearcher().search_bits(header.serialize(), POW_LIMIT_REGTEST)
        self.assertTrue(found.found)
        header.nonce = found.nonce

        honest_hex = assemble_block(header, txs).hex()
        mutated_hex = assemble_block(header, txs + [txs[-1]]).hex()
        self.assertEqual(honest_hex[:160], mutated_hex[:160])  # identical header

        before = rpc.get_block_count()
        verdict = rpc.submit_block(mutated_hex)
        self.assertIsNotNone(verdict)
        self.assertIn("duplicate", verdict.lower())
        self.assertEqual(rpc.get_block_count(), before)

        self.assertIsNone(rpc.submit_block(honest_hex))
        self.assertEqual(rpc.get_block_count(), before + 1)

        block = rpc.get_block(header.hash_display(), 1)
        ids = block["tx"]
        self.assertEqual(len(ids), 3)
        self.assertTrue(verify_merkle_root(block))
        forged = dict(block, tx=ids + [ids[-1]])
        _, mutated_flag = merkle_root_checked([display_to_internal(t) for t in forged["tx"]])
        self.assertTrue(mutated_flag)
        self.assertFalse(verify_merkle_root(forged))  # same merkleroot, still rejected

    def test_analyzer_coinbase_check_is_satoshi_exact_on_real_blocks(self):
        rpc = self.rpc
        rpc.generate_to_address(1, self.address)
        analysis = BlockAnalyzer(BlockchainReader(rpc)).analyze(rpc.get_best_block_hash())
        self.assertTrue(analysis.coinbase_within_limit)
        self.assertTrue(analysis.merkle_root_verified)
        self.assertTrue(analysis.pow_meets_target)

    def test_event_driven_service_wakes_on_new_block_without_polling(self):
        rpc = self.rpc
        tmp = tempfile.mkdtemp(prefix="bal-evt-")
        store = ChainStore(os.path.join(tmp, "e.db"))
        self.addCleanup(store.close)
        svc = MonitoringService(rpc, store, poll_interval=0.05)
        svc.sync_once()
        t = threading.Thread(target=svc.run_event_driven, kwargs={"wait_ms": 20000}, daemon=True)
        t.start()
        time.sleep(0.5)  # service is now parked inside waitfornewblock
        base = store.count_blocks("active")
        t0 = time.monotonic()
        rpc.generate_to_address(1, self.address)
        deadline = t0 + 5
        while store.count_blocks("active") < base + 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        latency = time.monotonic() - t0
        self.assertEqual(store.count_blocks("active"), base + 1)
        self.assertLess(latency, 3.0)  # far below the 20 s wait window
        svc.stop()
        rpc.generate_to_address(1, self.address)  # releases the parked long-poll
        t.join(timeout=10)
        self.assertFalse(t.is_alive())

    def test_wait_for_new_block_times_out_cleanly(self):
        t0 = time.monotonic()
        tip = self.rpc.wait_for_new_block(300)
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)
        self.assertEqual(tip["hash"], self.rpc.get_best_block_hash())

    def test_rpc_error_surface_still_typed(self):
        with self.assertRaises(RPCError):
            self.rpc.get_block("00" * 32)


if __name__ == "__main__":
    unittest.main()
