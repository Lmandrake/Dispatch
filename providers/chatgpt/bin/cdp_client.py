"""The CDP flow this provider needs (tab reuse, origin waits), independent of how bytes reach Chrome.

No websocket here (2026-10-29, owner: one Chrome access layer, so a change of access method is
made in one place). Bytes reach Chrome through Machinist's shared client, tools/chrome_access.py
(the Machinist extension bridge; its loud ws fallback lives there). `CDP` below is a thin shim over
it for `consult.py --direct` and the probes; the broker's `BridgeCDP` rides the same bridge.
Machinist is found at $MACHINIST_TOOLS, else $MACHINIST/tools, else a sibling Machinist checkout;
its absence is a CDPError naming the path.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


def machinist_tools() -> Path:
    t = os.environ.get("MACHINIST_TOOLS")
    if t:
        return Path(t)
    m = os.environ.get("MACHINIST")
    if m:
        return Path(m) / "tools"
    return Path(__file__).resolve().parents[4] / "Machinist" / "tools"


def chrome_access():
    """Machinist's chrome_access module, by stable path. Raises CDPError naming the path."""
    t = machinist_tools()
    if not (t / "chrome_access.py").is_file():
        raise CDPError(f"Machinist chrome_access.py not found in {t}: set MACHINIST_TOOLS")
    if str(t) not in sys.path:
        sys.path.insert(0, str(t))
    return importlib.import_module("chrome_access")


class CDPError(RuntimeError):
    pass


CHROME_BUNDLE = "com.google.Chrome"


def frontmost_app() -> tuple[str, str] | None:
    """(bundle id, name) of the frontmost macOS app, or None if it cannot be read.

    The bundle id is the identity that matters — app names are neither unique nor stable, and the
    restore below acts on whatever this returns.
    """
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to tell (first application process whose '
             'frontmost is true) to return (bundle identifier) & "|" & name'],
            capture_output=True, text=True, timeout=5)
        out = r.stdout.strip()
        if "|" not in out:
            return None
        bundle, _, name = out.partition("|")
        return (bundle.strip(), name.strip()) if bundle.strip() else None
    except Exception:
        return None


def activate_app(bundle_id: str) -> None:
    try:
        subprocess.run(["osascript", "-e", f'tell application id "{bundle_id}" to activate'],
                       capture_output=True, timeout=5)
    except Exception:
        pass


