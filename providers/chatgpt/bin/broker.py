#!/usr/bin/env python3
"""One long-lived CDP connection, shared by every Claude Code instance on this Mac.

## Why this exists

Chrome raises its "Allow remote debugging?" sheet on **every incoming websocket connection**, and
the Chromium dialog code calls `Activate()` on the browser window before showing it. So each
connection costs the user a ~1s theft of focus, and that cost is per connection rather than per
session. Measured 2026-09-26: three `CDP()` constructions in one process raised three sheets.

There is no way to switch that off on the user's normal profile. The runtime toggle at `chrome://inspect`
starts the DevTools server in `kWithApprovalOnly`, which requires approval per connection.
`--remote-debugging-port` does start in the no-approval mode, but since Chrome 136 the switch is
ignored unless Chrome runs on a non-default `--user-data-dir` — a different profile, therefore not
the logged-in ChatGPT session.

So the only lever is **fewer connections**. Every consult borrows one connection through this broker.

## The connection is not ours: it is the extension bridge's

The broker used to open its own websocket (`cdp_client.CDP`) and spawn its own presser. Now it
speaks to an extension bridge's unix socket via `BridgeCDP` below and owns no connection to Chrome.
Everything else here is unchanged: the lease, the allowlist, the origin re-check, one tab per
thread, `Input.insertText` and the trusted Enter, its own socket and idle exit.

**Default: the extension bridge** (`chrome-ext-bridge.mjs`, socket
`chrome-ext-bridge.sock` in your state dir). CDP runs through the extension's
`chrome.debugger`, so there is no "Allow remote debugging?" sheet and Chrome never comes frontmost.
Its tabs are in the user's own profile (their chatgpt.com cookies apply) but live in the extension's own
unfocused window, and `Target.getTargets` lists ONLY those tabs: `reuse_page` reuses the
extension's chatgpt.com tab and can no longer see, or navigate, one of the user's. A background agent keeps
that bridge up; if the extension is not connected the connect fails by name (EXT_NOT_CONNECTED)
and does NOT fall back to the sheet-raising route.

**Opt-in fallback: `CDP_TRANSPORT=ws`** selects the websocket bridge
(`tools/cdp-bridge.mjs`, `cdp-bridge.sock` in your state dir): sees all of the user's tabs, costs an Allow sheet
per bridge lifetime and can activate Chrome. `$CDP_BRIDGE_SOCK` overrides either socket.

Both bridges have the `session {targetId, method, params}` command. The non-flattened
`Target.sendMessageToTarget` fallback below is kept for an old ws bridge without it (ws only; the
extension refuses browser-level methods other than Target.getTargets/createTarget/closeTarget).

## Why it is also a queue, in the Fetcher style

Several Claude Code instances may run on one machine at once and share one ChatGPT account and
one thread per repo. Two consults posting concurrently would interleave prompts and replies in the
same conversation, and concurrent polling is exactly what has driven `/backend-api/conversations`
to 429 before. So the broker hands out a **single FIFO lease**: one consult runs at a time, the
rest wait their turn. Serialization is the feature, not a limitation — and it is the reason this is
a broker rather than a connection cache.

A lease is released when its holder releases it **or when its connection drops**, because a crashed
instance holding a lease forever would wedge every other instance on the machine.

## What authority this hands out, stated plainly

The long-lived websocket has full control of the user's authenticated browser. A generic "run any CDP
command" service on a local socket would therefore be a privilege-amplification API for every
process running as the user. It is bounded two ways instead:

* a **method allowlist** — the dozen CDP methods this tool actually uses, nothing else;
* an **origin restriction** — targets may only be created on, navigated to, or attached to
  `https://chatgpt.com`, and JS may only be evaluated in sessions the broker itself attached.

That still means "arbitrary JS in a ChatGPT tab", which is inherent: the tool reads
`/backend-api/...` from inside the page. What it is not is access to every other tab he has open.
The socket lives in a 0700 directory, is chmod 0600, and is not a TCP port.

Usage:
    broker.py --serve [--idle-exit SECONDS]   # run in the foreground (what --ensure spawns)
    broker.py --ensure                        # start one if not already running; print its status
    broker.py --status
    broker.py --shutdown
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp_client import CDPError, CDPSession  # noqa: E402

RUN_DIR = Path.home() / ".cache/chatgpt-consult"
SOCK = RUN_DIR / "broker.sock"
LOG = RUN_DIR / "broker.log"

# Four hours of idleness, then exit. A process holding full authority over the user's browser should not
# live forever unattended, and the cost of it being gone is one approval sheet.
IDLE_EXIT_DEFAULT = 4 * 3600

ALLOWED_ORIGINS = ("https://chatgpt.com",)

# Exactly what consult.py calls. Adding to this list widens what any local process can do with the user's
# browser, so it is a deliberate edit, not a convenience.
ALLOWED_METHODS = frozenset({
    "Browser.getVersion",
    "Target.getTargets",
    "Target.createTarget",
    "Target.attachToTarget",
    "Target.closeTarget",
    "Runtime.enable",
    "Runtime.evaluate",
    "Page.navigate",
    "Input.insertText",
    "Input.dispatchKeyEvent",
    "Emulation.setFocusEmulationEnabled",
})

# Methods that must never be reachable even if someone widens the list carelessly. activateTarget
# and bringToFront exist only to pull a tab in front of the user, which is the whole thing this
# broker was built to avoid.
DENIED_METHODS = frozenset({"Target.activateTarget", "Page.bringToFront",
                            "Browser.setWindowBounds", "Target.setDiscoverTargets"})

# Pure reads, safe to repeat after a dropped socket. Chrome does drop an idle DevTools websocket
# (measured 2026-09-26: `socket closed mid-frame` between consults), and the first call of the next
# consult is `Target.getTargets`, so replaying just these turns "the broker was idle too long" from a
# failed consult into an invisible reconnect.
#
# Nothing that MUTATES is in here, and that is the important half. `Runtime.evaluate` looks like a
# read and is not — the JS this tool runs POSTs to /backend-api — and `Input.*` is how a prompt gets
# submitted. Replaying either could post twice off one ambiguous failure, which is exactly the
# at-least-once bug the submit path is built to avoid.
SAFE_TO_REPLAY = frozenset({"Browser.getVersion", "Target.getTargets"})

# Methods that ACT on an attached session, and therefore need the session's target re-checked against
# the origin allowlist every single time.
#
# Checking only at attach time was not a bound at all, and a second-model review named the escape
# before I found it. Verified by probe 2026-09-27: `Page.navigate` off-origin is refused, and then
# `Runtime.evaluate("location.href='https://example.com/'")` navigates the very same tab anyway —
# JavaScript does not need a CDP navigation method. The next evaluate then ran happily against
# `https://example.com`. So the guard was decoration for every call after the first.
#
# Re-checking per call is deliberately NOT cached behind a TTL: a TTL is precisely the window an
# escape would aim for. The cost is one extra local CDP roundtrip per call.
NEEDS_ON_ORIGIN_SESSION = frozenset({"Runtime.evaluate", "Input.insertText",
                                     "Input.dispatchKeyEvent", "Page.navigate",
                                     "Emulation.setFocusEmulationEnabled"})


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, file=sys.stderr, flush=True)


def allowed_url(url: str) -> bool:
    return any((url or "").startswith(o) for o in ALLOWED_ORIGINS)


# ---------------------------------------------------------------------- the bridge transport

def machinist_tools() -> Path:
    return Path(os.environ.get("MACHINIST_TOOLS") or Path("Machinist-tools"))


def bridge_transport() -> str:
    """`ext` (default) or `ws`, from CDP_TRANSPORT, read at call time. Anything else is refused."""
    t = os.environ.get("CDP_TRANSPORT") or "ext"
    if t not in ("ext", "ws"):
        raise CDPError(f"CDP_TRANSPORT must be ext or ws, not {t!r}")
    return t


def bridge_sock() -> Path:
    """Same resolution as cdp-client.cjs, read at call time so a test can point it elsewhere."""
    if os.environ.get("CDP_BRIDGE_SOCK"):
        return Path(os.environ["CDP_BRIDGE_SOCK"])
    name = "chrome-ext-bridge.sock" if bridge_transport() == "ext" else "cdp-bridge.sock"
    return Path(os.environ.get("LODESTAR_STATE_DIR", ".lodestar")) / name


# The fallback route sends session methods blind (Target.sendMessageToTarget), so give Chrome a
# moment before the next read observes their effect.
BLIND_SETTLE_S = 0.3


class BridgeCDP:
    """`call(method, params, session_id)` over the extension bridge's unix socket. Owns no websocket.

    Session ids handed out here are virtual (`<targetId>|<nonce>`): the bridge keys its sessions by
    target, so attaching is local bookkeeping after the broker has checked the target's live origin.
    `close()` closes nothing on the wire: the bridge's connection is shared machine-wide.
    """

    def __init__(self, wait: float = 60.0):
        self.wait = wait
        self.has_session_cmd: bool | None = None     # learned on the first session-scoped call
        self._blind: dict[str, str] = {}             # targetId -> non-flattened sessionId

    # -- wire
    def request(self, req: dict, wait: float | None = None) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(wait or self.wait)
        try:
            s.connect(str(bridge_sock()))
            fh = s.makefile("rwb")
            fh.write(json.dumps({"id": 1, **req}).encode() + b"\n")
            fh.flush()
            line = fh.readline()
        except socket.timeout as e:
            raise CDPError(f"bridge request {req.get('cmd')} timed out") from e
        except OSError as e:
            raise CDPError(f"bridge socket {bridge_sock()} unreachable: {e}") from e
        finally:
            s.close()
        if not line:
            raise CDPError("bridge socket closed without answering")
        r = json.loads(line)
        if not r.get("ok"):
            err = str(r.get("error"))
            # The bridge says "CDP timeout"; the broker's drop logic keys on "timed out".
            if "timeout" in err and "timed out" not in err:
                err += " (timed out)"
            raise CDPError(err)
        return r.get("result")

    def alive(self) -> bool:
        try:
            return bool((self.request({"cmd": "ping"}, wait=2) or {}).get("pong"))
        except (CDPError, ValueError):
            return False

    def connected(self) -> bool:
        try:
            return bool((self.request({"cmd": "status"}, wait=3) or {}).get("connected"))
        except (CDPError, ValueError):
            return False

    def connect(self) -> None:
        """Get the bridge up and holding an accepted Chrome connection.

        Already connected: nothing to do, no sheet. Otherwise the bridge's own client does it
        (`tools/cdp connect`, on the same transport and socket: over ext it starts the bridge if
        needed and waits for the extension, failing by name; over ws it runs the presser).
        The broker never presses a sheet itself, so two pressers can no longer race one sheet.
        """
        self.has_session_cmd = None
        self._blind.clear()
        if self.alive() and self.connected():
            return
        cli = machinist_tools() / "cdp"
        node = shutil.which("node")
        if not node or not cli.exists():
            raise CDPError(f"cannot reach the extension bridge: node={node!r}, {cli} "
                           f"exists={cli.exists()}")
        try:
            env = {**os.environ, "CDP_TRANSPORT": bridge_transport(),
                   "CDP_BRIDGE_SOCK": str(bridge_sock())}
            r = subprocess.run([node, str(cli), "connect"], capture_output=True, text=True,
                               timeout=150, stdin=subprocess.DEVNULL, env=env)
        except subprocess.TimeoutExpired as e:
            raise CDPError("`tools/cdp connect` did not finish in 150s") from e
        if r.returncode != 0 or not self.connected():
            raise CDPError(f"`tools/cdp connect` failed (rc={r.returncode}): "
                           f"{(r.stderr or r.stdout).strip()[-300:]}")

    def close(self) -> None:
        self._blind.clear()

    # -- CDP
    @staticmethod
    def target_of(session_id: str) -> str:
        return session_id.split("|", 1)[0]

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        params = params or {}
        if not session_id:
            if method == "Target.attachToTarget":
                return {"sessionId": f"{params['targetId']}|{uuid.uuid4().hex[:8]}"}
            if method == "Target.closeTarget":
                self._blind.pop(params.get("targetId") or "", None)
            return self.request({"cmd": "browser", "method": method, "params": params}) or {}
        tid = self.target_of(session_id)
        if self.has_session_cmd is not False:
            try:
                r = self.request({"cmd": "session", "targetId": tid, "method": method,
                                  "params": params})
                self.has_session_cmd = True
                return r or {}
            except CDPError as e:
                if "unknown cmd" not in str(e):
                    raise
                self.has_session_cmd = False
                log("bridge has no `session` command; using eval + blind sendMessageToTarget")
        return self._fallback(tid, method, params)

    def _fallback(self, tid: str, method: str, params: dict) -> dict:
        if method == "Runtime.enable":
            return {}                       # the bridge's eval needs no enable
        if method == "Runtime.evaluate":
            # The bridge's eval always sets awaitPromise and returnByValue. awaitPromise is a no-op
            # on a non-promise value, and every caller here passes returnByValue.
            return self.request({"cmd": "eval", "targetId": tid,
                                 "js": params.get("expression", "")}) or {}
        sid = self._blind.get(tid)
        if sid is None:
            sid = self.request({"cmd": "browser", "method": "Target.attachToTarget",
                                "params": {"targetId": tid, "flatten": False}})["sessionId"]
            self._blind[tid] = sid
        msg = {"id": int(time.time() * 1000) % 1_000_000_000, "method": method, "params": params}
        self.request({"cmd": "browser", "method": "Target.sendMessageToTarget",
                      "params": {"sessionId": sid, "message": json.dumps(msg)}})
        time.sleep(BLIND_SETTLE_S)
        return {}


class Broker:
    """Owns the websocket, the lease queue, and the authority bounds."""

    def __init__(self, idle_exit: float = IDLE_EXIT_DEFAULT):
        self.idle_exit = idle_exit
        self.lock = threading.Lock()            # serializes CDP traffic
        self.cdp: BridgeCDP | None = None
        self.epoch: str | None = None
        self.connections = 0
        self.calls = 0
        self.refusals = 0
        self.started = time.time()
        self.last_activity = time.time()
        self.clients = 0

        # Our own sessions and tabs, so evaluate/close cannot be aimed at the user's tabs. Keyed by
        # (client id, session id) rather than session id alone: a review pointed out that a global
        # map lets one instance act through a session another instance attached, which is the same
        # ambient-authority shape the allowlist exists to remove. Ownership is per client.
        self.sessions: dict[tuple[int, str], str] = {}   # (client, sessionId) -> targetId
        self.our_targets: dict[str, int] = {}            # targetId -> owning client

        # FIFO lease
        self.lease_cv = threading.Condition()
        self.lease_holder: tuple[int, str] | None = None   # (client id, label)
        self.lease_since: float | None = None
        self.waiting: deque[int] = deque()

    # ---------------------------------------------------------------- connection

    def _connect_locked(self) -> None:
        """Borrow the extension bridge's one websocket. Caller holds self.lock.

        No `CDP()`, no presser, no focus juggling here any more: the bridge path owns the sheet
        (see the module docstring). An epoch now marks one broker-side attachment to the bridge.
        """
        cdp = BridgeCDP()
        cdp.connect()
        self.cdp = cdp
        self.epoch = uuid.uuid4().hex[:12]
        self.connections += 1
        # Every id from a previous epoch is meaningless now; never try to resurrect one.
        self.sessions.clear()
        self.our_targets.clear()
        log(f"attached to the extension bridge, epoch={self.epoch} (connection #{self.connections})")

    def ensure_connection_locked(self) -> None:
        """Reconnect lazily — only when a request actually needs the wire.

        Eager reconnection is the wrong shape here: a retry loop against a dead socket would raise
        an approval sheet on every attempt, stacking modals on the user's screen. So a dead connection
        stays dead until someone has real work.
        """
        if self.cdp is None:
            self._connect_locked()

    def drop_locked(self, why: str) -> None:
        log(f"connection dropped ({why}); epoch {self.epoch} is now void")
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass
        self.cdp = None
        self.epoch = None
        self.sessions.clear()
        self.our_targets.clear()

    # ---------------------------------------------------------------- authority

    def check(self, method: str, params: dict, session_id: str | None,
              client_id: int) -> str | None:
        """None if allowed, else the reason for refusal."""
        if method in DENIED_METHODS:
            return f"{method} is explicitly denied: it exists to pull a tab in front of the user"
        if method not in ALLOWED_METHODS:
            return (f"{method} is not in the broker's allowlist. The broker is deliberately not a "
                    f"general CDP proxy; widen ALLOWED_METHODS in broker.py if this is genuinely "
                    f"needed.")
        url = params.get("url")
        if method in ("Target.createTarget", "Page.navigate"):
            if not allowed_url(url or ""):
                return f"refusing to open or navigate to {url!r}: only {ALLOWED_ORIGINS} are allowed"
        if method in ("Runtime.evaluate", "Runtime.enable", "Input.insertText",
                      "Input.dispatchKeyEvent", "Page.navigate",
                      "Emulation.setFocusEmulationEnabled") and session_id:
            if (client_id, session_id) not in self.sessions:
                return ("that session was not attached by YOU through this broker (it may belong to "
                        "another client or to a previous connection epoch); re-attach and retry")
        if method == "Target.closeTarget":
            if self.our_targets.get(params.get("targetId") or "") != client_id:
                return "refusing to close a tab you did not open through this broker"
        return None

    def _target_info_locked(self, target_id: str | None) -> dict | None:
        """Live TargetInfo for a target id. Caller holds self.lock."""
        assert self.cdp is not None
        for t in self.cdp.call("Target.getTargets")["targetInfos"]:
            if t.get("targetId") == target_id:
                return t
        return None

    def cdp_call(self, method: str, params: dict, session_id: str | None,
                 want_epoch: str | None, client_id: int) -> dict:
        with self.lock:
            self.last_activity = time.time()
            self.ensure_connection_locked()
            if want_epoch and want_epoch != self.epoch:
                raise StaleEpoch(f"your ids are from epoch {want_epoch}; the broker is now on "
                                 f"{self.epoch}. Re-resolve the thread; do not reuse old ids.")
            # attachToTarget needs the target's CURRENT url, which only the browser knows.
            if method == "Target.attachToTarget":
                tid = params.get("targetId")
                info = self._target_info_locked(tid)
                if info is None:
                    raise CDPError(f"no such target {tid}")
                if not allowed_url(info.get("url") or ""):
                    self.refusals += 1
                    raise Refused(f"refusing to attach to {info.get('url')!r}: only "
                                  f"{ALLOWED_ORIGINS} are allowed")
            # Re-verify the session's LIVE origin, because JS can navigate a tab out from under an
            # attach-time check. See NEEDS_ON_ORIGIN_SESSION.
            if method in NEEDS_ON_ORIGIN_SESSION and session_id:
                tid = self.sessions.get((client_id, session_id))
                info = self._target_info_locked(tid) if tid else None
                here = (info or {}).get("url") or ""
                if not allowed_url(here):
                    self.refusals += 1
                    raise Refused(
                        f"refusing {method}: that session's tab is now at {here[:80]!r}, outside "
                        f"{ALLOWED_ORIGINS}. A session is re-checked on every call because JS can "
                        f"navigate a tab without using a CDP navigation method.")
            why = self.check(method, params, session_id, client_id)
            if why:
                self.refusals += 1
                raise Refused(why)
            try:
                result = self.cdp.call(method, params, session_id=session_id)
            except CDPError as e:
                # A stalled read counts as a dead connection, not a recoverable error.
                # `_recv_exact` can abandon a partially-read frame, leaving the stream
                # desynchronized, and continuing to use it would eventually mis-parse someone
                # else's frame as a reply.
                if not any(w in str(e) for w in ("closed", "socket", "timed out", "disconnected")):
                    raise
                self.drop_locked(str(e))
                if method not in SAFE_TO_REPLAY or session_id:
                    raise ConnectionLost(
                        f"the browser connection died during {method}. It was NOT replayed, because "
                        f"repeating it could act twice. Re-resolve and retry; the next call "
                        f"reconnects.") from e
                self.ensure_connection_locked()
                log(f"replayed {method} on epoch {self.epoch} after a dropped socket")
                result = self.cdp.call(method, params, session_id=session_id)
            self.calls += 1
            if method == "Target.getTargets":
                # Annotate rather than overwrite `attached`. A tab is skipped for reuse when it is
                # attached by SOMEONE ELSE, but the broker's own attachments also set `attached`, so a
                # bare check would make every tab unreusable from the second consult onward — and
                # creating a fresh tab each time is the 19-leaked-tabs failure that tab reuse exists
                # to prevent. `brokerOwned` is additive so the real protocol field stays truthful.
                ours = set(self.sessions.values()) | set(self.our_targets)
                for t in result.get("targetInfos", []):
                    t["brokerOwned"] = t.get("targetId") in ours
            elif method == "Target.createTarget":
                self.our_targets[result["targetId"]] = client_id
            elif method == "Target.attachToTarget":
                self.sessions[(client_id, result["sessionId"])] = params.get("targetId")
            elif method == "Target.closeTarget":
                self.our_targets.pop(params.get("targetId") or "", None)
            return result

    # ---------------------------------------------------------------- the lease

    def acquire(self, client_id: int, label: str, wait: float) -> dict:
        ticket = client_id
        deadline = time.time() + wait
        with self.lease_cv:
            self.waiting.append(ticket)
            try:
                while True:
                    if self.lease_holder is None and self.waiting[0] == ticket:
                        self.waiting.popleft()
                        self.lease_holder = (client_id, label)
                        self.lease_since = time.time()
                        log(f"lease -> {label} (client {client_id})")
                        return {"granted": True, "epoch": self.epoch,
                                "waited": round(time.time() - (deadline - wait), 1)}
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        try:
                            self.waiting.remove(ticket)
                        except ValueError:
                            pass
                        held = self.lease_holder[1] if self.lease_holder else "nobody"
                        return {"granted": False,
                                "reason": f"another consult is running ({held}); waited {wait:.0f}s",
                                "queue_depth": len(self.waiting)}
                    self.lease_cv.wait(min(remaining, 1.0))
            finally:
                self.lease_cv.notify_all()

    def release(self, client_id: int, reason: str = "released") -> bool:
        with self.lease_cv:
            if self.lease_holder and self.lease_holder[0] == client_id:
                log(f"lease released by {self.lease_holder[1]} ({reason}, "
                    f"held {time.time() - (self.lease_since or 0):.1f}s)")
                self.lease_holder = None
                self.lease_since = None
                self.lease_cv.notify_all()
                return True
            return False

    # ---------------------------------------------------------------- reporting

    def forget_client(self, client_id: int) -> None:
        """Drop a departed client's session handles. Tabs outlive clients; sessions do not."""
        with self.lock:
            for key in [k for k in self.sessions if k[0] == client_id]:
                del self.sessions[key]

    def status(self) -> dict:
        with self.lease_cv:
            holder = self.lease_holder[1] if self.lease_holder else None
            depth = len(self.waiting)
        return {
            "pid": os.getpid(),
            "epoch": self.epoch,
            "connected": self.cdp is not None,
            "browser_connections": self.connections,
            "uptime_s": round(time.time() - self.started, 1),
            "idle_s": round(time.time() - self.last_activity, 1),
            "idle_exit_s": self.idle_exit,
            "cdp_calls": self.calls,
            "refusals": self.refusals,
            "clients": self.clients,
            "lease_holder": holder,
            "queue_depth": depth,
            "our_tabs": len(self.our_targets),
        }


