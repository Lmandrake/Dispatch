"""Plain data: frozen dataclasses for everything trellis stores.

Objects are immutable; services build changed copies with
``dataclasses.replace`` and hand them to the repository.  Tuples (not lists)
hold multi-valued fields so that instances stay hashable and comparable.

Vocabulary
----------
* roles, weakest first: ``viewer`` < ``member`` < ``admin`` (per project;
  see ``trellis.permissions``)
* issue statuses: ``open``, ``in_progress``, ``review``, ``blocked`` are
  *open*; ``done`` and ``wontfix`` are *closed* (see ``trellis.workflow``)
* priorities, lowest first: ``low``, ``normal``, ``high``, ``urgent``
* issue types: ``bug``, ``task``, ``story``, ``chore``
"""

from dataclasses import dataclass, field

ROLES = ("viewer", "member", "admin")

STATUSES = ("open", "in_progress", "review", "blocked", "done", "wontfix")
OPEN_STATUSES = ("open", "in_progress", "review", "blocked")
CLOSED_STATUSES = ("done", "wontfix")

PRIORITIES = ("low", "normal", "high", "urgent")
TYPES = ("bug", "task", "story", "chore")


def role_rank(role):
    """0 for viewer, 1 for member, 2 for admin; -1 for anything else."""
    try:
        return ROLES.index(role)
    except ValueError:
        return -1


def priority_rank(priority):
    """0 for low ... 3 for urgent."""
    return PRIORITIES.index(priority)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    email: str = ""
    active: bool = True
    created_at: str = ""


@dataclass(frozen=True)
class Project:
    key: str
    name: str
    description: str = ""
    lead: str = ""
    archived: bool = False
    next_number: int = 1
    created_at: str = ""


@dataclass(frozen=True)
class Membership:
    project: str
    username: str
    role: str


@dataclass(frozen=True)
class Issue:
    project: str
    number: int
    title: str
    description: str = ""
    type: str = "task"
    status: str = "open"
    priority: str = "normal"
    reporter: str = ""
    assignee: str = ""
    labels: tuple = ()
    watchers: tuple = ()
    due: str = ""
    estimate: int | None = None
    created_at: str = ""
    updated_at: str = ""
    closed_at: str = ""

    @property
    def key(self):
        return f"{self.project}-{self.number}"

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def is_closed(self):
        return self.status in CLOSED_STATUSES


@dataclass(frozen=True)
class Comment:
    id: int
    issue: str
    author: str
    body: str
    created_at: str = ""


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    timestamp: str
    actor: str
    action: str
    subject: str
    details: dict = field(default_factory=dict)


def issue_key_parts(key):
    """Split ``"WEB-12"`` into ``("WEB", 12)``.  Raises ValueError."""
    project, sep, number = key.rpartition("-")
    if not sep or not project or not number.isdigit():
        raise ValueError(f"not an issue key: {key!r}")
    return project, int(number)
