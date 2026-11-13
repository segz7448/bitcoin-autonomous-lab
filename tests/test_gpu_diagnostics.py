"""Allowlist diagnostics control flow with fault doubles, not GPU evidence."""
import unittest
from unittest.mock import patch
from gpu.diagnostics.report import collect


class Runtime:
    def __init__(self,init=0,allocation=0):self.init=init;self.allocation=allocation;self.attributes=[]
    def cudaRuntimeGetVersion(self,p):p._obj.value=13000;return 0
    def cudaGetDeviceCount(self,p):p._obj.value=1;return self.init
    def cudaSetDevice(self,d):return 0
    def cudaDeviceGetAttribute(self,p,a,d):self.attributes.append(a);p._obj.value=128;return 0
    def cudaMemGetInfo(self,a,t):a._obj.value=1024;t._obj.value=2048;return 0
    def cudaMalloc(self,p,n):p._obj.value=1234;return self.allocation
    def cudaFree(self,p):return 0


class TestDiagnosticsFaults(unittest.TestCase):
    def test_runtime_collects_only_authorized_attributes(self):
        runtime=Runtime()
        with patch('gpu.diagnostics.report.load_runtime',return_value=runtime),patch('gpu.diagnostics.report.ct.CDLL',side_effect=OSError):
            r=collect(probe_kernel=False)
        self.assertEqual(runtime.attributes,list(range(1,8)))
        self.assertTrue(r['cuda_accessible']);self.assertFalse(r['gpu_operational'])
        self.assertEqual(r['gpu_memory_total_bytes'],2048)
        self.assertEqual(r['allocation_status'],0)
        self.assertEqual(r['kernel_execution_status'],'not_run')

    def test_allocation_failure_not_operational(self):
        with patch('gpu.diagnostics.report.load_runtime',return_value=Runtime(allocation=2)):
            r=collect()
        self.assertFalse(r['gpu_operational']);self.assertEqual(r['allocation_status'],2)
        self.assertEqual(r['kernel_execution_status'],'not_run')

    def test_initialization_failure_not_operational(self):
        with patch('gpu.diagnostics.report.load_runtime',return_value=Runtime(init=35)):
            r=collect()
        self.assertFalse(r['cuda_accessible']);self.assertFalse(r['gpu_operational'])
        self.assertEqual(r['initialization_status'],35)

    def test_kernel_failure_not_operational(self):
        with patch('gpu.diagnostics.report.load_runtime',return_value=Runtime()),patch('gpu.engine.CudaBackend',side_effect=RuntimeError):
            r=collect()
        self.assertFalse(r['gpu_operational'])
        self.assertEqual(r['kernel_execution_status'],'failed_or_unavailable')
