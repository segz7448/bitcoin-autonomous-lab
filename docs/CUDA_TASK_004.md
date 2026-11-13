# TASK 004: CUDA computation engine

> **Historical record: written 2026-11-13 in the original test environment (Python 3.10, Bitcoin Core 32.1 regtest, userspace CUDA 13.0 toolkit, no GPU driver).** Its test counts describe that run; current suite counts are in `docs/CORRECTION_PRE_007.md`.

Status: CUDA source compiled successfully; GPU execution is NOT verified.
CPU fallback and Bitcoin Core Regtest checks pass. The missing system driver
and device access are a real blocker, not a GPU benchmark result.

The previous `AUDIT_004.md` and `TEST_RESULTS_004.md` describe the earlier
security audit. They remain intact as history. This document covers the user's
CUDA TASK 004.

## Architecture and authority

- `gpu/cuda/kernels/sha256.h`: complete SHA-256 compression, arbitrary-length
  padding, SHA256d of an 80-byte header, and little-endian inclusive target check.
- `gpu/cuda/engine.cu`: one nonce per CUDA thread; 64-bit index arithmetic
  prevents wraparound. Host entry point validates launch limits, allocates,
  launches, synchronizes, copies output, and frees partial allocations on error.
- `gpu/engine.py`: `cpu`, `cuda`, and `auto` interface. CUDA selection requires
  a real multi-nonce kernel self-test with independent hashlib verification.
  Missing/failed CUDA selects CPU, with the actual backend and reason returned.
- Every returned CUDA digest AND target flag is recomputed on CPU. Candidates
  additionally pass the public verifier. CUDA is never the validity authority.
- Raw integer targets are computational thresholds. `batch_bits` validates the
  original header's compact target and caller-supplied chain PoW limit. Use it
  for consensus work. `verify_candidate(..., bits=..., pow_limit=...)` checks
  original header agreement, invalid compact encodings and chain limits too.
- Batches are half-open ranges `[start_nonce, start_nonce + count)` within
  `[0, 2**32]`. Empty ranges are allowed. Results include `next_nonce`, exact
  logical `hashes_computed`, every digest, candidates, elapsed time, and boundary
  exhaustion. Resume with `next_nonce`; never wrap to zero. A batch is bounded
  at 1,048,576 hashes. GPU workspace request is 112 + 33*count bytes, plus
  runtime/context overhead. Failed GPU work is not counted as completed logical
  results; a fallback recomputes the entire requested batch on CPU.

## Installation and use

Python standard library is enough for CPU computation. For an optional isolated
CUDA toolkit install (requires Internet and pip, no administrator access):

```sh
python -m gpu.cuda.install_userspace "$HOME/.bal-cuda"
export PATH="$HOME/.bal-cuda/nvidia/cu13/bin:$PATH"
export LD_LIBRARY_PATH="$HOME/.bal-cuda/nvidia/cu13/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python -m gpu.cuda.build
python -m gpu.diagnostics.report --output gpu/diagnostics/local-report.json
python -m gpu.benchmark.run --output results/local/cuda-benchmark.json
```

Create `results/local` before writing there. Installation pins the compiler,
CRT, NVVM, runtime and runtime compiler together at 13.0.88 to prevent an
incompatible compiler/assembler combination. It uses the vendor compiler's
supported default build configuration, without inspecting device characteristics.
No native-target detection or device-identity discovery occurs. Build diagnostics
are withheld because general compiler output can reveal restricted details.
The project never installs drivers or changes device permissions automatically.
The toolkit is not a driver and cannot create system device access.

```python
from gpu.engine import ComputeEngine, verify_candidate
from mining.pow.target import POW_LIMIT_REGTEST

engine = ComputeEngine('auto')  # 'cpu' forces CPU; 'cuda' falls back honestly
# header is exactly 80 bytes from an existing Regtest block/template
result = engine.batch_bits(header, POW_LIMIT_REGTEST,
                           start_nonce=0, count=4096, threads=128)
print(result['backend'], result['fallback_reason'], result['next_nonce'])
```

`AgentInterface` exposes `cuda_diagnostics`, `compute_sha256d`,
`compute_nonce_batch`, `verify_compute_candidate`, `benchmark_compute`, and
`compute_benchmark_results`. Benchmark retrieval uses results from that interface
instance, not a fabricated or silently stale file. Operations are computation
only: no pool, public-network submission, or autonomous mining agent.

