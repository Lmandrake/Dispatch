import datetime as dt, json, math, pathlib, random, sys
R = pathlib.Path(sys.argv[1]); H = pathlib.Path(sys.argv[2])
rnd = random.Random(9)
UTC = dt.timezone.utc
SERVICES = ["api", "auth", "db", "cache", "worker", "billing"]
LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
t = dt.datetime(2026, 3, 1, 23, 50, 0, tzinfo=UTC)
lines, recs = [], []
corrupt = 0
for i in range(3000):
    t += dt.timedelta(seconds=rnd.randint(0, 9))
    r = rnd.random()
    if r < 0.06:
        corrupt += 1
        lines.append(rnd.choice([
            '{"ts": "2026-03-02 01:00:00", "level": "info", "service": "api", "msg": "trunc',
            "\x00\x07garbage\x1b[0m ###",
            "2026-03-02T00:00:00Z [FATAL] api: unknown level here",
            '{"ts": "not-a-date", "level": "info", "service": "db", "msg": "x"}',
            '{"level": "info", "service": "db", "msg": "no ts"}',
            "Mar 99 12:00:00 host1 api[1]: INFO bad day",
            "2026-13-01T00:00:00Z [INFO] api: bad month",
            "-- MARK --",
            '["not", "an", "object"]',
        ]))
        continue
    if r < 0.08:
        lines.append(rnd.choice(["", "   ", "\t"]))
        continue
    lvl = rnd.choices(LEVELS, [3, 6, 2, 1])[0]
    svc = rnd.choice(SERVICES)
    lat = rnd.randint(1, 2500) if rnd.random() < 0.6 else None
    fmt = rnd.choice("ABC")
    if fmt == "A":
        lv = lvl if lvl != "WARN" or rnd.random() < 0.5 else "WARNING"
        s = f"{t:%Y-%m-%dT%H:%M:%SZ} [{lv}] {svc}: event {i} done"
        if lat is not None:
            s += f" latency={lat}ms"
    elif fmt == "B":
        d = {"ts": f"{t:%Y-%m-%d %H:%M:%S}", "level": rnd.choice([lvl.lower(), lvl.title()]) if lvl != "WARN" else rnd.choice(["warn", "warning"]),
             "service": svc, "msg": f"event {i}"}
        if lat is not None:
            d["latency_ms"] = lat
        if rnd.random() < 0.3:
            d["extra"] = {"k": rnd.randint(1, 9)}
        s = json.dumps(d)
    else:
        s = f"{MON[t.month-1]} {t.day:>2} {t:%H:%M:%S} host{rnd.randint(1,4)} {svc}[{rnd.randint(100,999)}]: {lvl} event {i}"
        if lat is not None:
            s += f" latency={lat/1000:.3f}s"
    lines.append(s)
    recs.append((t, lvl, svc, lat))
(R / "logs").mkdir(parents=True, exist_ok=True)
(R / "logs/app.log").write_text("\n".join(lines) + "\n")
lats = sorted(x[3] for x in recs if x[3] is not None)
def p95(v):
    return v[math.ceil(0.95 * len(v)) - 1]
errs = {}
for x in recs:
    if x[1] == "ERROR":
        errs[x[2]] = errs.get(x[2], 0) + 1
truth = {
    "total_lines": len(recs) + corrupt, "parsed": len(recs), "corrupt": corrupt,
    "by_level": {l: sum(1 for x in recs if x[1] == l) for l in LEVELS},
    "by_service": {s: sum(1 for x in recs if x[2] == s) for s in sorted(SERVICES)},
    "latency_ms": {"count": len(lats), "min": float(lats[0]), "max": float(lats[-1]),
                   "mean": round(sum(lats) / len(lats), 2), "p95": float(p95(lats))},
    "first_ts": f"{min(x[0] for x in recs):%Y-%m-%dT%H:%M:%SZ}",
    "last_ts": f"{max(x[0] for x in recs):%Y-%m-%dT%H:%M:%SZ}",
    "top_errors": [[s, c] for s, c in sorted(errs.items(), key=lambda kv: (-kv[1], kv[0]))[:3]],
}
(H / "hidden_truth.json").write_text(json.dumps(truth, indent=1))
print(json.dumps(truth)[:400])
