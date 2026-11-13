import ctypes as ct
import hashlib
import json
from gpu.engine import CudaBackend, CudaError, ComputeEngine
from gpu.diagnostics.report import load_runtime
from mining.pow.target import MAX_UINT256
print('CUDA operational checks only')
try:
    driver = ct.CDLL('libcuda.so.1')
    print('driver_cuInit_status:', driver.cuInit(0))
except OSError:
    print('driver_library: not loadable')
runtime = load_runtime()
if runtime is None:
    print('runtime_library: not loadable')
else:
    version = ct.c_int()
    print('runtime_version_query_status:', runtime.cudaRuntimeGetVersion(ct.byref(version)))
    print('runtime_version:', version.value)
    count = ct.c_int()
    status = runtime.cudaGetDeviceCount(ct.byref(count))
    print('cudaGetDeviceCount_status:', status)
    if status == 0:
        print('accessible_device_count:', count.value)
try:
    cuda = CudaBackend()
    cuda.batch(bytes(range(80)), MAX_UINT256, 0, 4, 32)
    print('actual_CUDA_execution: passed CPU-verified batch')
except CudaError as exc:
    print('actual_CUDA_execution: unavailable:', str(exc))
for requested in ('auto', 'cuda', 'cpu'):
    header = bytes(range(80))
    out = ComputeEngine(requested).batch(header, MAX_UINT256, 7, 4)
    expected = [hashlib.sha256(hashlib.sha256(header[:76] + n.to_bytes(4, 'little')).digest()).hexdigest() for n in range(7, 11)]
    valid = out['digests'] == expected
    print(json.dumps({'requested': requested, 'actual_backend': out['backend'], 'fallback_reason': out['fallback_reason'], 'four_SHA256d_digests_match_hashlib': valid}))
    if not valid:
        raise SystemExit(1)
