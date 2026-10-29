# Getting a GPT consult through reliably — a working recipe

Written from a session on a **fully set-up Mac** that completed two consults
end to end, including one long deep-research reply, after the tool's own reply-collection failed
both times.

🔴 **These steps were verified on ONE set-up Mac only.** Read on a second Mac that
had never been set up, not one of them applied — see step 0. Every
claim below is about a machine where the debug server binds and an `--autoConnect` MCP server is
declared. **Run step 0 before trusting any of it.**

**The headline: `consult.py` posting and `consult.py` reading the reply are two separate
things, and the second one fails often. That is survivable and does not mean the consult
failed.** Treat a failed read as a retrieval problem, never as a reason to resend.

---

## 🔴 STEP 0 — RUN THE PREFLIGHT. Every step below presupposes a precondition this document does not check.

```bash
python3 ~/dev/Dispatch/providers/chatgpt/bin/preflight.py          # --fix applies what an agent may fix
```

Exit **0** clean · **1** blocked on a human · **2** fixable by you.

**Added 2026-09-29 after this recipe was read on a second Mac and helped with nothing**, because
its step 1 assumes Chrome's remote-debugging server is already **bound** and on that machine it
was not. Everything from "start the presser" onward is then a no-op: with nothing bound, no
connection is ever attempted, so no Allow sheet can appear and `allow-remote-debugging.sh`
reporting *"no sheet appeared"* is **uninformative, not evidence**. A session spent hours
debugging the transport instead.

Three preconditions differ per machine, and the recipe originally named none of them:

| precondition | whose job | what its absence looks like |
|---|---|---|
| Runtime debug server **bound** (`chrome://inspect/#remote-debugging`, *"Allow remote debugging for this browser instance"*) | **HIS** — no `defaults` key, cannot be scripted | `No DevToolsActivePort`; broker `connected: false` |
| An MCP server declared with **`--autoConnect`** | yours | `mcp__chrome-mine__*` does not exist; the only browser MCP launches its **own** throwaway Chrome, signed into nothing |
| Repo **enrolled** | yours | sends silently fall back to draft |

⚠️ **The toggle is PER BROWSER INSTANCE and persists in no preference file** — it is lost on
every Chrome restart, so *"he enabled it yesterday"* is never a reason to skip step 0. The page
also carries a live **`Server running at: <address>`** line; if it reads `starting…` the toggle
is on and the server still has not bound, which is a separate unexplained failure not explained here.

⚠️ **`claude mcp list` saying a server is "Connected" does not mean the browser is reachable** —
that is the stdio handshake with the MCP process. The Chrome attach happens on the first tool
call. Measured: `chrome-mine` reported Connected while nothing was bound.

**If step 0 exits 1, stop.** Ask the user in words, then re-run it. Do not curl `/json/version`
(all four `/json*` endpoints 404 by design on a runtime-enabled Chrome), do not launch a
throwaway profile with `--remote-debugging-port` (it works, and is signed into nothing), and do
not start the presser. If he cannot or will not enable it, the working fallback is the GUI path
in §9.

---

## 1. Start the Allow-sheet presser FIRST. This is the biggest single win.

```bash
~/dev/Dispatch/providers/chatgpt/bin/keep-allowing.sh 900    # run in BACKGROUND, before any CDP call
```

Chrome raises "Allow remote debugging?" on **every new client connection**, and the websocket
handshake **does not error on it — it blocks in recv**. So the tool looks like it is hanging
while a modal silently waits for a human, and every readiness signal still reads green.

Symptoms of an unpressed sheet, all of which look like something else:

- an MCP browser call returning `user-cancel`
- `Runtime.evaluate: TimeoutError`
- a consult that appears to hang with no output

`consult.py` presses the sheet for **its own handshake only**. That scope does not cover a
second connection made later in the session — in particular a `chrome-mine` MCP call, which is
exactly what you need for the recovery path below. So start the standalone presser anyway, and
restart it if you killed it before you were actually done.

