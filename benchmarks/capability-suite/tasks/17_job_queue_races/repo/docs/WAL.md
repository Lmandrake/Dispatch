# Write-ahead log

Directory layout under the broker's data directory:

```
DATA/
  taskmill.json            optional configuration
  schedules.json           optional schedules for the runtime
  wal/wal-000001.log       log segments, numbered from 1
  wal/wal-000002.log
  snapshots/snapshot-000000000041.json
```

## Record framing

```
offset  size  field
0       4     magic b"TMW1"
4       4     payload length, unsigned big-endian
8       4     zlib.crc32(payload), unsigned big-endian
12      n     payload: canonical JSON (sorted keys, no spaces, UTF-8)
```

Every payload is an object with `seq` (int, strictly increasing in the order
changes were made) and `op`; see `state.py` for each op's fields.

Records are appended by the thread that made the change, after it released
the broker lock. Records can therefore appear in the files out of `seq`
order (and across a segment boundary). Readers must treat `seq` as the
order of events. `taskmill wal verify` reports `file_order_is_seq_order`.

## Segments and checkpoints

A new segment starts when the current one reaches `wal_segment_bytes`, and at
every checkpoint.

A checkpoint writes `snapshots/snapshot-<S>.json`. The snapshot at position
`S` must contain exactly the effects of the changes with `seq <= S`: every
one of them, and none after. It then deletes every non-current segment whose
records all have `seq <= S`. Operations keep running while a checkpoint is
in progress (it does not hold the broker lock while writing), so changes
made during a checkpoint must end up either in the snapshot or after `S`
in the log, never neither.

## Torn tails and corruption

A crash may leave the final record of the newest segment incomplete: a
partial header, a partial payload, or a payload whose CRC does not match.
Such a record was never acknowledged to a caller, so it is dropped. On open,
the newest segment is truncated back to the end of its last good record
before anything new is appended, so that the log stays a clean sequence of
records. Damage anywhere else (a bad record followed by more data, or in an
older segment) is corruption: opening fails with `WalCorrupt`, and an
operator must decide what to do.

## Recovery

1. Load the newest snapshot whose checksum is valid (fall back to older ones).
2. Scan all segments.
3. Replay every record with `seq` greater than the snapshot's `last_seq`, in
   `seq` order.

Recovery must produce exactly the state the broker had in memory when it
last returned from an operation (`Broker.fingerprint()` is equal).
