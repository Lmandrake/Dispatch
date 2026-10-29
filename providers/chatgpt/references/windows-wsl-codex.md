# Consulting from Windows/WSL: the native `codex.exe` route, and lessons from running it

The container transport in `SKILL.md` needs Colima, which a Windows/WSL2 machine does not have.
There the working route is the Windows Codex CLI (`codex.exe exec`) driven from WSL. The reference
implementation is a small (about 100 lines) `gpt_consult.py` wrapper (it needs a `find_codex_cli()` and a `wsl_to_win()` helper).
Copy its shape rather than re-deriving it, because each line below was paid for.

The lessons that are not WSL-specific (effort, size, parallelism, grading) apply to every transport.

## The call

```
codex.exe exec --sandbox read-only --skip-git-repo-check -o <WIN path>\answer.md \
  -c model_reasoning_effort="high" -m gpt-6.1-sol -
```

- **Prompt on stdin (`-`).** That avoids the Windows command-line length limit entirely. If you pass
  the prompt as an argument instead, close stdin.
- **`--sandbox read-only`.** A consult reads; it never edits.
- **`-o` takes a Windows path.** Convert with `wslpath -w`, or the equivalent helper.
- **Model `gpt-6.1-sol`, effort `high` as the floor.** Consults want deep reasoning, so low effort is not used. `gpt-6.1-sol` was measured
  answering (not refused). Image generation is a separate path with its own default
  model (`gpt-5.5` at the time), so do not let a consult default leak into it, or the reverse.

## WSL path traps (measured 2026-10-02)

- **An ext4 (`\\wsl.localhost\...`) cwd breaks codex's sandbox helper** (`orchestrator_helper_launch_failed`).
  Stage each job in a directory on a Windows drive and run with that as the cwd. A suitable path is
  `<scratch drive>\codex\consult-<timestamp>-<pid>\`.
- **Reading a `\\wsl.localhost` path from a Windows cwd hangs**, and even Windows-drive reads through
  the sandbox are flaky. **So inline every input into the prompt.** Do not ask codex to open files.
- **Inline format that works:** the question, then the line *"The files below are inlined in full; do
  not try to open them from disk."*, then each file between `===== FILE: <repo-relative path> =====` and
  `===== END FILE: <path> =====`. Repo-relative names let the answer cite `file:line` you can check.
- **Encoding.** Through Windows PowerShell's codepage, codex reads `°` and `§` as mojibake. Pass the
  prompt as UTF-8 bytes on stdin, and either say "read as UTF-8" or keep the prompt ASCII.

## Size, time, and parallelism

- **Keep a consult under about 700k characters.** A 777k-char consult had the middle of its inlined
  prompt silently dropped, and the model still answered with confidence. It said so only because it
  was asked to. Each prompt should ask for an **"Outside this slice"** list of anything it could not
  see, and you should re-run a smaller consult for whatever lands there (2026-10-10).
- **Slice large reviews with a manifest.** Write one file list per consult, put every source file in
  exactly one slice, and include the shared context (the design and its prior review) in all of them.
  The prompt then says: "Review ONLY against the code you can see; when a claim depends on code not
  in this slice, say 'outside this slice' rather than guessing."
- **Budget time for it.** At high effort, ~700k-char consults took 438–970 s each. A 1500 s timeout
  suits ordinary consults; give large slices 3000 s.
- **Run consults one at a time, or guard them.** Two consults launched at the same moment once
  crossed answers: the run about subject A got back an answer about subject B (2026-10-02). If you do
  run them in parallel, name the subject in the prompt, ask the answer to restate it, and check it.
- **No live process does not mean a dead consult.** It may have finished and written its answer while
  you waited on a monitor. Read the output file before reporting it dead. One consult was reported to
  the user as dead 50 minutes after it had finished.

## Failure modes that look like answers

- **Expired ChatGPT auth** prints a plausible session header, then repeated 401 refresh-token errors,
  then exits 1. Grade the answer body, never the header or the exit code. Re-login is the user's
  interactive act, so ask the user.
- **Strange failures after a Codex app update** (a "module could not be found" dialog, UAC prompts)
  have cleared only after killing stale pre-update `codex.exe` / `codex-code-mode-host.exe` processes.
  Check `tasklist.exe | grep -i codex` before anything else.
- **An empty or missing `answer.md`** means the consult failed. Keep the job dir and read the tail of
  codex's log; do not retry blind.

## Framing that produced findings (complements `prompt-patterns.md`)

**Code/design review.** Open with "You are an adversarial senior reviewer for <project>", give one
paragraph of context, list numbered topics to check the design against the code, then fix the output
format:

- `## Findings`: numbered, each with severity (BLOCKER / MAJOR / MINOR), a title, evidence as exact
  `file:line` from the inlined files, why it matters, and a concrete fix. "Only real, evidenced
  findings; no style nits."
- `## Design claims verified`: the claims it checked and found true.
- `## Outside this slice`: anything it could not check.

End with "Be specific and terse. Do not rewrite the design."

**Stuck bug.** The brief carries the symptom and its class, expected vs actual, the last-known-good
state and what changed since, versions, the failing result rows, the log's **first** exception, what
was ruled out and by which check, and the relevant source excerpts (GPT reads nothing it is not
given). Ask one question: **"Rank the hypotheses and give the cheapest test that tells each apart."**

## Reading the answer

- **GPT's answer is a hypothesis, never a verdict.** Test each material claim with the strongest
  instrument that fits: a script, the source, the log, a bisection. Nothing it says closes work or
  reaches the user as a finding until that test has passed.
- **Verify every line-level claim against the file.** One consult reported an extra closing brace in
  a 153-line file whose braces balanced 27/27.
- Keep the prompt and the answer next to the work while it is live. Commit only what survives: the
  tests that were confirmed, and the false theories worth knowing.
