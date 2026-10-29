"""Every Jev question and every threshold, in one file.

This is the human review surface. TypeSafe's own guidance is that questions and
thresholds are the part people must read, and that they should live in one place rather
than be scattered through the code that calls them. Nothing else in this package
defines a question or compares against a constant.

Read `docs/FINDINGS.md` before changing a threshold. The numbers here are not tuned;
they are starting points chosen to send more work to a human, not less.
"""

from __future__ import annotations

MODEL = "jev-latest"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
# Deliberately strict, because the failure that matters is a plausible-looking wrong
# answer reaching a reviewer as though it were settled. Every one of these should be
# re-set against measured data, never argued into place. See the standing rule in
# CoverageMap: do not pre-set an acceptance threshold for something unmeasured.

# Below this, a Choice or Score verdict does not stand on its own.
AUTO_ACCEPT_CONFIDENCE = 0.80

# A passage at or below this on `is_a_provision` reads as non-normative: commentary, a
# self-assessment question, a form template, or the risk statement echoed back.
#
# MEASURED, n=260, 2026-09-28 (studies/misfire_benchmark_2026-09-28/):
#   <= 0.12  catches 95.0% of known risk-echo misfires, flags  5.0% of live text
#   <= 0.15  catches 96.3%,                              flags 10.0%
#   <= 0.20  catches 98.8%,                              flags 16.3%
# 0.12 is chosen because the marginal echo caught above it costs twice the false flags.
# Re-measure before moving it; do not argue it into a new value.
NOT_A_PROVISION = 0.12

# MEASURED REDUNDANT, same run. `echoes_the_risk` has excellent specificity (live text
# sits at p90 = 0.09) but poor sensitivity (echo misfires spread from p10 = 0.11 to
# p90 = 0.96). OR-ing it into the rule above moves echo detection 96.3% -> 97.5% at an
# unchanged false-flag rate, which does not justify treating it as load-bearing.
# Retained because it rides free in the same call and its disagreement with
# `is_a_provision` is diagnostic, but nothing should gate on it alone.
ECHOES_THE_RISK = 0.50

# `is_a_provision` measures NORMATIVITY, not AUTHENTICITY. Invented prose scored a median
# 0.685 against live text's 0.655 -- statistically indistinguishable, because invented
# prose is invented to look like a requirement. Jev is never shown the source document, so
# it cannot detect a fabricated quote even in principle. That check is a string comparison
# and belongs in code. Never present this battery as a fabrication guard.
DETECTS_FABRICATION = False


# ---------------------------------------------------------------------------
# The battery
# ---------------------------------------------------------------------------
# All four are asked in a single call. Jev evaluates each independently against the same
# state, so adding questions barely changes latency and does not create the context-rot
# a long prompt would.
#
# THE LOAD-BEARING FINDING: `relation` on its own is fooled by the exact failure mode
# this project cares most about. On a passage that was the risk statement's own wording
# quoted back as a NASA citation, `relation` returned "imposes_control" at probability
# 0.89 with confidence 0.84, and `specificity` returned 3.97 out of 4 at confidence 0.97
# -- confidently wrong on both. `is_a_provision` returned 0.16, which is a clean
# rejection. So the guard questions are not redundant decoration: they are the only
# reason this battery is safe to use. Never read `relation` alone.

RELATION = {
    "type": "choice",
    "instructions": "How does the `passage` relate to the risk described in `risk`?",
    "criteria": {
        "imposes_control": (
            "The passage states a requirement or directive that, if followed, would "
            "reduce or control the specific failure described in `risk`."
        ),
        "offers_guidance": (
            "The passage gives non-binding guidance, recommendation, or practice "
            "bearing on the failure described in `risk`."
        ),
        "mentions_context": (
            "The passage touches the same subject area but imposes no control and "
            "gives no guidance on the failure described in `risk`."
        ),
        "unrelated": (
            "The passage does not address the failure described in `risk` at all."
        ),
    },
}

# The guard that caught the misfire. Asked about the passage alone -- it deliberately
# does not mention the risk, so it cannot be dragged toward a verdict by the risk's
# wording the way `relation` was.
IS_A_PROVISION = {
    "type": "noul",
    "instructions": (
        "Is the `passage` a governance provision issued by a standards body -- a "
        "requirement, directive, or guidance statement -- as opposed to analysis, "
        "commentary, or a restatement of the risk being assessed?"
    ),
    "criteria": {
        "true": "It reads as published requirement or guidance text from a standard.",
        "false": (
            "It reads as commentary, analysis, or a paraphrase of the risk being assessed."
        ),
    },
}

ECHOES_RISK = {
    "type": "noul",
    "instructions": (
        "Is the `passage` substantially a restatement of the text in `risk` rather than "
        "independent source material?"
    ),
    "criteria": {
        "true": "The passage paraphrases or repeats the risk statement's own wording.",
        "false": "The passage is independent text that happens to bear on the risk.",
    },
}

# Kept for diagnostics, NOT for ranking. Jev's published limitations say score levels are
# weakly calibrated numerically and must not be interpolated to reconstruct a magnitude.
# It is here because its disagreement with `is_a_provision` is itself a useful signal.
SPECIFICITY = {
    "type": "score",
    "instructions": (
        "How specifically does the `passage` address the exact failure described in `risk`?"
    ),
    "criteria": [
        "Not at all -- different subject",
        "Same broad domain only",
        "Addresses a related mechanism",
        "Addresses this failure among others",
        "Directly and specifically addresses this failure",
    ],
}

BATTERY = {
    "relation": RELATION,
    "is_a_provision": IS_A_PROVISION,
    "echoes_the_risk": ECHOES_RISK,
    "specificity": SPECIFICITY,
}


def build_state(risk: dict, passage: str) -> dict:
    """The state for one (risk, passage) pair.

    The risk is passed as named fields rather than one prose blob because Jev's
    published limitations include degraded accuracy on large states full of detail the
    question does not need, and because a question can then refer to a field by name.

    Only the four causal fields and the title go in. `Mitigating Document(s)` is
    deliberately excluded: it names documents the team already believes are relevant,
    which would leak the answer into the question.
    """
    return {
        "risk": {
            "title": risk["title"],
            "if": risk["if"],
            "then": risk["then"],
            "due_to": risk["due_to"],
            "resulting_in": risk["resulting_in"],
        },
        "passage": passage,
    }
