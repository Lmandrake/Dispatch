"""Agentic tool-calling assessment: can a model actually drive a tool loop?

The chat battery (`battery/tasks.yaml`) measures single-turn prose quality. That
says nothing about whether a model can hold a multi-turn tool loop together,
which is what decides its fitness as an agent backend. A model can score 10/10
on prose and still be useless as an agent because it emits malformed function
arguments on turn three.

So this module runs a real agentic task — sweep a documentation corpus for
retired, stale, or completed content — against real tools, and scores three
independent things:

  protocol   Did it emit well-formed tool calls: known name, parseable JSON
             arguments, required fields present, correct types? Malformed calls
             are not free in practice — each one costs a retry turn.
  behavior   Did it read before answering, avoid repeating itself, and terminate
             by calling the report tool rather than exhausting its turn budget?
  task       Precision / recall / F1 of what it reported, against a frozen
             answer key (`battery/agentic/answer_key.yaml`).

Scoring is deterministic — no LLM judge is involved, so the numbers are
comparable across runs and are not subject to the lenient-judge problem noted
in WISDOM.md.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import config
from .client import NemotronClient

AGENTIC_DIR = config.BATTERY_DIR / "agentic"
CORPUS_DIR = AGENTIC_DIR / "corpus"
ANSWER_KEY = AGENTIC_DIR / "answer_key.yaml"

MAX_TURNS = 12
# Plain-chat probes used to tell "no tool support" from "unreachable".
PROBE_ATTEMPTS = 4
MAX_GREP_HITS = 40
MAX_READ_BYTES = 20_000


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List every documentation file in the project, as paths relative to the project root.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full text of one file. Returns the content with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the project root, e.g. 'docs/runbook.md'.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search every documentation file for a case-insensitive regular expression. Returns matching lines as 'path:line: text'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "A regular expression, e.g. 'deprecated|decommission'.",
                    }
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_removable",
            "description": (
                "Submit the final answer and finish the task. Call this exactly once, "
                "after you have finished investigating, with every retired, stale, or "
                "completed item you believe can be removed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Every removable item found.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string", "description": "Path of the file the item is in."},
                                "item": {"type": "string", "description": "What is removable — a section heading, a line, or 'the entire file'."},
                                "reason": {"type": "string", "description": "Why it is safe to remove."},
                            },
                            "required": ["file", "item", "reason"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}
REQUIRED_ARGS = {
    "list_files": [],
    "read_file": ["path"],
    "grep": ["pattern"],
    "report_removable": ["items"],
}

SYSTEM_PROMPT = (
    "You are a documentation maintenance agent. You investigate a project's docs "
    "using the tools provided, then report what can be removed.\n\n"
    "Rules:\n"
    "- Use the tools to look at the real files. Do not guess at file contents.\n"
    "- An item is removable if it is retired, deprecated, decommissioned, "
    "superseded, or describes work that is already completed.\n"
    "- Open work, current architecture, and live procedures must NOT be reported.\n"
    "- Watch for content in one file that another file shows is obsolete.\n"
    "- When your investigation is complete, call report_removable exactly once. "
    "That ends the task."
)


class Corpus:
    """A read-only, path-escape-proof view of a documentation tree."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def files(self) -> list[str]:
        out = [
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and p.suffix.lower() in {".md", ".txt", ".rst"}
        ]
        return out

    def _resolve(self, rel: str) -> Path:
        # Reject absolute paths and anything escaping the corpus root.
        candidate = (self.root / str(rel).lstrip("/\\")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"path outside the project: {rel}")
        return candidate

    def read(self, rel: str) -> str:
        p = self._resolve(rel)
        if not p.is_file():
            avail = ", ".join(self.files())
            raise FileNotFoundError(f"no such file: {rel}. Available files: {avail}")
        lines = p.read_text(encoding="utf-8").splitlines()
        body = "\n".join(f"{i:>4}: {ln}" for i, ln in enumerate(lines, 1))
        return body[:MAX_READ_BYTES]

    def grep(self, pattern: str) -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
        hits: list[str] = []
        for rel in self.files():
            for i, ln in enumerate(self._resolve(rel).read_text(encoding="utf-8").splitlines(), 1):
                if rx.search(ln):
                    hits.append(f"{rel}:{i}: {ln.strip()}")
                    if len(hits) >= MAX_GREP_HITS:
                        return "\n".join(hits) + f"\n... (truncated at {MAX_GREP_HITS} hits)"
        return "\n".join(hits) if hits else "no matches"


