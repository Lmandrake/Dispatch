"""The GenAI route (base URL, model ids, key helper), read from ~/.claude/settings.json at call time.

Contract: this repo names no
host, subscription, key, model id or region prefix. The account-switching tool writes settings.json `env`;
we read it every run. A process env value wins over settings.json (as Claude Code exports it).
A missing variable raises GenAIEnvMissing by name; there is no fallback.
"""
import json
import os

SETTINGS = os.path.expanduser(os.environ.get("NH_CLAUDE_SETTINGS", "~/.claude/settings.json"))
MODEL_VARS = {
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "small_fast": "ANTHROPIC_SMALL_FAST_MODEL",
}
CONTEXT_MARKER = "[1m]"


class GenAIEnvMissing(RuntimeError):
    pass


def settings():
    with open(SETTINGS, encoding="utf-8") as fh:
        return json.load(fh)


def need(name, s=None):
    v = (os.environ.get(name) or "").strip()
    if not v:
        v = str(((s or settings()).get("env") or {}).get(name) or "").strip()
    if not v:
        raise GenAIEnvMissing("%s is not set in the environment or %s env (the account-switching tool writes it); "
                              "refusing to guess an account." % (name, SETTINGS))
    return v


def base_url(s=None):
    return need("ANTHROPIC_BASE_URL", s).rstrip("/")


def models(s=None):
    """{alias: (wire_id, has_1m_marker)} for every alias the env names."""
    s = s or settings()
    out = {}
    for alias, var in MODEL_VARS.items():
        v = need(var, s)
        out[alias] = (v[: -len(CONTEXT_MARKER)] if v.endswith(CONTEXT_MARKER) else v,
                      v.endswith(CONTEXT_MARKER))
    return out


def key_helper(s=None):
    s = s or settings()
    h = (s.get("apiKeyHelper") or "").strip()
    if not h:
        raise GenAIEnvMissing("apiKeyHelper is not set in %s" % SETTINGS)
    return os.path.expanduser(h)


def helper_ttl_ms(s=None):
    try:
        return int(need("CLAUDE_CODE_API_KEY_HELPER_TTL_MS", s))
    except GenAIEnvMissing:
        return 300000  # Claude Code's documented default helper TTL; not an account value


def passthrough_env(s=None):
    """settings.json env keys a harness should inherit (betas kill-switch etc.), minus Claude-UI-only ones."""
    s = s or settings()
    env = {k: str(v) for k, v in (s.get("env") or {}).items()}
    return {k: v for k, v in env.items() if k.startswith(("ANTHROPIC_", "CLAUDE_CODE_DISABLE_EXPERIMENTAL"))}


if __name__ == "__main__":
    print("base_url  :", base_url())
    for a, (m, big) in models().items():
        print("%-10s: %s%s" % (a, m, "  (1M context)" if big else ""))
    print("key helper:", key_helper(), "ttl_ms", helper_ttl_ms())
