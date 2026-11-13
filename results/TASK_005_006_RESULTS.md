# TASK 005/006 live demonstration evidence

> **Historical record: captured 2026-11-13 in the original execution environment (disposable Linux x86_64 sandbox, Python 3.10, Bitcoin Core 32.1 regtest).** Counts and hashes below describe those runs. The pre-TASK 007 reproduction is in results/CORRECTION_PRE_007_RESULTS.md.

## Final build (backend-dispatched search), captured 2026-11-13T15:30:31Z

Command: BAL_BITCOIND=<verified Core 32.1> python3 scripts/milestone_005_006.py --cycles 3
Same disposable regtest node flow as below; in this build every nonce batch
is dispatched through gpu.engine.ComputeEngine (backend recorded per cycle,
CUDA fault -> CPU fallback wired), the agent manages batch sizes live, and
block-time updates respect mintime and the network-adjusted future limit.

```
node ready: chain=regtest height=0

== pre-mining diagnostics ==
  backend: cpu
  backend_fallback_reason: CUDA unavailable or self-test failed
  backend_benchmark_hs: 330835.1
  engine_ready: True

== starting autonomous agent for 3 cycles ==
  cycle 1: accepted height=1 hash=37d7ad1e05012c3e558f352fb587b779c61af526991f4de2e479682b1991db69 nonce=4 hashes=65536 (496773.1 H/s)
  cycle 2: accepted height=2 hash=117fdbf77695c44e06382ede366ad9c470a5e2ef04f20a0ddb2fd32ccce1cee9 nonce=2 hashes=131072 (491784.0 H/s)
  cycle 3: accepted height=3 hash=60a155a626a7f0fcb3c151a5662d84d9c0d154756527cb155cdf2f7eaaa9418b nonce=0 hashes=131072 (398859.2 H/s)

== persistent mining statistics ==
  cycles: 3  accepted: 3
  total hashes: 327680  avg hashrate: 431901.2 H/s
  session b309f0e9: height 3 accepted=1 backend=cpu hashes=131072 peak=420179.0 H/s
  session bcb5d465: height 2 accepted=1 backend=cpu hashes=131072 peak=521599.8 H/s
  session 7fb9e975: height 1 accepted=1 backend=cpu hashes=65536 peak=529620.2 H/s

== agent decisions ==
  [backend-selected] backend=cpu (requested auto); fallback_reason=CUDA unavailable or self-test failed; measured 330835 H/s
  [batch-size-adjusted] batch_size 65536 -> 131072 from measured batch time 0.140s
  [cycle-accepted] height=1 hash=37d7ad1e05012c3e558f352fb587b779c61af526991f4de2e479682b1991db69 nonce=4 hashes=65536 in 0.140s
  [cycle-accepted] height=2 hash=117fdbf77695c44e06382ede366ad9c470a5e2ef04f20a0ddb2fd32ccce1cee9 nonce=2 hashes=131072 in 0.278s
  [cycle-accepted] height=3 hash=60a155a626a7f0fcb3c151a5662d84d9c0d154756527cb155cdf2f7eaaa9418b nonce=0 hashes=131072 in 0.341s

== errors / recovery events: 0 ==

RESULT: PASS - 3/3 autonomous cycles accepted by Bitcoin Core
```

A further identical live run captured on screen (15:31Z, screenshot
evidence) shows the same 3/3 outcome with block hashes 12e90b98e3f2870ef...,
22f9ed408614b96d..., 1e20c27d2740c4da....

## Earlier build (direct CPU searcher), captured 2026-11-13T15:21:16Z

Command: BAL_BITCOIND=<verified Core 32.1> python3 scripts/milestone_005_006.py --cycles 3
Captured: 2026-11-13T15:21:16Z on a disposable regtest node

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
  backend_benchmark_hs: 332154.1
  engine_ready: True

== starting autonomous agent for 3 cycles ==
  start: {'ok': True, 'state': 'running', 'backend': 'cpu'}
  cycle 1: accepted height=1 hash=2311193bf09ce990f9c82310d069779901853274baeadfbc3e6f8c1ffb996cfb nonce=2 hashes=3 (3385.2 H/s)
  cycle 2: accepted height=2 hash=7d44685f512651429914d7eef86131e4c0c89f4d159cd009611afb559a8968e4 nonce=0 hashes=1 (1264.3 H/s)
  cycle 3: accepted height=3 hash=6c812ebf34036408d76e0cc0a592402d6fb2e35f011932ca4af83295badde0b4 nonce=0 hashes=1 (1282.4 H/s)

== blockchain status after autonomous mining ==
  blocks: 3
  best block: 6c812ebf34036408d76e0cc0a592402d6fb2e35f011932ca4af83295badde0b4

== persistent mining statistics ==
  cycles: 3  accepted: 3
  total hashes: 5  avg hashrate: 346.1 H/s
  total coinbase value: 15000000000 sats (regtest, worthless)
  session e53edf79: height 3 accepted=1 backend=cpu hashes=1 peak=101214.6 H/s
  session 5f130271: height 2 accepted=1 backend=cpu hashes=1 peak=90009.0 H/s
  session a1465615: height 1 accepted=1 backend=cpu hashes=3 peak=197850.0 H/s

== agent decisions ==
  [backend-selected] backend=cpu (requested auto); fallback_reason=CUDA unavailable or self-test failed; measured 332154 H/s
  [mining-started] limits: max_cycles=3, max_seconds_per_cycle=60
  [cycle-accepted] height=1 hash=2311193bf09ce990f9c82310d069779901853274baeadfbc3e6f8c1ffb996cfb nonce=2 hashes=3 in 0.006s
  [cycle-accepted] height=2 hash=7d44685f512651429914d7eef86131e4c0c89f4d159cd009611afb559a8968e4 nonce=0 hashes=1 in 0.005s
  [cycle-accepted] height=3 hash=6c812ebf34036408d76e0cc0a592402d6fb2e35f011932ca4af83295badde0b4 nonce=0 hashes=1 in 0.004s

== errors / recovery events: 0 ==

== persistence check (reopened database) ==
  cycles visible after restart: 3

RESULT: PASS - 3/3 autonomous cycles accepted by Bitcoin Core
```
