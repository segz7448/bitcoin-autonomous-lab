"""Install a pinned, matching user-space CUDA toolkit. No hardware discovery.

The driver and access to CUDA devices must be supplied by the system owner.
No system packages, drivers or permissions are changed here.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGES = ('nvidia-cuda-nvcc', 'nvidia-cuda-crt', 'nvidia-nvvm',
            'nvidia-cuda-runtime', 'nvidia-cuda-nvrtc')
VERSION = '13.0.88'


def install(destination):
    destination = Path(destination).expanduser().resolve()
    # A new dedicated directory avoids overwriting unrelated user packages.
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('choose an empty dedicated installation directory')
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as log:
        try:
            result = subprocess.run([sys.executable, '-m', 'pip', 'install',
                                     '--target', str(destination),
                                     *[p+'=='+VERSION for p in PACKAGES]],
                                    stdout=log, stderr=log, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('user-space CUDA installation failed or timed out') from None
    if result.returncode:
        raise RuntimeError('user-space CUDA installation failed; package output withheld for privacy')
    library = destination / 'nvidia' / 'cu13' / 'lib'
    # NVIDIA wheel ships a versioned runtime, while nvcc links -lcudart.
    alias = library / 'libcudart.so'
    if not alias.exists():
        alias.symlink_to('libcudart.so.13')
    print('CUDA 13.0 user-space toolkit installed; driver/device access still required')
    print('Add the installation nvidia/cu13/bin to PATH and nvidia/cu13/lib to LD_LIBRARY_PATH')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    install(args.destination)
