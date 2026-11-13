# TASK 004 CUDA validation

CUDA toolchain installed in user space at $0. Actual CUDA source compilation
succeeded. Runtime initialization returns 35; no loadable system CUDA driver
and no exposed CUDA control device. No GPU computation or GPU benchmark passed.

Final gate:

- `python -m unittest discover`: 243 tests run, 241 passed, 2 skipped.
- `python -O -m unittest discover`: same result.
- Two skips are real-CUDA tests: header/nonce GPU agreement and live Regtest GPU
  agreement. They are not counted as passed CUDA tests.
- Existing Core Regtest tests and new CPU/auto-backend Core header tests run
  against an actual local Bitcoin Core node, with no public peers.
- `python -m pyflakes .`: clean.
- `python -m bandit -r gpu`: 0 High, 0 Medium, 6 Low scanner findings.
  These are imports/calls to subprocess for the explicitly requested toolchain
  install/build and compiler-version check. Arguments are lists with no shell;
  install uses pinned package names and build compiles this repository's source.
  They are documented residual notes, not a claim of zero vulnerabilities.
- Shared CUDA SHA-256 logic also compiled with the CPU C++ compiler using
  `-Wall -Wextra -Werror`; 16 padding lengths and 100 seeded random headers match
  independent hashlib results. This is CPU algorithm evidence, NOT GPU evidence.

The audit caught and fixed an initially unpinned compiler dependency mismatch,
missing runtime linker alias, candidate nonce-boundary validation, original-header
nBits agreement, unused imports and privacy-safe compiler failure reporting before
push. Full tests were repeated after the fixes.

`cuda-004-diagnostics.json` and `cuda-004-benchmark.json` contain actual operational
measurements. CPU throughput medians are roughly 1.10M H/s (256) and 1.03M H/s
(4096). GPU timings/configuration/limits remain null or explicitly unavailable.
Available RAM is a point-in-time measurement, not a capacity guarantee.

Screenshots capture commands executing live in a terminal, not drawn text or
transcript playback. `cuda-004-diagnostics-live.png` shows build/diagnostics and
`cuda-004-tests-live.png` shows targeted tests and full-suite/optimized summaries.
