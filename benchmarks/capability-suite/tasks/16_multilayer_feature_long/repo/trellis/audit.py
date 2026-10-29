"""The audit trail.

Every successful mutating service call records audit events through
``AuditLog.record``; a call that fails records nothing (the transaction is
rolled back).  Events live in the repository and are numbered consecutively
from 1.  ``actor`` is the username that performed the change.

Actions, with their ``details`` keys:

======================  ======================================================
action                  details
======================  ======================================================
user.created            display_name, email
user.deactivated        (none)
user.reactivated        (none)
project.created         name
project.updated         changes: {field: [old, new]}
project.archived        (none)
project.unarchived      (none)
member.added            username, role
member.role_changed     username, old, new
member.removed          username
issue.created           title, type, priority, plus assignee / due / labels /
                        estimate only when set, and imported: true for rows
                        that came from ``import``
issue.updated           changes: {field: [old, new]}
issue.transitioned      from, to
issue.assigned          from, to   ("" for nobody)
issue.labeled           added: [labels]
issue.unlabeled         removed: [labels]
issue.watched           username
issue.unwatched         username
issue.deleted           title
comment.added           id, plus mentions: [usernames] when there are any
======================  ======================================================

Subjects are usernames for ``user.*``, project keys for ``project.*`` and
``member.*``, and issue keys (``WEB-12``) for ``issue.*`` and ``comment.*``.
"""

from trellis.clock import utc_now
from trellis.models import AuditEvent


class AuditLog:
    def __init__(self, repo, clock=utc_now):
        self.repo = repo
        self.clock = clock

    def record(self, actor, action, subject, **details):
        seq = self.repo.last_event_seq() + 1
        event = AuditEvent(seq=seq, timestamp=self.clock(), actor=actor, action=action,
                           subject=subject, details=details)
        self.repo.append_event(event)
        return event

    def events(self, subject=None, action=None, actor=None, since_seq=0, project=None):
        """Events filtered by exact subject, by action (exact, or a prefix
        ending in ``.`` such as ``"issue."``), by actor, by ``seq > since_seq``
        and by project (events whose subject is the project key or one of
        its issue keys)."""
        out = []
        for ev in self.repo.list_events():
            if ev.seq <= since_seq:
                continue
            if subject is not None and ev.subject != subject:
                continue
            if actor is not None and ev.actor != actor:
                continue
            if action is not None:
                if action.endswith("."):
                    if not ev.action.startswith(action):
                        continue
                elif ev.action != action:
                    continue
            if project is not None and not _in_project(ev, project):
                continue
            out.append(ev)
        return out


def _in_project(event, project):
    if event.action.startswith(("project.", "member.")):
        return event.subject == project
    if event.action.startswith(("issue.", "comment.")):
        return event.subject.rpartition("-")[0] == project
    return False


def _fmt_value(value):
    if isinstance(value, list):
        return "[" + ", ".join(repr(v) for v in value) + "]"
    return repr(value)


def format_event(event):
    """One-line human rendering used by ``trellis history``."""
    parts = []
    for key in sorted(event.details):
        value = event.details[key]
        if isinstance(value, dict):
            inner = ", ".join(
                f"{k}: {_fmt_value(v[0])} -> {_fmt_value(v[1])}"
                if isinstance(v, (list, tuple)) and len(v) == 2 else f"{k}: {_fmt_value(v)}"
                for k, v in sorted(value.items()))
            parts.append(f"{key}={{{inner}}}")
        else:
            parts.append(f"{key}={_fmt_value(value)}")
    tail = (" " + " ".join(parts)) if parts else ""
    return f"#{event.seq} {event.timestamp} {event.actor} {event.action} {event.subject}{tail}"
