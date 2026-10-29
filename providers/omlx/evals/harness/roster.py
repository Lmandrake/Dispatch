"""Discovery: what models exist right now, and how the table has drifted from them.

This is the stage the pipeline was missing. Measurement scores models and the
table ranks them, but nothing established what the roster actually IS -- so
`routing-table.json` shipped `roster_hash: null` and empty `untested`/`missing`,
and a skill reading it could not tell a current table from a stale one.

Two rules carry over from the design and are not negotiable here:

1. **Egress is derived, never hand-labeled**, via egress.classify. An
   unrecognized host resolves to `remote`, and absent config yields NO
   sanctioned suffixes -- broken config must narrow access, never widen it.
   This is the one place where being wrong is irreversible.
2. **A null hash means "not computed", not "matches".** check_drift reports
   `hash_mismatch: None` against a table that carries no hash, because
   reporting False would claim a comparison that never ran.
"""
import datetime
import hashlib

from evals.harness.egress import classify

# Models that support an extended-thinking request. sanctioned.py attaches a
# thinking block only for claude ids, so a 'think' run against anything else
# silently runs nothink -- advertising think for those would let the table rank
# a mode that never actually happened.
_THINKING_SUBSTRING = "claude"

BOTH_MODES = ["nothink", "think"]
NOTHINK_ONLY = ["nothink"]

# Days after which a table is treated as stale (design §5).
STALE_AFTER_DAYS = 30


def roster_hash(refs: list[str]) -> str:
    """Fingerprint of a roster, over its sorted refs.

    Order-independent so re-running discovery cannot produce a spurious
    mismatch, and prefixed with the algorithm so a future change is visible in
    the artifact rather than silently reinterpreted.
    """
    joined = "\n".join(sorted(refs))
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _modes(target: str, model_id: str) -> list[str]:
    # A private enterprise endpoint's models are assumed to toggle reasoning the
    # same way oMLX's do (chat_template_kwargs.enable_thinking), unrelated to the
    # claude-only extended-thinking param a gateway uses -- so they get the same
    # both-modes treatment as local models, not the gateway's claude-substring
    # heuristic below.
    if target in ("omlx", "enterprise"):
        return list(BOTH_MODES)
    if _THINKING_SUBSTRING in model_id.lower():
        return list(BOTH_MODES)
    return list(NOTHINK_ONLY)


def build_roster(entries: list[dict], generated_at: str,
                 sanctioned_suffixes: list[str] | None = None) -> dict:
    """Turn discovered models into the roster artifact.

    Each entry needs `id`, `target`, `endpoint`, and optionally `context`.
    Discovery (the network calls) lives in main(); this stays pure so the
    derivation rules are testable without a live server.
    """
    models = []
    for e in entries:
        target, model_id = e["target"], e["id"]
        endpoint = e.get("endpoint") or ""
        models.append({
            "ref": f"{target}/{model_id}",
            "target": target,
            "endpoint": endpoint,
            "egress": classify(target, endpoint, sanctioned_suffixes),
            "modes": _modes(target, model_id),
            "context": e.get("context"),
        })
    models.sort(key=lambda m: m["ref"])
    return {
        "generated_at": generated_at,
        "roster_hash": roster_hash([m["ref"] for m in models]),
        "models": models,
    }


def _ranked_refs(table: dict) -> set[str]:
    return {
        row.get("model_ref")
        for node in (table.get("activities") or {}).values()
        for row in (node.get("ranked") or [])
        if row.get("model_ref")
    }


def _age_days(table_generated_at: str | None, now: str) -> int | None:
    if not table_generated_at:
        return None
    try:
        then = datetime.datetime.fromisoformat(table_generated_at.replace("Z", "+00:00"))
        current = datetime.datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (current - then).days


def check_drift(roster: dict, table: dict) -> dict:
    """Compare a live roster against a generated table.

    `untested` is present-but-unranked: a model exists and nothing measured it.
    `missing` is ranked-but-absent: the table recommends something the roster no
    longer has, which a consumer must never select.
    """
    live = {m["ref"] for m in roster.get("models") or []}
    ranked = _ranked_refs(table)

    table_hash = table.get("roster_hash")
    mismatch = None if table_hash is None else table_hash != roster.get("roster_hash")

    age = _age_days(table.get("generated_at"), roster.get("generated_at") or "")
    untested = sorted(live - ranked)
    missing = sorted(ranked - live)

    return {
        "untested": untested,
        "missing": missing,
        "hash_mismatch": mismatch,
        "age_days": age,
        "stale": bool(age is not None and age > STALE_AFTER_DAYS),
        # Clean means a consumer can trust the table as current. An unknown
        # hash is not clean: it is an unverified claim.
        "clean": not untested and not missing and mismatch is False,
    }


# --- discovery (the network half) --------------------------------------------
# Kept below the pure functions and out of them: everything above is testable
# without a live server, and the roster's derivation rules are where the
# irreversible mistake lives.

