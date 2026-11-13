# Bitcoin Autonomous Lab

An open-source Bitcoin infrastructure and autonomous mining research project.

The goal is an integrated system that runs and manages a Bitcoin full node,
independently verifies blocks and transactions, monitors the chain in real
time, implements proof-of-work (including the SHA-256 double-hash) from the
protocol up, experiments with CPU mining, and - in later tasks - researches
GPU acceleration, autonomous solo-mining orchestration, and an AI-agent
interface for monitoring and controlling the infrastructure.

Everything is built regtest-first: all experiments run on Bitcoin Core's
private regression-test network, and every claimed capability is backed by
a reproducible test or a recorded live run. Nothing here is simulated.

## Status: TASK 004 audit and hardening complete (verified live)

See `docs/AUDIT_004.md` for the defects found and fixed. TASK 003 summary:

An independent Bitcoin Proof-of-Work engine lives in `mining/pow/`
(SHA-256, double SHA-256, strict 80-byte headers, compact targets with
Core's consensus checks, interruptible nonce search, validator, Core
verification, benchmarks). Every block on a live Bitcoin Core 32.1 regtest
node is re-hashed and PoW-checked by the engine and compared with Core;
the engine also mines a block that Core accepts, and Core rejects the same
invalid-PoW block the engine rejects. Six real mainnet headers are
verified too. 166 automated tests pass. See `docs/POW_ENGINE.md` and
`results/TEST_RESULTS_003.md`.

## TASK 002 (complete, verified live)

The Blockchain Intelligence Engine is implemented and was executed live
against Bitcoin Core 32.1 on regtest. Evidence: `results/TEST_RESULTS_002.md`
plus genuine terminal captures in `results/`.

- `blockchain/reader.py` - typed queries: height, best hash, blocks,
  headers, txids, chain tips (getblockchaininfo, getblockcount,
  getbestblockhash, getblockhash, getblock, getblockheader, getchaintips).
- `blockchain/transactions.py` - transaction decode, inputs/outputs, fees
  where the data exists, sizes, confirmations, mempool tracking and
  new-transaction detection; unavailable data is reported explicitly.
- `blockchain/analysis.py` - header/target/sizes interpretation,
  independent merkle root verification, subsidy and fee accounting.
- `blockchain/service.py` - background monitoring: cheap polling, new-block
  detection, reorg detection with orphaned-branch records, sync status,
  reconnection and backoff on RPC failures.
- `blockchain/storage.py` - SQLite persistence for blocks, transactions,
  mempool sightings, sync state and monitor events; reorg-safe.
- `agent/interface.py` - structured machine-readable answers (height,
  latest block, latest N blocks, block analysis, tx counts, difficulty,
  mempool, new-block discovery).

Latest verified run (see `results/`): all milestone checks passed; 106
automated tests green including live regtest integration.

### TASK 001 (complete)

The first milestone - the Bitcoin Core regtest integration - is implemented
and was executed live against Bitcoin Core 32.1. Evidence:
`results/TEST_RESULTS.md` plus genuine terminal captures in `results/`.

The first milestone - the Bitcoin Core regtest integration - is implemented
and was executed live against Bitcoin Core 32.1. Evidence:
`results/TEST_RESULTS.md` plus genuine terminal captures in `results/`.

| Milestone requirement | Result |
| --- | --- |
| Start a local Bitcoin Core node (regtest) | `NodeManager.start()` launches `bitcoind -regtest`, waits for RPC, verifies `chain=regtest` |
| Connect through JSON-RPC | `BitcoinRPC` over HTTP with cookie auth; no stored credentials |
| getblockchaininfo | chain, height, best hash, difficulty retrieved |
| getblockcount | retrieved and cross-checked after generation |
| generatetoaddress | 3 blocks generated to a regtest wallet address |
| getblock | tip block retrieved (height, confirmations, tx count, prev hash) |
| Node recognizes generated blocks | per-block: `getblockhash(height)` matches, hash recomputed locally from header fields, PoW target check passes, prev-block linkage verified |

Latest verified run (see `results/`): all 7 checks passed; 56 automated
tests green including the live regtest integration test.

## Repository layout

```
node/        Bitcoin Core integration and node lifecycle management
blockchain/  Block/transaction primitives, independent verification, monitoring
mining/      Proof-of-work research (CPU miner, coinbase/BIP34/BIP141, benchmark)
gpu/         GPU acceleration research (not yet implemented - see gpu/README.md)
agent/       Autonomous agent orchestration interface
dashboard/   Monitoring and analytics rendering
tests/       Automated tests: unit, adversarial, fake-node, live regtest
docs/        Architecture, setup, regtest guide, security
scripts/     Milestone runner and node start/stop helpers
results/     Test transcripts and genuine screenshots of live runs
```

## Quickstart

Requires Python 3.10+ (standard library only) and Bitcoin Core
(verified against 32.1; see `docs/SETUP.md` for checksum-verified install).

```bash
export BAL_BITCOIND=/path/to/bitcoind     # or put bitcoind on PATH
python3 scripts/milestone_001.py          # regtest integration, live
python3 scripts/milestone_002.py          # intelligence engine, live
python3 -m unittest discover -s tests -t .  # full test suite
```

## Engineering standards

- Modular, typed, logged Python; standard library only (no third-party deps).
- Independent verification: block hashes and PoW targets are recomputed from
  RPC fields, never trusted from the node.
- Fail-closed regtest guards: the node manager and the template miner refuse
  to operate on any chain but regtest.
- No secrets in the repo: cookie auth from the node-generated file, or
  environment variables (`docs/SECURITY.md`).
- No simulated functionality presented as real Bitcoin functionality.

## Roadmap

- **TASK 001 (done):** node management, JSON-RPC, chain monitoring,
  independent block verification, regtest block generation, test suite.
- **TASK 002 (done):** blockchain intelligence engine - monitoring service,
  transaction intelligence, block analysis with merkle verification,
  SQLite persistence, reorg handling, agent query interface.
- **TASK 003 (done):** independent SHA-256 / header / target / nonce-search
  Proof-of-Work engine, verified against Bitcoin Core.
- **TASK 004 (done):** audit, hardening and retest - see `docs/AUDIT_004.md`
  (target/merkle/coinbase consensus checks, sync robustness, RPC and storage
  hardening, event-driven monitoring).
- **Next:** GPU research and the autonomous agent layer.
- **Not in scope yet:** mainnet mining, GPU mining (blocked until the Core
  integration is established and tested), paid infrastructure.

## Honest scope notes

- Regtest results demonstrate correctness of the integration against the
  reference implementation. They are not evidence of mainnet mining
  capability or any economic outcome.
- On mainnet today, a block's reward is the current subsidy (3.125 BTC
  since the April 2024 halving) plus that block's transaction fees, paid to
  the miner that finds a valid block - a separate matter from confirming
  transactions, and not something this milestone attempts.
- The CPU benchmark numbers in `results/` describe only the machine they
  were measured on.

## TASK 004: CUDA computation engine

Real CUDA SHA256d/parallel nonce-search source, independent CPU verification,
allowlisted diagnostics, repeated benchmarks, and CPU/CUDA/auto computation APIs
are implemented. CUDA 13.0 was installed in user space and the source compiled.
Actual GPU execution remains blocked by unavailable system driver/device access;
no GPU speed or successful GPU mining is claimed. CPU fallback and live Core
Regtest validation pass. See [CUDA technical guide](docs/CUDA_TASK_004.md),
[CUDA test results](results/CUDA_TEST_RESULTS_004.md), and structured diagnostics
in `results/cuda-004-diagnostics.json`. Earlier audit-004 documents remain history.