class Refused(RuntimeError):
    pass


class StaleEpoch(RuntimeError):
    pass


class ConnectionLost(RuntimeError):
    """The websocket died mid-call and the call was deliberately not replayed."""


# ---------------------------------------------------------------------- serving


def serve(idle_exit: float) -> int:
    import fcntl
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUN_DIR, stat.S_IRWXU)

    # Single-instance by LOCK, not by "does the socket file exist".
    #
    # The existence check alone loses a race that matters: two consults starting together both see no
    # socket, both spawn a broker, and the loser's cleanup would unlink the WINNER's live socket,
    # leaving every client unable to connect to a broker that is running fine. An exclusive flock is
    # held for the whole process lifetime and is released by the kernel if we die, so a crashed
    # broker does not lock the machine out either.
    lockfh = (RUN_DIR / "broker.lock").open("w")
    try:
        fcntl.flock(lockfh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another broker holds the lock; refusing to start a second")
        return 3
    lockfh.write(f"{os.getpid()}\n")
    lockfh.flush()
    if SOCK.exists():
        # We hold the lock, so any socket here is a leftover from a broker that died.
        SOCK.unlink()

    broker = Broker(idle_exit=idle_exit)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK))
    os.chmod(SOCK, stat.S_IRUSR | stat.S_IWUSR)
    srv.listen(16)
    srv.settimeout(1.0)
    stop = threading.Event()
    log(f"serving on {SOCK} (idle exit {idle_exit:.0f}s)")

    next_client = [0]

    def handle(conn: socket.socket, client_id: int) -> None:
        broker.clients += 1
        fh = conn.makefile("rwb")
        try:
            for raw in fh:
                try:
                    req = json.loads(raw)
                except Exception as e:
                    fh.write(json.dumps({"ok": False, "error": f"bad json: {e}"}).encode() + b"\n")
                    fh.flush()
                    continue
                resp = dispatch(broker, req, client_id, stop)
                fh.write(json.dumps(resp).encode() + b"\n")
                fh.flush()
        except (OSError, ValueError):
            pass
        finally:
            # A client that dies holding the lease must not wedge the machine.
            if broker.release(client_id, reason="client disconnected"):
                log(f"auto-released the lease held by a disconnected client {client_id}")
            broker.forget_client(client_id)
            broker.clients -= 1
            try:
                fh.close()
                conn.close()
            except Exception:
                pass

    try:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                if (broker.clients == 0
                        and time.time() - broker.last_activity > broker.idle_exit):
                    log(f"idle for {broker.idle_exit:.0f}s; exiting")
                    break
                continue
            next_client[0] += 1
            threading.Thread(target=handle, args=(conn, next_client[0]), daemon=True).start()
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        with broker.lock:
            broker.drop_locked("shutting down")
        srv.close()
        SOCK.unlink(missing_ok=True)
        log("stopped")
    return 0


