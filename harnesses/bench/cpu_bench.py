#!/usr/bin/env python3
"""Local-CPU benchmark: Claude Code CLI vs Pi vs OMP on the same GenAI route and model.

    python3 bench/cpu_bench.py --out results/<run>/ [--plan pilot] [--model-alias haiku]

Every run is one JSON line in <out>/runs.jsonl. Per run we record:
  rusage_cpu_s   user+sys CPU of the harness process and every descendant it reaped (wait4)
  tree_cpu_s     user+sys CPU summed over the live process tree, sampled at 4 Hz (last value
                 seen per pid; catches descendants the harness never reaps, misses the tail of
                 short-lived ones)
  wall_s, peak_tree_rss_mb, maxrss_mb (largest single process), cpu_pct_samples (tree %CPU)
  ok             the task's own check passed (output contains the expected marker / file)
Nothing here names an account, host or model: the route comes from gen/genai_route.py.
Methodology and caveats: docs/METHOD.md.
"""
import argparse
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "gen"))
import genai_route as g  # noqa: E402
import make_configs as mc  # noqa: E402

ROOT = os.path.join(mc.storage_root(), "NewHarness")
PI_BIN = os.environ.get("NH_PI_BIN", os.path.join(ROOT, "build/pi/node_modules/.bin/pi"))
OMP_BIN = os.environ.get("NH_OMP_BIN", os.path.join(ROOT, "build/omp/node_modules/.bin/omp"))
CLAUDE_BIN = os.environ.get("NH_CLAUDE_BIN") or shutil.which("claude", path=os.path.expanduser("~/.local/bin"))
SAMPLE_S = 0.25

TASKS = {
    # name: (prompt, check(stdout, workdir) -> bool)
    "version": (None, lambda out, wd: bool(out.strip())),
    "pong": ("Reply with exactly the word PONG and nothing else.", lambda out, wd: "PONG" in out),
    "stream": ("Without using any tools, write the integers from 1 to 400, one per line, then the "
               "word DONE on its own line. Output nothing else.",
               lambda out, wd: "DONE" in out and "399" in out),
    "tools": ("Use your tools: read a.txt and b.txt in the current directory, each holds one integer. "
              "Write their sum (just the number) to c.txt. Then reply with the word FINISHED.",
              lambda out, wd: _read(os.path.join(wd, "c.txt")) == "579"),
}


def _read(p):
    try:
        with open(p) as fh:
            return fh.read().strip()
    except OSError:
        return None


TOKEN_REFRESH_S = 900


def fresh_token():
    """One bearer from Claude Code's own apiKeyHelper (bypassing bin/genai-token's cache), fetched
    outside any measured run, so token cost never lands on a harness."""
    out = subprocess.run([g.key_helper()], capture_output=True, text=True, check=True)
    tok = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
    if not tok:
        raise g.GenAIEnvMissing("apiKeyHelper returned no token")
    return tok


def clean_env(token):
    """Our own environment minus this session's Claude Code identity, plus the settings.json env."""
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"))}
    s = g.settings()
    env.update({k: str(v) for k, v in (s.get("env") or {}).items()})
    g.base_url(s)  # fail by name if missing
    env["NH_GENAI_TOKEN"] = token
    env["PI_SKIP_VERSION_CHECK"] = "1"
    env["PI_TELEMETRY"] = "0"
    env["OMP_SKIP_SETUP"] = "1"
    env["PI_NO_TITLE"] = "1"
    env["OTEL_SDK_DISABLED"] = "true"
    return env


def command(harness, profile, task, model, interactive=False):
    """argv and extra env for one harness/profile/task."""
    prompt = TASKS[task][0] if task in TASKS else None
    extra = {}
    if harness == "claude":
        argv = [CLAUDE_BIN]
        if task == "version":
            return argv + ["--version"], extra
        # Both profiles get the same token source as Pi/OMP (the pre-fetched bearer via
        # bin/genai-token), so no harness pays for a fresh the gateway's own token helper.
        helper = os.path.join(REPO, "bin", "genai-token")
        if profile == "bare":
            argv += ["--bare", "--strict-mcp-config"]
        # NH_CLAUDE_EXTRA_SETTINGS: JSON merged into the per-run --settings (e.g. pin a plugin
        # on or off for this bench only, without editing ~/.claude/settings.json).
        extra_settings = json.loads(os.environ.get("NH_CLAUDE_EXTRA_SETTINGS") or "{}")
        argv += ["--settings", json.dumps(dict(extra_settings, apiKeyHelper=helper))]
        argv += ["--model", model, "--dangerously-skip-permissions"]
        if not interactive:
            argv += ["-p", "--no-session-persistence", prompt]
        return argv, extra
    tagdir = mc.agent_dir(harness, profile, "-bench")
    extra["PI_CODING_AGENT_DIR"] = tagdir
    argv = [PI_BIN if harness == "pi" else OMP_BIN]
    if task == "version":
        return argv + ["--version"], extra
    argv += ["--model", "%s/%s" % (mc.PROVIDER, model)]
    if not interactive:
        argv += ["-p", "--no-session", prompt]
    return argv, extra


