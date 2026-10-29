# Leases

Reserving a job grants a lease: an opaque random token, the worker's name and
a deadline (`now + visibility_timeout` of the job's queue). The token is the
only way to `ack`, `nack`, `heartbeat` or `release` that delivery.

A lease is **valid** while both hold:

* it is the job's current lease (the job has not been redelivered under a
  newer token, acked, nacked, released or cancelled since), and
* the broker clock is before its deadline (`now < deadline`).

`ack`, `nack`, `heartbeat` and `release` succeed only with a valid lease, and
validity is judged at the instant the operation is committed. Work the call
does before committing (encoding a result, preparing an error, firing the
`*.before_commit` hooks) does not count: if the lease stopped being valid in
the meantime, the call raises `LeaseLost`, changes nothing, writes no WAL
record, and counts `leases.lost{op=<ack|nack|heartbeat|release>}`.

A heartbeat sets the deadline to `now + extend` (default: the queue's
visibility timeout), never shortens it, and never moves it past
`issued_at + max_visibility_timeout`. A heartbeat presented with a token
that is not the job's current lease token never touches the current lease.

When a lease's deadline passes, the reaper (or the next `reserve`) expires
it. The job goes back to `pending` with the error "lease expired", or to
`failed` if that delivery was its last allowed attempt (see
`docs/RETRIES.md`).

`release(token)` hands back a delivery the worker never started: the job is
pending again immediately and the attempt is not counted.

Tokens of finished leases are remembered for `retired_token_ttl` seconds so
that `LeaseLost` can say why ("expired", "superseded by a newer delivery",
"released", "cancelled").

## Cancellation

`cancel(job_id)` acts on the job's state at the moment the cancel is
committed. If the job was reserved by then (even if it was still pending
when `cancel` was called), the cancel ends that lease: the job is
`cancelled`, and the holder's later `ack`, `nack` or `heartbeat` raises
`LeaseLost` ("cancelled"). A cancelled job is never delivered again unless
an operator retries it.
