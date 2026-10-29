#!/usr/bin/env python3
"""Is the ChatGPT session in your Chrome signed in, and on what plan?

## 🔴 Read this before changing the fetch: a cookie-only read ALWAYS says "guest"

`/backend-api/*` authenticates by **bearer token, not cookie.** A `fetch` with
`credentials: 'include'` and no `Authorization` header gets **HTTP 200 and the anonymous
view** — `plan_type: "guest"`, `has_active_subscription: false`,
`subscription_plan: "chatgptguestplan"` — from a browser that is perfectly well signed
in. Measured against live signed-in tabs, including a project thread (a paid-only URL).
The same call with the bearer token from `/api/auth/session` returned a paid
`plan_type` (`"examplelite"`) and `has_active_subscription: true`.

**That 200 is why this is dangerous.** A 401 would have been obvious and a timeout would
have been obvious. A successful response in the anonymous view is a *clean, plausible,
wrong answer* — so the UNKNOWN safety net below never fires, and the verdict is
confidently false. The first version of this file shipped exactly that bug, reported the
user as signed out, and `consult.py` refused every consult on the strength of it. The
2026-09-30 session's "both tabs read plan: guest" finding was almost certainly the same
false negative, which means the alarm it raised — that consults might be running on a
weaker model than the ledger records — was never real.

**The signed-in signal is the presence of an `accessToken` on `/api/auth/session`.** The
plan then comes from the accounts endpoint *with* that token attached. The token itself
never crosses out of the page: `_READ_JS` uses it internally and returns only derived
facts. `/api/auth/session` carries it behind its own DO-NOT-SHARE banner and nothing in
this repo may hold it, log it, or write it to a ledger.

## The plan gate is DERIVED, not an allowlist

`examplelite` was not in the first version's `PAID_PLANS`, so even with the token the verdict
would still have been "not usable" — two independent bugs pointing the same way. A list of
plan names is the brittle thing: OpenAI renames tiers without warning, and every rename
reads as a downgrade. So the gate is **`entitlement.has_active_subscription is True` and
the plan is not a known guest plan**. `PAID_PLANS` survives only as a label for the
output. Do not reintroduce it as the gate.

## Three-valued on purpose

`SIGNED_IN` / `GUEST` / `UNKNOWN`, and **`UNKNOWN` is never treated as OK**. If the
transport is down, no chatgpt.com tab is open, or the payload will not parse, the answer
is "could not tell" — not "fine". A green check that cannot see anything is the shape of
the bug this file exists to catch.

## It must never navigate

`cdp_client.reuse_page` **navigates** the tab it attaches to, and a user's chatgpt.com
tabs are conversations being read. `attach_readonly` attaches and evaluates without a
`Page.navigate`, which is the only safe way to inspect a tab you did not open.

Self-test (no browser — calibrates the classifier on known positive, known negative,
empty and truncated, plus the two live payloads measured above):

    python3 bin/chatgpt_auth.py --selftest
    python3 bin/chatgpt_auth.py --live        # read the real browser
"""
from __future__ import annotations

import json

SIGNED_IN = "signed_in"
GUEST = "guest"
UNKNOWN = "unknown"

#: Descriptive only — NOT the gate. See the module docstring: `examplelite` was missing from
#: the first version's copy of this and that alone would have refused a healthy session.
PAID_PLANS = frozenset({"plus", "pro", "examplelite", "team", "enterprise", "business"})
#: Plans that mean nobody is signed in. These ARE part of the gate, as a veto.
GUEST_PLANS = frozenset({"guest", "anonymous"})

#: Measured 2026-10-01. `/backend-api/accounts/check` answers 405 on GET and `/v1`
#: answers 404 with a JSON body, which an earlier loop accepted as an answer and so never
#: reached the real endpoint. Kept as a dated fallback: if the suffix is bumped, the next
#: path at least produces a distinguishable error.
_ENDPOINTS = ("/backend-api/accounts/check/v4-2023-04-27",
              "/backend-api/accounts/check/v1",
              "/backend-api/accounts/check")

