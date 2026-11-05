"""Which Anthropic tier a subagent spawn should get: sonnet or opus.

`delegate.route` ranks LOCAL models on a published per-job corpus. This module answers
the other question every session actually faces -- which `model:` to pass to a spawn on
the sanctioned gateway -- and it answers it from our own measurement, because no
published corpus ranks the Claude tiers on the work we hand them.

🔴 HAIKU IS BANNED EVERYWHERE (owner, 2026-10-31: "Ban it everywhere"; "Sonnet 5.5 is
the lowest model to consider, due to Haiku's error rate."). Sonnet is the floor. This
reverses the 2026-10-20 restoration of the Haiku rung, so no path here returns it.

The principle, measured 2026-10-20 (`docs/research/2026-10-20-model-ladder/`): a tier
earns work when a wrong answer will be CAUGHT, not when the task looks simple.

The rules, owner-approved 2026-10-20 and amended by the ban (numbers are stable, because
recorded decisions cite them):

  1. Haiku is banned; Sonnet is the floor.
  2. A failed check escalates, never ships: Sonnet, then Opus.
  3. Opus for factual recall, summaries, extraction a person will trust, judgments and
     reviews. None has a mechanical check.
  4. A passed check is not proof: when a wrong answer that slips past is costly, Opus.
  5. To save money on uncheckable work, lower Opus's effort; do not drop a tier.
  6. Sonnet is the step down when there is no check, for well-specified work.
  7. Speed alone never drops a tier.

WHAT COUNTS AS A CHECK: a mechanical test that runs on the output before anything
relies on it and that can fail -- tests, schema validation, a compiler or type check,
an exact match against a source, a command whose result can be re-run and compared.
NOT a check: a model reading the output and agreeing, the small model's own confidence,
"it looks right". This module cannot verify that a named check is real; it records it,
and the ledger records whether it passed.

Every figure printed as evidence is COMPUTED from the committed reports in
`docs/research/2026-10-20-model-ladder/data/`, never typed here, and
`tests/test_tiers.py` re-checks each rule's direction against those reports.

Pure stdlib, no I/O in `decide`.
"""
from __future__ import annotations

import json
import pathlib
import re

SONNET, OPUS = "sonnet", "opus"
#: Rung 1 of the ladder (the operating rules): no model at all. Not an alias, so
#: it resolves to no wire id and a spawn guard never sees it.
PYTHON = "python"

#: Kinds of work a spawn does. Coarse on purpose: the rules only need to know whether a
#: kind can ever have a mechanical check.
KINDS = ("search", "code", "transform", "recall", "summary", "extraction", "judgment",
         "other", "agentic", "draft", "parse")

#: Rule 0. Anything parseable -- dates, ids, counts, sorting, frontmatter,
#: schema-shaped files -- is deterministic Python, the cheapest rung, before any model.
DETERMINISTIC = frozenset({"parse"})

#: Words that mark a "check" as a reader rather than a mechanism (rule 1's definition).
#: A check naming one of these is recorded but treated as no check: it cannot fail on
#: its own. Coarse on purpose; a false refusal costs an escalation path, a false accept
#: promises one that will never fire.
_NOT_MECHANICAL = re.compile(
    r"\b(model|llm|gpt|claude|opus|sonnet|haiku|judge|review(?:er|s)?|reads?|"
    r"looks?|agrees?|eyeball|confiden(?:t|ce)|vibe|human|manual(?:ly)?)\b", re.I)


def is_mechanical(check: str | None) -> bool:
    """True when `check` names something that runs and can fail without a reader.

    Heuristic over the text (this module cannot run the check): blank, or naming a
    model, a reviewer or a reader's impression, is not mechanical.
    """
    check = (check or "").strip()
    return bool(check) and not _NOT_MECHANICAL.search(check)

