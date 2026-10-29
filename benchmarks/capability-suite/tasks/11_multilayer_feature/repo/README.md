# stockroom

A small inventory and order tracker for a workshop stockroom.  Python 3.12,
standard library only.

    python3 -m stockroom add BOLT-0042 "Hex bolt M6" --qty 120 --price 0.15 --location A1
    python3 -m stockroom order place BOLT-0042 30 --customer "Line 3"
    python3 -m stockroom list --where 'qty < 50 or loc ~ a'
    python3 -m stockroom export items --format json

Layout:

| module | role |
|---|---|
| `stockroom/models.py` | frozen dataclasses: Item, Order, AuditEvent |
| `stockroom/storage/` | Repository interface; memory and JSON-file backends |
| `stockroom/query/` | the `--where` filter language (lexer, parser, compiler) |
| `stockroom/validation.py`, `services.py` | business rules |
| `stockroom/audit.py` | audit trail |
| `stockroom/export.py`, `report.py`, `table.py` | CSV / JSON / text output, CSV import |
| `stockroom/cli.py` | argparse front end |

The JSON data file format is documented, with its version history, in
`stockroom/storage/jsonfile.py`.  Run the tests with `python3 -m pytest -q`.
