# The worker pool

`WorkerPool(broker, registry, concurrency=4, prefetch=1)` runs
`concurrency` worker threads, a completion thread and a heartbeat thread.

Each worker reserves up to `prefetch` jobs at a time (one blocking reserve,
then non-blocking ones to fill the buffer) and runs their handlers one after
another, in reservation order. Prefetched jobs are "in flight" from the
moment they are reserved: the heartbeat thread renews their leases.

A handler's outcome is handed to the completion thread, which performs the
`ack` or `nack` and records `worker.handled{kind,outcome}` (`ok`, `retry`,
`failed`, `lost`, `no_handler`) and `worker.run_seconds`. Outcomes whose
ack/nack is rejected with `LeaseLost` count as `lost`.

## Shutdown

`stop()` (and leaving the `with` block):

1. stops reserving new jobs;
2. lets every handler that has already started finish;
3. completes (acks/nacks) every outcome produced, including those still
   queued for the completion thread;
4. gives back every prefetched job whose handler never started with
   `Broker.release`, so it is pending again at once and its attempt is not
   counted;
5. stops the heartbeat thread.

After `stop()` returns, no job is left reserved by the pool.
