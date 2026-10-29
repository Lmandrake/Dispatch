# TICKET-4540: work lost across a restart (sev 2)

Opened by: Orders

> On 2026-10-23 an order-confirmation job was enqueued (we have the job id
> from the API response) about the time the broker was writing its periodic
> checkpoint. After the next restart the job did not exist and its id was
> later handed out again to a different job. A heartbeat and an ack from the
> same few milliseconds were also lost: the job ran again after the restart.
> `taskmill recover --check` on a copy of the data shows the snapshot from
> that checkpoint and no error.

> Checkpoints run every 5000 records under load, so the broker is busy while
> they are written.
