"""`skills/delegate-router/SKILL.md`: every number in it, recomputed.

🔴 CLAUDE.md: prose that STATES a fact about the data must be computed from the data.
Prose that *reasons* about the data can be fixed later; prose that states a fact goes
stale silently. Two generated captions in this repo drifted into being false because
nothing checked them.

A SKILL.md cannot compute anything — it is text a model reads. So the check lives here:
each figure the skill quotes is recomputed from the live corpus and compared. When
throughput is re-measured or the AA corpus refreshes, these go RED and name the line to
update, instead of the skill quietly lying to every session that loads it.

The tolerance is deliberately tight. A loose one would let a real drift through, and
the point is to be told, not to be reassured.
"""
import pathlib
import re

import pytest

from dispatchlib import prior as P

SKILL = (pathlib.Path(__file__).resolve().parents[1] / "skills"
         / "delegate-router" / "SKILL.md")
OUT_TOKENS = 400                     # the size the skill's cost figures are quoted at


@pytest.fixture(scope="module")
def text():
    assert SKILL.exists(), SKILL
    return SKILL.read_text()


@pytest.fixture(scope="module")
def local():
    tput = P._throughput()
    assert tput, "throughput.json is empty; this whole file would pass vacuously"
    return tput


# --- structure ---------------------------------------------------------------

def test_the_skill_has_only_name_and_description_in_its_frontmatter(text):
    """House style, matching `omlx-delegate` and `m365-mail-calendar`."""
    assert text.startswith("---\n")
    fm = text.split("---\n")[1]
    keys = {line.split(":", 1)[0] for line in fm.splitlines() if ":" in line
            and not line.startswith(" ")}
    assert keys == {"name", "description"}, keys


def test_the_skill_is_within_the_house_length(text):
    n = len(text.splitlines())
    assert 100 <= n <= 220, f"{n} lines; house style is 100-200"


def test_every_command_the_skill_tells_a_session_to_run_exists(text):
    """The failure this catches is a skill naming a subcommand that was renamed."""
    import subprocess
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    subs = set(re.findall(r"\./bin/delegate (\w+)", text))
    assert subs, "no commands quoted; the test would pass vacuously"
    help_text = subprocess.run(
        [sys.executable, str(root / "bin" / "delegate"), "--help"],
        capture_output=True, text=True).stdout
    for s in sorted(subs):
        assert s in help_text, f"the skill tells a session to run `delegate {s}`, " \
                               f"which argparse does not offer"


def test_every_file_path_the_skill_names_is_on_disk(text):
    paths = re.findall(r"`(~/dev/[A-Za-z0-9_./-]+|references/[A-Za-z0-9_.-]+)`", text)
    assert paths, "no paths quoted; the test would pass vacuously"
    root = pathlib.Path(__file__).resolve().parents[1]
    for p in sorted(set(paths)):
        # `references/` is the oMLX destination's corpus, in providers/omlx/.
        from dispatchlib.omlx import OMLX_REPO
        if p.startswith("~/dev/") and not p.startswith("~/dev/Dispatch/"):
            # A sibling repo checkout (e.g. one holding a guard hook). Checked only where that checkout exists.
            sibling = pathlib.Path(p).expanduser().parents[len(pathlib.Path(p).parts) - 4]
            if not sibling.is_dir():
                continue
        full = (pathlib.Path(p).expanduser() if p.startswith("~")
                else OMLX_REPO / p)
        assert full.exists(), f"{p} does not exist"


# --- the numbers -------------------------------------------------------------

def _quoted_floats(text, pattern):
    m = re.search(pattern, text)
    assert m, f"the skill no longer contains {pattern!r}; update this test with it"
    return [float(g) for g in m.groups()]


def test_the_quoted_throughput_figures_still_match_the_measurement(text, local):
    """`15.3 tok/s` and `78.8` are in the skill's speed argument."""
    slow = local["Qwen3.8-27B-8bit"]["warm_tok_per_s"]
    fast = local["Qwen3.5-9B-MLX-4bit"]["warm_tok_per_s"]
    assert f"{slow} tok/s" in text, (
        f"the skill quotes a throughput for Qwen3.8-27B-8bit that is not {slow}; "
        f"re-measurement has moved it")
    assert str(fast) in text, f"Qwen3.5-9B-MLX-4bit now measures {fast}"


def test_the_quoted_speed_ratio_is_still_about_five(text, local):
    rates = [v["warm_tok_per_s"] for v in local.values() if v.get("warm_tok_per_s")]
    ratio = max(rates) / min(rates)
    claimed = _quoted_floats(text, r"anti-correlated across this\s+fleet by about (\d+)")
    assert abs(ratio - claimed[0]) < 1.0, (
        f"the skill claims about {claimed[0]}x and the fleet now spans {ratio:.1f}x")


def test_the_quoted_local_cost_still_matches(text, local):
    """🔴 The figure that makes the skill's cost argument. If hardware price, duty
    cycle, power band or throughput move, this is what says so."""
    p = P.DestinationPrior("omlx/Qwen3.8-27B-8bit", P.LOCAL,
                           tok_per_s=local["Qwen3.8-27B-8bit"]["warm_tok_per_s"])
    usd = p.usd_for(OUT_TOKENS)
    lo, hi = _quoted_floats(text, r"costs \*\*\$([\d.]+)–([\d.]+)\*\*")
    assert abs(usd["lo"] - lo) < 0.0002, f"local low is now {usd['lo']:.4f}"
    assert abs(usd["hi"] - hi) < 0.0002, f"local high is now {usd['hi']:.4f}"


def test_the_quoted_gateway_cost_still_matches(text):
    served = sorted(P.GATEWAY_FAMILY_SUFFIXES)
    sonnet = next(s for s in P.sanctioned_priors(served) if "sonnet-5" in s.destination)
    usd = sonnet.usd_for(OUT_TOKENS)
    claimed = _quoted_floats(text, r"gateway costs \$([\d.]+)\*\*")
    assert abs(usd["lo"] - claimed[0]) < 0.0002, (
        f"Sonnet 5 at {OUT_TOKENS} tokens is now ${usd['lo']:.4f}")


def test_the_cost_inversion_the_skill_asserts_is_still_true(text, local):
    """The skill says the gateway is cheaper at this size. That is a CLAIM about the
    data, so it gets checked -- and if it stops being true the skill must change its
    argument, not its tolerance."""
    assert "cheaper" in text
    loc = P.DestinationPrior("omlx/x", P.LOCAL,
                             tok_per_s=local["Qwen3.8-27B-8bit"]["warm_tok_per_s"]
                             ).usd_for(OUT_TOKENS)
    sonnet = next(s for s in P.sanctioned_priors(sorted(P.GATEWAY_FAMILY_SUFFIXES))
                  if "sonnet-5" in s.destination).usd_for(OUT_TOKENS)
    assert sonnet["lo"] < loc["lo"], (
        "the skill tells sessions the gateway is cheaper at 400 output tokens; it is "
        "no longer true and the skill's cost paragraph is now wrong")


def test_the_skill_quotes_no_tier_verdict_or_score(text):
    """Verdicts move whenever the corpus refreshes, and nothing recomputes a skill.
    The skill may name the TIERS as a vocabulary; it must not say which model has
    which, or quote a percentile."""
    assert not re.search(r"\b\d+(?:st|nd|rd|th) percentile\b", text)
    for bad in re.findall(r"(DELEGATE|VERIFY|DO NOT) for \w+", text):
        pytest.fail(f"the skill assigns a tier: {bad!r}")
