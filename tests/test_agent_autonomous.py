"""TASK 006: autonomous agent lifecycle, control, recovery tests."""

import json
import multiprocessing
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.autonomous.agent import MiningAgent, ResourceLimits  # noqa: E402
from agent.autonomous.compute import ComputationManager  # noqa: E402
from mining.engine.session import CycleResult, CycleStatus  # noqa: E402
from mining.engine.stats import MiningStatsStore  # noqa: E402

from tests.test_engine_session import FakeChainRPC  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")
PAYOUT = bytes.fromhex("51")


class SyncedFakeChain(FakeChainRPC):
    def get_blockchain_info(self):
        info = super().get_blockchain_info()
        info["headers"] = info["blocks"]
        return info


class _ChildChain(SyncedFakeChain):
    def get_block_template(self):
        time.sleep(0.3)
        return super().get_block_template()


def _killed_agent_child(db_path, state_path):
    """Child process: mine through a real agent until the parent kills us."""
    stats = MiningStatsStore(db_path)
    agent = MiningAgent(_ChildChain(), stats, state_path,
                        limits=ResourceLimits(
                            max_cycles=100000, max_seconds_per_cycle=60,
                            failure_backoff_seconds=0.01),
                        requested_backend="cpu")
    agent.start(PAYOUT)
    while True:
        time.sleep(1)


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

    def test_recovery_after_actual_process_kill(self):
        # Genuine interruption evidence: a real subprocess mining through
        # the agent is SIGKILLed mid-session, leaving its own state file
        # behind. A new agent on the same state must detect the dead
        # session, record a recovery event, and mine to completion.
        if sys.platform.startswith("win"):
            self.skipTest("fork-based kill test is POSIX-only")

        class SlowChain(SyncedFakeChain):
            def get_block_template(self):
                time.sleep(0.3)
                return super().get_block_template()

        ctx = multiprocessing.get_context("fork")
        proc = ctx.Process(
            target=_killed_agent_child,
            args=(self.db_path, self.state_path))
        def _state():
            try:
                with open(self.state_path) as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return {}

        proc.start()
        try:
            self.assertTrue(wait_for(
                lambda: _state().get("state") == "running", timeout=20))
            self.assertTrue(wait_for(
                lambda: _state().get("cycles_completed", 0) >= 1,
                timeout=30))
        finally:
            proc.kill()   # SIGKILL: no cleanup handlers run
            proc.join(timeout=15)
        self.assertFalse(proc.is_alive())

        # The dead process left the session mid-run, never idle.
        with open(self.state_path) as fh:
            killed_state = json.load(fh)
        self.assertEqual(killed_state["state"], "running")
        killed_cycles = killed_state["cycles_completed"]

        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc)
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["state"] in ("idle", "stopped"),
            timeout=30))
        events = agent.errors()["events"]
        recovery = [e for e in events if e["kind"] == "recovery"]
        self.assertTrue(recovery, "killed session must trigger recovery")
        self.assertIn(str(killed_cycles), recovery[0]["detail"])
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] == 3, timeout=30))
        self.assertEqual(rpc.blocks, 3)

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


class _StubbornEngine:
    """Engine whose mine_cycle blocks until released, ignoring cancellation.

    Simulates a worker that does not respond to stop(): the agent must
    never report STOPPED while a thread is stuck inside this engine.
    """

    def __init__(self):
        self.batch_size = 4096
        self.release = threading.Event()
        self.calls = 0

    def stop(self):
        pass  # deliberately ignores cancellation

    def mine_cycle(self, payout_script, max_seconds=None, max_hashes=None):
        self.calls += 1
        self.release.wait(timeout=30)
        return CycleResult(session_id="stubborn", started_at="t0",
                           finished_at="t1", seconds=0.01,
                           status=CycleStatus.CANCELLED,
                           error="cancelled by test")


