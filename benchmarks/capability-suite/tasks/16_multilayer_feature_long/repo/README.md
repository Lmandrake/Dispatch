# trellis

A small project and issue tracker for a team that wants its tracker in a
file next to the code.  Python 3.12, standard library only.

    python3 -m trellis user add ana "Ana Lima" --email ana@example.com
    python3 -m trellis project create WEB "Website" --lead ana
    python3 -m trellis --as ana create WEB "Login page broken" -t bug -p urgent --due +3d -l auth
    python3 -m trellis list --where 'status != done and (priority >= high or overdue)'
    python3 -m trellis board WEB
    python3 -m trellis --as ana digest
    python3 -m trellis export issues --format json

Data lives in one JSON file (`--db tracker.json`, the default is
`trellis.json`) or one SQLite database (`--db tracker.db`); both backends
behave the same.

Documentation:

| file | what |
|---|---|
| `docs/ARCHITECTURE.md` | layers, modules, where to change what |
| `docs/STORAGE.md` | the two backends, transactions, format/schema history, upgrading |
| `docs/QUERY.md` | the `--where` language |
| `docs/CLI.md` | every command and its output |
| `docs/PERMISSIONS.md` | roles and rules |
| `docs/RECURRENCE.md` | recurring issues (agreed design; not implemented yet) |

Run the tests with `python3 -m pytest -q`.
