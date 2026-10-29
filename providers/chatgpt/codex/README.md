# Codex transport (`consult.py --transport codex`)

Codex CLI runs ONLY inside the `codex-consult:0.161.0` image under Colima. Never install Codex or
the ChatGPT/Codex desktop app on the host. Default transport since 2026-10-07; Chrome only when asked.

- Build: `colima start --cpu 2 --memory 4` then
  `docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t codex-consult:0.161.0 codex/`
- Credentials: the configured credential home (`CODEX_CONTAINER_HOME`, mode 700), mounted rw at `/codex` only. `config.toml` there is
  overwritten from `codex/config.toml` on every run; `auth.json` is never written by our code.
- Login (user's hands; needs ChatGPT -> Settings -> Security -> device code login enabled):
  `docker run --rm -it --user $(id -u):$(id -g) --read-only --tmpfs /tmp:rw,mode=1777 --cap-drop ALL --security-opt no-new-privileges -v "$CODEX_CONTAINER_HOME":/codex codex-consult:0.161.0 login --device-auth`
- Sandbox decision (measured 2026-10-07): bubblewrap cannot create user namespaces in this
  container, so Codex's `read-only` sandbox fails closed. Shell/exec/view_image tools are disabled
  and attachments are inlined, so the scanned packet is the whole disclosure. code_mode_host is
  off (functions.exec reports "execution host is disabled"); a canary in /codex was unreadable.
  Still exposed and harmless here: wait/sleep, request_user_input, collaboration.* sub-agents.
- Model: always `-m gpt-6.1-sol` (events do not name the model), reasoning effort high.
- Exit codes: 0 completed, 2 refused (nothing sent), 20 auth_required, 21 allowance_exhausted,
  22 transport_error, 23 deadline. No failure falls back to Chrome.
- Tests: `python3 -m unittest discover -s tests` (no Docker, no network).

## Research profile (standing ruling 2026-10-07: "Build it without the network rule")

Research consults (`--kind literature_review` or `--trigger research_needed`) default to
`--transport codex` with profile `research`; review consults keep profile `review`, unchanged.
`--transport chrome` remains available explicitly. The ledger row records `codex_profile`.

| | review (production) | research |
|---|---|---|
| Credentials | the credential home | the research credential home (`CODEX_RESEARCH_HOME`, mode 700, its own login) |
| Config | `codex/config.toml` | `codex/config.research.toml` = review + `web_search = "live"` + `code_mode_host = true` |
| Lock | `<credential home>/.worker.lock` | `<research credential home>/.worker.lock` |
| Flags | `exec ...` | top-level `--search` before `exec` |

Same image, same hardening (read-only rootfs, cap-drop ALL, no-new-privileges, pids/memory limits,
packet-only ro mount, tmpfs /tmp). Each run mounts only its own profile's home; the worker refuses
if the two homes resolve to one directory, and a test asserts neither home appears in the other's run.

- Login: `docker run --rm -it --user $(id -u):$(id -g) --read-only --tmpfs /tmp:rw,mode=1777 --cap-drop ALL --security-opt no-new-privileges -v "$CODEX_RESEARCH_HOME":/codex codex-consult:0.161.0 login --device-auth`
  (no auth.json there -> exit 20 naming this command; never a Chrome fallback).
- **Risk, plainly.** Web search exists only in code mode, and code mode also exposes `functions.exec`,
  `tools.apply_patch` and multi-agent spawn/collaboration, whatever `multi_agent`/`shell_tool` say.
  So the research model can execute code and patch files inside the container, and the container has
  unrestricted egress by the user's choice. Blast radius: the research login (its auth.json is
  readable at /codex) plus whatever the prompt itself contains. Repos and the review login are never
  mounted. Treat a research prompt as published.
- **Hardening follow-up (documented, not built):** an OpenAI-only egress rule for research
  containers (e.g. a dedicated docker network with an allowlisting proxy to the OpenAI/ChatGPT API
  hosts), so code exec cannot reach anywhere else. Web search itself runs server-side, so it should
  survive the rule; measure that when it is built.

### Experiment findings (measured 2026-10-07)

- The code-mode host binary is already in `codex-consult:0.161.0`; no new image needed.
- Web search works with `web_search = "live"` + `[features] code_mode_host = true` + top-level
  `--search` (before `exec`). `-c web_search=...` overrides were ignored; `"enabled"` is an invalid
  value under `--strict-config`. Without code mode, `--search` reports "web search is unavailable".
- Enabling code mode ALSO exposes functions.exec, tools.apply_patch and multi-agent
  spawn/collaboration regardless of `multi_agent = false` / `shell_tool = false`.
- Live smoke (2026-10-07 20:31): "newest Python 3.x on python.org/downloads" -> 4 `web_search`
  events + `open_page`, answer Python 3.14.8 (released 2026-09-30), independently confirmed against
  python.org; production the credential home's `auth.json` hash unchanged across login and run.


> **2026-10-07, standing ruling:** every consult now defaults to the web-enabled research profile — web research is a normal part of a review. `--no-web` selects the locked review profile. Consequence: review packets (attached code) now share a container with code mode and open egress, so a hijacked page could send packet contents somewhere other than OpenAI; the OpenAI-only egress rule is the hardening that closes it.
