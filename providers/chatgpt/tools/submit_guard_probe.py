#!/usr/bin/env python3
"""Prove the submit guard fires, recovers, and refuses — without touching the user's account.

Why this exists. On 2026-09-27 a consult composed 21,131 characters into a newly created thread,
pressed Enter, and waited the full 600 s for a reply to a message it had never sent. The keystroke
was delivered (verified: a trusted `keydown`, `keyCode` 13, on the focused `ProseMirror` element) and
ChatGPT silently dropped it, because the page's submit handler is not always wired immediately after
a load — every readiness signal available was already green. A second Enter submitted in 0.5 s.

So the guard is a bounded retry, and what makes a retry safe is the part worth testing. **The fake
below models the SERVER and the COMPOSER as two independent dimensions**, because the decoupling of
those two is exactly the defect under investigation: the first version of this probe drove both from
one `clears_after` counter, so it structurally could not express the dangerous case — the message is
accepted, the acknowledgement is lost, and the editor does not clear. GPT named that coupling when
reviewing the fix, and it is the same instrumentation mistake this project keeps finding elsewhere: a
metric that cannot represent a failure reports zero for it forever.

Arms 3 and 6 are controls: each asserts the guard REFUSING. A probe that cannot observe the failure
it exists to detect reports success forever.

Run:  python3 tools/submit_guard_probe.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin"))
import consult as C  # noqa: E402
from cdp_client import CDPError  # noqa: E402

# The logic is under test, not the wall-clock constants, so shorten them and say so.
C.SUBMIT_CONFIRM = 0.4

PROMPT = "line one\nline two   with  spaces\n\nline three"
SINCE = 1000.0


class FakeCDP:
    """Two independent dimensions, plus what the composer holds.

    `server_accepts_after` — the press count at which the server records our user turn (None: never).
    `composer_clears_after` — the press count at which the editor empties (None: never).
    `composer_becomes` — text the composer shows instead of ours once it has cleared (a restored
    draft, a rehydrated UI, or the user typing into that tab).
    """

    def __init__(self, server_accepts_after: int | None, composer_clears_after: int | None,
                 dispatch_raises: bool = False, composer_becomes: str | None = None,
                 composer_gone: bool = False):
        self.server_accepts_after = server_accepts_after
        self.composer_clears_after = composer_clears_after
        self.dispatch_raises = dispatch_raises
        self.composer_becomes = composer_becomes
        self.composer_gone = composer_gone
        self.presses = 0
        self.focus_calls = 0
        self.cleared_composer = False

    # --- transport ---------------------------------------------------------
    def call(self, method, params=None, session_id=None):
        if method == "Input.dispatchKeyEvent":
            if params.get("type") == "keyDown":
                self.presses += 1
                if self.dispatch_raises:
                    raise CDPError("socket closed mid-frame")
            return {}
        raise AssertionError(f"unexpected CDP method in this probe: {method}")

    def evaluate(self, session_id, expression, await_promise=True):
        if expression is C.FOCUS_JS:
            self.focus_calls += 1
            return True
        if expression is C.COMPOSER_JS:
            if self.composer_gone:
                return {"gone": True}
            cleared = (self.composer_clears_after is not None
                       and self.presses >= self.composer_clears_after)
            if cleared:
                shown = self.composer_becomes or ""
            else:
                shown = PROMPT
            return {"norm": C.norm_text(shown), "focused": True,
                    "send": bool(shown), "streaming": False}
        if expression is C.CONV_JS:
            accepted = (self.server_accepts_after is not None
                        and self.presses >= self.server_accepts_after)
            turns = ([{"id": "u", "role": "user", "created": SINCE + 1, "model": None,
                       "text": PROMPT}] if accepted else [])
            return {"turns": turns, "streaming": False}
        if "execCommand('delete')" in expression:     # park_unsent clearing the composer
            self.cleared_composer = True
            return True
        raise AssertionError(f"unexpected JS in this probe: {expression[:60]!r}")


def arm(name: str, fake: FakeCDP, expect: type | None, expect_presses: int) -> bool:
    raised = None
    try:
        C.submit(fake, "session", PROMPT, SINCE, False)
    except C.ConsultError as e:
        raised = e
    ok = (type(raised) is expect if expect else raised is None) and fake.presses == expect_presses
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n"
          f"          presses={fake.presses} (want {expect_presses}), "
          f"raised={type(raised).__name__ if raised else None} "
          f"(want {expect.__name__ if expect else None})")
    return ok


def park_arm(mutated: bool) -> bool:
    """The unsent prompt is saved to disk BEFORE the composer is cleared — and only if it is ours.

    Saving our text is no licence to delete what is in the box now: if the content changed it may be
    the user's, so the second case must save and NOT clear.
    """
    import tempfile
    fake = FakeCDP(server_accepts_after=None, composer_clears_after=1 if mutated else None,
                   composer_becomes="text he typed himself" if mutated else None)
    if mutated:
        fake.presses = 1                      # force the "cleared, then became his text" state
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(C.park_unsent(fake, "session", pathlib.Path(tmp), "probe-id", PROMPT))
        # Read inside the block: the temp dir is gone afterwards, and checking `path.exists()` after
        # it is removed reports False for a file that WAS written — a probe whose reporting lies about
        # a passing arm is barely better than one that cannot see a failure.
        saved = path.exists() and path.read_text() == PROMPT
        ok = saved and path.parent.name == ".consult" and fake.cleared_composer is (not mutated)
    what = "his text is left alone" if mutated else "our text is cleared"
    print(f"  [{'PASS' if ok else 'FAIL'}] park_unsent: saved first, then {what}\n"
          f"          saved={saved}, cleared={fake.cleared_composer} (want {not mutated})")
    return ok


def main() -> int:
    print(f"submit guard probe — SUBMIT_TRIES={C.SUBMIT_TRIES}, "
          f"SUBMIT_CONFIRM shortened to {C.SUBMIT_CONFIRM}s for this probe")
    results = [
        arm("1. a submit that takes is not retried",
            FakeCDP(server_accepts_after=1, composer_clears_after=1), None, 1),
        arm("2. a swallowed Enter is retried and recovers",
            FakeCDP(server_accepts_after=2, composer_clears_after=2), None, 2),
        arm("3. CONTROL — a composer that never clears and a server that never accepts RAISES",
            FakeCDP(server_accepts_after=None, composer_clears_after=None),
            C.SubmitRefused, C.SUBMIT_TRIES),
        arm("4. THE AMBIGUOUS COMMIT: server accepted, ack lost, editor never cleared — "
            "one press only",
            FakeCDP(server_accepts_after=1, composer_clears_after=None, dispatch_raises=True),
            None, 1),
        arm("5. the composer cleared and then became HIS text, but the server has ours: sent",
            FakeCDP(server_accepts_after=1, composer_clears_after=1,
                    composer_becomes="looks good"), None, 1),
        arm("6. CONTROL — composer holds text that is not ours and the server has nothing: "
            "refuses to press Enter again",
            FakeCDP(server_accepts_after=None, composer_clears_after=1,
                    composer_becomes="looks good"), C.ComposerMutated, 1),
        arm("7. the composer vanished and the server has nothing: refuses",
            FakeCDP(server_accepts_after=None, composer_clears_after=None, composer_gone=True),
            C.ComposerMutated, 1),
        park_arm(mutated=False),
        park_arm(mutated=True),
    ]
    print("ALL PASS" if all(results) else "FAILURES ABOVE")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
