# Hook points

`broker.hooks.add(point, fn)` registers `fn(**kwargs)`; it returns a remover.
Hooks run synchronously in the thread doing the work and never with the
broker lock held, so a hook may block (tests use this to pause an operation
at a known point) or call back into the broker.

| point | fired | kwargs |
|---|---|---|
| `enqueue` | after an enqueue is committed and logged | `job` (a copy) |
| `reserve` | after a reservation is committed and logged | `job_id`, `token`, `worker` |
| `ack.before_commit` | ack: token checked and result encoded, before the commit | `job_id`, `token` |
| `nack.before_commit` | nack: token checked and error text prepared, before the commit | `job_id`, `token` |
| `cancel.before_commit` | cancel: job found unfinished, before the commit (a hook may raise to veto) | `job_id`, `state` |
| `heartbeat` | after a renewal is committed | `job_id`, `token`, `deadline` |
| `wal.append` | for each record, just before it is written (no locks held) | `record` |
| `reap` | after expired leases were committed | `expired` (job ids) |
| `checkpoint.begin` | checkpoint: state captured, before the snapshot is written | `jobs` (count) |
| `checkpoint` | after a snapshot was written | `last_seq` |
| `handler.start` | worker: before calling the handler | `job_id`, `worker` |
| `handler.end` | worker: after ack/nack | `job_id`, `worker`, `ok` |

An exception raised by a hook propagates into the operation.
