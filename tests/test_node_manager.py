"""Node manager configuration and safety guards (no live node needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.node_manager import (  # noqa: E402
    ChainMismatchError, NodeConfig, NodeManager, NodeStartupError,
)


class _FakeRPC:
    def __init__(self, chain):
        self._chain = chain

    def get_blockchain_info(self):
        return {"chain": self._chain}


class TestNodeConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = NodeConfig()
        self.assertEqual(cfg.rpc_port, 18443)
        self.assertEqual(cfg.rpc_url, "http://127.0.0.1:18443")
        self.assertTrue(str(cfg.cookie_path).endswith(
            os.path.join("regtest", ".cookie")))

    def test_from_env(self):
        cfg = NodeConfig.from_env({
            "BAL_BITCOIND": "/opt/bitcoin/bin/bitcoind",
            "BAL_DATADIR": "/tmp/bal-data",
            "BAL_RPC_PORT": "18555",
        })
        self.assertEqual(cfg.bitcoind, "/opt/bitcoin/bin/bitcoind")
        self.assertEqual(cfg.rpc_port, 18555)
        self.assertEqual(str(cfg.regtest_dir),
                         os.path.join("/tmp/bal-data", "regtest"))


class TestRegtestGuard(unittest.TestCase):
    def test_non_regtest_chain_rejected(self):
        manager = NodeManager(NodeConfig(datadir="/tmp/bal-test-nonregtest"))
        for chain in ("main", "test", "testnet4", "signet", ""):
            with self.subTest(chain=chain):
                with self.assertRaises(ChainMismatchError):
                    manager._enforce_regtest(_FakeRPC(chain))

    def test_regtest_chain_accepted(self):
        manager = NodeManager(NodeConfig(datadir="/tmp/bal-test-regtest"))
        manager._enforce_regtest(_FakeRPC("regtest"))  # no raise


class TestStartupFailures(unittest.TestCase):
    def test_missing_bitcoind_fails_clearly(self):
        manager = NodeManager(NodeConfig(
            bitcoind="definitely-not-a-real-bitcoind-binary",
            datadir="/tmp/bal-test-missing",
        ))
        with self.assertRaises(NodeStartupError) as ctx:
            manager.start(timeout=5)
        self.assertIn("bitcoind not found", str(ctx.exception))

    def test_client_without_cookie_fails(self):
        manager = NodeManager(NodeConfig(datadir="/tmp/bal-test-nocookie"))
        with self.assertRaises(NodeStartupError):
            manager.client()


if __name__ == "__main__":
    unittest.main()
