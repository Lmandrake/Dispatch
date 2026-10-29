#!/usr/bin/env python3
"""Render AA's intelligence-vs-cost plane with OUR reachable models highlighted.

    python3 tools/charts/intelligence_vs_cost.py [out.html]

Reads coordinates from `costmap` -- the one loader -- and never re-globs a corpus
itself. Three generators in this repo once did their own loading, so a change of
basis never reached them and regenerating produced byte-identical files while the
routing table moved underneath.

Every number in the prose is computed from `costmap.fleet_summary`. Two captions
here drifted into being false when they were hardcoded beside data that moved.

ENCODING, redundant on purpose so the chart does not depend on colour:

  group      colour AND shape   square = enterprise gateway, circle = outside, triangle = local
  provenance fill               solid = AA measured, hollow = AA's own estimate,
                                hollow + dashed = ours
  uncertainty a bar             drawn on any axis we computed rather than read
"""
from __future__ import annotations

import html
import math
import re
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "evals" / "harness"))

import costmap as C  # noqa: E402

OUT_DEFAULT = REPO / "charts" / "06-intelligence-vs-cost.html"

W, H = 1180, 700
#: The right margin only has to hold the widest label that lands on the right
#: edge, not every label -- an earlier 300 left ~450px of dead space and squeezed
#: the plot into two thirds of the width.
#: T was 92 with an HTML legend floating above the plot. The legend now lives
#: inside the grid, so that headroom is dead space.
#: R dropped 56 -> 34 on 2026-10-01, once far-right labels were forced inward (see
#: `place_labels`). While `Claude Fable 5.1` and `Claude Sonnet 5.5` took OUTWARD labels
#: the margin had to hold ~140px of text past the marker; with every label in the right
#: quarter now pointing inward, the only thing living out there is the axis's `+$`
#: annotation. Those 22px go to the data. Re-check the right edge after any change that
#: lets a far-right label escape outward again — the two are coupled.
L, R, T, B = 104, 34, 58, 104
PX0, PX1 = L, W - R
PY0, PY1 = T, H - B

#: Colour per access group, as CSS variables so each has a light AND a dark value.
#:
#: MEASURED contrast drove every choice. Pure yellow was asked for and is
#: unusable -- #ffd700 is 1.37:1 on the light background, against the 4.5:1 floor
#: this chart already had to fix once. A dark gold (#9a6a00, 4.61:1) still reads as
#: the yellow family and is legible; its dark-mode partner #e0a33c reads 7.86:1.
#: Every one of the eight values clears 4.5:1 in its own mode.
#:
#: Legend text is kept SHORT because it is drawn inside the plot in two columns;
#: the long form overran into the second column and was clipped.
GROUP_STYLE = {
    C.GATEWAY:     ("var(--g-gw)",  "square",   "enterprise gateway only"),
    C.BOTH:    ("var(--g-both)", "diamond",  "both inside & outside"),
    C.OUTSIDE: ("var(--g-out)",  "circle",   "paid, outside only"),
    C.LOCAL:   ("var(--g-loc)",  "triangle", "local, installed"),
    C.LOCAL_CANDIDATE: ("var(--g-loc)", "triangle", "local, could install"),
}
#: The frontier group is deliberately grey and semi-transparent: it is context for
#: our fleet, not a fourth thing competing for attention. Named separately from
#: GROUP_STYLE so it cannot be picked up by the fleet-drawing loop.
FRONTIER_COLOUR = "var(--mut)"
#: Linear dollars. Few and coarse on purpose -- at 3x font size only a handful
#: of tick labels fit without colliding.
#: Per-axis configuration. The whole renderer works off `p.x`, so a second chart is
#: produced by PROJECTING the x fields onto a different measure rather than by
#: copying the generator -- which is how the three older charts in this repo drifted
#: apart from each other.
AXES = {
    "cost": dict(
        out="06-intelligence-vs-cost.html",
        title="Performance vs. Cost (not response time)",
        axis="cost per task (USD)",
        ticks=(0, 1, 2, 3, 4, 5, 6, 7, 8),
        fmt=lambda v: f"${v:g}",
        icon="+$", icon_cls="dirn cash",
    ),
    "time": dict(
        out="07-intelligence-vs-time.html",
        title="Performance vs. Response Time (not cost)",
        axis="end-to-end time per task (minutes)",
        ticks=(0, 600, 1200, 1800, 2400, 3000, 3600),
        fmt=lambda v: f"{v / 60:g}",
        icon="+\u23F1", icon_cls="dirn clock",
    ),
}
TICKS = AXES["cost"]["ticks"]

#: Where the provenance stamp sits: the LOWER-RIGHT corner, BELOW the plot, outside the
#: axes entirely.
#:
#: 🔴 It used to live inside the plot's top-right, reserved as a 438x24 collision box.
#: Review feedback: the attribution line belongs outside the graph so it has nothing
#: to do with setting axes. It was setting them — a reserved box that large in the top-right pushes labels down
#: and left, which is how the dearest models ended up needing the space the right margin
#: was holding open. Provenance is metadata about the chart, not a mark on it, so it has
#: no business competing with the data for room. Outside the plot it reserves nothing.
STAMP_XY = (W - 6, H - 8)


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _base(name: str) -> str:
    """The model name with its effort/mode parenthetical removed."""
    return name.split(" (")[0]


def short_name(name: str) -> str:
    """Shorten an AA row name for display, keeping the effort setting.

    AA named a row "Claude Opus 5.5 (Adaptive Reasoning, Xhigh Effort, Default
    Fallback)" until 2026-10 and "Claude Opus 5.5 (Xhigh, Default Fallback)" since -- up to 62 characters, of which about 12 carry information here. Drawn
    in full, the frontier labels dominate the plot they are meant to give context
    to. The effort word is KEPT because it is the whole point of those rows: the
    same model at a different effort is a different point on this chart.

    The full name always survives in the tooltip, so nothing is lost.
    """
    if " (" not in name:
        return name
    base, _, rest = name.partition(" (")
    rest = rest.rstrip(")")
    m = re.search(r"(\w+)\s+Effort", rest)
    if m:
        return f"{base} · {m.group(1).lower()}"
    # AA dropped "Adaptive Reasoning" and "Effort" between 2026-09-30 and
    # 2026-10-16: "(Non-reasoning, High)" must still shorten to its effort word.
    m = re.search(r"\b(low|medium|high|xhigh|max)\b", rest, re.I)
    if m:
        return f"{base} · {m.group(1).lower()}"
    first = rest.split(",")[0].strip()
    # A bare mode or effort word ("max", "low", "Non-reasoning") is already short.
    return f"{base} · {first.lower()}" if len(first) <= 14 else base


