# Setup

## Requirements

- Python 3.10 or newer (standard library only; no pip packages).
- Bitcoin Core (24.x or newer recommended; developed and verified against
  Bitcoin Core 32.1).

## Install Bitcoin Core (verified download)

Download the release for your platform from
https://bitcoincore.org/bin/ and verify the tarball against the published
SHA256SUMS before extracting:

```bash
curl -LO https://bitcoincore.org/bin/bitcoin-core-32.1/bitcoin-32.1-x86_64-linux-gnu.tar.gz
curl -LO https://bitcoincore.org/bin/bitcoin-core-32.1/SHA256SUMS
grep x86_64-linux-gnu.tar.gz SHA256SUMS | sha256sum -c -   # must print: OK
tar xzf bitcoin-32.1-x86_64-linux-gnu.tar.gz
```

Point the lab at the binary (or put it on your PATH):

```bash
export BAL_BITCOIND=/path/to/bitcoin-32.1/bin/bitcoind
```

## Quickstart

```bash
# Run the full TASK 001 milestone against a real local regtest node:
python3 scripts/milestone_001.py

# Or manage a persistent node yourself:
./scripts/regtest_up.sh      # start (datadir .bal/regtest-data)
python3 -m dashboard.status  # live snapshot + tip verification
./scripts/regtest_down.sh    # stop

# Tests:
python3 -m unittest discover -s tests -t .            # unit + fake-node tests
BAL_BITCOIND=... python3 -m unittest tests.test_regtest_integration -v
```

## Configuration (environment variables, no config files with secrets)

| Variable        | Default              | Purpose                        |
|-----------------|----------------------|--------------------------------|
| `BAL_BITCOIND`  | `bitcoind` (PATH)    | bitcoind binary location       |
| `BAL_DATADIR`   | `.bal/regtest-data`  | regtest data directory         |
| `BAL_RPC_HOST`  | `127.0.0.1`          | RPC bind/connect host          |
| `BAL_RPC_PORT`  | `18443`              | RPC port (regtest default)     |
| `BAL_RPC_COOKIE`| (datadir cookie)     | override cookie path           |
| `BAL_RPC_USER`/`BAL_RPC_PASSWORD` | unset | explicit RPC auth (only if cookie auth is unavailable) |
