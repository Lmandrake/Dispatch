# cap-sonnet-full-hard-2026-10-25

model Claude Sonnet 5.5, thinking medium, 45 runs, jobs 6, 2026-10-25T08:19:33-0700 to 2026-10-25T08:36:26-0700. Graded from runs.jsonl.

| task | claude-full | pi-full | omp-full |
|---|---|---|---|
| 11_multilayer_feature | 3/3 | 2/3 | 3/3 |
| 12_cache_race | 0/3 | 1/3 | 1/3 |
| 13_format_migration | 3/3 | 3/3 | 2/3 |
| 14_wrong_module_blame | 3/3 | 3/3 | 3/3 |
| 15_spec_interpreter | 1/3 | 1/3 | 2/3 |
| **total** | **10/15** | **10/15** | **11/15** |

Medians per run (all tasks):

| measure | claude-full | pi-full | omp-full |
|---|---|---|---|
| wall_s | 125.1 | 81.8 | 126.2 |
| cpu_s | 5.3 | 2.6 | 4.9 |
| peak_rss_mb | 453.8 | 274.9 | 614.4 |
| turns | 8 | 7 | 10 |
| tool_calls | 7 | 6 | 9 |
| out | 15834 | 12366 | 12732 |
| cache_read | 459183 | 297316 | 317429 |
| cache_write | 46290 | 59783 | 47774 |

Sum of wall_s per arm: claude-full 2035, pi-full 1227, omp-full 2189

Median wall_s per task:

| task | claude-full | pi-full | omp-full |
|---|---|---|---|
| 11_multilayer_feature | 125.1 | 81.8 | 126.2 |
| 12_cache_race | 57.2 | 36.3 | 62.2 |
| 13_format_migration | 258.7 | 155.5 | 261.6 |
| 14_wrong_module_blame | 23.2 | 17.7 | 32.0 |
| 15_spec_interpreter | 205.0 | 123.3 | 229.7 |

Tool calls, summed:

- claude-full: Bash 116, Read 3, Edit 1
- pi-full: bash 97
- omp-full: bash 128, read 5, glob 2

Failures:

- 12_cache_race pi-full r0: rc=0 timed_out=False pytest `1 failed, 33 passed in 2.95s` 
- 12_cache_race omp-full r0: rc=0 timed_out=False pytest `1 failed, 33 passed in 2.98s` 
- 12_cache_race claude-full r0: rc=0 timed_out=False pytest `1 failed, 33 passed in 1.12s` 
- 15_spec_interpreter pi-full r0: rc=0 timed_out=False pytest `1 failed, 278 passed in 0.59s` 
- 11_multilayer_feature pi-full r1: rc=0 timed_out=False pytest `1 failed, 65 passed in 0.32s` 
- 13_format_migration omp-full r0: rc=0 timed_out=False pytest `1 failed, 39 passed in 0.25s` 
- 15_spec_interpreter claude-full r0: rc=0 timed_out=False pytest `1 failed, 278 passed in 0.56s` 
- 12_cache_race pi-full r1: rc=0 timed_out=False pytest `2 failed, 32 passed in 3.06s` 
- 12_cache_race claude-full r1: rc=0 timed_out=False pytest `1 failed, 33 passed in 3.09s` 
- 15_spec_interpreter claude-full r1: rc=0 timed_out=False pytest `1 failed, 278 passed in 0.58s` 
- 12_cache_race omp-full r2: rc=0 timed_out=False pytest `1 failed, 33 passed in 3.25s` 
- 12_cache_race claude-full r2: rc=0 timed_out=False pytest `2 failed, 32 passed in 11.08s` 
- 15_spec_interpreter pi-full r2: rc=0 timed_out=False pytest `1 failed, 278 passed in 0.57s` 
- 15_spec_interpreter omp-full r2: rc=0 timed_out=False pytest `1 failed, 278 passed in 0.65s` 

Reading: with full config the hard-suite gap closes (Claude 10, Pi 10, OMP 11 of 15; stock was 10/13/9). Differences of one or two passes on 15 runs are noise. Pi stays fastest in wall time on every task. Task 12 (cache race) is the hardest for all three.
