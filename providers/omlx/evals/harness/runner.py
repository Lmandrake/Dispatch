from evals.harness.atoms import Atom, score_atoms
from evals.harness.checkers import atoms_from_gold
from evals.harness.metrics import Trial


def atoms_for(fixture: dict) -> list[Atom]:
    """A fixture's atoms come from its own `atoms` array when it has one, and are
    derived from the legacy gold_recall spec only when it does not.

    Getting this backwards is silent and total: a fixture whose checker is not
    `gold_recall` has no `gold` key, so the legacy path returns [] and the run
    records an EMPTY atom vector. Most of the probe's tasks are in that category,
    so the sweep would spend every model call and store nothing for them -- and
    the legacy-path test would still be green.
    """
    if fixture.get("atoms"):
        return [Atom(id=a["id"], cls=a["cls"], kind=a["kind"], spec=a["spec"])
                for a in fixture["atoms"]]
    return atoms_from_gold(fixture)


def atom_row(fixture: dict, output: str, void: bool) -> dict[str, str]:
    """The per-trial atom vector as a flat {atom_id: outcome_value} map -- ids and
    outcome NAMES only, never a matched span or any output text, because this
    lands in a committed result file beside a private transcript.

    A VOID trial records no atoms rather than failures: finish_reason == length
    means the atoms were never fairly attempted, and recording them as FAIL would
    charge a model for hitting a budget ceiling.
    """
    if void:
        return {}
    return {r.atom_id: r.outcome.value
            for r in score_atoms(atoms_for(fixture), output)}


def _to_trial(resp: dict) -> Trial:
    t = resp.get("timing")
    if not isinstance(t, dict):
        raise ValueError(
            "response has no 'timing' dict: the client must inject "
            "client-measured ttft_s and total_s (see client contract)"
        )
    total = t.get("total_s")
    if not isinstance(total, (int, float)) or total <= 0:
        raise ValueError(f"response timing has invalid total_s={total!r}; must be a positive number")

    u = resp.get("usage", {})
    out = u.get("completion_tokens", 0) or 0
    return Trial(
        ttft_s=t.get("ttft_s", 0.0) or 0.0,
        tok_per_s=(out / total),
        total_s=total,
        prompt_tokens=u.get("prompt_tokens", 0),
        output_tokens=out,
        cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        finish_reason=resp["choices"][0]["finish_reason"],
    )


def run_trial(client, model: str, mode: str, prompt: str, budgets: dict) -> Trial:
    budget = budgets[mode]
    messages = [{"role": "user", "content": prompt}]
    resp = client.complete(model, messages, budget, mode == "think")
    trial = _to_trial(resp)
    if trial.void:
        resp = client.complete(model, messages, budget * 2, mode == "think")
        trial = _to_trial(resp)
    return trial
