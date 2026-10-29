# Harder suite (tasks 11-15), Sonnet 5.5, stock arms, 2026-10-24

Run data is not published; the table below is the record. n=3 per cell, thinking medium, jobs 6, 40-minute limit per run. The arms are the same stock and bare arms as on 10-23.

| task | claude-stock | pi-bare-stdin | omp-bare |
|---|---|---|---|
| 11_multilayer_feature | 3/3 | 3/3 | 3/3 |
| 12_cache_race | 2/3 | 2/3 | 0/3 |
| 13_format_migration | 2/3 | 3/3 | 3/3 |
| 14_wrong_module_blame | 3/3 | 3/3 | 3/3 |
| 15_spec_interpreter | 0/3 | 2/3 | 0/3 |
| **total** | **10/15** | **13/15** | **9/15** |

| per run, median | claude-stock | pi-bare-stdin | omp-bare |
|---|---|---|---|
| wall s | 119 | 75 | 186 |
| context tokens (in + cache) | 246k | 160k | 346k |
| peak RSS MB | 333 | 190 | 526 |

The total wall time was 2234 s for Claude, 1338 s for Pi and 2606 s for OMP. No run timed out, and only one crashed (OMP).

- **The suite is off the ceiling, but the tasks are shorter than designed.** The median run took 1-4 minutes, not 20 or more. That is still enough to separate the harnesses a little.
- **Most of the difference comes from one trap in task 15.** 7 of the 8 failures on task 15 are the same hidden case: `[1, 2][nil:]` must raise `TallyTypeError`, as `SPEC.md` (lines 264-265) says. The agents treated `nil` as an omitted bound, as Python does. Pi got it right 2 times in 3 and the others 0 times in 3. **The headline "Pi 13, Claude 10" is therefore mostly one edge case.** With n=3 it is not a significant gap.
- **Task 12 (concurrency) is the one real separator.** OMP got 0 of 3. One OMP run crashed. The other two kept the out-of-order-writer bug and the server-consistency bug. Claude and Pi each missed it once: Claude missed the whole invalidation and load group, and Pi missed one test.
- **Pi used the least time and context on hard tasks too.** Its lead in context fell from 8x on short tasks to about 1.5x here. On long tasks the code being read dominates, not the system prompt.
- **Both specs were checked.** The single failing test in task 13 (`block_size=0` with `version=1` must be accepted) is in `docs/FORMAT_v2.md` lines 132-133. The `nil` slice case is in `SPEC.md`. Neither test is unfair.

Next: make the tasks longer (the 20-minute target was missed), and run with n of at least 5 before claiming any ordering.
