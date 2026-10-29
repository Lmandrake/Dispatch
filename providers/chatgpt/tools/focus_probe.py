#!/usr/bin/env python3
"""Prove the consult path does not disturb what the user is looking at.

This is a control, not a unit test. Every claim it checks is about the browser's real behaviour
and is therefore unversioned: a Chrome update can silently take away `background: true`, and
nothing else the tool checks would notice — the consult would still succeed, it would just start
yanking his active tab away mid-sentence. So the property gets an instrument.

Measured facts this asserts, all established 2026-09-26 over six rounds:

  * `Target.createTarget(background=True)` does NOT change the active tab, on macOS, which is the
    documented behaviour (the docs' only caveat is headless shell). The control arm — the same call
    WITHOUT the flag, required to disturb the tab — is what keeps a pass from coming out of a probe
    that has simply stopped looking.
  * `Page.navigate` on a non-active tab does not activate it, so tab reuse is safe too.
  * `Input.insertText` and a trusted `Input.dispatchKeyEvent` Enter land in a tab that is NOT the
    active tab — which is what makes a fully background consult possible at all.
  * The websocket connect is the ONE step that steals focus (Chrome activates itself for the
    "Allow remote debugging?" sheet, once per connection). `CDP(restore_focus=True)` puts the
    previous app back.

The invariant is deliberately wider than "the active tab did not change". A second-model review
pointed out that the dangerous cases are not a normal tab suddenly foregrounding — they are Chrome
failing to find an eligible window and opening a NEW one, which an active-tab check on the front
window cannot see. So all three are asserted: the frontmost app, the active tab of EVERY
pre-existing window, and the window COUNT.

Deliberately uses a local file: URL, never chatgpt.com, so a stray Enter cannot post anything.

Usage:  python3 tools/focus_probe.py        # exits 0 when the property holds, 1 when it does not
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
from cdp_client import CDP, frontmost_app, activate_app  # noqa: E402

PROBE_HTML = """<!doctype html><html><body>
<div id="box" contenteditable="true"></div>
<script>window.T = () => document.getElementById('box').innerText;</script>
</body></html>"""


def chrome_state() -> tuple[int, str]:
    """(window count, active tab of every window). Both halves of the invariant in one read."""
    r = subprocess.run(
        ["osascript", "-e",
         'tell application "Google Chrome" to return ((count of windows) as text) & "|" & '
         '(URL of active tab of every window as text)'],
        capture_output=True, text=True, timeout=5)
    count, _, tabs = r.stdout.strip().partition("|")
    try:
        return int(count), tabs
    except ValueError:
        return -1, tabs


def ready(cdp: CDP, sid: str, tries: int = 40) -> bool:
    for _ in range(tries):
        if cdp.evaluate(sid, "typeof window.T", await_promise=False) == "function":
            return True
        time.sleep(0.25)
    return False


def attach(cdp: CDP, tid: str) -> str:
    sid = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    cdp.call("Runtime.enable", session_id=sid)
    return sid


def main() -> int:
    page = Path("/tmp/cgptconsult_focus_probe.html")
    page.write_text(PROBE_HTML)
    url = f"file://{page}"

    before_app = frontmost_app()
    before_count, before_tabs = chrome_state()
    if before_app and before_app[0] == "com.google.Chrome":
        print("note: Chrome is already frontmost, so the app-level check is vacuous here.\n"
              "      Switch to another app and rerun to exercise it.")
    print(f"baseline: frontmost={before_app}  windows={before_count}\n"
          f"          activeTabs={before_tabs[:100]}")

    def undisturbed() -> tuple[bool, str]:
        count, tabs = chrome_state()
        return (count == before_count and tabs == before_tabs,
                f"windows={count} activeTabs={tabs[:80]}")

    results: list[tuple[str, bool, str]] = []
    cdp = CDP()
    created: list[str] = []
    try:
        results.append(("frontmost app restored after connect",
                        frontmost_app() == before_app, f"frontmost={frontmost_app()}"))

        tid = cdp.call("Target.createTarget", {"url": url, "background": True})["targetId"]
        created.append(tid)
        time.sleep(1.2)
        ok, detail = undisturbed()
        results.append(("background:true left every window and its active tab alone",
                        ok, detail))

        sid = attach(cdp, tid)
        if not ready(cdp, sid):
            results.append(("probe page became ready", False, "window.T never appeared"))
        else:
            cdp.evaluate(sid, "document.getElementById('box').focus(); 1", await_promise=False)
            cdp.call("Input.insertText", {"text": "alpha\nbeta"}, session_id=sid)
            time.sleep(0.3)
            for kind in ("keyDown", "char", "keyUp"):
                cdp.call("Input.dispatchKeyEvent", {
                    "type": kind, "key": "Enter", "code": "Enter",
                    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                    "text": "\r" if kind == "keyDown" else "",
                }, session_id=sid)
            time.sleep(0.4)
            text = cdp.evaluate(sid, "window.T()", await_promise=False) or ""
            ok, detail = undisturbed()
            results.append(("input landed in a tab that is NOT the active tab",
                            "alpha" in text and "beta" in text and ok,
                            f"text={text!r} {detail}"))
            results.append(("the trusted Enter registered (trailing newline)",
                            text.endswith("\n"), f"text={text!r}"))

            cdp.call("Page.navigate", {"url": url + "?again"}, session_id=sid)
            time.sleep(1.2)
            ok, detail = undisturbed()
            results.append(("Page.navigate on a non-active tab did not activate it", ok, detail))

        # Control arm: without the flag the tab MUST take over. A probe that cannot see the
        # failure it is built to detect reports success forever.
        ctl = cdp.call("Target.createTarget", {"url": url})["targetId"]
        created.append(ctl)
        time.sleep(1.2)
        ok, detail = undisturbed()
        results.append(("CONTROL: no background flag does disturb the active tab",
                        not ok, detail))
    finally:
        for t in created:
            try:
                cdp.call("Target.closeTarget", {"targetId": t})
            except Exception:
                pass
        cdp.close()
        if before_app and frontmost_app() != before_app:
            activate_app(before_app[0])

    print()
    failed = 0
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {detail}")
        failed += not ok
    time.sleep(0.6)
    count, tabs = chrome_state()
    print(f"\nfinal: frontmost={frontmost_app()}  windows={count}  activeTabs={tabs[:90]}")
    print("the consult path is invisible" if not failed
          else f"{failed} focus propert{'y' if failed == 1 else 'ies'} broken")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