Pressing that sheet is the agent's job. Never let it reach the user.

## 2. Check the broker before assuming trouble

```bash
python3 ~/dev/Dispatch/providers/chatgpt/bin/broker.py --status
```

`"connected": true` with a stable `epoch` means no new sheet is needed at all. An epoch that
changes mid-session is a warning sign — a new broker connection means a new sheet.

## 3. One-time per repo

```bash
python3 ~/dev/Dispatch/providers/chatgpt/bin/consult.py --enroll
```

Without it the consult silently falls back to draft. Also add `.consult/` to that repo's
`.gitignore` — it holds a pointer into a ChatGPT account plus raw transcripts.

## 4. Two arguments that waste a whole round trip if wrong

**`--trigger` is a closed set.** `user_request` is **not** valid and argparse rejects the whole
invocation, so nothing is sent while the exit code still looks clean. Valid values:

```
measurement_machinery  risky_implementation  decision_bearing_design  debug_stall
impossibility_claim    universal_result      research_needed          user_asked   other
```

**Never wrap the call in GNU `timeout`.** It does not exist in this BSD userland, fails with
exit 127 *before* the wrapped command runs, and a hook may block it for precisely that reason. Use
the Bash tool's own `timeout` parameter, or `run_in_background`.

## 5. Run it in the background and do other work

```bash
python3 ~/dev/Dispatch/providers/chatgpt/bin/consult.py \
  --prompt-file /tmp/q.md --kind design_review --trigger measurement_machinery \
  --believe "known: …; hypothesis: …; unsure: …"
```

Backgrounding it matters because a deep-research reply can take **5–15 minutes**. Read the
progress log for the decisive line:

```
prompt confirmed posted — https://chatgpt.com/g/g-p-…/c/<conversation-id>
```

**Once you see that, the prompt is in the thread.** Anything that fails afterwards is a read
failure. Both of these are read failures and both are recoverable:

```
FAILED: Runtime.evaluate: TimeoutError: timed out [INTERNAL]
SUBMITTED but the reply could not be read: 'conversation HTTP 429'
```

`--show-thread` will not help for a `--cold` consult: cold goes to a fresh conversation, so
nothing is cached under `Consult_<Repo>` and you get `no thread cached`. Use the recovery path.

## 6. The recovery path that works: read the tab over the chrome-mine MCP

Presser running, then:

**a. Find the tab** — `mcp__<autoconnect-server>__list_pages`, and match the conversation id
from the "prompt confirmed posted" line. ⚠️ **`chrome-mine` is a name somebody chose, not a
given** — step 0 prints the server that is actually declared on this machine and its tool
prefix. On a machine with no `--autoConnect` server, the only browser MCP is the plugin's, whose
tools are `mcp__plugin_chrome-devtools-mcp_chrome-devtools__*` and which drives **its own**
Chrome, so `list_pages` will never show a ChatGPT tab however long you look.

**b. Wait for generation, then extract.** One call does both. Poll for the stop button to
disappear rather than guessing a duration, and write to a file so a 30 000-character reply does
not land in context:

```javascript
async () => {
  const gen = () => !!document.querySelector(
    'button[data-testid="stop-button"], button[aria-label*="Stop"]');
  const t0 = Date.now();
  while (gen() && Date.now() - t0 < 170000) { await new Promise(r => setTimeout(r, 4000)); }
  const nodes = document.querySelectorAll('div[data-markdown-text-style="assistant-message"]');
  const texts = Array.from(nodes).map(n => n.innerText).filter(t => t.length > 200);
  return {stillGenerating: gen(), nodes: texts.length, reply: texts.join('\n\n---\n\n')};
}
```

Pass `filePath` to `evaluate_script`. ⚠️ **`waitForStableDom` is not a parameter on every
version** — one plugin build accepts only `function`, `args`, `dialogAction` and
`filePath`, and passing an unknown key is rejected rather than ignored. Check the tool's own
schema before copying this line.