# --------------------------------------------------------------------- scales --

def make_scales(pts, fleet):
    """LINEAR cost axis, on the owner's instruction (2026-09-30).

    A log axis is legible but misrepresents the thing being decided: it makes a
    $7.60 model look about three times a $0.005 one when it is fifteen hundred
    times. Linear tells the truth about ratios and pays for it by crushing
    everything under about $0.30 against the left edge -- which is itself the
    honest picture, since on a true cost scale the cheap tiers really are almost
    indistinguishable from free.
    """
    # The maximum comes from the MARKERS only (owner, 2026-10-01). Including the
    # upper end of every uncertainty band let the single widest band set the scale
    # and squeezed everyone else; bands now run off the right edge and are clipped
    # there, with the clipped end drawn OPEN so it cannot read as a measured bound.
    #
    # 🔴 And a BACKGROUND point may not stretch the axis past our own fleet. One grey
    # dot -- `Claude Fable 5 (… Opus 4.8 Fallback)` at $8.75, unlabelled, not reachable --
    # was setting `hi` to $9.10 while every model this chart is about ends at $7.63. That
    # lone outlier was 15% of the axis, which is most of the right-hand whitespace the
    # owner objected to twice. The domain now ends just past the FLEET, and background
    # points beyond it are clamped to the edge and drawn clipped-open, the same
    # convention the uncertainty bands already use for running off the right.
    ours = [p.x for p in fleet if p.x and p.x > 0]
    bg = [p.x for p in pts if p.x and p.x > 0]
    if not ours:
        raise ValueError("no fleet point carries a cost; the x axis has nothing to scale")
    # Background still counts where it sits INSIDE our range -- it is only the tail
    # beyond us that is refused a vote. 1.02, not 1.04: the last tick plus a hair.
    lo, hi = 0.0, max(ours + [x for x in bg if x <= max(ours)]) * 1.02
    ys = [p.y for p in pts] + [p.y for p in fleet]
    # Floor of 60, not 70. The data maxes at ~57.6, so a 70 floor left 17.7% of
    # the plot height empty above every mark -- space taken straight out of the
    # local cluster, which is where the label placer was running out of room.
    ytop = max(60.0, math.ceil(max(ys) / 10.0) * 10.0)

    def sx(v: float) -> float:
        return PX0 + (max(v, 0.0) - lo) / (hi - lo) * (PX1 - PX0)

    def sy(v: float) -> float:
        return PY1 - (v / ytop) * (PY1 - PY0)

    return sx, sy, lo, hi, ytop


# --------------------------------------------------------------------- marks --

def mark(cx: float, cy: float, shape: str, colour: str, tier: str,
         r: float = 6.0) -> str:
    """One marker. Fill carries provenance; shape carries the group."""
    solid = tier == C.MEASURED
    fill = colour if solid else "var(--s)"
    dash = ' stroke-dasharray="2.6 2"' if tier == C.OUR_ESTIMATE else ""
    # Same weight for both. A heavier ring on the hollow (estimate) glyphs made
    # them read as prominently as measured ones; the empty fill already carries
    # the distinction.
    sw = 1.6
    common = (f'fill="{fill}" stroke="{colour}" stroke-width="{sw}"{dash}')
    if shape == "square":
        s = r * 1.8
        return (f'<rect x="{cx - s / 2:.1f}" y="{cy - s / 2:.1f}" '
                f'width="{s:.1f}" height="{s:.1f}" rx="1.2" {common}/>')
    if shape == "triangle":
        a = r * 1.25
        return (f'<polygon points="{cx:.1f},{cy - a:.1f} '
                f'{cx + a:.1f},{cy + a * 0.82:.1f} '
                f'{cx - a:.1f},{cy + a * 0.82:.1f}" {common}/>')
    if shape == "diamond":
        a = r * 1.15
        return (f'<polygon points="{cx:.1f},{cy - a:.1f} {cx + a:.1f},{cy:.1f} '
                f'{cx:.1f},{cy + a:.1f} {cx - a:.1f},{cy:.1f}" {common}/>')
    if shape == "cross":
        # The frontier we cannot reach. Diamond moved to the both-ways group, and
        # an x-shape reads as "not available" rather than as another category.
        a = r * 0.85
        return (f'<path d="M{cx - a:.1f},{cy - a:.1f}L{cx + a:.1f},{cy + a:.1f}'
                f'M{cx + a:.1f},{cy - a:.1f}L{cx - a:.1f},{cy + a:.1f}" '
                f'fill="none" stroke="{colour}" stroke-width="1.9"/>')
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" {common}/>'