#: Read the session and the account summary from inside the page.
#:
#: The access token is used here and NOT returned. `auth_mode` tells the classifier which
#: credential actually reached the endpoint, because a cookie-only answer cannot
#: distinguish "signed out" from "signed in, wrong credential" — it says guest either way.
_READ_JS = r"""
(async (urls) => {
  const out = {};
  // 1) The signed-in signal. An empty object here means genuinely not signed in.
  let token = null;
  try {
    const s = await (await fetch('/api/auth/session', {credentials: 'include'})).json();
    token = (s && s.accessToken) ? s.accessToken : null;
    out.has_session = !!(s && (s.accessToken || s.user));
    out.email_domain = (s && s.user && s.user.email)
        ? String(s.user.email).split('@').pop() : null;
    out.session_expires = (s && s.expires) ? s.expires : null;
  } catch (e) {
    out.session_error = String(e);
    out.has_session = null;
  }
  out.auth_mode = token ? 'bearer' : 'cookie_only';

  const headers = {'accept': 'application/json'};
  if (token) headers['authorization'] = 'Bearer ' + token;

  let last = null;
  for (const u of urls) {
    try {
      const r = await fetch(u, {credentials: 'include', headers: headers});
      const t = await r.text();
      if (r.status === 401 || r.status === 403) {
        out.url = u; out.status = r.status; return out;
      }
      if (!r.ok) { last = {url: u, status: r.status, head: t.slice(0, 200)}; continue; }
      let j = null;
      try { j = JSON.parse(t); }
      catch (e) {
        last = {url: u, status: r.status, parse_error: true, head: t.slice(0, 200)};
        continue;
      }
      const accts = (j && j.accounts && typeof j.accounts === 'object')
        ? Object.keys(j.accounts).map(k => {
            const a = (j.accounts[k] || {}).account || {};
            const e = (j.accounts[k] || {}).entitlement || {};
            return {key: k, plan: a.plan_type || null, email: a.name || null,
                    has_active_sub: (typeof e.has_active_subscription === 'boolean'
                                     ? e.has_active_subscription : null),
                    sub_plan: e.subscription_plan || null};
          })
        : null;
      if (accts === null) { last = {url: u, status: r.status, accounts: null}; continue; }
      out.url = u; out.status = r.status; out.accounts = accts;
      return out;
    } catch (e) {
      last = {url: u, threw: String(e)};
    }
  }
  return Object.assign(out, last || {threw: 'no endpoint answered'});
})(%(urls)s)
"""