# --------------------------------------------------------------------------
# Run record
# --------------------------------------------------------------------------


@dataclass
class AgenticRun:
    model: str
    turns: int = 0
    latency: float = 0.0
    # protocol
    tool_calls_total: int = 0
    unknown_tool: int = 0
    bad_json_args: int = 0
    missing_required_arg: int = 0
    prose_instead_of_call: int = 0   # a turn that produced neither call nor finish
    truncated_turns: int = 0         # hit the token ceiling mid-thought (reasoning models)
    # behavior
    duplicate_calls: int = 0
    files_read: set = field(default_factory=set)
    grep_calls: int = 0
    listed: bool = False
    reported: bool = False
    extra_reports: int = 0
    exhausted: bool = False
    budget_exhausted: bool = False
    # outcome
    reported_items: list = field(default_factory=list)
    transcript: list = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    tools_unsupported: bool = False

    @property
    def malformed(self) -> int:
        return self.unknown_tool + self.bad_json_args + self.missing_required_arg

    @property
    def wellformed_rate(self) -> float:
        denom = self.tool_calls_total + self.prose_instead_of_call
        if not denom:
            return 0.0
        return round((self.tool_calls_total - self.malformed) / denom, 4)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "files_read"}
        d["files_read"] = sorted(self.files_read)
        d["malformed"] = self.malformed
        d["wellformed_rate"] = self.wellformed_rate
        return d


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def _extract_tool_calls(result) -> list[dict]:
    """Normalise tool calls off a ChatResult into plain dicts."""
    out = []
    for tc in getattr(result, "tool_calls", None) or []:
        fn = tc.get("function") or {}
        out.append(
            {
                "id": tc.get("id") or f"call_{len(out)}",
                "name": fn.get("name") or "",
                "arguments": fn.get("arguments"),
            }
        )
    return out


