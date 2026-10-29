"""Storage backends behind one interface.

``open_repository(path)`` picks the backend from the path:

* ``:memory:``                         JSON backend kept only in memory
* ``sqlite::memory:``                  SQLite in-memory database
* ``*.db``, ``*.sqlite``, ``*.sqlite3``  SQLite file (stdlib ``sqlite3``)
* anything else                        JSON file

Both backends implement ``trellis.storage.base.Repository`` and must behave
identically: same results, same ordering, same commit/rollback semantics.
``tests/test_storage.py`` runs every storage test against both.
"""

from trellis.storage.base import Repository
from trellis.storage.jsonfile import JsonFileRepository
from trellis.storage.sqlite import SqliteRepository

SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")


def backend_for(path):
    path = str(path)
    if path == ":memory:":
        return "json"
    if path == "sqlite::memory:":
        return "sqlite"
    if path.lower().endswith(SQLITE_SUFFIXES):
        return "sqlite"
    return "json"


def open_repository(path):
    path = str(path)
    if backend_for(path) == "sqlite":
        return SqliteRepository(":memory:" if path == "sqlite::memory:" else path)
    return JsonFileRepository(None if path == ":memory:" else path)


__all__ = ["Repository", "JsonFileRepository", "SqliteRepository", "open_repository", "backend_for"]