def classify(raw) -> dict:
    """Turn the page's summary into a verdict. Anything unrecognisable is UNKNOWN.

    Returns `{state, plan, email_domain, auth_mode, has_active_sub, detail}`. `plan` is
    None whenever the state is UNKNOWN, so a caller cannot read a plan out of a failed
    read.
    """
    def unknown(detail, **extra):
        return {"state": UNKNOWN, "plan": None, "email_domain": None,
                "auth_mode": (raw or {}).get("auth_mode") if isinstance(raw, dict) else None,
                "has_active_sub": None, "detail": detail, **extra}

    if raw is None:
        # Redundant with the isinstance check below and kept for the message; mutation
        # -tested 2026-10-01, deleting it leaves the self-test green.
        return unknown("no answer from the page (evaluate returned nothing)")
    if not isinstance(raw, dict):
        return unknown(f"unexpected answer shape: {type(raw).__name__}")

    mode = raw.get("auth_mode")
    base = {"auth_mode": mode, "email_domain": raw.get("email_domain")}

    if raw.get("threw"):
        return unknown(f"fetch threw in the page: {raw['threw']}")
    if raw.get("parse_error"):
        return unknown(f"HTTP {raw.get('status')} but the body is not JSON: "
                       f"{(raw.get('head') or '')[:120]!r}")

    status = raw.get("status")
    if status in (401, 403):
        return {"state": GUEST, "plan": None, "has_active_sub": False,
                "detail": f"HTTP {status} from the accounts endpoint: not signed in",
                **base}
    if isinstance(status, int) and status >= 400:
        return unknown(f"HTTP {status} from {raw.get('url')}")

    accounts = raw.get("accounts")
    if not accounts:
        return unknown("payload carried no `accounts` object")

    # 🔴 The load-bearing branch. A cookie-only read returns the ANONYMOUS view with a
    # 200, so its "guest" says nothing about the session. Only `/api/auth/session` can
    # settle that, and when it reports no session at all the answer is a real GUEST.
    if mode == "cookie_only":
        if raw.get("has_session") is False:
            return {"state": GUEST, "plan": None, "has_active_sub": False,
                    "detail": "no session on /api/auth/session — genuinely not signed in",
                    **base}
        return unknown(
            "the accounts endpoint was read WITHOUT a bearer token, which always returns "
            "the anonymous view — this says nothing about the session. "
            + (f"/api/auth/session errored: {raw['session_error']}"
               if raw.get("session_error") else
               "no accessToken was available to attach."))

    plans = [(a.get("plan") or "").strip().lower() for a in accounts]
    subs = [a.get("has_active_sub") for a in accounts]
    sub_plans = [(a.get("sub_plan") or "").strip().lower() for a in accounts]
    emails = [a.get("email") for a in accounts if a.get("email")]
    named = ", ".join(p or "?" for p in plans)
    active = True if any(s is True for s in subs) else (
        False if any(s is False for s in subs) else None)
    # Best account wins: a personal `default` sitting beside a real workspace is normal,
    # and a live payload can have exactly that shape.
    best = next((p for p in plans if p not in GUEST_PLANS and p), None)

    detail = (f"plans: {named}"
              + (f"; subscription {', '.join(s for s in sub_plans if s)}" if any(sub_plans) else "")
              + (f"; active={active}" if active is not None else "")
              + (f"; {len(accounts)} account(s)" if len(accounts) > 1 else ""))

    if best is None:
        # Every account is a guest plan, read WITH a valid token. That is conclusive.
        return {"state": GUEST, "plan": plans[0] if plans else None,
                "has_active_sub": active,
                "detail": detail + " — every account is a guest plan", **base}
    return {"state": SIGNED_IN, "plan": best, "has_active_sub": active,
            "detail": detail + (f"; {emails[0]}" if emails else ""), **base}


def is_usable(verdict: dict) -> bool:
    """May a consult run against this session and be logged as one?

    DERIVED, not an allowlist: an active subscription and a plan that is not a guest
    plan. A plan-name allowlist is what made `examplelite` read as unusable, and OpenAI
    renames tiers without warning — under an allowlist every rename reads as a downgrade
    and silently blocks consulting.

    `has_active_subscription` absent (None) passes, because a workspace payload may omit
    the field; an explicit False does not.
    """
    if verdict.get("state") != SIGNED_IN:
        return False
    if (verdict.get("plan") or "") in GUEST_PLANS:
        return False
    return verdict.get("has_active_sub") is not False


def attach_readonly(cdp, match: str = "chatgpt.com") -> str | None:
    """A session on an existing tab matching `match`, WITHOUT navigating it.

    `cdp_client.reuse_page` issues `Page.navigate`, which would move a conversation the
    user is reading. It also skips any tab with a foreign debugger attached — and live
    chatgpt.com tabs can read `attached: true, brokerOwned: false`, so it found none of them and fell through to creating a new tab. This
    attaches to them anyway: a read-only `Runtime.evaluate` is not the operation that
    hang was measured on.
    """
    try:
        targets = cdp.call("Target.getTargets")["targetInfos"]
    except Exception:                                            # noqa: BLE001
        return None
    for t in targets:
        if t.get("type") != "page" or match not in (t.get("url") or ""):
            continue
        try:
            sid = cdp.call("Target.attachToTarget",
                           {"targetId": t["targetId"], "flatten": True})["sessionId"]
            cdp.call("Runtime.enable", session_id=sid)
            return sid
        except Exception:                                        # noqa: BLE001
            continue
    return None