def run_agentic_task(
    client: NemotronClient,
    model: str,
    corpus: Corpus,
    task_prompt: str,
    max_turns: int = MAX_TURNS,
    max_tokens: int = 3000,
    model_budget: float = 420.0,
) -> AgenticRun:
    """Drive one model through the tool loop and record everything it did.

    `model_budget` caps total wall time. Slow decoders are a real agentic
    failure mode — an agent turn that takes six minutes is unusable regardless
    of its answer — so budget exhaustion is recorded as an outcome, not an
    error, and the run is scored on whatever it managed to report.
    """
    run = AgenticRun(model=model)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_prompt},
    ]
    seen_calls: set[tuple[str, str]] = set()
    start = time.monotonic()

    for turn in range(max_turns):
        if time.monotonic() - start > model_budget:
            run.budget_exhausted = True
            break
        run.turns = turn + 1
        r = client.chat(
            model,
            messages,
            max_tokens=max_tokens,
            stream=False,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        if not r.ok:
            # Distinguish "this model cannot do function calling" from "this model
            # is gone" — they look identical from the error string. NIM answers a
            # tools-bearing request to a non-tool model with a bare 404, which
            # reads exactly like a dead endpoint. The only reliable test is
            # differential: ask again without tools. If that succeeds, the model
            # is alive and simply has no tool support.
            #
            # This matters: moonshotai/kimi-k3 (rank 1 on the chat leaderboard)
            # 404s with tools and answers fine without them. Reported as "gone",
            # it would have been wrongly struck off the registry.
            # One probe is not enough: free-tier capacity makes a live model
            # return 429/404 intermittently (kimi-k3 answered 1 call in 12 while
            # nemotron-3-super answered 24/24 in the same loop). A single sample
            # cannot tell "gone" from "busy", so probe until one succeeds.
            probe_ok = False
            for _ in range(PROBE_ATTEMPTS):
                probe = client.chat(model, [{"role": "user", "content": "hi"}],
                                    max_tokens=64, stream=False)
                if probe.ok:
                    probe_ok = True
                    break
            run.tools_unsupported = probe_ok
            run.ok = False
            run.error = (
                f"answers plain chat but rejects tools: {r.error}"
                if probe_ok else
                f"unreachable on {PROBE_ATTEMPTS} plain probes too: {r.error}"
            )
            break

        calls = _extract_tool_calls(r)
        if r.finish_reason == "length":
            run.truncated_turns += 1
        run.transcript.append(
            {"turn": run.turns, "content": (r.text or "")[:800],
             "finish_reason": r.finish_reason,
             "tool_calls": [{"name": c["name"], "arguments": c["arguments"]} for c in calls]}
        )

        if not calls:
            # No tool call. If it already reported, that is a clean finish;
            # otherwise it answered in prose, which is a protocol failure.
            if run.reported:
                break
            if r.finish_reason == "length":
                nudge = (
                    "Your previous turn ran out of tokens before producing anything. "
                    "Stop deliberating and call report_removable now with what you "
                    "already know. Keep each reason to one short sentence."
                )
            else:
                run.prose_instead_of_call += 1
                nudge = (
                    "You must use the provided tools. Investigate with "
                    "list_files / read_file / grep, then call report_removable "
                    "exactly once with your findings."
                )
            messages.append({"role": "assistant", "content": r.text or ""})
            messages.append({"role": "user", "content": nudge})
            continue

        run.tool_calls_total += len(calls)
        messages.append(
            {
                "role": "assistant",
                "content": r.text or "",
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                    for c in calls
                ],
            }
        )

        finished = False
        for c in calls:
            name, raw_args = c["name"], c["arguments"]

            # --- protocol validation -------------------------------------
            if name not in TOOL_NAMES:
                run.unknown_tool += 1
                messages.append(_tool_msg(c, f"error: no such tool {name!r}. "
                                             f"Available: {sorted(TOOL_NAMES)}"))
                continue
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args) if raw_args not in (None, "") else {}
                except (TypeError, json.JSONDecodeError):
                    run.bad_json_args += 1
                    messages.append(_tool_msg(c, "error: arguments were not valid JSON."))
                    continue
            if not isinstance(args, dict):
                run.bad_json_args += 1
                messages.append(_tool_msg(c, "error: arguments must be a JSON object."))
                continue
            missing = [k for k in REQUIRED_ARGS[name] if k not in args]
            if missing:
                run.missing_required_arg += 1
                messages.append(_tool_msg(c, f"error: missing required argument(s): {missing}"))
                continue

            # --- loop detection ------------------------------------------
            sig = (name, json.dumps(args, sort_keys=True)[:400])
            if sig in seen_calls and name != "report_removable":
                run.duplicate_calls += 1
            seen_calls.add(sig)

            # --- dispatch -------------------------------------------------
            try:
                if name == "list_files":
                    run.listed = True
                    out = "\n".join(corpus.files())
                elif name == "read_file":
                    run.files_read.add(str(args["path"]))
                    out = corpus.read(str(args["path"]))
                elif name == "grep":
                    run.grep_calls += 1
                    out = corpus.grep(str(args["pattern"]))
                else:  # report_removable
                    items = _coerce_items(args.get("items"))
                    if run.reported:
                        run.extra_reports += 1
                    else:
                        run.reported = True
                        run.reported_items = items
                    out = f"Recorded {len(items)} item(s). Task complete."
                    finished = True
            except Exception as exc:
                out = f"error: {exc}"
            messages.append(_tool_msg(c, out))

        if finished:
            break
    else:
        run.exhausted = True

    run.latency = round(time.monotonic() - start, 2)
    return run


