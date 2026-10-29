# Driving the user's Chrome to reach ChatGPT

Everything here was measured on one Mac (Chrome 144+). **Every single
item fails silently if done the obvious way** — no exception raised, no error logged, just a wrong
or empty result that looks like the model said nothing. That is why this file exists instead of a
one-line "use CDP".

The
`chrome-session-fetch` skill covers the general procedure for fetching pages through the user's session;
this file covers only what ChatGPT specifically needs.

## Contents

- [Attaching](#attaching) — the consent sheet, and why no HTTP CDP client works
- [Never work in the user's tabs](#never-work-in-the user's-tabs)
- [Putting text in](#putting-text-in-never-type)
- [Submitting](#submitting-a-scripted-click-does-nothing)
- [Reading the reply](#reading-the-reply)
- [Retrieving files GPT wrote](#retrieving-a-file-gpt-wrote)
- [Reading a whole thread](#reading-a-whole-thread)

## Attaching

Chrome 144+ enables remote debugging **at runtime** and exposes **only** the websocket named in
`~/Library/Application Support/Google/Chrome/DevToolsActivePort` — a port (9222) on line 1 and a
browser path on line 2.

**All four `/json*` HTTP endpoints return 404.** So no HTTP-based CDP client works, and no library
that discovers targets via `--browserUrl` can attach. That is why `bin/cdp_client.py` is a
stdlib-only websocket client speaking just the CDP subset needed: adding a dependency would not have
helped, because the dependency would use the endpoints that are gone.

**The consent sheet is yours to press, never the user's.** Before connecting:

```bash
$BROWSER_TOOLS_DIR/allow-remote-debugging.sh 90 &
```

**A websocket handshake timeout IS an unanswered dialog sitting on the user's screen.** It does not raise;
it blocks in `sock.recv`. Do not diagnose it and move on — that leaves a modal in front of the user. This
happened and he had to point it out. Press it, then re-run the helper briefly to confirm nothing else
is queued.

🔴 **AND A SWALLOWED TRUSTED ENTER IS THE SAME DIALOG, ONE STAGE LATER.** This is the failure the
skill missed until 2026-09-28, and it cost the user a click.

The consent presser lives inside `cdp_client.connect` and is `terminate()`d in a `finally` the instant
the handshake returns. That covers the *connection*. It does not cover the *interaction* — and the
sheet does not have to block the handshake to do damage, because what it holds is **keyboard focus**.
So the connection is healthy, the composer is correctly filled, every readiness signal is green, and
each `Input.dispatchKeyEvent` Enter lands in the dialog instead of the page.

Measured: four consecutive Enters swallowed, **twice in a row**, while the broker log showed a healthy
attach and the epoch changing between runs — a new broker connection means a new sheet. The tool
reported *"something about the page has changed"*, which sent the diagnosis in entirely the wrong
direction, and the user eventually pressed Allow in person.

**So: whenever a trusted Enter is swallowed, press the consent sheet before retrying.** `consult.py`
now does this in the submit retry loop, and the helper's return value is the diagnosis rather than
fire-and-forget:

| swallowed Enter | sheet pressed | means |
|---|---|---|
| yes | **yes** | the modal was the cause; the next attempt will land |
| yes | **no** | something else holds focus — stop retrying and go look |

Two general lessons, both worth carrying beyond this skill:

- **A consent presser scoped to the connect is scoped too narrowly.** The sheet outlives the handshake,
  so anything that depends on keyboard focus must be covered too. If a new interaction phase gets
  added, it needs the same treatment.
- **"Retrying harder" is the wrong response to a keystroke that vanishes.** Four attempts into a modal
  is four wasted attempts plus a misleading error message. Identify what owns focus first.

## Never work in the user's tabs — and never leak your own

The MCP auto-selects the user's **first existing tab** when no target is given. Always pass an explicit
target, and close only tabs you opened.

**REUSE a tab; do not create one per attempt.** Learned expensively on 2026-09-26: `open_page`
created a tab on every call while `close()` deliberately leaves tabs open, so a run that retried a few
times leaked **19 ChatGPT tabs** into the user's browser. He noticed before the tool did. The cost was not
only clutter — that pile of live ChatGPT tabs, each polling, **rate-limited the API the tool
depends on**: `/backend-api/conversations` began answering `429`, and the tool could no longer find
its own thread. It then stayed 429 for many minutes after the tabs were closed.

So `cdp_client.open_page(url, reuse_match="chatgpt.com")` attaches to an existing tab on that origin
and navigates it, creating one only as a fallback.

**Reuse NAVIGATES, so a bad URL destroys the tab's state.** Passing a truncated conversation URL
navigated a live consult tab to that broken URL, after which `getTargets` reported the truncated URL
and the conversation read `400` — a self-inflicted failure that looked exactly like a server problem.
Never build a URL from a **display-truncated** listing; read the full value.

**Audit before closing.** Distinguish your tabs from the user's: bare `https://chatgpt.com/` tabs are yours
(that is where the tool opens), while a specific conversation URL may be one he is reading. Keep one
tab per live thread.

## Putting text in: never type

**Use `Input.insertText`.** Typing a multi-line prompt **submits at the first newline** — that is how
a probe intended as a no-op once sent a real message into the user's account. `insertText` raises no key
events, so newlines stay newlines.

Poll for the composer before inserting: **`document.readyState === "complete"` precedes composer
hydration by seconds**, because the page is a SPA. Wait for `div[contenteditable="true"]`.

## Submitting: a scripted click does nothing

**Submit with a trusted `Input.dispatchKeyEvent` Enter.** `element.click()` on the Send button is
found, enabled, visible, returns cleanly, logs success — **and posts nothing**, because a scripted
click is an untrusted event. Measured: a 7,217-char prompt sat in the composer while the tool waited
the full 600 s for a reply it had never requested.

Since `insertText` has already placed the entire prompt, **one Enter submits all of it**. The same
newline-submits behaviour that makes *typing* unsafe is what makes this work.

### The FIRST Enter after a page load is sometimes dropped, and no readiness signal predicts it

Measured 2026-09-27, after a consult waited the full 600 s for a reply to a message it had never
sent. The keystroke was **delivered** — a capture-phase listener recorded a trusted `keydown`,
`key: "Enter"`, `keyCode: 13`, `isTrusted: true`, targeting the focused `ProseMirror` element — and
ChatGPT simply did not act on it. Reproduced on a fresh navigation with a **116-char** message
(4.3 s after `Page.navigate`, composer present, `readyState: complete`, composer focused and carrying
`ProseMirror-focused`, Send button rendered and **enabled**) and originally with 21,131 chars. A
second Enter, dispatched later against the identical DOM state, submitted in **0.5 s**.

So **size is not the cause** — a 21 K `Input.insertText` blocks for 3.3 s and arms Send 0.03 s after
it returns — and there is nothing left to poll: every readiness signal available is already green
while the handler is not yet wired. It is also intermittent: a later run with the same timing
submitted first try.

**Confirm the submit locally, then retry.** ChatGPT empties the composer the instant it accepts a
message (observed at the first 0.5 s poll), so a composer that still holds the prompt is positive
evidence that **nothing was sent** — which makes a retry safe from double-posting, the one risk worth
being paranoid about here. That check is local and sub-second; the server round trip is the *second*
phase, and conflating the two is what turned a lost keystroke into a ten-minute wait. `bin/consult.py`
implements this as `submit()` / `await_posted()` / `await_reply()`, and
`tools/submit_guard_probe.py` asserts the retry, the refusal and the no-double-post property against
a fake transport.

**A definitive failure must empty the composer**, after writing the prompt to disk. Leaving 21,000
characters of unsent prompt in the user's own composer is user-visible mess, and the next thing he
types lands on the end of it.

Also gone: `button[data-testid="send-button"]` **no longer exists** — exactly one `data-testid`
survives page-wide. Do not select on it.

## Reading the reply

**`[data-message-author-role]` returns ZERO elements** on the current DOM. It is the widely
documented selector and it is stale here; code written against it returns an empty answer
indistinguishable from the model saying nothing. Use
`div[data-markdown-text-style="assistant-message"]`.

**Never match class names** — they are hashed (`MarkdownRoot-rZKhxa`) and change without notice.

**Completion and baselines must come from the SERVER, not the DOM.** The DOM is virtualized: a long
thread can report a handful of rendered assistant nodes against many more real turns. A rendered count is
therefore useless as a before/after baseline. Poll `/backend-api/conversation/<id>` and compare
`create_time` against a timestamp taken before sending.

**Confirm the prompt posted before waiting on a reply at all.** That distinction is what turns a
silent non-send into a clear error rather than a ten-minute hang. The page does announce
`Response complete`, but a live region can hold the *previous* turn's announcement, so it is not a
reliable completion signal on its own.

## Retrieving a file GPT wrote

Two hops, and the API tells you the contract.
`/backend-api/conversation/<id>/interpreter/download` rejects a bare `file_path` with **422 naming
the fields it wants** — `message_id` and `sandbox_path` — then returns a signed `download_url` rather
than the bytes, so fetch that too.

**Do it immediately.** Files are `sandbox:/mnt/data/...` paths in containers that expire; the first
document retrieved this way was lost to an expired container and had to be re-requested.

## Reading a whole thread

Cookies alone give `404 conversation_inaccessible`. Fetch `/api/auth/session` for `accessToken`, then
`/backend-api/conversation/<id>` with `Authorization: Bearer …`.

**Never persist that token to disk.**

Scraping the DOM instead silently truncates, because it is virtualized — only the last few turns
exist. A long history recovered via the API can reveal advice that was issued and never applied.

## Endpoints, verified 2026-09-26

Discovered by deliberately sending a minimal payload and reading the **422**, which names the fields it
wants. That is a cheap, safe way to learn an undocumented contract — much better than guessing a
schema and creating the wrong object.

| need | call | notes |
|---|---|---|
| list Projects | `GET /backend-api/gizmos/snorlax/sidebar` | `id`, `short_url`, `display.name`. **Adding `?limit=100` makes it 422** — send no query params. |
| list conversations | `GET /backend-api/conversations?offset=&limit=&order=updated` | rate-limited; see below |
| read a conversation | `GET /backend-api/conversation/<id>` | bearer required |
| rename a conversation | `PATCH /backend-api/conversation/<id>` `{"title":…}` | |
| **create a Project** | `POST /backend-api/projects` `{name, instructions}` | returns a `g-p-…` id |
| delete a custom GPT | `DELETE /backend-api/gizmos/<id>` | returns `{"deleted":true}` |

**`POST /backend-api/gizmos` creates a CUSTOM GPT, not a Project**, even though Projects are gizmos and
appear under that namespace. It answers `200` with a `g-…` id where a Project has **`g-p-…`**. This is
the one to get right: a wrong call here silently puts a stray object in the user's account that looks like it
worked. It happened, and the stray was deleted with the call above.

**Read the returned id prefix to confirm you created what you meant to.** `g-p-` is a Project; `g-` is
a GPT. A 200 is not confirmation of the right *kind* of thing.

## Do not read Projects out of the sidebar DOM

Two independent ways it lies. A conversation **inside** a Project has the same `/g/g-p-` URL prefix, so
`a[href*="/g/g-p-"]` returns thread titles as though they were Project names. And on a freshly opened
tab the sidebar may not be rendered at all, which yields "no Projects visible" — a confident wrong
answer indistinguishable from the Project genuinely not existing. Both happened in sequence. Use the
API row above; a real Project link's path ends at `/g/g-p-<id>-<slug>` with no `/c/` segment.

## Transient failures worth retrying rather than escalating

`/api/auth/session` has returned **403 transiently and recovered on retry**. Do not escalate a single
403 to the user as a lapsed session — retry once first. Report a lapse only when it persists.

`/backend-api/conversations` returns **429** under repeated polling, and it persists for minutes after
the cause is removed. **A 429 there must never be read as "this repo has no thread"** — that would
create a duplicate thread and split the accumulated context the whole design exists to preserve. Back
off, then refuse rather than create.

## A brand-new thread is unreadable for a moment

Right after the first message posts, the URL carries a client-generated conversation id **before the
server has persisted it** — measured shape: `/c/local-chatgpt%3A<uuid>`, swapped for the real id after
~2.5 s — so `GET /backend-api/conversation/<id>` answers `400`/`404` for a second or two. Detect it by
the `local-` prefix and report it as *pending* rather than as a read failure; a caller that cannot
tell the two apart has to guess whether to keep waiting.

Treat it as "not ready" only while the prompt is still unconfirmed; once posting is confirmed, a read
failure is real and must surface instead of spinning to the deadline.

## The Allow sheet reappears on EVERY connection

`allow-remote-debugging.sh` presses one sheet and exits. A run that connects more than once therefore
leaves a second sheet on the user's screen, and the websocket handshake **blocks in `recv` rather than
erroring**, so the tool appears to hang. Use `bin/keep-allowing.sh <seconds> &` to keep pressing for
the whole session, and kill it when done. Pressing that sheet is the agent's job — he had to click one
himself on 2026-09-26, which is precisely the wasted turn the helper exists to prevent.

**It is per CONNECTION, by design in Chromium, and it is what steals focus.** Three consecutive
`CDP()` constructions in one process raised three sheets. The sheet has no "remember" affordance —
its whole accessibility tree is a heading, two static texts and exactly three buttons:
`Turn off in settings`, `Cancel`, `Allow`. The runtime toggle at `chrome://inspect` starts the
DevTools server in `kWithApprovalOnly`, which requires approval per incoming connection, and the
dialog code calls `Activate()` on the browser window before showing the sheet. So the focus theft is
instructed, not a macOS side-effect.

**`--remote-debugging-port` does not rescue this on the user's profile.** It starts the server in the
no-approval mode, but since Chrome 136 the switch is **ignored unless Chrome runs on a non-default
`--user-data-dir`** — which means a different profile, i.e. not the logged-in ChatGPT session. There
is no supported knob that keeps the runtime-toggle mode and drops per-connection approval. **The way
to pay this less often is fewer connections, not a cleverer restore.**

## Everything except the connect is invisible — measured, and protected by a probe

Six rounds on 2026-09-26, Chrome 154. Ground truth is taken from **outside** the browser
(AppleScript's frontmost app and Chrome's own tab state), because the in-page signals mislead.

| step | disturbs the user? |
|---|---|
| websocket connect | **yes** — Chrome becomes frontmost for the Allow sheet |
| `Target.createTarget` **with `background: true`** | no |
| `Target.createTarget` without it | **yes** — the new tab becomes the active tab |
| `Target.attachToTarget`, `Runtime.enable` | no |
| `Page.navigate` on a non-active tab | no |
| `Input.insertText`, trusted `Input.dispatchKeyEvent` Enter | no |
| `Target.closeTarget`, idle connection | no |

So **a whole consult can run in a tab the user never sees**: input reaches a background tab, and
`background: true` keeps it background. `CDP(restore_focus=True)` re-activates the app that was
frontmost before the socket opened, which turns the one remaining steal into a ~1.1 s flicker.

Three details that are easy to get wrong:

- **Restore is compare-and-restore.** Only re-activate if the app frontmost *afterwards* is Chrome.
  If it is anything else the user acted during that second, and yanking the user back is worse than the
  steal. Identify the user by **bundle id**, not name — names are neither unique nor stable.
- **The invariant must include the window COUNT and every window's active tab**, not just the front
  window's. The dangerous failure is not a tab foregrounding, it is Chrome failing to find an
  eligible window and opening a **new** one, which a front-window check cannot see. Hazards worth
  probing if this ever regresses: zero browser windows, only a popup/PWA window, a window belonging
  to another profile, fullscreen on another Space, session restore still running.
- **`Target.createTarget` silently accepts unknown parameters, so "it was accepted" proves nothing.**
  A review suggested adding `focus: false` as a second expression of the invariant. Chrome 154 accepts
  it — and accepts `zzzNotARealParam: true` just as happily, and the protocol page lists no `focus`
  parameter on `createTarget` at all. So it is not used: an unvalidated flag that may do nothing is
  worse than no flag, because it reads as protection. Test a nonsense parameter before concluding a
  real one is supported.

`tools/focus_probe.py` asserts all of this against a local `file:` URL, never chatgpt.com, so a
stray Enter cannot post anything. It carries a **control arm** that creates a tab *without* the flag
and requires it to disturb the active tab — a probe that cannot observe the failure it exists to
detect would report success forever.

## The presser is inside `CDP.__init__`, and the sheet is matched structurally

Two traps, both of which produced a modal left sitting on the user's screen.

**Pressing the sheet belongs to whatever opens the socket.** It used to be the caller's job, and a
caller who forgets does not get an error — the handshake **blocks in `recv`** for the whole deadline,
which looks exactly like a dead browser. That happened twice in one session, once from `--direct` and
once from a probe. `CDP.__init__` now spawns `bin/keep-allowing.sh` itself, so every opener is covered.

**`axprobe --within "Allow remote debugging?"` matched the wrong element, and the collision was
self-inflicted.** `--within` is a substring match over the whole AX tree, so once a Chrome tab
happened to *display* the words "Allow remote debugging?" — a chat thread about this very sheet —
the presser scoped itself into that page's static text, found no buttons, and reported
`0 sheet(s) pressed` while a sheet was up. `allow-remote-debugging.sh` now asks **System Events**
whether a real sheet of a real window carries that name, and only then hunts the button **app-wide by
role**. The sheet precondition is what makes the app-wide search safe. Same lesson as any false
zero: a query that can match the wrong thing returns a confident wrong answer.

## Do not reuse a tab another debugger is attached to — and "another" excludes the broker

Attaching a second session to a target with `attached: true` was measured to hang: the attach returned
in 0.0 s and the following `Runtime.enable` never answered, stalling to the socket deadline. Chrome
also reports a tab as unattached while a dying connection's session is still tearing down, so the
state is not fully trustworthy either way.

Two things follow, and the second is the trap. Skip a **foreign** attachment, and treat a failed
candidate as a reason to try the next one rather than to fail the consult. But `attached` alone is the
wrong test, because **the broker's own attachments set it too** — skipping those would create a fresh
tab on every consult, which is the 19-leaked-tabs failure tab reuse exists to prevent. The broker
therefore annotates each target with `brokerOwned` (additive, so the real protocol field stays
truthful), and a tab we own is still reusable.

## `hasFocus()` lies under CDP; `visibilityState` lies for a different reason

With sessions attached, **13 of 14 page targets reported `visibilityState === "visible"` and
`hasFocus() === true` at once** — impossible for 14 tabs in one window. Two things were separated by
measurement, and the distinction matters:

- **`document.hasFocus()` is focus emulation.** `Emulation.setFocusEmulationEnabled({enabled:false})`
  flipped it `true → false` on 11 of 14 targets, leaving it true only where the tab genuinely was
  active. So it is recoverable if a page ever needs the truth.
- **`document.visibilityState` stayed `"visible"` on every target even with focus emulation off.**
  Its cause is unexplained and it remains unusable as a "is this tab in front" oracle.

**Rule out your own session routing before blaming Chrome.** The first hypothesis for an impossible
reading like this was a flattened-session routing bug in `cdp_client` — every answer coming from one
page. It was tested by comparing each session's own `location.href` against the `TargetInfo.url` it
was attached for: **0 mismatches of 14**, so routing is sound and the reading is real. That check is
cheap and it is the right first move, because a routing bug would also be a live defect in the code
that posts prompts.