class TreeSampler(threading.Thread):
    def __init__(self, pid):
        super().__init__(daemon=True)
        self.root = pid
        self.last = {}          # pid -> (create_time, cpu_s)
        self.peak_rss = 0
        self.pct = []           # (t, tree cpu % over the last interval)
        self.nprocs = 0
        self.stop_ev = threading.Event()

    def total(self):
        return sum(c for _, c in self.last.values())

    def run(self):
        prev_t, prev_cpu = time.monotonic(), 0.0
        while not self.stop_ev.is_set():
            try:
                rootp = psutil.Process(self.root)
                procs = [rootp] + rootp.children(recursive=True)
            except psutil.Error:
                procs = []
            rss = 0
            for p in procs:
                try:
                    with p.oneshot():
                        ct = p.cpu_times()
                        self.last[p.pid] = (p.create_time(), ct.user + ct.system)
                        rss += p.memory_info().rss
                except psutil.Error:
                    pass
            self.nprocs = max(self.nprocs, len(procs))
            self.peak_rss = max(self.peak_rss, rss)
            now, cpu = time.monotonic(), self.total()
            if now > prev_t:
                self.pct.append((round(now, 3), round(100 * (cpu - prev_cpu) / (now - prev_t), 1)))
            prev_t, prev_cpu = now, cpu
            self.stop_ev.wait(SAMPLE_S)


def make_workdir(run_id):
    wd = os.path.join(ROOT, "scratch", "runs", run_id)
    os.makedirs(wd, exist_ok=True)
    with open(os.path.join(wd, "a.txt"), "w") as fh:
        fh.write("123\n")
    with open(os.path.join(wd, "b.txt"), "w") as fh:
        fh.write("456\n")
    return wd