class CDPSession:
    """The CDP operations this tool needs, independent of how the bytes reach Chrome.

    Two transports implement `call`: `CDP`, a private session over Machinist's chrome_access, and
    `BrokerClient`, which borrows the shared broker's session and its machine-wide lease. Everything above `call` lives here precisely so the broker is a **transport swap** rather
    than a second implementation of the flow — two copies of the tab-reuse and origin-waiting rules
    would drift, and the rules are the expensive part.
    """

    target_id: str | None = None

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def reuse_page(self, url: str, match: str) -> str | None:
        """Attach to a tab already on `match` and navigate it to `url`. None if there is none.

        Why this exists. `open_page` created a tab on every call while `close()` deliberately leaves
        the tab open, so a session that retried a few times leaked **19 tabs** into the user's
        browser — and that pile of live ChatGPT tabs, each polling, rate-limited the very API the
        tool depends on: `/backend-api/conversations` started answering 429 and the tool could no
        longer find its own thread. Tab reuse is therefore not tidiness, it is what keeps the channel
        working.

        `match` is a substring the CALLER chooses, so reuse stays scoped to tabs already dedicated to
        this purpose. Navigating a tab the user is actively reading would be worse than opening one,
        so match on something specific, and let tab creation remain the fallback.
        """
        import time
        candidates = [t for t in self.call("Target.getTargets")["targetInfos"]
                      if t.get("type") == "page" and match in (t.get("url") or "")]
        # Prefer a tab nobody ELSE is driving. A target attached by a foreign debugger — a DevTools
        # window, another CDP client — was measured to hang: the attach returned in 0.0s and the
        # following `Runtime.enable` never answered, timing out at the full 120s socket deadline and
        # reading as a dead browser.
        #
        # `attached` alone is the wrong test, because the broker's own attachments set it too, and
        # skipping those would create a fresh tab on every consult — the 19-leaked-tabs failure this
        # method exists to prevent. The broker therefore annotates `brokerOwned`, and a tab we own is
        # still reusable. Without a broker the annotation is absent and `attached` is the right test,
        # since a private connection has attached nothing when it calls this.
        def foreign(t: dict) -> bool:
            return bool(t.get("attached")) and not t.get("brokerOwned")

        candidates.sort(key=foreign)
        for t in candidates:
            if foreign(t):
                continue
            # Try the next candidate rather than failing the consult. Chrome can report a tab as
            # unattached while a dying connection's session is still being torn down, and attaching to
            # one of those was measured to hang `Runtime.enable` until the socket deadline. One bad
            # candidate should cost a retry, not a consult — and `open_page` still falls back to
            # creating a tab if every candidate turns out to be unusable.
            try:
                session_id = self.call("Target.attachToTarget",
                                       {"targetId": t["targetId"], "flatten": True})["sessionId"]
                self.call("Runtime.enable", session_id=session_id)
                self.target_id = t["targetId"]
                if (t.get("url") or "").rstrip("/") != url.rstrip("/"):
                    self.call("Page.navigate", {"url": url}, session_id=session_id)
                    time.sleep(0.6)
                self.await_origin(session_id, url)
                return session_id
            except CDPError:
                continue
        return None

    def open_page(self, url: str, reuse_match: str | None = None) -> str:
        """Attach to a reusable tab when `reuse_match` finds one, else create our own.

        Target.createTarget returns before navigation commits, so a relative fetch issued
        immediately fails with "Failed to parse URL" against about:blank. Waiting for the
        origin is therefore part of opening, not an optional extra.

        `background: true` keeps the new tab from becoming the active tab — measured in a same-run
        A/B on 2026-09-26: with the flag the user's active tab was untouched, without it the probe
        tab took over. This is also the documented behaviour; the docs' only caveat is "not
        supported by headless shell". (An earlier comment here claimed the docs said "not supported
        for MacOS" and that we were trusting a measurement over the spec. That was a misreading,
        caught by a second-model review and corrected by reading the protocol page.)

        The control in `tools/focus_probe.py` stays regardless, because UI semantics regress and a
        silent regression here is invisible to everything else the tool checks.
        """
        if reuse_match:
            session_id = self.reuse_page(url, reuse_match)
            if session_id:
                return session_id
        target_id = self.call(
            "Target.createTarget", {"url": url, "background": True})["targetId"]
        session_id = self.call("Target.attachToTarget",
                               {"targetId": target_id, "flatten": True})["sessionId"]
        self.call("Runtime.enable", session_id=session_id)
        self.target_id = target_id
        self.await_origin(session_id, url)
        return session_id

    def await_origin(self, session_id: str, url: str, tries: int = 60) -> str:
        """Block until the tab is actually on the target origin and the DOM is usable."""
        import time
        from urllib.parse import urlparse
        want = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        state = None
        for _ in range(tries):
            # A tab MID-NAVIGATION reports an empty URL, and the broker re-checks a session's origin
            # on every call — so evaluating in that window is refused. That refusal is a transient
            # state of the very navigation this method is waiting for, and treating it as fatal made
            # `reuse_page` discard a perfectly good tab and open another, which is the tab-leak this
            # whole reuse path exists to prevent. Keep polling; the loop's own exhaustion is the real
            # failure, and the last error is carried into it.
            try:
                state = self.evaluate(
                    session_id, "[location.origin, document.readyState].join('|')",
                    await_promise=False)
            except CDPError as e:
                state = f"<not evaluable: {e}>"
                time.sleep(0.5)
                continue
            if state and state.startswith(want) and not state.endswith("loading"):
                return state
            time.sleep(0.5)
        raise CDPError(f"tab never reached {want} (last state: {state!r})")

    def evaluate(self, session_id: str, expression: str, await_promise: bool = True):
        r = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        }, session_id=session_id)
        if "exceptionDetails" in r:
            raise CDPError(f"JS threw: {r['exceptionDetails'].get('text')} "
                           f"{r['exceptionDetails'].get('exception', {}).get('description', '')}")
        return r.get("result", {}).get("value")

    def close_page(self) -> None:
        if getattr(self, "target_id", None):
            try:
                self.call("Target.closeTarget", {"targetId": self.target_id})
            except CDPError:
                pass


class CDP(CDPSession):
    """A private session over Machinist's chrome_access (no broker lease). Owns no websocket.

    Kept for `consult.py --direct` and the probes. Legacy kwargs (restore_focus, press_consent) are
    accepted and ignored: over the extension there is no sheet to press and focus never moves.
    """

    def __init__(self, timeout: float = 120.0, **_legacy):
        ca = chrome_access()
        self._err = ca.CDPError
        try:
            self._s = ca.Session(timeout=timeout)
        except ca.CDPError as e:
            raise CDPError(str(e)) from e

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None) -> dict:
        try:
            return self._s.call(method, params, session_id)
        except self._err as e:
            raise CDPError(f"{method}: {e}") from e

    def close(self) -> None:
        pass                       # the bridge connection is shared; tabs are closed explicitly
