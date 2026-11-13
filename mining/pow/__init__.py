"""Independent Bitcoin Proof-of-Work engine (TASK 003).

Pure standard-library, no dependency on the orchestration/agent layers and
no dependency on the other lab modules except `core_verify` (which talks to
Bitcoin Core over the lab's RPC client).

Modules:
  sha256            SHA-256 from FIPS 180-4 (+ streaming object, midstate-free)
  double_sha256     SHA256(SHA256(x)), plus the fast hashlib path
  block_header      strict 80-byte header serialize / deserialize / hash
  target            compact nBits decode/encode with Core's consensus checks
  difficulty        difficulty, work and expected-hash arithmetic
  nonce_search      interruptible, bounded, exhaustion-aware nonce engine
  validator         independent Proof-of-Work validation
  core_verify       comparison against Bitcoin Core (regtest RPC)
  benchmark         repeatable throughput benchmarks
"""
