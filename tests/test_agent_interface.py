"""AgentInterface intelligence operations: structured answers, no exceptions."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.interface import AgentInterface  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402


class FakeManager:
    """Stand-in for NodeManager backed by the fake node."""

    def __init__(self, rpc):
        self._rpc = rpc

    def client(self):
        return self._rpc


class TestAgentIntelligence(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeRPC()
        self.hashes = self.rpc.mine(12)
        self.tmp = tempfile.mkdtemp(prefix="bal-agent-test-")
        self.db = os.path.join(self.tmp, "chain.db")
        self.agent = AgentInterface(FakeManager(self.rpc))

    def test_current_block_height(self):
        result = self.agent.current_block_height()
        self.assertTrue(result["ok"])
        self.assertEqual(result["height"], 11)

    def test_latest_block_hash(self):
        result = self.agent.latest_block_hash()
        self.assertTrue(result["ok"])
        self.assertEqual(result["block_hash"], self.hashes[-1])

    def test_latest_blocks(self):
        result = self.agent.latest_blocks(10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 10)
        self.assertEqual(result["blocks"][0]["height"], 11)

    def test_analyze_block(self):
        result = self.agent.analyze_block(self.hashes[5])
        self.assertTrue(result["ok"])
        analysis = result["analysis"]
        self.assertTrue(analysis["merkle_root_verified"])
        self.assertTrue(analysis["pow_meets_target"])

    def test_latest_block_tx_count(self):
        result = self.agent.latest_block_tx_count()
        self.assertTrue(result["ok"])
        self.assertEqual(result["n_tx"], 1)

    def test_network_difficulty(self):
        result = self.agent.network_difficulty()
        self.assertTrue(result["ok"])
        self.assertGreater(result["difficulty"], 0)

    def test_mempool_status(self):
        self.rpc.add_mempool_tx("ab" * 32)
        result = self.agent.mempool_status()
        self.assertTrue(result["ok"])
        self.assertEqual(result["mempool"]["size"], 1)

    def test_has_new_block(self):
        first = self.agent.has_new_block(self.db)
        self.assertTrue(first["ok"])
        self.assertTrue(first["new_block"])  # initial sync
        again = self.agent.has_new_block(self.db)
        self.assertFalse(again["new_block"])
        self.rpc.mine(1)
        third = self.agent.has_new_block(self.db)
        self.assertTrue(third["new_block"])

    def test_get_transaction_unavailable_is_structured(self):
        result = self.agent.get_transaction("00" * 32)
        self.assertTrue(result["ok"])
        self.assertFalse(result["transaction"]["available"])

    def test_errors_are_structured_not_raised(self):
        broken = AgentInterface(FakeManager(None))
        result = broken.current_block_height()
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
