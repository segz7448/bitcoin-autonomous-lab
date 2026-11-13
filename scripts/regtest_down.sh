#!/usr/bin/env bash
# Stop the lab's regtest Bitcoin Core node.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m node.node_manager stop
