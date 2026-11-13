# TASK 005/006: Autonomous Bitcoin mining engine and AI mining agent

Regtest-only research system. The engine obtains real mining work from
Bitcoin Core, constructs candidate blocks, searches Proof-of-Work, submits
blocks and verifies acceptance. The agent coordinates the whole lifecycle
autonomously. Bitcoin Core's `generatetoaddress` is never used by the
mining path - the project's own engine constructs, searches and submits
every candidate block. (It is used in tests only, as an independent tool
to advance the tip.)

## Architecture

```
agent/autonomous/agent.py        MiningAgent - control interface, lifecycle,
                                 decisions, recovery, resource limits
agent/autonomous/compute.py      ComputationManager - backend selection from
                                 measured results, honest CPU fallback
        | uses
mining/engine/template.py        getblocktemplate acquisition + validation,
                                 staleness detection (tip change / expiry)
mining/engine/builder.py         candidate block construction: strict tx
                                 verification, selection, coinbase, witness
                                 commitment, merkle root, extranonce/time
mining/engine/search.py          PoW search: exhaustion -> extra-nonce
                                 escalation, staleness/cancel, independent
                                 CPU verification of every solution
mining/engine/session.py         MiningEngine - one full cycle:
                                 acquire -> build -> search -> submit ->
                                 verify on active chain
mining/engine/stats.py           MiningStatsStore - SQLite mining history,
                                 agent decisions, error/recovery events
        | reuses (unchanged)
mining/block.py                  coinbase (BIP34/141) and block assembly
mining/template_miner.py         original single-shot mining flow
mining/pow/                      SHA256d engine, nonce search, validation
gpu/engine.py                    ComputeEngine (CPU/CUDA with CPU verify)
node/, blockchain/               node management, RPC, chain intelligence
```

## Candidate block construction (Phase 3)

* Every transaction offered by the template is re-parsed; its txid (and
  wtxid for SegWit transactions) is recomputed from the raw data and must
  match, or the template is rejected.
* Selection honours dependencies (1-based, topological) and the template's
  sigop/size/weight limits; a transaction whose dependency was skipped is
  skipped too.
* The coinbase pays exactly subsidy(height) + selected fees and never more
  than the template's `coinbasevalue`. The subsidy follows the Bitcoin
  halving schedule.
* A BIP141 witness commitment is computed when witness transactions are
  present and cross-checked against Core's `default_witness_commitment`.
* Extra-nonce variation rebuilds the coinbase and merkle root; timestamp
  variation respects the template's `mintime`.

## Proof-of-Work search (Phase 4)

Nonce batches are dispatched through `gpu.engine.ComputeEngine`, the
project's CPU/CUDA backend abstraction: the backend that actually hashes
each batch is recorded, a CUDA execution fault falls back to the CPU with
the reason recorded, and every reported nonce is independently
re-verified on the CPU (`mining.pow.validator`) before submission. The
engine adds: target validation against the regtest pow limit, nonce-range
exhaustion handling via bounded extra-nonce rounds, block-time updates
that respect the template's `mintime` and the network-adjusted consensus
limit (`getnetworkinfo` timeoffset + MAX_FUTURE_BLOCK_TIME; a template
whose mintime exceeds that limit fails closed), staleness and
cancellation checks between every batch, and exact accounting: hashes,
seconds, average/peak hashrate, batches, extra-nonce rounds. Batch sizes
are managed by the agent's `ComputationManager` from measured batch
times. A `NonceSearcher`-based path remains for direct use and tests.

## Submission and acceptance (Phase 5)

A block counts as mined only when `submitblock` returns no error AND the
block is verified on the active chain (`getblock` confirmations >= 1 and
it is the node's best block). `duplicate` is distinguished from other
rejections; every rejection reason is recorded. Errors are never silently
discarded.

## Statistics (Phase 6)

`MiningStatsStore` (SQLite, same store pattern as the chain database, own
file) records one row per cycle: session ID, height, prev/block hash,
start/finish times, hashes, average and peak hashrate, backend, batches,
nonce, extra-nonce counter, submission result, acceptance, coinbase value,
fees and error text. Agent decisions and error/recovery events are kept in
the same database. History survives restarts. Benchmark numbers never
enter the store.

## Autonomous agent (Phases 7-11)

Lifecycle: initialize (connectivity, regtest-only, sync, work availability,
backend probe) -> observe -> prepare -> compute -> verify -> submit ->
repeat. The agent decides when to mine, which backend is usable (measured
batch through `ComputeEngine`; CUDA only after its self-test and a real
batch succeed, otherwise honest CPU fallback with the reason recorded),
when work is stale, and when to back off or halt (consecutive-failure
limit). Decisions are based on actual state and measured results; the AI
layer never bypasses consensus validation.

Control interface (`MiningAgent`, all returning `{"ok": ...}` dicts):
`start`, `stop`, `pause`, `resume`, `status`, `blockchain_status`,
`backend_status`, `current_stats`, `historical_stats`, `decisions`,
`errors`, `diagnostics`. Persistent state (JSON state file + SQLite)
detects sessions that ended without shutdown and records a recovery event
instead of resuming inconsistently. Resource limits cap cycles, per-cycle
seconds/hashes, pacing and failure tolerance.

Privacy: only operational outcomes (backend name, fallback reason,
measured hashrate) are reported. No GPU model, architecture, compute
capability, VM architecture or hardware identifiers are requested, exposed
or inferred.

## Running

```bash
# everything (live tests need bitcoind via BAL_BITCOIND or PATH)
python3 -m unittest discover -s tests -t .

# end-to-end autonomous demonstration on a disposable regtest node
BAL_BITCOIND=/path/to/bitcoind python3 scripts/milestone_005_006.py --cycles 3
```

Tests: `tests/test_engine_template.py`, `tests/test_engine_builder.py`,
`tests/test_engine_search.py`, `tests/test_engine_session.py`,
`tests/test_agent_autonomous.py` - unit coverage plus live regtest
integration (real templates, real constructed blocks accepted by Core,
multi-cycle autonomous runs, persistence across restarts).

## Known limitations

* Regtest only. No mainnet/testnet/signet, no pools, no real money.
* Regtest difficulty is trivial (~1-2 hashes per block); the engine is
  correct and fully consensus-validated, not fast. Competitive mining is
  out of scope.
* CUDA is selected only when genuinely usable; in environments without
  GPU access the agent honestly falls back to CPU and records the reason.
  Mining batches dispatch through `ComputeEngine`, so a working CUDA
  backend is used for real search batches; this environment has no CUDA
  access, so all measured results here are CPU.
* The agent is single-process; the control interface is in-process Python
  (dicts), consistent with `AgentInterface`.
