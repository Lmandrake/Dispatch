# Metering feeds

Usage arrives in three feeds. Every feed file sits in `<data dir>/feeds/`; files are read in
name order.

## API gateway export (`*.csv`)

RFC 4180 CSV, UTF-8, with a header line. The columns are

| column | meaning |
|---|---|
| `event_id` | unique id of the usage event |
| `customer` | customer id (case-insensitive) |
| `metric` | metric id, normally `api_calls` |
| `quantity` | non-negative decimal |
| `timestamp` | an instant with an offset (see docs/PERIODS.md) |
| `note` | free text from support engineers, usually empty |

Column order differs between gateway versions (the 2026 exports come in two orders); the
header is authoritative. Fields that contain a comma, a double quote or a line break are
enclosed in double quotes, and a double quote inside such a field is written twice. The
`note` column in particular often contains commas ("replayed by support, ticket 4471").

A row whose number of fields differs from the header's is **rejected**, not skipped: it goes
to the run's reject list with the reason, so that the reconciliation report shows it. No feed
row is ever dropped without trace.

## Storage snapshots (`*.jsonl`)

One JSON object per line: `id`, `customer`, `metric` (`storage_gb`), `value`, optional `unit`
(B, KB, MB, GB, TB; decimal multiples, default GB) and `ts`. `value` must be a decimal string
or an integer; a JSON float is rejected because storage sizes must not pick up binary rounding
error. `ts` may be epoch seconds, epoch milliseconds (13 digits) or an ISO string with an
offset; the offset is part of the instant (`2026-03-31T23:30:00+02:00` is 21:30 UTC), and an
ISO string without one is rejected.

## Seat audit log (`*.log`)

`<timestamp> key=value ...` per line; values with spaces are double-quoted (`\"` is a literal
quote). Required keys: `event`, `cust`, `metric`, `qty`. `#` lines are comments.

## Ingestion

1. A record of an unknown customer or metric is rejected.
2. An event id seen before, in any feed file of the run (the two gateway exports overlap,
   and the storage service re-sends snapshots), is a replay. If customer, metric, quantity and instant all agree
   it is dropped silently (gateways re-deliver after timeouts) and counted as a replay;
   otherwise the later record is rejected as a conflicting duplicate.
3. Every rejected row is listed in the reconciliation report.

## Alerts

`alerts.py` replays a period's records in time order and reports the first record at which a
customer's aggregated usage reaches a threshold they asked to be warned about.
