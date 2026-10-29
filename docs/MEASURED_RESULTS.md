# Measured results: summary tables

The figures quoted in the README, with the method in one line each. Per-run data and
transcripts are not published; these tables are the record. Directions matter more than
the last digit: n is small throughout and every interval is stated where one exists.

## Second review pass (code review)

42 real escaped bugs, 14 snapshots, 7 repos, 3 runs per shape, scoped packets, Sonnet judge,
bootstrap intervals.

| shape | recall | judged false alarms per run |
|---|---|---|
| one Opus review | 0.42 | n/a |
| second blind Opus | 0.51 | about 0.9 |
| blind GPT | 0.53 | about 0.1 |
| Sonnet critic of the Opus review | 0.53 | n/a |

GPT minus a second Opus: +0.03 recall, 90% CI -0.03 to +0.08, a tie. Giving the reviewer the whole
repo instead of the change cut one-Opus recall from 0.42 to 0.15 (partial run, 68 of 135 calls).
Synthetic bug puzzles are not a usable benchmark here: Opus alone scored 0.97 on them.

## Harness comparison (same model, Sonnet 5.5)

| suite | Claude Code | Pi | OMP |
|---|---|---|---|
| 10 short tasks, n=3 | 30/30 | 30/30 | 29/30 |
| 5 harder tasks, pooled over two runs | 20/30 | 23/30 | 20/30 |

All three tie within 90% intervals on the harder suite. Pi sent about 12k context tokens per
task against about 93k for Claude Code, and took about 30% less wall time. Claude Code was the
only harness with no crash or stall across 120 capability runs (Pi 1, OMP 3).

## Local CPU per headless task

Pi about 0.4 CPU-s, Claude Code as configured about 3.9, Claude Code with `--bare` about the
same as Pi, OMP heaviest. Small n (3 headless reps), one busy laptop on battery.
