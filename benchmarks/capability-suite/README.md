# Capability suite (protected)

Nineteen coding tasks, easy (01-10), hard (11-15) and long (16-19, 7-16 min each), for comparing agent harnesses or models on
equal terms. Built and first run in `~/dev/Dispatch/harnesses` (was NewHarness) (2026-10-23/24); results and method live
there (`docs/CAPABILITY-*.md`, `docs/METHOD.md`). The runner is `~/dev/Dispatch/harnesses/bench/capability_bench.py`.

- `tasks/<name>/`: `prompt.txt` (given verbatim), `repo/` (starting project), `hidden/` (grading
  tests copied in after the agent exits), `meta.json`. Task list and format: `tasks/README.md`.
- `ref-solutions/<name>/`: a passing reference for each task. **Never show these to an agent under test.**
  Not included in the public release (so they cannot leak into a model's training data or an agent's
  context); there `verify.sh` checks only the failing start state, and the frozen test pins what ships.
- `generators/`: scripts that produced the generated inputs of tasks 06-09, 13, 14.
- `verify.sh <task>...`: hidden tests must fail on `repo/` and pass on the reference.

## Protection

This suite is frozen. `MANIFEST.sha256` pins every file, and `tests/test_capability_suite_frozen.py`
fails if any file is changed, added or removed. Do not edit a task to make an agent pass, and do
not regenerate the manifest to make that test pass. A new or changed task gets a new number (16+),
the owner's say-so, then `verify.sh` on it, then a manifest refresh in its own commit:
`find tasks ref-solutions generators verify.sh -type f | LC_ALL=C sort | xargs shasum -a 256 > MANIFEST.sha256`

Task 20 (interpreter extension) is listed in `tasks/README.md` but deliberately not frozen here: it timed out at 40 min twice and the owner dropped it (2026-10-25).