def place_labels(items, sy_top, sy_bot, reserved=()):
    """Greedy anti-collision: keep the text off the other text AND off the bars.

    Labels are the whole reason a scatter becomes unreadable, and this repo has
    shipped two charts with colliding text by not rendering before committing.
    Candidates run right, left, then above/below, and a label that cannot be
    placed anywhere is still drawn -- silently dropping one would hide a model
    the chart exists to show.

    Each item carries the horizontal extent of its uncertainty bar, and labels
    anchor OUTSIDE that extent rather than beside the marker. Anchoring at the
    marker put the bar through the middle of the text, which rendered as a
    strikethrough on all six local models and all three Novas -- caught only by
    looking at the picture.
    """
    # Seeded with the MARKER boxes, not just other labels. Without them a label
    # can land squarely on someone else's dot -- a grey frontier label sat on the
    # Fable marker, which reads as a rendering bug rather than a tight fit.
    placed: list[tuple[float, float, float, float]] = list(reserved)
    out = []

    def free(box):
        x0, y0, x1, y1 = box
        for q in placed:
            if x0 < q[2] + 9 and q[0] < x1 + 9 and y0 < q[3] + 2 and q[1] < y1 + 2:
                return False
        return True

    # Sorted by PRIORITY first, then y. Our own fleet claims its positions before
    # the frontier context does; otherwise a grey reference label can displace the
    # label of a model the chart exists to show.
    for prio, cx, cy, text, colour, bar_lo, bar_hi, cls in sorted(
            items, key=lambda t: (t[0], t[2])):
        w = {"lb": 6.35, "reflbl": 7.0}.get(cls, 5.8) * len(text) + 6
        # 16, not 13: bar boxes are now reserved (including this point's own), and
        # 16 clears its cap given the 9px pad in free().
        rx, lx = bar_hi + 16, bar_lo - 16 - w
        # Points in the right quarter of the plot are labelled INWARD, so a cluster
        # at the dear end does not force a wide empty right gutter.
        far_right = cx > PX0 + 0.72 * (PX1 - PX0)
        # Finer steps and a longer ladder than the first version, which ran out of
        # candidates inside the local cluster -- six models sit within a narrow
        # band of both axes there, and the fallback drew them on top of each other.
        ladder = (0, -12, 12, -24, 24, -36, 36, -48, 48, -62, 62,
                  -76, 76, -92, 92, -110, 110, -130, 130, -152, 152,
                  -176, 176, -202, 202, -230, 230)
        inward = [(lx, cy + 3.6 + dy, "end") for dy in ladder]
        outward = [(rx, cy + 3.6 + dy, "start") for dy in ladder]
        if far_right:
            # 🔴 ALL inward slots before ANY outward one. Interleaving them by `dy`
            # was the defect: an outward slot 12px up outranked an inward slot 12px
            # down, so `Claude Fable 5.1` and `Claude Sonnet 5.5` -- at 87% of the
            # axis -- both took outward labels, and the ~140px they needed past the
            # marker is what forced the wide right margin. A far-right point going
            # outward should be a last resort, not a coin toss with the next row.
            cands = inward + outward
        else:
            cands = [c for pair in zip(outward, inward) for c in pair]
        chosen = None
        for tx, ty, anchor in cands:
            # +6, not +26: the x tick numbers sit just below the axis and are not
            # in the collision list, so the old slack was one data change from a
            # collision.
            if ty < sy_top + 8 or ty > sy_bot + 6:
                continue
            # Horizontal bounds too. The left bound is the PLOT edge, not the
            # canvas edge: a canvas-edge bound still let the longest local label
            # sit in the axis margin, on top of the rotated y-axis title and the
            # tick numbers, neither of which is in the collision list.
            if tx < L - 2 or tx + w > W - 6:
                continue
            box = (tx, ty - 12, tx + w, ty + 5) if cls == "reflbl" else (tx, ty - 9, tx + w, ty + 3)
            if free(box):
                placed.append(box)
                chosen = (tx, ty, anchor)
                break
        if chosen is None:
            chosen = (rx, cy + 3.6, "start")
            placed.append((chosen[0], chosen[1] - 9, chosen[0] + w, chosen[1] + 3))
        tx, ty, anchor = chosen
        ax = tx if anchor == "start" else tx + w
        # Attach a leader to the BAR END the label sits next to, not to the
        # marker -- a leader from the marker would cross its own bar.
        attach = bar_hi if anchor == "start" else bar_lo
        out.append((ax, ty, anchor, text, colour, attach, cy, cls))
    return out


# ---------------------------------------------------------------------- build --

