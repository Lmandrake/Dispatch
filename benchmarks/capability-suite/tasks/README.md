# Capability task suite

Twenty tasks for comparing coding-agent harnesses on the same model. Tasks 01 to 10 are small, and every harness passes them. Tasks 11 to 15 are harder multi-step tasks, though Sonnet finishes them in 1 to 6 minutes. Tasks 16 to 20 are long-form successors to 11 to 15: codebases of 6,500 to 9,400 lines, multi-stage requirements and traps that need investigation, aimed at 15 to 25 minutes for a strong agent. Run them with `--timeout 2400`.

## Format

One directory per task, `bench/tasks/<name>/`:

- `prompt.txt`: the instruction given to the agent verbatim. The agent's cwd is a fresh copy of `repo/`.
- `repo/`: the starting project (Python 3.12 stdlib, plus pytest). Some include visible tests.
- `hidden/`: copied into the workdir root after the agent finishes, overwriting anything with the same name. Then
  `python3 -m pytest -q -p no:cacheprovider hidden_*.py` decides the result: exit 0 is a pass, anything else a fail.
  Hidden tests check the requested behaviour and that existing behaviour still works.
  `09_log_summary/hidden/hidden_truth.json` is the ground truth, recorded when the log was generated.
  `10_quadratic_perf/hidden/conftest.py` stops any test after 30 s, so an unfixed O(n^2) solution fails instead of hanging.
  `12_cache_race` and `15_spec_interpreter` also have a `hidden/conftest.py` with a wall-clock limit (60 s and 30 s per test).
  In 11 and 13 the prompt tells the agent to update visible tests whose expected output changes with the feature. The visible tests in 15 fail on the untouched stub, and two visible tests in 14 fail on purpose.
- `meta.json`: `category`, `what_it_probes`, `expected_minutes_for_human`.

| task | category |
|---|---|
| 01_pagination_offbyone | bugfix with a visible failing test |
| 02_cli_flag | feature across argparse and a library module |
| 03_rename_refactor | multi-file rename, including a string registry |
| 04_ttl_lru_cache | implement from a docstring spec |
| 05_order_dependent_state | order-dependent failures (shared mutable state) |
| 06_precise_edit_large_file | one edit in a 2000-line generated module (AST hashes guard the rest) |
| 07_override_chain | effective value set through constants, profile, ini and env layers |
| 08_noisy_output | 20,000-line log, 10 malformed records, one bad formatter |
| 09_log_summary | multi-format messy log parsed to a JSON schema |
| 10_quadratic_perf | O(n^2) to sort-and-sweep, with a time bound |
| 11_multilayer_feature | per-item tags threaded through every layer of a 2,600-line inventory app (models, two stores, file format v3 with v1/v2 compat, query language, CLI, exports, audit log) |
| 12_cache_race | stale prices blamed on TTL; really a lost invalidation, out-of-order warming, cache-key collisions and non-atomic stats, with no global lock allowed |
| 13_format_migration | binary log format v1 to v2 (UTF-8 strings, microsecond timestamps, per-block CRC, index): v1 reads and byte-exact v1 writes kept, plus migrate |
| 14_wrong_module_blame | visible failing test blames the report formatter; two independent upstream bugs (rate cache key, float summation) are the cause |
| 15_spec_interpreter | whole interpreter for a small language from a 450-line SPEC.md (exact rationals, closures, error model with positions, recursion limit) |
| 16_multilayer_feature_long | recurring issues threaded through a 6,500-line issue tracker (recurrence grammar in docs/RECURRENCE.md, spawn-on-close, schema v5 migration on SQLite and JSON backends, a stale agenda cache, rollback, permissions) |
| 17_job_queue_races | job queue (9,400 lines): "retry backoff is broken" ticket, really 14 independent bugs (lease/ack races, WAL replay order and torn tail, idempotency key folding, cron leap years, tenant-blind result cache, ...), several only in further tickets; plus fair per-tenant scheduling and a `doctor` WAL report |
| 18_format_migration_long | columnar time-series archive: byte-exact v3 format from a 390-line FORMAT_v3.md (delta/zigzag/dictionary/XOR encodings, chunk CRCs, footer index that range queries must use to skip decompression, nullable columns), v1/v2 kept byte-identical |
| 19_billing_misdirection | billing system (8,500 lines): finance blames renderer rounding; 16 upstream bugs incl. cross-module chains and two masking pairs, five reachable only through tickets plus docs; then rebill, a multi-period restatement and a month-end close with an audit pack, about 1,100 lines of new code from docs |
| 20_interpreter_extension | extend a working 6,800-line interpreter (tree walker plus bytecode VM with a peephole optimiser) per a 190-line SPEC_v2.md: try/catch/finally, match with guards, keyword/default arguments, new built-ins; all three engine configurations must agree |

## How verification was done (2026-10-23; tasks 11 to 15 on 2026-10-24; 16 to 20 on 2026-10-25)

For each task, the hidden tests were run in a temporary copy of the untouched `repo/`, and all of them failed.
A reference solution was written outside the repo, in `<agent-storage>/NewHarness/scratch/ref-solutions/<task>/`.
The hidden tests were then run against each reference solution, and all of them passed.
The script that did this is `<agent-storage>/NewHarness/scratch/verify.sh`.
The reference for 12_cache_race passed 6 runs in a row in the final check. The generators for tasks 06 to 09, 13 and 14 are in `<agent-storage>/NewHarness/scratch/gen/`.
The timing limits in tasks 04 and 10 were measured on the Laptop; slower hosts may need a looser limit.
Tasks 16 to 20 were verified the same way, with `verify.sh`. The reference for 17 passed 5 runs in a row. Generators and rebuild scripts are in `<agent-storage>/NewHarness/scratch/gen/`: `gen16.py`, `fix17.py` plus `stage2_17/`, `gen18.py`, `gen19_all.sh`.
Each of 16 to 20 has a `hidden/conftest.py` per-test wall-clock limit: 30 s for 16 and 18, 60 s for 17 and 19, 20 s for 20.
One smoke run per task (claude-stock, Sonnet, medium effort, `--timeout 2400`, 2026-10-25), final versions: 16 passed in 9.6 min, 17 passed in 7.0 min (13.1 min on an earlier run), 18 passed in 15.7 min, 19 passed in 8.1 min, and 20 timed out at 40 min with 111 of 180 failing. In 20 the agent's turns were few and very slow (5 to 18 minutes each, writing large patches), so it may need a longer timeout or a smaller spec.
