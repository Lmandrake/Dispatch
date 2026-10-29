"""JSON-file repository.

The whole database is one JSON document (current format, version 4)::

    {
      "format": "trellis",
      "version": 4,
      "next_comment_id": 7,
      "users":       [ {username, display_name, email, active, created_at}, ... ],
      "projects":    [ {key, name, description, lead, archived, next_number, created_at}, ... ],
      "memberships": [ {project, username, role}, ... ],
      "issues":      [ {project, number, title, ..., labels: [...], watchers: [...], ...}, ... ],
      "comments":    [ {id, issue, author, body, created_at}, ... ],
      "events":      [ {seq, timestamp, actor, action, subject, details}, ... ]
    }

Lists are written in the repository's canonical order (see
``trellis.storage.base``).  The file is read once when the repository is
opened; changes are kept in memory and written back atomically (temp file
plus rename) on ``commit()``.  ``rollback()`` restores the state of the last
commit.  Older formats are upgraded in memory by
``trellis.storage.json_migrations`` and written back in the current format
on the next commit; the file on disk is not touched until then.

``JsonFileRepository(None)`` keeps everything in memory only (``--db
:memory:``); commit then just takes the snapshot.

The repository keeps a secondary index of issue keys by assignee so that
``issues_assigned_to`` does not scan every issue.  The index is part of the
snapshot, so rollback restores it too.
"""

import json
import os
import tempfile

from trellis.errors import StorageError
from trellis.storage import codec
from trellis.storage.base import Repository
from trellis.storage.json_migrations import FORMAT_NAME, FORMAT_VERSION, migrate


