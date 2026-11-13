# gpu/

GPU acceleration research and CUDA integration.

**Status: intentionally not implemented.** TASK 001's restrictions require
the Bitcoin Core integration to be established and tested before any GPU
mining work begins. This directory holds the place for that later work.

Planned research order (later tasks):
1. SHA-256 throughput model and roofline estimate versus the CPU path.
2. CUDA (or OpenCL) kernel for the 80-byte header hashing loop.
3. Correctness harness: kernel output checked byte-for-byte against
   `blockchain.sha256` and `hashlib` before any benchmarking.
4. Integration behind the same `mining.miner.scan_nonces` interface so the
   orchestration layer can swap hashing backends.
