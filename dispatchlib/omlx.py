"""The oMLX destination's code and evidence, in `providers/omlx/`.

The router ranks local models from the `refer` corpus, the served-model probe
(`router`) and the cost map, and reads the measured `routing/throughput.json` and
`references/`. They were re-homed here from an earlier project so a clone of Dispatch runs with nothing beside it.

`$DISPATCH_OMLX` overrides the location (a test or a machine pointing at a newer
measurement checkout). A missing tree raises by name on first use; nothing falls back
silently.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import sys

OMLX_REPO = (pathlib.Path(os.path.expanduser(os.environ["DISPATCH_OMLX"]))
             if os.environ.get("DISPATCH_OMLX")
             else pathlib.Path(__file__).resolve().parents[1] / "providers" / "omlx")


def harness(name: str):
    """`evals.harness.<name>` from the oMLX provider tree."""
    if not (OMLX_REPO / "evals" / "harness" / f"{name}.py").exists():
        raise ModuleNotFoundError(
            f"evals.harness.{name} not found under {OMLX_REPO}: the oMLX destination "
            f"lives in Dispatch's providers/omlx/; restore it, or set $DISPATCH_OMLX")
    if str(OMLX_REPO) not in sys.path:
        sys.path.append(str(OMLX_REPO))
    return importlib.import_module(f"evals.harness.{name}")
