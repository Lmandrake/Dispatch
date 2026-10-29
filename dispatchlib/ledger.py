"""The empirical layer: what we decided, what was attempted, and what the caller did.

🔴 WHY THIS EXISTS AND WHY IT HAS NO GRADER.

A previous attempt to answer "which model can this work be handed to" built its own
benchmark suite and it had little resolution: most fixtures were passed at 1.00 by
anything competent. Worse, the GRADERS were repeatedly the defect: a keyword-recall
grader scored a verbatim copy of the input as passing, and a scope bug in a trap check
made a universal 0.00 that was really the instrument.

So the owner's ruling, 2026-10-01: **the outcome signal is what the caller DID with the
output** -- used as-is, edited, rewrote, discarded, escalated -- and there is no
automatic quality score anywhere in this module. A disposition is an observation about
behaviour, not a judgement this code computes. An instrument that cannot grade cannot
mis-grade.

🔴 THREE ROW TYPES, NEVER COLLAPSED.

  * `DECISION`    -- what the router chose, what it rejected and why, and what the
    prior PREDICTED. Written at route time, before any outcome exists.
  * `ATTEMPT`     -- what was actually tried and what happened operationally: the
    destination really used, how long it took, whether it errored and in which class.
  * `DISPOSITION` -- what the consumer did with the returned result.

The plan had only two. The third came out of the cold design review (see
`docs/ROUTER_CONSULT.md`, finding L3): **launched is not completed**, and that is the
exact failure already measured in this repo -- a subagent spawned with `model: fable`
returns a successful launch and then dies on HTTP 400 from the gateway. With two row
types the launch IS the record, so the dispatch reads as successful forever.

The same review corrected the claim that two row types make "the prior was wrong"
distinguishable from "the box was busy" (L1). They do not: both worlds produce
`predicted 4s / measured 40s`. The split buys chronology and attribution, not
diagnosis, and `bin/delegate ledger` says "cause unresolved" rather than guessing.

🔴 A SELF-REPORT IS NOT AN OBSERVED ACTION, and that distinction is load-bearing.

An agent that calls `record --disposition used-as-is` and then writes something
substantially different has reproduced the grader failure under a new field name
(review finding D3). So `disposition_source` is required and three-valued, and only
`observed_operation` is ever counted as observed use.

Separately (D1): **"no edits" and "no review needed" are different properties.** Twenty
outputs forwarded unread and twenty outputs forwarded after thirty minutes of review
each produce twenty `used-as-is` rows. Since DELEGATE means "you need not read it",
only `review_status` can bear on a hand-off claim -- never the disposition alone.

🔴 THE ACTUATION THRESHOLD IS PRECOMMITTED. THE OVERRIDE IS NOT BUILT.

`ACTUATION` is written here, before the first row existed, so it cannot be chosen later
to fit the data -- a failure this repo has paid for three times in another form (a
delegability cliff written and reverted thrice, each time after seeing what it refused).

What is deliberately ABSENT is any code that replaces a prior with an empirical rate.
Review finding T3: the prior holds benchmark percentiles, throughput and cost; a
used-as-is fraction is none of those, and nothing defines how 90% acceptance compares
to an intelligence index of 70. Until that mapping exists, "empirical overrides prior"
is not an executable rule, so `cells()` computes rates and LABELS the cell, and
`bin/delegate` prints prior and observed side by side.

🔴 NO PROMPT TEXT AND NO OUTPUT TEXT, EVER -- INCLUDING ON THE ERROR PATH.

Standing rule for this repo: result files are committed and the original corpus was
private material naming individuals. A row carries identifiers, enums,
counts and timings. `check_row` enforces it by ALLOWLIST, because the dangerous
direction is a new field quietly carrying text. Review finding A6 is why the error path
matters as much as the happy one: an exception handler that serialises a hook payload
leaks the input while every normal row stays clean. There is exactly one free-text
field, `note`, capped and single-line.

Pure stdlib. Append-only JSONL, one row per line, newest last.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import re

DEFAULT_LEDGER_PATH = (pathlib.Path(__file__).resolve().parents[1]
                       / "routing" / "dispositions.jsonl")

DECISION = "DECISION"
ATTEMPT = "ATTEMPT"
DISPOSITION = "DISPOSITION"
ROW_TYPES = (DECISION, ATTEMPT, DISPOSITION)

# --------------------------------------------------------------- the dispositions --
#: What the consumer did with the output. Ordered best-to-worst, which is the only
#: ordering this module asserts -- it is not a score and nothing multiplies it.
#:
#: `escalated` is deliberately NOT the worst. Escalating is the system working: the
#: consumer recognised the destination was wrong and moved the work. Discarding is
#: worse because the work was simply lost. Collapsing the two would make a correct
#: escalation read as a failure and bias the router against destinations whose
#: weaknesses are VISIBLE -- which are the safe ones.
#:
#: `unknown` is a first-class member, not a gap. Review finding D6: if 20 of 100
#: outputs get recorded and the other 80 do not, the true used-as-is fraction is
#: anywhere from 20% to 100%, and presenting the 20 as "100% success" is the
#: denominator failure this whole repo exists to avoid.
DISPOSITIONS = ("used-as-is", "edited", "rewrote", "discarded", "escalated", "unknown")

#: Where the disposition came from. REQUIRED. See the D3 note in the module docstring:
#: an agent pronouncing its own success is the grader returning by another name.
#:
#:   observed_operation -- code recorded an action that demonstrably occurred (a
#:                         publish of unchanged text, a selection among results, a
#:                         retry request).
#:   actor_report       -- an agent or a tool said so. Countable, never "observed".
#:   human_report       -- the owner said so.
DISPOSITION_SOURCES = ("observed_operation", "actor_report", "human_report")

#: Whether anyone read the output before using it. Separate from the disposition
#: because `used-as-is` conflates "nobody looked" with "looked hard and changed
#: nothing", and only the first can ever support a hand-off claim.
REVIEW_STATUS = ("none", "performed", "unknown")

#: Who consumed the output. A disposition from an automated pipeline and one from a
#: human are different observations about different workflows.
CONSUMER_TYPES = ("agent", "human", "automated_pipeline")

#: Dispositions that mean the hand-off paid for itself without a rewrite. `edited`
#: counts: a tweak is cheaper than doing the work. `rewrote` does not.
USABLE = frozenset({"used-as-is", "edited"})
#: The loose "no edits" set. NOT sufficient for a hand-off claim on its own -- see
#: `handoff_rate` in `cells`, which additionally requires an unreviewed, observed use.
CLEAN = frozenset({"used-as-is"})

#: Why a destination was chosen. An enum so the ledger stays countable; the prose a
#: human reads is produced at print time and is NOT stored.
REASONS = ("prior-ranked", "owner-specified", "forced", "only-candidate",
           "empirical-override", "no-candidate", "exploration", "tier-rule")

#: Why a destination was rejected. `unreachable` and `unknown` are separate on
#: purpose: the roster-loss defect in this repo was an unreachable endpoint reading
#: as an empty one.
REJECTIONS = ("unreachable", "unknown", "tier-too-low", "not-served",
              "wrong-machine", "no-published-figure", "lower-ranked",
              "over-time-budget", "no-task-interface", "no-check",
              "never-cheap-tier")

#: What happened to an attempt, operationally. `launched` is NOT terminal and is the
#: whole reason this row type exists: a launch that later 400s must not be stored as
#: a completion.
ATTEMPT_STATUS = ("launched", "completed", "errored", "timed-out", "refused",
                  "abandoned")

#: Error classes, not error text. Coarse on purpose: a class is countable and cannot
#: carry a payload.
ERROR_CLASSES = ("invalid-model", "auth", "unreachable", "rate-limited",
                 "truncated", "timeout", "server-error", "other")

# ------------------------------------------------------------- the actuation rule --
#: 🔴 PRECOMMITTED 2026-10-01, BEFORE THE FIRST ROW WAS WRITTEN.
#:
#: `min_dispositions` is a JUDGEMENT and is marked as one, in the same spirit as
#: `refer.DELEGATE_FLOOR`. It is not derived from a variance estimate, because there
#: is no disposition data from which to estimate one -- stating that plainly is the
#: point. It matches the archived sweeps' cell size so the two bodies of evidence are
#: at least commensurable.
#:
#: WHAT IT DOES: below the threshold a cell is labelled `provisional`, above it
#: `empirical`. WHAT IT DOES NOT DO: replace a prior. See the T3 note in the module
#: docstring -- the review established that comparison is undefined, so the label is
#: displayed next to the prior and nothing is overridden. `overrides_prior` is False
#: here and `test_ledger` pins that nothing in this repo reads it as True.
#:
#: The reviewer's own bound on what any threshold can mean, under conditions that do
#: NOT hold here (complete recording, independent jobs): zero adverse dispositions in
#: 20 gives a one-sided 95% upper bound of 1 - 0.05**(1/20) ~= 13.9% on the adverse
#: rate; reaching 5% needs 59. Recorded to bound the claim, not to argue for 59.
#:
#: Change any value and you MUST bump `version`; rows from two versions are never
#: pooled, and `test_ledger` pins that.
ACTUATION = {
    "version": 1,
    "min_dispositions": 20,
    "overrides_prior": False,
    "rationale": "A (destination, task-kind) cell with fewer than 20 dispositions "
                 "cannot distinguish a bad destination from an unlucky week, so the "
                 "cell is labelled provisional. 20 is a judgement, not a "
                 "measurement: there is no disposition variance to estimate from "
                 "yet. Even above the threshold the empirical rate does NOT override "
                 "the prior -- a used-as-is fraction and a benchmark percentile are "
                 "unlike quantities and no mapping between them has been defined.",
}

#: Maximum length of the one free-text field.
NOTE_MAX = 200

#: A value that looks like prose rather than an identifier has no business in a row.
_IDENT_MAX = 120

#: Every key a row may carry, by row type. An ALLOWLIST: the dangerous direction is a
#: new field quietly carrying model output into a committed file. `check_row` refuses
#: an unknown key, and because an allowlist is a claim, `test_ledger` checks it
#: against every row this repo has actually written.
_COMMON = {"row", "event_id", "ts", "rule_version", "note"}
ALLOWED_KEYS = {
    DECISION: _COMMON | {
        "decision_id", "machine", "network", "task_kind", "size_input_tokens",
        "destination", "want", "time_budget_secs", "reason", "rejected",
        "predicted_usd", "predicted_secs", "predicted_tier", "basis",
        "n_dispositions", "batch_id", "config_fingerprint", "eligible",
        "selection_p",
    },
    ATTEMPT: _COMMON | {
        "decision_id", "destination", "status", "latency_secs", "error_class",
        "attempt_n", "tokens_in", "tokens_out", "config_fingerprint",
        "check_passed",
    },
    DISPOSITION: _COMMON | {
        "decision_id", "disposition", "disposition_source", "review_status",
        "consumer_type", "supersedes",
    },
}


class LedgerRefused(Exception):
    """A row was refused rather than written. Never caught internally: a refused row
    is a bug in the caller, and silently dropping it would lose the very decision the
    ledger exists to record."""


def actuation_note() -> str:
    """The actuation rule in one paragraph, for a CLI to print.

    This accessor exists so that no caller has to read `ACTUATION['overrides_prior']`
    itself. The distinction matters: printing the flag is transparency, BRANCHING on
    it would be wiring the override, and a grep cannot tell those apart. So the raw
    key stays inside this module and `test_ledger` forbids it everywhere else --
    which is only enforceable if there is a sanctioned way to display it.
    """
    a = ACTUATION
    return (f"Actuation rule v{a['version']}: a (destination, task-kind) cell is "
            f"labelled 'empirical' at {a['min_dispositions']} dispositions and "
            f"'provisional' below. The label does NOT override the prior: a "
            f"used-as-is fraction and a benchmark percentile are unlike quantities "
            f"and no mapping between them has been defined.")


def now_iso() -> str:
    """Local time with a UTC offset. Not UTC: every other dated artifact in this repo
    and in the handoffs is local, and a mixed-timezone ledger cannot be read against
    them."""
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _stamp(ts: str) -> str:
    """`2026-10-01T18:52:07-0700` -> `20261001T185207`.

    Slice to 19 chars FIRST, then strip separators. The first version tried to drop
    the timezone with `.split("+")[0].split("-0")[0]`, which silently truncated every
    id to `202610`: a negative offset has no `+`, and `-0` matches inside the DATE at
    `-01`. It produced a plausible-looking id, so nothing caught it until a real
    decision was written and read back. A date format is a parser; test it on a real
    value, not on the shape you had in mind.
    """
    return re.sub(r"[^0-9T]", "", ts[:19])


def decision_id(task_kind: str, destination: str | None, ts: str | None = None) -> str:
    """A short, sortable, collision-resistant id a human can read back.

    Shape `<YYYYMMDDTHHMMSS>-<task_kind>-<6 hex>`. The hex covers the full tuple
    including seconds, so two decisions in the same second for the same cell still
    differ -- which a timestamp alone would not guarantee.
    """
    ts = ts or now_iso()
    h = hashlib.sha256(f"{ts}|{task_kind}|{destination}".encode()).hexdigest()[:6]
    return f"{_stamp(ts)}-{task_kind}-{h}"


def event_id(row: dict) -> str:
    """A stable id for one row, so duplicate delivery is detectable.

    Derived from the row's own content rather than a counter: two processes appending
    concurrently cannot coordinate a counter, but they will produce the same hash for
    the same event. `append` dedupes on it.
    """
    body = json.dumps({k: v for k, v in row.items() if k != "event_id"},
                      sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


# ----------------------------------------------------------------- validation --

def check_row(row: dict) -> None:
    """Refuse anything that is not a countable, text-free record.

    Raises `LedgerRefused` naming the offending key. Deliberately strict in the
    direction that protects the committed file: an unknown key is refused even when
    harmless, because the rule has to be mechanical to be worth anything.
    """
    rt = row.get("row")
    if rt not in ROW_TYPES:
        raise LedgerRefused(f"row type must be one of {ROW_TYPES}, got {rt!r}")
    extra = sorted(set(row) - ALLOWED_KEYS[rt])
    if extra:
        raise LedgerRefused(
            f"{rt} row carries key(s) not on the allowlist: {extra}. A new field is "
            f"how prompt or output text reaches a committed file; add it to "
            f"ALLOWED_KEYS deliberately, with a test, or put it in `note`.")
    if row.get("rule_version") != ACTUATION["version"]:
        raise LedgerRefused(
            f"rule_version must be {ACTUATION['version']} (ACTUATION['version']); "
            f"got {row.get('rule_version')!r}. Rows from two rule versions are never "
            f"pooled, so the stamp is not optional.")

    note = row.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise LedgerRefused("note must be a string or absent")
        if len(note) > NOTE_MAX:
            raise LedgerRefused(
                f"note is {len(note)} chars, over the {NOTE_MAX} cap. The cap is what "
                f"stops an output being pasted into the one free-text field.")
        if "\n" in note:
            raise LedgerRefused("note must be a single line; a multi-line note is how "
                                "a transcript gets in")

    for key, val in row.items():
        if key == "note":
            continue
        for s in _strings_in(val):
            if len(s) > _IDENT_MAX:
                raise LedgerRefused(
                    f"{key} contains a {len(s)}-char string; identifiers are capped "
                    f"at {_IDENT_MAX}. This is not a text field.")

    {DECISION: _check_decision, ATTEMPT: _check_attempt,
     DISPOSITION: _check_disposition}[rt](row)


def _strings_in(val):
    if isinstance(val, str):
        yield val
    elif isinstance(val, dict):
        for k, v in val.items():
            yield k
            yield from _strings_in(v)
    elif isinstance(val, (list, tuple)):
        for v in val:
            yield from _strings_in(v)


def _check_decision(row: dict) -> None:
    if not row.get("decision_id"):
        raise LedgerRefused("a DECISION needs a decision_id; the other rows key on it")
    if not row.get("task_kind"):
        raise LedgerRefused("a DECISION needs a task_kind")
    reason = row.get("reason")
    if reason not in REASONS:
        raise LedgerRefused(f"reason must be one of {REASONS}, got {reason!r}")
    if row.get("destination") is None and reason != "no-candidate":
        raise LedgerRefused(
            "a DECISION with no destination must say reason='no-candidate'; any other "
            "reason claims a choice was made")
    for rej in row.get("rejected") or []:
        if not isinstance(rej, dict) or set(rej) != {"destination", "why"}:
            raise LedgerRefused("each rejected entry is {'destination': str, 'why': str}")
        if rej["why"] not in REJECTIONS:
            raise LedgerRefused(
                f"rejection reason must be one of {REJECTIONS}, got {rej['why']!r}")
    # `0` must mean a measured zero. A prediction we do not have is None.
    for key in ("predicted_usd", "predicted_secs", "time_budget_secs"):
        v = row.get(key)
        if v is not None and not isinstance(v, (int, float)):
            raise LedgerRefused(f"{key} must be a number or None (None = unknown; "
                                f"0 would claim a measured zero)")
    n = row.get("size_input_tokens")
    if n is not None and (not isinstance(n, int) or n < 0):
        raise LedgerRefused(
            "size_input_tokens must be a non-negative int or None. It is INPUT "
            "tokens specifically -- expected output, document count and total "
            "context are different quantities and were conflated in the design")


def _check_attempt(row: dict) -> None:
    if not row.get("decision_id"):
        raise LedgerRefused("an ATTEMPT is unattributable without its decision_id")
    st = row.get("status")
    if st not in ATTEMPT_STATUS:
        raise LedgerRefused(f"status must be one of {ATTEMPT_STATUS}, got {st!r}")
    if st == "errored" and row.get("error_class") not in ERROR_CLASSES:
        raise LedgerRefused(
            f"an errored ATTEMPT must carry an error_class from {ERROR_CLASSES}; a "
            f"bare error tells a later reader nothing countable")
    if row.get("error_class") is not None and row["error_class"] not in ERROR_CLASSES:
        raise LedgerRefused(f"error_class must be one of {ERROR_CLASSES}")
    lat = row.get("latency_secs")
    if lat is not None and (not isinstance(lat, (int, float)) or lat < 0):
        raise LedgerRefused("latency_secs must be a non-negative number or None")
    cp = row.get("check_passed")
    if cp is not None and not isinstance(cp, bool):
        raise LedgerRefused("check_passed is True, False or None (None = no check ran, "
                            "which is not the same as a pass)")


def _check_disposition(row: dict) -> None:
    if not row.get("decision_id"):
        raise LedgerRefused("a DISPOSITION is meaningless without its decision_id")
    d = row.get("disposition")
    if d not in DISPOSITIONS:
        raise LedgerRefused(f"disposition must be one of {DISPOSITIONS}, got {d!r}")
    src = row.get("disposition_source")
    if src not in DISPOSITION_SOURCES:
        raise LedgerRefused(
            f"disposition_source is REQUIRED and must be one of "
            f"{DISPOSITION_SOURCES}, got {src!r}. An agent pronouncing its own "
            f"success is the grader failure returning under a new field name, and "
            f"the only defence is recording which kind of claim this is.")
    rv = row.get("review_status")
    if rv is not None and rv not in REVIEW_STATUS:
        raise LedgerRefused(f"review_status must be one of {REVIEW_STATUS} or None")
    ct = row.get("consumer_type")
    if ct is not None and ct not in CONSUMER_TYPES:
        raise LedgerRefused(f"consumer_type must be one of {CONSUMER_TYPES} or None")


# ------------------------------------------------------------------- read / write --

def append(row: dict, path: pathlib.Path | str = DEFAULT_LEDGER_PATH) -> dict:
    """Validate, stamp and append one row. Returns the row as written.

    `ts`, `rule_version` and `event_id` are filled in when absent, so a caller cannot
    forget the stamp -- but a WRONG `rule_version` is still refused, because silently
    correcting one would defeat the version check.

    Idempotent on `event_id`: appending the same event twice is a no-op. Duplicate
    delivery is a real failure mode of any append-only log, and a duplicated
    disposition would inflate a cell's sample size.
    """
    row = dict(row)
    row.setdefault("ts", now_iso())
    row.setdefault("rule_version", ACTUATION["version"])
    row["event_id"] = row.get("event_id") or event_id(row)
    check_row(row)
    p = pathlib.Path(path)
    if p.exists() and any(r.get("event_id") == row["event_id"] for r in read(p)):
        return row
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read(path: pathlib.Path | str = DEFAULT_LEDGER_PATH) -> list[dict]:
    """Every row, in file order. A missing file is an empty ledger -- a real state
    (nothing routed yet), and the only absence this module treats as data.

    A malformed line RAISES, including a truncated final line. A ledger that silently
    skipped unparseable lines would under-count exactly the rows most likely to
    matter: a crash mid-write happens during the incidents.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return []
    rows = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise LedgerRefused(f"{p}:{i} is not valid JSON ({e}); refusing to read a "
                                f"partial ledger") from None
    return rows


