# TICKET-4519: cancelled jobs still run; deploys leave jobs stuck (sev 2)

Opened by: Customer Success (subscriptions)

> A customer cancelled their order from the web UI, the API said
> `{"cancelled": true}`, and the fulfilment job kept running and shipped
> the box. It happens when the cancel arrives right as a worker picks the
> job up. The job record says `cancelled`, yet `GET /leases` still lists a
> lease for it, its worker kept heartbeating it without error, and when the
> worker finished, its ack failed with an internal error ("cannot go from
> cancelled to done") instead of the usual LeaseLost. That pool then
> stopped completing any jobs at all until it was restarted.

Opened by: SRE

> Rolling deploys of the worker fleet (pools run with `prefetch=8`) leave a
> batch of jobs in `reserved` with no worker holding them. They only come
> back after the visibility timeout (10 minutes on the reports queue), and
> each of them has one attempt burned without ever running. A couple with
> `max_attempts=1` went straight to failed. Before prefetch was introduced
> deploys were clean.

> Jobs whose handler hangs past the visibility timeout on their last
> allowed attempt are delivered one extra time: a job with
> `max_attempts=3` shows `attempts: 4` after three timeouts and a fourth
> run. Jobs that fail by raising stop at 3 as expected.
