# Pre-TASK 007 correction milestone - engineering report

Date: 2026-11-13. Base commit: 378f737 (TASK 005/006 corrections). Scope:
review-driven hardening of the mining engine and autonomous agent, plus
documentation reconciliation and a live three-cycle reproduction. Regtest
only. No consensus, RPC-guard or privacy-restriction logic was altered.

Live evidence: `results/CORRECTION_PRE_007_RESULTS.md` (full run log,
preserved mining database and state file, suite/static/security outputs).

## 1. Issues found and corrections implemented

### 1.1 Mining database permissions (mining/engine/stats.py)

Issue: `ChainStore` creates its SQLite database owner-only (0600), but
`MiningStatsStore` created the mining database with default (umask)
permissions, and never restricted an existing permissive file.

Corrections:

- `MiningStatsStore.__init__` (stats.py:89) now creates the parent
  directory with `os.makedirs(..., exist_ok=True)` (stats.py:92), creates
  the database file owner-only with `os.open(..., 0o600)` before SQLite
  opens it (stats.py:113), and calls the new `_owner_only()` helper
  (stats.py:65) which `chmod`s the file to 0600 on POSIX systems -
  including an existing database that was left permissive. On platforms
  without POSIX permission semantics the chmod is skipped. Restriction is
  never weakened; a real chmod failure raises instead of hiding.
- Agent state file (`agent/autonomous/agent.py:_write_state`, agent.py:136): the write
  is now race-safe and atomic - a private, uniquely-named temporary file
  is created with `tempfile.mkstemp` (O_CREAT|O_EXCL, mode 0600) in the
  same directory and atomically renamed over the final path. There is no
  fixed temp name an attacker could pre-plant a symlink at, and
  `os.replace` never follows a symlink at the destination (it replaces
  the link itself). The final file is chmod'ed 0600 on POSIX, which also
  repairs a previously permissive file.
- Unsafe database paths are refused, never clobbered: a symlink (dangling
  or not) or a non-regular file at the database path raises ValueError
  before anything is opened, and new databases are created with
  O_NOFOLLOW where the platform offers it (kernel-enforced at open, not
  check-then-use). Documented residual: the sqlite3 stdlib API follows
  symlinks at connect time, so a link swapped in between validation and
  connect cannot be fully excluded; the state directory is expected to be
  private.

Tests: `tests/test_stats_permissions.py` (7 tests: parent-dir creation,
new DB is 0600, existing permissive DB restricted, data preserved across
restriction, symlink database path refused without clobbering its target,
dangling symlink refused without creating its target, non-regular path
refused) and `TestAgentShutdown.test_agent_state_file_is_owner_only`
(including repair of a permissive state file) plus
`test_state_write_never_follows_symlinks` (a symlink planted at the final
state path is replaced, its target untouched; a symlink planted at the
legacy fixed temp name is never used). POSIX-only assertions skip cleanly
elsewhere.

### 1.2 Agent shutdown truthfulness (agent/autonomous/agent.py)

Issue: `stop()` set state STOPPED and persisted it unconditionally after a
30-second `join`, even if the mining worker thread was still alive - a
false STOPPED in `status()` and in the state file.

Corrections (`stop()`, agent.py:263):

- New `AgentState.STOPPING` (agent.py:46): cancellation has been signalled
  but the worker has not verifiably terminated.
- `stop()` signals cancellation, calls `engine.stop()`, joins with a
  configurable timeout (`shutdown_timeout`, default 30 s, agent.py:113),
  then checks `thread.is_alive()` (agent.py:285).
- STOPPED is reported and persisted only after the worker has verifiably
  terminated. On timeout, `stop()` returns an explicit shutdown-timeout
  error, records an error event, and the state stays STOPPING in memory,
  in `status()` and in the state file - no false STOPPED anywhere.
- When the worker does exit, the lifecycle's `finally` converges the state
  to a truthful STOPPED (stop_event was set). A later `stop()` observes
  the real state.
- Resource cleanup is unchanged: cancellation is signalled before the
  join in every path.
- Related hazard closed: `start()` now also refuses while STOPPING, so a
  second worker can never be started while a stuck worker from the
  previous session is still alive (would have double-mined).

Tests (`tests/test_agent_autonomous.py`, class `TestAgentShutdown`):
normal shutdown reports STOPPED only with the thread dead
(test_shutdown_reports_stopped_after_worker_exits), stop from paused,
shutdown timeout with a genuinely stuck worker - status and state file
both read "stopping", an error event is recorded, `start()` is refused
while the stuck worker lives, and the state converges to "stopped" once
the worker is released
(test_shutdown_timeout_never_reports_false_stopped), and stop-when-idle
cancellation.

### 1.3 Resource-limit validation (agent/autonomous/agent.py)

