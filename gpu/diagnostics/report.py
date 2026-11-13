"""Allowlisted operational CUDA diagnostics. Never use device-property dumps."""
import ctypes as ct
import json
import re
import shutil
import subprocess
from pathlib import Path

# Only explicitly authorized scalar attributes, from cudaDeviceAttr.
ATTRIBUTES = {'max_threads_per_block': 1, 'max_block_dim_x': 2,
              'max_block_dim_y': 3, 'max_block_dim_z': 4,
              'max_grid_dim_x': 5, 'max_grid_dim_y': 6, 'max_grid_dim_z': 7}


def load_runtime():
    for name in ('libcudart.so', 'libcudart.so.13', 'libcudart.so.12', 'libcudart.so.11.0'):
        try:
            return ct.CDLL(name)
        except OSError:
            pass
    return None


def system_ram():
    values = {}
    # Read only the two permitted memory entries, never a hardware inventory.
    try:
        with open('/proc/meminfo', encoding='ascii') as stream:
            for line in stream:
                key, _, val = line.partition(':')
                if key in ('MemTotal', 'MemAvailable'):
                    values[key] = int(val.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return {'available_bytes': values.get('MemAvailable'), 'total_bytes': values.get('MemTotal')}


def collect(probe_kernel=True):
    r = dict(gpu_available=None, gpu_operational=False, cuda_accessible=False,
             device_count=None, driver_version=None, runtime_version=None,
             compiler_version=None, system_ram=system_ram(),
             gpu_memory_available_bytes=None, gpu_memory_total_bytes=None,
             initialization_status='not_run', allocation_status='not_run',
             kernel_execution_status='not_run', limits={k: None for k in ATTRIBUTES},
             blockers=[])
    try:
        driver = ct.CDLL('libcuda.so.1')
        ver = ct.c_int()
        if driver.cuDriverGetVersion(ct.byref(ver)) == 0:
            r['driver_version'] = ver.value
        status = driver.cuInit(0)
        r['driver_initialization_code'] = status
        if status == 0:
            count = ct.c_int()
            if driver.cuDeviceGetCount(ct.byref(count)) == 0:
                r['device_count'] = count.value
                r['gpu_available'] = count.value > 0
    except OSError:
        r['blockers'].append('CUDA driver library not loadable')
    compiler = shutil.which('nvcc')
    if compiler:
        try:
            out = subprocess.run([compiler, '--version'], capture_output=True,
                                 text=True, timeout=10, check=False)
            version = re.search(r'release (\d+\.\d+)', out.stdout)
            if out.returncode == 0 and version:
                r['compiler_version'] = version.group(1)
        except (OSError, subprocess.TimeoutExpired):
            r['blockers'].append('CUDA compiler version check failed')
    else:
        r['blockers'].append('CUDA compiler nvcc not installed')
    runtime = load_runtime()
    if runtime is None:
        r['blockers'].append('CUDA runtime library not loadable')
        return r
    ver = ct.c_int()
    if runtime.cudaRuntimeGetVersion(ct.byref(ver)) == 0:
        r['runtime_version'] = ver.value
    count = ct.c_int()
    status = runtime.cudaGetDeviceCount(ct.byref(count))
    r['initialization_status'] = status
    if status or count.value < 1:
        r['blockers'].append('CUDA runtime cannot access a device')
        return r
    r.update(device_count=count.value, gpu_available=True)
    status = runtime.cudaSetDevice(0)
    r['initialization_status'] = status
    if status:
        r['blockers'].append('CUDA device initialization failed')
        return r
    r['cuda_accessible'] = True
    for key, attribute in ATTRIBUTES.items():
        value = ct.c_int()
        if runtime.cudaDeviceGetAttribute(ct.byref(value), attribute, 0) == 0:
            r['limits'][key] = value.value
    available, total = ct.c_size_t(), ct.c_size_t()
    if runtime.cudaMemGetInfo(ct.byref(available), ct.byref(total)) == 0:
        r.update(gpu_memory_available_bytes=available.value, gpu_memory_total_bytes=total.value)
    pointer = ct.c_void_p()
    status = runtime.cudaMalloc(ct.byref(pointer), ct.c_size_t(4096))
    r['allocation_status'] = status
    if status == 0:
        free_status = runtime.cudaFree(pointer)
        if free_status:
            r['allocation_status'] = free_status
    if probe_kernel and r['allocation_status'] == 0:
        try:
            from gpu.engine import CudaBackend
            CudaBackend(diagnostics=r)
            r.update(gpu_operational=True, kernel_execution_status='passed_cpu_verified')
        except (RuntimeError, ValueError):
            r['kernel_execution_status'] = 'failed_or_unavailable'
            r['blockers'].append('CUDA library build or independent kernel self-test required')
    return r


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = collect()
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
