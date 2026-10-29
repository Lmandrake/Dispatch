#!/usr/bin/env python3
"""Assert the broker's claims, including the ones that are security properties.

The broker exists to make two promises that nothing else here can check:

  1. **N consults cost ONE browser connection**, therefore one approval sheet and one focus steal.
     If this regresses the broker is pure overhead — it would be doing the thing it replaced.
  2. **It is not a general CDP proxy.** It holds full authority over his authenticated browser on a
     local socket, so the method allowlist and the chatgpt.com origin restriction are the whole
     reason it is safe to leave running. Those refusals get positive tests: a guard never observed
     refusing has not been tested.

Plus the lease, which is what lets several Claude Code instances share it: one consult at a time,
FIFO, and released automatically when its holder's socket dies — otherwise one crashed instance
would wedge every other instance on the machine.

Usage:  python3 tools/broker_probe.py     # 0 if every property holds
"""
from __future__ import annotations


import sys
import time
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import broker as B  # noqa: E402
from cdp_client import CDPError, frontmost_app  # noqa: E402

CHATGPT = "https://chatgpt.com/"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def refused(fn, *a, **kw) -> tuple[bool, str]:
    """True when the call was refused. A refusal is the PASS condition for these."""
    try:
        fn(*a, **kw)
        return False, "was allowed — the guard did not fire"
    except CDPError as e:
        return True, str(e)[:120]