Issue: `ResourceLimits` accepted any values, including zero/negative cycle
limits, negative time budgets, negative hash limits, negative pauses,
zero/negative consecutive-failure limits and negative backoffs - the
controller could run with nonsensical or accidentally unbounded settings.

Correction: `ResourceLimits.__post_init__` (agent.py:92) validates every
field through `_require_positive_int` / `_require_positive_number` /
`_require_non_negative_number` (agent.py:51-70), rejecting zeros,
negatives, booleans,
wrong types - and, after a follow-up audit, all nonfinite values
(math.isfinite): NaN and +inf were verified to slip through the first
version (an inf time budget is an unbounded budget; a NaN/inf pause or
backoff corrupts the lifecycle's waits). `shutdown_timeout` is validated
the same way (positive, finite, numeric; NaN previously passed its `<= 0`
check). `max_hashes_per_cycle=None` remains the one explicit opt-out (no
per-cycle hash cap), a deliberate choice rather than an accident.

Tests: `TestResourceLimitsValidation` (6 tests: defaults valid, boundary
values accepted, None hash limit explicit, 15 invalid configurations
rejected, 7 nonfinite configurations rejected, shutdown_timeout validated
including NaN/inf/0/negative/wrong-type).

### 1.4 Documentation reconciliation

- `README.md` - removed the duplicated TASK 001 paragraph; repository
  layout and roadmap now describe the actual CUDA implementation (source
  compiled, GPU execution unverified) instead of "not yet implemented";
  status section carries the current suite counts (326 run, 324 passed,
  2 skipped); `generatetoaddress` labelled as a Core testing utility.
- `gpu/README.md` - rewritten: was "intentionally not implemented"; now
  describes ComputeEngine, the CUDA source (compiles under CUDA 13.0),
  the honest CPU fallback, and the unverified-GPU status.
- `docs/ARCHITECTURE.md` - layout now includes `mining/engine/`,
  `agent/autonomous/` and the real `gpu/` contents; added the autonomous
  mining data flow; `generatetoaddress` distinguished from the mining
  path.
- `docs/REGTEST.md` - `generatetoaddress` described as a testing utility
  used only by early milestones/tests; the engine's own
  getblocktemplate -> build -> search -> submitblock path stated.
- `docs/SECURITY.md` - the 0600 guarantee now covers the chain DB, the
  mining stats DB and the agent state file (tmp + final, with repair);
  wallet paragraph covers the engine's own coinbase.
- `docs/MINING_ENGINE.md` - added the owner-only database, truthful
  shutdown semantics and resource-limit validation; test list updated.
- `docs/CUDA_TASK_004.md`, `docs/TASK_005_006_REPORT.md` and all
  `results/*.md` - preserved unchanged except a header label naming their
  original date and environment; no historical result was rewritten to
  look current.
- Roadmap consistency: every file now agrees - TASKs 001-006 done, CUDA
  source compiled/execution unverified, pre-007 hardening done, TASK 007
  next.

## 2. Live Regtest reproduction (brief item 5)

`python3 scripts/milestone_005_006.py --cycles 3` on a disposable Bitcoin
Core 32.1 regtest node (tarball SHA-256 verified against the published
SHA256SUMS). The agent ran the full lifecycle unaided; Bitcoin Core
accepted all three blocks; the chain advanced 0 -> 3; the mining database
recorded all three accepted cycles and read back correctly after
reopening. Full log and independent DB re-read in
`results/CORRECTION_PRE_007_RESULTS.md`; the actual `mining.db` and
`agent_state.json` (both mode 0600) are preserved in
`results/correction-pre-007/`. `generatetoaddress` was not used.

Accepted blocks (2026-11-13 ~16:06 UTC, this environment, final code):

| height | block hash | nonce | hashes | submit |
| --- | --- | --- | --- | --- |
| 1 | 03f64bd387653681155e7503427e4e6b5745acd11f65e95ecd94be36ab4c636c | 0 | 65536 | accepted |
| 2 | 0db6f9448077091c48d18f8d0768d017932fd31dcb9e6a9a9efdb920dbb57b5b | 1 | 131072 | accepted |
| 3 | 758c9a480b7298b10481a528da0eb45713b473fe8f7dbc11dd87a6277a738598 | 1 | 131072 | accepted |

## 3. Test results (this environment, final state)

- Normal suite: 326 tests run, 324 passed, 2 skipped, 0 failed, 0 errors.
- Optimized suite (`python -O`): 326 run, 324 passed, 2 skipped.
- Live regtest integration tests included (run against the verified Core
  32.1 binary), including the new permission, shutdown and resource-limit
  tests.
- Skipped (never counted as passed): the two real-CUDA tests -
  `test_gpu_compute...test_real_cuda_or_honest_skip` ("real CUDA
  unavailable; no simulated success") and
  `test_gpu_regtest...test_core_header_real_cuda_or_skip` ("CUDA execution
  blocked; Core CPU validation runs separately").
- Unexecuted tests: none beyond the 2 skips. Warnings: none.
- Syntax/compilation: `python3 -m compileall -q .` clean.
- Static analysis: `python3 -m pyflakes .` clean.
- Security analysis: `python3 -m bandit -r . -x ./tests,./.git`:
  0 High, 0 Medium, 8 Low. Bandit's one Medium heuristic (SQL string
  construction in `mining/engine/stats.py`) was reviewed and is a false
  positive: the interpolated text is the fixed module-level COLUMNS
  allowlist and all values are bound parameters; a justified `# nosec
  B608` records that review. The 8 Low findings are the known subprocess
  calls (bitcoind lifecycle, CUDA toolchain build/install) - argument
  lists, no shell, pinned sources.

## 4. CUDA operational status

Unchanged and still unverified: CUDA source compiles under the userspace
13.0 toolkit, but the runtime cannot initialize in this environment (no
loadable system driver / device access), so the two real-CUDA tests skip
honestly. No GPU execution, speed or capability is claimed. All measured
results are CPU.

## 5. Final source audit (brief item 7)

- No broken imports, undefined names or syntax errors (pyflakes,
  compileall, full suite).
- No consensus-logic changes: the diff touches no target/PoW/consensus
  code; changes are confined to stats permissions, agent shutdown, limit
  validation, the milestone script's additive `--keep` option, tests and
  documentation.
- No credential exposure: no secrets added; state files are now 0600.
- Regtest-only restrictions untouched (chain guards unmodified).
- State-file symlink attacks are closed race-safely (unique-temp atomic
  replace; no fixed temp name; destination links are replaced, never
  followed - adversarial tests verify the target is untouched). Database
  paths are partially mitigated: symlink/non-regular paths are refused
  before open and new databases are created with O_NOFOLLOW
  (kernel-enforced), but the sqlite3 stdlib API itself follows symlinks
  at connect time, so a link swapped in between validation and connect
  cannot be excluded - the state directory must be private. This
  residual is documented in `mining/engine/stats.py` and not claimed
  closed.
- No incorrect GPU capability claims anywhere in code or docs.
- Agent status reporting is now truthful on the shutdown path (1.2).
- Resource limits cannot be bypassed with invalid values (1.3).
- Persistence behavior intact and now owner-only (1.1); milestone run
  verified reopen-readability.
- Privacy restrictions preserved: no hardware identity, architecture or
  compute-capability probing added; diagnostics remain operational only.

## 6. Remaining limitations

- GPU execution unverified (above); CUDA cannot be claimed operational
  until it runs on GPU-capable hardware.
- The agent's control interface is in-process Python (dicts), not a remote
  protocol.
- Regtest hashrate figures are low-difficulty, small-sample measurements
  from a single test run - indicative only.
- The original intermediate three-block run from the earlier session was
  lost when its temporary data was cleaned; the canonical preserved runs
  are `results/TASK_005_006_RESULTS.md` and this milestone's run. Nothing
  was reconstructed or invented to fill that gap.

## 7. Files changed

- `mining/engine/stats.py` - owner-only DB creation/restriction, parent
  dir creation, nosec-justified insert.
- `agent/autonomous/agent.py` - STOPPING state, truthful stop(),
  shutdown_timeout, ResourceLimits validation, owner-only state files.
- `scripts/milestone_005_006.py` - additive `--keep` evidence preservation.
- `tests/test_stats_permissions.py` - new (7 tests).
- `tests/test_agent_autonomous.py` - new TestAgentShutdown (5 tests) and
  TestResourceLimitsValidation (6 tests).
- Docs: `README.md`, `gpu/README.md`, `docs/ARCHITECTURE.md`,
  `docs/REGTEST.md`, `docs/SECURITY.md`, `docs/MINING_ENGINE.md`,
  `docs/CUDA_TASK_004.md` (label only), `docs/TASK_005_006_REPORT.md`
  (label only).
- Results: historical labels on `results/TEST_RESULTS*.md`,
  `results/CUDA_TEST_RESULTS_004.md`, `results/TASK_005_006_RESULTS.md`;
  new `results/CORRECTION_PRE_007_RESULTS.md` and preserved artifacts in
  `results/correction-pre-007/`.

## 8. Git

Two local commits on top of origin/main (378f737):

- `c26d958b37b16bd7caed63525b45b8be7a6dbebf` - the corrections
  (permissions, shutdown, resource limits, documentation, live
  reproduction).
- the hardening follow-up (nonfinite limit rejection, race-safe atomic
  state writes, symlink-safe database paths, refreshed evidence) - the
  commit that also contains this document; its exact hash is reported
  with the milestone delivery, since a document cannot embed its own
  commit hash.

Working tree clean. Not pushed: push waits for explicit approval, per
the milestone instructions.
