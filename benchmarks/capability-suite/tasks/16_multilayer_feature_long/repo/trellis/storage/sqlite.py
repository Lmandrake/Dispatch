"""SQLite repository (stdlib ``sqlite3``).

The connection runs in autocommit mode (``isolation_level=None``) and the
repository manages transactions itself: the first write after a commit or
rollback issues ``BEGIN``; ``commit()`` / ``rollback()`` end it.  Reads
inside an open transaction see its uncommitted writes, exactly like the
JSON backend's in-memory state.

Multi-valued issue fields live in side tables (``issue_labels``,
``issue_watchers``); ``save_issue`` rewrites them.  The next comment id is
kept in the ``meta`` table so that it rolls back with everything else.

Row cache
---------
Reading an issue takes three queries, and the services read the same few
issues over and over inside one command, so ``get_issue`` keeps a small
cache of Issue objects by (project, number).  ``save_issue`` and
``delete_issue`` update it and ``rollback`` empties it.  Anything that
writes the ``issues`` table or its side tables must go through those
methods (or clear the cache) or reads will go stale.
"""

import json
import os
import sqlite3

from trellis.errors import StorageError
from trellis.models import AuditEvent, Comment, Issue, Membership, Project, User
from trellis.storage import codec
from trellis.storage.base import Repository
from trellis.storage.sqlite_migrations import SCHEMA_VERSION, upgrade

_ISSUE_COLUMNS = ("project", "number", "title", "description", "type", "status", "priority",
                  "reporter", "assignee", "due", "created_at", "updated_at", "closed_at",
                  "estimate")