def dispatch(broker: Broker, req: dict, client_id: int, stop: threading.Event) -> dict:
    op = req.get("op")
    try:
        if op == "ping":
            return {"ok": True, "pid": os.getpid(), "epoch": broker.epoch}
        if op == "status":
            return {"ok": True, "status": broker.status()}
        if op == "cdp":
            result = broker.cdp_call(req.get("method", ""), req.get("params") or {},
                                     req.get("session_id"), req.get("epoch"), client_id)
            return {"ok": True, "result": result, "epoch": broker.epoch}
        if op == "lease_acquire":
            r = broker.acquire(client_id, req.get("label") or f"client {client_id}",
                               float(req.get("wait", 600)))
            return {"ok": True, **r}
        if op == "lease_release":
            return {"ok": True, "released": broker.release(client_id)}
        if op == "shutdown":
            stop.set()
            return {"ok": True, "stopping": True}
        return {"ok": False, "error": f"unknown op {op!r}"}
    except Refused as e:
        return {"ok": False, "error": str(e), "code": "REFUSED"}
    except StaleEpoch as e:
        return {"ok": False, "error": str(e), "code": "STALE_EPOCH", "epoch": broker.epoch}
    except ConnectionLost as e:
        return {"ok": False, "error": str(e), "code": "CONNECTION_LOST", "epoch": broker.epoch}
    except CDPError as e:
        return {"ok": False, "error": str(e), "code": "CDP_ERROR", "epoch": broker.epoch}
    except Exception as e:                                   # never kill the serving thread
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "code": "INTERNAL"}


