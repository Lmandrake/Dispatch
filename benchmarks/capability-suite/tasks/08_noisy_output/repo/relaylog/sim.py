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
