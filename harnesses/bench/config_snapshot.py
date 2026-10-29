#!/usr/bin/env python3
"""Snapshot the Claude Code config a benchmark ran under (no secrets): version, enabled plugins,
MCP servers (claude mcp list, ~/.claude.json user + project scopes, plugin-provided), hook count,
skills count, load average, battery.   python3 bench/config_snapshot.py OUT.json
"""
import glob
import json
import os
import subprocess
import sys

H = os.path.expanduser


def run(argv, timeout=120):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return (p.stdout + p.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return "error: %r" % exc


def main(out):
    s = json.load(open(H("~/.claude/settings.json")))
    cj = json.load(open(H("~/.claude.json")))
    ep = s.get("enabledPlugins") or {}
    installed = json.load(open(H("~/.claude/plugins/installed_plugins.json"))).get("plugins", {})
    plugin_mcp, plugin_hooks = {}, {}
    for name, rows in installed.items():
        for row in rows:
            ip = row.get("installPath", "")
            for f in (os.path.join(ip, ".mcp.json"), os.path.join(ip, ".claude-plugin", "plugin.json")):
                try:
                    d = json.load(open(f))
                except (OSError, ValueError):
                    continue
                m = d.get("mcpServers")
                if isinstance(m, dict) and m:
                    plugin_mcp[name] = sorted(m)
            hf = os.path.join(ip, "hooks", "hooks.json")
            if os.path.exists(hf):
                try:
                    hk = json.load(open(hf)).get("hooks", {})
                    plugin_hooks[name] = sum(len(x.get("hooks", [])) for v in hk.values() for x in v)
                except (OSError, ValueError):
                    plugin_hooks[name] = "unreadable"
    env = dict(os.environ)
    for k in [k for k in env if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE",)]:
        env.pop(k)
    mcp_list = subprocess.run([H("~/.local/bin/claude"), "mcp", "list"], capture_output=True, text=True,
                              timeout=180, env=env, cwd=H("~"), stdin=subprocess.DEVNULL)
    snap = {
        "claude_version": run([H("~/.local/bin/claude"), "--version"]),
        "enabled_plugins": sorted(k for k, v in ep.items() if v),
        "disabled_plugins": sorted(k for k, v in ep.items() if not v),
        "installed_plugins": sorted(installed),
        "plugin_provided_mcp": plugin_mcp,
        "plugin_hooks": plugin_hooks,
        "settings_hooks_by_event": {ev: sum(len(a.get("hooks", [])) for a in arr) for ev, arr in (s.get("hooks") or {}).items()},
        "settings_hook_count": sum(len(a.get("hooks", [])) for arr in (s.get("hooks") or {}).values() for a in arr),
        "user_mcp_servers": {k: {kk: v.get(kk) for kk in ("type", "command", "args", "url") if kk in v}
                             for k, v in (cj.get("mcpServers") or {}).items()},
        "project_mcp_servers": {p: sorted(v.get("mcpServers") or {}) for p, v in (cj.get("projects") or {}).items() if v.get("mcpServers")},
        "claude_mcp_list": (mcp_list.stdout + mcp_list.stderr).strip().splitlines(),
        "skills_dir_count": len(os.listdir(H("~/.claude/skills"))),
        "loadavg": [round(x, 2) for x in os.getloadavg()],
        "battery": run(["pmset", "-g", "batt"]).splitlines()[-1:],
        "taken": run(["date", "+%Y-%m-%dT%H:%M:%S%z"]),
    }
    json.dump(snap, open(out, "w"), indent=2)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1])
