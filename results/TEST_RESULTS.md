# TASK 001 - Verified results

All results below come from real executions on 2026-11-13 against Bitcoin
Core 32.1 (release tarball SHA-256 verified against the published
SHA256SUMS before use). The screenshots in this directory are genuine
captures of live terminal sessions: the `+` lines are the exact commands as
executed (bash `set -x`), followed by each command's own unabridged output.
Nothing was retyped, replayed, or edited.

## 1. Automated test suite (tests-suite.png)

Command: `python3 -m unittest discover -s tests -t . -v`

Result: **56 tests, OK, 0 failures, 0 errors, 0 skips.** This includes the
live regtest integration test (`test_milestone_flow`), which starts a real
bitcoind, runs the full milestone flow, and shuts it down.

Suite coverage:

- `test_sha256.py` - pure-Python SHA-256 vs FIPS 180-4 vectors and vs
  hashlib across all padding branches (130 lengths).
- `test_primitives.py` - real-mainnet block reconstruction (genesis block
  and block 125552): recomputed hashes match the known block hashes and
  meet their targets; compact-target round-trips.
- `test_adversarial.py` - target encoding edges, nonce bounds, BIP34
  boundary encodings, malformed inputs, witness commitment layout,
  fail-closed template anomalies, RPC failure mapping, regtest-only guard.
- `test_mining.py` - mine and independently verify a low-difficulty block;
  exhaustion path at an impossible target.
- `test_rpc_client.py` - cookie and user/password auth headers, env config,
  validation, no-hardcoded-credential guarantee, error mapping.
- `test_node_manager.py` - config, regtest-only enforcement, startup
  failure paths.
- `test_monitor.py` - snapshots, independent block verification (including
  tamper detection), generate-and-verify logic.
- `test_regtest_integration.py` - the milestone below, as a test.

## 2. Live milestone run (milestone-regtest-live.png)

Command: `python3 scripts/milestone_001.py` (fresh temporary datadir each
run; block hashes and payout address differ per run, as expected).

Every milestone requirement executed and passed:

1. Local Bitcoin Core node started in regtest mode.
2. JSON-RPC connection established (Bitcoin Core Satoshi:32.1.0).
3. `getblockchaininfo` returned `chain=regtest`, height 0, regtest genesis
   best block `0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206`.
4. `getblockcount` returned 0 before generation, 3 after.
5. `generatetoaddress` produced 3 blocks to a regtest wallet address.
6. `getblock` returned the new tip (height 3, 1 confirmation, 1 tx).
7. For each generated block: the node maps its height to the same hash
   (`getblockhash`), and the lab independently reconstructs the 80-byte
   header from the reply fields, recomputes the block hash, re-checks the
   proof-of-work target, and verifies previous-block linkage - all PASS.

Final line of the run: `MILESTONE RESULT: ALL CHECKS PASSED`, followed by a
clean node shutdown.

## Scope notes

- All of the above is on Bitcoin Core's private regtest network. It
  demonstrates a working, tested node integration. It is not a mainnet
  result and not an earnings result.
- The regtest wallet used for `generatetoaddress` is throwaway and holds
  valueless test coins; it is deleted with the temporary datadir.
