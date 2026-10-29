"""Where each user's last digest stopped.

Digest cursors are not part of the tracker's data (reading a digest must
not need write permission), so they live in a small sidecar JSON file next
to the database: ``<db>.digest.json``, mapping username -> last seen event
seq.  An in-memory database keeps cursors in memory.
"""

import json
import os

_MEMORY = {}


def cursor_path(db_path):
    if db_path in (None, ":memory:", "sqlite::memory:"):
        return None
    return os.fspath(db_path) + ".digest.json"


def _read(path):
    if path is None:
        return dict(_MEMORY)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {str(k): int(v) for k, v in data.items()}


def load_cursor(db_path, username):
    return _read(cursor_path(db_path)).get(username, 0)


def save_cursor(db_path, username, seq):
    path = cursor_path(db_path)
    data = _read(path)
    data[username] = int(seq)
    if path is None:
        _MEMORY.clear()
        _MEMORY.update(data)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
