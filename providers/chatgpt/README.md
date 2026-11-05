# ChatGPT provider

Folded into Dispatch as `providers/chatgpt/`. The skill is
`Dispatch/skills/chatgpt-consult/`. The consult ledger and `.consult/` state moved to the private
overlay (`dispatchlib/providers.py`); without one, the ledger is a git-ignored local file.
Tests: `cd providers/chatgpt && python3 -m pytest -q tests`.


A standing Claude Code skill that makes **consulting ChatGPT a normal part of every project** —
adversarial code review, design-document hardening, and escalation when a bug will not yield — through
your own logged-in Chrome, with every consultation recorded so the practice can be judged on
evidence.

## Why

A second model reading work cold catches a class of defect the author structurally cannot catch: the
thing nobody thought to check. When the same process produces the work and grades it, the grade is the
weakest link.

The case that motivated this: a scoring harness reported `0 spurious` fabricated edges. The figure was
meaningless — the scorer keyed families by a field that most structures did not have, so an entire class
of failure was invisible to the instrument built to certify its absence. Re-running the author's own
tests could never have found it. One GPT review did.

## Layout

```
SKILL.md                      the skill: when to consult, how to ask, the authority rules
references/
  chrome-cdp.md               browser access facts — each fails SILENTLY if guessed
  thread-management.md        finding, creating and recovering Consult_<Project>
  prompt-patterns.md          framings that produced findings rather than praise
  ledger.md                   the effectiveness record, and how to read it back
bin/
  consult.py                  the driver
  cdp_client.py               stdlib-only CDP websocket client
ledger/consults.jsonl         append-only record of every consultation and its outcome
```

## Install

```bash
ln -s ~/dev/Dispatch/skills/chatgpt-consult ~/.claude/skills/chatgpt-consult
```

## Use

```bash
python3 ~/dev/Dispatch/providers/chatgpt/bin/consult.py --prompt-file q.md --kind code_review
python3 ~/dev/Dispatch/providers/chatgpt/bin/consult.py --ledger
```

Sends by default; `--draft` composes without submitting. Threads live in the `Consults` ChatGPT
Project, one per repo, titled `Consult_<Project>`, so context accumulates across sessions and days.

## More than one user

Two people can share this repo and one ChatGPT account and still keep separate records. Each user can
put a `~/.config/chatgpt-consult/config.json` on each machine they consult from:

```json
{
  "ledger": "ledger/consults-user.jsonl",
  "chatgpt_project": "ClaudeConsultUser",
  "thread_prefix": "ConsultUser_"
}
```

- `ledger`: that user's ledger. Relative paths resolve against this repo. Keep it in `ledger/`, so the
  files can be read separately or together.
- `chatgpt_project`: the ChatGPT Project where that user's new threads are created. The user creates it
  by hand; the tool never creates Projects.
- `thread_prefix`: threads are titled `<prefix><repo>`. **This, not the Project, is what keeps two
  users' threads apart.** Thread recovery searches titles across the whole account, so a shared prefix
  would let one user's `Machinist` recover the other's thread.

With no file, every value keeps its original default (`ledger/consults.jsonl`, `ClaudeConsult`,
`Consult_`). An unreadable file stops the tool rather than falling back to those defaults.
`CHATGPT_CONSULT_CONFIG` points at a different file. Codex consults are ephemeral and never touch a
Project or a thread; for them, only `ledger` matters.

## The rule that keeps it useful

A second model's answer is **guidance, never authority**. It may not serve as a grading key, may not
override a human ruling, and may not be cited as evidence that a component works. Argue with it when
it is wrong — a consultation you pushed back on is worth more than one you rubber-stamped.

And never fabricate a reply. If the channel breaks, say so. An invented answer attributed to another
model launders your own reasoning as independent corroboration, destroying the one property that made
the consultation worth doing.

## Local desktop app

If a ChatGPT or Codex desktop app is already installed, it may be used. If it is not, **do not install
it** — it may be disallowed as a local application on managed machines. Browser access is the usual
route and is what this tooling uses.
