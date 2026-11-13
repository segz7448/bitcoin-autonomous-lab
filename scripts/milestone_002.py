#!/usr/bin/env python3
"""TASK 002 milestone: Blockchain Intelligence Engine, live on regtest.

Exercises every capability the task requires, in order, against a real
Bitcoin Core node on the private regtest network, and prints a PASS/FAIL
line per requirement. Any failure aborts with a non-zero exit code; nothing
is simulated and no result is asserted without being executed.

Requirements covered:
  1. Blockchain monitoring: height, new-block detection, block/header
     retrieval, timestamps, difficulty, prev hashes, txids, local record.
  2. Transaction intelligence: decode, inputs/outputs, fees where
     available, sizes, confirmations, mempool tracking, new-tx detection,
     explicit handling of unavailable data.
  3. Block structure analysis: header fields, merkle root verification
     against real block data, subsidy and fee accounting.
  4. Monitoring service: background sync, new-block processing, reorg
     detection, sync status, RPC failure resilience with backoff.
  5. Data storage: persistent block/transaction metadata and timestamps,
     reorg-safe updates, state surviving a restart.
  6. AI agent interface: structured machine-readable answers.

Usage:
  BAL_BITCOIND=/path/to/bitcoind python3 scripts/milestone_002.py
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.interface import AgentInterface  # noqa: E402
from blockchain.analysis import BlockAnalyzer, expected_subsidy_sats  # noqa: E402
from blockchain.reader import BlockchainReader  # noqa: E402
from blockchain.service import MonitoringService  # noqa: E402
from blockchain.storage import ChainStore  # noqa: E402
from blockchain.transactions import TransactionIntelligence  # noqa: E402
from node.node_manager import NodeConfig, NodeManager  # noqa: E402

logging.basicConfig(level=logging.WARNING)


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail else ""))
    return condition


def main() -> int:
    ok = True
    datadir = tempfile.mkdtemp(prefix="bal-ms002-")
    db_path = os.path.join(datadir, "chain.db")
    config = NodeConfig.from_env()
    config.datadir = datadir
    # txindex lets the engine inspect confirmed transactions directly;
    # the milestone also exercises the unavailable-data path explicitly.
    config.extra_args = ("-txindex",)
    manager = NodeManager(config)

    print("=" * 64)
    print("TASK 002 MILESTONE: Blockchain Intelligence Engine (live run)")
    print("=" * 64)

    rpc = manager.start()
    agent = AgentInterface(manager)
    agent.ensure_wallet("bal")
    address = rpc.get_new_address()

    # ---------------------------------------------------------------
    print("\n[1] Blockchain monitoring (real RPC data)")
    info = rpc.get_blockchain_info()
    ok &= check("getblockchaininfo answered", info["chain"] == "regtest",
                f"chain={info['chain']}")
    height = rpc.get_block_count()
    ok &= check("getblockcount answered", height >= 0, f"height={height}")

    # Mature the coinbase (100 confirmations) so the wallet can spend.
    rpc.generate_to_address(101, address)
    height = rpc.get_block_count()
    rpc.generate_to_address(5, address)
    new_height = rpc.get_block_count()
    ok &= check("height change detected after generatetoaddress",
                new_height == height + 5,
                f"{height} -> {new_height}")
    reader = BlockchainReader(rpc)
    best = rpc.get_best_block_hash()
    block = reader.block_summary(best)
    ok &= check("getblock by hash", block.hash == best,
                f"hash={block.hash[:16]}...")
    header = reader.header(best)
    ok &= check("getblockheader (timestamp, difficulty, prev hash, txids)",
                header.height == block.height
                and header.merkle_root == block.merkle_root
                and len(reader.block_txids(best)) == block.n_tx,
                f"time={header.time} bits={header.bits} "
                f"prev={header.prev_hash[:12]}... n_tx={block.n_tx}")
    tips = reader.chain_tips()
    ok &= check("getchaintips", tips[0].status == "active"
                and tips[0].height == new_height,
                f"active tip height={tips[0].height}")

    # ---------------------------------------------------------------
    print("\n[2] Transaction intelligence")
    txs = TransactionIntelligence(rpc)
    # Create a real spend so the mempool has a non-coinbase transaction.
    send_txid = rpc.send_to_address(rpc.get_new_address(), 1.0)
    entry = txs.mempool_entry(send_txid)
    ok &= check("getmempoolentry (fee, vsize, ancestors)",
                entry["fee_btc"] > 0 and entry["vsize"] > 0,
                f"fee={entry['fee_btc']} BTC vsize={entry['vsize']}")
    status = txs.mempool_status()
    ok &= check("getrawmempool / getmempoolinfo tracking",
                send_txid in status.txids and status.size >= 1,
                f"mempool size={status.size}")
    new = txs.detect_new_mempool_txs(set())
    ok &= check("new transaction detection", any(t["txid"] == send_txid
                                                 for t in new),
                f"{len(new)} new tx observed")
    decoded = txs.get_transaction(send_txid)
    ok &= check("getrawtransaction decode (inputs/outputs/sizes)",
                decoded.available and decoded.n_inputs >= 1
                and decoded.n_outputs >= 1 and decoded.vsize > 0,
                f"vin={decoded.n_inputs} vout={decoded.n_outputs} "
                f"vsize={decoded.vsize}")
    fee_info = txs.transaction_fee(send_txid)
    ok &= check("fee where data available", fee_info["fee_btc"] is not None
                and fee_info["source"] == "mempool",
                f"{fee_info['fee_btc']} BTC from {fee_info['source']}")
    missing = txs.get_transaction("00" * 32)
    ok &= check("unavailable tx handled explicitly (not fabricated)",
                not missing.available
                and "No such" in (missing.unavailable_reason or ""),
                missing.unavailable_reason)
    mined = rpc.generate_to_address(1, address)[0]
    confirmed = txs.get_transaction(send_txid)
    ok &= check("confirmations after mining",
                confirmed.confirmations >= 1
                and confirmed.block_hash == mined,
                f"confirmations={confirmed.confirmations}")

    # ---------------------------------------------------------------
    print("\n[3] Block structure analysis")
    analyzer = BlockAnalyzer(reader)
    analysis = analyzer.analyze(mined)
    ok &= check("header fields (version/prev/merkle/nonce/bits)",
                analysis.nonce >= 0 and analysis.merkle_root
                and analysis.prev_hash != "00" * 32,
                f"nonce={analysis.nonce} bits={analysis.bits}")
    ok &= check("difficulty target derived from bits",
                analysis.target > 0 and analysis.pow_meets_target,
                f"difficulty={analysis.difficulty}")
    ok &= check("sizes / weight / tx count",
                analysis.size > 0 and analysis.weight > 0
                and analysis.n_tx >= 2,
                f"size={analysis.size} weight={analysis.weight} "
                f"n_tx={analysis.n_tx}")
    ok &= check("merkle root verified against real block data",
                analysis.merkle_root_verified)
    ok &= check("subsidy and fees consistent",
                analysis.total_fees_btc is not None
                and analysis.total_fees_btc > 0
                and analysis.coinbase_within_limit
                and analysis.expected_subsidy_btc
                == expected_subsidy_sats(analysis.height) / 100_000_000,
                f"fees={analysis.total_fees_btc} "
                f"coinbase={analysis.coinbase_value_btc} "
                f"subsidy={analysis.expected_subsidy_btc}")

    # ---------------------------------------------------------------
    print("\n[4] Background monitoring service")
    store = ChainStore(db_path)
    service = MonitoringService(rpc, store, poll_interval=0.2,
                                rpc_factory=manager.client)
    seen = []
    service.add_block_listener(seen.append)
    report = service.sync_once()
    ok &= check("initial sync processed and stored all blocks",
                report.ok and report.synced_height_after == new_height + 1
                and len(report.new_blocks) == new_height + 2,
                f"synced={report.synced_height_after}")
    ok &= check("local record of processed blocks persisted",
                store.count_blocks() == new_height + 2)
    hashes2 = rpc.generate_to_address(3, address)
    report = service.sync_once()
    ok &= check("new blocks detected and stored on next cycle",
                report.new_blocks == hashes2,
                f"{len(report.new_blocks)} new blocks")
    ok &= check("new-block listeners fired",
                len(seen) == (new_height + 2) + 3)
    service.record_block_transactions(hashes2[-1])
    ok &= check("transaction metadata stored",
                store.count_transactions() >= 1,
                f"stored tx={store.count_transactions()}")

    # Force a reorg: invalidate the tip, mine two competing blocks.
    forked = hashes2[-1]
    rpc.invalidate_block(forked)
    # Fresh address: the competing branch must not reproduce the
    # invalidated block's hash.
    rpc.generate_to_address(2, rpc.get_new_address())
    report = service.sync_once()
    ok &= check("reorg detected with orphaned block recorded",
                report.reorg_detected and forked in report.orphaned_blocks,
                f"orphaned={len(report.orphaned_blocks)}")
    ok &= check("chain re-synced on the new branch",
                report.in_sync
                and store.count_blocks("orphaned") >= 1,
                f"orphaned rows={store.count_blocks('orphaned')}")

    sync_status = service.status()
    ok &= check("synchronization status maintained",
                sync_status["in_sync"]
                and sync_status["synced_height"] == sync_status["node_height"],
                f"synced={sync_status['synced_height']}")

    # RPC failure resilience: kill the node; the service must not crash.
    manager.stop()
    failures = service.sync_once()
    ok &= check("RPC failure handled (no crash, recorded)",
                not failures.ok and failures.consecutive_failures >= 1,
                f"error={failures.error}")
    manager.start()
    recovered = service.sync_once()
    ok &= check("service recovered after node restart",
                recovered.ok and recovered.in_sync,
                f"synced={recovered.synced_height_after}")

    # ---------------------------------------------------------------
    print("\n[5] Data storage across restarts")
    store.close()
    reopened = ChainStore(db_path)
    persisted = reopened.get_sync()
    ok &= check("sync state survives restart",
                persisted is not None
                and persisted["last_height"] == recovered.synced_height_after,
                f"last_height={persisted['last_height']}")
    ok &= check("block metadata survives restart",
                reopened.count_blocks("active")
                == recovered.synced_height_after + 1)
    ok &= check("reorg history survives restart",
                reopened.count_blocks("orphaned") >= 1
                and any(e["kind"] == "reorg" for e in reopened.events()))
    reopened.close()

    # ---------------------------------------------------------------
    print("\n[6] AI agent interface (structured answers)")
    h = agent.current_block_height()
    ok &= check("current block height", h["ok"] and h["height"] ==
                recovered.synced_height_after, f"height={h['height']}")
    bh = agent.latest_block_hash()
    ok &= check("latest block hash", bh["ok"]
                and len(bh["block_hash"]) == 64, bh["block_hash"][:16] + "...")
    lb = agent.latest_blocks(10)
    ok &= check("latest 10 blocks", lb["ok"] and lb["count"] == 10,
                f"count={lb['count']}")
    ab = agent.analyze_block(lb["blocks"][0]["hash"])
    ok &= check("analyze a block (machine-readable)",
                ab["ok"] and ab["analysis"]["merkle_root_verified"])
    tc = agent.latest_block_tx_count()
    ok &= check("transactions in latest block", tc["ok"]
                and tc["n_tx"] >= 1, f"n_tx={tc['n_tx']}")
    nd = agent.network_difficulty()
    ok &= check("network difficulty", nd["ok"]
                and nd["difficulty"] > 0, f"{nd['difficulty']}")
    mp = agent.mempool_status()
    ok &= check("mempool status", mp["ok"] and mp["mempool"]["size"] >= 0,
                f"size={mp['mempool']['size']}")
    nb = agent.has_new_block(db_path)
    ok &= check("new-block discovery query (structured)",
                nb["ok"] and nb["report"]["in_sync"])

    print("\n" + "=" * 64)
    print("MILESTONE RESULT: " + ("ALL CHECKS PASSED"
                                   if ok else "FAILURES PRESENT"))
    print("=" * 64)

    manager.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