def main() -> int:
    if B.ping():
        print("a broker is already running; shutting it down so the count starts clean")
        B.request({"op": "shutdown"})
        time.sleep(1.0)

    # No presser here on purpose: the broker presses its own approval sheet as part of connecting.
    # If that ever regresses, this probe hangs, which is the correct way to notice.
    before_app = frontmost_app()
    try:
        p = B.ensure(idle_exit=90)
        check("broker starts on demand", bool(p), f"ping={p}")
        if not p:
            print(f"  (see {B.LOG})")
            return 1

        # --- property 1: many clients, one browser connection
        c1 = B.BrokerClient(label="probe-1")
        c1.call("Browser.getVersion")
        c2 = B.BrokerClient(label="probe-2")
        c2.call("Browser.getVersion")
        c3 = B.BrokerClient(label="probe-3")
        c3.call("Target.getTargets")
        st = B.request({"op": "status"})["status"]
        check("3 clients cost exactly 1 browser connection",
              st["browser_connections"] == 1,
              f"browser_connections={st['browser_connections']} epoch={st['epoch']}")
        check("all three clients share one epoch",
              c1.epoch == c2.epoch == c3.epoch == st["epoch"],
              f"{c1.epoch} / {c2.epoch} / {c3.epoch}")

        # --- focus: using the running broker must disturb nothing at all
        now = frontmost_app()
        check("using an already-running broker steals no focus",
              now == before_app, f"before={before_app} now={now}")

        # --- property 2: the authority bounds, each observed refusing
        ok, why = refused(c1.call, "Target.createTarget",
                          {"url": "https://example.com/", "background": True})
        check("refuses to open a tab outside chatgpt.com", ok, why)

        ok, why = refused(c1.call, "Page.bringToFront")
        check("refuses Page.bringToFront (explicitly denied)", ok, why)

        ok, why = refused(c1.call, "Target.activateTarget", {"targetId": "x"})
        check("refuses Target.activateTarget (explicitly denied)", ok, why)

        ok, why = refused(c1.call, "Browser.close")
        check("refuses a method absent from the allowlist", ok, why)

        ok, why = refused(c1.call, "Runtime.evaluate",
                          {"expression": "1", "returnByValue": True},
                          session_id="not-a-session-we-attached")
        check("refuses evaluate on a session it did not attach", ok, why)

        # attach to one of HIS tabs, chosen from the live target list
        foreign = [t for t in c1.call("Target.getTargets")["targetInfos"]
                   if t.get("type") == "page" and "chatgpt.com" not in (t.get("url") or "")]
        if foreign:
            ok, why = refused(c1.call, "Target.attachToTarget",
                              {"targetId": foreign[0]["targetId"], "flatten": True})
            check("refuses to attach to a non-chatgpt tab of his", ok,
                  f"{foreign[0].get('url','')[:50]} -> {why}")
        else:
            check("refuses to attach to a non-chatgpt tab of his", False,
                  "no non-chatgpt page target open; could not exercise this")

        ok, why = refused(c1.call, "Target.closeTarget", {"targetId": "some-other-tab"})
        check("refuses to close a tab it did not open", ok, why)

        # --- the escape a second-model review named, and that was real when it did.
        # `Page.navigate` off-origin is refused, and JS then navigates the same tab anyway, because
        # JavaScript needs no CDP navigation method. Checking the origin only at attach time was
        # therefore no bound at all after the first call. The session's live origin is now re-checked
        # per call, so the call AFTER such a navigation must be refused.
        tid = c1.call("Target.createTarget",
                      {"url": CHATGPT, "background": True})["targetId"]
        esc = c1.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        c1.call("Runtime.enable", session_id=esc)
        time.sleep(2.0)
        on_origin = c1.evaluate(esc, "location.origin", await_promise=False)
        check("a freshly attached chatgpt session can be evaluated",
              on_origin == "https://chatgpt.com", f"origin={on_origin!r}")
        try:
            c1.evaluate(esc, "location.href='https://example.com/'; 1", await_promise=False)
        except CDPError:
            pass
        time.sleep(3.0)
        ok, why = refused(c1.evaluate, esc, "location.origin", False)
        check("refuses to evaluate after JS navigated the tab off-origin", ok, why)

        # One instance must not be able to act through another instance's session or close its tab.
        # Ownership is per client, not global, so a session handle leaking between instances confers
        # nothing — the same ambient-authority shape the allowlist exists to remove.
        ok, why = refused(c2.call, "Runtime.evaluate",
                          {"expression": "1", "returnByValue": True}, session_id=esc)
        check("one client cannot use another client's session", ok, why)
        ok, why = refused(c2.call, "Target.closeTarget", {"targetId": tid})
        check("one client cannot close another client's tab", ok, why)

        c1.call("Target.closeTarget", {"targetId": tid})

        st = B.request({"op": "status"})["status"]
        check("every refusal was counted", st["refusals"] >= 6, f"refusals={st['refusals']}")

        # --- the lease
        g1 = c1.acquire_lease(wait=5)
        check("first claimant gets the lease", g1.get("granted"), str(g1))
        g2 = c2.acquire_lease(wait=1)
        check("a second consult is made to wait, not run concurrently",
              g2.get("granted") is False, str(g2)[:110])
        c1.release_lease()
        g2 = c2.acquire_lease(wait=5)
        check("the lease passes on once released", g2.get("granted"), str(g2))

        # --- auto-release when a holder dies, so one crash cannot wedge the machine
        c2.close()                     # c2 still held the lease
        time.sleep(0.6)
        g3 = c3.acquire_lease(wait=5)
        check("a dead client's lease is released automatically", g3.get("granted"), str(g3))
        c3.release_lease()

        # --- a second broker must refuse, and must not damage the running one. The existence check
        # alone lost this: the loser's cleanup unlinked the winner's live socket.
        import subprocess as sp
        r = sp.run([sys.executable, str(BIN / "broker.py"), "--serve", "--idle-exit", "5"],
                   capture_output=True, text=True, timeout=30)
        check("a second broker refuses to start", r.returncode == 3,
              f"rc={r.returncode} {(r.stderr or '').strip()[:80]}")
        check("the running broker still answers afterwards", bool(B.ping()),
              f"ping={B.ping()}")

        # --- a stale epoch is a typed error, not a puzzling CDP failure
        c3.epoch = "deadbeefdead"
        try:
            c3.call("Browser.getVersion")
            check("a stale epoch raises StaleEpochError", False, "no error raised")
        except B.StaleEpochError as e:
            check("a stale epoch raises StaleEpochError", True, str(e)[:110])
        except CDPError as e:
            check("a stale epoch raises StaleEpochError", False, f"wrong type: {e}")

        for c in (c1, c3):
            c.close()
    finally:
        if B.ping():
            B.request({"op": "shutdown"})

    print()
    failed = 0
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if detail:
            print(f"        {detail}")
        failed += not ok
    print(f"\n{len(results) - failed}/{len(results)} properties hold")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