def discover_omlx(endpoint: str, api_key: str | None,
                  timeout: float = 10.0) -> list[dict]:
    """Models resident on the local oMLX server."""
    import json
    import urllib.request

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(f"{endpoint}/models", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return [
        {"id": m["id"], "target": "omlx", "endpoint": endpoint,
         "context": m.get("max_model_len")}
        for m in data.get("data") or []
        if m.get("id")
    ]


# Gateway aliases: the same model can be published several times behind
# alias suffixes. Ranking each alias separately would multiply one
# model into many rows that are not independent measurements.
_ALIAS_SUFFIXES = ("-load-balanced", "-lb-")


def _is_alias(model_id: str) -> bool:
    return any(s in model_id for s in _ALIAS_SUFFIXES)


def is_chat_model(info: dict) -> bool:
    """Whether a gateway model can serve a completion at all.

    The gateway reports `mode` itself ('chat' or 'embedding'), so this reads
    metadata rather than inferring modality from the id -- an embedding model
    cannot answer a fixture, and listing one as 'untested' would invite someone
    to go measure something that can never be measured.

    An ABSENT mode counts as usable. Unknown modality is not a reason to hide a
    model: the cost of including a wrong one is noise in a list, while the cost
    of excluding a right one is a model that silently never gets measured.
    """
    mode = info.get("mode")
    return mode is None or mode == "chat"


def discover_sanctioned(timeout: float = 30.0) -> list[dict]:
    """Models the sanctioned gateway publishes, aliases collapsed.

    Reads the endpoint and auth the same way the eval client does, so discovery
    cannot drift from what a measurement run would actually reach.
    """
    import json
    import urllib.request

    from evals.harness.sanctioned import SanctionedClient

    client = SanctionedClient()
    base = client.base_url()
    req = urllib.request.Request(
        f"{base}/model/info",
        headers={"Authorization": f"Bearer {client._auth_token()}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())

    seen: dict[str, dict] = {}
    for m in data.get("data") or []:
        model_id = m.get("model_name")
        if not model_id or _is_alias(model_id):
            continue
        info = m.get("model_info") or {}
        if not is_chat_model(info):
            continue
        seen.setdefault(model_id, {
            "id": model_id, "target": "sanctioned", "endpoint": base,
            "context": info.get("max_input_tokens"),
        })
    return list(seen.values())


def discover_enterprise(endpoint: str, api_key: str | None,
                     timeout: float = 10.0) -> list[dict]:
    """Models a private enterprise endpoint publishes (via a private plugin). Same
    OpenAI-compatible /models shape as discover_omlx, just a different remote endpoint."""
    import json
    import urllib.request

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(f"{endpoint}/models", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return [
        {"id": m["id"], "target": "enterprise", "endpoint": endpoint,
         "context": m.get("max_model_len")}
        for m in data.get("data") or []
        if m.get("id")
    ]


def main() -> int:
    import argparse
    import json
    import pathlib
    import sys

    from evals.harness.egress import load_sanctioned

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="routing/roster.json")
    ap.add_argument("--table", default="routing/routing-table.json")
    ap.add_argument("--omlx-endpoint", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--skip-sanctioned", action="store_true",
                    help="Discover local models only; skip the gateway call.")
    ap.add_argument("--skip-enterprise", action="store_true",
                    help="Skip the private enterprise-endpoint discovery call.")
    ap.add_argument("--check", action="store_true",
                    help="Compare the live roster against the table and report "
                         "drift. Exits non-zero when drift is found.")
    args = ap.parse_args()

    entries: list[dict] = []
    try:
        key = None
        settings = pathlib.Path.home() / ".omlx" / "settings.json"
        if settings.exists():
            key = (json.loads(settings.read_text()).get("auth") or {}).get("api_key")
        entries += discover_omlx(args.omlx_endpoint, key)
    except Exception as e:
        print(f"warning: oMLX discovery failed ({type(e).__name__}: {e}); "
              f"local models absent from this roster", file=sys.stderr)

    if not args.skip_sanctioned:
        try:
            entries += discover_sanctioned()
        except Exception as e:
            print(f"warning: sanctioned discovery failed ({type(e).__name__}: {e}); "
                  f"gateway models absent from this roster", file=sys.stderr)

    if not args.skip_enterprise:
        try:
            from evals.harness.enterprise_plugin import DEFAULT_BASE_URL, DEFAULT_KEY_PATH, _load_key
            entries += discover_enterprise(DEFAULT_BASE_URL, _load_key(DEFAULT_KEY_PATH))
        except Exception as e:
            print(f"warning: enterprise-endpoint discovery failed (private plugin absent or unconfigured) ({type(e).__name__}: {e}); "
                  f"enterprise-endpoint models absent from this roster", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    roster = build_roster(entries, now, load_sanctioned())

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(roster, indent=2) + "\n")

    by_egress: dict[str, int] = {}
    for m in roster["models"]:
        by_egress[m["egress"]] = by_egress.get(m["egress"], 0) + 1
    summary = ", ".join(f"{n} {e}" for e, n in sorted(by_egress.items()))
    print(f"{out}: {len(roster['models'])} models ({summary or 'none'})")
    print(f"  roster_hash {roster['roster_hash']}")

    if not args.check:
        return 0

    table_path = pathlib.Path(args.table)
    if not table_path.exists():
        print(f"{table_path} does not exist: nothing to compare against.",
              file=sys.stderr)
        return 1
    drift = check_drift(roster, json.loads(table_path.read_text()))

    print(f"\ndrift vs {table_path}:")
    print(f"  untested (present, never measured): {len(drift['untested'])}")
    for ref in drift["untested"]:
        print(f"    {ref}")
    print(f"  missing (ranked, no longer present): {len(drift['missing'])}")
    for ref in drift["missing"]:
        print(f"    {ref}")
    mismatch = drift["hash_mismatch"]
    print("  roster_hash: " + (
        "unknown -- the table carries no hash, so nothing was compared"
        if mismatch is None else
        "MISMATCH -- the roster changed since the table was generated"
        if mismatch else "matches"))
    age = drift["age_days"]
    print(f"  age: {'unknown' if age is None else f'{age} days'}"
          f"{' (STALE)' if drift['stale'] else ''}")

    if drift["clean"]:
        print("\nclean: every present model is ranked and the hash matches.")
        return 0
    print("\nDRIFT: a model in `missing` must never be selected, and the table "
          "cannot be trusted as current until it is regenerated.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
