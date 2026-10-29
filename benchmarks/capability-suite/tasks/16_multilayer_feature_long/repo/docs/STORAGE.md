# Storage

Two backends implement `trellis.storage.base.Repository`:

| backend | chosen for | module |
|---|---|---|
| JSON file | any other path; `:memory:` | `storage/jsonfile.py` |
| SQLite | `*.db`, `*.sqlite`, `*.sqlite3`; `sqlite::memory:` | `storage/sqlite.py` |

They must be indistinguishable through the interface: the same objects, in
the same order, with the same transaction semantics.  `trellis.transfer.dump`
returns a backend-neutral snapshot; `tests/test_storage.py` runs every test
against both backends and compares dumps.

## Transactions

Changes are provisional until `commit()`.  `rollback()` returns the
repository to the state of the last commit, including issue numbers
(`project.next_number`), the comment-id counter, audit events and any
secondary index a backend keeps.

* JSON: the whole state (dicts plus the assignee index) is snapshotted on
  commit and restored on rollback.  `commit()` rewrites the file atomically.
* SQLite: the repository issues `BEGIN` before its first write and
  `COMMIT`/`ROLLBACK` itself.  It keeps a cache of Issue objects (see the
  module docstring); `save_issue`/`delete_issue` keep it current and
  rollback empties it.  Because reads are served from that cache, a column
  that `save_issue` forgets to write will *look* saved until the database
  is reopened.

## Versions

The JSON format version is the document's `version` key; the SQLite schema
version is `PRAGMA user_version`.  The two are kept in step: version N of
one stores exactly the data of version N of the other.

| version | change |
|---|---|
| 1 | trellis 0.5: tags as a comma string, `deadline`, embedded comments (JSON), roles reader/writer/owner |
| 2 | `labels` list / `issue_labels` table, `watchers`, top-level comments with ids, roles viewer/member/admin |
| 3 | `deadline` -> `due`, `estimate`, event `actor` |
| 4 | project `archived` and `lead`, user `active` (current) |

Opening older data upgrades it step by step:

* JSON: `json_migrations.migrate` upgrades the document in memory; the file
  on disk is untouched until the next commit, which writes the current
  version.  `trellis db upgrade` forces that write.
* SQLite: `sqlite_migrations.upgrade` runs every step in one transaction
  when the database is opened, then stamps the new `user_version`.
* Data *newer* than this trellis understands is refused with a
  `StorageError`; it is never rewritten.

Adding a version means: bump `FORMAT_VERSION` and add a `MIGRATIONS` step in
`json_migrations.py`; bump `SCHEMA_VERSION`, change `CURRENT_SCHEMA` and
add a `MIGRATIONS` step in `sqlite_migrations.py` (a fresh database and an
upgraded one must end with identical tables and columns); update the codec
and the SQLite column list; add fixture files of the previous version to
`tests/data/` (`legacy_vN.json` / `legacy_vN.db`, all holding the same data).