class TestAgentShutdown(AgentFixture):
    """stop() must tell the truth about worker termination."""

    def test_normal_shutdown_reports_stopped_after_worker_exits(self):
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc, limits=ResourceLimits(
            max_cycles=100000, max_seconds_per_cycle=30,
            cycle_pause_seconds=0.05, failure_backoff_seconds=0.01))
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] >= 1))
        result = agent.stop()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "stopped")
        # The worker really terminated before STOPPED was reported.
        self.assertFalse(agent._thread.is_alive())
        self.assertEqual(agent.status()["state"], "stopped")
        with open(self.state_path) as fh:
            self.assertEqual(json.load(fh)["state"], "stopped")
        self.assertFalse(agent.stop()["ok"])  # already stopped

    def test_stop_from_paused(self):
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc, limits=ResourceLimits(
            max_cycles=100000, max_seconds_per_cycle=30,
            cycle_pause_seconds=0.05, failure_backoff_seconds=0.01))
        self.assertTrue(agent.start(PAYOUT)["ok"])
        self.assertTrue(wait_for(
            lambda: agent.status()["cycles_completed"] >= 1))
        self.assertTrue(agent.pause()["ok"])
        result = agent.stop()
        self.assertTrue(result["ok"], result)
        self.assertFalse(agent._thread.is_alive())
        self.assertEqual(agent.status()["state"], "stopped")

    def test_shutdown_timeout_never_reports_false_stopped(self):
        rpc = SyncedFakeChain()
        agent = self.make_agent(rpc, limits=ResourceLimits(
            max_cycles=100000, max_seconds_per_cycle=30,
            failure_backoff_seconds=0.01), shutdown_timeout=0.2)
        self.assertTrue(agent.start(PAYOUT)["ok"])
        stubborn = _StubbornEngine()
        agent._engine = stubborn
        self.assertTrue(wait_for(lambda: stubborn.calls >= 1))

        result = agent.stop()
        self.assertFalse(result["ok"])
        self.assertIn("shutdown timeout", result["error"])
        self.assertEqual(result["state"], "stopping")
        # Status and the persisted state file both reflect that the
        # worker is still alive - no false STOPPED anywhere.
        self.assertEqual(agent.status()["state"], "stopping")
        self.assertTrue(agent._thread.is_alive())
        with open(self.state_path) as fh:
            self.assertEqual(json.load(fh)["state"], "stopping")
        events = agent.errors()["events"]
        self.assertTrue(any("shutdown timeout" in e["detail"]
                            for e in events))
        # A second worker must not be started while the stuck one lives.
        self.assertFalse(agent.start(PAYOUT)["ok"])
        self.assertTrue(agent._thread.is_alive())

        # Once the worker actually terminates, the state converges to a
        # truthful STOPPED on its own.
        stubborn.release.set()
        self.assertTrue(wait_for(
            lambda: agent.status()["state"] == "stopped"))
        self.assertFalse(agent._thread.is_alive())
        with open(self.state_path) as fh:
            self.assertEqual(json.load(fh)["state"], "stopped")

    @unittest.skipUnless(os.name == "posix", "POSIX permissions only")
    def test_agent_state_file_is_owner_only(self):
        agent = self.make_agent(SyncedFakeChain())
        agent._write_state("idle")
        self.assertEqual(
            stat.S_IMODE(os.stat(self.state_path).st_mode), 0o600)
        # A previously permissive state file is repaired on next write.
        os.chmod(self.state_path, 0o644)
        agent._write_state("idle")
        self.assertEqual(
            stat.S_IMODE(os.stat(self.state_path).st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "symlink semantics are POSIX")
    def test_state_write_never_follows_symlinks(self):
        agent = self.make_agent(SyncedFakeChain())
        victim = os.path.join(self.tmp, "victim.txt")
        with open(victim, "w") as fh:
            fh.write("IMPORTANT\n")
        # A symlink planted at the final state path: os.replace swaps the
        # link itself out; the target is never touched.
        os.symlink(victim, self.state_path)
        agent._write_state("idle")
        with open(victim) as fh:
            self.assertEqual(fh.read(), "IMPORTANT\n")
        self.assertFalse(os.path.islink(self.state_path))
        with open(self.state_path) as fh:
            self.assertEqual(json.load(fh)["state"], "idle")
        # A symlink planted at the legacy fixed temp name is simply never
        # used: the real temp file is unique and private.
        os.symlink(victim, self.state_path + ".tmp")
        agent._write_state("idle")
        with open(victim) as fh:
            self.assertEqual(fh.read(), "IMPORTANT\n")
        self.assertTrue(os.path.islink(self.state_path + ".tmp"))


class TestResourceLimitsValidation(unittest.TestCase):
    def test_defaults_are_valid(self):
        ResourceLimits()

    def test_valid_boundary_values_accepted(self):
        ResourceLimits(max_cycles=1, max_seconds_per_cycle=0.5,
                       max_hashes_per_cycle=1, cycle_pause_seconds=0.0,
                       max_consecutive_failures=1,
                       failure_backoff_seconds=0.0)

    def test_none_hash_limit_is_explicit_opt_out(self):
        limits = ResourceLimits(max_hashes_per_cycle=None)
        self.assertIsNone(limits.max_hashes_per_cycle)

    def test_invalid_values_rejected(self):
        invalid = [
            {"max_cycles": 0}, {"max_cycles": -5}, {"max_cycles": 1.5},
            {"max_cycles": True}, {"max_cycles": "3"},
            {"max_seconds_per_cycle": 0}, {"max_seconds_per_cycle": -0.5},
            {"max_seconds_per_cycle": "60"},
            {"max_hashes_per_cycle": 0}, {"max_hashes_per_cycle": -100},
            {"cycle_pause_seconds": -0.1},
            {"max_consecutive_failures": 0},
            {"max_consecutive_failures": -2},
            {"max_consecutive_failures": 1.5},
            {"failure_backoff_seconds": -1.0},
        ]
        for kwargs in invalid:
            with self.assertRaises(ValueError, msg=repr(kwargs)):
                ResourceLimits(**kwargs)

    def test_nonfinite_values_rejected(self):
        inf, nan = float("inf"), float("nan")
        invalid = [
            {"max_seconds_per_cycle": inf}, {"max_seconds_per_cycle": nan},
            {"max_hashes_per_cycle": inf},
            {"cycle_pause_seconds": inf}, {"cycle_pause_seconds": nan},
            {"failure_backoff_seconds": inf},
            {"failure_backoff_seconds": nan},
        ]
        for kwargs in invalid:
            with self.assertRaises(ValueError, msg=repr(kwargs)):
                ResourceLimits(**kwargs)

    def test_shutdown_timeout_validation(self):
        tmp = tempfile.mkdtemp(prefix="bal-limits-")
        self.addCleanup(shutil.rmtree, tmp, True)
        stats = MiningStatsStore(os.path.join(tmp, "m.db"))
        self.addCleanup(stats.close)
        state_path = os.path.join(tmp, "agent_state.json")
        for bad in (0, -1, float("nan"), float("inf"), "30", True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                MiningAgent(SyncedFakeChain(), stats, state_path,
                            shutdown_timeout=bad)
        # A positive finite timeout constructs fine.
        MiningAgent(SyncedFakeChain(), stats, state_path,
                    shutdown_timeout=5.0)


if __name__ == "__main__":
    unittest.main()
