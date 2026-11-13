# gpu/

GPU acceleration research and CUDA integration.

**Status: CUDA source implemented and compiled; GPU execution unverified.**

What exists today:

- `gpu/engine.py` - `ComputeEngine`, the project's CPU/CUDA backend
  abstraction. Every mining nonce batch is dispatched through it: CUDA is
  used only when its self-test and a real measured batch succeed, and any
  CUDA execution fault falls back to the CPU with the reason recorded.
  Independent CPU verification re-checks every reported nonce.
- `gpu/cuda/engine.cu` + `gpu/cuda/kernels/` - real CUDA SHA256d /
  parallel nonce-search source, plus the userspace toolchain installer
  (`install_userspace.py`) and build helper (`build.py`). The source
  compiles under CUDA 13.0.
- `gpu/benchmark/` - repeated CPU/CUDA benchmark harness.
- `gpu/diagnostics/` - privacy-safe operational diagnostics (backend
  status and fallback reasons only; no GPU model, architecture, compute
  capability or hardware identifiers).

What is not proven: actual GPU execution. In the development environment
the CUDA runtime cannot initialize (no loadable system driver / device
access), so the two real-CUDA tests skip honestly, no GPU hashrate is
claimed, and all measured mining results are CPU. Source compilation does
not prove kernel runtime correctness; only a successful run on
GPU-capable hardware would. See `docs/CUDA_TASK_004.md` and
`results/CUDA_TEST_RESULTS_004.md` for the full investigation.

Integration: the mining engine (`mining/engine/search.py`) dispatches
every batch through `ComputeEngine`, records the backend that actually
hashed, and the autonomous agent selects the backend from measured probe
results - never assumed availability.
