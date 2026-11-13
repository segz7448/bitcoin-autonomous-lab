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

## Status: TASK 001 milestone complete (verified live)

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
python3 scripts/milestone_001.py          # the live milestone, end to end
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
- **Next:** live chain monitoring loop, PoW template mining on regtest
  (`mining/template_miner.py` is implemented and tested), then GPU research
  and the autonomous agent layer.
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
