# Finding, creating and recovering the consult thread

One thread per repo, titled `Consult_<Project>`, all of them inside a single ChatGPT **Project**
named `Consults`. This is the convention.

## What the URL shape tells you

```
https://chatgpt.com/g/g-p-<project-id>-<project-slug>/c/<conversation-id>
                      └──────── ChatGPT Project ────────┘  └── thread ──┘
```

A URL with no `/g/g-p-…` segment is a **top-level** thread, not in any Project. That is the shape to
avoid: if the tool ever reports a thread URL without that segment, the thread was created outside
`Consults` and should be recreated in the right place rather than used.

An older thread that predates this convention can stay where it is — moving a thread loses nothing
but gains nothing either, and its accumulated context is the whole reason it is valuable. New projects go in `Consults`.

## Resolution order

The cache is checked first because it is the only step that costs nothing.

1. **`<repo>/.consult/thread.json`** — the cached URL for this repo. Add `.consult/` to the repo's
   `.gitignore`: it holds a pointer into the user's personal account plus raw transcripts, neither of which
   belongs in a shared repo.
2. **Search the user's conversation list by title.** `GET /backend-api/conversations?offset=0&limit=100`
   with the bearer token (see `chrome-cdp.md`), then match `title == "Consult_<Project>"`. This is
   the recovery path when the cache is lost — a fresh clone, a new machine, a deleted state dir.
   Recovering beats creating, because a new thread starts with none of the accumulated context that
   makes the channel worth using.
3. **Create it**, inside `Consults`.

## Creating a thread inside Consults

Navigate to the Project and start a conversation there, rather than creating a conversation and
trying to move it — ChatGPT has no reliable "move to Project" affordance over CDP.

1. Resolve the Project's URL by title. If `Consults` does not exist, **stop and tell the user**
   rather than creating a Project. Creating a Project is a visible, structural change to the user's account
   and he named this one specifically; if it is missing, the likeliest explanation is a different name
   or a typo on our side, not that he wants a new one.
2. Open the Project URL, wait for the composer (`div[contenteditable="true"]` — `readyState` is not
   enough, see `chrome-cdp.md`), then insert and submit the first prompt. The conversation is created
   by the first message, and the URL gains its `/c/<id>` segment only after it posts.
3. Read the resulting URL and cache it.

**Title the thread explicitly.** ChatGPT auto-titles from the first message and that title is
unpredictable, which breaks the title-search recovery path above. Rename via
`PATCH /backend-api/conversation/<id>` with `{"title": "Consult_<Project>"}` and the bearer token.
If the rename fails, the thread still works — the cache is the primary mechanism — but say so, because
recovery for that repo is now cache-only.

## What "project name" means

The repo directory name, verbatim casing: `ExampleProject`, `ExampleTool`. Derive it from
`git rev-parse --show-toplevel` so it is stable regardless of the working directory inside the repo,
and so two sessions in the same repo resolve the same thread.

For work outside a git repo, there is no project identity to key on. Use the containing directory name
and say in the prompt that the consult is not repo-backed, so a future reader of the thread is not
misled into thinking a repo exists.

## Recovering a reply from a previous session

The reply is already in the thread and in `<repo>/.consult/`. Read the transcript first — it is on
disk and free. Only go to the API if the transcript is missing, and then fetch
`/backend-api/conversation/<id>` rather than scraping: **the DOM is virtualized and scraping silently
truncates to the last few turns.** Reading the full history through the API can reveal advice that was never applied.

## When the thread gets long

Long threads are the point — accumulated context is why a persistent thread beats a fresh one. But two
real limits arrive eventually: the model's context window, and the fact that a stale early turn can
contradict a later correction. When a thread is clearly labouring, do not silently start a new one.
Tell the user, and propose a summary hand-off — a fresh thread whose first message carries the
still-live conclusions. Silently rotating threads would destroy the continuity the design exists to
provide, and the ledger would not show why the answers got worse.