**c. Convert and read.**

```bash
python3 -c "
import json; d=json.load(open('.consult/reply.json'))
open('.consult/reply.md','w').write(d['reply']); print(len(d['reply']),'chars')"
```

**Two traps in the extraction itself.** The `> 200` char filter is load-bearing: without it you
collect ten reasoning-progress nodes totalling 600 characters and conclude the reply is the
string `"Searched 2 websites"`. And if `stillGenerating` comes back `true`, you have a partial
answer — poll again rather than reporting what you have. A deep pass legitimately needed three
consecutive ~170 s waits here.

## 7. Framing is what determines reply quality

Measured across both rounds: naming your own weakest joint and saying plainly that *you are the
party being graded* produced concrete attacks, not praise. Ask for counterexamples you can turn
into tests rather than an assessment. State what you already ruled out, so the reply does not
spend itself rediscovering your context. Long prompts are fine — 10 000 characters worked well.

And the standing rule: the reply is **guidance, never a grading key**, and it **cannot override
a standing ruling**. When the user ruled the scope of a design down, the right move was a second
consult framed by the user's ruling — not absorbing recommendations he had declined.

## 8. Housekeeping

Kill the presser when genuinely finished (`pkill -f keep-allowing.sh`), record findings with
`--record-finding`, and remember that `confirmed` requires independent verification — GPT
asserting a defect is not evidence of one.

---

## 9. When the debug server will not bind at all: send it by hand

**This is not in the spirit of the tool and it is still the right move when step 0 exits 1 and
he cannot enable the toggle.** Measured on a second Mac: it sent an 9,068-character
prompt and got a 36,000-character deep-research reply back, with the CDP path refusing
throughout.

It works because the user's ChatGPT window is *already open and already signed in* — the only thing
missing was a way for a program to reach it.

```bash
pbcopy < notes/your-question.md                      # NEVER type it: see below
osascript -e 'tell application "Google Chrome" to activate'
$BROWSER_TOOLS_DIR/bin/uiclick <x> <y>            # the composer
osascript -e 'tell application "System Events" to keystroke "v" using command down'
screencapture -x -o /tmp/check.png                   # VERIFY before submitting
osascript -e 'tell application "System Events" to key code 36'   # Return
```

**Why paste and never type.** `references/chrome-cdp.md` records that typing a multi-line prompt
submits it at the first newline. A clipboard paste raises no per-key events, which is the same
reason `Input.insertText` is mandated on the CDP path — so `pbcopy` + Cmd+V satisfies that rule
rather than breaking it.

**Getting the reply back out.** Clicking the message's copy button by coordinate is fiddly and
was measured failing twice; clicking *in the message body* then Cmd+A, Cmd+C captured the whole
page reliably. Trim the app chrome afterwards. The reply arrives with headings and code fences
flattened — acceptable for reading, not for quoting structure.

**Screenshot before pressing Return.** Verify the paste landed in the composer and not somewhere
else. The GUI is machine-wide: `frontmost`, the keyboard and the clipboard are shared, so nothing
else may be driving the GUI at the same time — including your own background agents.

### 🔴 The step that is easy to skip: reconcile the ledger

A hand-sent consult leaves `consult.py`'s row saying `sent: false, reply_chars: 0` — accurate
about the CDP path and **wrong about what happened**. The effectiveness record then shows a
consult that failed and produced nothing. There is no `--record-consult`, so attach the findings
to the real `consult_id` and say in the note that the send was out of band:

```bash
python3 ~/dev/Dispatch/providers/chatgpt/bin/consult.py --record-finding <consult_id> \
  --finding-id <slug> --novel yes --correctness confirmed \
  --verification source_inspection --severity major --disposition applied \
  --note "Sent BY HAND into the user's own logged-in window; the CDP path refused. <finding>"
```

A ledger that silently mixes hand-sent and tool-sent consults cannot be read, and the whole
point of the ledger is to measure whether this channel is worth its cost.
