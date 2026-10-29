#!/usr/bin/env python3
"""Count real invocations of plugin skills/commands/agents and MCP tools in Claude Code transcripts.

    python3 bench/usage_scan.py INVENTORY.json OUT.json [--days 60]

Evidence = assistant tool_use blocks (Skill.skill, Agent/Task.subagent_type, mcp__<server>__* tool
names) and user-typed slash commands (<command-name>/x</command-name>). Mentions in prose do not
count. Plugin skills appear as "<plugin>:<skill>"; bare "<skill>" also credited when unique to it.
Reads ~/.claude/projects/**/*.jsonl modified in the window; per-record timestamps decide last-used.
"""
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict

CMD = re.compile(r"<command-name>/?([^<\s]+)</command-name>")


def main(inv_path, out, days=60):
    inv = json.load(open(inv_path))
    cutoff = time.time() - days * 86400
    skills, agents, mcp, cmds = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    files = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True)
             if os.path.getmtime(f) >= cutoff]
    for f in files:
        try:
            fh = open(f, errors="replace")
        except OSError:
            continue
        for line in fh:
            if '"tool_use"' not in line and "command-name" not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ts = r.get("timestamp") or ""
            msg = r.get("message") or {}
            content = msg.get("content")
            if r.get("type") == "user":
                text = content if isinstance(content, str) else " ".join(
                    c.get("text", "") for c in content or [] if isinstance(c, dict))
                for m in CMD.findall(text or ""):
                    cmds[m].append(ts)
                continue
            if r.get("type") != "assistant" or not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name, inp = c.get("name", ""), c.get("input") or {}
                if name == "Skill":
                    skills[str(inp.get("skill", ""))].append(ts)
                elif name in ("Agent", "Task"):
                    agents[str(inp.get("subagent_type", ""))].append(ts)
                elif name.startswith("mcp__"):
                    mcp[name.split("__")[1]].append(ts)
    def agg(d):
        return {k: {"n": len(v), "last": max(v) if v else ""} for k, v in d.items()}
    S, A, M, C = agg(skills), agg(agents), agg(mcp), agg(cmds)
    per_plugin = {}
    for pname, p in inv.items():
        short = p["short"]
        hits = []
        for s in p["skills"]:
            for key in ("%s:%s" % (short, s), s):
                if key in S:
                    hits.append(("skill", key, S[key]))
        for c in p["commands"]:
            for key in ("%s:%s" % (short, c),):
                if key in S:
                    hits.append(("skill-cmd", key, S[key]))
                if key in C:
                    hits.append(("slash", key, C[key]))
        for a in p["agents"]:
            for key in ("%s:%s" % (short, a),):
                if key in A:
                    hits.append(("agent", key, A[key]))
        for m in p["mcp"]:
            for key in M:
                if key == m or key.endswith("_" + m) or key == "plugin_%s_%s" % (short, m):
                    hits.append(("mcp", key, M[key]))
        per_plugin[pname] = {"n": sum(h[2]["n"] for h in hits),
                             "last": max((h[2]["last"] for h in hits), default=""),
                             "hits": [[h[0], h[1], h[2]["n"], h[2]["last"]] for h in hits]}
    json.dump({"days": days, "files": len(files), "per_plugin": per_plugin, "mcp_servers": M,
               "skills": S, "agents": A, "slash": C}, open(out, "w"), indent=1)
    print(out, len(files), "files")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(a[0], a[1], int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 60)
