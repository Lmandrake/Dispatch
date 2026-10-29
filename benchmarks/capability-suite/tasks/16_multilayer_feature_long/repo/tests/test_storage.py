import json
import os
import shutil
import sqlite3

import pytest

from tests.helpers import DATA, make_repo, make_tracker
from trellis.errors import StorageError
from trellis.models import Comment, Issue, Project, User
from trellis.storage import JsonFileRepository, SqliteRepository, backend_for, open_repository
from trellis.storage import json_migrations as JM
from trellis.storage import sqlite_migrations as SM
from trellis.transfer import copy_repository, dump


def test_backend_for():
    assert backend_for("x.json") == "json"
    assert backend_for("x.DB") == "sqlite"
    assert backend_for("x.sqlite3") == "sqlite"
    assert backend_for(":memory:") == "json"
    assert backend_for("sqlite::memory:") == "sqlite"


def test_roundtrip_and_ordering(backend, tmp_path):
    repo = make_repo(backend, tmp_path)
    repo.save_project(Project("WEB", "Web"))
    for n in (10, 2, 1):
        repo.save_issue(Issue("WEB", n, f"issue {n}", labels=("a", "b"), watchers=("amy", "zed")))
    repo.commit()
    assert [i.number for i in repo.list_issues()] == [1, 2, 10]
    assert repo.get_issue("WEB", 2).labels == ("a", "b")
    assert repo.get_issue("WEB", 2).watchers == ("amy", "zed")


def test_rollback_restores_everything(backend, tmp_path):
    repo = make_repo(backend, tmp_path)
    repo.save_user(User("ana", "Ana"))
    repo.save_project(Project("WEB", "Web", next_number=2))
    repo.save_issue(Issue("WEB", 1, "one", assignee="ana"))
    repo.commit()
    before = dump(repo)
    repo.save_issue(Issue("WEB", 1, "changed", assignee=""))
    repo.save_issue(Issue("WEB", 2, "two", assignee="ana"))
    repo.save_project(Project("WEB", "Web", next_number=3))
    repo.add_comment(Comment(repo.next_comment_id(), "WEB-1", "ana", "hi"))
    repo.rollback()
    assert dump(repo) == before
    assert [i.key for i in repo.issues_assigned_to("ana")] == ["WEB-1"]
    assert repo.get_issue("WEB", 1).title == "one"


def test_reopen_persists(backend, tmp_path):
    repo = make_repo(backend, tmp_path)
    t, _ = make_tracker(repo)
    t.create_issue("WEB", "Persist me", due="2026-06-01", labels=["x"], estimate=5)
    snapshot = dump(repo)
    repo.close()
    again = open_repository(tmp_path / ("t.json" if backend == "json" else "t.db"))
    assert dump(again) == snapshot


def test_backends_identical_after_same_operations(tmp_path):
    dumps = []
    for kind in ("json", "sqlite"):
        repo = make_repo(kind)
        t, clock = make_tracker(repo)
        t.create_issue("WEB", "A", assignee="bob", due="2026-05-10", labels=["ui"])
        clock.advance(60)
        t.as_user("bob").transition("WEB-1", "in_progress")
        t.add_comment("WEB-1", "note @bob")
        with pytest.raises(Exception):
            t.bulk_transition(["WEB-1", "WEB-99"], "done")
        dumps.append(dump(repo))
    assert dumps[0] == dumps[1]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("ext", ["json", "db"])
def test_legacy_files_open(tmp_path, version, ext):
    repo = _legacy_copy(tmp_path, version, ext)
    assert repo.opened_version == version
    assert repo.schema_version == JM.FORMAT_VERSION == SM.SCHEMA_VERSION
    issues = {i.key: i for i in repo.list_issues()}
    assert sorted(issues) == ["OPS-1", "WEB-1", "WEB-2", "WEB-3"]
    assert issues["WEB-1"].labels == ("auth", "ui")
    assert issues["OPS-1"].labels == ("backups", "ops")
    assert issues["WEB-3"].due == "2025-02-01"
    assert repo.get_membership("WEB", "cyd").role == "viewer"
    assert [c.id for c in repo.list_comments()] == [1, 2, 3]
    assert repo.peek_comment_id() == 4


def _legacy_copy(tmp_path, version, ext):
    """Open a *copy*: SQLite upgrades a database in place when it is opened."""
    path = tmp_path / f"legacy_v{version}.{ext}"
    shutil.copy(os.path.join(DATA, f"legacy_v{version}.{ext}"), path)
    return open_repository(path)


def test_all_legacy_versions_hold_the_same_data(tmp_path):
    dumps = [dump(_legacy_copy(tmp_path, v, ext)) for v in (1, 2, 3, 4) for ext in ("json", "db")]
    assert all(d == dumps[0] for d in dumps)


def test_json_old_file_untouched_until_commit(tmp_path):
    path = tmp_path / "old.json"
    shutil.copy(os.path.join(DATA, "legacy_v1.json"), path)
    raw = path.read_bytes()
    repo = JsonFileRepository(path)
    assert path.read_bytes() == raw
    repo.commit()
    assert json.loads(path.read_text())["version"] == JM.FORMAT_VERSION


def test_newer_versions_refused(tmp_path):
    p = tmp_path / "future.json"
    p.write_text(json.dumps({"format": "trellis", "version": JM.FORMAT_VERSION + 1}))
    with pytest.raises(StorageError, match="only understands"):
        JsonFileRepository(p)
    db = tmp_path / "future.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE x (a)")
    conn.execute(f"PRAGMA user_version = {SM.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(StorageError, match="only understands"):
        SqliteRepository(str(db))


def test_upgraded_sqlite_schema_matches_fresh(tmp_path):
    path = tmp_path / "old.db"
    shutil.copy(os.path.join(DATA, "legacy_v1.db"), path)
    old = SqliteRepository(str(path))
    fresh = SqliteRepository(":memory:")
    assert old.table_names() == fresh.table_names()
    for table in fresh.table_names():
        assert old.table_columns(table) == fresh.table_columns(table), table


def test_copy_json_to_sqlite(tmp_path):
    src = _legacy_copy(tmp_path, 2, "json")
    dst = open_repository(tmp_path / "copy.db")
    assert copy_repository(src, dst) == dump(src)