def build(published, fleet, frontier, ladders, watch, summary, spec) -> str:
    sx, sy, xlo, xhi, ytop = make_scales(published, fleet)
    # Both the fleet and the named frontier come out of the background cloud, or
    # they would be drawn twice -- once faint, once solid, half a pixel apart.
    aa_shown = ({p.aa_name for p in fleet if p.aa_name}
                | {p.label for p in frontier}
                | {r.aa_name for v in ladders.values() for r in v if r.aa_name}
                | {p.label for p in watch})
    parts: list[str] = []

    parts.append(f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="'
                 'Artificial Analysis Intelligence Index against USD cost per '
                 'task, with the models reachable on the enterprise gateway, outside it and on '
                 'this machine highlighted and all other models faded">')

    # grid + axes
    for v in range(0, int(ytop) + 1, 10):
        y = sy(v)
        parts.append(f'<line x1="{PX0}" y1="{y:.1f}" x2="{PX1}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{PX0 - 10}" y="{y + 3.6:.1f}" class="tick" '
                     f'text-anchor="end">{v}</text>')
    for t in spec['ticks']:
        if not (xlo <= t <= xhi):
            continue
        x = sx(t)
        lab = spec["fmt"](t)
        parts.append(f'<line x1="{x:.1f}" y1="{PY0}" x2="{x:.1f}" y2="{PY1}" class="grid"/>')
        parts.append(f'<text x="{x:.1f}" y="{PY1 + 20}" class="tick" '
                     f'text-anchor="middle">{lab}</text>')

    label_items = []
    # Reserved regions no label may occupy. The legend's footprint, then the
    # frontier polyline, then (in the loops below) every marker and every bar.
    # The provenance stamp is NOT reserved here any more: it sits below the plot, outside
    # the axes (see STAMP_XY), so it cannot collide with a label and must not be allowed
    # to displace one. Reserving 438x24 of the top-right corner for it was costing the
    # dearest models the room they then took out of the right margin.
    marker_boxes: list[tuple[float, float, float, float]] = [
        (PX1 - 460, PY1 - 118, PX1 - 44, PY1 - 20)]

    # the frontier, over the published field only
    front = C.pareto(published)
    if len(front) > 1:
        d = " ".join(f"{sx(p.x):.1f},{sy(p.y):.1f}" for p in front)
        parts.append(f'<polyline points="{d}" class="front"/>')
        # No annotation on the line. It was neither visible nor useful at this size
        # (owner, 2026-09-30); the legend already names the dotted curve.
        # Labels carry an opaque background halo (paint-order:stroke), so one
        # crossing the line punches a ragged gap in it. Four labels were cutting
        # the frontier's top-right terminus -- the exact segment the annotation
        # points at -- which reads as a broken line, not a tight fit.
        for a, b in zip(front, front[1:]):
            ax, ay, bx, by = sx(a.x), sy(a.y), sx(b.x), sy(b.y)
            for i in range(9):
                t = i / 8
                px, py = ax + (bx - ax) * t, ay + (by - ay) * t
                marker_boxes.append((px - 3, py - 3, px + 3, py + 3))

    # --- background: everything else, faded and unlabelled
    #
    # A point beyond the domain is CLAMPED to the right edge and marked, not dropped:
    # the axis no longer lets the background tail set the scale (see `scales`), and
    # silently deleting a model the cloud is supposed to represent would misstate how
    # far the field extends. Its tooltip carries the real figure.
    parts.append('<g class="bg">')
    offscale = 0
    for p in published:
        if p.aa_name in aa_shown:
            continue
        beyond = p.x > xhi
        if beyond:
            offscale += 1
        cx = min(sx(p.x), PX1 - 1)
        parts.append(f'<circle cx="{cx:.1f}" cy="{sy(p.y):.1f}" r="4.2"'
                     + (' class="offscale"' if beyond else '')
                     + f'><title>{esc(p.label)}\nindex {p.y:.1f} · ${p.x:,.2f}/task'
                     + ('\n⟶ beyond the axis, clamped to the edge' if beyond else '')
                     + '</title></circle>')
    parts.append('</g>')

    # --- watched vendors: grey and transparent like the cloud they came out of,
    # but LABELLED. They are context for who is catching up, not options.
    parts.append('<g class="watch">')
    for p in watch:
        cx, cy = sx(p.x), sy(p.y)
        parts.append(
            f'<g><title>{esc(p.label)}\nindex {p.y:.1f} · ${p.x:,.3f}/task\n'
            f'watched, not available to us</title>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.0"/></g>')
        label_items.append((2, cx, cy, short_name(p.label), FRONTIER_COLOUR,
                            cx, cx, "lbf"))
        marker_boxes.append((cx - 5, cy - 5, cx + 5, cy + 5))
    parts.append('</g>')

    # --- the frontier we are not on: named, but grey and recessive
    parts.append('<g class="frontier">')
    parts.append('<g class="frontier">')
    for p in frontier:
        cx, cy = sx(p.x), sy(p.y)
        parts.append(
            f'<g><title>{esc(p.label)}\nindex {p.y:.1f} · ${p.x:,.4f}/task\n'
            f'on the frontier — the best score available at this price</title>'
            f'{mark(cx, cy, "cross", FRONTIER_COLOUR, C.MEASURED, r=4.6)}</g>')
        label_items.append((1, cx, cy, short_name(p.label), FRONTIER_COLOUR,
                            cx, cx, "lbf"))
        marker_boxes.append((cx - 5.5, cy - 5.5, cx + 5.5, cy + 5.5))
    parts.append('</g>')

    # Base names that appear in BOTH our fleet and the frontier. Only these need
    # their effort setting spelled out to stay distinguishable.
    twinned = {_base(p.label) for p in frontier} & {
        _base(p.aa_name) for p in fleet if p.aa_name}

    # --- effort ladders: the same model at settings we do not route
    parts.append('<g class="lad">')
    for lbl, rungs in ladders.items():
        colour = GROUP_STYLE[rungs[0].group][0]
        d = " ".join(f"{sx(r.x):.1f},{sy(r.y):.1f}" for r in rungs)
        parts.append(f'<polyline points="{d}" class="ladder" stroke="{colour}"/>')
        # Reserve the LADDER LINE as an obstacle, not just its rung dots. Labels
        # carry an opaque halo, so one crossing a line punches a gap in it -- the
        # green Claude ladder was being cut by "Claude Opus 5". The frontier
        # polyline was already reserved; these were not.
        for a, b in zip(rungs, rungs[1:]):
            ax, ay, bx, by = sx(a.x), sy(a.y), sx(b.x), sy(b.y)
            for i in range(7):
                t = i / 6
                marker_boxes.append((ax + (bx - ax) * t - 3, ay + (by - ay) * t - 3,
                                     ax + (bx - ax) * t + 3, ay + (by - ay) * t + 3))
        for r in rungs:
            rx, ry = sx(r.x), sy(r.y)
            parts.append(
                f'<g class="rung"><title>{esc(short_name(r.label))}\n'
                f'index {r.y:.1f} · ${r.x:,.3f}/task\n'
                f'same model as {esc(lbl)}, cheaper effort setting</title>'
                f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="2.6" fill="{colour}"/></g>')
            marker_boxes.append((rx - 3.5, ry - 3.5, rx + 3.5, ry + 3.5))
    parts.append('</g>')

    # --- foreground
    parts.append('<g class="fg">')
    for p in sorted(fleet, key=lambda p: p.group):
        colour, shape, _ = GROUP_STYLE[p.group]
        cx, cy = sx(p.x), sy(p.y)

        tip = (f"{p.label}\nindex {p.y:.1f}"
               + (f" (range {p.y_lo:.1f}–{p.y_hi:.1f})" if p.has_y_range else "")
               + f"\n${p.x:,.4f}/task"
               + (f" (range ${p.x_lo:,.4f}–${p.x_hi:,.4f})" if p.has_x_range else "")
               + f"\n{p.tier.replace('_', ' ')}: {p.basis}")
        parts.append(f'<g><title>{esc(tip)}</title>')

        if p.has_x_range:
            x0, x1 = sx(p.x_lo), sx(p.x_hi)
            clipped_hi, clipped_lo = x1 > PX1, x0 < PX0
            x0, x1 = max(x0, PX0), min(x1, PX1)
            parts.append(f'<line x1="{x0:.1f}" y1="{cy:.1f}" x2="{x1:.1f}" '
                         f'y2="{cy:.1f}" class="bar" stroke="{colour}"/>')
            # A cap asserts "the interval ends here". Omit it on an end that ran off
            # the plot, so a clipped band reads as continuing rather than as bounded.
            for xe, clip in ((x0, clipped_lo), (x1, clipped_hi)):
                if clip:
                    continue
                parts.append(f'<line x1="{xe:.1f}" y1="{cy - 3.5:.1f}" '
                             f'x2="{xe:.1f}" y2="{cy + 3.5:.1f}" class="bar" '
                             f'stroke="{colour}"/>')
        if p.y_haircut is not None:
            yh = sy(p.y_haircut)
            parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx:.1f}" '
                         f'y2="{yh:.1f}" class="cut" stroke="{colour}"/>')
            # A CAP, not a second marker. Drawn as a full glyph this produced eight
            # green triangles under a header that says six local models -- a stated
            # count the reader could contradict by counting. It also had to pick a
            # provenance style, and whichever it picked disagreed with either the
            # legend or the caveat text. A cap is unambiguously the end of the stub.
            parts.append(f'<line x1="{cx - 4.5:.1f}" y1="{yh:.1f}" '
                         f'x2="{cx + 4.5:.1f}" y2="{yh:.1f}" class="cut" '
                         f'stroke="{colour}"/>')
            marker_boxes.append((cx - 5, cy - 5, cx + 5, yh + 5))
        elif p.has_y_range:
            y0, y1 = sy(p.y_lo), sy(p.y_hi)
            # Capped, and thinner than the x bars. Uncapped it read as a chart
            # feature -- a long bare vertical line looks drawn, not measured.
            parts.append(f'<line x1="{cx:.1f}" y1="{y0:.1f}" x2="{cx:.1f}" '
                         f'y2="{y1:.1f}" class="ybar" stroke="{colour}"/>')
            for ye in (y0, y1):
                parts.append(f'<line x1="{cx - 3.5:.1f}" y1="{ye:.1f}" '
                             f'x2="{cx + 3.5:.1f}" y2="{ye:.1f}" class="ybar" '
                             f'stroke="{colour}"/>')
        parts.append(mark(cx, cy, shape, colour, p.tier))
        parts.append('</g>')
        bar_lo = sx(p.x_lo) if p.has_x_range else cx
        bar_hi = sx(p.x_hi) if p.has_x_range else cx
        # Qualify with the effort setting ONLY where a frontier twin of the same
        # base model is also on the chart. Three points came from Claude Opus 5.5 --
        # ours plus two frontier variants -- and only ours was unqualified, so the
        # headline "$1.82 vs $5.98 at max effort" claim pointed at the one dot that
        # did not say its effort.
        #
        # Qualifying ALL of them instead was worse: every paid pick is max effort
        # (that is what "flagship" means here, and the caveat says so), so five of
        # the six suffixes carried no information while crowding the top-right.
        # NOT applied to local models either -- both Qwen3.8 copies share one AA
        # row, so the AA name would collapse 8bit and 4bit together and lose the
        # quantisation, which is the entire distinction between them.
        text = p.label
        if p.group != C.LOCAL and p.aa_name and _base(p.aa_name) in twinned:
            text = short_name(p.aa_name)
        label_items.append((0, cx, cy, text, colour, bar_lo, bar_hi, "lb"))
        marker_boxes.append((cx - 7.5, cy - 7.5, cx + 7.5, cy + 7.5))
        # Reserve the BARS too. A label may not sit on another model's interval:
        # Nova Pro's bar ran straight through the "Nova Lite" label, so the two
        # read as one continuous range with a name in the middle of it. The
        # docstring above claimed this was fixed -- it was fixed for a label
        # against its OWN bar only.
        if p.has_x_range:
            marker_boxes.append((bar_lo - 4, cy - 4.5, bar_hi + 4, cy + 4.5))
        elif p.has_y_range:
            marker_boxes.append((cx - 4.5, sy(p.y_hi) - 4, cx + 4.5,
                                 sy(p.y_lo) + 4))
    parts.append('</g>')

    # Owner, 2026-10-16: whole-width "best local" rules were too noisy. Each best model
    # gets a white tag with a leader to its marker instead, placed by the same
    # anti-collision pass as every other label (fixed offsets landed on other text).
    _best = {grp: max((p for p in fleet if p.group == grp and p.x and p.x > 0),
                      key=lambda p: p.y, default=None)
             for grp in (C.LOCAL, C.LOCAL_CANDIDATE)}
    _cur, _poss = _best[C.LOCAL], _best[C.LOCAL_CANDIDATE]
    _tags = [(_cur, "current")] if _cur else []
    if _poss and (not _cur or _poss.y > _cur.y + 1.0):
        _tags.append((_poss, "possible"))
    for p, tag in _tags:
        cx = min(max(sx(p.x), PX0), PX1 - 1)
        # Anchored on the MARKER, not the bar: on the time chart a bar spans most of
        # the axis, and a tag at its far end points at nothing.
        label_items.append((0.5, cx, sy(p.y), f"best local ({tag}) {p.y:.1f}",
                            "#fff", cx + 6, cx + 6, "reflbl"))

    for ax, ty, anchor, text, colour, attach, cy, cls in place_labels(
            label_items, PY0, PY1, reserved=marker_boxes):
        # A leader only when the label had to move off its own row; on the same
        # row the marker or its bar already reaches the text.
        if cls == "reflbl":
            parts.append(f'<line x1="{attach - 6 + (3 if ax > attach else -3):.1f}" y1="{cy:.1f}" '
                         f'x2="{ax:.1f}" y2="{ty - 4:.1f}" class="reflead"/>')
        elif abs(ty - (cy + 3.6)) >= 5 or abs(ax - attach) > 40:
            lead = "lead" if cls == "lb" else "lead leadf"
            parts.append(f'<line x1="{attach:.1f}" y1="{cy:.1f}" x2="{ax:.1f}" '
                         f'y2="{ty - 3:.1f}" class="{lead}" stroke="{colour}"/>')
        fill = "" if cls == "reflbl" else f' fill="{colour}"'   # CSS sets light/dark
        parts.append(f'<text x="{ax:.1f}" y="{ty:.1f}" class="{cls}" '
                     f'text-anchor="{anchor}"{fill}>{esc(text)}</text>')

    # TWO reference lines, not one. A single "best local" rule was read as the local
    # ceiling while candidate models sat plainly above it -- the line meant
    # INSTALLED and never said so. Naming both makes the gap between what we run and
    # what we could run the readable thing it should have been.
    #
    # 🔴 And the "possible" line is DROPPED when it is not above "current". Installing
    # the best candidate on 2026-10-01 inverted the pair -- K2 Horizon at 25.3 beat the
    # best remaining candidate at 24.6 -- and two lines 0.7 index apart overprinted each
    # other's labels. A "possible" ceiling at or below what is already installed is also
    # not a fact worth a line: it says there is nothing better to install, which the
    # caption can say in words without drawing a second rule through the first.
    # Date and source ON the chart, so a screenshot carries its own provenance.
    # Its footprint is reserved in `marker_boxes` at the top of this function --
    # reserving it HERE did nothing, because place_labels has already run.
    sx0, sy0 = STAMP_XY
    parts.append(f'<text x="{sx0:.0f}" y="{sy0:.0f}" class="stamp" '
                 f'text-anchor="end">Source: artificialanalysis.ai &#183; '
                 f'retrieved {C.corpus_date()}</text>')
    parts.append(legend_svg(PX1 - 452, PY1 - 96,
                            present={p.group for p in fleet}))
    # Direction-of-good markers at the far end of each axis, so which way is worse
    # needs no caption.
    parts.append(f'<text x="{PX1 + 14:.0f}" y="{PY1 + 12:.0f}" '
                 f'class="{spec["icon_cls"]}">{spec["icon"]}</text>')
    parts.append(f'<text x="{PX0:.0f}" y="{PY0 - 18:.0f}" class="dirn" '
                 f'text-anchor="middle">+\U0001F9E0</text>')
    # Axis titles SHORTENED: at 34px a full sentence does not fit the plot width.
    # The detail they carried now lives in the keyed caveats below the chart.
    parts.append(f'<text x="{(PX0 + PX1) / 2:.0f}" y="{H - 34}" class="axl" '
                 f'text-anchor="middle">{esc(spec["axis"])}</text>')
    parts.append(f'<text transform="translate(34,{(PY0 + PY1) / 2:.0f}) rotate(-90)" '
                 f'class="axl" text-anchor="middle">Intelligence Index</text>')
    parts.append("</svg>")
    return "".join(parts)


