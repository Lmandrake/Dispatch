# Configuration

`BrokerConfig` fields (all optional in `taskmill.json`; unknown keys are an error):

| key | default | meaning |
|---|---|---|
| `id_prefix` | `"job"` | job ids are `<prefix>-<n>` |
| `visibility_timeout` | 30 | seconds a reservation lasts without a heartbeat |
| `max_visibility_timeout` | 3600 | heartbeats never extend a lease past `issued_at` + this |
| `max_attempts` | 5 | deliveries before a failing job is dead |
| `backoff` | exponential 1s x2, max 300s | retry delay policy (see `backoff.py`) |
| `default_priority` | 5 | 0 is the most urgent, 9 the least |
| `dedup_window` | 86400 | idempotency keys stay held this long after the job finishes |
| `retention` | 604800 | finished jobs are purged this long after finishing |
| `max_payload_bytes`, `max_result_bytes` | 65536 | encoded size limits |
| `max_errors_kept` | 5 | per job, oldest dropped first |
| `retired_token_ttl` | 600 | how long old lease tokens are remembered for error messages |
| `wal_fsync` | `"always"` | `always`, `batch` or `never` |
| `wal_segment_bytes` | 1048576 | segment rotation size |
| `checkpoint_every` | 0 | automatic checkpoint after this many records (0 = off) |
| `snapshots_kept` | 2 | older snapshots are deleted |
| `queues` | `{}` | per-queue `max_attempts`, `visibility_timeout`, `backoff`, `rate`, `burst`, `paused`, `fair`, `tenant_weights`, `default_weight` (see FAIRNESS.md) |

Environment overrides: `TASKMILL_<KEY>` for scalar keys (`BrokerConfig.from_env`).
