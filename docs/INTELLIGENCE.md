# Blockchain Intelligence Engine (TASK 002)

The Intelligence Engine lets Bitcoin Autonomous Lab read, monitor,
interpret and analyze the Bitcoin blockchain independently. Everything it
reports comes from live Bitcoin Core RPC replies or from independent
recomputation against them - no blockchain data is simulated.

## Architecture

```
                 +---------------------------+
                 |      agent/interface.py    |  structured JSON answers
                 +------------+--------------+
                              |
                 +------------v--------------+
                 |   blockchain/service.py    |  MonitoringService:
                 |  sync loop, reorg watch,   |  polls cheaply, detects new
                 |  backoff/reconnect         |  blocks + reorgs, never dies
                 +--+--------+--------+---+--+     on RPC failure
                    |        |        |
        +-----------v--+ +---v-----+ +v-----------+
        | blockchain/  | |blockchain/ |blockchain/  |
        | reader.py    | |analysis.py |transactions.|
        | typed RPC    | |headers,    |py           |
        | queries      | |merkle,     |decode, fees,|
        |              | |subsidy     |mempool      |
        +-----------+--+ +---+-----+ +------+-----+
                    |        |             |
                 +--v--------v-------------v--+
                 |      node/rpc_client.py     |  Bitcoin Core JSON-RPC
                 +------------+---------------+
                              |
                 +------------v--------------+
                 |   blockchain/storage.py    |  SQLite: blocks, txs,
                 |  (reorg-safe)              |  mempool, sync, events
                 +---------------------------+
```

- `reader.py` - typed queries: height, best hash, blocks by hash/height,
  headers, txids, chain tips. No state.
- `analysis.py` - header/target/sizes interpretation, independent merkle
  root verification, subsidy schedule and fee accounting.
- `transactions.py` - transaction decode, inputs/outputs, fees where the
  data exists (mempool entries, verbosity-2 blocks), explicit
  "unavailable" results otherwise, mempool tracking and new-tx detection.
- `service.py` - the background monitor. An idle cycle costs exactly one
  `getblockcount` plus one `getblockhash` tip check; full `getblock` calls
  happen only for blocks that are actually new. Reorgs are detected by
  comparing stored hashes with the node's; RPC failures back off
  exponentially and the service reconnects (fresh cookie) instead of dying.
- `storage.py` - SQLite persistence for blocks, transactions, mempool
  sightings, sync state and monitor events. Blocks are keyed by hash with
  an `active`/`orphaned` status, so reorganization history is preserved
  rather than deleted.
- `agent/interface.py` - machine-readable answers (ok/error dicts) to:
  current height, latest hash, latest N blocks, analyze a block,
  tx count in latest block, network difficulty, mempool status,
  new-block discovery, transaction lookup.

## RPC methods used

getblockchaininfo, getblockcount, getbestblockhash, getblockhash,
getblock (verbosity 0/1/2), getblockheader, getchaintips,
getrawtransaction, decoderawtransaction, getmempoolinfo, getrawmempool,
getmempoolentry, generatetoaddress (regtest), sendtoaddress (regtest
wallet), invalidateblock/reconsiderblock (regtest testing), plus the
TASK 001 lifecycle calls (getnetworkinfo, uptime, stop, wallet creation).

## Database schema (SQLite)

- `blocks(hash PRIMARY KEY, height, prev_hash, merkle_root, time,
  median_time, bits, nonce, difficulty, size, stripped_size, weight,
  n_tx, status, processed_at)` - `status` is `active` or `orphaned`.
- `transactions(txid PRIMARY KEY, block_hash, size, vsize, weight,
  fee_btc, is_coinbase, n_inputs, n_outputs, value_out_btc,
  confirmations, status, first_seen, updated_at)`.
- `mempool_seen(txid PRIMARY KEY, first_seen, last_seen, fee_btc, vsize)`.
- `sync_state(id=1, last_height, last_hash, updated_at)`.
- `monitor_events(id, ts, kind, detail)`.

## Known limitations

- Fees for confirmed transactions require txindex or verbosity-2 block
  data; the engine reports them only where genuinely available and says
  so otherwise.
- The monitor polls (ZMQ notifications are a planned upgrade); the poll
  interval trades detection latency against RPC load.
- Regtest only, per the project's current scope. The NodeManager still
  refuses to operate on any other chain.

## Next recommended milestone

TASK 003 candidates: autonomous agent policies on top of the monitoring
service (alerting rules, watch addresses), ZMQ-based instant block
notification, and - only when explicitly authorized - regtest mining
experiments driven by the template miner from TASK 001.