#: Rule 8 (E9, 2026-10-24, a break-even experiment). `agentic` = a solver running a tool
#: loop: Haiku 5.5 passed 0 of 4 E6t trials at $6-8 each while Sonnet passed 4 of 4 at
#: $0.5-1.3. `draft` = producing candidates that a stronger model must then review:
#: Sonnet review of cheap drafts alone cost 63-85% of Sonnet drafting directly (Haiku
#: route 117%), so review overhead caps the saving whatever the producer. Both stay on
#: Sonnet, check or not. E9 batch3: a remote enterprise model, remote-large, through
#: OpenCode's tool loop also passed 0 of 8 on the E5 grouping unit (capability, not
#: tooling), so agentic multi-step geospatial solving is DO NOT for remote-large too.
SONNET_ONLY = frozenset({"agentic", "draft"})

#: Rule 3. These go to Opus even with a "check", because what passes for a check on
#: them is a reader agreeing, which is not mechanical.
OPUS_ONLY = frozenset({"recall", "summary", "extraction", "judgment"})

#: Rule 6. Well-specified kinds where Sonnet is the no-check step down.
SONNET_OK = frozenset({"search", "code", "transform", "other"}) | SONNET_ONLY

#: Rule 2. Where a failed check goes.
ESCALATE_TO = OPUS

DATA = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "research"
        / "2026-10-20-model-ladder" / "data")

RULES = {
    0: "Parseable work is deterministic Python: no model, no tier.",
    1: "Haiku is banned everywhere (owner, 2026-10-31); Sonnet is the floor.",
    2: f"A failed check escalates, never ships: Sonnet, then {ESCALATE_TO}.",
    3: "Opus for recall, summaries, trusted extraction, judgment or review.",
    4: "A passed check is not proof: when a missed error is costly, Opus.",
    5: "To save money on uncheckable work, lower Opus's effort; do not drop a tier.",
    6: "Sonnet is the no-check step down, for well-specified work only.",
    7: "Speed alone never drops a tier.",
    8: "Agentic solving and drafting stay on Sonnet; never delegate drafting to a cheap "
       "producer without pricing the review.",
}


