#!/usr/bin/env python3
"""Run one GPT consult through Codex CLI inside a locked-down Colima container.

Codex is installed ONLY in the `codex-consult:<ver>` image (codex/Dockerfile), never on the host,
and the ChatGPT/Codex desktop app may be disallowed. Agents should call `consult.py --transport codex`,
which adds enrollment, idempotence and the ledger; this module owns the container boundary.

The boundary, and why each piece is there:

* **Immutable packet.** The prompt and the explicitly attached files are COPIED into a fresh dir,
  attachments are INLINED into the prompt, the whole text is secret-scanned, and its sha256 is
  recorded. Only that dir is mounted, read-only. No repo mount: a read-only repo mount does not
  bound disclosure, it only prevents writes (GPT hardening review, 2026-10-07 §5).
* **No filesystem tools.** shell/unified_exec/view_image are disabled in codex/config.toml, so what
  leaves the machine is exactly the scanned prompt. bubblewrap cannot create namespaces in this
  container (measured), so Codex's sandbox stays `read-only` and fails closed rather than being
  swapped for danger-full-access.
* **One serialized worker.** A host flock wraps each COMPLETE `codex exec`, because concurrent jobs on
  one credential copy race the refresh-token rotation. Credentials live only in the credential home
  (mode 700), mounted writable at /codex; this module never writes auth.json.
* **Two profiles, two logins.** `review` (default) is the locked worker above. `research` (user
  ruling 2026-10-07) uses a SEPARATE credential home (`CODEX_RESEARCH_HOME`), codex/config.research.toml
  (web_search live + code_mode_host, which also exposes exec/apply_patch inside the container), its
  own lock, and top-level `--search`. Neither profile's home is ever mounted into the other's run.
  No egress restriction: by user's choice. See codex/README.md "Research profile".
* **Classified outcomes, no fallback.** Any failure is reported as a class with its own exit code.
  Nothing here, or in consult.py, falls back to Chrome.
"""
from __future__ import annotations

import argparse
import dataclasses
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid

CODEX_VERSION = "0.161.0"
IMAGE = f"codex-consult:{CODEX_VERSION}"
REPO = pathlib.Path(__file__).resolve().parent.parent
REPO_CONFIG = REPO / "codex" / "config.toml"
RESEARCH_CONFIG = REPO / "codex" / "config.research.toml"
CODEX_HOME = pathlib.Path(os.environ.get("CODEX_CONTAINER_HOME",
                                         pathlib.Path.home() / ".codex-container"))
RESEARCH_HOME = pathlib.Path(os.environ.get("CODEX_RESEARCH_HOME",
                                            pathlib.Path.home() / ".codex-container-research"))
REVIEW, RESEARCH = "review", "research"
PROFILES = (REVIEW, RESEARCH)
# Under $HOME because Colima only shares $HOME into the VM; $TMPDIR (/var/folders) is invisible.
PACKET_ROOT = pathlib.Path.home() / ".cache" / "codex-consult" / "packets"
DEFAULT_DEADLINE = 900.0
# Always passed with -m so the ledger records the model that was asked for, not "account default".
# Events do not name the model (measured), so this is the record. priority-1 in models_cache 2026-10-07.
DEFAULT_MODEL = "gpt-6.1-sol"
REASONING_EFFORT = "high"           # must match codex/config.toml

COMPLETED = "completed"
AUTH_REQUIRED = "auth_required"
ALLOWANCE_EXHAUSTED = "allowance_exhausted"
TRANSPORT_ERROR = "transport_error"
DEADLINE = "deadline"
REFUSED = "refused"           # secret scan or packet problem: nothing was sent
EXIT_CODES = {COMPLETED: 0, REFUSED: 2, AUTH_REQUIRED: 20, ALLOWANCE_EXHAUSTED: 21,
              TRANSPORT_ERROR: 22, DEADLINE: 23}

AUTH_MARKERS = ("401", "unauthorized", "not logged in", "refresh token", "token expired",
                "please log in", "login again", "re-authenticate", "invalid_grant", "403 forbidden")
ALLOWANCE_MARKERS = ("429", "usage limit", "rate limit", "quota", "limit reached",
                     "too many requests", "usage_limit", "insufficient_quota", "purchase more")


