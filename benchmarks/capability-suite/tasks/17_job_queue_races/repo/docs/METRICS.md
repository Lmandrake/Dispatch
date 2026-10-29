# Metrics

Every component records into one `Metrics` registry (`broker.metrics`):

```
jobs.enqueued{queue}       jobs.deduplicated{queue}   jobs.reserved{queue}
jobs.acked{queue}          jobs.retried{queue}        jobs.failed{queue}
jobs.expired{queue}        jobs.cancelled{queue}      jobs.purged
leases.heartbeats          leases.lost{op}
worker.handled{kind,outcome}                          worker.run_seconds (histogram)
scheduler.fired{schedule}  scheduler.skipped{schedule}
resultcache.hits{kind}     resultcache.misses{kind}
wal.records                checkpoints
```

`snapshot()` returns `{"name{k=v,...}": value}` with labels sorted by name
(no braces without labels). Histograms appear as `name.count`, `name.sum`,
`name.max` and cumulative `name.le_<bound>` buckets. `render_text()` gives
one `name value` line per series, sorted.

Every update is exact: concurrent `inc` and `observe` calls from any number
of threads never lose an increment or an observation, and `last_updated`
reflects the latest update. Operators reconcile `jobs.acked` against the
business tables every night.