## Approved diagnostics and actual environment result

The diagnostic module queries only approved scalar limits (runtime attribute IDs
1 through 7), availability/count, driver/runtime/compiler versions, memory totals,
initialization, allocation and kernel status. It never calls a general device
properties or identity interface. Unknown values are JSON null, not invented.
System memory comes only from the `MemAvailable` and `MemTotal` entries.

After installing the user-space components:

- CUDA compiler: 13.0 (package 13.0.88). CUDA runtime: 13000 (13.0).
- Real `.cu` source compiled into the computation library successfully.
- Driver version: unavailable; the CUDA driver library is not loadable.
- Runtime initialization: error 35 (`cudaErrorInsufficientDriver`).
- CUDA accessibility/operational status: false. Physical GPU availability and
  CUDA-accessible device count: unknown, not proof that no GPU exists.
- Launch limits and GPU memory: unavailable. GPU allocation/kernel: not run.
- Driver-install access check: no administrative privileges, system library
  directory not writable, noninteractive administrative access denied, and
  CUDA control device not present/accessibly exposed. A driver kernel component
  and device access require a system administrator or a CUDA-enabled execution
  environment. No system modifications or permission bypass were attempted.
- Exact contemporaneous approved RAM values are in
  `results/cuda-004-diagnostics.json`; available RAM changes between runs.

## Benchmark methodology and limits

Fixed 80-byte input; nonce range starts at zero; multiple batch sizes and valid
thread configurations; one untimed warmup followed by at least two timed repeats
(default three). Report every sample and median throughput. CPU/GPU end-to-end
measurements include Python overhead, allocation/transfers where applicable, CPU
verification, result construction and candidate handling. They are NOT sustained
mining performance. Device-batch timings, when available, separately include
allocation, transfers and a synchronized kernel but exclude CPU verification;
these are NOT raw kernel timings. Raw kernel throughput remains null.

The benchmark checks the supported limits rather than assuming maximum threads
are fastest. It reports the measured best CUDA configuration when real CUDA runs
succeed; callers can pass its batch size and threads to the engine. No CUDA
configuration can be selected here because execution is blocked. Results label
that absence explicitly, never time the CPU and call it a GPU result.

Actual repeated CPU results are in `results/cuda-004-benchmark.json`:
256-hash batches about 1.10 million H/s; 4096-hash batches about 1.03 million H/s.
These short batches are a smoke benchmark, not a stable speed promise. GPU rates,
GPU memory measurements and speedup comparison remain unavailable.

## Validation and known limitations

See `results/CUDA_TEST_RESULTS_004.md` for exact test commands/results. Tests cover
padding boundaries, 100 reproducible randomized 80-byte headers, known Bitcoin
headers, little-endian target equality, invalid targets, nonce generation/range
exhaustion at the boundary, limits, allocation/launch errors, corrupt GPU outputs,
backend selection/fallback, repeated benchmarks and real Core Regtest headers.
Fault doubles exercise errors only, never claim a working GPU. The compression
header is additionally compiled and run on CPU, explicitly not CUDA evidence.

GPU SHA256d agreement and live Regtest CUDA execution tests are genuinely skipped
until a usable driver/device is present. GPU tuning, GPU speed, successful GPU
allocation and candidate discovery on GPU are therefore UNVERIFIED. Source
compilation does not prove kernel runtime correctness. Actual hardware execution
and CPU verification remain the acceptance gate for those claims.

Other limits: no persistent GPU allocation or asynchronous batching; all returned
hashes are copied and verified on CPU, intentionally limiting potential speedup;
no SHA-256 midstate optimization; GPU binaries are generated locally and ignored
by git; selection is per engine, not a global device setting. Batch calls are
synchronous and not interruptible mid-kernel. No autonomous loop is provided.

## API references

- NVIDIA device attributes (only approved individual scalars are used):
  https://docs.nvidia.com/cuda/archive/11.6.2/cuda-runtime-api/group__CUDART__DEVICE.html
- Memory accounting:
  https://docs.nvidia.com/cuda/cuda-runtime-api/cuda_runtime_api/group__CUDART__MEMORY.html
- Runtime/driver version encoding:
  https://docs.nvidia.com/cuda/archive/13.2.2/cuda-runtime-api/group__CUDART____VERSION.html
- Compiler configuration:
  https://docs.nvidia.com/cuda/cuda-compiler-driver-nvcc/index.html