def project_to_time(points):
    """Return points with the x fields carrying SECONDS instead of dollars.

    The renderer reads `p.x` everywhere, so projecting is how the second chart is
    built -- not by copying the generator. Points with no published time are
    DROPPED rather than placed at zero, which would plant a model at "instant".
    """
    import dataclasses as _dc
    out = []
    for p in points:
        if not p.has_secs:
            continue
        out.append(_dc.replace(p, x=p.secs, x_lo=p.secs_lo or p.secs,
                               x_hi=p.secs_hi or p.secs))
    return out


def prose(summary, published, frontier, fleet, ladders, watch) -> tuple[str, str]:
    s = summary
    gap = s["best_paid_y"] - s["best_local_y"]
    # Telegraphic on purpose. An earlier version ran five prose lines and took as
    # much vertical space as the plot while saying less than this does.
    lede = (
        f'<b>{s["n_fleet"]} reachable</b> of {len(published)} billed &nbsp;·&nbsp; '
        # Zero-count groups are OMITTED, not printed as "0 gateway": Nova's
        # removal emptied that group, and a zero reads as a data gap rather than as
        # "nothing here is gateway-exclusive", which is the actual finding.
        + " &nbsp;·&nbsp; ".join(
            f'{s["n_by_group"][g]} {lbl}' for g, lbl in (
                (C.GATEWAY, "gateway-only"), (C.BOTH, "both"),
                (C.OUTSIDE, "paid outside"), (C.LOCAL, "local installed"),
                (C.LOCAL_CANDIDATE, "could install"))
            if s["n_by_group"].get(g))
        + f' &nbsp;·&nbsp; {len(frontier)} unreachable'
        + f' &nbsp;·&nbsp; {len(watch)} watched (Gemini)'
        + f' &nbsp;·&nbsp; {sum(len(v) for v in ladders.values())} effort settings'
        + f' &nbsp;·&nbsp; AA corpus {C.corpus_date()}<br>'
        # "Hollow = estimate. Bar = computed axis." was cut: the legend says
        # exactly that, 60px below and inside the plot.
        + f'Provenance: {s["n_by_tier"][C.MEASURED]} measured, '
        + f'{s["n_by_tier"][C.AA_ESTIMATED]} their estimate, '
        + f'{s["n_by_tier"][C.OUR_ESTIMATE]} ours. &nbsp;'
        # The most expensive thing that was missing. Without it a reader takes
        # "20.2 local vs 57.6 Opus" as "local is a third as good at MY tasks",
        # which is exactly the error this repo's own percentile-is-not-a-bar rule
        # exists to prevent.
        + f'<b>Y = AA\'s general benchmark, not our jobs.</b>')
    # THE HEADLINE, and it is computed, not asserted -- it also reversed the one
    # this chart carried an hour ago. Adding the GPT-6 ladder put purchasable rungs
    # BELOW our local electricity cost, so "local is the cheap option" stopped being
    # true. Any claim about local's cost advantage has to be derived against every
    # purchasable rung, not just each model's flagship.
    best_local = max((p for p in fleet if p.group == C.LOCAL),
                     key=lambda p: p.y, default=None)
    buyable = [p for p in fleet if p.group != C.LOCAL and p.tier == C.MEASURED]
    buyable += [r for v in ladders.values() for r in v]
    # DOMINATING option: meaningfully cheaper AND better, picked for the largest
    # score advantage rather than the lowest price.
    #
    # Picking the CHEAPEST qualifying rung instead gave "98x less" off GPT-6 Luna
    # at low effort -- arithmetically true and rhetorically hollow, because that
    # rung answers in about 2,000 tokens against our 30,000 and only matches us on
    # score. The 1.5x floor keeps the cost half of the claim from being marginal.
    take = ""
    if best_local:
        dominating = [p for p in buyable
                      if p.x < best_local.x / 1.5 and p.y > best_local.y]
        if dominating:
            d = max(dominating, key=lambda p: p.y)
            take = (f'<b>Local is not the cheap option.</b> '
                    f'{short_name(d.label)} costs ${d.x:.2f} against '
                    f'${best_local.x:.2f} to run {best_local.label} here — '
                    f'{best_local.x / d.x:.1f}× cheaper and '
                    f'<b>{d.y - best_local.y:+.0f} index points</b>. ')
    take += (f'Best reachable is <b>{gap:.0f} points</b> above best local. '
             f'Gap decides delegation, not price.')

    # Computed, not asserted: a frontier point that is the SAME base model as one
    # of ours at a cheaper effort setting. This is the one actionable thing on the
    # chart, so it must be derived or it will go stale like the two captions this
    # repo already had to correct.
    def base(name: str) -> str:
        return name.split(" (")[0]
    owned = {base(p.aa_name): p for p in fleet if p.aa_name}
    deals = [(o, f) for f in frontier
             if (o := owned.get(base(f.label))) and f.x < o.x * 0.9]
    if deals:
        o, f = min(deals, key=lambda d: d[1].x / d[0].x)
        take += (f' <b>Left on the table:</b> {short_name(f.label)} = '
                 f'${f.x:,.2f} for {f.y:.1f}, vs ${o.x:,.2f} for {o.y:.1f} at max '
                 f'effort — {o.x / f.x:.1f}× cheaper, same model.')
    return lede, take


