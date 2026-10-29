#!/usr/bin/env python3
"""Generate Pi and OMP agent directories from the live Claude Code config (~/.claude, ~/.claude.json).

    python3 gen/make_configs.py [--harness pi|omp|all] [--profile full|bare]

Output goes under the storage root (<root>/harnesses/agents/<harness>-<profile>/), never ~/.pi,
~/.omp or ~/.claude, and is regenerated on every launch (bin/pi-claude, bin/omp-claude), so a
An account change takes effect on the next run. Nothing here names an account, host,
key or model id: all of it is read from settings.json at run time (gen/genai_route.py).

Profiles:
  full  CLAUDE.md as user instructions, ~/.claude/skills, MCP servers from ~/.claude.json.
  bare  Model route only: no instructions, no skills, no MCP. Used by bench/ so all three
        harnesses carry the same (empty) payload.
What does not port is listed in docs/PORTING.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import genai_route as g  # noqa: E402

PROVIDER = "enterprisegenai"
TOKEN_CMD = "!" + os.path.join(REPO, "bin", "genai-token")


def token_ref(token_env, harness):
    """apiKey value: per-request helper command, or an env var (bench mode). Pi interpolates
    `$NAME`; OMP takes a bare variable name (and silently sends the literal if it is unset,
    so bench/cpu_bench.py always sets it)."""
    if not token_env:
        return TOKEN_CMD
    return ("$" + token_env) if harness == "pi" else token_env


def storage_root():
    return os.environ.get("DISPATCH_STORAGE_ROOT") or os.path.expanduser("~/.cache/dispatch")


def model_entries(s):
    seen, out = set(), []
    for alias, (mid, big) in g.models(s).items():
        if mid in seen:
            continue
        seen.add(mid)
        out.append({"id": mid, "name": "%s (%s)" % (mid, alias), "reasoning": True,
                    "input": ["text", "image"],
                    "contextWindow": 1000000 if big else 200000, "maxTokens": 32000,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}})
    return out


def claude_mcp_servers():
    try:
        with open(os.path.expanduser("~/.claude.json"), encoding="utf-8") as fh:
            servers = json.load(fh).get("mcpServers") or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for name, cfg in servers.items():
        c = {k: cfg[k] for k in ("command", "args", "env", "url", "headers") if k in cfg and cfg[k]}
        if cfg.get("type") in ("stdio", "http"):
            c["type"] = cfg["type"]
        out[name] = c
    return out


def write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(obj, str):
            fh.write(obj)
        else:
            json.dump(obj, fh, indent=2)
            fh.write("\n")


def reset_dir(d, keep=("sessions", "logs", "cache")):
    os.makedirs(d, exist_ok=True)
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if name in keep:
            continue
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)


def gen_pi(d, profile, s, token_env=None):
    reset_dir(d)
    write(os.path.join(d, "models.json"), {"providers": {PROVIDER: {
        "name": "Enterprise GenAI (from Claude Code settings)", "baseUrl": g.base_url(s),
        "api": "anthropic-messages", "apiKey": token_ref(token_env, "pi"), "authHeader": True,
        "models": [dict(m, compat={"forceAdaptiveThinking": True}) for m in model_entries(s)]}}})
    # Without forceAdaptiveThinking Pi sends a custom provider's Claude 5 models the old fixed
    # budget_tokens thinking (8192 at medium) instead of adaptive effort as Claude Code and OMP
    # do: about 2-4x the output tokens and wall time (docs/CAPABILITY-2026-10-23.md).
    settings = {"defaultProvider": PROVIDER, "defaultModel": g.models(s)["sonnet"][0],
                "quietStartup": True, "enableInstallTelemetry": False}
    if profile == "full":
        settings["skills"] = [os.path.expanduser("~/.claude/skills")]
        shutil.copyfile(os.path.expanduser("~/.claude/CLAUDE.md"), os.path.join(d, "AGENTS.md"))
        write(os.path.join(d, "mcp.json"), {"mcpServers": claude_mcp_servers()})
    write(os.path.join(d, "settings.json"), settings)


def gen_omp(d, profile, s, token_env=None):
    reset_dir(d)
    provider = {"baseUrl": g.base_url(s), "api": "anthropic-messages", "apiKey": token_ref(token_env, "omp"),
                "authHeader": True, "auth": "apiKey", "models": model_entries(s)}
    # JSON is valid YAML; OMP reads models.yml / config.yml.
    write(os.path.join(d, "models.yml"), json.dumps({"providers": {PROVIDER: provider}}, indent=2) + "\n")
    m = g.models(s)
    cfg = {"modelRoles": {"default": "%s/%s" % (PROVIDER, m["sonnet"][0]),
                          "smol": "%s/%s" % (PROVIDER, m["small_fast"][0]),
                          "slow": "%s/%s" % (PROVIDER, m["opus"][0])},
           "startup": {"quiet": True, "setupWizard": False, "changelogMode": "hidden"},
           "enableInstallTelemetry": False}
    if profile == "full":
        cfg["skills"] = {"customDirectories": [os.path.expanduser("~/.claude/skills")]}
        shutil.copyfile(os.path.expanduser("~/.claude/CLAUDE.md"), os.path.join(d, "AGENTS.md"))
        write(os.path.join(d, "mcp.json"), {"mcpServers": claude_mcp_servers()})
    write(os.path.join(d, "config.yml"), json.dumps(cfg, indent=2) + "\n")


def agent_dir(harness, profile, tag=""):
    return os.path.join(storage_root(), "harnesses", "agents", "%s-%s%s" % (harness, profile, tag))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", choices=["pi", "omp", "all"], default="all")
    ap.add_argument("--profile", choices=["full", "bare"], default="full")
    ap.add_argument("--token-env", help="read the bearer from this env var instead of running bin/genai-token per request (bench)")
    a = ap.parse_args(argv)
    s = g.settings()
    for h in (["pi", "omp"] if a.harness == "all" else [a.harness]):
        d = agent_dir(h, a.profile, "-bench" if a.token_env else "")
        (gen_pi if h == "pi" else gen_omp)(d, a.profile, s, a.token_env)
        print(d)


if __name__ == "__main__":
    main()