def _tool_msg(call: dict, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": content}


def _coerce_items(raw: Any) -> list[dict]:
    """Models return `items` as a list, or as a JSON string, or as one object."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [{"file": "", "item": raw, "reason": ""}]
    if isinstance(raw, dict):
        raw = [raw]
    out = []
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, dict):
            out.append({k: str(it.get(k, "")) for k in ("file", "item", "reason")})
        else:
            out.append({"file": "", "item": str(it), "reason": ""})
    return out


# --------------------------------------------------------------------------
# Deterministic scoring against the answer key
# --------------------------------------------------------------------------


def _norm_file(s: str) -> str:
    s = str(s or "").strip().replace("\\", "/").lstrip("./").lower()
    return s.rsplit("/", 1)[-1] if "/" not in s else s


def _file_matches(reported: str, key_file: str) -> bool:
    """Tolerant path comparison: 'docs/runbook.md', 'runbook.md' and
    './docs/runbook.md' all match the key's 'docs/runbook.md'."""
    r, k = _norm_file(reported), str(key_file).strip().lower()
    return r == k or r == k.rsplit("/", 1)[-1] or k.endswith("/" + r)


def load_key(path: Path = ANSWER_KEY) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def score_run(run: AgenticRun, key: dict) -> dict:
    """Compare reported items to the gold key. Purely mechanical."""
    required = key.get("required", [])
    optional = key.get("optional", [])
    keep = key.get("keep", [])

    hit: dict[str, dict] = {}
    false_positives: list[dict] = []
    trap_hits: list[dict] = []
    neutral = 0

    def matches(entry: dict, rep_file: str, text: str) -> bool:
        if not _file_matches(rep_file, entry["file"]):
            return False
        return any(str(kw).lower() in text for kw in entry.get("match_any", []))

    for item in run.reported_items:
        rep_file = item.get("file", "")
        text = f"{item.get('item','')} {item.get('reason','')}".lower()

        got = next((e for e in required if e["id"] not in hit and matches(e, rep_file, text)), None)
        if got:
            hit[got["id"]] = item
            continue
        # Already-credited required item reported twice: neither reward nor punish.
        if any(matches(e, rep_file, text) for e in required):
            continue
        trap = next((e for e in keep if matches(e, rep_file, text)), None)
        if trap:
            trap_hits.append({"reported": item, "why_wrong": trap.get("why", "")})
            false_positives.append(item)
            continue
        if any(matches(e, rep_file, text) for e in optional):
            neutral += 1
            continue
        false_positives.append(item)

    tp, fp = len(hit), len(false_positives)
    fn = len(required) - tp
    precision = round(tp / (tp + fp), 4) if (tp + fp) else 0.0
    recall = round(tp / len(required), 4) if required else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) else 0.0

    terminated = 1.0 if (run.reported and not run.exhausted
                         and not run.budget_exhausted) else 0.0
    protocol = run.wellformed_rate
    # F1 gates the score, protocol scales it. Rationale: an agent that drives a
    # spotless tool loop and finds nothing is useless, so it must not collect
    # half marks for good manners — an earlier additive formula gave a model
    # that reported nothing 5.0/10. Termination needs no term of its own: a run
    # that never calls report_removable has no items, so F1 is already 0.
    # The 0.5 floor keeps a correct answer from being erased by a few retries.
    composite = round(10 * f1 * (0.5 + 0.5 * protocol), 2)

    return {
        "model": run.model,
        "agentic_score": None if run.tools_unsupported else composite,
        "tools_unsupported": run.tools_unsupported,
        "ok": run.ok,
        "error": run.error,
        # protocol
        "wellformed_rate": protocol,
        "tool_calls": run.tool_calls_total,
        "malformed": run.malformed,
        "unknown_tool": run.unknown_tool,
        "bad_json_args": run.bad_json_args,
        "missing_required_arg": run.missing_required_arg,
        "prose_instead_of_call": run.prose_instead_of_call,
        "truncated_turns": run.truncated_turns,
        # behavior
        "turns": run.turns,
        "duplicate_calls": run.duplicate_calls,
        "files_read": len(run.files_read),
        "grep_calls": run.grep_calls,
        "listed_files": run.listed,
        "terminated": bool(terminated),
        "exhausted": run.exhausted,
        "budget_exhausted": run.budget_exhausted,
        "extra_reports": run.extra_reports,
        # task
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "trap_hits": len(trap_hits),
        "neutral_optional": neutral,
        "found_ids": sorted(hit),
        "missed_ids": sorted(e["id"] for e in required if e["id"] not in hit),
        "traps": trap_hits,
        "latency": run.latency,
        "reported_count": len(run.reported_items),
    }


# --------------------------------------------------------------------------
# Suite
# --------------------------------------------------------------------------


