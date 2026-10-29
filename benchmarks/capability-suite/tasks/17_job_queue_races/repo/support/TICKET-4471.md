# TICKET-4471: "retry backoff is broken, jobs run twice" (escalated, sev 2)

Opened by: Customer Success (billing-notifications team)
Escalated to: platform / taskmill owners

## Summary from support

Since we moved billing notifications onto taskmill 2.4 we keep getting
customers who receive the same invoice email twice, and occasionally a
refund gets issued twice. The billing team thinks the retry backoff is
broken: jobs seem to be retried immediately instead of waiting, so the
retry runs while the first attempt is still going. They have asked us to
"just set backoff to 10 minutes everywhere". Please take a proper look.

## What the teams reported (verbatim excerpts)

billing-notifications:

> worker-7 and worker-12 both logged `send_invoice ok` for job-88213 about
> 40 s apart. The invoice provider is slow at month end, 30-50 s per call,
> and the host had a long stall that night. Our visibility timeout is 30 s
> and the pool heartbeats every 10 s. worker-7's ack returned without error;
> worker-12's ack was rejected with LeaseLost. The job shows attempts=2,
> state=done and worker-7's result.

> We also see `heartbeat ok` lines from worker-7 for job-88213 AFTER
> worker-12 had already picked the job up, so worker-7 never noticed it had
> lost the job.

> Separately, a refund job that worker-3 nacked (provider timeout) went to
> `delayed` while worker-9 was halfway through running it, and then ran a
> third time.

payments:

> Refund retries are scheduled with backoff (base 5 s, factor 2). During the
> month-end peak the refund queue is never empty, and failed refunds just sit
> in `delayed` for hours: their run_at is long past but nothing picks them
> up until the queue drains at night. Also a priority-0 retry waited behind
> priority-9 bulk work. Outside peak hours retries are on time.

orders:

> Enqueue with idempotency key `INV-1/23` returned job-90455, which is the job
> for invoice `INV-12/3` (a different customer). Same thing happened for
> `Order 12` vs `ORDER-12`, which our two storefronts use for different
> orders. Our keys are case-sensitive and we never asked for any folding.

reporting:

> We have two schedules, `daily-report` (finance) and `daily.report`
> (marketing), both `0 6 * * *`. Only one of the two reports runs each
> morning; `scheduler.fired` shows one of them and the other's enqueue
> comes back as an existing job.

sre:

> After the host crash on 2026-10-21 the broker restarted fine and logged
> "discarded torn tail at byte 1048342 of wal-000017.log". The NEXT restart
> (routine deploy two days later) failed with
> `WalCorrupt: wal-000017.log: bad magic at byte 1048342` and we had to
> restore from the night's snapshot.

> After restarts we sometimes find a queue paused that an operator had
> resumed, or a job back at an old priority. `taskmill wal verify` says
> `file_order_is_seq_order: false` on those logs.

> The Grafana panel `sum(jobs.acked)` is lower than the number of jobs in
> state done, by a few hundred per day on the busy queues. Same for
> `worker.handled` vs the handler logs.

## Environment

taskmill 2.5.0, 32 worker threads, `wal_fsync=batch`, checkpoints every 5000
records, CPython 3.12.

## Follow-up from SRE

Once this is fixed we need `taskmill doctor` (docs/DOCTOR.md) to find which
past jobs were affected, and billing needs the fair queues in
docs/FAIRNESS.md before the multi-tenant rollout.