CSS = """
:root{--s:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--mut:#898781;--mut2:#6f6d68;--line:rgba(137,135,129,.32);
  --g-gw:#1f6fb4;--g-both:#1b7837;--g-out:#9a6a00;--g-loc:#6a3d9a}
@media(prefers-color-scheme:dark){:root{--s:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--mut:#8f8d86;--mut2:#a9a7a0;--line:rgba(160,158,150,.3);
  --g-gw:#5fa8e8;--g-both:#4caf6d;--g-out:#e0a33c;--g-loc:#b088e0}}
*{box-sizing:border-box}
body{background:var(--s);color:var(--ink);font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:12px 18px 16px;max-width:1320px}
h1{font:700 32px/1.15 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0 0 2px;letter-spacing:-.02em}
h2{font:400 17px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink2);margin:0 0 8px}
p.lede{color:var(--ink2);font-size:12px;line-height:1.45;margin:0 0 5px}
p.take{margin:0 0 6px;font-size:12.5px;line-height:1.45}
p.note{color:var(--mut2);font-size:11px;line-height:1.4;margin:4px 0 0;max-width:160ch}
svg{width:100%;height:auto;overflow:visible;display:block;margin:0}
.grid{stroke:var(--mut);stroke-width:.5;opacity:.18}
/* --mut2 rather than --mut plus opacity. Measured: --mut is 3.5:1 on the light
   background and the frontier labels were 2.0:1 -- the least legible text on the
   page, and WORSE in light than dark. Recede by size and weight, not contrast. */
/* 3x, on the owner's instruction. The axis titles were shortened to suit: a
   full sentence at 34px does not fit the plot width. */
.tick{font:25px sans-serif;fill:var(--mut2)}
.axl{font:600 27px sans-serif;fill:var(--ink2)}
/* Direction-of-good markers at the ends of each axis. */
.dirn{font:600 24px sans-serif;fill:var(--ink2)}
/* Money-green, and a shade lighter in dark mode to hold contrast. */
.dirn.cash{fill:#1d7a3d}
/* Yellow for the clock. #ffd700 measures 1.37:1 on the light background, so the
   light value is a dark gold that still reads yellow; dark mode gets the bright one. */
.dirn.clock{fill:#9a6a00}
@media(prefers-color-scheme:dark){.dirn.clock{fill:#ffd24a}}
@media(prefers-color-scheme:dark){.dirn.cash{fill:#4fc47a}}
.bg circle{fill:var(--mut);opacity:.16}
.bg circle:hover{opacity:.55}
.bg circle.offscale{opacity:.30;stroke:var(--mut);stroke-width:.8;stroke-dasharray:1.5 1.5}
.front{fill:none;stroke:var(--mut);stroke-width:1.5;stroke-dasharray:5 4;opacity:.5}
.frontlbl{font:italic 15px sans-serif;fill:var(--mut2)}
.reflbl{font:600 12px sans-serif;fill:#fff}
.reflead{stroke:#fff;stroke-width:1;opacity:.8}
@media(prefers-color-scheme:light){.reflbl{fill:#111}.reflead{stroke:#111}}
.bar{stroke-width:1.5;opacity:.6;stroke-linecap:round}
.ybar{stroke-width:1.2;opacity:.6;stroke-linecap:round}
.cut{stroke-width:1.5;opacity:.75;stroke-dasharray:3 2.5}
/* Effort ladders: the same model at a cheaper setting. Thin and low-opacity so
   the routed pick still dominates, but present, because this is where the
   largest saving on the chart lives. */
.ladder{fill:none;stroke-width:1.1;opacity:.45}
.rung{opacity:.5}
.lead{stroke-width:.8;opacity:.42}
.leadf{opacity:.26}
.lb{font:600 10.5px ui-monospace,Menlo,monospace;paint-order:stroke;stroke:var(--s);stroke-width:3.6px}
/* The frontier we are not on: named so it can be read, recessive so it never
   competes with our own fleet. Lighter weight, smaller, and semi-transparent. */
.lbf{font:400 9.5px ui-monospace,Menlo,monospace;paint-order:stroke;stroke:var(--s);stroke-width:3.2px;fill:var(--mut2)}
.frontier polygon{opacity:.5}
/* Watched vendors: a shade clearer than the anonymous cloud so a labelled dot
   is findable, still plainly background. */
.watch circle{fill:var(--mut);opacity:.34}
.watch circle:hover{opacity:.7}
.kt{font:10px sans-serif;fill:var(--ink2)}
.kh{font:600 9px sans-serif;fill:var(--mut2);letter-spacing:.04em}
.stamp{font:600 14px sans-serif;fill:var(--ink2)}
.stamp2{font:12px sans-serif;fill:var(--mut2)}
"""