def aggregate(rows: list[dict]) -> dict:
    """Collapse N repeats of one model into a single row.

    Termination is non-deterministic in practice — the same model can finish
    cleanly on one run and loop until its turn budget on the next — so a single
    sample cannot support a ranking. `terminated_rate` is the headline
    reliability number: how often it actually delivered an answer at all.
    """
    ok = [r for r in rows if r["ok"] and not r["tools_unsupported"]]
    base = dict(rows[0])
    if not ok:
        base.update({"runs": len(rows), "terminated_rate": 0.0})
        return base

    def col(k):
        return [r[k] for r in ok if r.get(k) is not None]

    scores = col("agentic_score")
    base.update({
        "runs": len(rows),
        "ok_runs": len(ok),
        "agentic_score": round(sum(scores) / len(scores), 2) if scores else None,
        "agentic_min": min(scores) if scores else None,
        "agentic_max": max(scores) if scores else None,
        "terminated_rate": round(sum(1 for r in ok if r["terminated"]) / len(ok), 3),
        "f1": round(sum(col("f1")) / len(col("f1")), 4) if col("f1") else None,
        "precision": round(sum(col("precision")) / len(col("precision")), 4) if col("precision") else None,
        "recall": round(sum(col("recall")) / len(col("recall")), 4) if col("recall") else None,
        "wellformed_rate": round(sum(col("wellformed_rate")) / len(col("wellformed_rate")), 4),
        "turns": round(sum(col("turns")) / len(col("turns")), 1),
        "malformed": sum(col("malformed")),
        "trap_hits": sum(col("trap_hits")),
        "truncated_turns": sum(col("truncated_turns")),
        "latency": round(sum(col("latency")) / len(col("latency")), 2),
        "per_run_scores": scores,
        # A finding is only credited if EVERY successful run found it.
        "missed_ids": sorted(set().union(*[set(r["missed_ids"]) for r in ok])),
        "found_every_run": sorted(set.intersection(*[set(r["found_ids"]) for r in ok])) if ok else [],
    })
    return base


