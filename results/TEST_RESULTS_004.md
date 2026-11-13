# TASK 004 test results

> **Historical record: captured 2026-11-13 in the original test environment (Python 3.10, Bitcoin Core 32.1 regtest, userspace CUDA 13.0 toolkit, no GPU driver).** Test counts below describe that run, not the current suite.

Environment: Bitcoin Core 32.1 regtest (live, no mocked RPC for the `*live*`
and `*core_integration*` tests), Python 3.10, standard library only.

| Check | Before (c12232a) | After |
|-------|------------------|-------|
| Full test suite | 166 tests OK | 213 tests OK (47 new: 42 audit regressions, 5 live hardening) |
| Same suite, three consecutive runs | - | 213 OK, 213 OK, 213 OK (no flakiness) |
| Same suite under `python -O` | not run | OK (no runtime check depends on `assert`) |
| pyflakes | 31 findings (unused imports/variables) | 0 |
| bandit | 1 Medium, 6 Low | 0 Medium; 2 Low (documented: `subprocess` argument-list launch of the configured `bitcoind`) |
| Branch coverage (library code) | 85% | 88% |
| Milestone scripts 001/002/003 against live regtest | pass | pass |

New live results (Core 32.1 regtest):

- A block with a duplicated trailing transaction (same header and merkle root as the honest block) is rejected by Core with `bad-txns-duplicate`; the engine's verifier flags it; the honest block is then accepted.
- The event-driven monitor, parked in `waitfornewblock` with a 20 s window, stored a newly generated block in well under 3 s.
- Deliberately invalid nonces are still rejected by both this engine and Core (TASK 003 tests unchanged and passing).

Evidence: `results/audit-004-new-tests-live.png` and `results/audit-004-static-and-full-suite.png` (direct captures of live terminal runs).

Reproduce: `BAL_BITCOIND=/path/to/bitcoind python3 -m unittest discover -s tests -t .`