def legend_svg(x: float, y: float, present=frozenset(GROUP_STYLE)) -> str:
    """The key, drawn INSIDE the plot in its empty upper-left corner.

    That corner is structurally empty -- nothing is both cheap and clever, so no
    model can ever land there -- which makes it free space rather than borrowed
    space. Previously this was a flex box floating above the chart that consumed
    almost as much height as the plot itself.

    Three columns, 13px rows, no border box: the surrounding whitespace is the
    separation, so a frame would only add weight.

    The two columns MULTIPLY -- a hollow blue square is column 1 composed with
    column 2 -- so they carry headers saying which channel each one reads. Without
    them the provenance column read as a fourth group, especially while its
    swatches were grey circles, a glyph column 1 had already spent twice.
    """
    rows = [(shape, colour, what) for g, (colour, shape, what)
            in GROUP_STYLE.items() if g in present]
    rows.append(("cross", FRONTIER_COLOUR, "frontier, unreachable"))
    out = [f'<g class="key" transform="translate({x:.0f},{y:.0f})">']
    dy = 13.0
    out.append('<text x="0" y="-13" class="kh">shape = where</text>')
    for i, (shape, colour, what) in enumerate(rows):
        yy = i * dy
        out.append(mark(7, yy, shape, colour, C.MEASURED, r=4.3))
        out.append(f'<text x="17" y="{yy + 3.4:.1f}" class="kt">{esc(what)}</text>')
    # The watched set gets its own row for the same reason the ladder does: a
    # labelled grey dot that the key does not mention is a question waiting to be
    # asked.
    yy = len(rows) * dy
    out.append(f'<circle cx="7" cy="{yy:.1f}" r="4.0" fill="{FRONTIER_COLOUR}" '
               f'opacity=".34"/>')
    out.append(f'<text x="17" y="{yy + 3.4:.1f}" class="kt">watched only</text>')
    # Second column: provenance, which is about FILL rather than shape, and NOTHING
    # else. Stroked in --ink2 on purpose so it is not mistaken for the frontier's
    # grey. The bar / haircut / ladder glyphs used to live here too, which made the
    # header a lie -- none of them is evidence.
    cx2 = 124.0
    out.append(f'<text x="{cx2 - 7:.0f}" y="-13" class="kh">fill = evidence</text>')
    prov = ((C.MEASURED, "measured"), (C.AA_ESTIMATED, "their estimate"),
            (C.OUR_ESTIMATE, "our estimate"))
    for i, (tier, what) in enumerate(prov):
        yy = i * dy
        out.append(mark(cx2, yy, "circle", "var(--ink2)", tier, r=4.3))
        out.append(f'<text x="{cx2 + 10:.0f}" y="{yy + 3.4:.1f}" class="kt">'
                   f'{esc(what)}</text>')

    # Third column: line-and-stub glyphs, each of which the owner has now had to
    # ask about. The effort ladder in particular was UNEXPLAINED -- small dots
    # trailing left of a flagship with nothing saying what they were.
    cx3 = 252.0
    out.append(f'<text x="{cx3 - 8:.0f}" y="-13" class="kh">other marks</text>')
    out.append(f'<line x1="{cx3 - 5:.0f}" y1="0" x2="{cx3 + 5:.0f}" y2="0" '
               f'class="bar" stroke="var(--ink2)"/>')
    out.append(f'<text x="{cx3 + 11:.0f}" y="3.4" class="kt">'
               f'computed, not read</text>')
    # The effort ladder: a line with rungs, drawn the way it appears on the plot.
    yy = dy
    out.append(f'<polyline points="{cx3 - 6:.0f},{yy + 2:.1f} {cx3:.0f},'
               f'{yy:.1f} {cx3 + 6:.0f},{yy - 2:.1f}" class="ladder" '
               f'stroke="var(--ink2)"/>')
    for ox in (-6, 0, 6):
        out.append(f'<circle cx="{cx3 + ox:.0f}" cy="{yy - ox / 3:.1f}" r="2.1" '
                   f'fill="var(--ink2)" class="rung"/>')
    out.append(f'<text x="{cx3 + 11:.0f}" y="{yy + 3.4:.1f}" class="kt">'
               f'same model, lower effort</text>')
    # The 4-bit pair: the other glyph nobody can guess.
    yy = 2 * dy
    out.append(f'<line x1="{cx3:.0f}" y1="{yy - 4:.1f}" x2="{cx3:.0f}" '
               f'y2="{yy + 3:.1f}" class="cut" stroke="var(--ink2)"/>')
    out.append(f'<line x1="{cx3 - 4:.0f}" y1="{yy + 3:.1f}" x2="{cx3 + 4:.0f}" '
               f'y2="{yy + 3:.1f}" class="cut" stroke="var(--ink2)"/>')
    out.append(f'<text x="{cx3 + 11:.0f}" y="{yy + 3.4:.1f}" class="kt">'
               f'4-bit haircut</text>')
    out.append('</g>')
    return "".join(out)