# ---------------------------------------------------------------------- clients


def request(payload: dict, wait: float = 900.0) -> dict:
    """One request over the broker socket. Raises BrokerUnavailable if nothing is listening."""
    if not SOCK.exists():
        raise BrokerUnavailable(f"no broker socket at {SOCK}")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(wait)
    try:
        s.connect(str(SOCK))
    except OSError as e:
        raise BrokerUnavailable(f"broker socket present but not accepting: {e}") from e
    try:
        fh = s.makefile("rwb")
        fh.write(json.dumps(payload).encode() + b"\n")
        fh.flush()
        line = fh.readline()
        if not line:
            raise BrokerUnavailable("broker closed the connection without answering")
        return json.loads(line)
    finally:
        s.close()


class BrokerUnavailable(RuntimeError):
    pass


def ping() -> dict | None:
    try:
        r = request({"op": "ping"}, wait=5)
        return r if r.get("ok") else None
    except (BrokerUnavailable, OSError, json.JSONDecodeError):
        return None


def ensure(idle_exit: float = IDLE_EXIT_DEFAULT) -> dict | None:
    """Start a broker if none is running. Returns its ping, or None if it could not be started."""
    p = ping()
    if p:
        return p
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if SOCK.exists() and ping() is None:
        SOCK.unlink(missing_ok=True)          # stale socket from a broker that died
    # Two attempts, because a broker that is still shutting down holds the single-instance lock: the
    # first spawn then exits 3 and there is nothing to ping. Retrying once after the lock frees turns
    # "you shut it down a second ago" from a failed consult into a short wait.
    for attempt in (1, 2):
        with LOG.open("a") as logfh:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve",
                 "--idle-exit", str(int(idle_exit))],
                stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL,
                start_new_session=True)
        for _ in range(40):
            time.sleep(0.25)
            p = ping()
            if p:
                return p
        if attempt == 1:
            time.sleep(1.0)
    return None


