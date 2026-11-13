"""Explicit offline build using nvcc's supported default configuration.

No native architecture detection, device property queries or system modification.
Compiler output is not exposed because it can contain restricted details.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path


def build():
    nvcc = shutil.which('nvcc')
    if not nvcc:
        raise RuntimeError('CUDA compiler unavailable; no build attempted')
    root = Path(__file__).resolve().parent
    output = root / 'libbal_cuda.so'
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / output.name
        with tempfile.TemporaryFile() as log:
            try:
                result = subprocess.run([nvcc, '--shared', '-Xcompiler', '-fPIC',
                                         '--cudart', 'shared', '--cudadevrt', 'none',
                                         '-L' + str(Path(nvcc).resolve().parent.parent / 'lib'),
                                         '-O3', str(root / 'engine.cu'), '-o', str(candidate)],
                                        stdout=log, stderr=log, timeout=180, check=False)
            except (OSError, subprocess.TimeoutExpired):
                raise RuntimeError('CUDA compilation unavailable or timed out') from None
        if result.returncode:
            raise RuntimeError('CUDA compilation failed; compiler details withheld for privacy')
        shutil.copyfile(candidate, output)
    return output


if __name__ == '__main__':
    try:
        build()
        print('CUDA library built; execution self-test still required')
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
