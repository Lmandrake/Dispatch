"""Build the prompt a dispatched job is sent, in the shape the measurement used.

`router.run_job` takes a prompt and sends it verbatim, by design -- it is the
table-only half of the routing layer and reads no fixtures. But every number in the
table was measured against `cli._build_prompt`'s envelope: the material, a `---`
rule, then the fixture's instruction. A caller that hands `run_job` a file of
material and nothing else sends the model no instruction at all, and then judges
what comes back against evidence gathered under a different prompt.

So this is the piece that sits between a caller's material and dispatch. It is kept
out of `router.py` on purpose (that module must keep running with no suites
directory, including inside Cowork) and pinned by a test that composes every fixture
both ways and requires the results to be identical.
"""

from __future__ import annotations

import glob
import json
import pathlib

DEFAULT_SUITES = pathlib.Path(__file__).resolve().parents[1] / "suites"


def fixture_for_activity(activity: str,
                         suites_dir: pathlib.Path = DEFAULT_SUITES) -> dict | None:
    """The fixture whose `activity` field matches, or None.

    None is a real answer: the table covers a handful of the decomposition's
    activities, and a miss must stay a miss rather than resolving to the nearest
    thing -- routing unmeasured work through a measured job's instruction is how a
    verdict gets applied to a task it never described.
    """
    for p in sorted(glob.glob(f"{suites_dir}/**/*.json", recursive=True)):
        fixture = json.loads(pathlib.Path(p).read_text())
        if fixture.get("activity") == activity:
            return fixture
    return None


def compose(material: str | None, fixture: dict) -> str:
    """`<material>\\n\\n---\\n\\n<instruction>`, exactly as the sweep built it.

    `material=None` means "use the fixture's own input", which reproduces the
    measured prompt byte for byte -- that is what the identity test relies on.

    An EMPTY STRING is not None. It means the caller handed over an empty file, and
    falling back to the fixture's built-in input there would silently answer a
    different question and return something that looks entirely correct.
    """
    if material is not None and not material.strip():
        raise ValueError(
            "material is empty: refusing to fall back to the fixture's own input, "
            "which would answer a different question than the one asked")

    prompt = fixture["prompt"]
    if material is not None:
        return f"{material}\n\n---\n\n{prompt}"

    input_path = fixture.get("input_path")
    if input_path:
        content = pathlib.Path(input_path).expanduser().read_text()
        return f"{content}\n\n---\n\n{prompt}"
    inline = fixture.get("input")
    if inline:
        return f"{inline}\n\n---\n\n{prompt}"
    return prompt
