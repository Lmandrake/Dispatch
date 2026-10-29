#!/usr/bin/env python3
"""Is this machine actually able to run a consult? Check, and fix what is fixable.

## Why this exists

A session on a second machine once spent hours failing to send a consult, and every layer it
looked at reported something that was true but not the answer. The transport was not the
problem to debug; the *machine* had never been set up. Three preconditions differed from the
first machine, none of them visible from any error message the tooling produced:

  1. Chrome's runtime remote-debugging server was not bound. `consult.py` said so accurately
     and the session did not believe it, because a *synced* ledger row showed a success that
     had actually happened on the other machine.
  2. No MCP server was declared with `--autoConnect`, so the only browser MCP available was
     the plugin's, which launches its OWN throwaway Chrome. Every experiment run "against
     Chrome" was therefore run against the wrong browser, and the results were confounded
     without saying so.
  3. `docs/RELIABLE-ACCESS-RECIPE.md` was written on the first machine and every step presupposes
     (1). Read on a machine where (1) is false, it looks like a cure and is a no-op.

🔴 **The lesson this file encodes: a doc that says "check X" is what failed.** So this is
executable, it names which machine it ran on, and it distinguishes what it can fix from what
needs a human — because exactly one of these preconditions is not the agent's to fix, and
pretending otherwise is how the last attempt wasted an afternoon.

⚠️ **`claude mcp list` reporting a server "Connected" does NOT mean the browser is reachable.**
That is the stdio handshake with the MCP server process. The Chrome attach happens lazily on
the first tool call. Measured here: `chrome-mine` reported Connected while nothing was bound.

Usage:
    python3 bin/preflight.py            # report; exit 0 clean, 1 needs a human, 2 fixable
    python3 bin/preflight.py --fix      # fix what is fixable, then report
    python3 bin/preflight.py --json     # same checks, machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import shutil
import socket
import subprocess
import sys

HOME = pathlib.Path.home()
CHROME_PROFILE = pathlib.Path(os.environ.get("CHATGPT_CHROME_PROFILE") or HOME / "Library/Application Support/Google/Chrome")
PORT_FILE = CHROME_PROFILE / "DevToolsActivePort"
CLAUDE_JSON = HOME / ".claude.json"
REPO = pathlib.Path(__file__).resolve().parents[1]
PRESSER = REPO / "bin" / "keep-allowing.sh"
BROKER = REPO / "bin" / "broker.py"

#: What a missing precondition costs, and who can fix it.
HUMAN = "human"      # only the human can do this
AGENT = "agent"      # the agent can, and --fix will
INFO = "info"        # no action, just tell the session what it is working with
#: A check that could not reach far enough to answer. 🔴 NOT the same as `ok`, and not
#: the same as a failure either -- see `check_chatgpt_auth`. `main` reports these
#: separately and never prints "all preconditions met" while one is outstanding.
UNDETERMINED = "undetermined"


class Check:
    def __init__(self, name, ok, detail, user=INFO, remedy=None):
        self.name, self.ok, self.detail = name, ok, detail
        self.user, self.remedy = user, remedy

    def as_dict(self):
        return {"check": self.name, "ok": self.ok, "detail": self.detail,
                "user": self.user, "remedy": self.remedy}


def _machine() -> str:
    """Name the machine in the output. A result that does not say which Mac it came from is
    how one machine's finding got spent as another machine's precondition -- twice, once through a doc and
    once through a synced ledger row."""
    try:
        host = subprocess.run(["scutil", "--get", "LocalHostName"],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        host = ""
    return host or platform.node() or "unknown"


# -- the checks ------------------------------------------------------------

def check_chrome_running() -> Check:
    out = subprocess.run(["pgrep", "-f", "Google Chrome.app/Contents/MacOS/Google Chrome"],
                         capture_output=True, text=True).stdout.split()
    return Check("chrome_running", bool(out),
                 f"{len(out)} Chrome process(es)" if out else "Chrome is not running",
                 HUMAN if not out else INFO,
                 None if out else "Start Chrome (the user's own browser, signed into ChatGPT).")


def _chrome_listening() -> list[str]:
    """Every listening TCP socket owned by a Chrome process.

    🔴 This, not the port file, is the ground truth. A throwaway Chrome launched with an
    explicit `--remote-debugging-port` was measured LISTENING while writing no port file at
    all, so the file's absence alone does not prove the server is down -- and a bare
    `curl 127.0.0.1:9222/json/version` proves even less, because a runtime-enabled Chrome
    returns 404 on all four `/json*` endpoints by design.
    """
    pids = subprocess.run(["pgrep", "-f", "Google Chrome"],
                          capture_output=True, text=True).stdout.split()
    found = []
    for pid in pids:
        r = subprocess.run(["lsof", "-nP", "-a", "-p", pid, "-iTCP", "-sTCP:LISTEN"],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 9:
                found.append(parts[8])
    return found


def check_debug_server() -> Check:
    socks = _chrome_listening()
    port_file = PORT_FILE.read_text().strip().splitlines() if PORT_FILE.exists() else []
    ok = bool(socks) or bool(port_file)
    if ok:
        detail = (f"bound — port file {port_file[0] if port_file else 'absent'}, "
                  f"listening {socks or 'none reported'}")
    else:
        detail = "NOT bound — no port file and no Chrome process listening on any TCP port"
    return Check(
        "debug_server_bound", ok, detail, INFO if ok else HUMAN,
        None if ok else (
            "THIS ONE IS NOT YOURS TO FIX. Ask the user, in words, to open "
            "chrome://inspect/#remote-debugging and tick 'Allow remote debugging for this "
            "browser instance', then re-run this check. The setting is PER INSTANCE and "
            "persists in no preference file, so it is lost on every Chrome restart and "
            "'he enabled it yesterday' is never a reason to skip this. That page also shows "
            "'Server running at: <address>' — if it reads 'starting…' the toggle is on and "
            "the server still has not bound, which is a different and unexplained failure "
            "(see your browser-automation notes). Do NOT debug the "
            "transport, start the presser, or curl anything until this is bound."))


def _mcp_servers() -> dict:
    try:
        return json.loads(CLAUDE_JSON.read_text()).get("mcpServers") or {}
    except (OSError, ValueError):
        return {}


def check_autoconnect_server() -> Check:
    """Is a browser MCP declared that ATTACHES to the user's Chrome rather than launching its own?

    Without this the only browser MCP is the plugin's, which declares no args and therefore
    runs with `autoConnect: false` -- its documented default -- and launches a throwaway
    profile at ~/.cache/chrome-devtools-mcp/chrome-profile. That browser is not signed into
    anything, so `list_pages` can never find a ChatGPT tab, and any experiment run through it
    is an experiment on the wrong browser.
    """
    hits = [name for name, cfg in _mcp_servers().items()
            if any("autoconnect" in str(a).lower() for a in (cfg.get("args") or []))]
    return Check(
        "autoconnect_mcp_declared", bool(hits),
        (f"declared: {hits} — call its tools as mcp__{hits[0]}__*" if hits
         else "no MCP server declares --autoConnect; the only browser MCP launches its OWN "
              "throwaway Chrome, which is signed into nothing"),
        INFO if hits else AGENT,
        None if hits else (
            "claude mcp add --scope user chrome-mine -- "
            "npx -y chrome-devtools-mcp@1.10.1 --autoConnect --channel stable    "
            "(then RESTART Claude Code: an MCP config change does not take effect in the "
            "running session). Leave the plugin's copy enabled as a fallback — it is the only "
            "browser access that works when the toggle above is not bound."))


def check_browser_mcps() -> Check:
    """Tell the session what tool names it actually has. Guessing this cost a whole detour:
    the first machine's recipe says `mcp__chrome-mine__list_pages`, which does not exist on a machine
    where that server was never declared."""
    names = [n for n in _mcp_servers() if "chrome" in n.lower()]
    plugin = "chrome-devtools-mcp" in (CLAUDE_JSON.read_text() if CLAUDE_JSON.exists() else "")
    parts = [f"hand-declared: {names or 'none'}"]
    if plugin:
        parts.append("plugin chrome-devtools present "
                     "(prefix mcp__plugin_chrome-devtools-mcp_chrome-devtools__*, "
                     "launches its own Chrome)")
    return Check("browser_mcps", True, "; ".join(parts), INFO)


def check_enrolled(cwd: pathlib.Path) -> Check:
    cfg = cwd / ".consult" / "config.json"
    ok = False
    if cfg.exists():
        try:
            ok = bool(json.loads(cfg.read_text()).get("remote_consult"))
        except ValueError:
            ok = False
    return Check("repo_enrolled", ok,
                 f"{cwd.name}: {'enrolled' if ok else 'NOT enrolled — sends fall back to draft'}",
                 INFO if ok else AGENT,
                 None if ok else f"python3 {REPO}/bin/consult.py --enroll   (run from {cwd})")


def check_presser_hook() -> Check:
    """Is the PreToolUse hook that arms the presser before raw browser-MCP calls registered HERE?
    ~/.claude/settings.json is in no repo, so a hook registered on one Mac is absent on the others
    with nothing reporting it. The hook may be absent on one Mac, and a raw browser-MCP call then leaves a sheet for the user to click."""
    settings = pathlib.Path.home() / ".claude" / "settings.json"
    try:
        hooks = json.loads(settings.read_text()).get("hooks", {}).get("PreToolUse", [])
    except (OSError, ValueError) as e:
        return Check("presser_hook", False, f"cannot read {settings}: {e}", UNDETERMINED)
    ok = "arm-allow-presser" in json.dumps(hooks)
    return Check("presser_hook", ok,
                 "PreToolUse arm-allow-presser hook " + ("registered" if ok else "NOT registered on this machine"),
                 INFO, None if ok else (
                     "Register the arm-allow-presser script as a PreToolUse hook "
                     "matching mcp__chrome-mine__.*|mcp__plugin_chrome-devtools.* in "
                     "~/.claude/settings.json (a config change: needs the user's yes)."))


def check_presser() -> Check:
    if not PRESSER.exists():
        return Check("allow_presser", False, f"{PRESSER} is missing", INFO,
                     "Expected in this repo; the Allow sheet then has to be pressed another way.")
    running = bool(subprocess.run(["pgrep", "-f", "keep-allowing.sh"],
                                  capture_output=True, text=True).stdout.strip())
    return Check("allow_presser", True,
                 f"available; currently {'RUNNING' if running else 'not running'}", INFO,
                 None if running else (
                     f"{PRESSER} 900 &   — start it BEFORE any CDP call, but only once the "
                     f"debug server is bound. With nothing bound, no connection is attempted, "
                     f"so no sheet can ever appear and a run that reports 'no sheet appeared' "
                     f"is uninformative rather than a failure."))


def check_chatgpt_auth(debug_ok: bool) -> Check:
    """Is the ChatGPT session signed in on a paid plan — read from the live browser?

    🔴 **The check this preflight was missing.** On 2026-09-30 both chatgpt.com tabs read
    `plan: "guest"` while every check above reported green, so a lapsed session could run
    a consult that something weaker answered and the ledger would record the strong
    `reviewer_model` the recipe claims. See `chatgpt_auth.py` for the full account.

    It fails CLOSED in the honest direction: when the transport is down, no chatgpt.com
    tab is open, or the payload will not parse, the verdict is UNDETERMINED — reported
    as its own category, never folded into "all preconditions met". Finding nothing is
    not the same as finding nothing wrong.

    It never opens or navigates a tab — `ca.attach_readonly`, NOT `reuse_page`, which
    issues `Page.navigate` and would move a conversation he is reading. With no
    chatgpt.com tab already open this reports UNDETERMINED and says to open one.

    ⚠️ **A cookie-only read of the accounts endpoint always says "guest".** That is the
    bug this check once shipped with: it reported a signed-in user as signed out, and `consult.py` refused every consult on the
    strength of it. `chatgpt_auth` now reads the bearer token first; the UNKNOWN verdict
    covers the case where it cannot.
    """
    if not debug_ok:
        return Check("chatgpt_signed_in", False,
                     "cannot tell — the debug server is not bound, so the session is "
                     "unreadable from here", UNDETERMINED,
                     "Fix debug_server_bound first; this check is downstream of it.")
    try:
        sys.path.insert(0, str(REPO / "bin"))
        import broker as bk                                      # noqa: PLC0415
        import chatgpt_auth as ca                                # noqa: PLC0415
    except ImportError as e:
        return Check("chatgpt_signed_in", False,
                     f"cannot tell — {e}", UNDETERMINED, None)

    if bk.ping() is None:
        return Check("chatgpt_signed_in", False,
                     "cannot tell — the broker is not running, and starting one just to "
                     "read the plan would cost an approval sheet. It starts on the first "
                     "consult; re-run this then.", UNDETERMINED,
                     f"{BROKER} --ensure   (or simply run the consult and read its log)")
    client = None
    try:
        client = bk.BrokerClient(label="preflight auth read")
        sid = ca.attach_readonly(client)
        if not sid:
            return Check("chatgpt_signed_in", False,
                         "cannot tell — no chatgpt.com tab is open, and this check will "
                         "not open or navigate one", UNDETERMINED,
                         "Ask the user to leave a chatgpt.com tab open, or run the consult, "
                         "which opens one itself.")
        v = ca.read_plan(client, sid)
    except Exception as e:                                       # noqa: BLE001
        return Check("chatgpt_signed_in", False,
                     f"cannot tell — {type(e).__name__}: {e}", UNDETERMINED, None)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:                                    # noqa: BLE001, S110
                pass

    if ca.is_usable(v):
        return Check("chatgpt_signed_in", True, ca.describe(v), INFO)
    if v["state"] == ca.GUEST:
        return Check(
            "chatgpt_signed_in", False, ca.describe(v), HUMAN,
            "Ask the user, in words, to sign back in to chatgpt.com. Do NOT run a consult "
            "first: it will appear to work, something weaker will answer, and the ledger "
            "will record the reviewer_model the recipe claims rather than the one that "
            "replied. A review logged as frontier scrutiny and answered anonymously is "
            "worse than no review.")
    if v["state"] == ca.SIGNED_IN:
        return Check(
            "chatgpt_signed_in", False, ca.describe(v), HUMAN,
            f"Signed in, but plan {v['plan']!r} is not a tier this check recognises as "
            f"able to answer at the strength the ledger records. Confirm with the user before "
            f"logging a consult against it.")
    return Check("chatgpt_signed_in", False, ca.describe(v), UNDETERMINED, None)


def check_broker() -> Check:
    if not BROKER.exists():
        return Check("broker", False, "broker.py missing", INFO)
    r = subprocess.run([sys.executable, str(BROKER), "--status"],
                       capture_output=True, text=True)
    try:
        st = json.loads(r.stdout)
    except ValueError:
        return Check("broker", False, "not running (it starts on the first consult)", INFO)
    return Check(
        "broker", True,
        f"pid {st.get('pid')}, connected={st.get('connected')}, "
        f"browser_connections={st.get('browser_connections')}, epoch={st.get('epoch')}", INFO,
        None if st.get("connected") else (
            "⚠️ `connected: false` is NOT only a sheet question. Read it together with "
            "debug_server_bound above: if nothing is bound, the broker cannot connect and no "
            "amount of sheet-pressing will change that."))


# -- fixing ----------------------------------------------------------------

def apply_fixes(checks, cwd) -> list[str]:
    """Do the AGENT-owned fixes. Never claims to have fixed a HUMAN-owned one."""
    done = []
    for c in checks:
        if c.ok or c.user != AGENT:
            continue
        if c.name == "autoconnect_mcp_declared":
            if not shutil.which("claude"):
                done.append("autoconnect_mcp_declared: SKIPPED, `claude` not on PATH")
                continue
            r = subprocess.run(
                ["claude", "mcp", "add", "--scope", "user", "chrome-mine", "--",
                 "npx", "-y", "chrome-devtools-mcp@1.10.1", "--autoConnect",
                 "--channel", "stable"], capture_output=True, text=True)
            done.append(f"autoconnect_mcp_declared: {'declared chrome-mine — RESTART Claude Code' if r.returncode == 0 else 'FAILED: ' + (r.stderr or r.stdout).strip()[:160]}")
        elif c.name == "repo_enrolled":
            r = subprocess.run([sys.executable, str(REPO / "bin" / "consult.py"), "--enroll"],
                               cwd=str(cwd), capture_output=True, text=True)
            done.append(f"repo_enrolled: {'enrolled' if r.returncode == 0 else 'FAILED: ' + (r.stderr or r.stdout).strip()[:160]}")
    return done


def run(cwd: pathlib.Path, auth: bool = True):
    debug = check_debug_server()
    checks = [check_chrome_running(), debug, check_autoconnect_server(),
              check_browser_mcps(), check_enrolled(cwd), check_presser(), check_presser_hook(), check_broker()]
    if auth:
        # Last, and given the debug verdict rather than re-deriving it: the session read
        # is downstream of the transport, and a check that silently re-tests its own
        # precondition is how two layers disagree about the same fact.
        checks.append(check_chatgpt_auth(debug.ok))
    return checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true",
                    help="apply the fixes this agent owns; never the toggle")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--no-auth", dest="auth", action="store_false",
                    help="skip the live ChatGPT session read (it needs the broker and "
                         "an open tab); the other checks are offline")
    args = ap.parse_args(argv)

    cwd = pathlib.Path.cwd()
    checks = run(cwd, auth=args.auth)
    fixes = apply_fixes(checks, cwd) if args.fix else []
    if fixes:
        checks = run(cwd, auth=args.auth)

    blocked = [c for c in checks if not c.ok and c.user == HUMAN]
    fixable = [c for c in checks if not c.ok and c.user == AGENT]
    unknown = [c for c in checks if not c.ok and c.user == UNDETERMINED]

    if args.as_json:
        print(json.dumps({"machine": _machine(), "cwd": str(cwd),
                          "checks": [c.as_dict() for c in checks],
                          "fixes_applied": fixes,
                          "blocked_on_human": [c.name for c in blocked],
                          "fixable_by_agent": [c.name for c in fixable],
                          "undetermined": [c.name for c in unknown]}, indent=2))
    else:
        print(f"consult preflight — machine {_machine()}, cwd {cwd}\n")
        for c in checks:
            mark = 'ok ' if c.ok else ('?? ' if c.user == UNDETERMINED else 'XX ')
            print(f"  [{mark}] {c.name}: {c.detail}")
            if c.remedy:
                for i, line in enumerate(c.remedy.split("    ")):
                    print(f"          {'-> ' if i == 0 else '   '}{line.strip()}")
        for f in fixes:
            print(f"\n  FIXED: {f}")
        if blocked:
            print(f"\n🔴 BLOCKED ON A HUMAN: {', '.join(c.name for c in blocked)}. "
                  f"Do not work around this by debugging the transport.")
        elif fixable:
            print(f"\n⚠️  FIXABLE BY YOU: {', '.join(c.name for c in fixable)} — re-run with --fix")
        elif unknown:
            # NOT "all preconditions met". A check that could not see anything has not
            # cleared anything, and saying otherwise is the bug the auth check exists
            # to fix, reproduced one layer up.
            print(f"\n❔ COULD NOT DETERMINE: {', '.join(c.name for c in unknown)}. "
                  f"Everything else on this machine is met; these are unread, not clear.")
        else:
            print("\nAll preconditions met on this machine.")
    return 1 if blocked else (2 if fixable else 0)


if __name__ == "__main__":
    raise SystemExit(main())
