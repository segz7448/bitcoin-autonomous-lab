# FINAL VERIFICATION - TASKS 001-006

Date: November 13, 2026. Bitcoin Autonomous Lab. Regtest only.

## Verdict: CONDITIONAL PASS

Source and all available automated, live Regtest, static and reviewed
security verification requirements pass after two necessary corrections.
Actual CUDA execution remains unverified because the driver is not loadable
and CUDA runtime device access returns status 35 (insufficient driver).
This is not a full PASS. No GPU execution, GPU speed or real-BTC earnings
are claimed.

- Independently cloned and tested baseline: `7187bfdfbebd7775bd9908fd2138beb892c12c83`.
- Verified correction/source commit: `dc89bd44918a0f8cd4d251646b5769033abb0774`.
- The documentation/evidence commit contains no subsequent production-code
  changes. Its exact hash is supplied with delivery, rather than a stale
  self-referential hash in this document.
- Nothing from this final-verification assignment has been pushed. Publication
  is on hold pending the user's decision about the conditional CUDA verdict.
- Python 3.10.12, Bitcoin Core 32.1, pytest 9.2.0, pyflakes 4.0.3,
  Bandit 1.9.4, CUDA toolkit 13.0. No paid resources.

Complete outputs: `results/FINAL_VERIFICATION_001_006_RESULTS.md`.
Raw evidence: `results/final-verification-001-006/`.

## 1. Independent baseline and necessary corrections

The initial untouched clone passed 324 tests with 2 real-CUDA skips in both
normal and optimized pytest runs. Normal warnings: 0. Optimized warnings: 1.
Static checks and three live mining cycles also passed. These results did
not replace source review.

### ChainStore permissions and unsafe paths

Reproduced: reopening an existing chain database with mode 0644 left it
0644, contrary to the security documentation's owner-only promise. A
pre-planted dangling symlink was followed and its target was created.
All reproductions used disposable local test files.

`blockchain/storage.py` now rejects a symlink or non-regular main database
path, creates a new file with O_EXCL and O_NOFOLLOW where supported, and
repairs an existing database to 0600 on POSIX before connecting. Errors are
not hidden. Six focused tests cover creation, permission repair with data
preservation, existing/dangling symlinks, directory refusal and chmod failure.

Residual boundary: this is not a race-proof SQLite pathname API. Validation,
chmod and sqlite3.connect are distinct operations; SQLite also opens
journal/WAL/SHM paths. Keep all local state in a private directory that
other users cannot write. The same directory requirement applies to the
mining database and agent state. No claim is made that an attacker-writable
state directory is safe.

### Non-overridable Regtest template boundary

Reproduced without using a real non-Regtest node:
`TemplateManager(fake_rpc, expected_chain='main').acquire()` accepted a fake
RPC reporting chain `main`. The default engine was Regtest-only, but the
public parameter contradicted the module's unconditional Regtest contract.

`mining/engine/template.py` now refuses every expected_chain except
`regtest`, and acquire checks the node against the fixed `regtest` value.
Two new tests exercise constructor and acquisition refusal for six
non-Regtest/missing chain values. No consensus rules or target checks changed.

The eight regression methods passed after correction (12 parameterized
subtests). Their pre-fix output is preserved verbatim, including pytest's
separate failed-subtest entries. No findings were suppressed to force success.

## 2. Fresh live Bitcoin Core Regtest

Executed on a new disposable node:

```text
python3 scripts/milestone_005_006.py --cycles 3 --keep /downloads/final-verification/evidence/preserved
```

`--keep` only preserves the database/state before normal node cleanup. The
same script was also executed by an independent observer with arguments
`--cycles 3` on a second fresh node. Both runs exited 0 and advanced 0 -> 3.
The two runs intentionally have different block hashes and are labelled
separately in the raw evidence.

Canonical preserved run:

| Height | Block hash | Nonce | Hashes accounted | Core result |
| --- | --- | --- | --- | --- |
| 1 | `1c2d1383e42aa34e33b915a52005bd7146928c5f32a9aea13a18fdbd6226a46a` | 0 | 65536 | accepted |
| 2 | `12cb2d8344727e6d377ac008db14925a484f51593f0a3688c1aae67e8ae7a6c0` | 1 | 131072 | accepted |
| 3 | `6f0436d563ce918df0aa25cb0bba96511eca4f6ae12edba95fe57b2e75c21019` | 0 | 131072 | accepted |

The database was closed, reopened by the milestone, then independently
reopened again: three accepted CPU sessions, zero events, integrity_check
`ok`. Database and state were both 0600 before transfer into Git. Git does
not preserve owner-only permission bits on checkout; applications enforce
those modes at runtime and state directories must be private.

The observer called original functions unchanged while recording their
results: three calls to the project's builder, three successful independent
CPU header validations, and three full serialized blocks passed to
submitblock with null (accepted) replies. Each submitted header's SHA256d
hash matched the CPU validator. CPU batches actually executed. No RPC
method beginning with `generate` occurred in either observed mining run.
Full serialized blocks are in `observed-run.json`; the portable observer source is
included for repeatability. Early milestone integration tests legitimately
use Core's generation utility as a separate fixture, never as a substitute
for this live mining requirement.

## 3. Complete test suite and static checks

| Exact command | Passed | Failed | Skipped | Warnings | Exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| `python3 -m pytest -q` | 332 | 0 | 2 | 0 | 0 |
| `python3 -O -m pytest -q` | 332 | 0 | 2 | 1 | 0 |

Both runs additionally report 223 passed subtests. These are not added to
the 334 top-level tests to inflate the count. No test errors occurred.

The one optimized warning is pytest's PytestConfigWarning: assertions not
in test modules/plugins are ignored by the underlying optimized Python
interpreter. It is retained in the exact output, not described as zero warnings.
The repository's unittest assertion methods still execute. This warning is
not a failure or evidence that interpreter assertions survived optimization.

