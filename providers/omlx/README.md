# oMLX local destination

The local-model destination's code and evidence, re-homed from DispatchOpenCode
(2026-10-26, at its commit 13fd02d) so Dispatch runs from a bare clone.

- `evals/harness/` the published-evidence ranking (`refer`), the served-model probe
  (`router`), the cost map (`costmap`) and the client/roster modules they import.
- `references/` the published-benchmark corpus (see `references/README.md`).
- `routing/throughput.json` measured local throughput; `routing/routing-table.json` the
  retired sweep table, shown on request only.
- `evals/suites/`, `evals/fixtures/` the measured job fixtures the skill table cites.
- `bin/route`, `bin/roster`, `bin/refer` the destination's own commands.

The sweep harness, exams and charts stayed in DispatchOpenCode's archive; only what the
router imports or the skill cites came here.

Tests: `cd providers/omlx && python3 -m pytest -q evals/harness/tests`.