def record_decision(*, task_kind: str, destination: str | None, machine: str,
                    reason: str, network: dict | None = None,
                    size_input_tokens: int | None = None, want: str | None = None,
                    time_budget_secs: float | None = None,
                    rejected: list[dict] | None = None,
                    predicted_usd: float | None = None,
                    predicted_secs: float | None = None,
                    predicted_tier: str | None = None,
                    basis: str | None = None, n_dispositions: int | None = None,
                    batch_id: str | None = None,
                    config_fingerprint: str | None = None,
                    eligible: list[str] | None = None,
                    selection_p: float | None = None, note: str | None = None,
                    path: pathlib.Path | str = DEFAULT_LEDGER_PATH) -> str:
    """Write a DECISION and return its id, which the other two row types key on.

    `batch_id` groups siblings from one fan-out. Review finding T2: twenty
    near-identical jobs from one fan-out are not twenty independent experiences, and
    without this field row count silently becomes evidence breadth.

    `config_fingerprint` pins what the evidence is ABOUT (finding A2): swap a 4-bit
    build in under the same served name and a favourable cell would keep applying to
    a different artifact.
    """
    ts = now_iso()
    did = decision_id(task_kind, destination, ts)
    row = {"row": DECISION, "ts": ts, "decision_id": did, "machine": machine,
           "task_kind": task_kind, "destination": destination, "reason": reason,
           "network": network, "size_input_tokens": size_input_tokens, "want": want,
           "time_budget_secs": time_budget_secs, "rejected": rejected or [],
           "predicted_usd": predicted_usd, "predicted_secs": predicted_secs,
           "predicted_tier": predicted_tier, "basis": basis,
           "n_dispositions": n_dispositions, "batch_id": batch_id,
           "config_fingerprint": config_fingerprint, "eligible": eligible,
           "selection_p": selection_p}
    if note is not None:
        row["note"] = note
    append(row, path)
    return did


