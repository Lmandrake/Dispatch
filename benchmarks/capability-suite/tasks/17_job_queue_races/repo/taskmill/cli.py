"""Command-line interface: ``python3 -m taskmill <command> ...``.

    enqueue DATA QUEUE KIND [--payload JSON] [--priority N] [--delay S] [--key K]
                            [--max-attempts N] [--tag T ...]
    list    DATA [--queue Q] [--state S] [--json]
    show    DATA JOB_ID
    order   DATA QUEUE
    cancel  DATA JOB_ID
    retry   DATA JOB_ID
    stats   DATA [--json]
    run     DATA [--concurrency N] [--queue Q ...] [--until-idle] [--timeout S]
    recover DATA [--check]
    checkpoint DATA
    wal verify DATA
    wal dump DATA [--limit N]
    backoff SPEC_JSON [--attempts N] [--job-id ID]
    cron    EXPR [--after T] [--count N]
    key     KEY...                 show normalised idempotency keys
    inspect DATA [--job ID]        offline summary of snapshots and WAL (or one job's records)
    dead    DATA [--queue Q]       failed jobs grouped by error
    serve   DATA [--host H] [--port P]

DATA is a data directory (created if missing). Exit status: 0 success, 1 a
taskmill error (message on stderr), 2 usage error.
"""

import argparse
import json
import sys
import time

from . import codec
from .errors import TaskmillError

STATE_ORDER = ("pending", "delayed", "reserved", "done", "failed", "cancelled")


def _broker(data_dir):
    from .broker import Broker
    from .runtime import load_config
    return Broker(data_dir, load_config(data_dir))


def _print_json(doc) -> None:
    print(json.dumps(doc, sort_keys=True, indent=2))


def cmd_enqueue(a) -> int:
    payload = json.loads(a.payload) if a.payload is not None else None
    with _broker(a.data) as b:
        res = b.enqueue(a.queue, a.kind, payload, priority=a.priority, delay=a.delay,
                        idempotency_key=a.key, max_attempts=a.max_attempts, tags=a.tag)
    print(f"{res.job_id} {'created' if res.created else 'existing'}")
    return 0


def cmd_list(a) -> int:
    with _broker(a.data) as b:
        jobs = b.jobs(queue=a.queue, state=a.state)
    if a.json:
        _print_json([j.summary() for j in jobs])
        return 0
    for j in jobs:
        print(f"{j.id:<12} {j.queue:<12} {j.kind:<12} {j.state:<9} p{j.priority} a{j.attempts}/{j.max_attempts}")
    print(f"{len(jobs)} job(s)")
    return 0


def cmd_show(a) -> int:
    with _broker(a.data) as b:
        d = b.get(a.job_id).to_dict()
    if d.get("lease_token"):
        d["lease_token"] = d["lease_token"][:6] + "..."
    _print_json(d)
    return 0


def cmd_order(a) -> int:
    with _broker(a.data) as b:
        for job_id in b.order(a.queue):
            print(job_id)
    return 0


def cmd_cancel(a) -> int:
    with _broker(a.data) as b:
        ok = b.cancel(a.job_id)
    print("cancelled" if ok else "already finished")
    return 0


def cmd_retry(a) -> int:
    with _broker(a.data) as b:
        b.retry(a.job_id)
    print("pending")
    return 0


def cmd_stats(a) -> int:
    with _broker(a.data) as b:
        st = b.stats()
        per_queue = {q: b.queue_stats(q) for q in b.queue_names()}
    if a.json:
        _print_json({"broker": st, "queues": per_queue})
        return 0
    print(f"jobs {st['jobs']}  leases {st['leases']}  keys {st['idempotency_keys']}  last seq {st['last_seq']}")
    for q, c in per_queue.items():
        flags = " (paused)" if c["paused"] else ""
        counts = " ".join(f"{s}={c[s]}" for s in STATE_ORDER)
        print(f"  {q}{flags}: {counts}")
    return 0


def cmd_run(a) -> int:
    from .runtime import Runtime
    rt = Runtime(a.data, concurrency=a.concurrency, queues=a.queue or None)
    rt.start()
    try:
        if a.until_idle:
            ok = rt.pool.drain(timeout=a.timeout, queues=a.queue or None)
            if not ok:
                print("timed out waiting for the queue to drain", file=sys.stderr)
                return 1
        else:
            end = time.monotonic() + a.timeout
            while time.monotonic() < end:
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop()
    st = rt.broker.stats()
    print(" ".join(f"{s}={st['states'][s]}" for s in STATE_ORDER))
    return 0


def cmd_recover(a) -> int:
    if a.check:
        from .recovery import check
        from .runtime import load_config
        _print_json(check(a.data, load_config(a.data)))
        return 0
    with _broker(a.data) as b:
        print(b.recovery.summary())
    return 0


def cmd_checkpoint(a) -> int:
    with _broker(a.data) as b:
        path = b.checkpoint()
    print(path)
    return 0


