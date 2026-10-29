# evals/harness/atoms.py
"""Per-atom scoring: many independent verdicts per run instead of one bit.

The existing checkers compute 11 (B4) and 4 (B5) gold atoms and then collapse them
behind a recall threshold. That collapse is why a model scoring 10/11 and one
scoring 3/11 were the same measurement, and it is why 760 runs' worth of atom
detail is gone. Recording the atoms costs nothing -- the work is already done.

An atom result deliberately carries no text. Fixtures may be built over real meeting text, and a `detail` string is exactly how a
name ends up in a committed result file.
"""

from dataclasses import dataclass
from enum import Enum
import re


class Outcome(Enum):
    """Four-valued on purpose.

    A boolean cannot say "the output carries no evidence" or "this checker cannot
    judge this case", and both collapse to FAIL if forced. The distinction is
    load-bearing on trap atoms, where silence must not read as success.
    """

    PASS = "pass"
    FAIL = "fail"
    UNMEASURED = "unmeasured"
    REFUSED = "refused"


@dataclass(frozen=True)
class Atom:
    id: str
    cls: str        # R | T | F | S | J
    kind: str       # key into ATOM_KINDS
    spec: dict


@dataclass(frozen=True)
class AtomResult:
    atom_id: str
    cls: str
    outcome: Outcome


def _norm(s: str) -> list[str]:
    """The normalisation gold_recall already uses, so a migrated fixture scores
    identically: punctuation and markdown stripped, lowercased. Letter runs and
    digit runs are SEPARATE tokens ([a-z]+|[0-9]+) so a number and its unit match
    whether or not the model spaced them ("800ms" == "800 ms" == "800 ms" ==
    ['800','ms']); whitespace of any Unicode kind is already a token boundary."""
    return re.findall(r"[a-z]+|[0-9]+", s.lower())


def _has_run(hay: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def _blank(output: str) -> bool:
    return not output or not output.strip()


def _contains_run(spec: dict, output: str) -> Outcome:
    want = _norm(spec["tokens"])
    if not want:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    return Outcome.PASS if _has_run(_norm(output), want) else Outcome.FAIL


def _absent_run(spec: dict, output: str) -> Outcome:
    want = _norm(spec["tokens"])
    if not want:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    return Outcome.FAIL if _has_run(_norm(output), want) else Outcome.PASS


def _line_limit(spec: dict, output: str) -> Outcome:
    """Structural (S) budget: at most `max_lines` non-blank lines.

    A blank output is UNMEASURED, not PASS: "zero lines" trivially satisfies any
    limit, so counting it as PASS would let a model that produced nothing max out
    every structural budget in the instrument -- the same degenerate strategy the
    trap atoms guard against.
    """
    max_lines = spec["max_lines"]
    if not isinstance(max_lines, int) or isinstance(max_lines, bool) or max_lines < 0:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    n = sum(1 for ln in output.splitlines() if ln.strip())
    return Outcome.PASS if n <= max_lines else Outcome.FAIL


def _count_equals(spec: dict, output: str) -> Outcome:
    """Exactly `count` matches of `pattern` (regex, multiline). For mechanical
    tasks whose correct answer is a specific number of hits."""
    pattern = spec["pattern"]
    count = spec["count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return Outcome.REFUSED
    try:
        rx = re.compile(pattern, re.M)
    except re.error:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    return Outcome.PASS if len(rx.findall(output)) == count else Outcome.FAIL


def _regex_absent(spec: dict, output: str) -> Outcome:
    """Trap-friendly (T): the `pattern` must NOT appear. The regex analogue of
    `absent_run`, for traps a token run cannot express -- e.g. "a WARN line that
    also contains the word error", "a filename containing a colon".

    Blank output is UNMEASURED, never PASS: silence must not satisfy a trap.
    """
    pattern = spec["pattern"]
    try:
        rx = re.compile(pattern, re.M)
    except re.error:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    return Outcome.FAIL if rx.search(output) else Outcome.PASS


def _regex_present(spec: dict, output: str) -> Outcome:
    """Recall (R) via regex: the `pattern` MUST appear. The inverse of
    `regex_absent`, for a required item whose surface form varies -- e.g. a number
    a model may write as "800ms" or "800 ms", which `contains_run` (fixed token
    run) cannot match across the space. Blank output is UNMEASURED, not FAIL."""
    pattern = spec["pattern"]
    try:
        rx = re.compile(pattern, re.M)
    except re.error:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    return Outcome.PASS if rx.search(output) else Outcome.FAIL


def _max_words(spec: dict, output: str) -> Outcome:
    """Structural (S) conciseness: at most `max_words` whitespace-separated words.
    Measures whether a 'tighten this' task was actually done -- an output that
    merely echoes the source keeps every required token but fails this. Blank is
    UNMEASURED, never PASS (zero words trivially satisfies any budget)."""
    n = spec["max_words"]
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return Outcome.REFUSED
    if _blank(output):
        return Outcome.UNMEASURED
    return Outcome.PASS if len(output.split()) <= n else Outcome.FAIL


ATOM_KINDS = {"contains_run": _contains_run, "absent_run": _absent_run,
              "line_limit": _line_limit, "count_equals": _count_equals,
              "regex_absent": _regex_absent, "regex_present": _regex_present,
              "max_words": _max_words}


def score_atom(atom: Atom, output: str) -> AtomResult:
    fn = ATOM_KINDS.get(atom.kind)
    if fn is None:
        return AtomResult(atom.id, atom.cls, Outcome.REFUSED)
    try:
        outcome = fn(atom.spec, output)
    except (KeyError, TypeError, ValueError):
        outcome = Outcome.REFUSED
    return AtomResult(atom.id, atom.cls, outcome)


def score_atoms(atoms: list[Atom], output: str) -> list[AtomResult]:
    return [score_atom(a, output) for a in atoms]
