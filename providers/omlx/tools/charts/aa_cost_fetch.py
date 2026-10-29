#!/usr/bin/env python3
"""Refresh the published intelligence-vs-cost corpus from Artificial Analysis.

WHY THIS EXISTS SEPARATELY from `references/artificial-analysis.json`. That file
carries per-skill metrics (IFBench, hallucination, long-context) for a corpus
deliberately scoped to open weights <=200B, and `refer.py` guards it. It has no
cost field at all, and despite its own `_selection` note claiming "plus all
Anthropic" it holds ZERO Anthropic rows -- so it cannot answer "what does a task
cost" for anything we actually pay for. Rather than widen a file whose selection
other guards depend on, this writes a second, narrowly-scoped file.

WHAT THE TWO AXES ARE. Both come from AA's own embedded payload, not from us:

  y = `intelligenceIndex`                          AA Intelligence Index
  x = `intelligenceIndexCostPerTask.cost.total`    USD to run the index once

`cost.total` is the sum of the per-evaluation `weightedCostPerTask` values, and
is overwhelmingly INPUT tokens -- for Qwen3.8 27B it is $2.40 of $2.49. That
matters downstream: a local model's cost is dominated by prompt processing, not
generation, so our own throughput measurement (generation-only, short prompts)
cannot be used to derive it precisely. See `costmap.py`.

WHERE THE DATA LIVES. The `/evaluations/...` page that renders the published
chart fetches its data over an API and embeds only 30 records with no cost at
all -- curling it is useless. Any `/models/<slug>` page ships the full flight
payload instead. Slugs differ in what they carry, so several are unioned.

`intelligenceIndexIsEstimated` is AA's OWN flag and is preserved verbatim. An
estimated score is not a measurement and must not be plotted as one.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parent.parent.parent
OUT = REPO / "references" / "artificial-analysis-cost.json"

#: Pages to union, kept plural on purpose but deliberately SHORT.
#:
#: Measured 2026-09-30: the `claude-opus-5` page alone ships the entire
#: catalogue (676 models, 173 with cost) and four further pages added zero new
#: or upgraded records. So the union is insurance against one page's payload
#: changing, not a coverage mechanism -- each extra slug is a 4 MB fetch that
#: currently buys nothing, which is why there are two rather than five.
#:
#: GLM-5.3-Flash, long absent from every payload, appears as of 2026-10-16.
SLUGS = (
    "claude-opus-5",
    "gpt-5-6",
)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

#: Fields kept per model. Deliberately narrow: this file exists to place a dot on
#: two axes and say how much to trust it, not to mirror AA's whole schema.
KEEP = (
    "slug", "intelligenceIndex", "intelligenceIndexIsEstimated",
    "price1mBlended0To3To1", "isOpenWeights", "parameters", "releaseDate",
    # ACTIVE parameters, which is what decides generation speed on this hardware.
    # Measured here: tok/s x weight-GB is 403-457 GB/s across five dense local
    # models (about 82% of theoretical bandwidth), so generation is memory-bandwidth
    # bound. A mixture-of-experts reads only its active weights per token -- GLM
    # reads an impossible 1839 GB/s on total params, which is the tell. Without
    # this field a 36B MoE with 4B active looks as slow as a 36B dense model,
    # understating it by nearly 10x.
    "inferenceParametersActiveBillions", "licenseName", "openSourceCategorization",
)

#: Output tokens AA's index consumes per task, needed to turn a local model's
#: measured tokens/sec into a wall-clock time and hence an electricity cost.
#: Stored flat as `outputTokensPerTask` from the `output` member.
TOKENS_FIELD = "intelligenceIndexOutputTokensPerTask"


def fetch(slug: str) -> str:
    """Return one model page's HTML, or '' if it could not be retrieved."""
    url = f"https://artificialanalysis.ai/models/{slug}"
    try:
        out = subprocess.run(["curl", "-sS", "-A", UA, url],
                             capture_output=True, text=True, timeout=120)
    except Exception as e:                                   # pragma: no cover
        print(f"  {slug}: FAILED ({type(e).__name__})", file=sys.stderr)
        return ""
    if out.returncode != 0:
        print(f"  {slug}: curl exited {out.returncode}", file=sys.stderr)
        return ""
    return out.stdout


