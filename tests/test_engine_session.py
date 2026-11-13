"""TASK 005 Phases 5-6: submission, acceptance verification, statistics."""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.primitives import internal_to_display, sha256d_fast  # noqa: E402
from mining.engine.session import CycleStatus, MiningEngine  # noqa: E402
from mining.engine.stats import MiningStatsStore  # noqa: E402

from tests.test_engine_template import GENESIS, make_template  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")
PAYOUT = bytes.fromhex("51")


class FakeChainRPC:
    """A minimal in-memory regtest chain that honestly accepts valid PoW."""

    def __init__(self, chain="regtest", accept=True):
        self.chain = chain
        self.accept = accept
        self.blocks = 0
        self.best = GENESIS
        self.submitted = []

    def get_blockchain_info(self):
        return {"chain": self.chain, "blocks": self.blocks,
                "bestblockhash": self.best}

    def get_block_template(self):
        now = int(time.time())
        return make_template(height=self.blocks + 1,
                             previousblockhash=self.best,
                             curtime=now, mintime=now - 10)

    def get_best_block_hash(self):
        return self.best

    def submit_block(self, block_hex):
        self.submitted.append(block_hex)
        if not self.accept:
            return "bad-txn"
        header = bytes.fromhex(block_hex)[:80]
        self.best = internal_to_display(sha256d_fast(header))
        self.blocks += 1
        return None

    def get_block(self, block_hash):
        return {"hash": block_hash, "confirmations": 1,
                "height": self.blocks}


class SessionFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bal-stats-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db_path = os.path.join(self.tmp, "mining.db")


class TestMiningCycle(SessionFixture):
    def test_accepted_cycle_recorded(self):
        rpc = FakeChainRPC()
        with MiningStatsStore(self.db_path) as stats:
            engine = MiningEngine(rpc, stats=stats)
            result = engine.mine_cycle(PAYOUT, max_seconds=30)
            self.assertEqual(result.status, CycleStatus.ACCEPTED)
            self.assertTrue(result.accepted)
            self.assertEqual(len(rpc.submitted), 1)
            self.assertEqual(rpc.blocks, 1)
            self.assertIsNotNone(result.nonce)
            self.assertGreater(result.hashes, 0)
            self.assertGreater(result.hashrate_avg, 0)
            self.assertGreaterEqual(result.hashrate_peak, result.hashrate_avg * 0)
            self.assertEqual(result.backend, "cpu")
            self.assertEqual(result.coinbase_value, 5_000_000_000)
            self.assertEqual(result.fees, 0)
            self.assertEqual(result.chain_height_after, 1)

            history = stats.history()
            self.assertEqual(len(history), 1)
            row = history[0]
            self.assertEqual(row["session_id"], result.session_id)
            self.assertEqual(row["accepted"], 1)
            self.assertEqual(row["submit_result"], "accepted")
            self.assertEqual(row["block_hash"], result.block_hash)

        # Statistics survive a restart (new store object, same file).
        with MiningStatsStore(self.db_path) as reopened:
            self.assertEqual(len(reopened.history()), 1)
            totals = reopened.totals()
            self.assertEqual(totals["cycles"], 1)
            self.assertEqual(totals["accepted"], 1)

    def test_rejection_recorded_with_reason(self):
        rpc = FakeChainRPC(accept=False)
        with MiningStatsStore(self.db_path) as stats:
            engine = MiningEngine(rpc, stats=stats)
            result = engine.mine_cycle(PAYOUT, max_seconds=30)
            self.assertEqual(result.status, CycleStatus.REJECTED)
            self.assertFalse(result.accepted)
            self.assertIn("bad-txn", result.error)
            row = stats.history()[0]
            self.assertEqual(row["accepted"], 0)
            self.assertEqual(row["submit_result"], "bad-txn")
            self.assertIsNotNone(row["error"])

    def test_stale_template_never_submitted(self):
        rpc = FakeChainRPC()
        original = rpc.get_block_template

        def tip_moves_after_acquisition():
            template = original()
            rpc.best = "11" * 32  # tip advances right after work is handed out
            return template

        rpc.get_block_template = tip_moves_after_acquisition
        with MiningStatsStore(self.db_path) as stats:
            engine = MiningEngine(rpc, stats=stats)
            result = engine.mine_cycle(PAYOUT, max_seconds=30)
            self.assertEqual(result.status, CycleStatus.STALE)
            self.assertEqual(rpc.submitted, [])
            self.assertEqual(stats.history()[0]["accepted"], 0)

    def test_template_error_recorded(self):
        rpc = FakeChainRPC(chain="main")
        with MiningStatsStore(self.db_path) as stats:
            engine = MiningEngine(rpc, stats=stats)
            result = engine.mine_cycle(PAYOUT)
            self.assertEqual(result.status, CycleStatus.TEMPLATE_ERROR)
            self.assertEqual(rpc.submitted, [])
            self.assertIsNotNone(stats.history()[0]["error"])

    def test_consecutive_cycles(self):
        rpc = FakeChainRPC()
        with MiningStatsStore(self.db_path) as stats:
            engine = MiningEngine(rpc, stats=stats)
            results = engine.mine_blocks(3, PAYOUT, max_seconds_per_block=30)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(r.accepted for r in results))
            self.assertEqual(rpc.blocks, 3)
            self.assertEqual(len(stats.history()), 3)
            # Each cycle builds on the previous block.
            self.assertEqual(results[1].prev_hash, results[0].block_hash)
            self.assertEqual(results[2].prev_hash, results[1].block_hash)
            ids = [r.session_id for r in results]
            self.assertEqual(len(set(ids)), 3)


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestLiveMiningCycles(SessionFixture):
    """Real node: the engine constructs, searches, submits and records."""

    RPC_PORT = 18448

    def setUp(self):
        super().setUp()
        from node.node_manager import NodeConfig, NodeManager
        self.datadir = tempfile.mkdtemp(prefix="bal-cycle-")
        self.addCleanup(shutil.rmtree, self.datadir, True)
        self.manager = NodeManager(NodeConfig(
            bitcoind=BITCOIND, datadir=self.datadir, rpc_port=self.RPC_PORT,
        ))
        self.rpc = self.manager.start()
        self.addCleanup(self._stop)

    def _stop(self):
        try:
            self.manager.stop()
        except Exception:
            pass

    def test_three_autonomous_cycles_accepted(self):
        from mining.engine.session import payout_script_from_rpc
        self.rpc.create_wallet("bal")
        script = payout_script_from_rpc(self.rpc)
        with MiningStatsStore(self.db_path) as stats:
            engine = MiningEngine(self.rpc, stats=stats)
            results = engine.mine_blocks(3, script, max_seconds_per_block=30)
            self.assertEqual(len(results), 3)
            for result in results:
                self.assertEqual(result.status, CycleStatus.ACCEPTED,
                                 result.error)
                self.assertTrue(result.accepted)
            self.assertEqual(self.rpc.get_block_count(), 3)
            self.assertEqual(results[-1].block_hash,
                             self.rpc.get_best_block_hash())
            rows = stats.history()
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r["accepted"] == 1 for r in rows))
            self.assertTrue(all(r["hashes"] > 0 for r in rows))


if __name__ == "__main__":
    unittest.main()
