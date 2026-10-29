"""Which second pass a review gets: a cross-provider GPT pass, a second Opus, or a Sonnet critic.

THE MEASUREMENT (a closed study; summary in `docs/MEASURED_RESULTS.md`):
42 real escaped bugs in 14 snapshots across 7 repos, 3 runs per shape, scoped packets,
Sonnet judge, bootstrap CIs. One Opus review recalled 0.42. Any second independent
pass raised that to about 0.51-0.53. Blind GPT minus a second blind Opus: +0.03 recall,
90% CI -0.03 to +0.08, a TIE. GPT added about 0.1 judged false alarms per run against
the second Opus's 0.9, and costs no Claude tokens. A Sonnet critic of the Opus review
matched both on recall at Sonnet prices.

THE RULE that follows, and nothing stronger:
  * A second independent pass pays. Always take one on a review that matters.
  * When INDEPENDENCE is required (assurance: a different provider, account and
    training lineage must look at it), the route is GPT. It is not better at finding
    bugs; it is independent, and quieter.
  * Otherwise a second Opus or a Sonnet critic is the cost-equivalent default; GPT is
    still a fine choice when Claude tokens are the scarce thing.

Every figure is parsed from the study results file at call time (absent in the public export, where it reports so), and
`tests/test_second_opinion.py` fails if a direction this rests on reverses.
"""
from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
STUDY = REPO / "providers" / "chatgpt" / "research" / "multi-model-eval"
REPLAY = STUDY / "replay" / "RESULTS.md"

GPT, OPUS2, SONNET_CRITIC = "gpt", "opus-second-pass", "sonnet-critic"
#: Shape ids in the study -> the route each one is.
SHAPES = {"S1": "opus-alone", "S2b": OPUS2, "Xb": GPT, "SW": SONNET_CRITIC}

_NUM = r"([+-]?\d+(?:\.\d+)?)"


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def evidence(path: pathlib.Path = REPLAY) -> dict:
    """Recall (with 95% CI), lenient false positives per run and Claude tokens per run for
    each shape, plus the paired GPT-minus-second-Opus recall difference with its 90% CI."""
    if not path.is_file():
        # The study's per-run files are not published; fall back to the committed summary.
        d = json.loads((pathlib.Path(__file__).with_name("second_opinion_summary.json")).read_text())
        d["shapes"] = {k: {**v, "recall_ci95": tuple(v["recall_ci95"])} for k, v in d["shapes"].items()}
        if d.get("paired"):
            d["paired"]["ci90"] = tuple(d["paired"]["ci90"])
        return d
    text = path.read_text()
    shapes, diff = {}, None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        c = _cells(line)
        if c[0] in SHAPES and len(c) > 11:
            m = re.match(_NUM + r" \(" + _NUM + "-" + _NUM + r"\)", c[1])
            if not m:
                continue
            fp = re.match(_NUM, c[5])
            tok = re.match(_NUM + "k", c[10])
            shapes[c[0]] = {"route": SHAPES[c[0]], "recall": float(m.group(1)),
                            "recall_ci95": (float(m.group(2)), float(m.group(3))),
                            "fp_per_run": float(fp.group(1)) if fp else None,
                            "claude_eff_tokens_k": float(tok.group(1)) if tok else None}
        elif c[0] == "Xb - S2b" and len(c) >= 3 and c[1] == "recall":
            m = re.match(_NUM + r" \(" + _NUM + ", " + _NUM + r"\)", c[2])
            if m:
                diff = {"gpt_minus_opus2_recall": float(m.group(1)),
                        "ci90": (float(m.group(2)), float(m.group(3)))}
    n = re.search(r"\*\*(\d+) escaped bugs in (\d+) buggy snapshots across (\d+) repos\*\*", text)
    return {"source": str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path),
            "bugs": int(n.group(1)) if n else None,
            "snapshots": int(n.group(2)) if n else None,
            "repos": int(n.group(3)) if n else None,
            "shapes": shapes, "paired": diff}


def added_fp(ev: dict, shape: str) -> float:
    """False alarms a union shape ADDS over one Opus review (both are per-run means)."""
    return ev["shapes"][shape]["fp_per_run"] - ev["shapes"]["S1"]["fp_per_run"]


def recommend(*, independence: bool = False, gpt_ready: bool | None = None,
              gpt_why: str = "", path: pathlib.Path = REPLAY) -> dict:
    """The second pass for a review. `independence=True` means assurance needs a
    different provider/account/lineage. `gpt_ready=False` (from the chatgpt probe) means
    GPT cannot be reached now; independence then cannot be met here and that is said,
    never silently swapped for a same-provider pass."""
    ev = evidence(path)
    s, d = ev["shapes"], ev["paired"]
    tie = d is not None and d["ci90"][0] <= 0 <= d["ci90"][1]
    base = (f"one Opus {s['S1']['recall']:.2f} recall; second Opus {s['S2b']['recall']:.2f}, "
            f"GPT {s['Xb']['recall']:.2f}, Sonnet critic {s['SW']['recall']:.2f} "
            f"({ev['bugs']} escaped bugs, {ev['snapshots']} snapshots, 3 runs)")
    vs = (f"GPT minus second Opus {d['gpt_minus_opus2_recall']:+.2f} recall "
          f"(90% CI {d['ci90'][0]:+.2f} to {d['ci90'][1]:+.2f}): "
          f"{'a tie' if tie else 'not a tie'}; judged false alarms added per run GPT "
          f"{added_fp(ev, 'Xb'):.1f} vs second Opus {added_fp(ev, 'S2b'):.1f}")
    if independence:
        if gpt_ready is False:
            return {"route": None, "alternatives": [OPUS2, SONNET_CRITIC], "unmet": "independence",
                    "reason": "independence requires a different provider and the GPT route is not "
                              f"ready ({gpt_why or 'probe said no'}); a same-provider pass "
                              "does not meet it. " + base,
                    "evidence": ev}
        return {"route": GPT, "alternatives": [], "unmet": None,
                "reason": "independence required: only the cross-provider pass is "
                          f"independent. It ties on recall and is quieter. {vs}. {base}",
                "evidence": ev}
    return {"route": OPUS2, "alternatives": [SONNET_CRITIC, GPT], "unmet": None,
            "reason": f"a second independent pass pays; the three tie on recall, so take the "
                      f"cheapest you have. {base}. {vs}",
            "evidence": ev}
