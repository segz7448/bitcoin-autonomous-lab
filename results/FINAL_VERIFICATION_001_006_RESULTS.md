# Tasks 001-006 - full independent verification evidence

Date: 2026-11-13. Verdict: CONDITIONAL PASS.
Baseline: 7187bfdfbebd7775bd9908fd2138beb892c12c83.
Verified production source: dc89bd44918a0f8cd4d251646b5769033abb0774.
The final evidence commit changes documentation/evidence only.
No final-verification commits are pushed pending the user's publication decision.

Read docs/FINAL_VERIFICATION_001_006.md for all corrections, scanner reviews,
residual boundaries and the CUDA limitation. Raw files are under
results/final-verification-001-006/. Captures are original live terminal
screenshots, not generated terminal images. The canonical run's database
and state match the hashes below. The independent observer run is a separate
fresh chain with different hashes and full block hex in observed-run.json.

## Canonical final live Regtest

```text
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
  backend_benchmark_hs: 335623.3
  engine_ready: True

== starting autonomous agent for 3 cycles ==
  start: {'ok': True, 'state': 'running', 'backend': 'cpu'}
  cycle 1: accepted height=1 hash=1c2d1383e42aa34e33b915a52005bd7146928c5f32a9aea13a18fdbd6226a46a nonce=0 hashes=65536 (508291.2 H/s)
  cycle 2: accepted height=2 hash=12cb2d8344727e6d377ac008db14925a484f51593f0a3688c1aae67e8ae7a6c0 nonce=1 hashes=131072 (487422.2 H/s)
  cycle 3: accepted height=3 hash=6f0436d563ce918df0aa25cb0bba96511eca4f6ae12edba95fe57b2e75c21019 nonce=0 hashes=131072 (512300.1 H/s)

== blockchain status after autonomous mining ==
  blocks: 3
  best block: 6f0436d563ce918df0aa25cb0bba96511eca4f6ae12edba95fe57b2e75c21019

== persistent mining statistics ==
  cycles: 3  accepted: 3
  total hashes: 327680  avg hashrate: 479258.8 H/s
  total coinbase value: 15000000000 sats (regtest, worthless)
  session f1198542: height 3 accepted=1 backend=cpu hashes=131072 peak=537525.5 H/s
  session 2b4c74ce: height 2 accepted=1 backend=cpu hashes=131072 peak=511141.9 H/s
  session aed03abd: height 1 accepted=1 backend=cpu hashes=65536 peak=536814.7 H/s

== agent decisions ==
  [backend-selected] backend=cpu (requested auto); fallback_reason=CUDA unavailable or self-test failed; measured 335623 H/s
  [mining-started] limits: max_cycles=3, max_seconds_per_cycle=60
  [batch-size-adjusted] batch_size 65536 -> 131072 from measured batch time 0.137s
  [cycle-accepted] height=1 hash=1c2d1383e42aa34e33b915a52005bd7146928c5f32a9aea13a18fdbd6226a46a nonce=0 hashes=65536 in 0.137s
  [cycle-accepted] height=2 hash=12cb2d8344727e6d377ac008db14925a484f51593f0a3688c1aae67e8ae7a6c0 nonce=1 hashes=131072 in 0.280s
  [cycle-accepted] height=3 hash=6f0436d563ce918df0aa25cb0bba96511eca4f6ae12edba95fe57b2e75c21019 nonce=0 hashes=131072 in 0.267s

== errors / recovery events: 0 ==

== persistence check (reopened database) ==
  cycles visible after restart: 3

RESULT: PASS - 3/3 autonomous cycles accepted by Bitcoin Core
preserved mining.db -> /downloads/final-verification/evidence/preserved/ (mode 0o600)
preserved agent_state.json -> /downloads/final-verification/evidence/preserved/ (mode 0o600)
EXIT CODE: 0
```

## Independent observed fresh Regtest