class BrokerClient(CDPSession):
    """A CDPSession whose `call` goes through the broker instead of its own websocket.

    Holds the epoch it first saw and sends it with every call, so ids left over from a reconnect are
    refused loudly (`STALE_EPOCH`) instead of failing as a puzzling CDP error.
    """

    def __init__(self, label: str = "consult", wait: float = 900.0):
        p = ping()
        if not p:
            raise BrokerUnavailable("no broker running")
        self.epoch = p.get("epoch")
        self.label = label
        self.wait = wait
        self._sock: socket.socket | None = None
        self._fh = None
        self._connect()

    def _connect(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.wait)
        s.connect(str(SOCK))
        self._sock, self._fh = s, s.makefile("rwb")

    def _rpc(self, payload: dict) -> dict:
        assert self._fh is not None
        self._fh.write(json.dumps(payload).encode() + b"\n")
        self._fh.flush()
        line = self._fh.readline()
        if not line:
            raise BrokerUnavailable("broker closed the connection")
        return json.loads(line)

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        r = self._rpc({"op": "cdp", "method": method, "params": params or {},
                       "session_id": session_id, "epoch": self.epoch})
        if r.get("ok"):
            self.epoch = r.get("epoch", self.epoch)
            return r["result"]
        code = r.get("code")
        if code == "STALE_EPOCH":
            self.epoch = r.get("epoch")
            raise StaleEpochError(r["error"])
        raise CDPError(f"{method}: {r.get('error')} [{code}]")

    def acquire_lease(self, wait: float = 900.0) -> dict:
        r = self._rpc({"op": "lease_acquire", "label": self.label, "wait": wait})
        self.epoch = r.get("epoch") or self.epoch
        return r

    def release_lease(self) -> None:
        try:
            self._rpc({"op": "lease_release"})
        except Exception:
            pass

    def close(self) -> None:
        """Close only OUR socket. The browser connection stays up — that is the whole point."""
        try:
            if self._fh:
                self._fh.close()
            if self._sock:
                self._sock.close()
        except Exception:
            pass


class StaleEpochError(CDPError):
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help="run the broker in the foreground")
    ap.add_argument("--ensure", action="store_true", help="start one if not already running")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--shutdown", action="store_true")
    ap.add_argument("--idle-exit", type=float, default=IDLE_EXIT_DEFAULT)
    a = ap.parse_args()

    if a.serve:
        return serve(a.idle_exit)
    if a.ensure:
        p = ensure(a.idle_exit)
        if not p:
            print(f"could not start a broker; see {LOG}", file=sys.stderr)
            return 1
        print(json.dumps(request({"op": "status"})["status"], indent=2))
        return 0
    if a.status:
        p = ping()
        if not p:
            print("no broker running")
            return 1
        print(json.dumps(request({"op": "status"})["status"], indent=2))
        return 0
    if a.shutdown:
        if not ping():
            print("no broker running")
            return 0
        print(json.dumps(request({"op": "shutdown"})))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
