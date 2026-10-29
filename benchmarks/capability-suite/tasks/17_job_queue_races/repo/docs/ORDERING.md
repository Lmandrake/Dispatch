# Reservation order

Ready (pending) jobs are reserved in ascending `(priority, ready_at, seq)`:
lower priority number first (0 is the most urgent), then the job that became
ready first, then the one enqueued first. Across several queues the same key
decides (fair queues: see `docs/FAIRNESS.md`).

`ready_at` is the moment a job became eligible:

* its enqueue time, for a job enqueued without a delay;
* its `run_at`, for a delayed job or a retry;
* its old lease's deadline, after a lease expiry.

A delayed job is eligible from its `run_at` on, whatever else is in the
queue: once due, it competes with ready work on equal terms at every
reservation, as if it had been sitting in the ready heap since `run_at`.
How promotion is implemented (eagerly or lazily) must not be observable in
the order.

`Broker.order(queue)` lists the queue's jobs in the order successive
reservations would return them now (due jobs included), followed by delayed
jobs that are not yet due in `(run_at, seq)` order.
