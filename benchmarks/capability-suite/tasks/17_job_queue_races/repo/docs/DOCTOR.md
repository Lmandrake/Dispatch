# taskmill doctor

Status: **specified, not implemented yet** (requested by SRE after
TICKET-4471; they want to find past damage in production logs).

```
python3 -m taskmill doctor DATA [--json]
```

Reads every record in `DATA/wal` (read-only: never repairs or truncates
anything) and reports what the log shows went wrong. It does not open a
broker and does not need a snapshot.

## Analysis

Records are analysed in `seq` order. Only jobs whose `enqueue` record is in
the log are judged; records for other jobs (history before the oldest
remaining segment) are ignored. For each judged job the doctor tracks the
current lease token, the seq of its first `ack`, and whether it is
cancelled:

| record | rule |
|---|---|
| `reserve` | if the job is cancelled (a `cancel` with no `requeue` since): anomaly `reserve-after-cancel`, detail `cancelled at seq <c>`. In every case the record's token becomes the current token. |
| `ack`, `retry`, `fail`, `release`, `heartbeat` | if the record's token is not the current token: anomaly `stale-<op>`, detail `token <t> (current: <c>)`, and the record otherwise changes nothing. Else `ack`, `retry`, `fail` and `release` clear the current token (a valid `heartbeat` keeps it). |
| `ack` | additionally, if the job already had an `ack` (stale or not): anomaly `duplicate-ack`, detail `first ack at seq <f>`. The first `ack` of a job, valid or stale, sets its first-ack seq. |
| `expire` | clears the current token |
| `cancel` | clears the current token; the job is cancelled |
| `requeue` | the job is no longer cancelled; its first-ack seq is forgotten |
| `purge` | the purged jobs are forgotten (no longer judged) |
| others | nothing |

`<t>` and `<c>` are the first 6 characters of the tokens; `<c>` is `none`
when there is no current token.

## Text output

```
doctor: <R> record(s), seq <min>..<max>, <J> job(s), <A> anomaly(ies)
<seq> <job_id> <kind> <detail>
...
```

* `R` is the number of records read, `min`/`max` the smallest and largest
  seq (`-` for both when the log is empty, written `seq -..-`), `J` the
  number of distinct jobs whose `enqueue` record is in the log (a job
  purged later still counts), `A` the number of anomaly lines. The words are
  always `record(s)`, `job(s)` and `anomaly(ies)`, whatever the counts.
* Then one line per anomaly, sorted by seq, then by kind (ascending).
* If the newest segment has a torn tail, a final line
  `torn tail: <reason> at byte <offset> of <segment file name>`.

Exit status: 0 if there are no anomalies, 3 if there is at least one, 1 if
the log is corrupt (`taskmill: <message>` on stderr, like other errors).

## JSON output

`--json` prints one JSON object (sorted keys, 2-space indent, like other
`--json` commands):

```json
{"records": R, "min_seq": min|null, "max_seq": max|null, "jobs": J,
 "anomalies": [{"seq": 7, "job_id": "job-3", "kind": "stale-ack", "detail": "token 1a2b3c (current: 9f8e7d)"}],
 "torn_tail": null | {"path": "wal-000002.log", "offset": 812, "size": 830, "reason": "short payload"}}
```

with the same exit status rules.

## Library

`taskmill.doctor.diagnose(records) -> list of dicts` (the `anomalies` list
above, for any iterable of record dicts) and
`taskmill.doctor.examine(data_dir) -> dict` (the JSON document).