def run_agentic_suite(
    model_ids: list[str],
    corpus_dir: Path | None = None,
    run_dir: Path | None = None,
    max_turns: int = MAX_TURNS,
    timeout: float = 120.0,
    max_tokens: int = 3000,
    model_budget: float = 420.0,
    repeats: int = 1,
) -> Path:
    """Run the doc-sweep task across models, score it, and write results."""
    from datetime import datetime, timezone

    corpus_root = Path(corpus_dir) if corpus_dir else CORPUS_DIR
    scored_against_key = corpus_dir is None
    key = load_key()
    corpus = Corpus(corpus_root)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = run_dir or (config.RESULTS_DIR / f"agentic-{stamp}")
    (run_dir / "runs").mkdir(parents=True, exist_ok=True)

    client = NemotronClient(timeout=timeout)
    files = corpus.files()
    print(f"Corpus: {corpus_root}  ({len(files)} files)")
    if not scored_against_key:
        print("  NOTE: custom corpus — protocol/behavior only, task score not meaningful.")

    rows = []
    for mid in model_ids:
        print(f"\n=== {mid} ===")
        per_run = []
        for rep in range(repeats):
            run = run_agentic_task(client, mid, corpus, key["task"],
                                   max_turns=max_turns, max_tokens=max_tokens,
                                   model_budget=model_budget)
            row = score_run(run, key)
            if not scored_against_key:
                for k in ("agentic_score", "precision", "recall", "f1"):
                    row[k] = None
            per_run.append(row)
            tag = f"  [{rep + 1}/{repeats}]"
            if run.tools_unsupported:
                print(f"{tag} TOOLS UNSUPPORTED — {run.error}")
            elif not run.ok:
                print(f"{tag} FAIL — {run.error}")
            else:
                fin = ("reported" if run.reported else
                       "BUDGET-OUT" if run.budget_exhausted else "NEVER REPORTED")
                msg = (f"{tag} turns={row['turns']} calls={row['tool_calls']} "
                       f"malformed={row['malformed']} {fin}")
                if scored_against_key:
                    msg += (f" P={row['precision']} R={row['recall']} "
                            f"-> {row['agentic_score']}/10")
                print(msg)
            (run_dir / "runs" / f"{mid.replace('/', '__')}.rep{rep + 1}.json").write_text(
                json.dumps({"score": row, "run": run.as_dict()}, indent=2), encoding="utf-8"
            )
            if run.tools_unsupported or (not run.ok and "404" in str(run.error)):
                break  # dead model: no point repeating

        agg = aggregate(per_run)
        rows.append(agg)
        if scored_against_key and agg.get("ok_runs"):
            print(f"  => agentic {agg['agentic_score']}/10 "
                  f"(runs: {agg['per_run_scores']}) "
                  f"terminated {int(agg['terminated_rate'] * 100)}% of runs")

    (run_dir / "scores.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    md = build_agentic_report(rows, run_dir, len(key.get("required", [])), scored_against_key)
    print(f"\nRun complete -> {run_dir}\n{md}")
    return run_dir


def build_agentic_report(rows: list[dict], run_dir: Path, n_required: int,
                         scored: bool = True) -> Path:
    """Write the agentic leaderboard markdown."""
    live = [r for r in rows if r["ok"] and not r["tools_unsupported"]]
    live.sort(key=lambda r: (r.get("agentic_score") or 0, r.get("f1") or 0), reverse=True)

    L = [
        "# Agentic Tool-Calling Leaderboard",
        "",
        "Measures what the chat battery cannot: whether a model can hold a multi-turn",
        "tool loop together. Task — sweep a frozen documentation corpus for retired,",
        "stale, or completed content, using `list_files` / `read_file` / `grep`, then",
        "submit findings via a `report_removable` function call.",
        "",
        f"Scored deterministically against `battery/agentic/answer_key.yaml` "
        f"({n_required} required findings, one needing cross-file inference). No LLM judge.",
        "",
        "**Agentic** is the mean over repeats; **Spread** is min-max across them and",
        "**Terminated** is how often the model actually called `report_removable`",
        "instead of investigating until its turn budget ran out. Termination is the",
        "least reliable behaviour measured here — read Spread before trusting a rank.",
        "",
        "`agentic = 10 x F1 x (0.5 + 0.5 x protocol)` — F1 gates the score, protocol",
        "scales it. A clean tool loop that finds nothing scores 0, not half marks.",
        "",
        "| Rank | Model | Agentic | Spread | Terminated | Protocol | Turns | P | R | F1 | Traps | Latency |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(live, 1):
        spread = (f"{r.get('agentic_min')}–{r.get('agentic_max')}"
                  if r.get("runs", 1) > 1 and r.get("agentic_min") is not None else "—")
        term = (f"{int(r['terminated_rate'] * 100)}%" if "terminated_rate" in r
                else ("yes" if r.get("terminated") else "no"))
        L.append(
            f"| {i} | `{r['model']}` | **{r['agentic_score']}** | {spread} | {term} | "
            f"{r['wellformed_rate']} | {r['turns']} | "
            f"{r['precision']} | {r['recall']} | "
            f"{r['f1']} | {r['trap_hits']} | {r['latency']}s |"
        )

    unsup = [r for r in rows if r["tools_unsupported"]]
    failed = [r for r in rows if not r["ok"] and not r["tools_unsupported"]]
    if unsup:
        L += ["", "## No tool-calling support", "",
              "These answer plain chat but reject a request carrying `tools=`. They are",
              "unusable as an agent backend regardless of chat quality — and still",
              "perfectly good for delegation via `nemo call`. Confirmed by a differential",
              "probe (same model, same moment, no tools), not inferred from the error.", ""]
        L += [f"- `{r['model']}` — {(r['error'] or '')[:160]}" for r in unsup]
    if failed:
        L += ["", "## Errored", ""]
        L += [f"- `{r['model']}` — {(r['error'] or '')[:160]}" for r in failed]

    if live:
        L += ["", "## What each model missed", ""]
        for r in live:
            missed = ", ".join(r["missed_ids"]) or "nothing"
            L.append(f"- `{r['model']}` — missed: {missed}"
                     + (f" · fell for {r['trap_hits']} trap(s)" if r["trap_hits"] else ""))

    out = run_dir / "agentic.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out