@dataclasses.dataclass
class Result:
    outcome: str
    answer: str = ""
    message: str = ""
    thread_id: str | None = None
    model: str | None = None
    usage: dict | None = None
    packet_sha256: str | None = None
    packet_dir: str | None = None
    events_file: str | None = None
    seconds: float = 0.0

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.outcome]


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  codex: {msg}", file=sys.stderr, flush=True)


def _scan(text: str) -> list[str]:
    # The one scanner, shared with the browser route; imported lazily so consult.py can import us.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from consult import scan_payload
    return scan_payload(text)


# ------------------------------------------------------------------ packet


def build_packet(prompt: str, attachments: list[pathlib.Path], root: pathlib.Path | None = None
                 ) -> tuple[pathlib.Path, str, str]:
    """Copy exactly the prompt + attachments into a new dir. Returns (dir, full_text, sha256).

    Attachments are read ONCE from the copies, so a host file changing after the scan cannot change
    what is sent. A non-UTF-8 attachment is refused rather than mangled.
    """
    root = root or PACKET_ROOT
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    pdir = root / f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    (pdir / "attachments").mkdir(parents=True, mode=0o700)
    parts = [prompt]
    for i, src in enumerate(attachments):
        src = pathlib.Path(src).expanduser().resolve()
        if not src.is_file():
            shutil.rmtree(pdir, ignore_errors=True)
            raise ValueError(f"attachment is not a file: {src}")
        dst = pdir / "attachments" / f"{i:02d}-{src.name}"
        shutil.copyfile(src, dst)
        try:
            body = dst.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.rmtree(pdir, ignore_errors=True)
            raise ValueError(f"attachment is not UTF-8 text, refusing to inline: {src}")
        fence = "````" if "```" in body else "```"
        parts.append(f"\n\n---\n### Attached file {i + 1}: `{src.name}`\n\n{fence}\n{body}\n{fence}\n")
    text = "".join(parts)
    (pdir / "prompt.md").write_text(text, encoding="utf-8")
    for p in [*pdir.rglob("*")]:
        p.chmod(0o500 if p.is_dir() else 0o400)
    pdir.chmod(0o500)
    return pdir, text, hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ profiles


def home_for(profile: str) -> pathlib.Path:
    """The credential home for a profile. Read at call time so tests can patch the module globals.

    Raises if the two homes resolve to the same directory: a research run must never see the
    review login (or vice versa), and a mis-set env var is exactly how that would happen.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown codex profile: {profile!r}")
    if CODEX_HOME.expanduser().resolve() == RESEARCH_HOME.expanduser().resolve():
        raise ValueError(f"review and research codex homes are the same directory: {CODEX_HOME}")
    return RESEARCH_HOME if profile == RESEARCH else CODEX_HOME


def config_for(profile: str) -> pathlib.Path:
    home_for(profile)    # validates the profile name
    return RESEARCH_CONFIG if profile == RESEARCH else REPO_CONFIG


def login_command(profile: str = REVIEW) -> str:
    return (f"docker run --rm -it --user $(id -u):$(id -g) --read-only --tmpfs /tmp:rw,mode=1777 "
            f"--cap-drop ALL --security-opt no-new-privileges -v {home_for(profile)}:/codex "
            f"{IMAGE} login --device-auth")


# ------------------------------------------------------------------ container


# Consults always run in the small `colima` VM, whatever `docker context` is active (another
# context may be a big project VM). CONSULT_DOCKER_CONTEXT overrides; empty means "as active".
DOCKER_CONTEXT = os.environ.get("CONSULT_DOCKER_CONTEXT", "colima")


def docker_cmd() -> list[str]:
    return ["docker", "--context", DOCKER_CONTEXT] if DOCKER_CONTEXT else ["docker"]


def docker_args(packet: pathlib.Path, name: str, model: str | None, profile: str = REVIEW) -> list[str]:
    """The exact `docker run` line. Mounts: the PROFILE'S codex home (rw) and the packet (ro). Nothing else."""
    home = home_for(profile)
    a = [*docker_cmd(), "run", "--rm", "-i", "--name", name,
         "--user", f"{os.getuid()}:{os.getgid()}",
         "--read-only", "--tmpfs", "/tmp:rw,size=256m,mode=1777",
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
         "--pids-limit", "256", "--memory", "2g",
         "-v", f"{home}:/codex",
         "-v", f"{packet}:/packet:ro", "-w", "/packet"]
    ca = os.environ.get("CODEX_CA_CERTIFICATE") or os.environ.get("SSL_CERT_FILE")
    if ca:
        a += ["-v", f"{pathlib.Path(ca).resolve()}:/certs/ca.pem:ro",
              "-e", "CODEX_CA_CERTIFICATE=/certs/ca.pem", "-e", "SSL_CERT_FILE=/certs/ca.pem"]
    # Research profile only: `--search` is a TOP-LEVEL flag (before `exec`) in codex 0.161, and it
    # works only with config web_search="live" + code_mode_host=true (measured 2026-10-07).
    a += [IMAGE] + (["--search"] if profile == RESEARCH else []) + ["exec", "--json", "--ephemeral", "--strict-config", "--skip-git-repo-check",
          "--ignore-rules", "--sandbox", "read-only", "-C", "/packet"]
    a += ["-m", model or DEFAULT_MODEL]
    a.append("-")
    return a