```text
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
  backend_benchmark_hs: 326446.1
  engine_ready: True

== starting autonomous agent for 3 cycles ==
  start: {'ok': True, 'state': 'running', 'backend': 'cpu'}
  cycle 1: accepted height=1 hash=5c7f70189ceaa2b55ea31a4a3bd692e64f0723e7b4e0b515e06147eee60bc245 nonce=0 hashes=65536 (495209.6 H/s)
  cycle 2: accepted height=2 hash=24bef4ea8a755355bb119c9e1f0aee83a75e0459c29451c131126d78e381593d nonce=1 hashes=131072 (487764.4 H/s)
  cycle 3: accepted height=3 hash=422ecbd67eef576f898d4987b79d880648637c235456202376bce9280ea7cf50 nonce=0 hashes=131072 (510614.5 H/s)

== blockchain status after autonomous mining ==
  blocks: 3
  best block: 422ecbd67eef576f898d4987b79d880648637c235456202376bce9280ea7cf50

== persistent mining statistics ==
  cycles: 3  accepted: 3
  total hashes: 327680  avg hashrate: 476920.0 H/s
  total coinbase value: 15000000000 sats (regtest, worthless)
  session 523b7823: height 3 accepted=1 backend=cpu hashes=131072 peak=537834.5 H/s
  session d9e9cf35: height 2 accepted=1 backend=cpu hashes=131072 peak=514614.2 H/s
  session c05ba29d: height 1 accepted=1 backend=cpu hashes=65536 peak=526361.1 H/s

== agent decisions ==
  [backend-selected] backend=cpu (requested auto); fallback_reason=CUDA unavailable or self-test failed; measured 326446 H/s
  [mining-started] limits: max_cycles=3, max_seconds_per_cycle=60
  [batch-size-adjusted] batch_size 65536 -> 131072 from measured batch time 0.141s
  [cycle-accepted] height=1 hash=5c7f70189ceaa2b55ea31a4a3bd692e64f0723e7b4e0b515e06147eee60bc245 nonce=0 hashes=65536 in 0.141s
  [cycle-accepted] height=2 hash=24bef4ea8a755355bb119c9e1f0aee83a75e0459c29451c131126d78e381593d nonce=1 hashes=131072 in 0.279s
  [cycle-accepted] height=3 hash=422ecbd67eef576f898d4987b79d880648637c235456202376bce9280ea7cf50 nonce=0 hashes=131072 in 0.267s

== errors / recovery events: 0 ==

== persistence check (reopened database) ==
  cycles visible after restart: 3

RESULT: PASS - 3/3 autonomous cycles accepted by Bitcoin Core

INDEPENDENT OBSERVER CHECKS
milestone_exit_zero: True
own_builder_three_candidates: True
cpu_verified_three_solutions: True
three_full_block_submissions: True
matching_cpu_and_submitted_hashes: True
no_generation_rpc: True
real_cpu_hash_batches: True
RPC methods used: createwallet, getaddressinfo, getbestblockhash, getblock, getblockchaininfo, getblockcount, getblocktemplate, getnetworkinfo, getnewaddress, stop, submitblock
Full blocks and function/RPC evidence: observed-run.json
EXIT CODE: 0
```

## Normal pytest

```text
................................... [ 10%]
.................................................................................................................................... [ 50%]
........................s........s.....................................................................................................................................            [100%]
332 passed, 2 skipped, 223 subtests passed in 21.68s
EXIT CODE: 0
```

## Optimized pytest

```text
................................... [ 10%]
.................................................................................................................................... [ 50%]
........................s........s.....................................................................................................................................            [100%]
================================================================== warnings summary ==================================================================
../bal-deps/venv/lib/python3.10/site-packages/_pytest/config/__init__.py:1508
  /tmp/bal-deps/venv/lib/python3.10/site-packages/_pytest/config/__init__.py:1508: PytestConfigWarning: assertions not in test modules or plugins will be ignored because assert statements are not executed by the underlying Python interpreter (are you using python -O?)
  
    self._warn_about_missing_assertion(mode)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
332 passed, 2 skipped, 1 warning, 223 subtests passed in 22.14s
EXIT CODE: 0
```

## Pyflakes

```text
EXIT CODE: 0
```

## Compileall

```text
EXIT CODE: 0
```

## Bandit - requested command

