# TASK 005/006 engineering report: autonomous mining engine and AI mining agent

> **Historical record: written 2026-11-13 against commit 41a979f in the original test environment (Python 3.10, Bitcoin Core 32.1 regtest).** Preserved unchanged except this label; the current suite counts and correction status are in docs/CORRECTION_PRE_007.md.

Date: 2026-11-13. Commit: 41a979f. Scope: brief phonemsg TASK 005 + TASK 006
(autonomous Bitcoin mining engine and AI mining agent), regtest only.

## Completed components

**TASK 005 - mining engine (`mining/engine/`)**

| Phase | Component | Status |
| --- | --- | --- |
| 1 | Existing-system audit | Done: 243-test baseline, live node, RPC, monitoring verified before changes |
| 2 | `template.py` - getblocktemplate acquisition | Strict validation of every brief-listed field; staleness via tip change + BIP22 expiry; regtest-only |
| 3 | `builder.py` - candidate block construction | txid/wtxid recomputed from raw data (fail closed), dependency/limit-aware selection, BIP34 coinbase, subsidy+fee accounting (never above coinbasevalue), BIP141 witness commitment cross-checked with Core, extra-nonce/time variation |
| 4 | `search.py` - PoW search | Batches dispatched through `ComputeEngine` (actual backend recorded, CUDA fault -> CPU fallback recorded); target validated vs regtest limit; exhaustion -> bounded extra-nonce escalation; time updates clamped to mintime and network-adjusted MAX_FUTURE_BLOCK_TIME; staleness/cancel checked between batches; budgets; independent CPU re-verification of every nonce before reporting |
| 5 | Submission/acceptance (`session.py`) | submitblock, duplicate vs rejection distinguished, active-chain verification (confirmations + best block), all rejection reasons recorded |
| 6 | `stats.py` - persistent statistics | SQLite (project store pattern, own mining.db); all brief Phase 6 fields; survives restarts; benchmark numbers excluded |

**TASK 006 - autonomous agent (`agent/autonomous/`)**

| Phase | Component | Status |
| --- | --- | --- |
| 7 | Architecture | Agent coordinates through existing interfaces; no duplicate implementations |
| 8 | Lifecycle | initialize/observe/prepare/compute/verify/submit/repeat; recovery from interrupted sessions via persistent state |
| 9 | Computation management | `ComputationManager` over `ComputeEngine`; backend chosen from a measured real batch; honest CPU fallback with recorded reason; TASK 004 privacy bounds kept |
| 10 | Decision-making | Every decision recorded with reasons (backend, start, stale work, cycle outcomes, backoff, halt); no random decisions; consensus validation never bypassed |
| 11 | Control interface | start/stop/pause/resume/status/blockchain_status/backend_status/current_stats/historical_stats/decisions/errors/diagnostics; resource limits; graceful shutdown; no credentials in logs or source |

## Test results (live, 2026-11-13)

- Full suite: **309 tests, OK, 2 skipped** (the two CUDA tests, below).
- New tests added: 66 (template 18, builder 13, search 10, session 6, agent 11, backend dispatch 8), each stage's unit tests plus live regtest integration. Backend dispatch tests cover ComputeEngine-wired search, injected CUDA-fault -> CPU fallback with the real fallback code path, staleness abandonment mid-batch, network-adjusted block-time clamping (including fail-closed mintime beyond the future limit), and batch-size management. Recovery evidence includes an actual SIGKILL of a mining agent subprocess mid-session, after which a fresh agent detects the dead session, records a recovery event, and mines to completion.
- Live consensus proof: candidates built by the new builder were accepted by
  Bitcoin Core 32.1 onto the active chain.
- Autonomous demonstration: `scripts/milestone_005_006.py --cycles 3` -
  **3/3 agent-managed cycles accepted**, chain advanced 0 -> 3, zero errors,
  statistics persisted and re-read after restart. Raw capture:
  `results/TASK_005_006_RESULTS.md`.

### Accepted-block evidence (own engine, not generatetoaddress)

Final build (backend-dispatched search): `results/TASK_005_006_RESULTS.md`,
captured 2026-11-13T15:30:31Z, agent-managed cycles on a disposable regtest
node; every nonce batch dispatched through `gpu.engine.ComputeEngine`.

