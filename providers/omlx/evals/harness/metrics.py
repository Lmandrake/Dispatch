from dataclasses import dataclass, field


@dataclass
class Trial:
    ttft_s: float
    tok_per_s: float
    total_s: float
    prompt_tokens: int
    output_tokens: int
    cached_tokens: int
    finish_reason: str
    void: bool = field(init=False)

    def __post_init__(self) -> None:
        self.void = self.finish_reason == "length"


def net_token_benefit(baseline_tokens: int, prompt_tokens: int,
                      returned_tokens: int, verification_tokens: int) -> int:
    return baseline_tokens - (prompt_tokens + returned_tokens + verification_tokens)


def wilson_ci(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Behaves at small n and at proportions near 0 or 1,
    where the naive normal approximation does not."""
    if n == 0:
        return (0.0, 1.0)
    p = passes / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z / d) * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (max(0.0, centre - half), min(1.0, centre + half))


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[i]


MECHANICAL = "mechanical"

# Fewest measured trap-runs below which a fabrication RATE is not a number worth
# pricing anything with. A model that hedges or truncates yields few gradable
# runs, and one failure in two observations is not an estimate. Below this the
# rate is REFUSED (None), which propagates to delegable=None, not to a clean 0.
MIN_GRADED_RUNS_FOR_RATE = 8


def fabrication_rate(per_trial: list[int | None]) -> tuple[float | None, int]:
    """Fraction of GRADED runs that fabricated at least once, and how many were
    graded.

    Run-level, not atom-level, and that distinction is the whole point. The
    decision it feeds is "must a human re-read the whole output", which is
    triggered by *any* fabrication in a run -- so the per-atom rate would
    understate it by roughly the trap count, and would also make the number
    depend on how many traps the instrument happens to declare.

    `None` entries are ungraded (or void) and are excluded from both numerator
    and denominator. Returns (None, n) when fewer than
    MIN_GRADED_RUNS_FOR_RATE runs were graded: "too few to say" must never
    render as "measured zero", which is the defect the whole fabrication line of
    work exists to remove.
    """
    graded = [c for c in per_trial if c is not None]
    if len(graded) < MIN_GRADED_RUNS_FOR_RATE:
        return (None, len(graded))
    return (sum(1 for c in graded if c > 0) / len(graded), len(graded))


def verification_tokens(kind: str | None, prompt_tokens: int,
                        output_tokens: int,
                        fabrication_rate_est: float | None = None) -> int:
    """Tokens needed to CHECK a delegated result, derived from the activity kind.

    This is the project's central claim made arithmetic. A *mechanical* activity
    is decided by a code checker, so verification is free. A *judgment* activity
    can only be checked by re-reading the source and the output, so verification
    costs about what the delegation itself consumed -- which is why judgment work
    must beat roughly twice its own cost to be worth delegating at all.

    An unrecognized or missing kind is treated as judgment. That fails closed:
    if we cannot tell whether a checker can decide the result, we assume a human
    must. Understating delegation's benefit is recoverable; overstating it means
    shipping work nobody actually verified.

    `fabrication_rate_est` makes the "mechanical is free" claim EMPIRICAL rather
    than asserted. A code checker can decide whether the required items are
    present; it cannot decide whether an item that is present was invented. So a
    mechanical activity is only free to verify for a model that does not
    fabricate -- and for one that does, a human must re-read the output, at
    roughly the cost of the delegation itself, weighted by how often it happens.

    This is what replaced a hard gate at `fabrication_count > 0`. That gate was a
    cliff at zero: under any continuous estimate a single fabrication in hundreds
    of observations disqualified a model outright, which is the same defect as the
    `pass_rate == 1.0` rule this project already reverted once. Pricing beats
    gating because it lets a model that fabricates rarely still win on economics
    if it is cheap enough, while a model that fabricates often cannot.

    A rate of None means unmeasured and adds nothing -- the caller is responsible
    for refusing to certify delegability in that case (see `delegable_from`),
    because silently adding zero here would price an unmeasured model as clean.
    """
    base = 0 if kind == MECHANICAL else prompt_tokens + output_tokens
    if not fabrication_rate_est:
        return base
    reread = prompt_tokens + output_tokens
    return int(round(base + fabrication_rate_est * reread))


# Fewest expected attempts we will babysit. This is an OPERATIONAL floor, not an
# economic one: the token arithmetic below cannot express wall-clock or round
# trips, and at five tries you are supervising the model rather than delegating
# to it. Kept separate and named so it is not mistaken for part of the economics.
MAX_EXPECTED_ATTEMPTS = 5.0
MIN_PASS_RATE = 1.0 / MAX_EXPECTED_ATTEMPTS


def expected_tokens_to_success(prompt_tokens: int, output_tokens: int,
                               verification_tokens: int,
                               pass_rate: float | None) -> float | None:
    """Tokens to obtain ONE acceptable answer, retrying failures.

    Each attempt costs its prompt, its output, and its verification. A failure
    is detected and retried, so the expected number of attempts is 1/pass_rate
    and the expected cost scales with it.

    A zero pass rate returns infinity rather than a small number. A model that
    never succeeds is cheap per attempt precisely because it does no useful
    work, and any finite figure would make that look attractive.
    """
    if pass_rate is None:
        return None
    per_attempt = prompt_tokens + output_tokens + verification_tokens
    if pass_rate <= 0:
        return float("inf")
    return per_attempt / pass_rate


def delegable_from(net: int | None, pass_rate: float | None,
                   fabrication_count: int, graded: bool,
                   expected_tokens: float | None = None,
                   baseline_tokens: int | None = None,
                   fabrication_matters: bool = True) -> bool | None:
    """Whether delegating this work costs less than doing it yourself.

    The test is economic, not a pass-rate cliff. An earlier version required
    `pass_rate == 1.0`, which is backwards for MECHANICAL work: mechanical is
    *defined* as "a code checker can decide it", so a failure there is free to
    notice and cheap to retry. Demanding perfection where being wrong is
    cheapest to catch rejected genuinely useful models -- a local 4-bit MoE at
    0.90 with the best token economy of any model measured was called
    undelegable, which is what prompted this rewrite.

    Three independent gates:

    1. **Economics.** Expected tokens to one good answer, retries included,
       must beat the baseline. This subsumes the old `net > 0` test while
       accounting for the cost of redoing failures, so a low pass rate must be
       paid for with a proportionally larger token advantage.
    2. **Operational sanity.** `MIN_PASS_RATE` -- see its comment. Cheap tries
       do not make ten round trips acceptable.
    3. **Fabrication**, priced rather than gated, and only where the fixture
       says it matters. `fabrication_matters` comes from the fixture's own
       `fabrication_is_disqualifying` flag.

       This gate USED TO read `if fabrication_count > 0: return False` -- a cliff
       at zero. With hundreds of graded observations per model, one slip
       disqualified outright, which is structurally the same mistake as the
       `pass_rate == 1.0` rule reverted earlier: it demanded perfection on the
       axis where being wrong is cheapest to notice. What remains here is only
       the *prerequisite* (an ungraded run cannot be certified); the fabrication
       signal itself now flows through `verification_tokens`, where a model that
       fabricates pays for the re-read its output forces.

       A model that fabricates on EVERY graded run is still refused, because a
       rate of 1.0 makes verification cost a full re-read every time and the
       economics cannot survive that -- but it is refused by arithmetic, not by
       fiat.

    Returns None for unknown, which is never interchangeable with False for
    measured-and-refused.
    """
    if pass_rate is None:
        return None
    # Grading remains a PREREQUISITE where fabrication matters: a run that was
    # never checked cannot be certified. That is not the same as the deleted
    # cliff, which refused a model for a single measured occurrence.
    if fabrication_matters and not graded:
        return None
    if pass_rate < MIN_PASS_RATE:
        return False
    if expected_tokens is None or baseline_tokens is None:
        # Fall back to the single-attempt figure when a caller has not supplied
        # the retry-aware inputs. Still never claims delegability without one.
        return None if net is None else net > 0
    return expected_tokens < baseline_tokens


def aggregate(trials: list["Trial"], passes: int,
              fabrications: list[int] | None = None,
              kind: str | None = None,
              baseline_tokens: int | None = None,
              fabrication_matters: bool = True) -> dict:
    valid = [t for t in trials if not t.void]
    n = len(valid)
    lo, hi = wilson_ci(passes, n)
    prompt_med = _pct([t.prompt_tokens for t in valid], 0.5)
    output_med = _pct([t.output_tokens for t in valid], 0.5)
    # A NON-EMPTY list is the grader signal. `None` means no grader ran, and so
    # does `[]`: cli._run_model_mode accumulates one entry per graded trial, so
    # an empty list is a run where grading never actually happened -- every
    # trial voided, or round-robin never selected the graded fixture. A
    # zero-filled list like [0, 0, 0] is the real "graded and found nothing".
    # Reading `[]` as graded-and-clean is the same "unknown reads as clean"
    # defect this grading exists to remove.
    graded = bool(fabrications)
    # Still a max, not a mean: one fabrication in twenty runs is a fabricating
    # model, and that is the right summary for a yes/no "did this ever happen".
    # But a max cannot price anything, which is why the RATE is computed too.
    fabrication_count = max(fabrications) if fabrications else 0
    fab_rate, fab_runs = fabrication_rate(list(fabrications or []))

    # Computed AFTER the rate, because it now depends on it. The rate is passed
    # only where the fixture declares fabrication disqualifying: on a fixture
    # where a fabricated item is simply a wrong answer the checker catches, it
    # does not force a human re-read and must not be billed as if it did.
    verify = verification_tokens(kind, int(prompt_med), int(output_med),
                                 fabrication_rate_est=(
                                     fab_rate if fabrication_matters else None))

    # None means "unknown". With zero valid trials there is no denominator and
    # nothing was measured; 0.0 would claim a measured total failure and let a
    # never-measured model enter a ranking as if it had failed every trial.
    # This is the same None-is-not-zero rule as baseline_tokens below.
    pass_rate: float | None = passes / n if n else None

    if baseline_tokens is None:
        # None means "unknown". Zero would claim a measured break-even.
        net: int | None = None
    else:
        net = net_token_benefit(baseline_tokens, int(prompt_med),
                               int(output_med), verify)
    # Retry-aware: what it costs to get ONE good answer, not one attempt. A
    # mechanical failure is free to notice, so redoing it is the honest cost
    # model -- see delegable_from for why a pass-rate cliff was wrong here.
    expected = expected_tokens_to_success(int(prompt_med), int(output_med),
                                          verify, pass_rate)
    delegable = delegable_from(net, pass_rate, fabrication_count, graded,
                               expected_tokens=expected,
                               baseline_tokens=baseline_tokens,
                               fabrication_matters=fabrication_matters)

    return {
        "n_trials": n,
        "indicative_only": n < 3,
        "void_rate": (len(trials) - n) / len(trials) if trials else 0.0,
        "tok_per_s_p50": _pct([t.tok_per_s for t in valid], 0.5),
        "tok_per_s_p95": _pct([t.tok_per_s for t in valid], 0.95),
        "ttft_p50": _pct([t.ttft_s for t in valid], 0.5),
        "ttft_p95": _pct([t.ttft_s for t in valid], 0.95),
        "total_s_p50": _pct([t.total_s for t in valid], 0.5),
        "total_s_max": max([t.total_s for t in valid], default=0.0),
        "pass_rate": pass_rate,
        "pass_rate_ci_low": lo,
        "pass_rate_ci_high": hi,
        # max, never mean: one fabrication in five runs is a fabricating model
        "fabrication_count": fabrication_count,
        "prompt_tokens_median": prompt_med,
        "output_tokens_median": output_med,
        "cached_tokens_max": max([t.cached_tokens for t in valid], default=0),
        "output_tokens_total": sum(t.output_tokens for t in valid),
        "kind": kind,
        "verification_tokens": verify,
        # The rate and its denominator travel together. A rate without the number
        # of runs behind it invites reading 0.0 from three observations as clean.
        # None means too few graded runs to say (see MIN_GRADED_RUNS_FOR_RATE).
        "fabrication_rate": fab_rate,
        "fabrication_runs_graded": fab_runs,
        "baseline_tokens": baseline_tokens,
        "net_token_benefit": net,
        # Retry-aware cost of one good answer. net_token_benefit is the
        # single-attempt figure and is kept for continuity; this is the one
        # the delegability test actually uses.
        "expected_tokens_to_success": expected,
        "delegable": delegable,
    }
