# TASK 003 results - SHA-256 Proof-of-Work engine

All numbers come from real executions: Bitcoin Core 32.1 (regtest), Python 3.10.12,
x86_64, 2 CPUs. Terminal captures: `milestone-003-pow-live.png`,
`tests-suite-003.png`. Raw milestone output: `milestone-003-output.txt`.

## Automated tests

`python3 -m unittest discover -s tests -t .` -> Ran 166 tests, OK (106 from
TASK 001/002 plus 60 new `test_pow_*` tests, including 5 live Core tests).

## SHA-256 results

* FIPS 180-4 / NIST vectors: "", "abc", the 448-bit and 896-bit messages,
  and 1,000,000 x "a" all match.
* 200+ lengths around the 55/56/63/64/119/120 byte padding edges and 300
  random inputs match hashlib; streaming equals one-shot.
* SHA256d("") = 5df6e0e2...9456, SHA256d("hello") = 9595c9df...3d50 match.

## Actual block-header verification

* Real mainnet headers, heights 0, 1, 170, 125552, 300000, 500000:
  deserialize -> serialize is byte-exact, own double SHA-256 equals the
  known block hash, PoW valid.
* Live Core regtest chain (genesis + 6 blocks, then +1 engine-mined):
  for every block, serialization equals Core's raw header hex, hash equals
  `getblockhash`/`getblockheader`, `bits`, `target`, `difficulty` equal Core's,
  prev-hash links hold, `chainwork` steps equal our computed block work,
  PoW validates. All checks pass for every block.

## Proof-of-Work validation results

* Engine-mined regtest block (getblocktemplate -> own nonce search ->
  submitblock): accepted by Core, Core's hash at that height equals ours.
* Tampered nonce: engine says `high-hash`, Core's `submitblock` says
  `high-hash`; tip unchanged.
* Header target above regtest pow limit: engine says `target-above-limit`;
  Core rejects it as well.
* Every real mainnet header with one flipped bit (prev, merkle, time, nonce)
  fails as `high-hash`. Negative, zero and overflow nBits are rejected
  (Core's arith_uint256 vectors reproduced). Equality with target passes,
  target+1 fails.
* Search at nBits 0x1f00ffff (target ~2^240): found nonce 103414 after 103,415
  hashes; the preceding nonce fails validation.

## Benchmarks (benchmark.py, 3 repeats, median)

| Workload | Hashes/s | Total hashes |
| --- | --- | --- |
| SHA-256, 80 B, hashlib | ~3.3 million | 600,000 |
| double SHA-256, 80 B, hashlib | ~1.75 million | 600,000 |
| nonce search engine (midstate) | ~1.61 million | 600,000 |
| SHA-256, 80 B, pure Python reference | ~4,600 | 6,000 |
| double SHA-256, 80 B, pure Python reference | ~3,100 | 6,000 |

CPU utilisation 1.0 (single thread, CPU-bound). Peak RSS about 23 MiB.
Rates depend on the host and vary a few percent between runs; hash counts are exact.
