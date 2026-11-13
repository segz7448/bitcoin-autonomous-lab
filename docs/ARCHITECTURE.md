# Architecture

## Overview

Bitcoin Autonomous Lab is a Python application (3.10+, standard library
only) that runs and manages a local Bitcoin Core node, verifies the chain
independently, monitors it, and hosts proof-of-work research - with an
interface layer designed for an autonomous agent to drive everything.

Bitcoin Core itself is the node of record and the independent consensus
validator. The lab never trusts the node's answers blindly: block headers
are reconstructed from RPC reply fields and block hashes and proof-of-work
targets are recomputed locally.

## Repository layout

```
bitcoin-autonomous-lab/
  node/          Bitcoin Core integration and node lifecycle.
    rpc_client.py    JSON-RPC client (cookie or user/password auth).
    node_manager.py  Start/stop/status for a local regtest bitcoind;
                     refuses to operate on any other chain.
  blockchain/    Block and transaction primitives + monitoring.
    sha256.py        Pure-Python SHA-256 (FIPS 180-4) reference.
    primitives.py    Headers, compact targets, merkle roots, script pushes,
                     byte-order conversions, header reconstruction from
                     getblock replies.
    monitor.py       ChainMonitor: snapshots, independent block
                     verification, generate-and-verify cycles.
    reader.py        BlockchainReader: typed chain queries (blocks,
                     headers, txids, tips). No state.
    analysis.py      BlockAnalyzer: header/target/sizes interpretation,
                     merkle verification, subsidy and fee accounting.
    transactions.py  TransactionIntelligence: decode, fees where
                     available, confirmations, mempool tracking.
    service.py       MonitoringService: poll loop, new-block detection,
                     reorg detection, sync status, backoff/reconnect.
    storage.py       ChainStore: SQLite persistence for blocks, txs,
                     mempool sightings, sync state, monitor events;
                     reorg-safe (orphaned branches are kept).
  mining/        Mining algorithms and PoW experiments (see mining/README).
    miner.py         CPU nonce scanner + verify_pow.
    block.py         BIP34/BIP141 coinbase construction, block assembly.
    template_miner.py getblocktemplate -> build -> mine -> submitblock.
    benchmark.py     Bounded hashrate measurement.
  gpu/           GPU acceleration research. Empty by design (TASK 001
                 restriction); see gpu/README for the research plan.
  agent/         Autonomous agent orchestration.
    interface.py     AgentInterface: every operation returns a structured,
                     JSON-serializable result; no exceptions escape.
  dashboard/     Monitoring and analytics.
    status.py        Text rendering of node/chain state + block reports.
  tests/         Automated tests (unit + fake-node + live regtest).
  docs/          This documentation set.
  scripts/       milestone_001.py live check, node start/stop helpers.
```

## Technology decisions

- **Python standard library only.** The integration surface (HTTP JSON-RPC,
  cookie auth, subprocess lifecycle) needs nothing else, and a zero-dependency
  core is auditable line by line. This directly serves the project's
  no-simulation rule: there is no framework magic between the code and the
  node.
- **Bitcoin Core as validator.** Claims about block correctness are settled
  by the reference implementation accepting (or rejecting) real blocks on
  regtest, not by the lab's own assertions.
- **Independent verification.** `blockchain.monitor` rebuilds each reported
  header and recomputes its hash and target check, so a node returning
  inconsistent data is detected, not believed.
- **Fail-closed regtest guard.** Both `NodeManager` (at start/connect) and
  `mining.template_miner` (before any mining) refuse chains other than
  regtest. Mainnet paths are not wired.
- **Cookie authentication.** The node generates its own credential file per
  datadir; the lab reads it at runtime and stores nothing (docs/SECURITY.md).
- **Agent seam.** `agent.interface.AgentInterface` returns only structured
  dicts, so an orchestrator can be swapped in without touching the
  node/blockchain/mining layers.

## Data flow (milestone 001)

```
scripts/milestone_001.py
   -> NodeManager.start()          spawn bitcoind -regtest, wait for RPC
   -> BitcoinRPC                   JSON-RPC over HTTP (cookie auth)
   -> ChainMonitor                 snapshot / verify / generate-and-verify
   -> dashboard.status             human-readable rendering
```

## Error handling and logging

Every module logs through the standard `logging` package. RPC errors raise
`RPCError` (with the node's error code); lifecycle failures raise
`NodeStartupError`; a non-regtest node raises `ChainMismatchError`. At the
agent boundary these become structured `{"ok": false, "error": ...}` results.
