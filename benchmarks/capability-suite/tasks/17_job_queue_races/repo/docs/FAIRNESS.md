# Fair queues (per-tenant weighted round robin)

Status: **specified, not implemented yet** (requested by the platform
council for the multi-tenant billing rollout). `QueueConfig` already
accepts the settings; the broker ignores them today.

## Configuration

```json
{"queues": {"billing": {"fair": true, "tenant_weights": {"acme": 3, "globex": 1}, "default_weight": 1}}}
```

Jobs carry an optional `tenant` (`Broker.enqueue(..., tenant="acme")`).
In a fair queue, jobs without a tenant belong to the tenant named
`default`. A tenant's weight is `tenant_weights[tenant]` if listed, else
`default_weight`. Queues without `fair: true` behave exactly as before
(tenants are ignored for ordering).

## Order

A fair queue serves its tenants in turns. The queue remembers the tenant
whose turn it is (`T`, initially none) and how many jobs `T` has been given
in the current turn (`n`).

On each reservation from the queue:

1. If `T` is set, `T` has a ready job and `n < weight(T)`: serve `T` and set
   `n = n + 1`.
2. Otherwise the turn passes to the next tenant that has a ready job: the
   first such tenant in ascending name order strictly after `T`, wrapping
   around to the start (so `T` itself comes last); if `T` is not set, the
   first tenant in name order with a ready job. Serve that tenant, make it
   `T` and set `n = 1`.

"Serve a tenant" means reserve that tenant's next job by the usual
`(priority, ready_at, seq)` order. Priority therefore orders jobs within a
tenant, not across tenants. "Ready" includes delayed jobs that are due (see
ORDERING.md).

Example: weights acme 3, globex 1, initech 2 (default), each with plenty of
work. Reservations go `acme acme acme globex initech initech acme acme acme
globex ...`. If globex has no ready job when its turn comes, the turn goes
straight to initech.

## Interaction with other features

* When several queues are eligible for one `reserve`, a fair queue offers
  the job that its next turn would serve, and queues are compared on that
  job's `(priority, ready_at, seq)` as usual. Only an actual reservation
  advances the turn (peeking, `order()`, stats do not).
* Paused and rate-limited queues are skipped as before; skipping does not
  advance the turn.
* `Broker.order(queue)` for a fair queue lists ready jobs in the order
  successive reservations would serve them from the current turn state,
  then not-yet-due delayed jobs in `(run_at, seq)` order.
* The turn state is runtime state, like rate limits: it is not written to
  the WAL or snapshots, and a restarted broker starts with no turn.
* `queue_stats(queue)` gains `"fair": true|false` and, for fair queues,
  `"turn": [tenant, n]` (or `null` before the first reservation).

## Job.tenant and the API

`tenant` is validated like a queue name (1-64 of `a-z 0-9 _ . -`, starting
with a letter or digit). It is part of `Job.to_dict()`, `Job.summary()`,
the admin API (`POST /queues/<q>/jobs` accepts `"tenant"`; `GET /jobs`
accepts `?tenant=`) and the CLI (`taskmill enqueue ... --tenant T`;
`taskmill list ... --tenant T`). `Broker.jobs(queue=None, state=None,
tenant=None)` filters by tenant.
