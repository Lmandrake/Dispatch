# TICKET-4502: month-end jobs fire on the wrong day; retry storms (sev 3)

Opened by: Finance Engineering

> Our `close-books` schedule is `0 2 29 * *` (02:00 UTC on the 29th, monthly).
> It has been fine for years, but our long-range planning export lists a
> run for 1 March 2100 (and nothing on 29 March 2100 would be wrong, but
> the 1 March one is not a 29th at all).

> `taskmill cron '0 0 29 2 *' --after 4070908800 --count 3` (from 2099)
> prints `2100-03-01T00:00` first. 2100 is not a leap year.

Opened by: Integrations

> We switched the partner-sync queue to `{"kind": "exponential", "base": 2,
> "factor": 2, "max": 30, "jitter": "decorrelated"}` because the docs
> recommended it for thundering herds. Some retries now wait well over 30 s
> (we logged 47 s and 71 s), and once a delay grows, later attempts keep
> growing from it. With `full` or `equal` jitter the delays never go over
> `max`.