def run_headless(harness, profile, task, model, env, run_id, timeout=240):
    wd = make_workdir(run_id)
    argv, extra = command(harness, profile, task, model)
    e = dict(env, **extra)
    t0 = time.monotonic()
    p = subprocess.Popen(argv, cwd=wd, env=e, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    s = TreeSampler(p.pid)
    s.start()
    out, err = [], []
    th = [threading.Thread(target=lambda f, b: b.append(f.read()), args=(p.stdout, out), daemon=True),
          threading.Thread(target=lambda f, b: b.append(f.read()), args=(p.stderr, err), daemon=True)]
    for t in th:
        t.start()
    deadline = t0 + timeout
    status = ru = None
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        if time.monotonic() > deadline:
            _kill_tree(p.pid)
            pid, status, ru = os.wait4(p.pid, 0)
            break
        time.sleep(0.05)
    wall = time.monotonic() - t0
    s.stop_ev.set()
    s.join()
    p.returncode = os.waitstatus_to_exitcode(status)
    for t in th:
        t.join(5)
    stdout = (out[0] if out else b"").decode(errors="replace")
    stderr = (err[0] if err else b"").decode(errors="replace")
    ok = TASKS[task][1](stdout, wd)
    return {"wall_s": round(wall, 3), "rusage_cpu_s": round(ru.ru_utime + ru.ru_stime, 3),
            "rusage_user_s": round(ru.ru_utime, 3), "rusage_sys_s": round(ru.ru_stime, 3),
            "maxrss_mb": round(ru.ru_maxrss / 2**20, 1),
            "tree_cpu_s": round(s.total(), 3), "peak_tree_rss_mb": round(s.peak_rss / 2**20, 1),
            "max_procs": s.nprocs, "rc": p.returncode, "ok": ok,
            "stdout_tail": stdout[-300:], "stderr_tail": stderr[-500:],
            "cpu_pct_samples": s.pct}


def _kill_tree(pid):
    try:
        procs = psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        procs = []
    for p in procs:
        try:
            p.kill()
        except psutil.Error:
            pass
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def run_interactive(harness, profile, model, env, run_id, settle_s, idle_s, prompt_task=None,
                    after_prompt_s=0):
    """Start the TUI in a 120x40 pty, let it settle, then measure CPU over an idle window
    (and optionally over a window after typing one prompt). Output is drained continuously."""
    wd = make_workdir(run_id)
    argv, extra = command(harness, profile, prompt_task or "pong", model, interactive=True)
    e = dict(env, **extra, TERM="xterm-256color", COLUMNS="120", LINES="40")
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(wd)
        os.execve(argv[0], argv, e)
    import fcntl
    import struct
    import termios
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    screen = bytearray()
    stop = threading.Event()

    def drain():
        while not stop.is_set():
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    b = os.read(fd, 65536)
                except OSError:
                    return
                if not b:
                    return
                screen.extend(b)
                if len(screen) > 400000:
                    del screen[:200000]
                # answer cursor-position queries so TUIs do not wait on them
                if b"\x1b[6n" in b:
                    os.write(fd, b"\x1b[40;1R")
    dt = threading.Thread(target=drain, daemon=True)
    dt.start()
    s = TreeSampler(pid)
    s.start()
    time.sleep(settle_s)
    c0, t0 = s.total(), time.monotonic()
    rss_settled = s.peak_rss
    time.sleep(idle_s)
    c1, t1 = s.total(), time.monotonic()
    res = {"settle_s": settle_s, "idle_s": round(t1 - t0, 2), "startup_cpu_s": round(c0, 3),
           "idle_cpu_s": round(c1 - c0, 3), "idle_cpu_pct": round(100 * (c1 - c0) / (t1 - t0), 2),
           "rss_settled_mb": round(rss_settled / 2**20, 1)}
    if prompt_task:
        os.write(fd, TASKS[prompt_task][0].encode())
        time.sleep(0.7)
        os.write(fd, b"\r")
        time.sleep(after_prompt_s)
        c2, t2 = s.total(), time.monotonic()
        res.update({"prompt_task": prompt_task, "prompt_window_s": round(t2 - t1, 2),
                    "prompt_cpu_s": round(c2 - c1, 3),
                    "prompt_ok": TASKS[prompt_task][1](bytes(screen).decode(errors="replace"), wd)})
    res["peak_tree_rss_mb"] = round(s.peak_rss / 2**20, 1)
    res["max_procs"] = s.nprocs
    res["alive_at_end"] = psutil.pid_exists(pid)
    res["screen_tail"] = bytes(screen[-1500:]).decode(errors="replace")
    res["cpu_pct_samples"] = s.pct
    stop.set()
    s.stop_ev.set()
    _kill_tree(pid)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    os.close(fd)
    return res


def concurrent(harness, profile, task, model, env, n, run_id):
    """N headless runs started together; per-run results plus the aggregate."""
    results = [None] * n
    ths = []
    for i in range(n):
        def go(i=i):
            results[i] = run_headless(harness, profile, task, model, env, "%s-%d" % (run_id, i))
        ths.append(threading.Thread(target=go))
    t0 = time.monotonic()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    wall = time.monotonic() - t0
    return {"n": n, "batch_wall_s": round(wall, 3),
            "sum_rusage_cpu_s": round(sum(r["rusage_cpu_s"] for r in results), 3),
            "sum_peak_rss_mb": round(sum(r["peak_tree_rss_mb"] for r in results), 1),
            "all_ok": all(r["ok"] for r in results),
            "per_run": [{k: v for k, v in r.items() if k != "cpu_pct_samples"} for r in results]}


CONFIGS = [("claude", "full"), ("claude", "bare"), ("pi", "bare"), ("omp", "bare"),
           ("pi", "full"), ("omp", "full")]


def plan_pilot(reps):
    steps = []
    for r in range(reps):
        for h, pr in CONFIGS:
            for task in ("version", "pong", "stream", "tools"):
                if task == "version" and pr == "full":
                    continue
                steps.append(("headless", h, pr, task, r))
    for r in range(2):
        for h, pr in CONFIGS:
            steps.append(("idle", h, pr, "stream", r))
    for h, pr in [("claude", "full"), ("claude", "bare"), ("pi", "bare"), ("omp", "bare")]:
        for n in (1, 2, 4, 8):
            steps.append(("concurrent", h, pr, "pong", n))
    return steps


def plan_cells(reps, configs):
    """n=reps per cell for one or more configs: headless pong/tools, TUI idle+stream, N=8 batch."""
    steps = []
    for r in range(reps):
        for h, pr in configs:
            steps += [("headless", h, pr, "pong", r), ("headless", h, pr, "tools", r),
                      ("idle", h, pr, "stream", r)]
    for r in range(reps):
        for h, pr in configs:
            steps.append(("concurrent", h, pr, "pong", 8))
    return steps


def machine_state():
    la = os.getloadavg()
    batt = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout.strip().splitlines()[-1:]
    top = sorted(((p.info["cpu_percent"] or 0, p.info["name"]) for p in psutil.process_iter(["cpu_percent", "name"])),
                 reverse=True)[:5]
    return {"loadavg": [round(x, 2) for x in la], "battery": batt, "top_now": top}


def versions():
    out = {}
    for name, b in (("claude", CLAUDE_BIN), ("pi", PI_BIN), ("omp", OMP_BIN)):
        try:
            out[name] = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=60,
                                       stdin=subprocess.DEVNULL).stdout.strip()[-80:]
        except Exception as exc:  # noqa: BLE001
            out[name] = "error: %s" % exc
    out["node"] = subprocess.run(["node", "-v"], capture_output=True, text=True).stdout.strip()
    out["bun"] = subprocess.run(["bun", "--version"], capture_output=True, text=True).stdout.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan", default="pilot", choices=["pilot", "smoke", "cells"])
    ap.add_argument("--configs", default="claude:full", help="cells plan: harness:profile,...")
    ap.add_argument("--label", default="")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model-alias", default="haiku")
    ap.add_argument("--idle-settle", type=float, default=20)
    ap.add_argument("--idle-window", type=float, default=45)
    ap.add_argument("--prompt-window", type=float, default=40)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for pr in ("bare", "full"):
        mc.main(["--profile", pr, "--token-env", "NH_GENAI_TOKEN"])
    model = g.models()[a.model_alias][0]
    env = clean_env(fresh_token())
    token_t = time.monotonic()
    meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model_alias": a.model_alias,
            "versions": versions(), "machine": machine_state(), "plan": a.plan, "reps": a.reps,
            "sample_s": SAMPLE_S, "cpu": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                                       capture_output=True, text=True).stdout.strip()}
    with open(os.path.join(a.out, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    meta["label"] = a.label
    cfgs = [tuple(c.split(":")) for c in a.configs.split(",")]
    meta["configs"] = cfgs
    steps = plan_pilot(a.reps) if a.plan == "pilot" else plan_cells(a.reps, cfgs) if a.plan == "cells" else [
        ("headless", h, pr, "pong", 0) for h, pr in CONFIGS] + [("idle", "pi", "bare", "stream", 0)]
    log = open(os.path.join(a.out, "runs.jsonl"), "a")
    for i, (kind, h, pr, task, r) in enumerate(steps):
        if time.monotonic() - token_t > TOKEN_REFRESH_S:
            env["NH_GENAI_TOKEN"], token_t = fresh_token(), time.monotonic()
        rid = "%s-%s-%s-%s-%s-%s" % (kind, h, pr, task, r, uuid.uuid4().hex[:6])
        t = time.time()
        try:
            if kind == "headless":
                res = run_headless(h, pr, task, model, env, rid)
            elif kind == "idle":
                res = run_interactive(h, pr, model, env, rid, a.idle_settle, a.idle_window,
                                      prompt_task=task, after_prompt_s=a.prompt_window)
            else:
                res = concurrent(h, pr, task, model, env, r, rid)
        except Exception as exc:  # noqa: BLE001
            res = {"error": repr(exc)}
        rec = {"i": i, "kind": kind, "harness": h, "profile": pr, "task": task, "rep_or_n": r,
               "t": round(t, 1), "loadavg": [round(x, 2) for x in os.getloadavg()], **res}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print("%d/%d %s %s-%s %s %s ok=%s cpu=%s" % (i + 1, len(steps), kind, h, pr, task, r,
              res.get("ok", res.get("all_ok", res.get("prompt_ok"))),
              res.get("rusage_cpu_s", res.get("sum_rusage_cpu_s", res.get("idle_cpu_pct")))), flush=True)
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["machine_end"] = machine_state()
    with open(os.path.join(a.out, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)


if __name__ == "__main__":
    main()
