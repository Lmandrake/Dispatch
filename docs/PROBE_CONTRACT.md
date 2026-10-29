# The destination probe contract (`dispatch-probe/1`)

`bin/delegate where` used to decide whether ChatGPT, an internal endpoint and Jev were ready by
**copying** each destination's logic into `capability.py`. Each copy drifted: ChatGPT
readiness read *this* repo's enrollment whatever repo the caller was in, and the internal
endpoint's readiness read a key file its own client does not read first (design review
2026-10-20, problem P1). So the router no longer knows how any destination works. Each
destination repo owns one probe command, and the router runs it and reads its JSON.

## What a probe prints

Exactly one JSON object on stdout, nothing else:

```json
{
  "contract": "dispatch-probe/1",
  "destination": "example",
  "ready": true,
  "why": "one plain sentence a person can act on",
  "remedy": null,
  "fixable_by": null,
  "facts": {"key_source": "<key file path>", "http_status": 200},
  "probed_at": "2026-10-21T11:02:03-07:00",
  "elapsed_s": 0.41
}
```

- **`ready` is three-valued.** `true` = this destination can take work now. `false` =
  it cannot, and the probe established why. `null` = the probe could not determine it
  (network not consulted, an unexpected status, a check it was told to skip). Never
  collapse `null` to `false`: refusing work because a check was unreadable is the same
  error as refusing it because a server is down.
- **`remedy`** is what to do when `ready` is not `true`, or `null`. **`fixable_by`** is
  `"agent"`, `"human"` or `null`.
- **`facts`** is a flat object of strings, numbers, booleans or nulls. It must never
  hold a key, token, response body, or an enterprise-internal hostname.

## How a probe behaves

- **Stdlib only, Python 3.9.** It runs under `/usr/bin/python3` with no venv, so
  `from __future__ import annotations` if you annotate, and no 3.10+ syntax.
- **Exit 0 whenever the probe ran**, whatever `ready` is. A non-zero exit means the
  probe itself broke, and the router reads that as `ready: null`.
- **Cheap.** At most one network call, with a timeout of 8 seconds or less; the whole
  probe finishes in under 10. `--offline` makes zero network calls and reports
  `ready: null` when readiness cannot be known without one.
- **Touches nothing.** It never opens Chrome or a DevTools connection (each one costs
  the owner an "Allow remote debugging?" sheet), never starts a daemon (a container runtime, the
  broker, Fetcher), and never writes a file.
- **Pinned by tests in its own repo:** the output parses and has every key above; a
  missing credential gives `ready: false`; an undeterminable state gives `ready: null`;
  and a planted fake key never appears in stdout.

## Which command, per destination

The router's registry, `routing/destinations.json`, is the authority for these. It
also carries each destination's **exposure** (where the material goes), lifted from the
table that used to live only in a private plugin's skill.

| destination | repo | command |
|---|---|---|
| chatgpt | `providers/chatgpt` | `bin/probe.py --json --repo <caller repo root>` |
| (private) | an enterprise plugin repo on `$DISPATCH_PROVIDER_PATHS`, registered by the overlay's `enterprise/overlay.json` (optional) | its own probe |
| jev | `providers/jev` | `bin/probe.py --json` |
| nemotron | `providers/nemotron` (in this repo) | `bin/probe.py --json` |
| fetcher | the Fetcher checkout | `bin/probe.py --json` |

Fetcher is listed by `where` and never ranked: it retrieves the web, it is not a model.
