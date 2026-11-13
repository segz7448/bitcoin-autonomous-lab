"""TASK 006: autonomous agent lifecycle, control, recovery tests."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.autonomous.agent import MiningAgent, ResourceLimits  # noqa: E402
from agent.autonomous.compute import ComputationManager  # noqa: E402
from mining.engine.stats import MiningStatsStore  # noqa: E402

from tests.test_engine_session import FakeChainRPC  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")
PAYOUT = bytes.fromhex("51")


class SyncedFakeChain(FakeChainRPC):
    def get_blockchain_info(self):
        info = super().get_blockchain_info()
        info["headers"] = info["blocks"]
        return info


def wait_for(predicate, timeout=15.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class AgentFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bal-agent-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db_path = os.path.join(self.tmp, "mining.db")
        self.state_path = os.path.join(self.tmp, "agent_state.json")

    def make_agent(self, rpc, **kwargs):
        stats = MiningStatsStore(self.db_path)
        self.addCleanup(stats.close)
        limits = kwargs.pop("limits", ResourceLimits(
            max_cycles=3, max_seconds_per_cycle=30,
            failure_backoff_seconds=0.01))
        return MiningAgent(rpc, stats, self.state_path, limits=limits, **kwargs)


class TestComputationManager(unittest.TestCase):
    def test_probe_measures_real_batch(self):
        report = ComputationManager(requested="auto").probe()
        self.assertEqual(report.backend, "cpu")  # no CUDA in this environment
        self.assertEqual(report.benchmark_hashes, 4096)
        self.assertGreater(report.benchmark_hashrate, 0)

    def test_cuda_request_falls_back_honestly(self):
        report = ComputationManager(requested="cuda").probe()
        self.assertEqual(report.backend, "cpu")
        self.assertIsNotNone(report.fallback_reason)


class TestAgentLifecycle(AgentFixture):
    def test_autonomous_cycles_complete(self):
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc)
        started = agent.start(PAYOUT)
        self.assertTrue(started["ok"], started)
        self.assertEqual(started["backend"], "cpu")
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] == 3))
        self.assertTrue(wait_for(
            lambda: agent.status()["state"] in ("idle", "stopped")))
        self.assertEqual(rpc.blocks, 3)

        status = agent.status()
        self.assertEqual(status["cycles_completed"], 3)
        self.assertEqual(status["state"], "idle")
        self.assertEqual(status["last_cycle"]["status"], "accepted")

        decisions = [d["kind"] for d in agent.decisions()["decisions"]]
        self.assertIn("backend-selected", decisions)
        self.assertIn("mining-started", decisions)
        self.assertEqual(decisions.count("cycle-accepted"), 3)

        stats = agent.current_stats()
        self.assertEqual(stats["totals"]["accepted"], 3)
        self.assertEqual(stats["totals"]["cycles"], 3)
        self.assertEqual(agent.blockchain_status()["blocks"], 3)
        self.assertTrue(agent.backend_status()["probed"])
        self.assertEqual(agent.errors()["events"], [])

    def test_pause_resume_stop(self):
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc, limits=ResourceLimits(
            max_cycles=1000, max_seconds_per_cycle=30,
            cycle_pause_seconds=0.05, failure_backoff_seconds=0.01))
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] >= 1))

        paused = agent.pause()
        self.assertTrue(paused["ok"])
        time.sleep(0.3)  # let any in-flight cycle finish
        frozen = agent.status()["cycles_completed"]
        time.sleep(0.4)
        self.assertEqual(agent.status()["cycles_completed"], frozen)

        resumed = agent.resume()
        self.assertTrue(resumed["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] > frozen))

        stopped = agent.stop()
        self.assertTrue(stopped["ok"])
        self.assertEqual(agent.status()["state"], "stopped")
        kinds = [d["kind"] for d in agent.decisions()["decisions"]]
        self.assertIn("mining-paused", kinds)
        self.assertIn("mining-resumed", kinds)
        self.assertIn("mining-stopped", kinds)

    def test_double_start_refused(self):
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc, limits=ResourceLimits(
            max_cycles=1000, max_seconds_per_cycle=30,
            cycle_pause_seconds=0.2))
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertFalse(agent.start(PAYOUT)["ok"])
        agent.stop()

    def test_stop_when_not_running(self):
        agent = self.make_agent(SyncedFakeChain())
        self.assertFalse(agent.stop()["ok"])

    def test_consecutive_failures_halt_mining(self):
        rpc = SyncedFakeChain(accept=False)
        agent = self.make_agent(rpc, limits=ResourceLimits(
            max_cycles=100, max_seconds_per_cycle=30,
            max_consecutive_failures=3, failure_backoff_seconds=0.01))
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["state"] in ("idle", "stopped", "error")))
        status = agent.status()
        self.assertEqual(status["cycles_completed"], 3)
        kinds = [d["kind"] for d in agent.decisions()["decisions"]]
        self.assertIn("mining-halted", kinds)
        events = agent.errors()["events"]
        self.assertEqual(sum(1 for e in events if e["kind"] == "cycle-failed"), 3)
        self.assertTrue(any(e["kind"] == "error" for e in events))

    def test_interrupted_session_recovery(self):
        # Simulate a crash: state file claims a running session.
        with open(self.state_path, "w") as fh:
            json.dump({"state": "running", "cycles_completed": 7}, fh)
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc)
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] == 3))
        self.assertTrue(wait_for(
            lambda: agent.status()["state"] in ("idle", "stopped")))
        events = agent.errors()["events"]
        self.assertTrue(any(e["kind"] == "recovery" for e in events))
        with open(self.state_path) as fh:
            self.assertEqual(json.load(fh)["state"], "idle")

    def test_start_refused_off_regtest(self):
        rpc = SyncedFakeChain(chain="main")
        agent = self.make_agent(rpc)
        result = agent.start(PAYOUT)
        self.assertFalse(result["ok"])
        self.assertTrue(any(e["kind"] == "error"
                            for e in agent.errors()["events"]))


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestLiveAutonomousAgent(AgentFixture):
    """The agent autonomously mines real blocks on a real node."""

    RPC_PORT = 18449

    def setUp(self):
        super().setUp()
        from node.node_manager import NodeConfig, NodeManager
        self.datadir = tempfile.mkdtemp(prefix="bal-agentlive-")
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

    def test_agent_mines_two_blocks_autonomously(self):
        from mining.engine.session import payout_script_from_rpc
        self.rpc.create_wallet("bal")
        script = payout_script_from_rpc(self.rpc)
        agent = self.make_agent(self.rpc, limits=ResourceLimits(
            max_cycles=2, max_seconds_per_cycle=30))
        started = agent.start(script)
        self.assertTrue(started["ok"], started)
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] == 2, timeout=60))
        self.assertTrue(wait_for(
            lambda: agent.status()["state"] in ("idle", "stopped")))

        self.assertEqual(self.rpc.get_block_count(), 2)
        stats = agent.current_stats()
        self.assertEqual(stats["totals"]["accepted"], 2)
        latest = stats["latest"]
        self.assertEqual(latest["height"], 2)
        self.assertEqual(latest["block_hash"],
                         self.rpc.get_best_block_hash())
        decisions = [d["kind"] for d in agent.decisions()["decisions"]]
        self.assertEqual(decisions.count("cycle-accepted"), 2)
        self.assertEqual(agent.errors()["events"], [])
        health = agent.diagnostics()
        self.assertTrue(health["ok"], health)
        self.assertTrue(health["checks"]["synchronized"])


if __name__ == "__main__":
    unittest.main()
