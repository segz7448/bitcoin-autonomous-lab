#!/usr/bin/env python3
"""TASK 005/006 end-to-end autonomous mining demonstration (brief Phase 13).

Starts a disposable Bitcoin Core regtest node, then hands control to the
autonomous mining agent. The agent - with no manual intervention per cycle -
acquires real mining work with getblocktemplate, constructs candidate
blocks, searches SHA256d nonces, independently verifies solutions on the
CPU, submits with submitblock, confirms acceptance on the active chain,
records persistent statistics, and repeats for consecutive cycles.

Bitcoin Core's generatetoaddress is never used to produce blocks here; the
project's own engine constructs, searches and submits every candidate.

Usage: BAL_BITCOIND=/path/to/bitcoind python3 scripts/milestone_005_006.py [--cycles N]
"""

import argparse
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.autonomous.agent import MiningAgent, ResourceLimits  # noqa: E402
from mining.engine.session import payout_script_from_rpc  # noqa: E402
from mining.engine.stats import MiningStatsStore  # noqa: E402
from node.node_manager import NodeConfig, NodeManager  # noqa: E402

RPC_PORT = 18450


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()

    bitcoind = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")
    if not bitcoind:
        print("error: bitcoind not found; set BAL_BITCOIND")
        return 2

    workdir = tempfile.mkdtemp(prefix="bal-demo-")
    db_path = os.path.join(workdir, "mining.db")
    state_path = os.path.join(workdir, "agent_state.json")
    manager = NodeManager(NodeConfig(
        bitcoind=bitcoind, datadir=os.path.join(workdir, "node"),
        rpc_port=RPC_PORT))
    try:
        rpc = manager.start()
        print(f"node ready: chain={rpc.get_blockchain_info()['chain']} "
              f"height={rpc.get_block_count()}")
        rpc.create_wallet("bal")
        script = payout_script_from_rpc(rpc)

        with MiningStatsStore(db_path) as stats:
            agent = MiningAgent(
                rpc, stats, state_path,
                limits=ResourceLimits(max_cycles=args.cycles,
                                      max_seconds_per_cycle=60,
                                      cycle_pause_seconds=0.3))
            print("\n== pre-mining diagnostics ==")
            health = agent.diagnostics()
            for name, value in health["checks"].items():
                print(f"  {name}: {value}")
            if not health["ok"]:
                print("diagnostics failed; aborting")
                return 1

            print(f"\n== starting autonomous agent for {args.cycles} cycles ==")
            started = agent.start(script)
            print(f"  start: {started}")
            seen = 0
            deadline = time.monotonic() + 60 * args.cycles
            while time.monotonic() < deadline:
                status = agent.status()
                if status["cycles_completed"] > seen:
                    seen = status["cycles_completed"]
                    last = status["last_cycle"]
                    print(f"  cycle {seen}: {last['status']} "
                          f"height={last['height']} "
                          f"hash={last['block_hash']} "
                          f"nonce={last['nonce']} "
                          f"hashes={last['hashes']} "
                          f"({last['hashrate_avg']:.1f} H/s)")
                if status["state"] in ("idle", "stopped", "error"):
                    break
                time.sleep(0.1)

            final = agent.status()
            if final["state"] == "running":
                agent.stop()

            print("\n== blockchain status after autonomous mining ==")
            chain = agent.blockchain_status()
            print(f"  blocks: {chain['blocks']}")
            print(f"  best block: {chain['best_block_hash']}")

            print("\n== persistent mining statistics ==")
            totals = stats.totals()
            print(f"  cycles: {totals['cycles']}  accepted: {totals['accepted']}")
            print(f"  total hashes: {totals['hashes']}  "
                  f"avg hashrate: {totals['hashrate_avg']:.1f} H/s")
            print(f"  total coinbase value: {totals['coinbase_value']} sats "
                  f"(regtest, worthless)")
            for row in stats.history():
                print(f"  session {row['session_id'][:8]}: height "
                      f"{row['height']} accepted={row['accepted']} "
                      f"backend={row['backend']} hashes={row['hashes']} "
                      f"peak={row['hashrate_peak']:.1f} H/s")

            print("\n== agent decisions ==")
            for d in reversed(agent.decisions()["decisions"]):
                print(f"  [{d['kind']}] {d['detail']}")
            events = agent.errors()["events"]
            print(f"\n== errors / recovery events: {len(events)} ==")
            for e in reversed(events):
                print(f"  [{e['kind']}] {e['detail']}")

            accepted = totals["accepted"]
            cycles = totals["cycles"]

        # Persistence across restart: reopen the same database file.
        with MiningStatsStore(db_path) as reopened:
            again = reopened.totals()
            print("\n== persistence check (reopened database) ==")
            print(f"  cycles visible after restart: {again['cycles']}")

        ok = (accepted == args.cycles == cycles
              and again["cycles"] == args.cycles
              and chain["blocks"] == args.cycles)
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'} - {accepted}/"
              f"{args.cycles} autonomous cycles accepted by Bitcoin Core")
        return 0 if ok else 1
    finally:
        manager.stop()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
