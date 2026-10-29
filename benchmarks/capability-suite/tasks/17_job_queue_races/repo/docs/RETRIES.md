# Retries and backoff

`attempts` counts deliveries: it goes up by one each time the job is
reserved (and down by one on `release`). A job may be delivered at most
`max_attempts` times.

When a delivery fails:

* `nack(permanent=True)`, a `PermanentError` from the handler, or a failed
  delivery with `attempts == max_attempts` fails the job;
* otherwise the job is retried after a delay: `retry_in` if given (or the
  handler's `Retry(delay=...)`), else the backoff policy's delay for
  `attempts` (1 after the first failed delivery).

A lease that expires counts as a failed delivery in exactly the same way:
the delivery that used up the last attempt fails the job, it is never
delivered again.

## Policies

```
{"kind": "fixed",       "delay": 5}
{"kind": "linear",      "base": 2, "step": 3, "max": 60}
{"kind": "exponential", "base": 1, "factor": 2, "max": 300}
```

The raw delay for attempt `n` is `delay`, `base + step*(n-1)` or
`base * factor**(n-1)`. Every policy accepts `jitter`:

| jitter | delay |
|---|---|
| `none` | the raw delay |
| `full` | uniform in `[0, raw]` |
| `equal` | `raw/2` + uniform in `[0, raw/2]` |
| `decorrelated` | `d(0) = base`; `d(n)` = uniform in `[base, 3*d(n-1)]`; only meaningful for `exponential` |

`max`, when present, is a hard ceiling: **no delay produced by any policy
and any jitter ever exceeds `max`**, and for `decorrelated` the capped value
is what feeds the next step (`d(n) = min(max, uniform(base, 3*d(n-1)))`).

Jitter is deterministic per (job id, attempt): the random generator is
seeded from both (`backoff._seed`), so replaying or re-evaluating a decision
gives the same delay.