```text
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.10.12
[manager]	WARNING	Test in comment: fixed is not a test name or id, ignoring
[manager]	WARNING	Test in comment: COLUMNS is not a test name or id, ignoring
[manager]	WARNING	Test in comment: constant is not a test name or id, ignoring
[manager]	WARNING	Test in comment: bound is not a test name or id, ignoring
[manager]	WARNING	Test in comment: values is not a test name or id, ignoring
[manager]	WARNING	Test in comment: only is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B608), but no failed test on file ./mining/engine/stats.py:152
[tester]	WARNING	nosec encountered (B608), but no failed test on file ./mining/engine/stats.py:152
[tester]	WARNING	nosec encountered (B608), but no failed test on file ./mining/engine/stats.py:152
[manager]	WARNING	Test in comment: scheme is not a test name or id, ignoring
[manager]	WARNING	Test in comment: validated is not a test name or id, ignoring
[manager]	WARNING	Test in comment: in is not a test name or id, ignoring
[manager]	WARNING	Test in comment: __init__ is not a test name or id, ignoring
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
Run started:2026-11-13 16:26:36.246032+00:00

Test results:
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./gpu/cuda/build.py:7:0
6	import shutil
7	import subprocess
8	import tempfile

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./gpu/cuda/build.py:22:25
21	            try:
22	                result = subprocess.run([nvcc, '--shared', '-Xcompiler', '-fPIC',
23	                                         '--cudart', 'shared', '--cudadevrt', 'none',
24	                                         '-L' + str(Path(nvcc).resolve().parent.parent / 'lib'),
25	                                         '-O3', str(root / 'engine.cu'), '-o', str(candidate)],
26	                                        stdout=log, stderr=log, timeout=180, check=False)
27	            except (OSError, subprocess.TimeoutExpired):

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./gpu/cuda/install_userspace.py:7:0
6	import argparse
7	import subprocess
8	import sys

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./gpu/cuda/install_userspace.py:25:21
24	        try:
25	            result = subprocess.run([sys.executable, '-m', 'pip', 'install',
26	                                     '--target', str(destination),
27	                                     *[p+'=='+VERSION for p in PACKAGES]],
28	                                    stdout=log, stderr=log, timeout=300, check=False)
29	        except (OSError, subprocess.TimeoutExpired):

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./gpu/diagnostics/report.py:6:0
5	import shutil
6	import subprocess
7	from pathlib import Path

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./gpu/diagnostics/report.py:63:18
62	        try:
63	            out = subprocess.run([compiler, '--version'], capture_output=True,
64	                                 text=True, timeout=10, check=False)
65	            version = re.search(r'release (\d+\.\d+)', out.stdout)

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./node/node_manager.py:18:0
17	import shutil
18	import subprocess
19	import time

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./node/node_manager.py:106:15
105	        logger.info("starting bitcoind: %s", " ".join(cmd))
106	        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
107	        if proc.returncode != 0:

--------------------------------------------------

Code scanned:
	Total lines of code: 5746
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 2

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 8
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 0
		High: 8
Files skipped (0):
EXIT CODE: 1
```

## Bandit - ignore existing nosec annotations

```text
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
[json]	INFO	JSON output written to file: /downloads/final-verification/evidence/bandit-unsuppressed.json
EXIT CODE: 1
```

## CUDA compilation

```text
CUDA library built; execution self-test still required
EXIT CODE: 0
```

## CUDA operational checks and CPU fallback

```text
CUDA operational checks only
driver_library: not loadable
runtime_version_query_status: 0
runtime_version: 13000
cudaGetDeviceCount_status: 35
actual_CUDA_execution: unavailable: CUDA unavailable: driver/runtime/device access required
{"requested": "auto", "actual_backend": "cpu", "fallback_reason": "CUDA unavailable or self-test failed", "four_SHA256d_digests_match_hashlib": true}
{"requested": "cuda", "actual_backend": "cpu", "fallback_reason": "CUDA unavailable or self-test failed", "four_SHA256d_digests_match_hashlib": true}
{"requested": "cpu", "actual_backend": "cpu", "fallback_reason": null, "four_SHA256d_digests_match_hashlib": true}
EXIT CODE: 0
```

## Exact CUDA skip reasons

```text
ss                                                                       [100%]
=========================== short test summary info ============================
SKIPPED [1] tests/test_gpu_compute.py:142: real CUDA unavailable; no simulated success
SKIPPED [1] tests/test_gpu_regtest.py:39: CUDA execution blocked; Core CPU validation runs separately
2 skipped in 0.45s
EXIT_CODE=0
```

## Packaged-tree Pyflakes

```text
EXIT_CODE=0
```

## Packaged-tree compileall

```text
EXIT_CODE=0
```

## Packaged-tree Bandit

