import pathlib, sys, textwrap
R = pathlib.Path(sys.argv[1])
def w(rel, s):
    p = R / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(s).lstrip())
w("conftest.py", "")
w("relaylog/__init__.py", "")
w("relaylog/sim.py", '''
    """Deterministic event simulation for the replay fixture."""
    import random

    KINDS = ["connect", "disconnect", "auth", "auth_fail", "send", "recv", "ack", "nack", "retry",
             "throttle", "heartbeat", "gc", "rotate", "flush", "spill", "resume", "pause", "config",
             "quota", "drain"]


    def events(n=20000, seed=1234):
        rnd = random.Random(seed)
        t = 1_700_000_000.0
        for i in range(n):
            t += rnd.expovariate(20)
            kind = rnd.choices(KINDS, weights=[5, 5, 4, 1, 20, 20, 15, 2, 3, 2, 10, 1, 1, 3, 1, 1, 1, 1, 1, 1])[0]
            peer = f"node-{rnd.randint(1, 64):02d}"
            size = rnd.randint(0, 65535)
            ms = round(rnd.uniform(0.1, 900.0), 2)
            seq = i
            # a backoff schedule is only known once the server has suggested one
            delay = None if rnd.random() < 0.02 else rnd.randint(10, 5000)
            yield {"t": t, "kind": kind, "peer": peer, "size": size, "ms": ms, "seq": seq,
                   "delay": delay, "attempt": rnd.randint(1, 6), "user": rnd.choice(["svc", "ops", "relay", "backup"])}
    ''')
fmts = {
 "connect":    ('INFO',  '"peer": %s, "seq": %d', 'q(e["peer"]), e["seq"]'),
 "disconnect": ('INFO',  '"peer": %s, "seq": %d, "ms": %s', 'q(e["peer"]), e["seq"], e["ms"]'),
 "auth":       ('INFO',  '"peer": %s, "user": %s', 'q(e["peer"]), q(e["user"])'),
 "auth_fail":  ('WARN',  '"peer": %s, "user": %s, "attempt": %d', 'q(e["peer"]), q(e["user"]), e["attempt"]'),
 "send":       ('DEBUG', '"peer": %s, "bytes": %d, "ms": %s', 'q(e["peer"]), e["size"], e["ms"]'),
 "recv":       ('DEBUG', '"peer": %s, "bytes": %d, "ms": %s', 'q(e["peer"]), e["size"], e["ms"]'),
 "ack":        ('DEBUG', '"seq": %d, "ms": %s', 'e["seq"], e["ms"]'),
 "nack":       ('WARN',  '"seq": %d, "peer": %s', 'e["seq"], q(e["peer"])'),
 "retry":      ('WARN',  '"seq": %d, "attempt": %d, "delay_ms": %s', 'e["seq"], e["attempt"], e["delay"]'),
 "throttle":   ('WARN',  '"peer": %s, "delay_ms": %s', 'q(e["peer"]), num(e["delay"])'),
 "heartbeat":  ('DEBUG', '"peer": %s, "ms": %s', 'q(e["peer"]), e["ms"]'),
 "gc":         ('INFO',  '"freed": %d', 'e["size"]'),
 "rotate":     ('INFO',  '"bytes": %d', 'e["size"]'),
 "flush":      ('DEBUG', '"bytes": %d, "ms": %s', 'e["size"], e["ms"]'),
 "spill":      ('WARN',  '"bytes": %d', 'e["size"]'),
 "resume":     ('INFO',  '"peer": %s, "delay_ms": %s', 'q(e["peer"]), num(e["delay"])'),
 "pause":      ('INFO',  '"peer": %s', 'q(e["peer"])'),
 "config":     ('INFO',  '"user": %s', 'q(e["user"])'),
 "quota":      ('WARN',  '"user": %s, "bytes": %d', 'q(e["user"]), e["size"]'),
 "drain":      ('INFO',  '"peer": %s, "ms": %s', 'q(e["peer"]), e["ms"]'),
}
body = ['"""Line formatters: one per event kind. Hot path, so no json.dumps per record."""',
        'import datetime', '', '',
        'def q(s):', '    return \'"\' + str(s).replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\') + \'"\'', '', '',
        'def num(x):', '    return "null" if x is None else repr(x)', '', '',
        'def ts(t):', '    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")', '', '']
for k, (lvl, f, a) in fmts.items():
    body += [f'def fmt_{k}(e):', f"    return '%s {lvl} {{\"kind\": \"{k}\", {f}}}' % (ts(e[\"t\"]), {a})", '', '']
body += ['FORMATTERS = {', *[f'    "{k}": fmt_{k},' for k in fmts], '}', '']
(R / "relaylog/formatters.py").write_text("\n".join(body))
w("tools/replay.py", '''
    """Replay the simulated relay session and print the event log (one record per line)."""
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    from relaylog.formatters import FORMATTERS
    from relaylog.sim import events


    def main():
        out = sys.stdout
        for e in events():
            out.write(FORMATTERS[e["kind"]](e) + "\\n")
        return 0


    if __name__ == "__main__":
        sys.exit(main())
    ''')
