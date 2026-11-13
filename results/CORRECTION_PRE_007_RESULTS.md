# Pre-TASK 007 correction milestone - live reproduction evidence

Captured 2026-11-13 (approx. 15:55 UTC) in this execution environment:
disposable Linux x86_64 sandbox, Python 3.10.12, Bitcoin Core 32.1
(release tarball SHA-256 `61545c17c3120fb7412f896d248b11993af04ec8817aad3649c55b2afb044963`,
verified against the published SHA256SUMS before use), regtest only.

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
  backend_benchmark_hs: 328664.7
  engine_ready: True

== starting autonomous agent for 3 cycles ==
  start: {'ok': True, 'state': 'running', 'backend': 'cpu'}
  cycle 1: accepted height=1 hash=5617ef9f6accb38b6f495c3d2aff9d4a6d629c49ab939a49faa96fbc65dcb861 nonce=0 hashes=65536 (498769.4 H/s)
  cycle 2: accepted height=2 hash=37b0806f454e42d4887e92f2fa05c4b3ed207fdf718f96dd55ea35020a402f6b nonce=3 hashes=131072 (488843.6 H/s)
  cycle 3: accepted height=3 hash=3f8134988cef380c4b0d1496845edd7b683ebb82b7281b23464b1aca7d857ace nonce=3 hashes=131072 (495125.2 H/s)

== blockchain status after autonomous mining ==
  blocks: 3
  best block: 3f8134988cef380c4b0d1496845edd7b683ebb82b7281b23464b1aca7d857ace

== persistent mining statistics ==
  cycles: 3  accepted: 3
  total hashes: 327680  avg hashrate: 473950.7 H/s
  total coinbase value: 15000000000 sats (regtest, worthless)
  session 72185cee: height 3 accepted=1 backend=cpu hashes=131072 peak=518481.1 H/s
  session 38ec2055: height 2 accepted=1 backend=cpu hashes=131072 peak=517862.9 H/s
  session dee3eb22: height 1 accepted=1 backend=cpu hashes=65536 peak=525263.8 H/s

== agent decisions ==
  [backend-selected] backend=cpu (requested auto); fallback_reason=CUDA unavailable or self-test failed; measured 328665 H/s
  [mining-started] limits: max_cycles=3, max_seconds_per_cycle=60
  [batch-size-adjusted] batch_size 65536 -> 131072 from measured batch time 0.139s
  [cycle-accepted] height=1 hash=5617ef9f6accb38b6f495c3d2aff9d4a6d629c49ab939a49faa96fbc65dcb861 nonce=0 hashes=65536 in 0.139s
  [cycle-accepted] height=2 hash=37b0806f454e42d4887e92f2fa05c4b3ed207fdf718f96dd55ea35020a402f6b nonce=3 hashes=131072 in 0.278s
  [cycle-accepted] height=3 hash=3f8134988cef380c4b0d1496845edd7b683ebb82b7281b23464b1aca7d857ace nonce=3 hashes=131072 in 0.274s

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

The script's new `--keep` option preserved the actual mining database and
agent state file before the disposable node was removed:

```
results/correction-pre-007/mining.db         mode 0600
results/correction-pre-007/agent_state.json  mode 0600
```

Both files are owner-only (0600) - the new permission hardening applied
to a real run.

Independent re-read of the preserved database (fresh sqlite3 connection,
after the run):

```
session dee3eb2236bc475eb7f99ffa25c1892b: height=1 hash=5617ef9f6accb38b6f495c3d2aff9d4a6d629c49ab939a49faa96fbc65dcb861 nonce=0 hashes=65536 avg=498769.4 peak=525263.8 backend=cpu submit=accepted accepted=1 seconds=0.139
session 38ec2055576542bab60f083acc7bb42d: height=2 hash=37b0806f454e42d4887e92f2fa05c4b3ed207fdf718f96dd55ea35020a402f6b nonce=3 hashes=131072 avg=488843.6 peak=517862.9 backend=cpu submit=accepted accepted=1 seconds=0.278
session 72185cee476e4f4cb3937fb314d6eabf: height=3 hash=3f8134988cef380c4b0d1496845edd7b683ebb82b7281b23464b1aca7d857ace nonce=3 hashes=131072 avg=495125.2 peak=518481.1 backend=cpu submit=accepted accepted=1 seconds=0.274
agent_decisions rows: 6; agent_events rows: 0
agent_state.json: {"state": "idle", "updated_at": "2026-11-13T15:55:38.854677+00:00", "cycles_completed": 3, "backend": "cpu"}
```

## 3. Accepted blocks (this run)

| height | block hash | nonce | hashes | session |
| --- | --- | --- | --- | --- |
| 1 | 5617ef9f6accb38b6f495c3d2aff9d4a6d629c49ab939a49faa96fbc65dcb861 | 0 | 65536 | dee3eb22 |
| 2 | 37b0806f454e42d4887e92f2fa05c4b3ed207fdf718f96dd55ea35020a402f6b | 3 | 131072 | 38ec2055 |
| 3 | 3f8134988cef380c4b0d1496845edd7b683ebb82b7281b23464b1aca7d857ace | 3 | 131072 | 72185cee |

Hashrates (~474-499 kH/s average) are regtest low-difficulty CPU
measurements on this sandbox - indicative only, not benchmarks.

## 4. Test suites (brief item 6), this environment

- Normal suite: `python3 -m unittest discover -s tests -t .`
  -> **321 tests, OK, 2 skipped** (includes live regtest integration tests
  against the verified Core 32.1 binary).
- Optimized suite: `python3 -O -m unittest discover -s tests -t .`
  -> **321 tests, OK, 2 skipped**.
- Skips (both real-CUDA tests, honestly skipped, not counted as passed):
  - `tests.test_gpu_compute.TestCompute.test_real_cuda_or_honest_skip`
    - "real CUDA unavailable; no simulated success"
  - `tests.test_gpu_regtest.TestComputeCore.test_core_header_real_cuda_or_skip`
    - "CUDA execution blocked; Core CPU validation runs separately"
- 0 unexecuted tests beyond the 2 skips. 0 failures. 0 errors. 0 warnings.
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