Skipped, never counted as passed:

- `test_gpu_compute.py::TestCompute::test_real_cuda_or_honest_skip`:
  real CUDA unavailable; no simulated success.
- `test_gpu_regtest.py::TestComputeCore::test_core_header_real_cuda_or_skip`:
  CUDA execution blocked; Core CPU validation runs separately.

`python3 -m pyflakes .`: no stdout/stderr, exit 0.
`python3 -m compileall -q .`: no stdout/stderr, exit 0.
The results document and raw logs preserve exact outputs and exit codes.
Static/security checks were also rerun after adding the evidence scripts;
those packaged-tree checks have the same exit codes and finding counts.
The observer was made portable by deriving its repository/output paths
from its own file, rather than a fixed temporary checkout path.

## 4. Security analysis - every finding reviewed

Requested command actually executed:

```text
python3 -m bandit -r . -x ./tests,./.git
```

Exit 1: 8 Low, 0 Medium, 0 High. This is not a clean scanner result.
Two existing narrowly scoped nosec annotations were not added or widened.
To audit them independently, also ran:

```text
python3 -m bandit -r . -x ./tests,./.git --ignore-nosec -f json -o /downloads/final-verification/evidence/bandit-unsuppressed.json
```

Exit 1: 8 Low, 2 Medium, 0 High. The following accounts for all ten findings:

| Finding | Location | Review and disposition |
| --- | --- | --- |
| B404 Low | gpu/cuda/build.py:7 | subprocess import only; needed to invoke compiler. Retained as scanner caution. |
| B603 Low | gpu/cuda/build.py:22 | Argument list, shell=False default, fixed source/output options, bounded timeout. Requires trusted nvcc/PATH. No shell-injection path identified. |
| B404 Low | gpu/cuda/install_userspace.py:7 | subprocess import only; explicit toolkit install workflow. Retained. |
| B603 Low | gpu/cuda/install_userspace.py:25 | sys.executable plus fixed package names/versions, target is a separate argument, no shell. Package-index/toolchain trust remains; version pinning is not cryptographic package provenance. |
| B404 Low | gpu/diagnostics/report.py:6 | subprocess import only for compiler version check. Retained. |
| B603 Low | gpu/diagnostics/report.py:63 | Resolved compiler and fixed --version argument, no shell, timeout. Requires trusted compiler/PATH. |
| B404 Low | node/node_manager.py:18 | subprocess import required to start Core. Retained. |
| B603 Low | node/node_manager.py:106 | Argument list, no shell, dedicated datadir, default -regtest/-listen=0, startup timeout, post-start chain check. Configured binary/extra_args are trusted operator inputs, not a remote command interface. |
| B608 Medium, existing annotation | mining/engine/stats.py:152 | False SQL-injection positive: only fixed module COLUMNS names form SQL; values are bound parameters and unknown fields are refused. No input becomes SQL syntax. |
| B310 Medium, existing annotation | node/rpc_client.py:156 | Generic urlopen warning. Constructor restricts initial URL to http/https; default plain HTTP requires loopback; application uses a trusted local Core endpoint. False positive for this supported use, not a claim that arbitrary hostile/redirecting remote endpoints are safe. |

Bandit also emits comment-parser warnings about prose following existing
nosec annotations and repeated notices that B608 did not fail on a given
AST node. Exact warnings remain in the log. No annotation was changed just
to reduce counts. The genuine source-review defects above were corrected
although Bandit did not detect them.

## 5. CUDA operational status and CPU fallback

Independently installed the pinned user-space CUDA 13.0 toolkit and built
the project's CUDA source successfully: build exit 0. This proves source
compilation only, not GPU operation.

Operational results after installation:

```text
driver_library: not loadable
runtime_version_query_status: 0
runtime_version: 13000
cudaGetDeviceCount_status: 35
actual_CUDA_execution: unavailable: CUDA unavailable: driver/runtime/device access required
```

The installed CUDA header identifies code 35 as cudaErrorInsufficientDriver.
Installing a compiler/runtime cannot supply the missing system driver or
grant device access. No fabricated kernel success or GPU benchmark was used.
For requests `auto`, `cuda` and `cpu`, actual backend was CPU and four actual
SHA256d results each matched independent hashlib calculations. Auto/cuda
reported a fallback reason. The live mining runs also used CPU.

## 6. Final source, diff and secret review

Reviewed baseline correction diff `378f737..7187bfd` and the new narrow
diff from `7187bfd` to the verified source commit. New production changes
are confined to chain-database path/permission handling and a stricter
Regtest template guard. Existing block/header/PoW/target/transaction/Merkle
validation was not weakened. Core itself independently accepted the newly
constructed complete blocks.

No credentials or secrets were found in the added diff or tracked-file
credential-signature scan. Credential-related source matches were auth
plumbing/environment names or deliberate dummy test values, not user
credentials. Preserved DB schemas/rows were inspected: only mining sessions,
decisions and events. No node cookies, wallet files, live auth headers,
private keys, tokens or raw diagnostic dumps were copied. The observer
records only RPC method names and public block payloads/results.

The intended changes are the two source corrections, eight regression
methods, security-boundary documentation, current README counts, this
report and the labelled evidence. No Task 007 or unrelated features were
started. Working source stayed untouched until real defects were reproduced.

## 7. What remains

Actual CUDA execution and its two skipped tests require functioning CUDA
driver/device access. Until then the strongest supported verdict is
CONDITIONAL PASS. An attacker-writable state directory is outside the
supported trust boundary. Regtest coins have no real monetary value;
short low-difficulty CPU hashrate samples prove neither GPU performance
nor economically viable mainnet mining.