class JsonFileRepository(Repository):
    backend = "json"

    def __init__(self, path=None):
        self.path = None if path is None else os.fspath(path)
        self._opened_version = FORMAT_VERSION
        self._reset()
        if self.path is not None and os.path.exists(self.path):
            self._load()
        self._snapshot = self._take_snapshot()

    # ---- state ---------------------------------------------------------
    def _reset(self):
        self._users = {}
        self._projects = {}
        self._memberships = {}
        self._issues = {}
        self._comments = {}
        self._events = []
        self._next_comment_id = 1
        self._by_assignee = {}

    def _take_snapshot(self):
        return (
            dict(self._users),
            dict(self._projects),
            dict(self._memberships),
            dict(self._issues),
            dict(self._comments),
            list(self._events),
            self._next_comment_id,
            {a: set(keys) for a, keys in self._by_assignee.items()},
        )

    def _restore(self, snap):
        (users, projects, memberships, issues, comments, events, next_cid, by_assignee) = snap
        self._users = dict(users)
        self._projects = dict(projects)
        self._memberships = dict(memberships)
        self._issues = dict(issues)
        self._comments = dict(comments)
        self._events = list(events)
        self._next_comment_id = next_cid
        self._by_assignee = {a: set(keys) for a, keys in by_assignee.items()}

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"cannot read {self.path}: {exc}") from None
        doc, self._opened_version = migrate(doc)
        for d in doc.get("users", []):
            u = codec.user_from_dict(d)
            self._users[u.username] = u
        for d in doc.get("projects", []):
            p = codec.project_from_dict(d)
            self._projects[p.key] = p
        for d in doc.get("memberships", []):
            m = codec.membership_from_dict(d)
            self._memberships[(m.project, m.username)] = m
        for d in doc.get("issues", []):
            i = codec.issue_from_dict(d)
            self._issues[(i.project, i.number)] = i
            self._index(i)
        for d in doc.get("comments", []):
            c = codec.comment_from_dict(d)
            self._comments[c.id] = c
        self._events = sorted((codec.event_from_dict(d) for d in doc.get("events", [])),
                              key=lambda e: e.seq)
        default_next = max([0] + list(self._comments)) + 1
        self._next_comment_id = int(doc.get("next_comment_id", default_next))

    # ---- index -----------------------------------------------------------
    def _index(self, issue):
        if issue.assignee:
            self._by_assignee.setdefault(issue.assignee, set()).add(issue.key)

    def _unindex(self, issue):
        keys = self._by_assignee.get(issue.assignee)
        if keys is not None:
            keys.discard(issue.key)
            if not keys:
                del self._by_assignee[issue.assignee]

    # ---- users -----------------------------------------------------------
    def get_user(self, username):
        return self._users.get(username)

    def save_user(self, user):
        self._users[user.username] = user

    def list_users(self):
        return [self._users[k] for k in sorted(self._users)]

    # ---- projects --------------------------------------------------------
    def get_project(self, key):
        return self._projects.get(key)

    def save_project(self, project):
        self._projects[project.key] = project

    def list_projects(self):
        return [self._projects[k] for k in sorted(self._projects)]

    # ---- memberships -----------------------------------------------------
    def get_membership(self, project, username):
        return self._memberships.get((project, username))

    def save_membership(self, membership):
        self._memberships[(membership.project, membership.username)] = membership

    def delete_membership(self, project, username):
        self._memberships.pop((project, username), None)

    def list_memberships(self, project=None, username=None):
        out = []
        for k in sorted(self._memberships):
            m = self._memberships[k]
            if project is not None and m.project != project:
                continue
            if username is not None and m.username != username:
                continue
            out.append(m)
        return out

    # ---- issues ----------------------------------------------------------
    def get_issue(self, project, number):
        return self._issues.get((project, number))

    def save_issue(self, issue):
        old = self._issues.get((issue.project, issue.number))
        if old is not None:
            self._unindex(old)
        self._issues[(issue.project, issue.number)] = issue
        self._index(issue)

    def delete_issue(self, project, number):
        old = self._issues.pop((project, number), None)
        if old is not None:
            self._unindex(old)

    def list_issues(self, project=None):
        keys = sorted(k for k in self._issues if project is None or k[0] == project)
        return [self._issues[k] for k in keys]

    def issues_assigned_to(self, username):
        out = []
        for key in self._by_assignee.get(username, ()):
            project, _, number = key.rpartition("-")
            out.append(self._issues[(project, int(number))])
        return sorted(out, key=lambda i: (i.project, i.number))

    # ---- comments --------------------------------------------------------
    def next_comment_id(self):
        cid = self._next_comment_id
        self._next_comment_id += 1
        return cid

    def peek_comment_id(self):
        return self._next_comment_id

    def set_comment_id(self, value):
        self._next_comment_id = int(value)

    def add_comment(self, comment):
        self._comments[comment.id] = comment

    def list_comments(self, issue_key=None):
        return [self._comments[k] for k in sorted(self._comments)
                if issue_key is None or self._comments[k].issue == issue_key]

    def delete_comments(self, issue_key):
        for cid in [k for k, c in self._comments.items() if c.issue == issue_key]:
            del self._comments[cid]

    # ---- events ----------------------------------------------------------
    def append_event(self, event):
        self._events.append(event)

    def list_events(self):
        return list(self._events)

    # ---- transactions ----------------------------------------------------
    def to_document(self):
        return {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "next_comment_id": self._next_comment_id,
            "users": [codec.user_to_dict(u) for u in self.list_users()],
            "projects": [codec.project_to_dict(p) for p in self.list_projects()],
            "memberships": [codec.membership_to_dict(m) for m in self.list_memberships()],
            "issues": [codec.issue_to_dict(i) for i in self.list_issues()],
            "comments": [codec.comment_to_dict(c) for c in self.list_comments()],
            "events": [codec.event_to_dict(e) for e in self.list_events()],
        }

    def commit(self):
        if self.path is not None:
            self._write(self.to_document())
        self._snapshot = self._take_snapshot()

    def _write(self, doc):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".trellis-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise StorageError(f"cannot write {self.path}: {exc}") from None

    def rollback(self):
        self._restore(self._snapshot)

    @property
    def schema_version(self):
        return FORMAT_VERSION

    @property
    def opened_version(self):
        return self._opened_version
