# Architecture

```
cli/            argparse tree (parser.py) and handlers (commands_*.py)
  |
services/       Tracker = UsersMixin + ProjectsMixin + IssuesMixin + CommentsMixin
  |               + BulkMixin + QueriesMixin + TrackerBase
  |             views.py: cached ordered lists of open issues (IssueViews)
  |
query/          lexer -> parser -> ast -> compiler (fields.py: the field table)
storage/        base.Repository; jsonfile.JsonFileRepository; sqlite.SqliteRepository
                codec.py (model <-> dict), json_migrations.py, sqlite_migrations.py
models.py       frozen dataclasses (User, Project, Membership, Issue, Comment, AuditEvent)
validation.py   check_* / normalize_* functions
workflow.py     the status machine
permissions.py  role table
dates.py        calendar-date arithmetic (no time zones)
audit.py        AuditLog and format_event
export.py       CSV / JSON / text output;   importer.py: CSV import
report.py       `trellis report NAME`
notify/         digest (what a user should hear about) and its cursor file
checks.py       `trellis db check`;   transfer.py: `trellis db copy`, dump()
timeline.py     `show --timeline`;    stats.py: lead / cycle time
config.py       ~/.trellisrc
```

## Rules of the road

* Only `services` changes a repository.  Every public mutating method is
  wrapped in `services.base.transactional`: it commits on success, and on
  any exception rolls the repository back and clears the cached views.
* Every mutating method records audit events (see the table in
  `audit.py`).  Event details are part of the interface: scripts and the
  digest read them.  When a new optional detail is added, existing events
  must look exactly as before (add the key only when it has a value).
* Both storage backends implement the same interface and must give the
  same answers in the same order, including after a rollback.
  `tests/test_storage.py` runs its tests against both, and
  `trellis.transfer.dump` gives a backend-neutral snapshot to compare.
* A model field that is stored needs: the dataclass field (with a
  default, so old code paths keep working), the codec (both directions),
  the JSON format (a new format version + a migration step), the SQLite
  schema (`CURRENT_SCHEMA` *and* a migration step), and the SQLite
  repository's column list.
* Output formats only ever grow: new CSV columns and JSON keys are
  appended at the end.
* `services/views.py` caches Issue objects.  Read its docstring before
  adding a field that any view consumer displays.

## Time

Timestamps are UTC strings (`clock.py`).  Dates (due dates and everything
computed from them) are plain calendar dates; "today" is the date part of
the clock.  There is no time-zone or daylight-saving handling anywhere,
by design: see `dates.py`.
