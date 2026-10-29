"""The storage interface.

A repository holds users, projects, memberships, issues, comments and the
audit trail.  Repositories know nothing about permissions or business
rules; ``trellis.services`` is the only code that should change one.

Transactions
------------
Every change is provisional until ``commit()``.  ``rollback()`` throws away
everything since the last commit (or since opening), including issue
numbers handed out, comments and audit events.  After a rollback every
read must return exactly what it returned right after the last commit.

Ordering
--------
* ``list_users``        by username
* ``list_projects``     by key
* ``list_memberships``  by (project, username)
* ``list_issues``       by (project, number) -- numeric, so WEB-2 < WEB-10
* ``list_comments``     by id
* ``list_events``       by seq

Returned objects are immutable model instances; multi-valued issue fields
(``labels``, ``watchers``) are sorted tuples.
"""

from abc import ABC, abstractmethod


class Repository(ABC):
    #: "json" or "sqlite"
    backend = "?"

    # ---- users ---------------------------------------------------------
    @abstractmethod
    def get_user(self, username): ...

    @abstractmethod
    def save_user(self, user): ...

    @abstractmethod
    def list_users(self): ...

    # ---- projects ------------------------------------------------------
    @abstractmethod
    def get_project(self, key): ...

    @abstractmethod
    def save_project(self, project): ...

    @abstractmethod
    def list_projects(self): ...

    # ---- memberships ---------------------------------------------------
    @abstractmethod
    def get_membership(self, project, username): ...

    @abstractmethod
    def save_membership(self, membership): ...

    @abstractmethod
    def delete_membership(self, project, username): ...

    @abstractmethod
    def list_memberships(self, project=None, username=None): ...

    # ---- issues --------------------------------------------------------
    @abstractmethod
    def get_issue(self, project, number): ...

    @abstractmethod
    def save_issue(self, issue): ...

    @abstractmethod
    def delete_issue(self, project, number): ...

    @abstractmethod
    def list_issues(self, project=None): ...

    def get_issue_by_key(self, key):
        project, _, number = key.rpartition("-")
        if not number.isdigit():
            return None
        return self.get_issue(project, int(number))

    def issues_assigned_to(self, username):
        return [i for i in self.list_issues() if i.assignee == username]

    # ---- comments ------------------------------------------------------
    @abstractmethod
    def next_comment_id(self):
        """Hand out the next comment id (and advance the counter)."""

    @abstractmethod
    def peek_comment_id(self):
        """The id ``next_comment_id`` would hand out, without advancing."""

    @abstractmethod
    def set_comment_id(self, value):
        """Set the counter (used when copying a database)."""

    @abstractmethod
    def add_comment(self, comment): ...

    @abstractmethod
    def list_comments(self, issue_key=None): ...

    @abstractmethod
    def delete_comments(self, issue_key): ...

    # ---- audit trail ---------------------------------------------------
    @abstractmethod
    def append_event(self, event): ...

    @abstractmethod
    def list_events(self): ...

    def last_event_seq(self):
        events = self.list_events()
        return events[-1].seq if events else 0

    # ---- transactions --------------------------------------------------
    @abstractmethod
    def commit(self): ...

    @abstractmethod
    def rollback(self): ...

    def close(self):
        pass

    # ---- introspection -------------------------------------------------
    @property
    @abstractmethod
    def schema_version(self):
        """The schema / format version of the data as stored *now* (after
        any upgrade done when opening)."""

    @property
    def opened_version(self):
        """The version the data had when it was opened (before upgrade)."""
        return self.schema_version