def read_plan(cdp, session_id: str) -> dict:
    """Evaluate the reader in an already-open chatgpt.com page and classify the result.

    Never opens or navigates: the caller supplies a session already on the origin. Use
    `attach_readonly` to get one for a tab you did not open.
    """
    try:
        raw = cdp.evaluate(session_id,
                           _READ_JS % {"urls": json.dumps(list(_ENDPOINTS))},
                           await_promise=True)
    except Exception as e:                                       # noqa: BLE001
        return {"state": UNKNOWN, "plan": None, "email_domain": None, "auth_mode": None,
                "has_active_sub": None,
                "detail": f"could not evaluate in the page: {type(e).__name__}: {e}"}
    return classify(raw)


def describe(verdict: dict) -> str:
    who = f" ({verdict['email_domain']})" if verdict.get("email_domain") else ""
    if verdict["state"] == SIGNED_IN:
        return f"signed in{who} on plan {verdict['plan']!r} — {verdict['detail']}"
    if verdict["state"] == GUEST:
        return f"NOT SIGNED IN{who} — {verdict['detail']}"
    return f"COULD NOT TELL — {verdict['detail']}"


# -- calibration ------------------------------------------------------------
_CASES = [
    # 🔴 Shape of a live browser payload WITH the bearer token (identifiers replaced).
    # `examplelite` is why a plan-name allowlist is not the gate.
    ("LIVE-shaped, bearer — a signed-in session (examplelite)",
     {"auth_mode": "bearer", "has_session": True, "email_domain": None,
      "status": 200, "url": "/backend-api/accounts/check/v4-2023-04-27",
      "accounts": [{"key": "acct-1", "plan": "examplelite", "email": None,
                    "has_active_sub": True, "sub_plan": "chatgptexamplelite"},
                   {"key": "default", "plan": "examplelite", "email": None,
                    "has_active_sub": True, "sub_plan": "chatgptexamplelite"}]},
     SIGNED_IN, True),
    # 🔴 Same shape, cookie-only. The bug: a clean 200 saying guest
    # about a session that is fine. Must be UNKNOWN, never GUEST.
    ("LIVE-shaped, cookie-only — the anonymous view of a healthy session",
     {"auth_mode": "cookie_only", "has_session": True, "status": 200,
      "accounts": [{"key": "default", "plan": "guest", "email": None,
                    "has_active_sub": False, "sub_plan": "chatgptguestplan"}]},
     UNKNOWN, False),
    ("cookie-only AND no session at all — genuinely signed out",
     {"auth_mode": "cookie_only", "has_session": False, "status": 200,
      "accounts": [{"key": "default", "plan": "guest", "email": None,
                    "has_active_sub": False, "sub_plan": "chatgptguestplan"}]},
     GUEST, False),
    ("bearer, and every account really is a guest plan",
     {"auth_mode": "bearer", "has_session": True, "status": 200,
      "accounts": [{"key": "default", "plan": "guest", "email": None,
                    "has_active_sub": False, "sub_plan": "chatgptguestplan"}]},
     GUEST, False),
    ("known positive (pro)",
     {"auth_mode": "bearer", "has_session": True, "status": 200,
      "accounts": [{"key": "default", "plan": "pro", "email": "x@example.com",
                    "has_active_sub": True, "sub_plan": "chatgptproplan"}]},
     SIGNED_IN, True),
    ("a renamed tier nobody has seen, with an active subscription — must still pass",
     {"auth_mode": "bearer", "has_session": True, "status": 200,
      "accounts": [{"key": "default", "plan": "ultra-2027", "email": None,
                    "has_active_sub": True, "sub_plan": "chatgptultraplan"}]},
     SIGNED_IN, True),
    ("paid tier whose subscription is explicitly inactive",
     {"auth_mode": "bearer", "has_session": True, "status": 200,
      "accounts": [{"key": "default", "plan": "plus", "email": None,
                    "has_active_sub": False, "sub_plan": "chatgptplusplan"}]},
     SIGNED_IN, False),
    ("workspace payload omitting has_active_subscription — absent passes",
     {"auth_mode": "bearer", "has_session": True, "status": 200,
      "accounts": [{"key": "ws", "plan": "enterprise", "email": None,
                    "has_active_sub": None, "sub_plan": None}]},
     SIGNED_IN, True),
    ("known negative — 401",
     {"auth_mode": "bearer", "status": 401}, GUEST, False),
    ("non-OK status with a parseable error body — not an answer",
     {"auth_mode": "bearer", "has_session": True,
      "url": "/backend-api/accounts/check/v1", "status": 404,
      "head": '{"detail":"Version not found"}'},
     UNKNOWN, False),
    ("empty — nothing came back", None, UNKNOWN, False),
    ("empty — payload with no accounts",
     {"auth_mode": "bearer", "status": 200, "accounts": None}, UNKNOWN, False),
    ("truncated — body did not parse",
     {"auth_mode": "bearer", "status": 200, "parse_error": True,
      "head": '{"accounts": {"def'}, UNKNOWN, False),
    ("fetch threw",
     {"auth_mode": "cookie_only", "threw": "TypeError: Failed to fetch"},
     UNKNOWN, False),
    ("session endpoint itself errored, cookie-only fallback",
     {"auth_mode": "cookie_only", "has_session": None,
      "session_error": "TypeError: Failed to fetch", "status": 200,
      "accounts": [{"key": "default", "plan": "guest", "email": None,
                    "has_active_sub": False, "sub_plan": "chatgptguestplan"}]},
     UNKNOWN, False),
    ("wrong shape entirely", "not a dict", UNKNOWN, False),
    ("server error",
     {"auth_mode": "bearer", "status": 503,
      "url": "/backend-api/accounts/check/v4-2023-04-27"}, UNKNOWN, False),
]


