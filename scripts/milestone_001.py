#!/usr/bin/env python3
"""TASK 001 milestone: live Bitcoin Core regtest integration.

Runs every capability the milestone requires, in order, against a real
Bitcoin Core node on the private regtest network, and prints a PASS/FAIL
line per requirement. Any failure aborts with a non-zero exit code; nothing
is simulated and no result is asserted without being executed.

Requirements covered:
  1. Start a local Bitcoin Core node (regtest).
  2. Connect to it through JSON-RPC.
  3. Retrieve blockchain information using getblockchaininfo.
  4. Retrieve the current block count.
  5. Generate test blocks using generatetoaddress.
  6. Retrieve block information using getblock.
  7. Verify the node recognizes the generated blocks (plus an independent
     header-reconstruction and proof-of-work check on each block).

Usage:
  BAL_BITCOIND=/path/to/bitcoind python3 scripts/milestone_001.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.monitor import ChainMonitor  # noqa: E402
from dashboard.status import render_status, render_verification  # noqa: E402
from node.node_manager import NodeConfig, NodeManager  # noqa: E402

logging.basicConfig(level=logging.WARNING)
N_GENERATE = 3


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail else ""))
    return condition


def main() -> int:
    ok = True
    datadir = tempfile.mkdtemp(prefix="bal-milestone-")
    config = NodeConfig.from_env()  # honors BAL_BITCOIND etc.
    config.datadir = datadir
    manager = NodeManager(config)

    print("=" * 64)
    print("TASK 001 MILESTONE: Bitcoin Core regtest integration (live run)")
    print("=" * 64)

    # 1. Start a local Bitcoin Core node.
    print("\n[1] Start local Bitcoin Core node (regtest)")
    rpc = manager.start()
    print(f"    bitcoind started, RPC endpoint {manager.config.rpc_url}")

    # 2. Connect through JSON-RPC.
    print("\n[2] Connect through JSON-RPC")
    net = rpc.get_network_info()
    ok &= check("JSON-RPC getnetworkinfo answered",
                "version" in net,
                f"Bitcoin Core {net['subversion'].strip('/')}")

    # 3. getblockchaininfo.
    print("\n[3] getblockchaininfo")
    info = rpc.get_blockchain_info()
    print(f"    {json.dumps({k: info[k] for k in ('chain', 'blocks', 'headers', 'bestblockhash', 'difficulty')})}")
    ok &= check("chain is regtest", info["chain"] == "regtest")

    # 4. getblockcount.
    print("\n[4] getblockcount")
    count = rpc.get_block_count()
    print(f"    block count: {count}")
    ok &= check("block count retrieved", isinstance(count, int))

    # Wallet + address for generatetoaddress (regtest-only test wallet).
    print("\n[5] generatetoaddress (generate test blocks)")
    if "bal" not in rpc.list_wallets():
        rpc.create_wallet("bal")
    address = rpc.get_new_address()
    print(f"    regtest wallet 'bal', payout address {address}")
    monitor = ChainMonitor(rpc)
    reports = monitor.generate_and_verify(N_GENERATE, address)
    new_count = rpc.get_block_count()
    print(f"    block count after generation: {new_count}")
    ok &= check(f"{N_GENERATE} blocks generated",
                new_count == count + N_GENERATE)

    # 6. getblock on the new tip.
    print("\n[6] getblock (new chain tip)")
    tip = rpc.get_best_block_hash()
    block = rpc.get_block(tip)
    print(f"    hash          {block['hash']}")
    print(f"    height        {block['height']}")
    print(f"    confirmations {block['confirmations']}")
    print(f"    transactions  {block['nTx']}")
    print(f"    previous      {block.get('previousblockhash', '(genesis)')}")
    ok &= check("tip block retrieved at expected height",
                block["height"] == new_count)

    # 7. Node recognizes the generated blocks + independent verification.
    print("\n[7] Node recognition + independent verification of each block")
    for report in reports:
        print()
        print(render_verification(report))
        ok &= report.ok

    print("\n" + "=" * 64)
    print(render_status(monitor.snapshot()))
    print("=" * 64)
    print(f"\nMILESTONE RESULT: {'ALL CHECKS PASSED' if ok else 'FAILURES PRESENT'}")

    manager.stop()
    print("node stopped cleanly")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
