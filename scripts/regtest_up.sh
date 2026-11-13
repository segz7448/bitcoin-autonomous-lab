#!/usr/bin/env bash
# Start the lab's regtest Bitcoin Core node (uses BAL_* env overrides if set).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m node.node_manager start