def record_attempt(decision_id_: str, status: str, *, destination: str | None = None,
                   latency_secs: float | None = None, error_class: str | None = None,
                   attempt_n: int | None = None, tokens_in: int | None = None,
                   tokens_out: int | None = None,
                   config_fingerprint: str | None = None, note: str | None = None,
                   check_passed: bool | None = None,
                   path: pathlib.Path | str = DEFAULT_LEDGER_PATH) -> dict:
    """Write an ATTEMPT: what was tried, and what happened operationally.

    🔴 `status='launched'` IS NOT A COMPLETION, and that is the whole point of this
    row type. The measured case: a subagent spawn returns a successful launch and
    then dies on `400 Invalid model name` from the gateway. A design with only
    DECISION and DISPOSITION records the launch as the outcome and the dispatch reads
    as successful forever.

    Refuses an unknown `decision_id` for the same reason `record_disposition` does.
    """
    _require_decision(decision_id_, path)
    row = {"row": ATTEMPT, "decision_id": decision_id_, "status": status,
           "destination": destination, "latency_secs": latency_secs,
           "error_class": error_class, "attempt_n": attempt_n,
           "tokens_in": tokens_in, "tokens_out": tokens_out,
           "config_fingerprint": config_fingerprint, "check_passed": check_passed}
    if note is not None:
        row["note"] = note
    return append(row, path)