| Height | Block hash | Nonce | Hashes | Peak H/s | Session |
| --- | --- | --- | --- | --- | --- |
| 1 | 37d7ad1e05012c3e558f352fb587b779c61af526991f4de2e479682b1991db69 | 4 | 65536 | 529620.2 | 7fb9e975 |
| 2 | 117fdbf77695c44e06382ede366ad9c470a5e2ef04f20a0ddb2fd32ccce1cee9 | 2 | 131072 | 521599.8 | bcb5d465 |
| 3 | 60a155a626a7f0fcb3c151a5662d84d9c0d154756527cb155cdf2f7eaaa9418b | 0 | 131072 | 420179.0 | b309f0e9 |

Run totals: 3 cycles, 3 accepted, 327680 hashes, average 431901.2 H/s (CPU
backend; CUDA unavailable in this environment, reason recorded). Hash counts
are whole dispatched batches: a batch is fully computed even when its match
is found early. A live screenshot run of the same build (15:31Z) shows the
same 3/3 outcome with hashes 12e90b98e3f2870ef..., 22f9ed408614b96d...,
1e20c27d2740c4da....

Earlier build (direct CPU searcher), preserved: same results file, captured
2026-11-13T15:21:16Z: heights 1-3, block hashes 2311193bf09ce990...,
7d44685f51265142..., 6c812ebf34036408..., 5 total hashes, average 346.1 H/s
(tiny-sample caveat: single-millisecond-batch measurements, this run only).
An ad-hoc live test of the session stage before that (three accepted cycles)
was not hash-preserved and its block hashes are unrecoverable: it ran on a
disposable node and stats database that were cleaned up, and no surviving
log records them; the recorded runs above are the preserved evidence.

Each cycle: template acquired via getblocktemplate, candidate constructed by
`mining.engine.builder`, nonce searched through the compute backend, verified
independently by `mining.pow.validator`, submitted with submitblock, accepted
(Core returned no rejection), confirmed best block at its height.

## The two skipped GPU tests - investigated

1. `tests.test_gpu_compute.TestCompute.test_real_cuda_or_honest_skip`
   - skip reason: "real CUDA unavailable; no simulated success".
2. `tests.test_gpu_regtest.TestComputeCore.test_core_header_real_cuda_or_skip`
   - skip reason: "CUDA execution blocked; Core CPU validation runs separately".

Both require a working CUDA driver/device. In this environment (documented in
TASK 004): the CUDA 13.0 toolkit compiles the kernels, but the driver library
is not loadable (runtime init error 35, insufficient driver), there are no
admin rights to install one, and the CUDA control device is absent. GPU
execution is therefore **not operational and is not claimed**. These tests are
written to skip honestly rather than simulate GPU success; they will execute
unmodified on a machine where the CUDA runtime genuinely initializes. CPU
fallback and CPU validation run and pass everywhere.

## Audit and quality gates before push

- pyflakes clean over all new/changed files (7 findings fixed: unused imports,
  dead variable, f-string misuse, and one real schema-execution bug caught by
  tests - multi-statement DDL needed `executescript`).
- Privacy/secrets scan over all staged files: no hardware-identity queries, no
  sandbox paths, no cookies/credentials.
- No existing file's behavior changed; additions only (plus README/roadmap).
- Fresh public clone at 41a979f re-ran the 57 new tests: all pass.

## Outstanding issues / corrections still open

1. **CUDA execution unverified** (environment limitation, above).
2. The agent control interface is in-process Python; a network/CLI control
   surface is out of scope.
3. Integration with the pre-existing modules (blockchain primitives, node
   manager/RPC client, storage, template miner) uses their public interfaces
   and observed live behavior only; those modules were not modified. Every
   new integration path is covered by passing tests.
4. Regtest difficulty cannot exercise hard targets; hard-target behavior is
   covered by mainnet header fixtures in the TASK 003 suite.

## Restrictions honored

Regtest only; no mainnet/testnet/signet; no pools; no real money; $0 spent;
no new infrastructure or driver changes; no fabricated mining or GPU results;
no hardware identities requested, exposed or inferred.
