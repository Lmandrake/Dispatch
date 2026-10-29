# Schedules and cron

Five-field cron, evaluated in UTC: minute (0-59), hour (0-23), day of month
(1-31), month (1-12 or jan-dec), day of week (0-6 or sun-sat, 7 is also
Sunday). Fields accept `*`, `n`, `a-b`, lists and `/step`. When both day of
month and day of week are restricted, a time matches if either matches.
Aliases `@hourly`, `@daily`/`@midnight`, `@weekly`, `@monthly`,
`@yearly`/`@annually`.

A time matches only if it is a real calendar date: day 31 never matches in
30-day months, day 30 never in February, and day 29 matches in February only
in leap years (Gregorian rules: divisible by 4, except centuries not
divisible by 400). `next_after(t)` returns the first matching minute
strictly after `t`; an expression that cannot match within 5 years (such as
`0 0 30 2 *`) raises `CronError`.

Each schedule slot is enqueued once, with the idempotency key
`cron/<schedule name>/<slot>` where the slot is `YYYY-MM-DDTHH:MM` (UTC) for
cron schedules and the integer slot time for `every` schedules.