```text
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.10.12
[manager]	WARNING	Test in comment: fixed is not a test name or id, ignoring
[manager]	WARNING	Test in comment: COLUMNS is not a test name or id, ignoring
[manager]	WARNING	Test in comment: constant is not a test name or id, ignoring
[manager]	WARNING	Test in comment: bound is not a test name or id, ignoring
[manager]	WARNING	Test in comment: values is not a test name or id, ignoring
[manager]	WARNING	Test in comment: only is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B608), but no failed test on file ./mining/engine/stats.py:152
[tester]	WARNING	nosec encountered (B608), but no failed test on file ./mining/engine/stats.py:152
[tester]	WARNING	nosec encountered (B608), but no failed test on file ./mining/engine/stats.py:152
[manager]	WARNING	Test in comment: scheme is not a test name or id, ignoring
[manager]	WARNING	Test in comment: validated is not a test name or id, ignoring
[manager]	WARNING	Test in comment: in is not a test name or id, ignoring
[manager]	WARNING	Test in comment: __init__ is not a test name or id, ignoring
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
Run started:2026-11-13 16:30:07.138638+00:00

Test results:
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./gpu/cuda/build.py:7:0
6	import shutil
7	import subprocess
8	import tempfile

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./gpu/cuda/build.py:22:25
21	            try:
22	                result = subprocess.run([nvcc, '--shared', '-Xcompiler', '-fPIC',
23	                                         '--cudart', 'shared', '--cudadevrt', 'none',
24	                                         '-L' + str(Path(nvcc).resolve().parent.parent / 'lib'),
25	                                         '-O3', str(root / 'engine.cu'), '-o', str(candidate)],
26	                                        stdout=log, stderr=log, timeout=180, check=False)
27	            except (OSError, subprocess.TimeoutExpired):

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./gpu/cuda/install_userspace.py:7:0
6	import argparse
7	import subprocess
8	import sys

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./gpu/cuda/install_userspace.py:25:21
24	        try:
25	            result = subprocess.run([sys.executable, '-m', 'pip', 'install',
26	                                     '--target', str(destination),
27	                                     *[p+'=='+VERSION for p in PACKAGES]],
28	                                    stdout=log, stderr=log, timeout=300, check=False)
29	        except (OSError, subprocess.TimeoutExpired):

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./gpu/diagnostics/report.py:6:0
5	import shutil
6	import subprocess
7	from pathlib import Path

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./gpu/diagnostics/report.py:63:18
62	        try:
63	            out = subprocess.run([compiler, '--version'], capture_output=True,
64	                                 text=True, timeout=10, check=False)
65	            version = re.search(r'release (\d+\.\d+)', out.stdout)

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: ./node/node_manager.py:18:0
17	import shutil
18	import subprocess
19	import time

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: ./node/node_manager.py:106:15
105	        logger.info("starting bitcoind: %s", " ".join(cmd))
106	        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
107	        if proc.returncode != 0:

--------------------------------------------------

Code scanned:
	Total lines of code: 5852
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 2

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 8
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 0
		High: 8
Files skipped (0):
EXIT_CODE=1
```

## Packaged-tree ignore-nosec Bandit

```text
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
[json]	INFO	JSON output written to file: /downloads/final-verification/evidence/packaged-bandit-unsuppressed.json
EXIT_CODE=1
```

## Independent database reread

```json
{
  "integrity_check": "ok",
  "sessions": [
    {
      "height": 1,
      "block_hash": "1c2d1383e42aa34e33b915a52005bd7146928c5f32a9aea13a18fdbd6226a46a",
      "accepted": 1,
      "backend": "cpu",
      "hashes": 65536,
      "nonce": 0,
      "submit_result": "accepted"
    },
    {
      "height": 2,
      "block_hash": "12cb2d8344727e6d377ac008db14925a484f51593f0a3688c1aae67e8ae7a6c0",
      "accepted": 1,
      "backend": "cpu",
      "hashes": 131072,
      "nonce": 1,
      "submit_result": "accepted"
    },
    {
      "height": 3,
      "block_hash": "6f0436d563ce918df0aa25cb0bba96511eca4f6ae12edba95fe57b2e75c21019",
      "accepted": 1,
      "backend": "cpu",
      "hashes": 131072,
      "nonce": 0,
      "submit_result": "accepted"
    }
  ],
  "events": 0,
  "mining_db_mode": "0o600",
  "agent_state_mode": "0o600"
}
```

## Complete unsuppressed finding data

Original and packaged-tree JSON files retain all 10 findings. The report reviews every finding, not only those visible with existing nosec annotations enabled.
