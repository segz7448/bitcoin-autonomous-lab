# Pre-TASK 007 correction milestone - live reproduction evidence

Captured 2026-11-13 (approx. 16:06 UTC) in this test run:
Python 3.10.12, Bitcoin Core 32.1
(release tarball SHA-256 `61545c17c3120fb7412f896d248b11993af04ec8817aad3649c55b2afb044963`,
verified against the published SHA256SUMS before use), regtest only.
This run executes the final corrected code (all correction commits). The
genuine live-terminal capture of this exact run is delivered with the
milestone report (the `+` lines are the exact commands as executed under
`bash -x`; nothing retyped or replayed).

## 1. Live three-cycle autonomous reproduction (brief item 5)

Command:

```
BAL_BITCOIND=<verified Core 32.1> python3 scripts/milestone_005_006.py --cycles 3 --keep results/correction-pre-007
```

A disposable regtest node was started by the script. The autonomous agent
- with no manual intervention per cycle - acquired work with
`getblocktemplate`, constructed each candidate block, searched the SHA256d
nonce space through ComputeEngine batches, CPU-verified each solution,
submitted with `submitblock`, and confirmed acceptance on the active
chain. `generatetoaddress` was not used for block production.

Full, unabridged output:

```
node ready: chain=regtest height=0

== pre-mining diagnostics ==
  core_connectivity: True
  chain: regtest
  regtest_only: True
  blocks: 0
  headers: 0
  synchronized: True
  mining_work_available: True
  next_height: 1
  backend: cpu
  backend_fallback_reason: CUDA unavailable or self-test failed
  backend_benchmark_hs: 333475.7
  engine_ready: True

== starting autonomous agent for 3 cycles ==
  start: {'ok': True, 'state': 'running', 'backend': 'cpu'}
  cycle 1: accepted height=1 hash=03f64bd387653681155e7503427e4e6b5745acd11f65e95ecd94be36ab4c636c nonce=0 hashes=65536 (504917.9 H/s)
  cycle 2: accepted height=2 hash=0db6f9448077091c48d18f8d0768d017932fd31dcb9e6a9a9efdb920dbb57b5b nonce=1 hashes=131072 (492090.3 H/s)
  cycle 3: accepted height=3 hash=758c9a480b7298b10481a528da0eb45713b473fe8f7dbc11dd87a6277a738598 nonce=1 hashes=131072 (502791.0 H/s)

== blockchain status after autonomous mining ==
  blocks: 3
  best block: 758c9a480b7298b10481a528da0eb45713b473fe8f7dbc11dd87a6277a738598

== persistent mining statistics ==
  cycles: 3  accepted: 3
  total hashes: 327680  avg hashrate: 477883.9 H/s
  total coinbase value: 15000000000 sats (regtest, worthless)
  session 66e4d022: height 3 accepted=1 backend=cpu hashes=131072 peak=532860.0 H/s
  session 11a5eab0: height 2 accepted=1 backend=cpu hashes=131072 peak=521949.2 H/s
  session 99b1a381: height 1 accepted=1 backend=cpu hashes=65536 peak=530822.8 H/s

== agent decisions ==
  [backend-selected] backend=cpu (requested auto); fallback_reason=CUDA unavailable or self-test failed; measured 333476 H/s
  [mining-started] limits: max_cycles=3, max_seconds_per_cycle=60
  [batch-size-adjusted] batch_size 65536 -> 131072 from measured batch time 0.138s
  [cycle-accepted] height=1 hash=03f64bd387653681155e7503427e4e6b5745acd11f65e95ecd94be36ab4c636c nonce=0 hashes=65536 in 0.138s
  [cycle-accepted] height=2 hash=0db6f9448077091c48d18f8d0768d017932fd31dcb9e6a9a9efdb920dbb57b5b nonce=1 hashes=131072 in 0.277s
  [cycle-accepted] height=3 hash=758c9a480b7298b10481a528da0eb45713b473fe8f7dbc11dd87a6277a738598 nonce=1 hashes=131072 in 0.271s

== errors / recovery events: 0 ==

== persistence check (reopened database) ==
  cycles visible after restart: 3

RESULT: PASS - 3/3 autonomous cycles accepted by Bitcoin Core
preserved mining.db -> results/correction-pre-007/ (mode 0o600)
preserved agent_state.json -> results/correction-pre-007/ (mode 0o600)
```

Verified against the checklist:

