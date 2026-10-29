# tsarc

Columnar time-series archives: a small library and CLI that field and lab
stations use to store sensor tables (`ts` time column plus typed value
columns) and the tooling around them. Python 3.12, standard library only.

```
python3 -m tsarc info FILE
python3 -m tsarc import CSV OUT [--schema S] [--meta k=v]... [--format-version V]
python3 -m tsarc export FILE [--format csv|jsonl]
python3 -m tsarc query FILE [--start T] [--end T] [--where EXPR] [--columns C,...]
python3 -m tsarc stats FILE
python3 -m tsarc verify FILE...
python3 -m tsarc convert SRC DST --format-version V
```

and more: `python3 -m tsarc --help` and the docstring of `tsarc/cli.py`.

Library:

```python
from tsarc import Schema, Table, write_archive, open_archive, read_table
```

## Layout

- `tsarc/schema.py`, `tsarc/types.py`, `tsarc/table.py`: schemas, value types, in-memory tables
- `tsarc/archive.py`: reader / writer API, dispatching to `tsarc/codec/v<N>.py`
- `tsarc/codec/`: one module per on-disk format version
- `tsarc/encoding/`: shared low-level encodings
- `tsarc/expr/`: the filter expression language (`docs/EXPRESSIONS.md`)
- `tsarc/ops/`: resample, merge, dedupe, rolling, gaps, joins, ...
- `tsarc/csvio.py`, `tsarc/jsonio.py`: CSV and JSON Lines
- `tsarc/stats.py`, `tsarc/info.py`, `tsarc/verify.py`, `tsarc/cli.py`

## Formats

- `docs/FORMAT_v1.md`: version 1, row-oriented (legacy, still written on request)
- `docs/FORMAT_v2.md`: version 2, columnar (the current default)
- `docs/FORMAT_v3.md`: version 3, chunked columnar (agreed, not yet implemented)

Tests: `python3 -m pytest -q`.
