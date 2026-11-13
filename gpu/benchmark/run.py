"""Repeated bounded actual-execution measurements, never synthetic GPU rates."""
import argparse
import json
import statistics
import time
from pathlib import Path
from gpu.diagnostics.report import collect
from gpu.engine import ComputeEngine, CudaBackend, CudaError, MAX_BATCH, uint


def run(batch_sizes=(256, 4096), thread_counts=(64, 128, 256), repeats=3):
    uint('repeats', repeats, 2, 10)
    if not isinstance(batch_sizes, (list, tuple)) or not 1 <= len(batch_sizes) <= 8:
        raise ValueError('require 1..8 batch sizes')
    if not isinstance(thread_counts, (list, tuple)) or not 1 <= len(thread_counts) <= 8:
        raise ValueError('require 1..8 thread configurations')
    for count in batch_sizes:
        uint('batch size', count, 1, min(MAX_BATCH, 65536))
    for threads in thread_counts:
        uint('threads', threads, 1, 1024)
    diagnostics = collect(probe_kernel=False)
    init_start = time.perf_counter()
    try:
        cuda = CudaBackend(diagnostics)
    except (CudaError, OSError, ValueError):
        cuda = None
    initialization = time.perf_counter() - init_start
    rows = []
    engines = [ComputeEngine('cpu')]
    if cuda:
        gpu = ComputeEngine('cpu')
        gpu.backend = cuda
        gpu.requested_backend = 'cuda'
        engines.append(gpu)
    header = bytes(range(80))
    for engine in engines:
        for count in batch_sizes:
            configurations = thread_counts if engine.backend.name == 'cuda' else (128,)
            for threads in configurations:
                if engine.backend.name == 'cuda':
                    limits = diagnostics['limits']
                    if threads > min(limits['max_threads_per_block'], limits['max_block_dim_x']):
                        continue
                    if (count+threads-1)//threads > limits['max_grid_dim_x']:
                        continue
                # Warmup excluded; validation and allocation included in timed samples.
                engine.batch(header, 1, 0, min(count, 32), threads)
                if engine.backend.name == 'cpu' and engine.requested_backend == 'cuda':
                    raise CudaError('CUDA failed during benchmark warmup; no GPU timing published')
                times, device_times = [], []
                for _ in range(repeats):
                    result = engine.batch(header, 1, 0, count, threads)
                    if result['backend'] != engine.requested_backend:
                        raise CudaError('CUDA failed during benchmark; no GPU timing published')
                    times.append(result['elapsed_seconds'])
                    if engine.backend.name == 'cuda':
                        device_times.append(engine.backend.last_device_batch_seconds)
                median = statistics.median(times)
                rows.append(dict(backend=engine.backend.name, batch_size=count,
                                 threads=threads if engine.backend.name == 'cuda' else None,
                                 repeats=repeats, hashes_per_repeat=count,
                                 total_hashes=count*repeats, elapsed_seconds=times,
                                 median_seconds=median, hashes_per_second=count/median,
                                 device_batch_seconds=device_times or None,
                                 requested_gpu_bytes=80+32+33*count if device_times else None))
    gpu_rows = [row for row in rows if row['backend'] == 'cuda']
    best = max(gpu_rows, key=lambda r: r['hashes_per_second']) if gpu_rows else None
    return dict(method='end-to-end batch including CPU verification; not mining throughput',
                raw_kernel_throughput=None,
                device_batch_method='allocation + transfers + synchronized kernel, excludes CPU verification',
                cuda_initialization_seconds=initialization,
                cuda_status='executed_cpu_verified' if gpu_rows else 'unavailable_not_benchmarked',
                diagnostics=diagnostics, rows=rows, selected_cuda_configuration=best)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run()
    if args.output:
        args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