def cmd_wal(a) -> int:
    import os
    from . import wal
    directory = os.path.join(a.data, "wal")
    if a.wal_cmd == "verify":
        rep = wal.verify(directory)
        _print_json(rep)
        return 0 if rep["ok"] else 1
    res = wal.scan(directory)
    recs = res.records if a.limit is None else res.records[: a.limit]
    for r in recs:
        print(codec.dumps(r))
    if res.torn:
        print(f"# torn tail: {res.torn.reason} at byte {res.torn.offset} of {os.path.basename(res.torn.path)}",
              file=sys.stderr)
    return 0


def cmd_backoff(a) -> int:
    from .backoff import parse_backoff
    bo = parse_backoff(json.loads(a.spec))
    print(bo.describe())
    for i, d in enumerate(bo.schedule(a.attempts, a.job_id), start=1):
        print(f"attempt {i}: {d:.3f}s")
    return 0


def cmd_cron(a) -> int:
    from .cron import format_slot, parse_cron
    expr = parse_cron(a.expr)
    for t in expr.upcoming(a.after, a.count):
        print(f"{format_slot(t)}  {int(t)}")
    return 0


def cmd_key(a) -> int:
    from .idempotency import normalize_key
    for k in a.keys:
        print(f"{k!r} -> {normalize_key(k)!r}")
    return 0


def cmd_inspect(a) -> int:
    from . import inspect as insp
    if a.job:
        sys.stdout.write(insp.render_history(insp.job_history(a.data, a.job)))
        return 0
    doc = insp.describe(a.data)
    _print_json(doc)
    return 1 if doc["error"] else 0


def cmd_dead(a) -> int:
    from . import deadletter
    with _broker(a.data) as b:
        sys.stdout.write(deadletter.render(b, a.queue))
    return 0


def cmd_serve(a) -> int:
    from .admin import AdminApp, serve
    from .runtime import Runtime
    from .tracing import Tracer
    rt = Runtime(a.data, concurrency=a.concurrency).start()
    tracer = Tracer(rt.broker).install()
    srv = serve(AdminApp(rt.broker, tracer), a.host, a.port)
    print(f"serving on http://{a.host}:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        rt.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskmill", description="threaded job queue")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("enqueue")
    s.add_argument("data")
    s.add_argument("queue")
    s.add_argument("kind")
    s.add_argument("--payload")
    s.add_argument("--priority", type=int)
    s.add_argument("--delay", type=float)
    s.add_argument("--key")
    s.add_argument("--max-attempts", type=int)
    s.add_argument("--tag", action="append")
    s.set_defaults(fn=cmd_enqueue)

    s = sub.add_parser("list")
    s.add_argument("data")
    s.add_argument("--queue")
    s.add_argument("--state", choices=STATE_ORDER)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_list)

    for name, fn in (("show", cmd_show), ("cancel", cmd_cancel), ("retry", cmd_retry)):
        s = sub.add_parser(name)
        s.add_argument("data")
        s.add_argument("job_id")
        s.set_defaults(fn=fn)

    s = sub.add_parser("order")
    s.add_argument("data")
    s.add_argument("queue")
    s.set_defaults(fn=cmd_order)

    s = sub.add_parser("stats")
    s.add_argument("data")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("run")
    s.add_argument("data")
    s.add_argument("--concurrency", type=int, default=4)
    s.add_argument("--queue", action="append")
    s.add_argument("--until-idle", action="store_true")
    s.add_argument("--timeout", type=float, default=30.0)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("recover")
    s.add_argument("data")
    s.add_argument("--check", action="store_true")
    s.set_defaults(fn=cmd_recover)

    s = sub.add_parser("checkpoint")
    s.add_argument("data")
    s.set_defaults(fn=cmd_checkpoint)

    s = sub.add_parser("wal")
    s.add_argument("wal_cmd", choices=("verify", "dump"))
    s.add_argument("data")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_wal)

    s = sub.add_parser("backoff")
    s.add_argument("spec")
    s.add_argument("--attempts", type=int, default=5)
    s.add_argument("--job-id", default="")
    s.set_defaults(fn=cmd_backoff)

    s = sub.add_parser("cron")
    s.add_argument("expr")
    s.add_argument("--after", type=float, default=0.0)
    s.add_argument("--count", type=int, default=5)
    s.set_defaults(fn=cmd_cron)

    s = sub.add_parser("key")
    s.add_argument("keys", nargs="+")
    s.set_defaults(fn=cmd_key)

    s = sub.add_parser("inspect")
    s.add_argument("data")
    s.add_argument("--job")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("dead")
    s.add_argument("data")
    s.add_argument("--queue")
    s.set_defaults(fn=cmd_dead)

    s = sub.add_parser("serve")
    s.add_argument("data")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8470)
    s.add_argument("--concurrency", type=int, default=4)
    s.set_defaults(fn=cmd_serve)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    try:
        return a.fn(a)
    except TaskmillError as exc:
        print(f"taskmill: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"taskmill: invalid JSON: {exc.msg}", file=sys.stderr)
        return 1