def selftest() -> int:
    if not _CASES:
        print("XX no cases: this self-test examined nothing")
        return 1
    bad = 0
    for name, raw, want_state, want_usable in _CASES:
        v = classify(raw)
        got = is_usable(v)
        ok = v["state"] == want_state and got == want_usable
        bad += not ok
        print(f"  [{'ok ' if ok else 'XX '}] {name}: state={v['state']} usable={got} "
              f"(want {want_state}/{want_usable})")
        if not ok:
            print(f"          detail: {v['detail']}")
    print(f"\n{len(_CASES) - bad}/{len(_CASES)} cases correct")
    return 1 if bad else 0


def live() -> int:
    """Read the real browser. Needs the broker and an open chatgpt.com tab."""
    import pathlib
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import broker as bk                                          # noqa: PLC0415
    if bk.ensure() is None:
        print("the broker would not start; cannot read the session")
        return 2
    c = bk.BrokerClient(label="auth read")
    try:
        sid = attach_readonly(c)
        if not sid:
            print("no chatgpt.com tab is open, and this will not open or navigate one")
            return 2
        v = read_plan(c, sid)
        print(describe(v))
        print(f"  state={v['state']} plan={v['plan']!r} auth_mode={v['auth_mode']!r} "
              f"usable={is_usable(v)}")
        return 0 if is_usable(v) else 1
    finally:
        c.close()


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    if "--live" in sys.argv:
        raise SystemExit(live())
    print(__doc__.splitlines()[0])
    print("\n  --selftest   calibrate the classifier, no browser needed")
    print("  --live       read the real session from an open chatgpt.com tab")
    raise SystemExit(0)