def notes(summary) -> str:
    """The caveats, KEYED to the element each one explains.

    Kept visible rather than folded into a <details>: making the honesty opt-in is
    the wrong trade for this project. But as one 197-word block it was
    unnavigable -- a reader looking at the little dashed stub could not find the
    sentence about it. Same content, keyed and about a third the length.
    """
    s = summary
    items = [
        ("Local cost",
         f'electricity <em>plus</em> amortised hardware — and the hardware is '
         f'~18× the power, at ${C.MACHINE_USD_PER_HOUR:.2f}/h '
         f'(${C.MACHINE_PRICE_USD:,.0f} over {C.MACHINE_LIFE_YEARS:.0f} yr at '
         f'{C.MACHINE_DUTY_HOURS_PER_DAY:.0f} h/day). The duty cycle is the '
         f'load-bearing guess: 24 h/day would cut this threefold. Power itself is '
         f'an <em>assumed</em> {C.POWER_DELTA_W[0]:.0f}–'
         f'{C.POWER_DELTA_W[1]:.0f} W — <code>powermetrics</code> needs a '
         f'password, and Apple\'s 480 W is a supply ceiling, not a draw.'),
        ("Cost axis",
         f'AA\'s cost is mostly <em>input</em> tokens, while our throughput '
         f'measures generation on short prompts — prefill is missing, so these '
         f'understate. Bars span '
         f'{C.PREFILL_MULTIPLIER[0]:.0f}–{C.PREFILL_MULTIPLIER[1]:.0f}× to admit '
         f'it.'),
        ("Nova", "priced from a list, never billed."),
        ("Sonnet 4.5",
         "absent from AA; placed by mapping its human-preference score onto this "
         "index. The two sources disagree on ordering there — hence the wide bars."),
        ("Second lower mark",
         f'{s["n_haircut_pairs"]} four-bit models carry a 4-bit accuracy haircut: '
         f'published degradation figures, applied by us. Eight-bit\'s published '
         f'figure is under 1%, so those four draw no pair.'),
        ("&ldquo;Flagship&rdquo;", "highest published effort per model."),
    ]
    body = " &nbsp;".join(f"<b>{k}</b> — {v}" for k, v in items)
    return f'<p class=note><b>Weak spots, keyed to the chart.</b> {body}</p>'


SUBTITLE = ("Every model we can reach \u2014 a managed gateway, paid "
            "accounts, and local hardware \u2014 against the whole published field")


def main(argv: list[str]) -> int:
    published = C.load_published()
    fleet = C.load_fleet()
    ladders = C.load_ladders(fleet)
    fleet = fleet + C.local_candidates()
    frontier = C.frontier_not_ours(published, fleet, ladders)
    watch = C.watched(published, fleet, ladders)
    summary = C.fleet_summary(fleet)
    lede, take = prose(summary, published, frontier, fleet, ladders, watch)

    for key, spec in AXES.items():
        pub, flt, fro, wat, lad, sub = (published, fleet, frontier, watch,
                                        ladders, SUBTITLE)
        if key == "time":
            # Projected onto seconds. Models with no published time are DROPPED, so
            # this chart is a subset -- said out loud rather than left to be noticed.
            pub, flt = project_to_time(published), project_to_time(fleet)
            fro, wat = project_to_time(frontier), project_to_time(watch)
            lad = {k: v for k, v in
                   ((k, project_to_time(v)) for k, v in ladders.items())
                   if len(v) > 1}
            dropped = len(fleet) - len(flt)
            sub = (f"{SUBTITLE} &#183; <b>{len(pub)} of {len(published)}</b> billed "
                   f"models publish an end-to-end time"
                   + (f"; {dropped} of ours do not and are absent" if dropped else ""))
        out = REPO / "charts" / spec["out"]
        doc = (
            "<!doctype html><meta charset=utf-8>\n"
            '<meta name=viewport content="width=device-width,initial-scale=1">\n'
            f"<title>{esc(spec['title'])}</title>\n"
            f"<style>{CSS}</style>\n"
            f"<h1>{esc(spec['title'])}</h1>\n<h2>{sub}</h2>\n"
            f"<p class=lede>{lede}</p>\n"
            f"<p class=take>{take}</p>\n"
            f"{build(pub, flt, fro, lad, wat, summary, spec)}\n"
            f"{notes(summary)}\n")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc)
        print(f"wrote {out.name} \u00b7 {len(pub)} published, {len(flt)} highlighted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