def flight_payload(html: str) -> str:
    """Join the Next.js flight chunks into one string.

    The page ships its data as many `self.__next_f.push([1,"<json-escaped>"])`
    calls whose payloads must be concatenated AFTER unescaping -- a record is
    routinely split across two chunks, so unescaping the joined form or joining
    the raw form both corrupt it.
    """
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    parts = []
    for c in chunks:
        try:
            parts.append(json.loads(c))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def records(buf: str) -> list[dict]:
    """Brace-match every object that opens with a uuid `id`.

    NOTE the absence of a scan cap. An earlier version stopped at 20,000 chars
    and silently found ZERO cost-bearing records, because a model object with
    its full evaluation array is larger than that -- the truncated text failed
    to parse and was skipped. A cap here does not lose a field, it loses the
    entire record, which reads as "AA does not publish cost".
    """
    out: list[dict] = []
    for m in re.finditer(r'\{"id":"[0-9a-f-]{36}"', buf):
        i = m.start()
        depth = 0
        for j in range(i, len(buf)):
            ch = buf[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        out.append(json.loads(buf[i:j + 1]))
                    except json.JSONDecodeError:
                        pass
                    break
    return out


def cost_total(rec: dict) -> float | None:
    """USD to run the whole index once, or None when AA publishes no cost."""
    c = rec.get("intelligenceIndexCostPerTask")
    if not isinstance(c, dict):
        return None
    cost = c.get("cost")
    if not isinstance(cost, dict):
        return None
    t = cost.get("total")
    return float(t) if isinstance(t, (int, float)) else None


def harvest(slugs=SLUGS) -> dict[str, dict]:
    """Union the model records across pages, keyed by AA's display name."""
    models: dict[str, dict] = {}
    for slug in slugs:
        html = fetch(slug)
        if not html:
            continue
        recs = records(flight_payload(html))
        added = 0
        for r in recs:
            name = r.get("name")
            if not name or r.get("intelligenceIndex") is None:
                continue
            row = {k: r.get(k) for k in KEEP if r.get(k) is not None}
            row["intelligenceIndex"] = float(r["intelligenceIndex"])
            row["intelligenceIndexIsEstimated"] = bool(
                r.get("intelligenceIndexIsEstimated"))
            ct = cost_total(r)
            if ct is not None:
                row["costPerTask"] = ct
            tok = r.get(TOKENS_FIELD)
            if isinstance(tok, dict) and isinstance(tok.get("output"), (int, float)):
                row["outputTokensPerTask"] = float(tok["output"])
            # Wall-clock seconds for one index task, END TO END -- AA's own
            # measurement, so it includes queueing and network latency as well as
            # generation. That is the whole point of the second chart: a model can be
            # cheap and clever and still take ten minutes to answer.
            t = r.get("intelligenceIndexTimePerTask")
            if isinstance(t, (int, float)) and t > 0:
                row["secondsPerTask"] = float(t)
            prev = models.get(name)
            # MERGE field-by-field rather than picking a winning record. A page
            # ships the same model more than once with different fields populated,
            # and "prefer whichever has cost" silently dropped `secondsPerTask` for
            # models whose cost-bearing record happened to omit it -- two rows I had
            # already verified carried a time went missing that way.
            if prev is None:
                models[name] = row
                added += 1
            else:
                gained = [k for k, v in row.items()
                          if v is not None and prev.get(k) is None]
                if gained:
                    prev.update({k: row[k] for k in gained})
                    added += 1
        print(f"  {slug}: {len(recs)} records, {added} new/upgraded")
    return models


def carry_forward(models: dict, prior: dict, prior_date: str) -> list[str]:
    """OPCD-2: never let a refresh silently lose a model or its cost.

    A live pull sometimes omits `costPerTask` (or a whole row) that the previous snapshot
    had, and the chart then drops the model with no gate failing. Fill the gap from the
    prior snapshot and mark the row `carriedFrom` so it is visibly stale, not fresh.
    Returns the names carried, for the run log.
    """
    carried = []
    for name, old in prior.items():
        new = models.get(name)
        if new is None:
            # Any row, cost-bearing or not: the fleet map names estimated rows too, and
            # a payload that thins out (2026-10-28: 698 -> 210 rows) must not delete them.
            models[name] = dict(old, carriedFrom=old.get("carriedFrom", prior_date))
            carried.append(name)
        elif "costPerTask" not in new and "costPerTask" in old:
            new["costPerTask"] = old["costPerTask"]
            new["carriedFrom"] = old.get("carriedFrom", prior_date)
            carried.append(name)
    return carried


def main() -> int:
    print(f"fetching {len(SLUGS)} model pages from artificialanalysis.ai")
    models = harvest()
    if not models:
        print("REFUSING to write: harvested nothing", file=sys.stderr)
        return 1
    try:
        _old = json.loads(OUT.read_text())
        carried = carry_forward(models, _old.get("models", {}), _old.get("_retrieved", "?"))
    except (OSError, ValueError):
        carried = []
    for n in carried:
        print(f"  carried forward from the previous snapshot: {n}")
    with_cost = sum(1 for v in models.values() if "costPerTask" in v)
    if with_cost == 0:
        print("REFUSING to write: no record carries a cost, which means the "
              "payload shape changed", file=sys.stderr)
        return 1
    doc = {
        "_what": "AA Intelligence Index against USD cost to run that index "
                 "once -- the two axes of AA's published intelligence-vs-cost "
                 "chart, harvested so we can place our own fleet on it.",
        "_source": "https://artificialanalysis.ai/models/<slug> "
                   "(embedded Next.js flight payload)",
        "_slugs": list(SLUGS),
        "_retrieved": _dt.date.today().isoformat(),
        "_x_axis": "costPerTask = intelligenceIndexCostPerTask.cost.total, USD. "
                   "Sum of the per-evaluation weightedCostPerTask values. "
                   "OVERWHELMINGLY INPUT TOKENS (for Qwen3.8 27B, $2.40 of "
                   "$2.49), so it is not comparable to a generation-only rate.",
        "_y_axis": "intelligenceIndex = AA Intelligence Index.",
        "_basis_note": "intelligenceIndexIsEstimated is AA's OWN flag, kept "
                       "verbatim. An estimated score is not a measurement and "
                       "must not be plotted or ranked as one. Every record "
                       "that carries a cost is measured; the estimates are all "
                       "cost-free, which is why a cost-bearing subset is also "
                       "the plottable subset.",
        "_why_not_the_evaluations_page": "The /evaluations/ page that renders "
                   "the published chart loads its data over an API and embeds "
                   "only 30 records with no cost field. Model pages ship the "
                   "full payload.",
        "_reproduce": "python3 tools/charts/aa_cost_fetch.py",
        "_counts": {"models": len(models), "with_cost": with_cost,
                    "estimated": sum(1 for v in models.values()
                                     if v["intelligenceIndexIsEstimated"])},
        "models": models,
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    print(f"wrote {OUT.relative_to(REPO)}: {len(models)} models, "
          f"{with_cost} with cost")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
