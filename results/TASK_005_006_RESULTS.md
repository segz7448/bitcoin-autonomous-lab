# TASK 005/006 live demonstration evidence

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
