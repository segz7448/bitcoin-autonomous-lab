# TASK 004 - Audit, hardening and retest

Scope: the code as of `c12232a` (TASKS 001-003). Method: static analysis
(pyflakes, bandit, vulture), branch coverage, manual review of every consensus
and I/O path, adversarial tests, and live runs against Bitcoin Core 32.1
regtest. Consensus rules were not weakened anywhere; several checks got
stricter. A block with an invalid nonce is still rejected, by this engine and
by Core.

## Defects found and fixed

| # | Where | Defect | Fix | Pinned by |
|---|-------|--------|-----|-----------|
| 1 | `blockchain/primitives.py` | Legacy target code used `hash < target`; Core accepts `hash <= target`. It also skipped the overflow / zero / negative-mantissa checks of `SetCompact`, so invalid nBits decoded to a huge or zero target. | One decoder only: legacy helpers delegate to `mining/pow/target.py`. | `TestConsensusTargetUnification` |
| 2 | `blockchain/analysis.py` | Merkle verification accepted a malleated block (CVE-2012-2459: duplicating the last tx of an odd level reproduces the root). | `merkle_root_checked` returns Core's `mutated` flag; `verify_merkle_root` rejects mutated trees. | `TestMerkleMutation`; live: Core rejects the duplicated block (`bad-txns-duplicate`) and accepts the honest block with the same header |
| 3 | `blockchain/analysis.py` | Coinbase limit check used floats with a 1e-8 tolerance, i.e. one satoshi of over-claim passed. | Exact integer-satoshi comparison. | `TestCoinbaseLimitIsExactToTheSatoshi` |
| 4 | `blockchain/service.py` | Only `getblockcount` was protected: an RPC failure while walking new blocks raised out of `run()` and killed the monitor. The walk also did not check parent links, so a chain change mid-walk could store blocks from two branches as one chain. | Whole cycle guarded, parent link verified per block, progress persisted, `run()` survives unexpected exceptions. | `TestServiceRobustness` |
| 5 | `blockchain/storage.py` | A `ChainStore` could not be used from the monitor thread (sqlite3 thread affinity) - found by the new live event-driven test. Default journal mode, no busy timeout, world-readable file. | Lock-serialized connection, WAL, busy timeout, file created `0600`. | `TestStoreThreadSafety`, `TestStoreDurability` |
| 6 | `node/rpc_client.py` | Credentials sent in cleartext to any host; any URL scheme accepted; malformed, truncated, oversized or id-mismatched replies surfaced as random `ValueError`/`KeyError`; `urllib.error` was only imported by accident. The request counter was shared and unlocked, so a long-poll thread and a second caller on one client could mis-pair replies (found live, fixed with a per-call id under a lock). | Loopback-only unless `allow_remote`/`BAL_RPC_ALLOW_REMOTE=1`; http(s) only; reply size cap; typed `RPCConnectionError` (a `URLError`, so existing backoff handles it). | `TestRPCClientHardening` (incl. a 6-thread reply-pairing test) |
| 7 | `mining/pow/target.py`, `blockchain/primitives.py` | Hash strings parsed with `int(x, 16)` / `bytes.fromhex`, which accept `0x`, signs, whitespace and underscores. | Exactly 64 hex digits, nothing else. | `TestHexStrictness` |
| 8 | `mining/miner.py` | Second, weaker nonce loop (`<`, no range checks, `max_seconds=0` meant "no limit", deadline checked every 1M hashes). | Reduced to a thin wrapper over `NonceSearcher`. | `TestLegacyMinerUsesConsensusSearch` |
| 9 | `mining/pow/nonce_search.py` | `search_variants` reported fake exhaustion for an empty list and ignored custom ranges; negative limits accepted; consensus self-check raised `AssertionError`. | `ValueError` for empty input / negative limits, real ranges reported, `PoWInternalError`. | `TestNonceSearchEdges` |
| 10 | five library modules | `assert` used for runtime checks (removed under `python -O`). | Explicit exceptions; a test forbids `assert` in library code and the suite passes under `-O`. | `TestNoBareAssertsInLibraryCode` |
| 11 | `agent/interface.py` | Database handle opened before the node was reachable (leaked on failure); unbounded `nblocks`/`n`; unvalidated hashes. | Node first, then store; bounds 1..1000; strict 64-hex. | `TestAgentInterfaceHardening` |

## Dead and duplicate code removed

- `blockchain/sha256.py`: a second full SHA-256; now a re-export of `mining/pow/sha256.py`.
- `mining/benchmark.py` (legacy, 0% covered, superseded by `mining/pow/benchmark.py`).
- Unused: `NodeUnavailable`, `ChainMonitor.wait_for_height`, `core_verdict_on_header_pow`, six re-exports in `mining/block.py`, all unused imports/variables (pyflakes now clean).

## Added

- `RPC.wait_for_new_block` and `MonitoringService.run_event_driven`: event-driven
  monitoring over Core's `waitfornewblock` long-poll. An idle chain costs one
  blocked request per wait window instead of a poll every interval; each
  wake-up still runs the full reorg/parent-link sync. Verified live.
- Tests: `tests/test_audit_hardening.py`, `tests/test_live_hardening.py`.

## Remaining, by design

- `node_manager` launches `bitcoind` via `subprocess` with an argument list
  (no shell); bandit reports it at Low severity. The binary path is
  operator-configured, not network input.
- `ChainStore.record_block` and `set_sync` are separate commits; a crash
  between them is repaired on the next cycle (INSERT OR REPLACE, resume from
  stored tip) rather than by one transaction.
- Event-driven monitoring uses RPC long-poll, not ZMQ (needs a non-stdlib
  dependency). Stopping a parked long-poll takes up to one wait window.
- Regtest only. Throughput numbers are CPU-only and measured on one machine.
