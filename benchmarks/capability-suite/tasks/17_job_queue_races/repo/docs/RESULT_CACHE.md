# Result cache

`CachedSubmitter(broker, kinds, ttl)` reuses results for job kinds that are
pure functions of their input. `submit(queue, kind, payload, tenant=...)`
returns a cached result when an identical job finished `done` less than
`ttl` seconds ago (by the broker clock), and otherwise enqueues the job.

Two submissions are identical when they have the same queue, the same kind,
the same payload (compared canonically: key order does not matter) and the
same tenant. A result is never served to a different tenant than the one
whose job produced it; jobs without a tenant only share results with other
jobs without a tenant. Failed or cancelled jobs are never cached.

`invalidate(queue, kind, payload, tenant=None)` drops one entry.
Counters: `resultcache.hits{kind}`, `resultcache.misses{kind}`.