def record_disposition(decision_id_: str, disposition: str, *,
                       source: str = "actor_report",
                       review_status: str | None = None,
                       consumer_type: str | None = None,
                       supersedes: str | None = None, note: str | None = None,
                       path: pathlib.Path | str = DEFAULT_LEDGER_PATH) -> dict:
    """Write a DISPOSITION against an existing decision.

    `source` defaults to `actor_report` -- the WEAKEST of the three -- on purpose. A
    caller that has genuinely observed an operation can say so; a caller that has not
    thought about it gets the label that does not claim observation. Defaulting the
    other way would let every self-report count as observed use, which is the D3
    failure.

    `supersedes` carries the event_id of a disposition this one corrects. Review
    finding D5: ten outputs re-marked `discarded` are ten observations with revised
    labels, not twenty -- `cells` counts only the latest per decision, and the
    history stays readable.
    """
    _require_decision(decision_id_, path)
    row = {"row": DISPOSITION, "decision_id": decision_id_,
           "disposition": disposition, "disposition_source": source,
           "review_status": review_status, "consumer_type": consumer_type,
           "supersedes": supersedes}
    if note is not None:
        row["note"] = note
    return append(row, path)


def _require_decision(did: str, path) -> None:
    known = {r.get("decision_id") for r in read(path) if r.get("row") == DECISION}
    if did not in known:
        raise LedgerRefused(
            f"no DECISION with id {did!r} in {path}; a row that names no decision "
            f"cannot update a cell, so it is refused rather than stored unattributed")


