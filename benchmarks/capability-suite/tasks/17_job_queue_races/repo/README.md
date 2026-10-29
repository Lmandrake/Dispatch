# taskmill

A threaded, durable job queue for one process: priorities, delayed jobs,
leases with heartbeats, retries with backoff, idempotency keys, cron
schedules, a worker pool, a write-ahead log with snapshots for crash
recovery, metrics, an admin API and a CLI. Python 3.12, standard library only.

```python
from taskmill import Broker, BrokerConfig, WorkerPool, default_registry

broker = Broker("/var/lib/taskmill", BrokerConfig(visibility_timeout=30))
broker.enqueue("email", "send", {"to": "a@example.org"}, idempotency_key="order-17")

registry = default_registry()

@registry.register("send")
def send(ctx):
    ...  # ctx.payload, ctx.attempt, ctx.heartbeat()
    return {"sent": True}

with WorkerPool(broker, registry, concurrency=8):
    ...
```

CLI (`python3 -m taskmill --help`):

```
python3 -m taskmill enqueue DATA QUEUE KIND [--payload JSON] [--priority N] [--delay S] [--key K]
python3 -m taskmill list DATA [--queue Q] [--state S] [--json]
python3 -m taskmill stats DATA [--json]
python3 -m taskmill run DATA [--concurrency N] [--until-idle]
python3 -m taskmill recover DATA [--check]
python3 -m taskmill wal verify DATA | wal dump DATA
python3 -m taskmill backoff '{"kind": "exponential", "base": 1, "factor": 2, "max": 60}'
python3 -m taskmill cron '*/15 9-17 * * mon-fri'
python3 -m taskmill key 'Order 12'
python3 -m taskmill serve DATA [--port 8470]
```

Layout:

| module | what |
|---|---|
| `broker.py` | the Broker: enqueue, reserve, ack/nack/heartbeat, operator actions, checkpoints |
| `state.py` | in-memory state and the record appliers shared by live operations and replay |
| `job.py` | the Job record and its state machine |
| `pqueue.py` | per-queue ready/delay heaps and the reservation order |
| `leases.py` | lease tokens, deadlines, heartbeats |
| `idempotency.py` | idempotency key normalisation and the dedup index |
| `backoff.py` | retry backoff policies |
| `wal.py`, `snapshot.py`, `recovery.py` | durability: log, snapshots, crash recovery |
| `worker.py`, `handlers.py`, `reaper.py` | the worker pool, handler registry, lease reaper |
| `scheduler.py`, `cron.py` | cron and interval schedules |
| `metrics.py`, `tracing.py`, `report.py` | observability |
| `admin.py`, `client.py`, `cli.py`, `runtime.py` | operator interfaces |
| `bulk.py`, `deadletter.py`, `export.py` | bulk tooling |
| `resultcache.py` | reuse results of identical finished jobs |

Design notes are in `docs/DESIGN.md` (it links the per-topic documents);
the WAL format in `docs/WAL.md`; hook points in `docs/HOOKS.md`;
configuration in `docs/CONFIG.md`. Planned work: `docs/FAIRNESS.md`,
`docs/DOCTOR.md`.

Tests: `python3 -m pytest -q`.

Also: `workflow.py` (chains and fan-in groups of jobs), `notify.py`
(in-process completion notifications), `inspect.py` (offline look at a data
directory: `python3 -m taskmill inspect DATA [--job ID]`).

Open support escalations live in `support/`.
