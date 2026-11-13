"""Live Bitcoin Core regtest integration for the PoW engine.

Skipped unless bitcoind is available (BAL_BITCOIND or PATH). No mocked RPC:
blocks are produced by Core (generatetoaddress) and by this engine (via
getblocktemplate + submitblock), and every verdict is compared to Core's.
"""
import os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.pow.block_header import BlockHeader
from mining.pow.core_verify import (mine_block_with_engine, tamper_to_invalid_pow,
                                    verify_block, verify_chain)
from mining.pow.target import POW_LIMIT_REGTEST
from node.node_manager import NodeConfig, NodeManager

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestCoreIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.datadir = tempfile.mkdtemp(prefix="bal-pow-itest-")
        cls.manager = NodeManager(NodeConfig(bitcoind=BITCOIND, datadir=cls.datadir, rpc_port=18446))
        cls.rpc = cls.manager.start()
        cls.rpc.create_wallet("bal")
        cls.address = cls.rpc.get_new_address()
        cls.script = bytes.fromhex(cls.rpc.get_address_info(cls.address)["scriptPubKey"])
        cls.rpc.generate_to_address(8, cls.address)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.manager.stop()
        finally:
            shutil.rmtree(cls.datadir, ignore_errors=True)

    def test_every_core_block_verifies_independently(self):
        report = verify_chain(self.rpc)
        self.assertEqual(report["chain"], "regtest")
        self.assertGreaterEqual(len(report["blocks"]), 9)       # genesis + 8
        for row in report["blocks"]:
            failed = [k for k, v in row["checks"].items() if not v]
            self.assertEqual(failed, [], f"height {row['height']}")
        self.assertTrue(report["all_ok"])

    def test_genesis_regtest_header_matches_core(self):
        h = self.rpc.get_block_hash(0)
        meta = self.rpc.get_block_header(h)
        self.assertEqual(BlockHeader.from_rpc(meta).hash_display(), h)

    def test_engine_mined_block_accepted_by_core(self):
        before = self.rpc.get_block_count()
        out = mine_block_with_engine(self.rpc, self.script, POW_LIMIT_REGTEST)
        self.assertIsNone(out["submitblock_result"])
        self.assertTrue(out["accepted_and_matches"])
        self.assertEqual(self.rpc.get_block_count(), before + 1)
        self.assertEqual(self.rpc.get_best_block_hash(), out["engine_hash"])
        self.assertTrue(verify_block(self.rpc, out["engine_hash"], POW_LIMIT_REGTEST)["all_ok"])

    def test_core_rejects_what_we_reject_high_hash(self):
        tip = self.rpc.get_best_block_hash()
        block_hex = self.rpc.call("getblock", tip, 0)
        bad_hex, ours = tamper_to_invalid_pow(block_hex, POW_LIMIT_REGTEST)
        self.assertFalse(ours["valid"])
        self.assertEqual(ours["reason"], "high-hash")
        # Core's verdict must agree.
        self.assertEqual(self.rpc.submit_block(bad_hex), "high-hash")
        self.assertEqual(self.rpc.get_best_block_hash(), tip)

    def test_core_rejects_bad_bits_when_we_do(self):
        # A header claiming an easier target than regtest allows is rejected by us and by Core.
        tip = self.rpc.get_best_block_hash()
        raw = bytearray.fromhex(self.rpc.call("getblock", tip, 0))
        raw[72:76] = (0x207FFFFF - 0).to_bytes(4, "little")      # unchanged baseline
        raw[72:76] = (0x2100FFFF).to_bytes(4, "little")           # above powLimit
        from mining.pow.validator import validate_header
        self.assertEqual(validate_header(bytes(raw[:80]), POW_LIMIT_REGTEST).reason, "target-above-limit")
        self.assertIn(self.rpc.submit_block(raw.hex()), ("bad-diffbits", "high-hash"))
        self.assertEqual(self.rpc.get_best_block_hash(), tip)


if __name__ == "__main__":
    unittest.main()