# ------------------------------------------------------------------------- cells --

def cells(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Roll the ledger up per (destination, task_kind).

    Only rows at the CURRENT `rule_version` count: pooling two versions is what the
    stamp exists to prevent, and a silent pool is indistinguishable from a larger
    sample.

    🔴 EVERY RATE COMES WITH ITS COVERAGE, AND WITH BOUNDS.

    `n_unknown` is the number of decisions with a destination that have no
    disposition at all. Review finding D6: 20 recorded out of 100 permits a true
    used-as-is fraction anywhere from 20% to 100%, so each rate also carries
    `*_lo`/`*_hi` -- the fraction if every unrecorded case were adverse, and if every
    one were favourable. Those are the only honest summary of a partially-recorded
    cell, and the gap between them is the measure of how little the cell says.

    Three rates, deliberately not one:

      * `usable_rate`  -- used-as-is or edited. "Cheaper than doing it myself."
      * `clean_rate`   -- used-as-is. "No edits were made."
      * `handoff_rate` -- used-as-is AND nobody reviewed it AND the use was an
        OBSERVED operation. The only rate that could ever bear on a DELEGATE tier,
        because DELEGATE means "you need not read it" and the other two cannot tell
        an unread forward from a thirty-minute review that changed nothing (D1).

    `n_batches` is beside `n_dispositions` so twenty fan-out siblings cannot be read
    as twenty independent situations (T2).
    """
    ver = ACTUATION["version"]
    decisions = {r["decision_id"]: r for r in rows
                 if r.get("row") == DECISION and r.get("rule_version") == ver
                 and r.get("destination")}
    # Latest disposition per decision wins; a correction replaces, never adds (D5).
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("row") != DISPOSITION or r.get("rule_version") != ver:
            continue
        if r.get("decision_id") in decisions:
            latest[r["decision_id"]] = r

    out: dict[tuple[str, str], dict] = {}

    def _cell(key):
        return out.setdefault(key, {
            "destination": key[0], "task_kind": key[1], "n_decisions": 0,
            "n_dispositions": 0, "counts": {d: 0 for d in DISPOSITIONS},
            "sources": {s: 0 for s in DISPOSITION_SOURCES},
            "n_attempts": 0, "n_errored": 0,
            "errors": {}, "_batches": set(), "_latencies": [],
            "n_launched_never_completed": 0,
        })

    for d in decisions.values():
        c = _cell((d["destination"], d["task_kind"]))
        c["n_decisions"] += 1
        if d.get("batch_id"):
            c["_batches"].add(d["batch_id"])

    # Attempts: operational truth, and the launched-but-never-completed count, which
    # is the one number that would have caught the fable spawn.
    per_decision_status: dict[str, set] = {}
    for r in rows:
        if r.get("row") != ATTEMPT or r.get("rule_version") != ver:
            continue
        dec = decisions.get(r.get("decision_id"))
        if dec is None:
            continue
        c = _cell((dec["destination"], dec["task_kind"]))
        c["n_attempts"] += 1
        per_decision_status.setdefault(r["decision_id"], set()).add(r["status"])
        if r["status"] == "errored":
            c["n_errored"] += 1
            k = r.get("error_class") or "other"
            c["errors"][k] = c["errors"].get(k, 0) + 1
        if isinstance(r.get("latency_secs"), (int, float)):
            c["_latencies"].append(r["latency_secs"])

    for did, statuses in per_decision_status.items():
        if "launched" in statuses and not (statuses & {"completed", "errored",
                                                       "timed-out", "refused",
                                                       "abandoned"}):
            dec = decisions[did]
            _cell((dec["destination"], dec["task_kind"]))["n_launched_never_completed"] += 1

    for did, r in latest.items():
        dec = decisions[did]
        c = _cell((dec["destination"], dec["task_kind"]))
        c["n_dispositions"] += 1
        c["counts"][r["disposition"]] += 1
        c["sources"][r["disposition_source"]] += 1
        if (r["disposition"] == "used-as-is"
                and r.get("review_status") == "none"
                and r["disposition_source"] == "observed_operation"):
            c["counts"].setdefault("_handoff", 0)
            c["counts"]["_handoff"] += 1

    for c in out.values():
        n, nd = c["n_dispositions"], c["n_decisions"]
        c["n_unknown"] = nd - n
        c["n_batches"] = len(c["_batches"]) or None
        handoff = c["counts"].pop("_handoff", 0)
        c["usable_rate"], c["usable_rate_lo"], c["usable_rate_hi"] = _rate(
            sum(c["counts"][d] for d in USABLE), n, nd)
        c["clean_rate"], c["clean_rate_lo"], c["clean_rate_hi"] = _rate(
            sum(c["counts"][d] for d in CLEAN), n, nd)
        c["handoff_rate"], c["handoff_rate_lo"], c["handoff_rate_hi"] = _rate(
            handoff, n, nd)
        c["basis"] = ("empirical" if n >= ACTUATION["min_dispositions"]
                      else "provisional")
        c["latency_p50"] = _median(c["_latencies"])
        del c["_latencies"], c["_batches"]
    return out


def _rate(favourable: int, n_recorded: int, n_decisions: int):
    """`(point, lo, hi)`. The point estimate is over RECORDED dispositions only; the
    bounds assume every unrecorded decision was adverse (lo) or favourable (hi).

    All three are None when nothing was recorded. `0.0` there would claim every
    hand-off was adverse, and `1.0` would claim the opposite -- the unrecorded case
    is unknown, which is a third thing.
    """
    if n_recorded == 0:
        return None, None, None
    point = favourable / n_recorded
    if n_decisions == 0:
        return point, point, point
    return point, favourable / n_decisions, (favourable + (n_decisions - n_recorded)) / n_decisions


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def cell_basis(rows: list[dict], destination: str, task_kind: str) -> tuple[str, int]:
    """`(basis, n_dispositions)` for one cell -- the actuation threshold, applied.

    A cell nobody has routed to is `provisional` with 0, not `empirical`: no
    dispositions is the strongest case of "the prior stands".

    NOTE what this does NOT do: `empirical` is a LABEL. Nothing in this repo may read
    it as permission to replace a prior -- see `ACTUATION['overrides_prior']`.
    """
    c = cells(rows).get((destination, task_kind))
    if c is None:
        return "provisional", 0
    return c["basis"], c["n_dispositions"]


def disagreements(rows: list[dict]) -> list[dict]:
    """Where the prior's prediction and the measured attempt disagree, WITHOUT
    diagnosing why.

    Review finding L1: `predicted 4s / measured 40s` is produced both by a latency
    model that omitted long-input processing and by a request that queued behind other
    work. Separate row types give chronology, not causes. So this reports the
    disagreement and says `cause: unresolved`; anything more would be a diagnosis
    manufactured from the row layout.
    """
    ver = ACTUATION["version"]
    decisions = {r["decision_id"]: r for r in rows
                 if r.get("row") == DECISION and r.get("rule_version") == ver}
    out = []
    for r in rows:
        if r.get("row") != ATTEMPT or r.get("rule_version") != ver:
            continue
        dec = decisions.get(r.get("decision_id"))
        if dec is None:
            continue
        pred, meas = dec.get("predicted_secs"), r.get("latency_secs")
        if pred is None or meas is None:
            continue
        if meas > 2 * pred or (pred > 2 * meas and meas > 0):
            out.append({"decision_id": r["decision_id"],
                        "destination": dec.get("destination"),
                        "task_kind": dec.get("task_kind"),
                        "predicted_secs": pred, "measured_secs": meas,
                        "ratio": round(meas / pred, 2) if pred else None,
                        "cause": "unresolved"})
    return out