class SqliteRepository(Repository):
    backend = "sqlite"

    def __init__(self, path=":memory:"):
        self.path = os.fspath(path)
        try:
            self.conn = sqlite3.connect(self.path, isolation_level=None)
        except sqlite3.Error as exc:
            raise StorageError(f"cannot open {self.path}: {exc}") from None
        self.conn.row_factory = sqlite3.Row
        try:
            self._opened_version = upgrade(self.conn)
        except sqlite3.DatabaseError as exc:
            self.conn.close()
            raise StorageError(f"cannot open {self.path}: {exc}") from None
        except StorageError:
            self.conn.close()
            raise
        if self._opened_version == 0:
            self._opened_version = SCHEMA_VERSION
        self._in_tx = False
        self._issue_cache = {}

    # ---- plumbing --------------------------------------------------------
    def _write(self, sql, params=()):
        if not self._in_tx:
            self.conn.execute("BEGIN")
            self._in_tx = True
        try:
            return self.conn.execute(sql, params)
        except sqlite3.Error as exc:
            raise StorageError(f"database error: {exc}") from None

    def _read(self, sql, params=()):
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"database error: {exc}") from None

    def close(self):
        if self._in_tx:
            self.rollback()
        self.conn.close()

    # ---- users -----------------------------------------------------------
    @staticmethod
    def _user(row):
        return User(username=row["username"], display_name=row["display_name"],
                    email=row["email"], active=bool(row["active"]), created_at=row["created_at"])

    def get_user(self, username):
        rows = self._read("SELECT * FROM users WHERE username = ?", (username,))
        return self._user(rows[0]) if rows else None

    def save_user(self, user):
        self._write(
            "INSERT INTO users (username, display_name, email, created_at, active) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(username) DO UPDATE SET "
            "display_name = excluded.display_name, email = excluded.email, "
            "created_at = excluded.created_at, active = excluded.active",
            (user.username, user.display_name, user.email, user.created_at, int(user.active)),
        )

    def list_users(self):
        return [self._user(r) for r in self._read("SELECT * FROM users ORDER BY username")]

    # ---- projects --------------------------------------------------------
    @staticmethod
    def _project(row):
        return Project(key=row["key"], name=row["name"], description=row["description"],
                       lead=row["lead"], archived=bool(row["archived"]),
                       next_number=row["next_number"], created_at=row["created_at"])

    def get_project(self, key):
        rows = self._read("SELECT * FROM projects WHERE key = ?", (key,))
        return self._project(rows[0]) if rows else None

    def save_project(self, project):
        self._write(
            "INSERT INTO projects (key, name, description, next_number, created_at, archived, lead) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "name = excluded.name, description = excluded.description, "
            "next_number = excluded.next_number, created_at = excluded.created_at, "
            "archived = excluded.archived, lead = excluded.lead",
            (project.key, project.name, project.description, project.next_number,
             project.created_at, int(project.archived), project.lead),
        )

    def list_projects(self):
        return [self._project(r) for r in self._read("SELECT * FROM projects ORDER BY key")]

    # ---- memberships -----------------------------------------------------
    @staticmethod
    def _membership(row):
        return Membership(project=row["project"], username=row["username"], role=row["role"])

    def get_membership(self, project, username):
        rows = self._read("SELECT * FROM memberships WHERE project = ? AND username = ?",
                          (project, username))
        return self._membership(rows[0]) if rows else None

    def save_membership(self, m):
        self._write(
            "INSERT INTO memberships (project, username, role) VALUES (?, ?, ?) "
            "ON CONFLICT(project, username) DO UPDATE SET role = excluded.role",
            (m.project, m.username, m.role),
        )

    def delete_membership(self, project, username):
        self._write("DELETE FROM memberships WHERE project = ? AND username = ?", (project, username))

    def list_memberships(self, project=None, username=None):
        sql = "SELECT * FROM memberships"
        where, params = [], []
        if project is not None:
            where.append("project = ?")
            params.append(project)
        if username is not None:
            where.append("username = ?")
            params.append(username)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY project, username"
        return [self._membership(r) for r in self._read(sql, params)]

    # ---- issues ----------------------------------------------------------
    def _issue_from_row(self, row):
        project, number = row["project"], row["number"]
        labels = [r[0] for r in self._read(
            "SELECT label FROM issue_labels WHERE project = ? AND number = ? ORDER BY label",
            (project, number))]
        watchers = [r[0] for r in self._read(
            "SELECT username FROM issue_watchers WHERE project = ? AND number = ? ORDER BY username",
            (project, number))]
        return codec.issue_from_dict(dict(row), labels=labels, watchers=watchers)

    def get_issue(self, project, number):
        key = (project, number)
        if key in self._issue_cache:
            return self._issue_cache[key]
        rows = self._read("SELECT * FROM issues WHERE project = ? AND number = ?", key)
        issue = self._issue_from_row(rows[0]) if rows else None
        if issue is not None:
            self._issue_cache[key] = issue
        return issue

    def save_issue(self, issue):
        d = codec.issue_to_dict(issue)
        values = [d[c] for c in _ISSUE_COLUMNS]
        placeholders = ", ".join("?" for _ in _ISSUE_COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _ISSUE_COLUMNS[2:])
        self._write(
            f"INSERT INTO issues ({', '.join(_ISSUE_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(project, number) DO UPDATE SET {updates}",
            values,
        )
        key = (issue.project, issue.number)
        self._write("DELETE FROM issue_labels WHERE project = ? AND number = ?", key)
        for label in issue.labels:
            self._write("INSERT INTO issue_labels VALUES (?, ?, ?)", (*key, label))
        self._write("DELETE FROM issue_watchers WHERE project = ? AND number = ?", key)
        for username in issue.watchers:
            self._write("INSERT INTO issue_watchers VALUES (?, ?, ?)", (*key, username))
        self._issue_cache[key] = issue

    def delete_issue(self, project, number):
        key = (project, number)
        self._write("DELETE FROM issues WHERE project = ? AND number = ?", key)
        self._write("DELETE FROM issue_labels WHERE project = ? AND number = ?", key)
        self._write("DELETE FROM issue_watchers WHERE project = ? AND number = ?", key)
        self._issue_cache.pop(key, None)

    def list_issues(self, project=None):
        if project is None:
            rows = self._read("SELECT * FROM issues ORDER BY project, number")
        else:
            rows = self._read("SELECT * FROM issues WHERE project = ? ORDER BY number", (project,))
        out = []
        for row in rows:
            key = (row["project"], row["number"])
            issue = self._issue_cache.get(key)
            if issue is None:
                issue = self._issue_from_row(row)
                self._issue_cache[key] = issue
            out.append(issue)
        return out

    def issues_assigned_to(self, username):
        rows = self._read("SELECT project, number FROM issues WHERE assignee = ? "
                          "ORDER BY project, number", (username,))
        return [self.get_issue(r["project"], r["number"]) for r in rows]

    # ---- comments --------------------------------------------------------
    def next_comment_id(self):
        cid = self.peek_comment_id()
        self.set_comment_id(cid + 1)
        return cid

    def peek_comment_id(self):
        rows = self._read("SELECT value FROM meta WHERE key = 'next_comment_id'")
        return int(rows[0][0]) if rows else 1

    def set_comment_id(self, value):
        self._write("INSERT INTO meta (key, value) VALUES ('next_comment_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(int(value)),))

    def add_comment(self, c):
        self._write("INSERT INTO comments (id, issue, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
                    (c.id, c.issue, c.author, c.body, c.created_at))

    def list_comments(self, issue_key=None):
        if issue_key is None:
            rows = self._read("SELECT * FROM comments ORDER BY id")
        else:
            rows = self._read("SELECT * FROM comments WHERE issue = ? ORDER BY id", (issue_key,))
        return [Comment(id=r["id"], issue=r["issue"], author=r["author"], body=r["body"],
                        created_at=r["created_at"]) for r in rows]

    def delete_comments(self, issue_key):
        self._write("DELETE FROM comments WHERE issue = ?", (issue_key,))

    # ---- events ----------------------------------------------------------
    def append_event(self, e):
        self._write(
            "INSERT INTO events (seq, timestamp, action, subject, details, actor) VALUES (?, ?, ?, ?, ?, ?)",
            (e.seq, e.timestamp, e.action, e.subject, json.dumps(e.details, sort_keys=True), e.actor),
        )

    def list_events(self):
        rows = self._read("SELECT * FROM events ORDER BY seq")
        return [AuditEvent(seq=r["seq"], timestamp=r["timestamp"], actor=r["actor"],
                           action=r["action"], subject=r["subject"],
                           details=json.loads(r["details"])) for r in rows]

    def last_event_seq(self):
        rows = self._read("SELECT COALESCE(MAX(seq), 0) FROM events")
        return rows[0][0]

    # ---- transactions ----------------------------------------------------
    def commit(self):
        if self._in_tx:
            try:
                self.conn.execute("COMMIT")
            except sqlite3.Error as exc:
                raise StorageError(f"cannot commit: {exc}") from None
            self._in_tx = False

    def rollback(self):
        if self._in_tx:
            self.conn.execute("ROLLBACK")
            self._in_tx = False
        self._issue_cache.clear()

    @property
    def schema_version(self):
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    @property
    def opened_version(self):
        return self._opened_version

    def table_columns(self, table):
        """``[(name, declared_type, notnull, default), ...]`` for ``table``."""
        return [(r["name"], r["type"], r["notnull"], r["dflt_value"])
                for r in self._read(f"PRAGMA table_info({table})")]

    def table_names(self):
        return sorted(r[0] for r in self._read(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"))
