#!/usr/bin/env python3
"""Capability benchmark: the same coding tasks, same model, same thinking level, on Claude Code,
Pi and OMP. Pass/fail is decided by hidden pytest files copied in after the agent exits.

    python3 bench/capability_bench.py --out <agent-storage>/NewHarness/runs/<name> \
        [--arms claude-stock,pi-bare,omp-bare] [--tasks all] [--reps 3] [--jobs 6] [--model-alias sonnet]

Arms (bare/stock arms differ only in harness; full arms add the operator's own configuration):
  claude-stock  Claude Code with an empty CLAUDE_CONFIG_DIR and CLAUDE.md loading disabled: its
                default tool set, no hooks, plugins, MCP or instructions
  claude-bare   claude --bare (Bash, Edit, Read only)
  pi-bare / omp-bare  route only, each harness's own default tools
  claude-full   Claude Code with the operator's own Claude Code configuration (instructions, hooks, skills, plugins, MCP)
  pi-full / omp-full  CLAUDE.md as AGENTS.md, ~/.claude/skills, MCP from ~/.claude.json
Full arms get FULL_PREAMBLE before the task prompt: an operator CLAUDE.md may tell a session to ask a
clarifying question first, which stalls a headless run.
One JSON line per run in runs.jsonl. Order is balanced: every rep visits the arms in a rotated
order, so no arm always starts first or always runs under the heaviest concurrent load.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cpu_bench as cb  # noqa: E402

TASKS_DIR = os.environ.get("NH_TASKS_DIR") or os.path.join(HERE, "tasks")
STOCK_DIR = os.path.join(cb.ROOT, "agents", "claude-stock")
ARMS = ["claude-stock", "pi-bare", "omp-bare"]
FULL_PREAMBLE = "This is a throwaway session: do not ask, just do the task below.\n\n"


def argv_for(arm, model, prompt, thinking):
    if arm.startswith("claude"):
        helper = os.path.join(cb.REPO, "bin", "genai-token")
        argv = [cb.CLAUDE_BIN]
        if arm == "claude-bare":
            argv += ["--bare"]
        if arm != "claude-full":
            argv += ["--strict-mcp-config"]
        argv += ["--settings", json.dumps({"apiKeyHelper": helper}),
                 "--model", model, "--effort", thinking, "--dangerously-skip-permissions",
                 "-p", "--no-session-persistence", "--output-format", "stream-json", "--verbose", prompt]
        # An empty CLAUDE_CONFIG_DIR still loads ~/.claude/CLAUDE.md (verified 2026-10-23: runs
        # stopped to ask a clarifying question); CLAUDE_CODE_DISABLE_CLAUDE_MDS drops it.
        extra = {"CLAUDE_CONFIG_DIR": STOCK_DIR, "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"} \
            if arm == "claude-stock" else {}
        return argv, extra
    harness, profile = arm.split("-")[:2]
    extra = {"PI_CODING_AGENT_DIR": cb.mc.agent_dir(harness, profile, "-bench")}
    argv = [cb.PI_BIN if harness == "pi" else cb.OMP_BIN, "--model", "%s/%s" % (cb.mc.PROVIDER, model),
            "--thinking", thinking, "-p", "--no-session", "--mode", "json"]
    # "-stdin" arms pipe the prompt in: on this Mac some long prompts passed as argv get node
    # SIGKILLed before it starts (docs/CAPABILITY-2026-10-23.md)
    return (argv if piped(arm) else argv + [prompt]), extra


def piped(arm):
    # pi/omp full arms carry the preamble, so their prompts go on stdin too
    return arm.endswith("-stdin") or (arm.endswith("-full") and not arm.startswith("claude"))


def parse_claude(out):
    r = {"turns": 0, "tool_calls": 0, "tools": {}, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "assistant":
            for c in d["message"].get("content", []):
                if c.get("type") == "tool_use":
                    r["tool_calls"] += 1
                    r["tools"][c["name"]] = r["tools"].get(c["name"], 0) + 1
        elif d.get("type") == "result":
            u = d.get("usage") or {}
            r.update({"turns": d.get("num_turns", 0), "in": u.get("input_tokens", 0),
                      "out": u.get("output_tokens", 0), "cache_read": u.get("cache_read_input_tokens", 0),
                      "cache_write": u.get("cache_creation_input_tokens", 0),
                      "final": (d.get("result") or "")[-300:], "is_error": d.get("is_error")})
    return r


def parse_pi(out):
    r = {"turns": 0, "tool_calls": 0, "tools": {}, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "message_end" or d["message"].get("role") != "assistant":
            continue
        m = d["message"]
        r["turns"] += 1
        for c in m.get("content", []):
            if isinstance(c, dict) and c.get("type") == "toolCall":
                r["tool_calls"] += 1
                r["tools"][c.get("name")] = r["tools"].get(c.get("name"), 0) + 1
        u = m.get("usage") or {}
        r["in"] += u.get("input", 0)
        r["out"] += u.get("output", 0)
        r["cache_read"] += u.get("cacheRead", 0)
        r["cache_write"] += u.get("cacheWrite", 0)
        texts = [c.get("text", "") for c in m.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            r["final"] = "".join(texts)[-300:]
        if m.get("stopReason") == "error" or m.get("errorMessage"):
            r["is_error"] = m.get("errorMessage") or True
    return r


def grade(task, wd):
    hidden = os.path.join(TASKS_DIR, task, "hidden")
    for f in os.listdir(hidden):
        src = os.path.join(hidden, f)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(wd, f))
    files = sorted(f for f in os.listdir(hidden) if f.startswith("hidden_test_"))
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files],
                       cwd=wd, capture_output=True, text=True, timeout=600)
    tail = p.stdout.strip().splitlines()[-1:] or [""]
    return p.returncode == 0, tail[0][-200:]


def run_one(arm, task, rep, model, thinking, env, out_dir, timeout):
    rid = "%s-%s-%d-%s" % (task, arm, rep, uuid.uuid4().hex[:6])
    wd = os.path.join(cb.ROOT, "scratch", "cap", rid)
    shutil.copytree(os.path.join(TASKS_DIR, task, "repo"), wd)
    prompt = open(os.path.join(TASKS_DIR, task, "prompt.txt")).read().strip()
    if "-full" in arm:
        prompt = FULL_PREAMBLE + prompt
    argv, extra = argv_for(arm, model, prompt, thinking)
    e = dict(env, **extra)
    t0 = time.monotonic()
    pipe = piped(arm)
    p = subprocess.Popen(argv, cwd=wd, env=e, stdin=subprocess.PIPE if pipe else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if pipe:
        p.stdin.write(prompt.encode())
        p.stdin.close()
    s = cb.TreeSampler(p.pid)
    s.start()
    out, err = [], []
    th = [threading.Thread(target=lambda f, b: b.append(f.read()), args=(p.stdout, out), daemon=True),
          threading.Thread(target=lambda f, b: b.append(f.read()), args=(p.stderr, err), daemon=True)]
    for t in th:
        t.start()
    timed_out = False
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        if time.monotonic() - t0 > timeout:
            timed_out = True
            cb._kill_tree(p.pid)
            pid, status, ru = os.wait4(p.pid, 0)
            break
        time.sleep(0.1)
    wall = time.monotonic() - t0
    s.stop_ev.set()
    s.join()
    for t in th:
        t.join(5)
    stdout = (out[0] if out else b"").decode(errors="replace")
    stderr = (err[0] if err else b"").decode(errors="replace")
    with open(os.path.join(out_dir, "transcripts", rid + ".jsonl"), "w") as fh:
        fh.write(stdout)
    stats = parse_claude(stdout) if arm.startswith("claude") else parse_pi(stdout)
    try:
        passed, pytest_tail = grade(task, wd)
    except subprocess.TimeoutExpired:
        passed, pytest_tail = False, "pytest timeout"
    return {"run_id": rid, "task": task, "arm": arm, "rep": rep, "model": model, "thinking": thinking,
            "passed": passed, "pytest": pytest_tail, "timed_out": timed_out,
            "rc": os.waitstatus_to_exitcode(status), "wall_s": round(wall, 1),
            "cpu_s": round(ru.ru_utime + ru.ru_stime, 2), "peak_rss_mb": round(s.peak_rss / 2**20, 1),
            "stderr_tail": stderr[-3000:], "workdir": wd, **stats}


def plan(tasks, arms, reps):
    steps = []
    for rep in range(reps):
        for i, task in enumerate(tasks):
            k = (rep + i) % len(arms)
            for arm in arms[k:] + arms[:k]:
                steps.append((arm, task, rep))
    return steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--tasks", default="all")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--model-alias", default="sonnet")
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--timeout", type=float, default=900)
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "transcripts"), exist_ok=True)
    os.makedirs(STOCK_DIR, exist_ok=True)
    arms = a.arms.split(",")
    for pr in sorted({arm.split("-")[1] for arm in arms if not arm.startswith("claude")}):
        cb.mc.main(["--profile", pr, "--token-env", "NH_GENAI_TOKEN"])
    tasks = sorted(d for d in os.listdir(TASKS_DIR) if os.path.isdir(os.path.join(TASKS_DIR, d))) \
        if a.tasks == "all" else a.tasks.split(",")
    model = cb.g.models()[a.model_alias][0]
    env = cb.clean_env(cb.fresh_token())
    env_lock, token_t = threading.Lock(), [time.monotonic()]
    steps = plan(tasks, arms, a.reps)
    meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model, "thinking": a.thinking,
            "arms": arms, "tasks": tasks, "reps": a.reps, "jobs": a.jobs, "versions": cb.versions(),
            "machine": cb.machine_state()}
    json.dump(meta, open(os.path.join(a.out, "meta.json"), "w"), indent=2)
    log = open(os.path.join(a.out, "runs.jsonl"), "a")
    log_lock, done = threading.Lock(), [0]

    def go(step):
        arm, task, rep = step
        with env_lock:
            if time.monotonic() - token_t[0] > cb.TOKEN_REFRESH_S:
                env["NH_GENAI_TOKEN"], token_t[0] = cb.fresh_token(), time.monotonic()
            e = dict(env)
        try:
            rec = run_one(arm, task, rep, model, a.thinking, e, a.out, a.timeout)
        except Exception as exc:  # noqa: BLE001
            rec = {"task": task, "arm": arm, "rep": rep, "error": repr(exc), "passed": False}
        with log_lock:
            log.write(json.dumps(rec) + "\n")
            log.flush()
            done[0] += 1
            print("%d/%d %s %s r%d passed=%s wall=%s cpu=%s" % (done[0], len(steps), task, arm, rep,
                  rec.get("passed"), rec.get("wall_s"), rec.get("cpu_s")), flush=True)

    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(go, steps))
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["machine_end"] = cb.machine_state()
    json.dump(meta, open(os.path.join(a.out, "meta.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