def decide(kind: str, *, check: str | None = None, stakes: str = "normal",
           fast: bool = False) -> dict:
    """The tier for one spawn. Returns {model, effort, escalate_to, check, rules,
    reason}.

    `check` is the command (or named mechanical test) that will run on the output.
    `stakes='high'` means a wrong answer that slips past the check is costly.
    `fast` is accepted only so rule 7 can be stated where someone asked for speed.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if stakes not in ("normal", "high"):
        raise ValueError("stakes must be 'normal' or 'high'")
    check = (check or "").strip() or None
    out = {"kind": kind, "check": check, "stakes": stakes, "model": None,
           "effort": None, "escalate_to": None, "rules": [], "reason": "",
           "check_mechanical": is_mechanical(check)}
    if fast:
        out["rules"].append(7)

    if kind in DETERMINISTIC:
        out.update(model=PYTHON,
                   reason="parseable input: write the Python, spend no model call")
        out["rules"].append(0)
        return out

    if check is not None and not out["check_mechanical"]:
        check = None

    if stakes == "high":
        out.update(model=OPUS, reason="a missed error is costly, so the strongest "
                                      "tier, whether or not a check runs")
        out["rules"].append(4)
        return out

    if kind in SONNET_ONLY:
        out.update(model=SONNET, reason=f"{kind}: a cheaper producer fails or saves nothing "
                                        f"once review is priced, check or not")
        out["rules"].append(8)
        return out

    if kind in OPUS_ONLY:
        out["rules"].append(3)
        out.update(model=OPUS, reason=f"{kind} has no mechanical check, and Sonnet "
                                      f"is not the step down for it either")
        out["rules"].append(5)
        return out

    if check is None:
        out.update(model=SONNET, reason="well-specified work with no mechanical check")
        out["rules"] += [1, 6]
        return out

    out.update(model=SONNET, escalate_to=ESCALATE_TO,
               reason=f"a mechanical check runs on the output ({check})")
    out["rules"] += [1, 2]
    return out


# ------------------------------------------------------------------ the evidence --

def evidence() -> dict:
    """The figures each rule rests on, read from the committed reports."""
    sq = json.loads((DATA / "simpleqa-report.json").read_text())
    cg = json.loads((DATA / "codegen-report.json").read_text())
    a, s, pm = sq["arms"], cg["strategies"], cg["per_model"]
    # the cheapest confidence threshold that gets within 2 points of Opus alone
    near = min((c for c in sq["cascades"]
                if c["correct"] >= a["opus-default"]["correct"] - 0.02),
               key=lambda c: c["escalated"])
    return {
        "recall_haiku": (a["haiku-default"]["correct"], a["haiku-default"]["incorrect"]),
        "recall_sonnet": (a["sonnet-default"]["correct"], a["sonnet-default"]["incorrect"]),
        "recall_opus": (a["opus-default"]["correct"], a["opus-default"]["incorrect"]),
        "recall_opus_low_cost_ratio": a["opus-low"]["cost_per_item"]
        / a["opus-default"]["cost_per_item"],
        "recall_opus_low_correct": a["opus-low"]["correct"],
        "recall_confidence_cascade": (near["escalated"], near["correct"],
                                      near["cost_per_item"]
                                      / a["opus-default"]["cost_per_item"]),
        "code_opus": (s["opus x1 unchecked"]["correct"],
                      s["opus x1 unchecked"]["cost_per_problem"]),
        "code_sonnet": (s["sonnet x1 unchecked"]["correct"],
                        s["sonnet x1 unchecked"]["cost_per_problem"]),
        "code_haiku_unchecked": (s["haiku x1 unchecked"]["correct"],
                                 s["haiku x1 unchecked"]["cost_per_problem"]),
        "code_false_accept": {m: pm[m]["false_accept_given_public_pass"] for m in pm},
        "code_median_latency": {m: pm[m]["median_latency_s"] for m in pm},
        "recall_median_latency": {k: a[k]["median_latency_s"] for k in a},
    }


def evidence_lines(rule_ids) -> list[str]:
    e = evidence()
    h, o = e["recall_haiku"], e["recall_opus"]
    lines = {
        1: (f"owner ban, 2026-10-31, for Haiku's error rate. Recall, no check: Haiku "
            f"{h[0]:.2f} correct / {h[1]:.2f} WRONG; code without a check: Haiku "
            f"{e['code_haiku_unchecked'][0]:.2f} vs Opus {e['code_opus'][0]:.2f}"),
        2: (f"code, unchecked: Sonnet {e['code_sonnet'][0]:.2f} vs Opus "
            f"{e['code_opus'][0]:.2f}; the gap is what the escalation exists to catch"),
        3: (f"recall: a cheap tier was wrong {h[1]:.0%} of the time; a confidence-gated "
            f"cascade had to escalate {e['recall_confidence_cascade'][0]:.0%} of items, at "
            f"{e['recall_confidence_cascade'][2]:.0%} of Opus's cost"),
        4: ("check passed but answer wrong: " + ", ".join(
            f"{m} {v:.1%}" for m, v in sorted(e["code_false_accept"].items(),
                                              key=lambda kv: -kv[1]))),
        5: (f"recall: Opus at low effort {e['recall_opus_low_correct']:.2f} correct at "
            f"{e['recall_opus_low_cost_ratio']:.0%} of default cost; Sonnet "
            f"{e['recall_sonnet'][0]:.2f} vs Opus {o[0]:.2f}"),
        6: (f"code: Sonnet {e['code_sonnet'][0]:.2f} vs Opus {e['code_opus'][0]:.2f} at "
            f"{e['code_sonnet'][1] / e['code_opus'][1]:.0%} of the cost"),
        7: ("median seconds per call on code: " + ", ".join(
            f"{m} {v:.0f}" for m, v in e["code_median_latency"].items())),
    }
    lines[0] = ("ladder rung 1 (owner rule): a parser costs no tokens "
                "and is exactly reproducible; no model measurement is needed or claimed")
    lines[8] = ("E9 2026-10-24: Haiku solver 0 of 4 at $6-8 a trial vs Sonnet 4 of 4 at "
                "$0.5-1.3; Sonnet review of cheap drafts cost 63-85% of Sonnet drafting "
                "directly (Haiku route 117%); remote-large as OpenCode tool-loop solver 0 of 8 on E5 (Sonnet 2/2 with item); token counts priced at plan rates "
                "(E9 break-even experiment)")
    return [f"rule {i}: {RULES[i]}\n           evidence: {lines[i]}"
            for i in sorted(set(rule_ids))]
