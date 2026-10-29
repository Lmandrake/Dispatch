"""What this machine can reach, right now -- the ground truth a route is computed on.

A routing decision that names an unreachable destination is worse than no decision:
it reads as a successful dispatch and then fails somewhere downstream, which is
exactly the defect this whole component exists to kill. Measured once: a subagent spawned with `model: fable` sends `claude-fable-5-1` to the
gateway, which answers

    400 anthropic_messages: Invalid model name passed in model=claude-fable-5-1.
        Call `/v1/models` to view available models for your key.

*after the agent has launched* -- so the dispatch succeeds, the agent dies, and
nothing in between says why.

🔴 TWO RULES THAT SHAPE EVERY FUNCTION HERE.

**1. Declared beats probed for facts that never change.** Local MLX models may exist on
only some machines. Every other machine must not pay a TCP timeout to
learn that, so `local_model_machines()` is a declaration and the probe runs only when
the declaration admits the possibility. An allowlist is a claim, so `test_capability`
checks it against the machine this code is running on.

**2. An unreachable destination and an unknown one are DIFFERENT ANSWERS.** Every
reachability field here is three-valued -- `True`, `False`, `None` -- and `None`
means "could not determine", never "no". This repo has already paid for collapsing
them twice: `routing/roster.json` lost every enterprise-endpoint row because a 401 was parsed as
an empty model list, and a plain `curl` of the local server returns an HTTP 401 that
a naive JSON read reports as "0 models served". A masked auth failure that reads as
an empty fleet is the characteristic failure of this kind of code.

## Probing vs reading

`snapshot()` probes: TCP connects, an HTTP call to the gateway, a subprocess or two.
It is for `bin/delegate`, which runs when a human or an agent asks a question and can
afford a second.

`load_snapshot()` only reads the cache. It is for the PreToolUse hook, which runs on
every single subagent spawn and must never make a network call -- a router that adds
300 ms to every spawn would be turned off, and rightly.

Staleness fails in the direction that cannot block work: a snapshot older than its
TTL marks every field `None` (unknown) rather than `False` (unreachable), because
`None` is what the hook is required to pass on. See `hook_verdict`.

Pure stdlib. Imports nothing from outside this repo at module level. Two sibling
tools' logic is MIRRORED here (a machine-identity helper and an account-catalogue helper), because this module has to work from Cowork's VM, a launchd job
and a bare `python3 -c`; both mirrors name their source and are pinned by a test.
Destination readiness is NOT mirrored any more: each destination repo owns a probe
(`docs/PROBE_CONTRACT.md`) and `consults()` runs it.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import time

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Where `snapshot()` caches itself and `load_snapshot()` reads from. Gitignored:
#: it describes one machine at one moment, so committing it would publish a fact
#: that is false everywhere else.
SNAPSHOT_PATH = REPO / "routing" / "capability.local.json"

#: How long a cached snapshot may be trusted by the hook. Chosen against what
#: actually changes: oMLX going down or a model being unloaded is the fastest-moving
#: fact here and a human notices it in minutes, while the gateway catalogue and the
#: machine's identity change on the scale of weeks. Ten minutes is short enough that
#: a dead server is not believed alive for a whole session, and long enough that a
#: normal session takes one probe.
SNAPSHOT_TTL_SECONDS = 600

# ------------------------------------------------------------------- the machine --
#: 🔴 DECLARED, not probed. Local MLX models are served by oMLX on one machine only.
#: The declaration is what lets every other machine answer "no local models" in zero
#: time instead of a TCP timeout.
#:
#: Which machines those are is site configuration, never code: `$DISPATCH_LOCAL_MODEL_MACHINES`
#: (comma-separated machine keys), else `"local_model_machines"` in the private overlay's
#: `site/overlay.json`. Unset everywhere, no machine is declared and no local probe runs.
#: Keys are machine keys as `machine_key()` returns them (lowercased, `.local` stripped).
LOCAL_MODEL_MACHINES_ENV = "DISPATCH_LOCAL_MODEL_MACHINES"


def local_model_machines(env: dict | None = None) -> frozenset:
    """The declared local-model machines. A declaration, no network I/O."""
    env = os.environ if env is None else env
    raw = env.get(LOCAL_MODEL_MACHINES_ENV)
    if raw is not None:
        return frozenset(k.strip().lower() for k in raw.split(",") if k.strip())
    from dispatchlib import providers
    keys = providers.overlay_config("site", env).get("local_model_machines") or []
    return frozenset(str(k).strip().lower() for k in keys if str(k).strip())


#: Hosts that are only reachable from the enterprise network or VPN, and what each one is
#: FOR. Probed as a group: they share a network precondition, so one probe answers
#: for all of them and the result is cached.
#:
#: The gateway host is never named here -- whichever account is active, it is
#: whatever `ANTHROPIC_BASE_URL` resolves to, read fresh by `_enterprise_hosts()` below.
#: Account comes from the environment, never named here.
#: Enterprise-internal hosts are named in the private overlay
#: (`<overlay>/enterprise/overlay.json` -> "internal_hosts": {host: what it is for}),
#: never here. With no overlay the set is empty and only the gateway host is probed.
def _static_internal_hosts(env: dict | None = None) -> dict:
    from dispatchlib import providers
    hosts = providers.overlay_config("enterprise", env).get("internal_hosts")
    return dict(hosts) if isinstance(hosts, dict) else {}


def _enterprise_hosts(env: dict | None = None) -> dict:
    """The overlay's internal hosts plus the active gateway host, named by `ANTHROPIC_BASE_URL`.

    The gateway host is derived, never hardcoded, because the account it names
    (whichever one is currently selected) changes with the environment, not with
    this code.
    """
    import urllib.parse
    env = env if env is not None else _settings_env()
    hosts = _static_internal_hosts()
    host = urllib.parse.urlparse(env.get("ANTHROPIC_BASE_URL") or "").hostname
    if host:
        hosts[host] = "the active Anthropic gateway"
    return hosts


def machine_key(override: str | None = None) -> str:
    """This machine's identity key.

    MIRRORS a sibling machine-identity helper: an explicit
    override, then `$WAYPOINT_MACHINE`, then the OS hostname; lowercased with a
    trailing `.local` stripped. Mirrored rather than imported because importing a
    sibling repo would make this module unusable from Cowork's VM (where `~/dev` is
    mounted at a different path) and from a bare `python3 -c`.

    `$WAYPOINT_MACHINE` exists because some managed machines get a hostname
    that changes on a re-image -- and it is also how a
    test pretends to be a different machine, which is how the declared-beats-probed
    rule is verified without a second computer.
    """
    raw = (override or os.environ.get("WAYPOINT_MACHINE")
           or socket.gethostname()).strip()
    if raw.lower().endswith(".local"):
        raw = raw[: -len(".local")]
    return raw.lower()


def can_have_local_models(machine: str | None = None) -> bool:
    """Whether local models are even possible here. A DECLARATION, no I/O."""
    return (machine or machine_key()) in local_model_machines()


# ------------------------------------------------------------------------ probes --

def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Same contract as `bin/doctor::_tcp_open`, which this duplicates on purpose:
    `bin/doctor` is a script, not an importable module, and a two-line socket call
    is cheaper to mirror than to restructure. True on connect, False on any OSError.

    Note what this CANNOT tell you: a port that accepts a connection but answers 401
    is `True` here. Liveness is not authorisation, and `local_models` keeps the two
    apart for exactly that reason.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def enterprise_reachable(timeout: float = 2.0, hosts=None) -> bool | None:
    """Is the enterprise network reachable? True / False / None.

    `None` is reserved for a case this probe cannot currently produce (every host
    errored in a way that is not a refusal) and exists so a caller must handle it;
    folding it into False is the collapse rule 2 forbids.

    One host answering is enough -- they share a network precondition, and requiring
    all of them would report "no network" whenever one service was down for maintenance.
    """
    hosts = list(hosts if hosts is not None else _enterprise_hosts())
    if not hosts:
        return None
    return any(tcp_open(h, 443, timeout=timeout) for h in hosts)


def _settings_env() -> dict:
    """The `env` block Claude Code is configured with.

    The live process environment WINS over the file, because the live environment is
    what a spawned subagent will actually inherit -- and the point of this module is
    to predict what the spawn will do, not what the config says it should do. The
    file is the fallback for a caller running outside Claude Code (a launchd job, a
    bare shell).
    """
    env = {}
    try:
        settings = json.loads((pathlib.Path.home() / ".claude" / "settings.json")
                              .read_text())
        if isinstance(settings.get("env"), dict):
            env.update({k: v for k, v in settings["env"].items()
                        if isinstance(v, str)})
    except Exception:                                   # noqa: BLE001
        pass                                            # absent config is not an error
    for k in list(env) + ["ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
                          "ANTHROPIC_DEFAULT_OPUS_MODEL",
                          "ANTHROPIC_DEFAULT_SONNET_MODEL",
                          "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                          "ANTHROPIC_SMALL_FAST_MODEL"]:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


#: Claude Code's three model aliases -> the env key that resolves each one. A spawn
#: that names an alias is resolved through these; a spawn that names anything else
#: (`fable`, a literal id) is sent as-is, which is why `fable` 400s and `haiku` does
#: not. MIRRORS a sibling account tool's role-key list, same reason as above.
ALIAS_ENV_KEYS = {
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}

#: Names the harness accepts that are NOT resolved through an env key, mapped to the
#: id it actually puts on the wire. MEASURED, not inferred -- each entry has to come
#: from an observed request, because guessing one would make the block message name a
#: model nobody sent.
#:
#: `fable` is here because of a real spawn in this session: the gateway answered
#:     400 anthropic_messages: Invalid model name passed in model=claude-fable-5-1
#: so the harness expands the short name itself and no `ANTHROPIC_DEFAULT_FABLE_MODEL`
#: exists to retarget it. That is the whole asymmetry worth knowing: `haiku` was
#: remapped to another id and works, `fable` cannot be remapped and dies.
HARNESS_ALIAS_IDS = {
    "fable": "claude-fable-5-1",
}

#: Claude Code strips a context-window suffix before sending the id on the wire.
#: `<region>.anthropic.claude-opus-5[1m]` is served as `...claude-opus-5`, so a
#: catalogue comparison that keeps the suffix finds nothing and would block every
#: Opus spawn on this machine. Measured: the gateway's ids carry no `[` at all.
_CONTEXT_SUFFIX = "[1m]"


def resolve_model(requested: str | None, env: dict | None = None) -> dict:
    """What id will actually be sent for a spawn that asked for `requested`.

    Returns `{requested, wire_id, via}` where `via` is `alias` (resolved through an
    env key), `literal` (sent as typed), or `default` (no model named, so the
    session's own model is inherited and there is nothing to check).

    🔴 THIS IS THE FUNCTION THE WHOLE HOOK RESTS ON, and the thing it gets right is
    that an alias is NOT a model id. An `ANTHROPIC_DEFAULT_HAIKU_MODEL` can be
    remapped to a Sonnet id and `model: haiku` still WORKS. Either way the alias is resolved from the environment, never named. A hook
    that hardcoded "block haiku" would now be blocking a valid spawn while letting
    `fable` through, which is the live defect. The rule is: resolve, then check the
    catalogue. Never match on the alias.
    """
    env = env if env is not None else _settings_env()
    if not requested:
        return {"requested": None, "wire_id": None, "via": "default"}
    key = ALIAS_ENV_KEYS.get(requested)
    if key:
        wire = env.get(key)
        return {"requested": requested, "wire_id": _strip_context(wire),
                "via": "alias"}
    if requested in HARNESS_ALIAS_IDS:
        return {"requested": requested, "wire_id": HARNESS_ALIAS_IDS[requested],
                "via": "harness-alias"}
    return {"requested": requested, "wire_id": _strip_context(requested),
            "via": "literal"}


def _strip_context(model: str | None) -> str | None:
    if not model:
        return None
    return model[: -len(_CONTEXT_SUFFIX)] if model.endswith(_CONTEXT_SUFFIX) else model


def alias_collapse(env: dict | None = None) -> dict:
    """Which model aliases resolve to the SAME wire id — i.e. which rungs of an
    escalation ladder are not actually different models.

    🔴 WHY THIS IS WORTH A FUNCTION. Escalation ladders are usually written
    in aliases: `haiku -> sonnet -> opus`, retry one rung up on failure. The aliases
    are remapped per machine by `ANTHROPIC_DEFAULT_*_MODEL`, and a machine may set BOTH
    `ANTHROPIC_DEFAULT_HAIKU_MODEL` and `ANTHROPIC_DEFAULT_SONNET_MODEL` to the same
    model (one with a `[1m]` context suffix, which is stripped on the wire). So the first escalation step re-runs the
    same weights and buys context, not capability — a retry that was meant to try a
    stronger model instead tries the same one and will usually fail the same way.

    Nothing reports that. The remap looks like a fix (it is: it stopped a 400), the
    ladder looks like a ladder, and the collapsed rung is invisible in both. This is the defect
    that is easy to miss.

    Returns `{wire_id: [aliases...]}` for every wire id with more than one alias.
    Empty dict means every rung is a distinct model.
    """
    env = env if env is not None else _settings_env()
    by_wire: dict[str, list[str]] = {}
    for alias in ALIAS_ENV_KEYS:
        wire = resolve_model(alias, env)["wire_id"]
        if wire:
            by_wire.setdefault(wire, []).append(alias)
    return {w: sorted(a) for w, a in by_wire.items() if len(a) > 1}


def active_subscription(env: dict | None = None) -> str | None:
    """Which gateway subscription is active, from `ANTHROPIC_BASE_URL`.

    The id is the path segment after the subscription marker (`DISPATCH_SUBSCRIPTION_MARKER`); the account-switching tool writes it there. Returns None when the URL
    carries no marker, which is a real state (a non-enterprise endpoint) and not a failure.
    """
    env = env if env is not None else _settings_env()
    url = env.get("ANTHROPIC_BASE_URL") or ""
    marker = os.environ.get("DISPATCH_SUBSCRIPTION_MARKER", "/sub-id-")
    if marker not in url:
        return None
    return url.split(marker, 1)[1].split("/")[0].strip() or None


def gateway_catalogue(env: dict | None = None, timeout: float = 20.0) -> dict:
    """The ids the active account can actually use, ASKED OF THE GATEWAY.

    Returns `{models, known, error, source}`. `known` is False and `models` is the
    CACHED fallback when the gateway could not be asked -- and the two are kept
    distinguishable, because "the account serves nothing" and "I could not ask" would
    otherwise both read as an empty catalogue and the hook would block every spawn.

    The cached fallback is the account-state file named by `DISPATCH_ACCOUNT_STATE`,
    kept per subscription by the account-switching tool. It is a cache, so it is named as `source: cache` and a caller
    that cares can refuse to act on it.

    This asks the gateway's /v1/models rather than trusting a roster: roster ids can
    carry a region prefix the active account does not serve, and the gateway answers
    400 for an id under the wrong prefix.
    """
    env = env if env is not None else _settings_env()
    base = (env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    if not base:
        return {"models": [], "known": False, "source": None,
                "error": "no ANTHROPIC_BASE_URL in the environment or settings.json"}
    token = _api_key(env)
    if token:
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{base}/v1/models",
                headers={"Authorization": f"Bearer {token}", "x-api-key": token})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            ids = sorted(m["id"] for m in (data.get("data") or []) if m.get("id"))
            return {"models": ids, "known": True, "source": "gateway", "error": None}
        except Exception as e:                          # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    else:
        err = "no API key: apiKeyHelper is absent or produced nothing"

    cached = _cached_catalogue(active_subscription(env))
    return {"models": cached, "known": False, "source": "cache" if cached else None,
            "error": err}


def _api_key(env: dict) -> str | None:
    """Mint a token with the configured `apiKeyHelper`.

    The helper is a shell script that talks to the gateway's auth path; there is no
    static key to read. Returns None on any failure -- a missing token is "I could
    not ask", which `gateway_catalogue` reports as `known: False`.

    The token is never logged, stored, or put in a snapshot.
    """
    import subprocess
    try:
        settings = json.loads((pathlib.Path.home() / ".claude" / "settings.json")
                              .read_text())
        helper = settings.get("apiKeyHelper")
    except Exception:                                   # noqa: BLE001
        helper = None
    if not helper:
        return None
    try:
        out = subprocess.run(helper, shell=True, capture_output=True, text=True,
                             timeout=60)
    except Exception:                                   # noqa: BLE001
        return None
    key = (out.stdout or "").strip()
    return key or None


def _cached_catalogue(subscription: str | None) -> list[str]:
    """Model ids the account-switching tool last saw for this subscription. Pure read, never raises."""
    if not subscription:
        return []
    try:
        state = json.loads(pathlib.Path(os.environ.get("DISPATCH_ACCOUNT_STATE") or pathlib.Path.home() / ".config" / "dispatch" / "account-state.json")
                           .read_text())
        acct = (state.get("accounts") or {}).get(subscription) or {}
        return sorted(m for m in (acct.get("models") or []) if isinstance(m, str))
    except Exception:                                   # noqa: BLE001
        return []


def local_models(machine: str | None = None, *, timeout: float = 2.0) -> dict:
    """What oMLX is serving, and whether we really know.

    Returns `{possible, listening, models, known, error}`.

      * `possible` -- the DECLARATION. False on any machine not declared as hosting them, and
        when it is False nothing below is probed at all: `listening` is False and
        `known` is True, because "this machine cannot have them" is knowledge, not
        a failure to look.
      * `listening` -- a TCP connect only. Liveness, not authorisation.
      * `known` -- False only when the port was open and the model list still could
        not be read (the 401 case). That is the one state where a caller must not
        treat the empty list as the fleet.
    """
    machine = machine or machine_key()
    if not can_have_local_models(machine):
        return {"possible": False, "listening": False, "models": [], "known": True,
                "error": None}
    if not tcp_open("127.0.0.1", 8000, timeout=timeout):
        return {"possible": True, "listening": False, "models": [], "known": True,
                "error": "nothing listening on 127.0.0.1:8000 (oMLX not running)"}
    try:
        from dispatchlib.omlx import harness
        router = harness("router")
        return {"possible": True, "listening": True,
                "models": router.served_model_ids(timeout=max(timeout, 10.0)),
                "known": True, "error": None}
    except Exception as e:                              # noqa: BLE001
        # The port answered but the list did not. This is the masked-401 state and
        # it must NOT become an empty fleet: `known: False` is what stops a caller
        # concluding the server serves nothing.
        return {"possible": True, "listening": True, "models": [], "known": False,
                "error": f"{type(e).__name__}: {e}"}


#: The destination registry: which repo owns each destination, its probe command and
#: where material sent there goes. See `docs/PROBE_CONTRACT.md`.
DESTINATIONS_PATH = REPO / "routing" / "destinations.json"
PROBE_CONTRACT = "dispatch-probe/1"
#: The whole probe must finish inside this. The contract allows a probe 10 s.
PROBE_TIMEOUT_SECONDS = 12.0


def destinations(path: pathlib.Path | str = DESTINATIONS_PATH) -> dict:
    """The registry's `destinations` block. Raises if it cannot be read: a missing
    registry is a broken install, and an empty dict would read as "no destinations".

    The committed registry holds only public destinations. A private one (an on-prem
    enterprise model service, say) is registered by the overlay's
    `enterprise/overlay.json` -> "destinations", merged here only for the default
    registry so a test's own registry stays exactly what it wrote."""
    reg = dict(json.loads(pathlib.Path(path).read_text())["destinations"])
    if pathlib.Path(path) == DESTINATIONS_PATH:
        from dispatchlib import providers
        extra = providers.overlay_config("enterprise").get("destinations")
        if isinstance(extra, dict):
            reg.update({k: v for k, v in extra.items() if isinstance(v, dict)})
    return reg


def caller_root(cwd: str | None = None) -> pathlib.Path:
    """The git root of the repo the caller is working in, else the directory itself.

    ChatGPT enrollment is per consulting repo, so "can I consult" has to be asked about
    the CALLER's repo. The first version asked about this one, whatever the caller was
    working on (design review 2026-10-20, P1)."""
    import subprocess
    d = pathlib.Path(cwd or os.getcwd())
    try:
        r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return pathlib.Path(r.stdout.strip())
    except Exception:                                   # noqa: BLE001
        pass
    return d


def repo_path(spec: dict) -> pathlib.Path:
    """Where a destination's repo is. A bare name (`EnterprisePlugin`) is looked up on
    `$DISPATCH_PROVIDER_PATHS` (`dispatchlib.providers`); a relative path is inside this
    repo (`providers/nemotron`); `~` and absolute paths are taken as written. A bare name
    found nowhere yields a path that does not exist, which `run_probe` reports as not cloned."""
    from dispatchlib import providers
    raw = spec["repo"]
    if "/" not in raw:
        found = providers.find(raw)
        return found if found else providers.search_dirs()[0] / raw
    p = pathlib.Path(os.path.expanduser(raw))
    return p if p.is_absolute() else REPO / p


def _probe_python() -> str:
    """The contract says a probe runs under /usr/bin/python3, so run it there."""
    return "/usr/bin/python3" if pathlib.Path("/usr/bin/python3").exists() else "python3"


def run_probe(name: str, spec: dict, *, caller: pathlib.Path | None = None,
              offline: bool = False, timeout: float = PROBE_TIMEOUT_SECONDS) -> dict:
    """Run one destination's own probe and return `{ready, why, ...}`.

    🔴 THE ROUTER DOES NOT KNOW HOW ANY DESTINATION WORKS. It used to: ChatGPT,
    internal-endpoint and Jev readiness were each re-implemented here, and each copy
    drifted from the repo it mirrored -- ChatGPT's read this repo's enrollment for every
    caller, the internal endpoint's read a key file its own client does not read first. Each
    destination repo now owns a `dispatch-probe/1` command and this only runs it.

    Every way the probe can fail to answer -- repo not cloned, command missing,
    timeout, non-zero exit, unparseable output, wrong contract -- becomes
    `ready: None` with the reason. Unknown, never refused.
    """
    import subprocess
    repo = repo_path(spec)
    base = {"exposure": spec.get("exposure"), "kind": spec.get("kind"),
            "ranked": bool(spec.get("ranked")), "repo": str(repo),
            "skill": spec.get("skill"), "remedy": None, "fixable_by": None,
            "facts": {}}

    def unknown(why):
        return dict(base, ready=None, why=why)

    if not repo.is_dir():
        return unknown(f"{repo} is not cloned on this machine")
    argv = [str(caller or caller_root()) if a == "{caller}" else a
            for a in spec["probe"]]
    exe = repo / argv[0]
    if not exe.exists():
        return unknown(f"{exe} does not exist; that repo predates the probe contract")
    cmd = [_probe_python(), str(exe)] + argv[1:] + (["--offline"] if offline else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(repo))
    except subprocess.TimeoutExpired:
        return unknown(f"probe did not answer within {timeout:g}s")
    except Exception as e:                              # noqa: BLE001
        return unknown(f"probe could not start: {type(e).__name__}")
    if r.returncode != 0:
        return unknown(f"probe exited {r.returncode}; the probe itself is broken")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        return unknown("probe printed something that is not JSON")
    if not isinstance(out, dict) or out.get("contract") != PROBE_CONTRACT:
        return unknown(f"probe does not speak {PROBE_CONTRACT}")
    ready = out.get("ready")
    if ready not in (True, False, None):
        return unknown(f"probe returned ready={ready!r}, which is not three-valued")
    facts = out.get("facts") if isinstance(out.get("facts"), dict) else {}
    return dict(base, ready=ready, why=str(out.get("why") or ""),
                remedy=out.get("remedy"), fixable_by=out.get("fixable_by"),
                facts=facts)


def consults(enterprise: bool | None = None, *, verify: bool = True,
             caller: pathlib.Path | None = None,
             registry: pathlib.Path | str = DESTINATIONS_PATH) -> dict:
    """Readiness of every registered destination, from each one's own probe.

    `verify=False` passes `--offline` to every probe, so none makes a network call
    and a readiness that needs one comes back `None`. `enterprise` is accepted for the
    snapshot's call shape and ignored: the internal endpoint's own probe establishes reach.

    A registry that cannot be read raises, rather than answering "no destinations".
    """
    del enterprise
    reg = destinations(registry)
    return {name: run_probe(name, spec, caller=caller, offline=not verify)
            for name, spec in reg.items()}


def proxy_rebind(env: dict | None = None) -> dict | None:
    """Whether the model aliases now point at something that is not the gateway.

    `/nemo-proxy` (providers/nemotron) sets `ANTHROPIC_BASE_URL` to a localhost LiteLLM
    proxy and maps `haiku`/`sonnet`/`opus` onto Nemotron models. Inside such a session
    `tier` still answers "haiku", and that name now means different weights from the
    ones its evidence was measured on. Nothing else notices, so this reports it.
    None when the base URL is not a loopback address.
    """
    import urllib.parse
    env = env if env is not None else _settings_env()
    url = env.get("ANTHROPIC_BASE_URL") or ""
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return {"base_url": url,
                "why": ("ANTHROPIC_BASE_URL is a local proxy, so haiku/sonnet/opus mean "
                        "whatever that proxy maps them to (/nemo-proxy maps them to "
                        "Nemotron). The tier rules were measured on Claude models and "
                        "do not hold for those names here.")}
    return None


# -------------------------------------------------------------------- snapshot --

def _observe(fn, *args):
    """Run one probe and wrap it as a timestamped observation.

    Returns `{value, ts, failed}`. A probe that raises becomes
    `{value: None, failed: <ExceptionClass>}` -- `None`, the unknown, never `False`.
    That is the collapse rule 2 forbids, applied at the aggregator: a probe that
    could not run has not established that the destination is unreachable.
    """
    try:
        return {"value": fn(*args), "ts": time.time(), "failed": None}
    except Exception as e:                              # noqa: BLE001
        return {"value": None, "ts": time.time(), "failed": type(e).__name__}


def observation(snap: dict | None, key: str, *,
                ttl: float = SNAPSHOT_TTL_SECONDS) -> object | None:
    """One observation's value, or None if it is absent, failed, or itself stale.

    This is the accessor every caller should use rather than reaching into the
    snapshot dict, because it is where the per-observation TTL is applied. Reading
    `snap["gateway"]["value"]` directly skips that check, which is exactly how C2
    bites: the top-level timestamp is fresh while the observation under it is not.
    """
    if not snap:
        return None
    obs = snap.get(key)
    if not isinstance(obs, dict) or "value" not in obs:
        return None
    ts = obs.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    age = time.time() - ts
    if age > ttl or age < -_CLOCK_TOLERANCE_SECONDS:
        return None
    return obs["value"]


def snapshot(*, machine: str | None = None, probe: bool = True,
             write: bool = True, path: pathlib.Path | str = SNAPSHOT_PATH) -> dict:
    """Everything above, in one dict, optionally cached to disk.

    `probe=False` returns the declared half only -- machine identity and whether
    local models are even possible -- with every probed field `None`. That is the
    honest answer for a caller that must not do I/O, and it is what proves the
    declared-beats-probed rule: on a machine not declared to host them the local answer is
    complete with `probe=True` and no socket is ever opened.
    """
    machine = machine or machine_key()
    env = _settings_env()
    snap = {
        "ts": time.time(),
        "machine": machine,
        "can_have_local_models": can_have_local_models(machine),
        "subscription": active_subscription(env),
        "alias_collapse": alias_collapse(env),
        "proxy_rebind": proxy_rebind(env),
        "probed": bool(probe),
    }
    if not probe:
        snap.update({"enterprise": None, "local": None, "gateway": None, "consults": None})
    else:
        # 🔴 EACH OBSERVATION CARRIES ITS OWN TIMESTAMP, and each is attempted
        # independently. Two reasons, both from the cold design review:
        #
        #   C2 -- refreshing one source must not rejuvenate another. A successful
        #   gateway refresh alongside a failed local refresh would otherwise carry
        #   "local is down" forward under a brand-new top-level timestamp, so a
        #   denial would be renewed by evidence about something else entirely.
        #
        #   C4 -- one discovery failure must not disable every guard. Each probe
        #   keeps its own "raise, never fabricate an empty result" discipline
        #   internally, and the AGGREGATOR isolates the failure, so a broken
        #   destination does not erase known facts about the others.
        enterprise = _observe(enterprise_reachable)
        snap.update({
            "enterprise": enterprise,
            "local": _observe(local_models, machine),
            "gateway": _observe(gateway_catalogue, env),
            "consults": _observe(consults, enterprise.get("value") if enterprise else None),
        })
    if write:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")
    return snap


def load_snapshot(path: pathlib.Path | str = SNAPSHOT_PATH, *,
                  ttl: float = SNAPSHOT_TTL_SECONDS,
                  env: dict | None = None) -> dict | None:
    """The cached snapshot if it is fresh AND still describes this configuration.
    Otherwise None. Never probes, never raises.

    🔴 RETURNS None RATHER THAN A STALE DICT, on purpose. A caller handed stale facts
    cannot tell they are stale unless it checks, and the one caller that matters here
    is a hook that must not block on them. `None` forces the fail-open path; a dict
    with an old timestamp invites a check that someone will forget to write.

    Three ways a snapshot is rejected, two of which came out of the cold design
    review (`docs/ROUTER_CONSULT.md`):

      * **Too old.** The ordinary case.
      * **Dated in the future (C5).** A negative age would otherwise read as fresh
        forever -- the first draft computed `now - ts > ttl` with no lower bound, so
        a clock that moved backwards, or a snapshot copied from another machine,
        pinned the cache permanently. A small tolerance absorbs NTP jitter; beyond
        that an impossible timestamp invalidates freshness rather than extending it.
      * **Wrong configuration (C1).** Freshness is not sufficiency: a five-second-old
        catalogue for account A says nothing about account B after a switch. The
        snapshot must match the machine AND the subscription the calling process will
        actually use, or its facts are unknown rather than merely old.
    """
    try:
        snap = json.loads(pathlib.Path(path).read_text())
        if not isinstance(snap, dict) or "ts" not in snap:
            return None
        age = time.time() - float(snap["ts"])
        if age > ttl or age < -_CLOCK_TOLERANCE_SECONDS:
            return None
        env = env if env is not None else _settings_env()
        if snap.get("machine") != machine_key():
            return None
        if snap.get("subscription") != active_subscription(env):
            return None
        return snap
    except Exception:                                   # noqa: BLE001
        return None


#: How far in the future a snapshot's timestamp may sit before it is treated as
#: impossible rather than fresh. Wide enough for NTP jitter and a filesystem whose
#: clock is a few seconds ahead; far short of anything a human would call stale.
_CLOCK_TOLERANCE_SECONDS = 120


# ----------------------------------------------------------------- hook verdict --

ALLOW = "allow"
BLOCK = "block"


def hook_verdict(requested_model: str | None, *, snap: dict | None = None,
                 env: dict | None = None) -> dict:
    """Should a subagent spawn asking for `requested_model` be blocked?

    Returns `{action, reason, wire_id, via, suggest}`. `action` is `allow` or
    `block`; `reason` is empty on an allow.

    🔴 THIS IS AN AVAILABILITY-AND-NAME GUARD, NOT A ROUTING POLICY.

    The plan called the hook "makes it binding". The cold design review (finding H1)
    showed that oversells it: an agent that ignores `bin/delegate` and spawns a
    served, reachable model straight from a stale prose instruction is ALLOWED here,
    with no DECISION row behind it. Making routing itself binding needs either a
    launcher that records and dispatches together, or a third check for a routing
    receipt -- and a receipt cannot be a "last decision" file, because two concurrent
    jobs would read each other's (H2). Per-invocation association is not available in
    the `Agent` tool's schema today, so it is left undone and said plainly rather
    than approximated. What this guard does catch is the failure that is *certain*.

    🔴 EVERY UNCERTAINTY ALLOWS. There are six ways this can fail to know
    something -- no snapshot, a stale snapshot, a snapshot describing a different
    machine or subscription, a catalogue that could not be read, an alias with no env
    mapping, no model named at all -- and all six return `allow`. The governing rule,
    from the review: *expired evidence becomes unknown; it neither proves
    availability nor remains grounds for denial.* Only a fresh, correctly scoped
    catalogue may deny.

    One failure this CANNOT see (A1): an agent definition may pin its own model, and
    the harness's own precedence between invocation parameter, agent frontmatter and
    environment default has changed across versions. `via: "default"` means no model
    was named in the call, which is reported honestly as unknown rather than treated
    as the session's model.

    This is the shape the plan called "fail open", tightened by something the plan
    got wrong. The plan said the hook blocks "a model the active account does not
    serve (today, any `haiku`)". That parenthetical is now FALSE:
    `ANTHROPIC_DEFAULT_HAIKU_MODEL` can be remapped by the gateway, in which case `model: haiku` resolves to the target and works. The id that
    actually 400s is `fable`, which no env key remaps, and which was measured dying
    in this session. Resolve first, then check -- never match on the alias.
    """
    res = resolve_model(requested_model, env)
    base = {"action": ALLOW, "reason": "", "wire_id": res["wire_id"],
            "via": res["via"], "suggest": None}

    if res["via"] == "default":
        return base                                     # nothing named, nothing to check
    if res["via"] == "alias" and not res["wire_id"]:
        base["reason"] = ""                             # alias with no mapping: unknown
        return base

    snap = snap if snap is not None else load_snapshot(env=env)
    if not snap:
        return base                                     # no fresh facts -> allow
    # Read through `observation`, never `snap["gateway"]` directly: the per-
    # observation TTL lives in there, and the top-level stamp can be fresh while this
    # fact is not (C2).
    gw = observation(snap, "gateway") or {}
    if not gw.get("known") or not gw.get("models"):
        return base                                     # could not ask -> allow

    if res["wire_id"] in gw["models"]:
        return base

    base["action"] = BLOCK
    base["suggest"] = _nearest_served(res["wire_id"], gw["models"])
    base["reason"] = (
        f"the gateway for subscription {snap.get('subscription')!r} does not serve "
        f"{res['wire_id']!r}" +
        (f" (requested as {res['requested']!r})"
         if res["wire_id"] != res["requested"] else "") +
        f". A spawn with this model returns HTTP 400 AFTER the agent launches, so it "
        f"reads as a successful dispatch and then a dead agent." +
        (f" Use {base['suggest']!r} instead." if base["suggest"] else
         " Ask the gateway's /v1/models for the served ids."))
    return base


def _nearest_served(wanted: str | None, served: list[str]) -> str | None:
    """A served id to suggest instead. Family match only -- never a silent rewrite.

    The hook NAMES this and blocks; it does not substitute. A silent substitution is
    what makes a ladder unauditable, which is the disease this component treats: the
    whole reason five prose ladders drifted undetected is that nothing ever reported
    a correction.
    """
    if not wanted:
        return None
    # Prefer a Sonnet-class id, which is the ladder's workhorse rung, and prefer a
    # plain id over a load-balanced alias so the suggestion is one a human recognises.
    plain = [m for m in served if "-lb-" not in m and "load-balanced" not in m]
    for family in ("sonnet", "opus"):
        hits = sorted(m for m in plain if family in m)
        if hits:
            return hits[-1]
    return plain[-1] if plain else None
