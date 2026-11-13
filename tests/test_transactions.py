"""TransactionIntelligence: decode, fees, mempool tracking, unavailability."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.transactions import TransactionIntelligence  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402

TXID = "ab" * 32


class TestTransactionIntelligence(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeRPC()
        self.rpc.mine(2)
        self.txs = TransactionIntelligence(self.rpc)

    def test_unavailable_tx_reported_not_fabricated(self):
        result = self.txs.get_transaction("00" * 32)
        self.assertFalse(result.available)
        self.assertIn("No such", result.unavailable_reason)

    def test_mempool_tx_summary(self):
        self.rpc.add_mempool_tx(TXID)
        summary = self.txs.get_transaction(TXID)
        self.assertTrue(summary.available)
        self.assertTrue(summary.in_mempool)
        self.assertEqual(summary.confirmations, 0)
        self.assertEqual(summary.n_inputs, 1)
        self.assertEqual(summary.vsize, 200)

    def test_confirmed_tx(self):
        self.rpc.txs[TXID] = self.rpc._verbose_tx(TXID) | {
            "confirmations": 3, "blockhash": self.rpc.blocks[-1]["hash"]}
        summary = self.txs.get_transaction(TXID)
        self.assertTrue(summary.available)
        self.assertEqual(summary.confirmations, 3)
        self.assertFalse(summary.in_mempool)

    def test_mempool_status(self):
        self.rpc.add_mempool_tx(TXID, fee=0.00002)
        status = self.txs.mempool_status()
        self.assertEqual(status.size, 1)
        self.assertIn(TXID, status.txids)
        self.assertAlmostEqual(status.total_fee_btc, 0.00002)

    def test_detect_new_mempool_txs(self):
        self.rpc.add_mempool_tx(TXID)
        self.rpc.add_mempool_tx("cd" * 32)
        new = self.txs.detect_new_mempool_txs({TXID})
        self.assertEqual([t["txid"] for t in new], ["cd" * 32])

    def test_fee_from_mempool(self):
        self.rpc.add_mempool_tx(TXID, fee=0.00002)
        fee = self.txs.transaction_fee(TXID)
        self.assertEqual(fee["source"], "mempool")
        self.assertAlmostEqual(fee["fee_btc"], 0.00002)

    def test_fee_unavailable_for_confirmed(self):
        self.rpc.txs[TXID] = self.rpc._verbose_tx(TXID) | {"confirmations": 5}
        fee = self.txs.transaction_fee(TXID)
        self.assertIsNone(fee["fee_btc"])
        self.assertEqual(fee["source"], "confirmed")

    def test_decode_raw_transaction(self):
        summary = self.txs.decode_raw_transaction("deadbeef")
        self.assertTrue(summary.available)
        self.assertEqual(summary.txid, "ab" * 32)


if __name__ == "__main__":
    unittest.main()
