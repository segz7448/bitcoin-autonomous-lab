# Proof-of-Work engine (TASK 003)

`mining/pow/` is an independent implementation of Bitcoin's block-header
hashing and Proof-of-Work check. It uses only the Python standard library
and does not import the agent, dashboard or intelligence layers. Only
`core_verify.py` talks to Bitcoin Core (through the lab's RPC client), and
its mining helper reuses the existing coinbase/block assembly in `mining/`.
Nothing in TASK 001/002 was changed.

## Modules

| File | Purpose |
| --- | --- |
| `sha256.py` | SHA-256 from FIPS 180-4: one-shot, streaming (`SHA256` object with `update/copy/digest`), bytes and hex output, correct padding/length encoding. |
| `double_sha256.py` | `SHA256(SHA256(x))` on the reference implementation, plus a hashlib fast path. Tests require both to agree. |
| `block_header.py` | Immutable `BlockHeader`: strict 80-byte `serialize` / `deserialize`, field range checks, display-vs-internal hash byte order, `from_rpc` for `getblockheader` replies. |
| `target.py` | Compact nBits decode/encode that mirrors Core's `SetCompact`/`GetCompact`, with explicit negative / zero / overflow detection, pow limits, and `check_proof_of_work` (mirror of Core's `CheckProofOfWork`). |
| `difficulty.py` | Core's `GetDifficulty` formula, block work, expected hashes. |
| `nonce_search.py` | Bounded, interruptible nonce engine with exact accounting, exhaustion reporting, resume point, SIGINT/SIGTERM shutdown helper, and `search_variants` for varying headers (extra nonce). |
| `validator.py` | Independent header PoW validation with a reason code (`ok`, `high-hash`, `negative-target`, `overflow-target`, `zero-target`, `target-above-limit`). |
| `core_verify.py` | Live comparison with Bitcoin Core: per-block verification, engine-mined block submission, tamper-and-compare rejection. |
| `benchmark.py` | Repeatable CPU benchmarks (separate from correctness tests). |

## Byte order, the one place it matters

* A hash is the raw 32-byte double-SHA-256 digest ("internal order"). Headers
  embed previous-hash and merkle root in this order.
* The displayed block hash (RPC, explorers) is that digest **reversed**.
* Proof-of-Work interprets the raw digest as a **little-endian** 256-bit
  integer and requires `integer <= target`. `target.hash_to_int` is the only
  place that conversion happens. The tests include a digest whose raw hex
  starts with `00000000` but is a huge integer (fails), and one that ends
  in zero bytes (displays with leading zeros and passes).
* All header integers are little-endian; `version` is signed int32.

## Consensus rules mirrored

Negative compact (sign bit set with non-zero mantissa), zero target,
overflow beyond 256 bits and targets above the network pow limit all fail.
Equality (`hash == target`) passes. Regtest pow limit is `0x7fffff...`,
mainnet `0x00000000ffff0000...`. `NonceSearcher.search_bits` refuses to
search an invalid target instead of silently searching a bogus one.

## Nonce engine

* Range `[start_nonce, end_nonce)`, `end_nonce <= 2^32`. It never wraps.
  Exhaustion returns `EXHAUSTED` with `hashes_attempted == range size`.
* The first 64 header bytes are hashed once (a hashlib midstate copy), so
  each attempt costs one SHA-256 compression of the second block plus the
  outer hash. Tests assert the result equals plain double-SHA-256 hashing.
* Status: `FOUND`, `EXHAUSTED`, `INTERRUPTED` (stop event / signal), `LIMIT`
  (max seconds or hashes). `next_nonce` is the resume point.
* `search_variants([(label, header80), ...])` runs each variant's range in
  turn with cumulative counters. A future miner can derive each header from a
  new coinbase extra nonce and merkle root.

## Core integration (regtest)

`verify_chain` walks every block on a real regtest node and checks, per
block: our serialization equals Core's raw header hex (`getblockheader <h> false`),
that hex is the prefix of `getblock <h> 0`, our hash equals `getblockhash` and
the node's `hash`, `bits`, `target` and `difficulty` equal Core's, `prev`
links match, `chainwork` increments by our `block_work`, and PoW validates.
`mine_block_with_engine` uses `getblocktemplate`, this engine's nonce search,
and `submitblock`; Core must accept it and report our hash at that height.
`tamper_to_invalid_pow` changes a nonce until our validator says `high-hash`
and then asks Core with `submitblock`; Core returns the same `high-hash`.

## Running

```
python3 -m unittest discover -s tests -t .           # everything (live tests need bitcoind)
BAL_BITCOIND=/path/to/bitcoind python3 scripts/milestone_003.py
python3 -m mining.pow.benchmark [--fast-hashes N --pure-hashes N --repeats N --json]
```

Correctness tests are `tests/test_pow_*.py`; benchmark module checks
(`test_pow_benchmark.py`) assert counting accuracy only, never speed.

## Known limitations

* Regtest difficulty is minimal (about 2 hashes per block), so the live Core
  comparison does not exercise hard targets. Hard-target behaviour is
  covered by six real mainnet headers (heights 0, 1, 170, 125552, 300000,
  500000) re-hashed and PoW-validated by this engine, plus boundary tests
  of the target comparison.
* Python speed: about 1.6 million nonces/s per core with the midstate
  engine (hashlib), about 3,000 double hashes/s for the pure-Python
  reference. This is a correctness and research engine, not competitive
  mining hardware. No GPU code, no mainnet mining.
* The engine is single-threaded. Parallel search over disjoint nonce ranges
  or extra nonces is straightforward but not part of this task.
* The full 2^32 exhaustion is tested at the boundary (last 1000 nonces,
  including 0xFFFFFFFF) rather than by hashing all 4.29 billion values.
* Block fixtures for mainnet are public headers fetched from
  blockstream.info; Core cannot be asked about them from a regtest node.