- own template manager obtained mining work: yes (backend probe + next_height diagnostics)
- own block builder constructed each candidate: yes (blocks accepted by Core on `submitblock`)
- own SHA256d engine searched each nonce: yes (backend=cpu recorded per cycle)
- CPU verification confirmed each candidate: yes (engine verifies before submission)
- submission via `submitblock`: yes, `submit_result=accepted` per cycle
- Bitcoin Core accepted each block: yes, 3/3
- active chain advanced by three: yes (blocks 0 -> 3, best block = cycle-3 hash)
- mining database recorded all three accepted cycles: yes (see below)
- database readable after reopening: yes (script persistence check + independent re-read below)
- agent completed the lifecycle with no manual intervention: yes (final state idle, 0 error events)

## 2. Preserved artifacts

The script's `--keep` option preserved the actual mining database and
agent state file before the disposable node was removed:

```
results/correction-pre-007/mining.db         mode 0600
results/correction-pre-007/agent_state.json  mode 0600
```

Both files are owner-only (0600) - the permission hardening applied to a
real run. The state file was written through the race-safe unique-temp +
atomic-rename path.

Independent re-read of the preserved database (fresh sqlite3 connection,
after the run):

```
session 99b1a381: height=1 hash=03f64bd387653681155e7503427e4e6b5745acd11f65e95ecd94be36ab4c636c nonce=0 hashes=65536 avg=504917.9 peak=530822.8 backend=cpu submit=accepted accepted=1 seconds=0.138
session 11a5eab0: height=2 hash=0db6f9448077091c48d18f8d0768d017932fd31dcb9e6a9a9efdb920dbb57b5b nonce=1 hashes=131072 avg=492090.3 peak=521949.2 backend=cpu submit=accepted accepted=1 seconds=0.277
session 66e4d022: height=3 hash=758c9a480b7298b10481a528da0eb45713b473fe8f7dbc11dd87a6277a738598 nonce=1 hashes=131072 avg=502791.0 peak=532860.0 backend=cpu submit=accepted accepted=1 seconds=0.271
agent_decisions rows: 6; agent_events rows: 0
agent_state.json: {"state": "idle", "updated_at": "2026-11-13T16:06:16.306747+00:00", "cycles_completed": 3, "backend": "cpu"}
```

## 3. Accepted blocks (this run)

| height | block hash | nonce | hashes | session |
| --- | --- | --- | --- | --- |
| 1 | 03f64bd387653681155e7503427e4e6b5745acd11f65e95ecd94be36ab4c636c | 0 | 65536 | 99b1a381 |
| 2 | 0db6f9448077091c48d18f8d0768d017932fd31dcb9e6a9a9efdb920dbb57b5b | 1 | 131072 | 11a5eab0 |
| 3 | 758c9a480b7298b10481a528da0eb45713b473fe8f7dbc11dd87a6277a738598 | 1 | 131072 | 66e4d022 |

Hashrates (~477-505 kH/s average) are regtest low-difficulty CPU
measurements from a single test run - indicative only, not benchmarks.

## 4. Test suites (brief item 6), this environment, final code

- Normal suite: `python3 -m unittest discover -s tests -t .`
  -> **326 tests, OK, 2 skipped** (includes live regtest integration tests
  against the verified Core 32.1 binary).
- Optimized suite: `python3 -O -m unittest discover -s tests -t .`
  -> **326 tests, OK, 2 skipped**.
- Skips (both real-CUDA tests, honestly skipped, not counted as passed):
  - `tests.test_gpu_compute.TestCompute.test_real_cuda_or_honest_skip`
    - "real CUDA unavailable; no simulated success"
  - `tests.test_gpu_regtest.TestComputeCore.test_core_header_real_cuda_or_skip`
    - "CUDA execution blocked; Core CPU validation runs separately"
- 0 unexecuted tests beyond the 2 skips. 0 failures. 0 errors.
- Expected stderr during the suite: negative-path tests (adversarial,
  monitor reorg/outage, RPC failure mapping) deliberately log simulated
  failures ("simulated outage", "reorg detected", ...); these are test
  fixtures asserting error handling, not warnings or defects.
- Syntax/compilation: `python3 -m compileall -q .` -> clean (exit 0).
- Static analysis: `python3 -m pyflakes .` -> clean (exit 0).
- Security analysis: `python3 -m bandit -r . -x ./tests,./.git` ->
  0 High, 0 Medium, 8 Low. (The one Medium it initially raised - an SQL
  string-construction heuristic on `mining/engine/stats.py` - was reviewed:
  the interpolated text is the fixed module-level COLUMNS allowlist and all
  values are bound parameters; a justified `# nosec B608` note records that
  review.) The 8 Low findings are the known, documented subprocess calls
  (bitcoind lifecycle, CUDA toolchain build/install) - argument lists, no
  shell, pinned sources.
