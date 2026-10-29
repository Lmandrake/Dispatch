# taskmill design

## One lock, short critical sections

The broker keeps all state in memory (`state.State`) behind one lock. Every
operation follows the same shape:

1. validate arguments (no lock);
2. take the lock; check the operation is allowed in the current state; build
   one or more WAL records, number them (`seq`), apply them to the state;
   release the lock;
3. append the records to the WAL (no broker lock: the WAL has its own lock
   and a slow disk must never stall reservations of other workers);
4. return.

Expensive work never happens under the broker lock: handlers run in worker
threads, results are encoded before the commit, hooks fire unlocked. This is
deliberate and load-bearing: with 32 workers, holding the broker lock across
an fsync or a large `json.dumps` showed up as a 10x drop in throughput in
the 2.1 benchmarks. Do not "fix" concurrency problems by widening the
critical section around I/O, encoding, hooks or handlers.

Because step 3 happens after the lock is released, two operations can reach
the WAL in either order. `seq` is the order the changes were made in; the
order of records in the files is only the order they happened to be written.

## Leases

The full rules are in `docs/LEASES.md`. In short: a reservation is a lease: a token valid until a deadline (`visibility_timeout`
after the reserve, extended by heartbeats). Only the current, unexpired lease
of a job may finish it. When a lease expires the job is delivered again
under a new token, and anything presented with the old token afterwards
(ack, nack, heartbeat) is rejected with `LeaseLost`. That is what makes
"at most one successful completion per job" hold even though handlers can
outlive their lease: a slow worker's late ack must lose against the
redelivery.

The decision to accept an ack, nack or heartbeat is made at the moment the
operation takes effect (when its record is applied), not when the call
started.

## Ordering

See `docs/ORDERING.md`; fair queues in `docs/FAIRNESS.md`.

## Durability

Every committed change is in the WAL before the call returns (with
`wal_fsync=always`). Checkpoints write a snapshot of the whole state at a
`seq` and delete WAL segments entirely covered by it. Recovery loads the
newest snapshot and replays newer records in `seq` order. See `docs/WAL.md`.

## Idempotency

See `docs/IDEMPOTENCY.md`.

## Metrics

Counters must be exact under any number of threads: operators reconcile
`jobs.acked` against the business tables every night.

The metric names are listed in `docs/METRICS.md`.

## Other documents

`docs/RETRIES.md` (backoff), `docs/SCHEDULES.md` (cron), `docs/WORKERS.md`
(the pool), `docs/RESULT_CACHE.md`, `docs/FAIRNESS.md`, `docs/DOCTOR.md`.