def install_config(profile: str = REVIEW) -> None:
    """Rewrite the profile home's config from its repo copy. Never touches auth.json."""
    home = home_for(profile)
    home.mkdir(mode=0o700, exist_ok=True)
    home.chmod(0o700)
    tmp = home / f".config.toml.{os.getpid()}.{uuid.uuid4().hex[:6]}"
    tmp.write_text(config_for(profile).read_text())
    tmp.replace(home / "config.toml")


def docker_ready() -> str | None:
    """None when the daemon answers; otherwise a reason. Starts Colima once if it is down."""
    def ok() -> bool:
        return subprocess.run([*docker_cmd(), "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, timeout=30).returncode == 0
    try:
        if ok():
            return None
        log("docker is not answering; running `colima start`")
        subprocess.run(["colima", "start"], capture_output=True, timeout=300)
        return None if ok() else "docker daemon unreachable after `colima start`"
    except (OSError, subprocess.SubprocessError) as e:
        return f"docker/colima unavailable: {e}"


def logged_in(profile: str = REVIEW) -> bool:
    return (home_for(profile) / "auth.json").is_file()


class WorkerLock:
    """Host-wide flock around one complete codex run, one lock PER PROFILE (each credential copy
    has its own refresh-token rotation to protect). Waits (queues) up to `wait` seconds."""

    def __init__(self, wait: float, profile: str = REVIEW):
        self.wait, self.fh, self.home = wait, None, home_for(profile)

    def __enter__(self):
        self.home.mkdir(mode=0o700, exist_ok=True)
        self.fh = (self.home / ".worker.lock").open("w")
        until, waited = time.time() + self.wait, False
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.time() >= until:
                    self.fh.close()
                    raise TimeoutError("codex worker lock not acquired before the deadline")
                if not waited:
                    log("another codex consult holds the worker lock; queueing")
                    waited = True
                time.sleep(0.5)

    def __exit__(self, *exc):
        self.fh.close()


# ------------------------------------------------------------------ events


def classify(events: list[dict], returncode: int, stderr: str = "") -> Result:
    answer, thread, model, usage, errors, failed, completed = "", None, None, None, [], False, False
    for e in events:
        t = e.get("type")
        if t == "thread.started":
            thread = e.get("thread_id")
        elif t == "item.completed":
            it = e.get("item") or {}
            if it.get("type") == "agent_message":
                answer = it.get("text") or answer
            elif it.get("type") == "error":
                errors.append(it.get("message", ""))
        elif t == "turn.completed":
            completed, usage = True, e.get("usage")
        elif t == "turn.failed":
            failed = True
            errors.append((e.get("error") or {}).get("message", ""))
        elif t == "error":
            errors.append(e.get("message", ""))
        for k in ("model", "model_slug"):
            if isinstance(e.get(k), str):
                model = e[k]
    if completed and answer.strip() and not failed:
        return Result(COMPLETED, answer=answer, thread_id=thread, model=model, usage=usage)
    # The final error is the verdict; earlier ones may be retried noise (e.g. WebSocket fallback).
    last = (errors[-1] if errors else stderr.strip()[-500:] or f"codex exited {returncode}")
    low = last.lower()
    if any(m in low for m in ALLOWANCE_MARKERS):
        outcome = ALLOWANCE_EXHAUSTED
    elif any(m in low for m in AUTH_MARKERS):
        outcome = AUTH_REQUIRED
    else:
        outcome = TRANSPORT_ERROR
    if completed and not answer.strip() and not failed:
        last = "turn completed with an empty answer"
    return Result(outcome, message=last, thread_id=thread, model=model, usage=usage)


def parse_events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ the run


def run(prompt: str, attachments: list[pathlib.Path] = (), model: str | None = None,
        deadline: float = DEFAULT_DEADLINE, runner=subprocess.run, profile: str = REVIEW) -> Result:
    """One consult. `runner` is injectable so tests never touch Docker or the network."""
    started = time.time()
    try:
        home_for(profile)
        pdir, text, digest = build_packet(prompt, list(attachments))
    except (OSError, ValueError) as e:
        return Result(REFUSED, message=str(e))
    res = _run_packet(pdir, text, digest, model, started + deadline, runner, profile)
    res.packet_sha256, res.packet_dir = digest, str(pdir)
    res.seconds = round(time.time() - started, 1)
    return res


def _run_packet(pdir, text, digest, model, until, runner, profile=REVIEW) -> Result:
    leaks = _scan(text)
    if leaks:
        return Result(REFUSED, message="secret-like content in packet: " + "; ".join(leaks))
    if runner is subprocess.run:
        why = docker_ready()
        if why:
            return Result(TRANSPORT_ERROR, message=why)
    if not logged_in(profile):
        return Result(AUTH_REQUIRED, message=f"no {home_for(profile)}/auth.json ({profile} profile); "
                                             f"log in with: {login_command(profile)}")
    name = f"codex-consult-{uuid.uuid4().hex[:10]}"
    try:
        with WorkerLock(max(0.0, until - time.time()), profile):
            install_config(profile)     # under the lock: no run ever sees a half-replaced config
            remaining = until - time.time()
            if remaining <= 5:
                return Result(DEADLINE, message="deadline spent waiting for the worker lock")
            # Re-verify the packet just before sending: it must be byte-identical to what was scanned.
            if hashlib.sha256((pdir / "prompt.md").read_bytes()).hexdigest() != digest:
                return Result(REFUSED, message="packet changed after it was scanned")
            try:
                proc = runner(docker_args(pdir, name, model, profile), input=text, capture_output=True,
                              text=True, timeout=remaining)
            except subprocess.TimeoutExpired:
                subprocess.run([*docker_cmd(), "kill", name], capture_output=True, timeout=30)
                return Result(DEADLINE, message=f"codex exec exceeded {remaining:.0f}s; container killed")
    except TimeoutError as e:
        return Result(DEADLINE, message=str(e))
    except OSError as e:
        return Result(TRANSPORT_ERROR, message=f"could not run docker: {e}")
    events_file = pdir.parent / f"{pdir.name}.events.jsonl"
    events_file.write_text(proc.stdout or "")
    res = classify(parse_events(proc.stdout or ""), proc.returncode, proc.stderr or "")
    res.model = res.model or model or DEFAULT_MODEL
    res.events_file = str(events_file)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Standalone codex consult (no enrollment or ledger; "
                                             "agents should use consult.py --transport codex).")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--attach", action="append", default=[])
    ap.add_argument("--model", default=None)
    ap.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE)
    ap.add_argument("--profile", choices=PROFILES, default=REVIEW)
    a = ap.parse_args()
    res = run(pathlib.Path(a.prompt_file).read_text(), [pathlib.Path(p) for p in a.attach],
              a.model, a.deadline, profile=a.profile)
    meta = dataclasses.asdict(res)
    meta.pop("answer")
    print(json.dumps(meta), file=sys.stderr)
    if res.outcome == COMPLETED:
        print(res.answer)
    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
